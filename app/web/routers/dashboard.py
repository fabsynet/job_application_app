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

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db.models import Run, Secret
from app.discovery.models import DiscoveryRunStats, Source
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


async def _get_discovery_context(session, request: Request) -> dict:
    """Build discovery summary + anomaly banner context from the latest run.

    Queries the most recent completed Run that has discovery counts, then
    joins DiscoveryRunStats with Source for per-source breakdown.  Anomaly
    dismissal uses a simple cookie keyed on the run_id that produced the
    anomaly.
    """
    # Find latest completed run with counts
    stmt = (
        select(Run)
        .where(Run.status == "succeeded")
        .order_by(Run.ended_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    latest_run = result.scalar_one_or_none()

    if latest_run is None or not latest_run.counts:
        return {
            "discovery_summary": None,
            "anomaly_warnings": [],
            "show_anomaly_banner": False,
        }

    counts = latest_run.counts or {}

    # Per-source stats from DiscoveryRunStats table
    stats_stmt = (
        select(DiscoveryRunStats, Source)
        .outerjoin(Source, DiscoveryRunStats.source_id == Source.id)
        .where(DiscoveryRunStats.run_id == latest_run.id)
        .order_by(DiscoveryRunStats.id)
    )
    stats_result = await session.execute(stats_stmt)
    rows = stats_result.all()

    sources_summary = []
    total_discovered = 0
    total_matched = 0
    for stat, source in rows:
        sources_summary.append({
            "slug": source.slug if source else "unknown",
            "source_type": source.source_type if source else "unknown",
            "display_name": source.display_name if source else None,
            "discovered": stat.discovered_count,
            "matched": stat.matched_count,
            "error": stat.error,
        })
        total_discovered += stat.discovered_count
        total_matched += stat.matched_count

    discovery_summary = {
        "sources": sources_summary,
        "total_discovered": total_discovered,
        "total_matched": total_matched,
    } if sources_summary else None

    # Anomaly warnings
    anomalies = counts.get("anomalies", [])
    anomaly_warnings = []
    for a in anomalies:
        anomaly_warnings.append(
            f"Source \"{a.get('slug', '?')}\" returned {a.get('today_count', 0)} jobs "
            f"(7-day avg: {a.get('rolling_avg', '?')}). This is below 20% threshold."
        )

    # Dismiss logic: cookie stores run_id of last dismissed anomaly
    dismissed_run_id = request.cookies.get("dismissed_anomaly_run_id", "")
    show_banner = bool(anomaly_warnings) and str(latest_run.id) != dismissed_run_id

    return {
        "discovery_summary": discovery_summary,
        "anomaly_warnings": anomaly_warnings,
        "show_anomaly_banner": show_banner,
        "_anomaly_run_id": str(latest_run.id) if anomaly_warnings else None,
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
    discovery_ctx = await _get_discovery_context(session, request)
    ctx.update(discovery_ctx)
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


@router.post("/dismiss-anomaly", response_class=HTMLResponse)
async def dismiss_anomaly(
    request: Request,
    session=Depends(get_session),
):
    """Dismiss the anomaly banner by setting a cookie with the current run_id.

    The banner will not reappear until a new run produces a fresh anomaly.
    Returns empty HTML so hx-swap="delete" removes the banner element.
    """
    # Find the latest run with anomalies to store its ID
    stmt = (
        select(Run)
        .where(Run.status == "succeeded")
        .order_by(Run.ended_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    latest_run = result.scalar_one_or_none()

    response = Response(content="", media_type="text/html")
    if latest_run is not None:
        response.set_cookie(
            key="dismissed_anomaly_run_id",
            value=str(latest_run.id),
            httponly=True,
            samesite="lax",
        )
    return response


__all__ = ["router"]
