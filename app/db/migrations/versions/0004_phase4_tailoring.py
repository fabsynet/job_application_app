"""Phase 4: TailoringRecord, CostLedger tables + settings.tailoring_intensity.

Revision ID: 0004_phase4_tailoring
Revises: 0003_phase3_discovery
Create Date: 2026-04-12

Creates the two tailoring tables that every subsequent Phase 4 plan
depends on: ``tailoring_records`` (one row per tailoring attempt) and
``cost_ledger`` (one row per Claude API call, for budget enforcement).

Also adds ``tailoring_intensity`` to the ``settings`` table. Like the
Phase 2 migration, new columns on ``settings`` carry a ``server_default``
because SQLite requires a default for ``ALTER TABLE ... ADD COLUMN`` on
an existing row.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_phase4_tailoring"
down_revision: Union[str, None] = "0003_phase3_discovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- TailoringRecord table ---
    op.create_table(
        "tailoring_records",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "intensity",
            sa.String(),
            nullable=False,
            server_default=sa.text("'balanced'"),
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("base_resume_path", sa.String(), nullable=False),
        sa.Column("tailored_resume_path", sa.String(), nullable=True),
        sa.Column("cover_letter_path", sa.String(), nullable=True),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cache_read_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cache_write_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "estimated_cost_dollars",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column("validation_passed", sa.Boolean(), nullable=True),
        sa.Column(
            "validation_warnings",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("prompt_hash", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_tailoring_records_job_id", "tailoring_records", ["job_id"]
    )

    # --- CostLedger table ---
    op.create_table(
        "cost_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "tailoring_record_id",
            sa.Integer(),
            sa.ForeignKey("tailoring_records.id"),
            nullable=True,
        ),
        sa.Column("call_type", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cache_read_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cache_write_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_dollars",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_cost_ledger_month", "cost_ledger", ["month"])

    # --- Settings.tailoring_intensity column ---
    op.add_column(
        "settings",
        sa.Column(
            "tailoring_intensity",
            sa.String(),
            nullable=False,
            server_default=sa.text("'balanced'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "tailoring_intensity")
    op.drop_index("ix_cost_ledger_month", table_name="cost_ledger")
    op.drop_table("cost_ledger")
    op.drop_index("ix_tailoring_records_job_id", table_name="tailoring_records")
    op.drop_table("tailoring_records")
