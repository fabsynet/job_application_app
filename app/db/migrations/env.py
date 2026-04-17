"""Alembic environment for the job-app Phase 1 schema.

Two runtime modes:
  * ``offline`` — emits DDL to stdout without a DB connection (used in CI
    and by the ``alembic upgrade head --sql`` verification).
  * ``online`` — connects to ``./data/app.db`` via the sync SQLite driver
    (Alembic runs its own migration transaction; async is unnecessary).

``include_object`` excludes any table whose name starts with ``apscheduler_``.
APScheduler 3.11's ``SQLAlchemyJobStore`` manages its own tables via
``Base.metadata.create_all`` at scheduler startup — mixing them into Alembic's
target metadata would cause spurious "drop table" diffs on every autogenerate.
See RESEARCH.md pitfall "APScheduler jobstore migration pain".
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Ensure the models module is imported so its tables register on
# SQLModel.metadata before Alembic inspects it.
from app.db import models  # noqa: F401

import os

config = context.config

# Allow overriding the DB URL via env var (e.g. in Docker where /data is an
# absolute mount point, not relative ./data).
if db_url := os.environ.get("ALEMBIC_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def include_object(
    object,  # noqa: A002 - Alembic API name
    name,
    type_,
    reflected,
    compare_to,
):
    """Filter APScheduler's own tables out of Alembic's view of the schema."""
    if type_ == "table" and name.startswith("apscheduler_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emits SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live SQLite database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
