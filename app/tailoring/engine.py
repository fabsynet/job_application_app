"""Tailoring orchestration engine (TAIL-01, TAIL-03, TAIL-04, SAFE-04).

Hooks together:

1. **PII stripping** (:func:`strip_pii_sections`) — pulls the contact
   header off the parsed resume sections so name, email, phone, address
   never enter the LLM prompt (SAFE-04).
2. **Tailoring call** — extractive-only prompt with intensity, cached
   system prefix, structured JSON output.
3. **LLM-as-judge validation** — second Claude call compares tailored
   output to the original and flags invented content.
4. **Auto-retry with escalation** — up to ``max_retries`` attempts, the
   tailoring prompt gets more conservative each time while the validator
   stays constant (research Pitfall 4).
5. **Cover letter** — one more call once tailoring has passed validation.

All token usage is captured per-call in :class:`TailoringResult.llm_calls`
so Plan 04-04's service layer can write individual ``CostLedger`` rows and
debit the ``BudgetGuard`` correctly (validator and cover letter calls must
be billed alongside the tailoring call).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.tailoring.prompts import (
    build_cover_letter_messages,
    build_system_messages,
    build_tailoring_messages,
    build_validator_messages,
)
from app.tailoring.provider import LLMProvider, LLMResponse

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class TailoringResult:
    """Everything one tailoring attempt produced.

    Populated by :func:`tailor_resume`. Consumers (Plan 04-04 service
    layer) use this to write a ``TailoringRecord`` row, one or more
    ``CostLedger`` rows, and to kick off DOCX generation.
    """

    success: bool
    tailored_sections: dict | None
    cover_letter_paragraphs: list[str] | None
    validation_passed: bool
    validation_warnings: list[dict]
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_write_tokens: int
    retry_count: int
    error: str | None
    llm_calls: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PII stripping (SAFE-04)
# ---------------------------------------------------------------------------

_CONTACT_HEADING_HINTS = ("contact", "info", "personal", "details", "profile")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")


def _looks_like_contact_section(section: dict) -> bool:
    """Heuristic: is this section the contact header?"""
    heading = section.get("heading")
    if heading is None:
        return True  # unlabelled first block is almost always the header
    lowered = str(heading).lower()
    return any(hint in lowered for hint in _CONTACT_HEADING_HINTS)


def strip_pii_sections(
    sections: list[dict],
) -> tuple[str, list[str]]:
    """Drop the contact section and return ``(sanitized_text, headings)``.

    ``sections`` comes straight from
    :func:`app.resume.service.extract_resume_text`. The first section
    typically has ``heading=None`` and contains the name, email, phone,
    and address — we drop it entirely. Any subsequent section whose
    heading matches a contact-style hint (``Contact``, ``Personal Info``,
    etc.) is also dropped.

    As a belt-and-braces second pass, any remaining lines that still
    parse as an email or phone number are redacted before the text is
    joined. This catches the edge case where the base resume has contact
    info embedded outside a heading block.

    Returns:
        A ``(sanitized_text, headings)`` tuple. ``headings`` preserves
        the exact heading strings so the tailoring prompt can ask Claude
        to use them verbatim (research Pitfall 5).
    """
    kept_blocks: list[str] = []
    headings: list[str] = []
    skipped = 0

    for idx, section in enumerate(sections):
        if idx == 0 and _looks_like_contact_section(section):
            skipped += 1
            continue
        if _looks_like_contact_section(section):
            skipped += 1
            continue

        heading = section.get("heading")
        text = (section.get("text") or "").strip()
        if heading:
            headings.append(str(heading))
            kept_blocks.append(f"{heading}\n{text}" if text else str(heading))
        elif text:
            kept_blocks.append(text)

    if skipped == 0:
        logger.warning(
            "pii_strip_no_contact_section",
            section_count=len(sections),
            msg="No contact-style section found to strip; falling back "
            "to regex redaction only.",
        )

    joined = "\n\n".join(kept_blocks)
    # Belt-and-braces: redact any dangling email / phone matches.
    joined = _EMAIL_RE.sub("[REDACTED_EMAIL]", joined)
    joined = _PHONE_RE.sub("[REDACTED_PHONE]", joined)

    return joined, headings


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fences(raw: str) -> str:
    """Remove ```json ... ``` fences if Claude included them anyway."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        # Remove leading fence line and trailing fence
        stripped = _FENCE_RE.sub("", stripped).strip()
    return stripped


