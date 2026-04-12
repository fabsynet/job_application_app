"""Phase 3 discovery models: Source, Job, DiscoveryRunStats.

Source — an ATS board the user wants to discover jobs from (Greenhouse,
Lever, or Ashby).  Job — a normalised job posting discovered from any
source.  DiscoveryRunStats — per-source counts for each pipeline run,
used for anomaly detection (rolling-average comparison).

All three tables follow the existing SQLModel + Alembic migration
pattern established in Phase 1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Source(SQLModel, table=True):
    """An ATS board the user wants to discover jobs from."""

    __tablename__ = "sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True)  # e.g. "stripe"
    source_type: str = Field()  # greenhouse | lever | ashby
    display_name: Optional[str] = Field(default=None)  # user-friendly label
    enabled: bool = Field(default=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    last_fetch_status: Optional[str] = Field(default=None)  # ok | error
    last_error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(SQLModel, table=True):
    """A normalised job posting discovered from any ATS source."""

    __tablename__ = "jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    fingerprint: str = Field(unique=True, index=True)  # SHA256 dedup key
    external_id: str = Field()  # ATS-specific ID
    title: str = Field()
    company: str = Field(index=True)
    location: str = Field(default="")
    description: str = Field(default="")  # plain text for scoring
    description_html: str = Field(default="")  # HTML for display
    url: str = Field()  # original posting URL
    source: str = Field()  # greenhouse | lever | ashby
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id")
    posted_date: Optional[datetime] = Field(default=None)  # nullable (Lever lacks this)
    score: int = Field(default=0)  # 0-100 keyword overlap
    matched_keywords: str = Field(default="")  # pipe-delimited
    status: str = Field(default="discovered")  # discovered | matched | queued | applied
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    run_id: Optional[int] = Field(default=None, foreign_key="runs.id")


class DiscoveryRunStats(SQLModel, table=True):
    """Per-source discovery counts for each run, for anomaly rolling average."""

    __tablename__ = "discovery_run_stats"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="runs.id", index=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    discovered_count: int = Field(default=0)
    matched_count: int = Field(default=0)
    error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


__all__ = ["Source", "Job", "DiscoveryRunStats"]
