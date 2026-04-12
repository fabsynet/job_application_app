"""GET /health — scheduler state snapshot for readiness probes.

The dashboard reads this endpoint every few seconds via HTMX polling (plan
01-04) to render the live status card. It is deliberately tiny and
side-effect free — no DB writes, no task creation.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    """Return scheduler + kill-switch state.

    Returns ``{"status": "starting"}`` if the lifespan has not yet populated
    ``app.state.scheduler`` (e.g. during a test that enters the lifespan
    manually and races the first request).
    """
    svc = getattr(request.app.state, "scheduler", None)
    if svc is None:
        return {"status": "starting"}
    return {
        "status": "ok",
        "scheduler_running": svc.is_running(),
        "kill_switch": svc.killswitch.is_engaged(),
        "next_run_iso": svc.next_run_iso(),
    }


__all__ = ["router"]
