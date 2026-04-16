"""Saved Answers CRUD router for the Settings UI.

Exposes list, edit, and delete operations on SavedAnswer rows.
All endpoints return HTMX-swappable partials so the settings page
updates in place without a full page reload.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.learning.service import (
    delete_saved_answer,
    get_all_saved_answers,
    update_saved_answer,
)
from app.web.deps import get_session

router = APIRouter(prefix="/settings/saved-answers")

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


async def _render_saved_answers(
    request: Request,
    session,
    flash: tuple[str, str] | None = None,
) -> HTMLResponse:
    """Fetch all saved answers and render the partial."""
    answers = await get_all_saved_answers(session)
    ctx: dict = {
        "answers": answers,
        "active_section": "saved-answers",
    }
    if flash:
        ctx["flash"] = flash
    return templates.TemplateResponse(
        request, "partials/settings_saved_answers.html.j2", ctx
    )


@router.get("", response_class=HTMLResponse)
async def list_saved_answers(
    request: Request,
    session=Depends(get_session),
) -> HTMLResponse:
    """Render the saved answers management section."""
    return await _render_saved_answers(request, session)


@router.post("/{answer_id}/edit", response_class=HTMLResponse)
async def edit_saved_answer(
    answer_id: int,
    request: Request,
    answer_text: str = Form(...),
    session=Depends(get_session),
) -> HTMLResponse:
    """Update a saved answer's text and re-render the list."""
    result = await update_saved_answer(session, answer_id, answer_text)
    if result is None:
        raise HTTPException(status_code=404, detail="Saved answer not found")
    await session.commit()
    return await _render_saved_answers(
        request, session, flash=("success", "Answer updated.")
    )


@router.post("/{answer_id}/delete", response_class=HTMLResponse)
async def delete_saved_answer_route(
    answer_id: int,
    request: Request,
    session=Depends(get_session),
) -> HTMLResponse:
    """Delete a saved answer and re-render the list."""
    deleted = await delete_saved_answer(session, answer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved answer not found")
    await session.commit()
    return await _render_saved_answers(
        request, session, flash=("success", "Answer deleted.")
    )


__all__ = ["router"]
