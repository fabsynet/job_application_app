"""SavedAnswer CRUD + UnknownField persistence for the learning loop.

Provides the data-access layer that the browser submission pipeline and
the settings UI use to store, retrieve, and resolve form-field answers.

All functions accept an ``AsyncSession`` and perform explicit
``session.flush()`` so callers see generated IDs without committing --
the caller (usually a route handler or pipeline step) owns the commit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.models import SavedAnswer, UnknownField


def _normalize_label(label: str) -> str:
    """Lowercase, strip whitespace, collapse internal whitespace."""
    return " ".join(label.lower().split())


async def save_answer(
    session: AsyncSession,
    field_label: str,
    answer_text: str,
    answer_type: str = "text",
    source_job_id: Optional[int] = None,
) -> SavedAnswer:
    """Create or update a SavedAnswer for *field_label*.

    If an answer with the same normalised label already exists, update its
    text and timestamp rather than creating a duplicate.
    """
    normalized = _normalize_label(field_label)
    result = await session.execute(
        select(SavedAnswer).where(
            SavedAnswer.field_label_normalized == normalized
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.answer_text = answer_text
        existing.answer_type = answer_type
        existing.updated_at = datetime.utcnow()
        if source_job_id is not None:
            existing.source_job_id = source_job_id
        session.add(existing)
        await session.flush()
        return existing

    answer = SavedAnswer(
        field_label=field_label,
        field_label_normalized=normalized,
        answer_text=answer_text,
        answer_type=answer_type,
        source_job_id=source_job_id,
    )
    session.add(answer)
    await session.flush()
    return answer


async def get_all_saved_answers(
    session: AsyncSession,
) -> list[SavedAnswer]:
    """Return all saved answers ordered by reuse count then recency."""
    result = await session.execute(
        select(SavedAnswer).order_by(
            SavedAnswer.times_reused.desc(),
            SavedAnswer.created_at.desc(),
        )
    )
    return list(result.scalars().all())


async def get_saved_answer(
    session: AsyncSession, answer_id: int
) -> SavedAnswer | None:
    """Look up a single SavedAnswer by primary key."""
    result = await session.execute(
        select(SavedAnswer).where(SavedAnswer.id == answer_id)
    )
    return result.scalar_one_or_none()


async def delete_saved_answer(
    session: AsyncSession, answer_id: int
) -> bool:
    """Delete a SavedAnswer by ID.  Returns True if a row was deleted."""
    answer = await get_saved_answer(session, answer_id)
    if answer is None:
        return False
    await session.delete(answer)
    await session.flush()
    return True


async def update_saved_answer(
    session: AsyncSession, answer_id: int, answer_text: str
) -> SavedAnswer | None:
    """Update the text of an existing SavedAnswer."""
    answer = await get_saved_answer(session, answer_id)
    if answer is None:
        return None
    answer.answer_text = answer_text
    answer.updated_at = datetime.utcnow()
    session.add(answer)
    await session.flush()
    return answer


async def increment_reuse_count(
    session: AsyncSession, answer_id: int
) -> None:
    """Bump the ``times_reused`` counter by one."""
    answer = await get_saved_answer(session, answer_id)
    if answer is not None:
        answer.times_reused += 1
        session.add(answer)
        await session.flush()


# -----------------------------------------------------------------------
# UnknownField persistence
# -----------------------------------------------------------------------


async def create_unknown_fields(
    session: AsyncSession,
    job_id: int,
    fields: list[dict],
) -> list[UnknownField]:
    """Bulk-create UnknownField rows, deduplicating by (job_id, field_label)."""
    # Fetch existing labels for this job to dedup.
    result = await session.execute(
        select(UnknownField.field_label).where(
            UnknownField.job_id == job_id
        )
    )
    existing_labels: set[str] = {row[0] for row in result.all()}

    created: list[UnknownField] = []
    for f in fields:
        label = f.get("field_label", "")
        if label in existing_labels:
            continue
        existing_labels.add(label)
        uf = UnknownField(
            job_id=job_id,
            field_label=label,
            field_type=f.get("field_type", "text"),
            field_options=f.get("field_options"),
            screenshot_path=f.get("screenshot_path"),
            page_number=f.get("page_number", 1),
            is_required=f.get("is_required", False),
        )
        session.add(uf)
        created.append(uf)

    if created:
        await session.flush()
    return created


async def get_unknown_fields_for_job(
    session: AsyncSession, job_id: int
) -> list[UnknownField]:
    """Return unresolved unknown fields for a job, ordered by page number."""
    result = await session.execute(
        select(UnknownField)
        .where(UnknownField.job_id == job_id, UnknownField.resolved == False)  # noqa: E712
        .order_by(UnknownField.page_number)
    )
    return list(result.scalars().all())


async def resolve_unknown_field(
    session: AsyncSession,
    field_id: int,
    saved_answer_id: int,
) -> None:
    """Mark an unknown field as resolved and link it to a saved answer."""
    result = await session.execute(
        select(UnknownField).where(UnknownField.id == field_id)
    )
    field = result.scalar_one_or_none()
    if field is not None:
        field.resolved = True
        field.saved_answer_id = saved_answer_id
        session.add(field)
        await session.flush()


async def resolve_all_for_job(
    session: AsyncSession,
    job_id: int,
    answers: dict[int, str],
) -> list[SavedAnswer]:
    """Resolve multiple unknown fields for a job in one go.

    *answers* maps ``field_id`` -> ``answer_text``.  For each entry we:
    1. Look up the UnknownField to get its label and type.
    2. Save an answer (create or update via :func:`save_answer`).
    3. Mark the field resolved.

    Returns the list of SavedAnswer objects created/updated.
    """
    saved: list[SavedAnswer] = []
    for field_id, answer_text in answers.items():
        result = await session.execute(
            select(UnknownField).where(UnknownField.id == field_id)
        )
        field = result.scalar_one_or_none()
        if field is None:
            continue
        sa = await save_answer(
            session,
            field_label=field.field_label,
            answer_text=answer_text,
            answer_type=field.field_type,
            source_job_id=job_id,
        )
        await resolve_unknown_field(session, field_id, sa.id)
        saved.append(sa)
    return saved


__all__ = [
    "save_answer",
    "get_all_saved_answers",
    "get_saved_answer",
    "delete_saved_answer",
    "update_saved_answer",
    "increment_reuse_count",
    "create_unknown_fields",
    "get_unknown_fields_for_job",
    "resolve_unknown_field",
    "resolve_all_for_job",
]
