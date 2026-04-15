"""Phase 5 notifications router — single ack endpoint.

Hosts the dashboard ``POST /notifications/ack/{id}`` action that lets
the user mark a failure suppression row as ``cleared_by='user_ack'``,
re-arming the notification email channel for the next occurrence of
the same signature without waiting for the auto-clear path.

The endpoint returns a tiny HTML fragment so HTMX swap-on-click works
out of the box from the dashboard banner; non-HTMX callers can ignore
the body and rely on the 200 status.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.submission.suppression import ack_suppression
from app.web.deps import get_session

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/ack/{suppression_id}", response_class=HTMLResponse)
async def ack_notification(suppression_id: int, session=Depends(get_session)):
    """Mark a failure suppression row as user-acknowledged.

    Returns a minimal HTML fragment on success (200) so HTMX swap
    targets like ``hx-target="#notifications-banner"`` get a clean
    replacement. Returns 404 when the row id is unknown.
    """
    ok = await ack_suppression(session, suppression_id)
    if not ok:
        raise HTTPException(404, "suppression not found")
    return HTMLResponse("<div class='toast'>Acknowledged.</div>")


__all__ = ["router"]
