"""Base form filler with label-based heuristic engine (06-03).

Maps form field labels to user profile data using regex pattern matching.
Provides classify/fill primitives used by all ATS-specific fillers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label heuristics — priority-ordered list of (pattern, profile_field, input_method)
# First match wins, so more specific patterns come first.
# ---------------------------------------------------------------------------

LABEL_HEURISTICS: list[tuple[str, str, str]] = [
    # Name fields — specific before generic
    (r"\bfirst[\s_-]*name\b", "first_name", "text"),
    (r"\blast[\s_-]*name\b", "last_name", "text"),
    (r"\bfull[\s_-]*name\b", "full_name", "text"),
    (r"\bname\b", "full_name", "text"),
    # Contact
    (r"\be[\s_-]*mail\b", "email", "text"),
    (r"\bphone\b|\bmobile\b|\bcell\b", "phone", "text"),
    # Links
    (r"\blinkedin\b", "linkedin_url", "text"),
    (r"\bgithub\b", "github_url", "text"),
    (r"\bportfolio\b|\bpersonal[\s_-]*site\b|\bwebsite\b", "portfolio_url", "text"),
    # File uploads
    (r"\bresume\b|\bcv\b|\bcurriculum\b", "resume", "upload"),
    (r"\bcover[\s_-]*letter\b", "cover_letter", "upload"),
    # Work authorization
    (
        r"\bwork[\s_-]*auth\b|\blegally[\s_-]*auth\b|\bsponsorship\b|\bauthori[sz](?:ed?|ation)\b",
        "work_authorization",
        "select_or_fill",
    ),
    # Compensation
    (r"\bsalary\b|\bcompensation\b|\bpay\b", "salary_expectation", "text"),
    # Experience
    (r"\byears?\s*(of\s*)?exp\b|\bexperience\b", "years_experience", "text"),
    # Location
    (
        r"\blocation\b|\bcity\b|\baddress\b|\bzip\b|\bpostal\b",
        "address",
        "text",
    ),
]


def match_field_to_profile(label: str) -> tuple[str, str] | None:
    """Return (profile_field, input_method) for the first matching heuristic.

    Matching is case-insensitive. Returns ``None`` if no heuristic matches.
    """
    if not label:
        return None
    for pattern, profile_field, input_method in LABEL_HEURISTICS:
        if re.search(pattern, label, re.IGNORECASE):
            return (profile_field, input_method)
    return None


def get_profile_value(profile: Any, field_name: str) -> str | None:
    """Resolve *field_name* to a string value from *profile*.

    Handles ``first_name`` / ``last_name`` by splitting ``full_name``.
    Returns ``None`` when the field is absent or empty.
    """
    if field_name == "first_name":
        full = getattr(profile, "full_name", None) or ""
        parts = full.strip().split()
        return parts[0] if parts else None

    if field_name == "last_name":
        full = getattr(profile, "full_name", None) or ""
        parts = full.strip().split()
        return " ".join(parts[1:]) if len(parts) > 1 else None

    # Direct attribute lookup
    value = getattr(profile, field_name, None)
    if value is None:
        return None
    return str(value) if value != "" else None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class KnownField:
    """A form field successfully mapped to a profile value."""

    label: str
    profile_field: str
    value: str
    input_method: str  # text | upload | select_or_fill
    locator: Any  # Playwright Locator


@dataclass
class UnknownFieldInfo:
    """A form field that could not be mapped to a profile value."""

    label: str
    field_type: str  # text | select | checkbox | file | radio | textarea
    options: list[str] = field(default_factory=list)
    is_required: bool = False
    page_number: int = 1
    locator: Any = None


# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------


async def _extract_label(element: Any, page: Any) -> str:
    """Best-effort label extraction for a form element."""
    # 1. <label for="id">
    elem_id = await element.get_attribute("id")
    if elem_id:
        label_el = page.locator(f'label[for="{elem_id}"]')
        if await label_el.count() > 0:
            text = (await label_el.first.inner_text()).strip()
            if text:
                return text

    # 2. Ancestor <label>
    ancestor_label = element.locator("xpath=ancestor::label")
    if await ancestor_label.count() > 0:
        text = (await ancestor_label.first.inner_text()).strip()
        if text:
            return text

    # 3. aria-label
    aria = await element.get_attribute("aria-label")
    if aria:
        return aria.strip()

    # 4. placeholder
    placeholder = await element.get_attribute("placeholder")
    if placeholder:
        return placeholder.strip()

    # 5. name attribute as last resort
    name = await element.get_attribute("name")
    if name:
        return name.strip()

    return ""


async def _detect_field_type(element: Any) -> str:
    """Detect the field type from tag name and input type."""
    tag = (await element.evaluate("el => el.tagName")).lower()
    if tag == "select":
        return "select"
    if tag == "textarea":
        return "textarea"
    input_type = (await element.get_attribute("type") or "text").lower()
    type_map = {
        "checkbox": "checkbox",
        "radio": "radio",
        "file": "file",
        "email": "text",
        "tel": "text",
        "url": "text",
        "number": "text",
    }
    return type_map.get(input_type, input_type)


async def _get_select_options(element: Any) -> list[str]:
    """Extract option texts from a <select> element."""
    options = await element.evaluate(
        "el => Array.from(el.options).map(o => o.text.trim()).filter(t => t)"
    )
    return options


async def classify_fields(
    page: Any,
    profile: Any,
    page_number: int = 1,
) -> tuple[list[KnownField], list[UnknownFieldInfo]]:
    """Find all visible form fields on *page*, partition into known/unknown.

    Returns ``(known_fields, unknown_fields)`` where known fields have a
    profile value ready to fill and unknown fields need human input.
    """
    known: list[KnownField] = []
    unknown: list[UnknownFieldInfo] = []

    # Gather all input-like elements visible on the page
    selectors = [
        "input:visible",
        "select:visible",
        "textarea:visible",
    ]
    seen_elements: set[str] = set()

    for selector in selectors:
        elements = page.locator(selector)
        count = await elements.count()

        for i in range(count):
            element = elements.nth(i)

            # De-duplicate by a stable identifier
            elem_id = await element.get_attribute("id") or ""
            elem_name = await element.get_attribute("name") or ""
            dedup_key = elem_id or elem_name or f"_idx_{selector}_{i}"
            if dedup_key in seen_elements:
                continue
            seen_elements.add(dedup_key)

            # Skip hidden/submit/button inputs
            input_type = (await element.get_attribute("type") or "").lower()
            if input_type in ("hidden", "submit", "button", "image", "reset"):
                continue

            label = await _extract_label(element, page)
            field_type = await _detect_field_type(element)

            match_result = match_field_to_profile(label)

            if match_result:
                profile_field, input_method = match_result

                # For upload fields, don't need a profile value
                if input_method == "upload":
                    known.append(
                        KnownField(
                            label=label,
                            profile_field=profile_field,
                            value="",  # filled later with file path
                            input_method=input_method,
                            locator=element,
                        )
                    )
                    continue

                value = get_profile_value(profile, profile_field)
                if value:
                    known.append(
                        KnownField(
                            label=label,
                            profile_field=profile_field,
                            value=value,
                            input_method=input_method,
                            locator=element,
                        )
                    )
                    continue

            # Unknown field — collect metadata
            options: list[str] = []
            if field_type == "select":
                options = await _get_select_options(element)

            is_required = (
                await element.get_attribute("required") is not None
                or await element.get_attribute("aria-required") == "true"
            )

            unknown.append(
                UnknownFieldInfo(
                    label=label,
                    field_type=field_type,
                    options=options,
                    is_required=is_required,
                    page_number=page_number,
                    locator=element,
                )
            )

    return known, unknown


# ---------------------------------------------------------------------------
# Field filling
# ---------------------------------------------------------------------------


async def try_select_with_fallback(locator: Any, value: str) -> bool:
    """Select an option by exact match, then case-insensitive substring.

    Returns True if an option was selected, False otherwise.
    """
    # Exact match
    try:
        await locator.select_option(label=value)
        return True
    except Exception:
        pass

    # Case-insensitive substring search
    try:
        options = await locator.evaluate(
            "el => Array.from(el.options).map(o => o.text.trim()).filter(t => t)"
        )
        value_lower = value.lower()
        for opt in options:
            if value_lower in opt.lower():
                # Re-create select_option without the side_effect from above
                await locator.select_option(label=opt)
                return True
    except Exception:
        logger.warning("Failed fallback select for value=%r", value)

    return False


async def fill_known_fields(
    page: Any,
    known_fields: list[KnownField],
    resume_path: Optional[str] = None,
    cover_letter_path: Optional[str] = None,
) -> None:
    """Fill all known fields on the current page.

    For ``upload`` fields, auto-detects resume vs cover letter by profile_field.
    For ``select_or_fill``, tries select first, falls back to text input.
    """
    for kf in known_fields:
        try:
            if kf.input_method == "upload":
                file_path = None
                if kf.profile_field == "resume" and resume_path:
                    file_path = resume_path
                elif kf.profile_field == "cover_letter" and cover_letter_path:
                    file_path = cover_letter_path

                if file_path:
                    await kf.locator.set_input_files(file_path)
                    logger.info("Uploaded %s for field %r", kf.profile_field, kf.label)
                else:
                    logger.warning(
                        "No file path for upload field %r (%s)",
                        kf.label,
                        kf.profile_field,
                    )
                continue

            if kf.input_method == "select_or_fill":
                # Try select first
                tag = (await kf.locator.evaluate("el => el.tagName")).lower()
                if tag == "select":
                    if await try_select_with_fallback(kf.locator, kf.value):
                        logger.info("Selected %r for field %r", kf.value, kf.label)
                        continue

                # Fallback to text fill
                await kf.locator.fill(kf.value)
                logger.info("Filled (fallback) %r for field %r", kf.value, kf.label)
                continue

            # Default: text fill
            await kf.locator.fill(kf.value)
            logger.info("Filled %r for field %r", kf.value, kf.label)

        except Exception:
            logger.exception("Error filling field %r", kf.label)
