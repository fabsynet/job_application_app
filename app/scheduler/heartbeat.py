"""Hourly heartbeat job registered with APScheduler's CronTrigger.

APScheduler invokes the job coroutine as a standalone function — it does not
have access to FastAPI's request scope or ``app.state``. So we use a
module-level setter that the lifespan calls at startup, binding the singleton
:class:`SchedulerService` to the heartbeat closure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from app.scheduler.service import SchedulerService

log = structlog.get_logger(__name__)

_scheduler_service: Optional["SchedulerService"] = None


def set_scheduler_service(service: "SchedulerService") -> None:
    """Bind the singleton SchedulerService for :func:`heartbeat_job` to consume.

    Called during lifespan startup exactly once.
    """
    global _scheduler_service
    _scheduler_service = service


def get_scheduler_service() -> Optional["SchedulerService"]:
    return _scheduler_service


async def heartbeat_job() -> None:
    """Entry point invoked by APScheduler's CronTrigger(minute=0).

    Delegates to :meth:`SchedulerService.run_pipeline` with
    ``triggered_by="scheduler"``. All exception handling is inside
    run_pipeline — we just log and swallow here so the APScheduler worker
    stays healthy for the next tick.
    """
    svc = get_scheduler_service()
    if svc is None:
        log.error("heartbeat_no_scheduler_service")
        return
    try:
        await svc.run_pipeline(triggered_by="scheduler")
    except Exception as e:  # noqa: BLE001
        log.exception("heartbeat_failed", error=str(e))


__all__ = ["heartbeat_job", "set_scheduler_service", "get_scheduler_service"]
