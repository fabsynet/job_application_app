"""Runs subsystem — RunContext and Run row service.

Phases 2+ consume :class:`RunContext` as the per-run immutable contract. The
service functions are the only path that writes to the ``runs`` table.
"""

from app.runs.context import RunContext
from app.runs.service import (
    create_run,
    finalize_run,
    list_recent_runs,
    mark_orphans_failed,
    mark_run_killed,
)

__all__ = [
    "RunContext",
    "create_run",
    "finalize_run",
    "list_recent_runs",
    "mark_orphans_failed",
    "mark_run_killed",
]
