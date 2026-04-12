"""Phase 2: Settings columns + Profile table.

Revision ID: 0002_phase2_config
Revises: 0001_initial
Create Date: 2026-04-12

Adds Phase 2 configuration columns to the settings table (mode, threshold,
schedule, budget, resume metadata) and creates the profile table for
auto-filling application forms.

All new columns on ``settings`` carry a ``server_default`` because SQLite
requires a default for ``ALTER TABLE ... ADD COLUMN`` on an existing row.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_phase2_config"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New Settings columns ---
    op.add_column(
        "settings",
        sa.Column(
            "match_threshold",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "schedule_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "quiet_hours_start",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("22"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "quiet_hours_end",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("7"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "budget_cap_dollars",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "budget_spent_dollars",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "budget_month",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "auto_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "resume_filename",
            sa.String(),
            nullable=True,
        ),
    )
    op.add_column(
        "settings",
        sa.Column(
            "resume_uploaded_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    # --- Profile table ---
    op.create_table(
        "profile",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("work_authorization", sa.String(), nullable=True),
        sa.Column("salary_expectation", sa.String(), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("linkedin_url", sa.String(), nullable=True),
        sa.Column("github_url", sa.String(), nullable=True),
        sa.Column("portfolio_url", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    op.drop_table("profile")

    op.drop_column("settings", "resume_uploaded_at")
    op.drop_column("settings", "resume_filename")
    op.drop_column("settings", "auto_mode")
    op.drop_column("settings", "budget_month")
    op.drop_column("settings", "budget_spent_dollars")
    op.drop_column("settings", "budget_cap_dollars")
    op.drop_column("settings", "quiet_hours_end")
    op.drop_column("settings", "quiet_hours_start")
    op.drop_column("settings", "schedule_enabled")
    op.drop_column("settings", "match_threshold")
