"""Tailoring service layer: DB ops and artifact path management.

This module owns every read/write against ``tailoring_records`` and
``cost_ledger``, plus the filesystem layout for versioned artifacts.
Plan 04-05 Task 1.

Artifact layout (CONTEXT.md decision, TAIL-09):

    data/resumes/{job_id}/v1.docx
    data/resumes/{job_id}/v2.docx
    data/resumes/{job_id}/cover_letter_v1.docx
    ...

The pipeline stage (Task 2) calls ``get_next_version`` to compute the
next integer, writes the DOCX artifacts to the paths returned by
``resume_artifact_path`` / ``cover_letter_artifact_path``, then hands
the ``TailoringResult`` plus paths to ``save_tailoring_record``.

Every DB helper takes an ``AsyncSession`` (session lifecycle is owned
by the caller, matching the Phase 3 ``app.discovery.service`` pattern).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.discovery.models import Job
from app.tailoring.budget import BudgetGuard
from app.tailoring.models import CostLedger, TailoringRecord

if TYPE_CHECKING:
    from app.tailoring.engine import TailoringResult


log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Job queue (tailoring input)
# ---------------------------------------------------------------------------


async def get_queued_jobs(session: AsyncSession) -> list[Job]:
    """Return jobs ready for tailoring, ordered by score DESC.

    A job becomes eligible for tailoring when discovery marks it
    ``status="matched"`` (keyword score >= threshold) **or** when the
    review queue flips it to ``status="retailoring"`` after a user clicks
    "Re-tailor with a different angle" in the drawer (Phase 5 plan 05-05).
    Both cases run through the same engine, so the pipeline stage selects
    them in one query and pulls them highest-score-first so budget-
    constrained runs still hit the best matches.
    """
    stmt = (
        select(Job)
        .where(Job.status.in_(("matched", "retailoring")))
        .order_by(Job.score.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


async def get_next_version(session: AsyncSession, job_id: int) -> int:
    """Return the next ``TailoringRecord.version`` for ``job_id``.

    Counts existing records (any status) and returns ``count + 1``.
    """
    stmt = select(func.count(TailoringRecord.id)).where(
        TailoringRecord.job_id == job_id
    )
    result = await session.execute(stmt)
    count = int(result.scalar_one() or 0)
    return count + 1


# ---------------------------------------------------------------------------
# TailoringRecord persistence
# ---------------------------------------------------------------------------


def _compute_prompt_hash(
    system_prompt: str, resume_text: str, job_description: str
) -> str:
    """SHA256 of the prompt inputs for reproducibility auditing.

    Stored on ``TailoringRecord.prompt_hash`` so two records sharing a
    hash are guaranteed to have been generated from identical inputs —
    the UI can use this to spot redundant retries.
    """
    hasher = hashlib.sha256()
    hasher.update(system_prompt.encode("utf-8", errors="replace"))
    hasher.update(b"\x1e")  # record separator
    hasher.update(resume_text.encode("utf-8", errors="replace"))
    hasher.update(b"\x1e")
    hasher.update(job_description.encode("utf-8", errors="replace"))
    return hasher.hexdigest()


async def save_tailoring_record(
    session: AsyncSession,
    job_id: int,
    version: int,
    intensity: str,
    base_resume_path: str,
    tailored_resume_path: Optional[str],
    cover_letter_path: Optional[str],
    result: Optional["TailoringResult"],
    status: str,
    resume_text: str = "",
    job_description: str = "",
    system_prompt: str = "",
) -> TailoringRecord:
    """Create and persist a ``TailoringRecord`` for one attempt.

    ``result`` may be ``None`` when an exception prevented the engine
    from producing a result (status ``"failed"``). In that case the
    token/cost fields are all zero.
    """
    if result is not None:
        validation_warnings_json = json.dumps(result.validation_warnings)
        input_tokens = result.total_input_tokens
        output_tokens = result.total_output_tokens
        cache_read_tokens = result.total_cache_read_tokens
        cache_write_tokens = result.total_cache_write_tokens
        retry_count = result.retry_count
        validation_passed = result.validation_passed
        error_message = result.error
        estimated_cost = BudgetGuard.estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
    else:
        validation_warnings_json = "[]"
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_write_tokens = 0
        retry_count = 0
        validation_passed = None
        error_message = "Tailoring engine raised before returning a result"
        estimated_cost = 0.0

    record = TailoringRecord(
        job_id=job_id,
        version=version,
        intensity=intensity,
        status=status,
        base_resume_path=base_resume_path,
        tailored_resume_path=tailored_resume_path,
        cover_letter_path=cover_letter_path,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        estimated_cost_dollars=estimated_cost,
        validation_passed=validation_passed,
        validation_warnings=validation_warnings_json,
        retry_count=retry_count,
        prompt_hash=_compute_prompt_hash(
            system_prompt, resume_text, job_description
        ),
        error_message=error_message,
        created_at=datetime.utcnow(),
    )
    session.add(record)
    await session.flush()  # populate record.id before caller uses it
    log.info(
        "tailoring_record_saved",
        record_id=record.id,
        job_id=job_id,
        version=version,
        status=status,
        estimated_cost=estimated_cost,
    )
    return record


# ---------------------------------------------------------------------------
# CostLedger persistence
# ---------------------------------------------------------------------------


def _current_month() -> str:
    """YYYY-MM in UTC, matching ``BudgetGuard._current_month``."""
    return datetime.utcnow().strftime("%Y-%m")


async def save_cost_entries(
    session: AsyncSession,
    record_id: int,
    llm_calls: list[dict],
) -> list[CostLedger]:
    """Write one ``CostLedger`` row per entry in ``llm_calls``.

    ``llm_calls`` is the list produced by ``TailoringResult.llm_calls``
    (engine 04-03): each dict carries ``call_type``, ``model``, and the
    four token buckets. The per-call cost is estimated via
    ``BudgetGuard.estimate_cost`` — the same pricing table the budget
    guard uses when it debits, so the ledger sum always matches spend.
    """
    month = _current_month()
    rows: list[CostLedger] = []
    for call in llm_calls:
        cost = BudgetGuard.estimate_cost(
            input_tokens=int(call.get("input_tokens", 0)),
            output_tokens=int(call.get("output_tokens", 0)),
            cache_read_tokens=int(call.get("cache_read_tokens", 0)),
            cache_write_tokens=int(call.get("cache_write_tokens", 0)),
            model=str(call.get("model", "claude-sonnet-4-5")),
        )
        row = CostLedger(
            tailoring_record_id=record_id,
            call_type=str(call.get("call_type", "tailor")),
            model=str(call.get("model", "claude-sonnet-4-5")),
            input_tokens=int(call.get("input_tokens", 0)),
            output_tokens=int(call.get("output_tokens", 0)),
            cache_read_tokens=int(call.get("cache_read_tokens", 0)),
            cache_write_tokens=int(call.get("cache_write_tokens", 0)),
            cost_dollars=cost,
            month=month,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        rows.append(row)
    await session.flush()
    log.info(
        "cost_entries_saved",
        record_id=record_id,
        entry_count=len(rows),
        total_cost=round(sum(r.cost_dollars for r in rows), 6),
    )
    return rows


# ---------------------------------------------------------------------------
# Read helpers (review queue / dashboard)
# ---------------------------------------------------------------------------


async def get_tailoring_records_for_job(
    session: AsyncSession, job_id: int
) -> list[TailoringRecord]:
    """All ``TailoringRecord`` rows for ``job_id`` ordered by version."""
    stmt = (
        select(TailoringRecord)
        .where(TailoringRecord.job_id == job_id)
        .order_by(TailoringRecord.version.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_tailoring(
    session: AsyncSession, job_id: int
) -> Optional[TailoringRecord]:
    """Return the highest-version *completed* record for ``job_id``.

    Returns ``None`` if no completed record exists — useful for the
    review queue to decide whether a job has a viewable artifact.
    """
    stmt = (
        select(TailoringRecord)
        .where(
            TailoringRecord.job_id == job_id,
            TailoringRecord.status == "completed",
        )
        .order_by(TailoringRecord.version.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_monthly_cost_summary(session: AsyncSession) -> dict:
    """Current-month spend breakdown for the dashboard budget card.

    Returns::

        {
            "total_cost": float,
            "call_count": int,
            "by_type": {"tailor": float, "validate": float, "cover_letter": float},
        }
    """
    month = _current_month()

    total_stmt = select(
        func.coalesce(func.sum(CostLedger.cost_dollars), 0.0),
        func.count(CostLedger.id),
    ).where(CostLedger.month == month)
    total_row = (await session.execute(total_stmt)).one()
    total_cost = float(total_row[0] or 0.0)
    call_count = int(total_row[1] or 0)

    by_type_stmt = (
        select(
            CostLedger.call_type,
            func.coalesce(func.sum(CostLedger.cost_dollars), 0.0),
        )
        .where(CostLedger.month == month)
        .group_by(CostLedger.call_type)
    )
    by_type_result = await session.execute(by_type_stmt)
    by_type: dict[str, float] = {
        "tailor": 0.0,
        "validate": 0.0,
        "cover_letter": 0.0,
    }
    for call_type, subtotal in by_type_result.all():
        by_type[str(call_type)] = float(subtotal or 0.0)

    return {
        "total_cost": round(total_cost, 6),
        "call_count": call_count,
        "by_type": {k: round(v, 6) for k, v in by_type.items()},
    }


# ---------------------------------------------------------------------------
# Artifact path helpers
# ---------------------------------------------------------------------------


def artifact_dir(job_id: int) -> Path:
    """Return ``data/resumes/{job_id}/``, creating it if needed."""
    d = Path(get_settings().data_dir) / "resumes" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def resume_artifact_path(job_id: int, version: int) -> Path:
    """Versioned tailored-resume DOCX path for ``job_id`` / ``version``."""
    return artifact_dir(job_id) / f"v{version}.docx"


def cover_letter_artifact_path(job_id: int, version: int) -> Path:
    """Versioned cover-letter DOCX path for ``job_id`` / ``version``."""
    return artifact_dir(job_id) / f"cover_letter_v{version}.docx"


__all__ = [
    "get_queued_jobs",
    "get_next_version",
    "save_tailoring_record",
    "save_cost_entries",
    "get_tailoring_records_for_job",
    "get_latest_tailoring",
    "get_monthly_cost_summary",
    "artifact_dir",
    "resume_artifact_path",
    "cover_letter_artifact_path",
]
