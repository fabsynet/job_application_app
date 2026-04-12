"""First-run setup wizard: resume upload -> API keys -> keywords.

Per CONTEXT.md the wizard is *guidance, not a gate*:

* Fresh ``./data`` boots with ``Settings.wizard_complete=False``; the dashboard
  handler detects this and redirects to ``/setup/1``.
* ``POST /setup/skip`` flips the flag without any user input — users who know
  what they are doing can walk straight to the dashboard.
* Step 2 accepts blank fields (operators may configure via the Settings page
  later); only submitted, non-empty values are upserted into ``Secret``.

The wizard writes ``wizard_complete=True`` exactly in two places: step 3 POST
(happy path) and ``/setup/skip`` POST. Going back and forth between steps does
not flip the flag, so an abandoned wizard on a container restart still
redirects to ``/setup/1``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Secret
from app.settings.service import get_settings_row, set_setting
from app.web.deps import get_session, get_vault

router = APIRouter(prefix="/setup")

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


@router.post("/skip")
async def skip_wizard(session=Depends(get_session)):
    """Mark the wizard complete without any user input and redirect to /."""
    await set_setting(session, "wizard_complete", True)
    return RedirectResponse("/", status_code=303)


@router.get("/1", response_class=HTMLResponse)
async def step1_get(request: Request, session=Depends(get_session)):
    cfg = get_settings()
    uploads = cfg.data_dir / "uploads"
    existing = (uploads / "resume_base.docx").exists()
    return templates.TemplateResponse(
        request,
        "wizard/step_1_resume.html.j2",
        {"step": 1, "existing": existing},
    )


@router.post("/1")
async def step1_post(
    request: Request,
    resume: UploadFile = File(...),
    session=Depends(get_session),
):
    """Store the uploaded DOCX at ``data_dir/uploads/resume_base.docx``."""
    if not resume.filename or not resume.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="resume must be a .docx file")
    content = await resume.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="empty upload")
    cfg = get_settings()
    uploads = cfg.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    target = uploads / "resume_base.docx"
    target.write_bytes(content)
    # Touch updated_at on the Settings row so the dashboard "last touched"
    # timestamp reflects wizard activity.
    await set_setting(session, "updated_at", datetime.utcnow())
    return RedirectResponse("/setup/2", status_code=303)


@router.get("/2", response_class=HTMLResponse)
async def step2_get(request: Request, session=Depends(get_session)):
    names = [
        r[0]
        for r in (
            await session.execute(select(Secret.name).order_by(Secret.name))
        ).all()
    ]
    return templates.TemplateResponse(
        request,
        "wizard/step_2_secrets.html.j2",
        {"step": 2, "stored": names},
    )


@router.post("/2")
async def step2_post(
    request: Request,
    anthropic_api_key: str = Form(""),
    smtp_host: str = Form(""),
    smtp_port: str = Form(""),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    """Upsert any non-empty credential fields as encrypted Secret rows.

    Every field is optional (the wizard is guidance, not a gate). Empty
    fields are silently skipped — users can fill them on the Settings page
    later. Non-empty values go through :meth:`FernetVault.encrypt`, which
    auto-registers the plaintext with the log scrubber BEFORE returning the
    ciphertext, so nothing between here and the DB commit can leak them.
    """
    fields = {
        "anthropic_api_key": anthropic_api_key,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
    }
    for name, value in fields.items():
        if not value:
            continue
        ciphertext = vault.encrypt(value)
        existing = (
            await session.execute(select(Secret).where(Secret.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            existing.ciphertext = ciphertext
            existing.updated_at = datetime.utcnow()
        else:
            session.add(Secret(name=name, ciphertext=ciphertext))
    await session.commit()
    return RedirectResponse("/setup/3", status_code=303)


@router.get("/3", response_class=HTMLResponse)
async def step3_get(request: Request, session=Depends(get_session)):
    row = await get_settings_row(session)
    # Pre-fill: CSV on disk -> newline-separated in textarea.
    pre = "\n".join(k for k in (row.keywords_csv or "").split(",") if k)
    return templates.TemplateResponse(
        request,
        "wizard/step_3_keywords.html.j2",
        {"step": 3, "keywords_text": pre},
    )


@router.post("/3")
async def step3_post(
    keywords: str = Form(""),
    session=Depends(get_session),
):
    """Persist keywords (one-per-line -> CSV) and flip wizard_complete."""
    lines = [ln.strip() for ln in keywords.splitlines() if ln.strip()]
    csv = ",".join(lines)
    await set_setting(session, "keywords_csv", csv)
    await set_setting(session, "wizard_complete", True)
    return RedirectResponse("/", status_code=303)


__all__ = ["router"]
