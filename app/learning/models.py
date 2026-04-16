"""Phase 6 learning models: SavedAnswer, UnknownField.

SavedAnswer — a field-label/answer pair learned from a previous application,
re-used to auto-fill future forms.  UnknownField — a form field the bot
could not map to any known answer, queued for human resolution.

Both tables follow the existing SQLModel + Alembic migration pattern
established in Phases 1-5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SavedAnswer(SQLModel, table=True):
    """A learned answer for a specific form field label.

    When the user fills in an unknown field, the answer is saved here so
    future applications with the same (or similar) label can be auto-filled.
    """

    __tablename__ = "saved_answers"

    id: Optional[int] = Field(default=None, primary_key=True)
    field_label: str = Field(index=True)
    field_label_normalized: str = Field()
    answer_text: str = Field()
    answer_type: str = Field(default="text")  # text | select | checkbox | file
    source_job_id: Optional[int] = Field(
        default=None, foreign_key="jobs.id"
    )
    times_reused: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UnknownField(SQLModel, table=True):
    """A form field the bot could not auto-fill.

    Stored for human review; once the user provides an answer the
    ``resolved`` flag flips and a SavedAnswer row is created.
    """

    __tablename__ = "unknown_fields"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    field_label: str = Field()
    field_type: str = Field(default="text")  # text | select | checkbox | file | radio
    field_options: Optional[str] = Field(default=None)  # JSON array for select/radio
    screenshot_path: Optional[str] = Field(default=None)
    page_number: int = Field(default=1)
    is_required: bool = Field(default=False)
    resolved: bool = Field(default=False)
    saved_answer_id: Optional[int] = Field(
        default=None, foreign_key="saved_answers.id"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
