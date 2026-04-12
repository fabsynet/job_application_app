"""Frozen per-run context passed explicitly through every pipeline stage.

RESEARCH.md Pattern 4: RunContext is a frozen dataclass (NOT a ContextVar)
because explicit is better than implicit. Every Phase 2+ stage must accept
``ctx: RunContext`` as an argument and gate outbound side effects on
``ctx.dry_run`` before any write.

Why frozen: the snapshot semantics documented in CONTEXT.md require that a
mid-run toggle of ``Settings.dry_run`` does NOT retroactively relabel the
in-flight run. A frozen dataclass makes that impossible to violate — once the
scheduler samples the Settings row at run-start and constructs the context,
no downstream code can mutate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RunContext:
    """Per-run immutable context captured at the start of :meth:`run_pipeline`.

    Attributes:
        run_id: Primary key of the ``runs`` row created for this execution.
        started_at: UTC timestamp at which the context was constructed.
        dry_run: Snapshot of ``Settings.dry_run``. Downstream stages MUST check
            this before any outbound side effect.
        triggered_by: One of ``"scheduler"`` | ``"manual"`` | ``"wizard"``.
        tz: The IANA timezone string the scheduler is configured with. Used
            by the rate limiter and log timestamps.
    """

    run_id: int
    started_at: datetime
    dry_run: bool
    triggered_by: str
    tz: str


__all__ = ["RunContext"]
