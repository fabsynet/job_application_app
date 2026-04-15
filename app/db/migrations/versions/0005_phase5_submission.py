"""Phase 5: submissions, failure_suppressions tables + Settings additions.

Revision ID: 0005_phase5_submission
Revises: 0004_phase4_tailoring
Create Date: 2026-04-15

Creates Phase 5 foundation tables and augments the settings singleton with
four new columns. Includes the critical partial UNIQUE index enforcing
"one sent submission per job" (SC-7 idempotency).

NOTE: Partial unique indexes are expressed via ``op.create_index`` with
``sqlite_where``. SQLite silently ignores ``sqlite_where`` on
``UniqueConstraint`` — research Pitfall 9. Always use create_index.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_phase5_submission"
down_revision: Union[str, None] = "0004_phase4_tailoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- submissions table ---
    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "tailoring_record_id",
            sa.Integer(),
            sa.ForeignKey("tailoring_records.id"),
            nullable=False,
        ),
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("smtp_from", sa.String(), nullable=False),
        sa.Column("smtp_to", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("attachment_filename", sa.String(), nullable=False),
        sa.Column("error_class", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("failure_signature", sa.String(), nullable=True),
        sa.Column(
            "submitter",
            sa.String(),
            nullable=False,
            server_default=sa.text("'email'"),
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_submissions_job_id", "submissions", ["job_id"]
    )
    op.create_index(
        "ix_submissions_failure_signature",
        "submissions",
        ["failure_signature"],
    )

    # Partial unique index — SC-7 idempotency. Use create_index with
    # sqlite_where; UniqueConstraint would silently drop the WHERE clause
    # on SQLite (research Pitfall 9).
    op.create_index(
        "ux_submissions_job_sent",
        "submissions",
        ["job_id"],
        unique=True,
        sqlite_where=sa.text("status = 'sent'"),
    )

    # --- failure_suppressions table ---
    op.create_table(
        "failure_suppressions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("error_class", sa.String(), nullable=False),
        sa.Column(
            "error_message_canon",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "notify_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "occurrence_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
        sa.Column("cleared_by", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_failure_suppressions_signature",
        "failure_suppressions",
        ["signature"],
        unique=True,
    )

    # --- Settings columns (Phase 5) ---
    # SQLite requires server_default for add-column to an existing row.
    op.add_column(
        "settings",
        sa.Column(
            "notification_email",
            sa.String(),
            nullable=True,
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "base_url",
            sa.String(),
            nullable=False,
            server_default=sa.text("'http://localhost:8000'"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "submissions_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "auto_holdout_margin_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "auto_holdout_margin_pct")
    op.drop_column("settings", "submissions_paused")
    op.drop_column("settings", "base_url")
    op.drop_column("settings", "notification_email")

    op.drop_index(
        "ix_failure_suppressions_signature",
        table_name="failure_suppressions",
    )
    op.drop_table("failure_suppressions")

    op.drop_index("ux_submissions_job_sent", table_name="submissions")
    op.drop_index(
        "ix_submissions_failure_signature", table_name="submissions"
    )
    op.drop_index("ix_submissions_job_id", table_name="submissions")
    op.drop_table("submissions")
