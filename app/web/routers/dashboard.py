"""Dashboard router: home page + HTMX polling fragments + force-run trigger.

The dashboard is the Phase 1 landing surface per CONTEXT.md:

* GET ``/`` renders the full status card (scheduler state, next run, last run
  counts, recent runs table, kill-switch + dry-run toggles).
* GET ``/fragments/status`` returns the tiny colored status pill — polled
  every 5 seconds by the dashboard when the tab is visible.
* GET ``/fragments/next-run`` returns the humanised countdown — polled every
  15 seconds.
* POST ``/runs/trigger`` fires the pipeline as a background asyncio task
  (fire-and-forget) and re-renders the status pill so the user sees the
  ``Running`` state immediately.

The ``_humanize_seconds`` helper runs server-side so there is no client-side
JavaScript timer competing with HTMX polling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.runs.service import list_recent_runs
from app.settings.service import get_settings_row
from app.web.deps import get_killswitch, get_scheduler, get_session

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


def _humanize_seconds(iso_next: Optional[str]) -> Optional[str]:
    """Turn an ISO-8601 timestamp into a compact ``1h 3m`` / ``47m 12s`` string.

    Returns ``None`` if the input is falsy or unparseable, which the template
    renders as ``No scheduled run``. Negative deltas (job is overdue) collapse
    to ``any moment`` so the UI never shows a negative countdown.
    """
    if not iso_next:
        return None
    try:
        nxt = datetime.fromisoformat(iso_next)
    except ValueError:
        return None
    now = datetime.now(nxt.tzinfo or timezone.utc)
    delta = (nxt - now).total_seconds()
    if delta < 0:
        return "any moment"
    m, s = divmod(int(delta), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


async def _common_ctx(request, session, svc, ks) -> dict:
    """Assemble the context dict every dashboard template needs.

    One shared builder keeps the status pill, next-run fragment, and full
    dashboard page in lock-step so polled fragments never drift from the
    initial page render.
    """
    row = await get_settings_row(session)
    runs = await list_recent_runs(session, limit=50)
    last_run = runs[0] if runs else None
    return {
        "request": request,
        "killed": ks.is_engaged(),
        "paused": False,
        "dry_run": row.dry_run,
        "kill_engaged": ks.is_engaged(),
        "next_run_human": _humanize_seconds(svc.next_run_iso()),
        "last_run": last_run,
        "recent_runs": runs,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("dashboard.html.j2", ctx)


@router.get("/fragments/status", response_class=HTMLResponse)
async def status_pill(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("partials/status_pill.html.j2", ctx)


@router.get("/fragments/next-run", response_class=HTMLResponse)
async def next_run_fragment(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("partials/next_run.html.j2", ctx)


@router.post("/runs/trigger", response_class=HTMLResponse)
async def trigger_run(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    """Fire-and-forget manual run trigger.

    The ``asyncio.create_task`` handoff is intentional: the HTTP response
    must return in a handful of milliseconds so HTMX can re-render the
    status pill, while the pipeline body runs on the same event loop in
    the background.
    """
    asyncio.create_task(svc.run_pipeline(triggered_by="manual"))
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("partials/status_pill.html.j2", ctx)


__all__ = ["router"]
