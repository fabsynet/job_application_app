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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db.models import Secret
from app.runs.service import list_recent_runs
from app.security.fernet import InvalidFernetKey
from app.settings.service import get_settings_row
from app.web.deps import get_killswitch, get_scheduler, get_session, get_vault

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
        "killed": ks.is_engaged(),
        "paused": False,
        "dry_run": row.dry_run,
        "kill_engaged": ks.is_engaged(),
        "next_run_human": _humanize_seconds(svc.next_run_iso()),
        "last_run": last_run,
        "recent_runs": runs,
        "rotation_banner": None,
    }


async def _detect_rotation(session, vault) -> Optional[str]:
    """Return a banner string if any stored Secret fails to decrypt.

    Used only by the full dashboard page render (not by HTMX fragments) to
    avoid re-running the decrypt probe on every 5-second poll. Stored rows
    that fail are preserved in the DB — the banner is remediation, not
    auto-deletion.
    """
    result = await session.execute(select(Secret).limit(1))
    sample = result.scalar_one_or_none()
    if sample is None:
        return None
    try:
        vault.decrypt(sample.ciphertext)
    except InvalidFernetKey:
        return (
            "Stored secrets cannot be decrypted. The FERNET_KEY appears to "
            "have changed since these secrets were saved. Re-enter your API "
            "keys and credentials in Settings to restore them."
        )
    return None


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
    vault=Depends(get_vault),
):
    """Full dashboard render with wizard guard + rotation banner detection.

    Guard: fresh ``./data`` boots with ``Settings.wizard_complete=False``;
    this redirects to ``/setup/1`` so the user walks through the wizard on
    first arrival. ``POST /setup/skip`` or completing step 3 flips the flag
    and this handler then serves the full dashboard.
    """
    row = await get_settings_row(session)
    if not row.wizard_complete:
        return RedirectResponse("/setup/1", status_code=307)
    ctx = await _common_ctx(request, session, svc, ks)
    ctx["rotation_banner"] = await _detect_rotation(session, vault)
    return templates.TemplateResponse(request, "dashboard.html.j2", ctx)


@router.get("/fragments/status", response_class=HTMLResponse)
async def status_pill(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse(request, "partials/status_pill.html.j2", ctx)


@router.get("/fragments/next-run", response_class=HTMLResponse)
async def next_run_fragment(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse(request, "partials/next_run.html.j2", ctx)


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
    return templates.TemplateResponse(request, "partials/status_pill.html.j2", ctx)


__all__ = ["router"]
