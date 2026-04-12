"""Phase 4 tailoring models: TailoringRecord, CostLedger.

TailoringRecord — one row per tailoring attempt for a given job. Tracks
the version (v1.docx, v2.docx, …), the intensity preset used, cost,
validator outcome and retry count, plus paths to the generated
artifacts (tailored resume + cover letter).

CostLedger — one row per Claude API call that ``TailoringRecord``
chain triggered. Used for monthly budget enforcement, dashboard
spend totals, and per-call audit/reproducibility. Keyed on ``month``
so the budget query is a cheap indexed SUM.

Both tables follow the existing SQLModel + Alembic migration pattern
established in Phases 1-3.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class TailoringRecord(SQLModel, table=True):
    """One tailoring attempt for a single job."""

    __tablename__ = "tailoring_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    version: int = Field(default=1)  # v1.docx, v2.docx, …
    intensity: str = Field(default="balanced")  # light | balanced | full
    status: str = Field(default="pending")  # pending | completed | failed | rejected
    base_resume_path: str = Field()
    tailored_resume_path: Optional[str] = Field(default=None)
    cover_letter_path: Optional[str] = Field(default=None)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_write_tokens: int = Field(default=0)
    estimated_cost_dollars: float = Field(default=0.0)
    validation_passed: Optional[bool] = Field(default=None)
    validation_warnings: str = Field(default="")  # JSON blob of validator findings
    retry_count: int = Field(default=0)
    prompt_hash: Optional[str] = Field(default=None)  # SHA256 for reproducibility
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CostLedger(SQLModel, table=True):
    """Per-call cost entry used for budget enforcement and audit."""

    __tablename__ = "cost_ledger"

    id: Optional[int] = Field(default=None, primary_key=True)
    tailoring_record_id: Optional[int] = Field(
        default=None, foreign_key="tailoring_records.id"
    )
    call_type: str = Field()  # tailor | validate | cover_letter
    model: str = Field()  # e.g. "claude-sonnet-4-5"
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_write_tokens: int = Field(default=0)
    cost_dollars: float = Field(default=0.0)
    month: str = Field(index=True)  # e.g. "2026-04"
    created_at: datetime = Field(default_factory=datetime.utcnow)


__all__ = ["TailoringRecord", "CostLedger"]
