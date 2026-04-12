"""Kill-switch and dry-run toggle routes.

Both toggles are HTMX-driven forms on the dashboard partial. POSTing either
route flips the corresponding flag (the kill-switch also cancels any
in-flight run via ``KillSwitch.engage``) and re-renders the shared toggles
partial. The dashboard's status pill picks up the new state on its next
5-second poll, so the user sees the full consequence of a click within
at most 5 seconds.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.settings.service import get_settings_row, set_setting
from app.web.deps import get_killswitch, get_scheduler, get_session

router = APIRouter(prefix="/toggles")

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


async def _toggles_ctx(request: Request, session, ks) -> dict:
    row = await get_settings_row(session)
    return {
        "kill_engaged": ks.is_engaged(),
        "dry_run": row.dry_run,
    }


@router.post("/kill-switch", response_class=HTMLResponse)
async def toggle_kill(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    """Flip the kill-switch. Engaging cancels any in-flight run immediately.

    Release resumes the scheduler job. Both paths persist to ``Settings``
    so a container restart hydrates into the correct state.
    """
    if ks.is_engaged():
        await ks.release(svc, session)
    else:
        await ks.engage(svc, session)
    ctx = await _toggles_ctx(request, session, ks)
    return templates.TemplateResponse(request, "partials/toggles.html.j2", ctx)


@router.post("/dry-run", response_class=HTMLResponse)
async def toggle_dry_run(
    request: Request,
    session=Depends(get_session),
    svc=Depends(get_scheduler),
    ks=Depends(get_killswitch),
):
    """Flip the ``Settings.dry_run`` flag.

    Takes effect on the next scheduled run (the RunContext frozen at
    pipeline entry snapshots the flag, so an in-flight run is not affected).
    """
    row = await get_settings_row(session)
    await set_setting(session, "dry_run", not row.dry_run)
    ctx = await _toggles_ctx(request, session, ks)
    return templates.TemplateResponse(request, "partials/toggles.html.j2", ctx)


__all__ = ["router"]
