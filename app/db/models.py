"""SQLModel tables for Phase 1.

The schema is deliberately minimal: four tables that every later phase will
*add columns to*, not rename. Each table is a direct transcription of the
RESEARCH.md "SQLModel Schema (Phase 1 tables)" block.

Canonical failure reasons for ``Run.failure_reason`` are documented as a
module-level constant. The set is not enforced at the DB level (SQLite does
not have an enum type); the service layer is expected to pick from it so
dashboard renderers stay stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column, LargeBinary
from sqlmodel import Field, SQLModel

# ---------------------------------------------------------------------------
# Canonical failure reasons
# ---------------------------------------------------------------------------
# Service code must pick from this set when writing ``Run.failure_reason``.
# Enforced at the application layer, not the database, so tests can easily
# add new reasons without migrations.
CANONICAL_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "killed",       # user flipped the kill switch mid-run
        "rate_limit",   # daily cap reached before the run could submit anything new
        "error",        # a stage raised a handled exception
        "dry_run_skip", # run aborted on purpose because Settings.dry_run was on
        "crashed",      # container died mid-run; mark_orphans_failed backfilled this row
    }
)


class Settings(SQLModel, table=True):
    """Global app settings. Enforced single-row via a fixed primary key.

    Phase 2 may split ``keywords_csv`` into a proper ``keywords`` table, but
    Phase 1 keeps the column form so the wizard can write without a join.
    """

    __tablename__ = "settings"

    id: int = Field(default=1, primary_key=True)  # singleton row
    kill_switch: bool = Field(default=False)
    dry_run: bool = Field(default=False)
    daily_cap: int = Field(default=20)
    delay_min_seconds: int = Field(default=30)
    delay_max_seconds: int = Field(default=120)
    timezone: str = Field(default="UTC")
    wizard_complete: bool = Field(default=False)
    keywords_csv: str = Field(default="")  # pipe-delimited (|) despite legacy name
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # --- Phase 2 fields ---
    match_threshold: int = Field(default=60)
    schedule_enabled: bool = Field(default=False)
    quiet_hours_start: int = Field(default=22)   # 0-23
    quiet_hours_end: int = Field(default=7)       # 0-23
    budget_cap_dollars: float = Field(default=0.0)    # 0 = no cap
    budget_spent_dollars: float = Field(default=0.0)
    budget_month: str = Field(default="")  # e.g. "2026-04"
    auto_mode: bool = Field(default=True)  # True=full-auto, False=review-queue
    resume_filename: Optional[str] = Field(default=None)
    resume_uploaded_at: Optional[datetime] = Field(default=None)

    # --- Phase 4 fields ---
    tailoring_intensity: str = Field(default="balanced")  # light | balanced | full

    # --- Phase 5 fields ---
    notification_email: Optional[str] = Field(default=None)  # fallback: smtp_user
    base_url: str = Field(default="http://localhost:8000")
    submissions_paused: bool = Field(default=False)
    auto_holdout_margin_pct: int = Field(default=10)


class Secret(SQLModel, table=True):
    """Encrypted secret store.

    ``ciphertext`` is a ``LargeBinary`` column; there is no plaintext column,
    ever. The service layer encrypts via ``FernetVault`` before writing.
    """

    __tablename__ = "secrets"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    ciphertext: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Run(SQLModel, table=True):
    """One execution of the scheduled pipeline (or a manual force-run).

    ``counts`` stores per-stage tallies as JSON — Phase 1 writes it empty,
    Phase 2+ fills the dict shape
    ``{"discovered", "matched", "tailored", "submitted", "failed"}``.
    """

    __tablename__ = "runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        index=True,
    )
    ended_at: Optional[datetime] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None)
    status: str = Field(default="running")  # running|succeeded|failed|skipped
    failure_reason: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False)
    triggered_by: str = Field(default="scheduler")
    counts: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )


class RateLimitCounter(SQLModel, table=True):
    """Per-local-day submission counter.

    ``day`` is an ISO date string in the container's local timezone, so the
    midnight reset is a cheap "insert the next day's row" rather than an
    UPDATE race.
    """

    __tablename__ = "rate_limit_counters"

    day: str = Field(primary_key=True)
    submitted_count: int = Field(default=0)


class Profile(SQLModel, table=True):
    """User profile for auto-filling application forms.

    Singleton row (id=1) like Settings. Populated from the Profile section
    of the settings sidebar or parsed from an uploaded resume.
    """

    __tablename__ = "profile"

    id: int = Field(default=1, primary_key=True)  # singleton row
    full_name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    address: Optional[str] = Field(default=None)
    work_authorization: Optional[str] = Field(default=None)
    salary_expectation: Optional[str] = Field(default=None)
    years_experience: Optional[int] = Field(default=None)
    linkedin_url: Optional[str] = Field(default=None)
    github_url: Optional[str] = Field(default=None)
    portfolio_url: Optional[str] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Phase 3 discovery models — imported here so Alembic's env.py picks them
# up via ``from app.db import models`` and registers them on SQLModel.metadata.
from app.discovery.models import DiscoveryRunStats, Job, Source  # noqa: F401, E402

# Phase 4 tailoring models — same pattern as Phase 3 discovery above.
from app.tailoring.models import CostLedger, TailoringRecord  # noqa: F401, E402

# Phase 5 submission models — imported so Alembic env.py picks them up
from app.submission.models import FailureSuppression, Submission  # noqa: F401, E402

__all__ = [
    "Settings",
    "Secret",
    "Run",
    "RateLimitCounter",
    "Profile",
    "CANONICAL_FAILURE_REASONS",
    "Source",
    "Job",
    "DiscoveryRunStats",
    "TailoringRecord",
    "CostLedger",
    "Submission",
    "FailureSuppression",
]