def parse_tailoring_response(raw_content: str) -> dict:
    """Parse the tailoring JSON out of Claude's response.

    Accepts content with or without markdown code fences. Raises
    ``ValueError`` with a descriptive message on any parse failure so
    the retry loop can log the reason and escalate.
    """
    if not raw_content or not raw_content.strip():
        raise ValueError("Tailoring response was empty")

    text = _strip_code_fences(raw_content)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Tailoring response was not valid JSON: {exc.msg} "
            f"(line {exc.lineno}, col {exc.colno})"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Tailoring response must be a JSON object, got {type(parsed).__name__}"
        )
    sections = parsed.get("sections")
    if not isinstance(sections, list):
        raise ValueError(
            "Tailoring response must have a 'sections' key that is a list"
        )
    return parsed


def parse_validation_response(raw_content: str) -> dict:
    """Parse the validator JSON out of Claude's response.

    Ensures the response has ``passed`` (bool) and ``violations`` (list).
    """
    if not raw_content or not raw_content.strip():
        raise ValueError("Validator response was empty")

    text = _strip_code_fences(raw_content)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Validator response was not valid JSON: {exc.msg}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError("Validator response must be a JSON object")
    if "passed" not in parsed or not isinstance(parsed["passed"], bool):
        raise ValueError(
            "Validator response must have a boolean 'passed' field"
        )
    violations = parsed.get("violations", [])
    if not isinstance(violations, list):
        raise ValueError("Validator 'violations' must be a list")
    parsed["violations"] = violations
    return parsed


def parse_cover_letter_response(raw_content: str) -> list[str]:
    """Extract the paragraphs list from a cover letter response."""
    if not raw_content or not raw_content.strip():
        raise ValueError("Cover letter response was empty")
    text = _strip_code_fences(raw_content)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Cover letter response was not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("Cover letter response must be a JSON object")
    paragraphs = parsed.get("paragraphs")
    if not isinstance(paragraphs, list) or not all(
        isinstance(p, str) for p in paragraphs
    ):
        raise ValueError(
            "Cover letter 'paragraphs' must be a list of strings"
        )
    return paragraphs


# ---------------------------------------------------------------------------
# Cost-tracking helpers
# ---------------------------------------------------------------------------


def _llm_call_record(call_type: str, response: LLMResponse) -> dict[str, Any]:
    """Flatten an ``LLMResponse`` into a CostLedger-ready dict."""
    return {
        "call_type": call_type,
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "cache_read_tokens": response.cache_read_tokens,
        "cache_write_tokens": response.cache_creation_tokens,
    }


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------


async def validate_output(
    provider: LLMProvider,
    original_text: str,
    tailored_json: str,
) -> tuple[bool, list[dict], LLMResponse]:
    """Run the LLM-as-judge validator.

    Returns ``(passed, violations, response)`` so the caller can both
    react to the verdict and log the token cost of the validator call.
    """
    system, messages = build_validator_messages(original_text, tailored_json)
    response = await provider.complete(
        system=system,
        messages=messages,
        max_tokens=2048,
        temperature=0.1,
    )
    parsed = parse_validation_response(response.content)
    passed = bool(parsed["passed"])
    violations = parsed["violations"]
    logger.info(
        "validation_result",
        passed=passed,
        violation_count=len(violations),
    )
    return passed, violations, response


