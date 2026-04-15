"""Phase 5 submission models: Submission, FailureSuppression."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Submission(SQLModel, table=True):
    __tablename__ = "submissions"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    tailoring_record_id: int = Field(foreign_key="tailoring_records.id")
    attempt: int = Field(default=1)
    status: str = Field(default="pending")  # pending | sent | failed
    smtp_from: str = Field()
    smtp_to: str = Field()
    subject: str = Field()
    attachment_filename: str = Field()
    error_class: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    failure_signature: Optional[str] = Field(default=None, index=True)
    submitter: str = Field(default="email")  # email | playwright (future)
    sent_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FailureSuppression(SQLModel, table=True):
    __tablename__ = "failure_suppressions"

    id: Optional[int] = Field(default=None, primary_key=True)
    signature: str = Field(unique=True, index=True)
    stage: str = Field()  # submission | pipeline | discovery | tailoring
    error_class: str = Field()
    error_message_canon: str = Field(default="")
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    notify_count: int = Field(default=1)
    occurrence_count: int = Field(default=1)
    cleared_at: Optional[datetime] = Field(default=None)
    cleared_by: Optional[str] = Field(default=None)  # 'auto_next_success' | 'user_ack'


__all__ = ["Submission", "FailureSuppression"]
