"""LLM semantic matcher for answer reuse across different field wordings.

Uses the LLMProvider protocol to batch-match new field labels against
previously saved answers.  If the LLM says a label is semantically
equivalent to a saved answer, the match is accepted (no confidence
threshold — per locked design decision).

Graceful degradation: on any LLM failure the caller gets all-None
matches so the pipeline can continue without auto-fill.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.learning.models import SavedAnswer
    from app.tailoring.provider import LLMProvider

logger = structlog.get_logger(__name__)


async def find_matching_answers(
    field_labels: list[str],
    saved_answers: list["SavedAnswer"],
    provider: "LLMProvider",
) -> dict[str, "SavedAnswer | None"]:
    """Batch-match *field_labels* against *saved_answers* via ONE LLM call.

    Returns a dict mapping each label to a matched SavedAnswer or None.
    On LLM failure, returns all None (graceful degradation).
    """
    if not field_labels or not saved_answers:
        return {label: None for label in field_labels}

    # Build saved-answer lookup by ID for fast resolution.
    answer_by_id: dict[int, "SavedAnswer"] = {
        sa.id: sa for sa in saved_answers
    }

    saved_list = [
        {"id": sa.id, "label": sa.field_label, "type": sa.answer_type}
        for sa in saved_answers
    ]

    prompt = (
        "You are a form-field matcher. Given a list of NEW field labels from a "
        "job application form, and a list of SAVED answers (each with an id and "
        "label), determine which saved answer (if any) is semantically "
        "equivalent to each new label.\n\n"
        "Rules:\n"
        "- Match only if the fields clearly ask for the same information.\n"
        "- If no saved answer matches, return null for that label.\n"
        "- Return ONLY valid JSON, no explanation.\n\n"
        f"NEW LABELS: {json.dumps(field_labels)}\n\n"
        f"SAVED ANSWERS: {json.dumps(saved_list)}\n\n"
        'Return JSON object: {{"matches": {{"<new_label>": <saved_id_or_null>, ...}}}}'
    )

    try:
        response = await provider.complete(
            system=[{"type": "text", "text": "You are a precise field matcher."}],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.0,
        )

        # Parse the JSON response.
        raw = response.content.strip()
        # Handle markdown code fences if present.
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        matches_raw = data.get("matches", {})

        result: dict[str, "SavedAnswer | None"] = {}
        for label in field_labels:
            matched_id = matches_raw.get(label)
            if matched_id is not None and int(matched_id) in answer_by_id:
                result[label] = answer_by_id[int(matched_id)]
            else:
                result[label] = None
        return result

    except Exception:
        logger.warning(
            "llm_match_failed",
            label_count=len(field_labels),
            exc_info=True,
        )
        return {label: None for label in field_labels}


async def try_match_and_fill(
    session: "AsyncSession",
    unknown_field_infos: list[dict],
    saved_answers: list["SavedAnswer"],
    provider: "LLMProvider",
) -> tuple[list[dict], list[dict]]:
    """Try to match unknown fields against saved answers via LLM.

    *unknown_field_infos* is a list of dicts with at least ``field_id``
    and ``field_label`` keys.

    Returns ``(matched, still_unknown)`` where each is a list of the
    input dicts, augmented with ``matched_answer`` on the matched ones.
    """
    from app.learning.service import increment_reuse_count, resolve_unknown_field

    if not unknown_field_infos or not saved_answers:
        return [], list(unknown_field_infos)

    labels = [f["field_label"] for f in unknown_field_infos]
    matches = await find_matching_answers(labels, saved_answers, provider)

    matched: list[dict] = []
    still_unknown: list[dict] = []

    for info in unknown_field_infos:
        answer = matches.get(info["field_label"])
        if answer is not None:
            info["matched_answer"] = answer
            await increment_reuse_count(session, answer.id)
            await resolve_unknown_field(session, info["field_id"], answer.id)
            matched.append(info)
        else:
            still_unknown.append(info)

    return matched, still_unknown


__all__ = [
    "find_matching_answers",
    "try_match_and_fill",
]