async def generate_cover_letter(
    provider: LLMProvider,
    resume_text: str,
    job_description: str,
    company: str,
    title: str,
) -> tuple[list[str], LLMResponse]:
    """Generate a cover letter and return ``(paragraphs, response)``."""
    system, messages = build_cover_letter_messages(
        resume_text=resume_text,
        job_description=job_description,
        company=company,
        title=title,
    )
    response = await provider.complete(
        system=system,
        messages=messages,
        max_tokens=2048,
        temperature=0.4,
    )
    paragraphs = parse_cover_letter_response(response.content)
    logger.info(
        "cover_letter_generated",
        paragraph_count=len(paragraphs),
    )
    return paragraphs, response


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def tailor_resume(
    provider: LLMProvider,
    resume_sections: list[dict],
    job_description: str,
    intensity: str = "balanced",
    max_retries: int = 3,
    company: str = "",
    title: str = "",
) -> TailoringResult:
    """End-to-end tailoring: strip PII, tailor, validate, retry, cover.

    Parameters:
        provider: Any :class:`LLMProvider`. In production this comes
            from :func:`app.tailoring.provider.get_provider`.
        resume_sections: Sections as returned by
            :func:`app.resume.service.extract_resume_text`'s
            ``"sections"`` key.
        job_description: Raw job description text.
        intensity: ``"light" | "balanced" | "full"``. Defaults to
            balanced (CONTEXT.md locked decision).
        max_retries: Total tailoring attempts before giving up. The
            escalation schedule goes ``retry=0, 1, 2, ...``.
        company: Optional target company — forwarded to the cover letter
            prompt. Leave empty if unknown (engine handles gracefully).
        title: Optional target role title — same.

    Returns:
        :class:`TailoringResult` with everything needed to persist a
        ``TailoringRecord`` and write ``CostLedger`` rows.
    """
    logger.info(
        "tailoring_start",
        intensity=intensity,
        max_retries=max_retries,
        section_count=len(resume_sections),
    )

    # -- Step 1: PII strip -------------------------------------------------
    sanitized_text, headings = strip_pii_sections(resume_sections)
    if not sanitized_text.strip():
        return TailoringResult(
            success=False,
            tailored_sections=None,
            cover_letter_paragraphs=None,
            validation_passed=False,
            validation_warnings=[],
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_read_tokens=0,
            total_cache_write_tokens=0,
            retry_count=0,
            error="Resume contained no content after PII stripping",
        )

    system_messages = build_system_messages(sanitized_text)

    # Accumulators shared across retries --------------------------------
    llm_calls: list[dict] = []
    all_warnings: list[dict] = []
    total_in = 0
    total_out = 0
    total_cr = 0
    total_cw = 0

    tailored_parsed: dict | None = None
    tailored_raw: str = ""
    validation_ok = False
    retry = 0
    last_error: str | None = None

    # -- Step 2: Retry loop ------------------------------------------------
    for retry in range(max_retries):
        logger.info(
            "tailoring_attempt",
            retry=retry,
            intensity=intensity,
        )
        user_messages = build_tailoring_messages(
            job_description=job_description,
            intensity=intensity,
            section_headings=headings,
            retry=retry,
        )

        try:
            tailor_resp = await provider.complete(
                system=system_messages,
                messages=user_messages,
                max_tokens=4096,
                temperature=0.3,
            )
        except Exception as exc:  # pragma: no cover — provider-level fail
            last_error = f"Tailoring call failed: {exc}"
            logger.error("tailoring_call_failed", error=str(exc))
            break

        llm_calls.append(_llm_call_record("tailor", tailor_resp))
        total_in += tailor_resp.input_tokens
        total_out += tailor_resp.output_tokens
        total_cr += tailor_resp.cache_read_tokens
        total_cw += tailor_resp.cache_creation_tokens

        try:
            tailored_parsed = parse_tailoring_response(tailor_resp.content)
        except ValueError as exc:
            last_error = f"Tailoring output parse error: {exc}"
            logger.warning(
                "tailoring_parse_failed",
                retry=retry,
                error=str(exc),
            )
            all_warnings.append(
                {
                    "type": "parse_error",
                    "retry": retry,
                    "explanation": str(exc),
                }
            )
            continue
        tailored_raw = tailor_resp.content

        # Validate ------------------------------------------------------
        try:
            passed, violations, val_resp = await validate_output(
                provider=provider,
                original_text=sanitized_text,
                tailored_json=tailored_raw,
            )
        except ValueError as exc:
            last_error = f"Validator parse error: {exc}"
            logger.warning(
                "validator_parse_failed",
                retry=retry,
                error=str(exc),
            )
            all_warnings.append(
                {
                    "type": "validator_parse_error",
                    "retry": retry,
                    "explanation": str(exc),
                }
            )
            continue
        except Exception as exc:  # pragma: no cover — provider-level fail
            last_error = f"Validator call failed: {exc}"
            logger.error("validator_call_failed", error=str(exc))
            break

        llm_calls.append(_llm_call_record("validate", val_resp))
        total_in += val_resp.input_tokens
        total_out += val_resp.output_tokens
        total_cr += val_resp.cache_read_tokens
        total_cw += val_resp.cache_creation_tokens

        # Stamp every violation with which retry it came from (so the
        # review queue can show "Retry 1 removed invented skill X").
        for v in violations:
            v_stamped = dict(v)
            v_stamped["retry"] = retry
            all_warnings.append(v_stamped)

        if passed:
            validation_ok = True
            logger.info(
                "tailoring_validation_passed",
                retry=retry,
                warning_count_total=len(all_warnings),
            )
            break

        logger.info(
            "tailoring_validation_failed",
            retry=retry,
            violation_count=len(violations),
        )
        last_error = (
            f"Validation rejected at retry {retry}: "
            f"{len(violations)} violation(s)"
        )

    # -- Step 3: Check outcome & cover letter ------------------------------
    if not validation_ok or tailored_parsed is None:
        logger.warning(
            "tailoring_failed",
            retry_count=retry + 1 if tailored_parsed is not None else retry,
            last_error=last_error,
        )
        return TailoringResult(
            success=False,
            tailored_sections=tailored_parsed,
            cover_letter_paragraphs=None,
            validation_passed=False,
            validation_warnings=all_warnings,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cache_read_tokens=total_cr,
            total_cache_write_tokens=total_cw,
            retry_count=retry + 1,
            error=last_error
            or f"Validation failed after {max_retries} attempts",
            llm_calls=llm_calls,
        )

    # Validation passed — generate cover letter.
    cover_paragraphs: list[str] | None = None
    try:
        cover_paragraphs, cover_resp = await generate_cover_letter(
            provider=provider,
            resume_text=sanitized_text,
            job_description=job_description,
            company=company,
            title=title,
        )
        llm_calls.append(_llm_call_record("cover_letter", cover_resp))
        total_in += cover_resp.input_tokens
        total_out += cover_resp.output_tokens
        total_cr += cover_resp.cache_read_tokens
        total_cw += cover_resp.cache_creation_tokens
    except ValueError as exc:
        # Parse error — keep the tailoring win but flag the cover letter.
        logger.warning("cover_letter_parse_failed", error=str(exc))
        all_warnings.append(
            {
                "type": "cover_letter_parse_error",
                "explanation": str(exc),
            }
        )
    except Exception as exc:  # pragma: no cover — provider-level fail
        logger.error("cover_letter_call_failed", error=str(exc))
        all_warnings.append(
            {
                "type": "cover_letter_call_error",
                "explanation": str(exc),
            }
        )

    logger.info(
        "tailoring_complete",
        retry_count=retry + 1,
        validation_passed=True,
        warning_count=len(all_warnings),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_cache_read_tokens=total_cr,
        total_cache_write_tokens=total_cw,
        cover_letter=cover_paragraphs is not None,
    )

    return TailoringResult(
        success=True,
        tailored_sections=tailored_parsed,
        cover_letter_paragraphs=cover_paragraphs,
        validation_passed=True,
        validation_warnings=all_warnings,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_cache_read_tokens=total_cr,
        total_cache_write_tokens=total_cw,
        retry_count=retry + 1,
        error=None,
        llm_calls=llm_calls,
    )


__all__ = [
    "TailoringResult",
    "strip_pii_sections",
    "parse_tailoring_response",
    "parse_validation_response",
    "parse_cover_letter_response",
    "validate_output",
    "generate_cover_letter",
    "tailor_resume",
]
