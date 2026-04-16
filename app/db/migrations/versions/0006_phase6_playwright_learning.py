"""Phase 6: saved_answers, unknown_fields tables + Settings additions.

Revision ID: 0006_phase6_playwright_learning
Revises: 0005_phase5_submission
Create Date: 2026-04-15

Creates Phase 6 foundation tables for the learning loop (saved answers and
unknown form fields) and augments the settings singleton with three new
columns for Playwright browser configuration.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_phase6_playwright_learning"
down_revision: Union[str, None] = "0005_phase5_submission"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- saved_answers table ---
    op.create_table(
        "saved_answers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("field_label", sa.String(), nullable=False),
        sa.Column("field_label_normalized", sa.String(), nullable=False),
        sa.Column("answer_text", sa.String(), nullable=False),
        sa.Column(
            "answer_type",
            sa.String(),
            nullable=False,
            server_default=sa.text("'text'"),
        ),
        sa.Column(
            "source_job_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "times_reused",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"]),
    )
    op.create_index(
        "ix_saved_answers_field_label", "saved_answers", ["field_label"]
    )

    # --- unknown_fields table ---
    op.create_table(
        "unknown_fields",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("field_label", sa.String(), nullable=False),
        sa.Column(
            "field_type",
            sa.String(),
            nullable=False,
            server_default=sa.text("'text'"),
        ),
        sa.Column("field_options", sa.String(), nullable=True),
        sa.Column("screenshot_path", sa.String(), nullable=True),
        sa.Column(
            "page_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("saved_answer_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["saved_answer_id"], ["saved_answers.id"]),
    )
    op.create_index(
        "ix_unknown_fields_job_id", "unknown_fields", ["job_id"]
    )

    # --- Settings columns (Phase 6) ---
    op.add_column(
        "settings",
        sa.Column(
            "playwright_headless",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "pause_if_unsure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "screenshot_retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "screenshot_retention_days")
    op.drop_column("settings", "pause_if_unsure")
    op.drop_column("settings", "playwright_headless")

    op.drop_index("ix_unknown_fields_job_id", table_name="unknown_fields")
    op.drop_table("unknown_fields")

    op.drop_index("ix_saved_answers_field_label", table_name="saved_answers")
    op.drop_table("saved_answers")
