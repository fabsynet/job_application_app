"""Phase 3: Sources, Jobs, DiscoveryRunStats tables.

Revision ID: 0003_phase3_discovery
Revises: 0002_phase2_config
Create Date: 2026-04-12

Creates the three discovery tables that every subsequent Phase 3 plan
depends on: ``sources`` (ATS boards), ``jobs`` (normalised postings),
and ``discovery_run_stats`` (per-source counts for anomaly detection).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_phase3_discovery"
down_revision: Union[str, None] = "0002_phase2_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Sources table ---
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("last_fetch_status", sa.String(), nullable=True),
        sa.Column("last_error_message", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_sources_slug", "sources", ["slug"])

    # --- Jobs table ---
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column(
            "location",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "description",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "description_html",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id"),
            nullable=True,
        ),
        sa.Column("posted_date", sa.DateTime(), nullable=True),
        sa.Column(
            "score",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "matched_keywords",
            sa.String(),
            nullable=False,
            server_default=sa.text("''"),
        ),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'discovered'"),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_jobs_fingerprint", "jobs", ["fingerprint"], unique=True)
    op.create_index("ix_jobs_company", "jobs", ["company"])

    # --- DiscoveryRunStats table ---
    op.create_table(
        "discovery_run_stats",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.id"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id"),
            nullable=False,
        ),
        sa.Column(
            "discovered_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "matched_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_discovery_run_stats_run_id", "discovery_run_stats", ["run_id"]
    )
    op.create_index(
        "ix_discovery_run_stats_source_id", "discovery_run_stats", ["source_id"]
    )


def downgrade() -> None:
    op.drop_table("discovery_run_stats")
    op.drop_table("jobs")
    op.drop_table("sources")
