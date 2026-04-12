"""Settings page: sidebar-navigated configuration hub.

The settings page is the single entry point for all configuration. It renders
a sidebar with section links and a content area that loads section partials
via HTMX. Existing secrets CRUD and rate-limit endpoints are preserved.

Sections implemented in this plan: Mode, Rate Limits, Safety.
Sections coming in later plans: Profile, Resume, Keywords, Threshold,
Credentials, Schedule, Budget.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models import Secret
from app.settings.service import get_settings_row, set_setting
from app.web.deps import get_rate_limiter, get_session, get_vault

router = APIRouter(prefix="/settings")

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)

# Canonical well-known secret names the UI renders as a checklist.
KNOWN_SECRET_NAMES = [
    "anthropic_api_key",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
]

# Section name -> (template path, display title)
_SECTION_MAP: dict[str, tuple[str, str]] = {
    "mode": ("partials/settings_mode.html.j2", "Mode"),
    "profile": ("partials/settings_placeholder.html.j2", "Profile"),
    "resume": ("partials/settings_placeholder.html.j2", "Resume"),
    "keywords": ("partials/settings_placeholder.html.j2", "Keywords"),
    "threshold": ("partials/settings_placeholder.html.j2", "Threshold"),
    "credentials": ("partials/settings_placeholder.html.j2", "Credentials"),
    "schedule": ("partials/settings_placeholder.html.j2", "Schedule"),
    "budget": ("partials/settings_placeholder.html.j2", "Budget"),
    "limits": ("partials/settings_limits.html.j2", "Rate Limits"),
    "safety": ("partials/settings_safety.html.j2", "Safety"),
}


async def _secret_names(session) -> list[str]:
    result = await session.execute(select(Secret.name).order_by(Secret.name))
    return [r[0] for r in result.all()]


async def _render_section(
    request: Request,
    session,
    section_name: str,
    flash: tuple[str, str] | None = None,
) -> HTMLResponse:
    """Build context and render the appropriate section partial."""
    if section_name not in _SECTION_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_name}")

    template_path, title = _SECTION_MAP[section_name]
    row = await get_settings_row(session)

    ctx: dict = {
        "settings": row,
        "section_title": title,
        "active_section": section_name,
    }
    if flash:
        ctx["flash"] = flash

    return templates.TemplateResponse(request, template_path, ctx)


# ── Main settings page ────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, session=Depends(get_session)):
    row = await get_settings_row(session)
    names = await _secret_names(session)
    default_section = "mode"
    template_path, title = _SECTION_MAP[default_section]
    return templates.TemplateResponse(
        request,
        "settings.html.j2",
        {
            "settings": row,
            "known_names": KNOWN_SECRET_NAMES,
            "stored_names": names,
            "active_section": default_section,
            "section_template": template_path,
            "section_title": title,
        },
    )


# ── Section partial loader ────────────────────────────────────────────

@router.get("/section/{section_name}", response_class=HTMLResponse)
async def get_section(
    section_name: str,
    request: Request,
    session=Depends(get_session),
):
    return await _render_section(request, session, section_name)


# ── Mode ──────────────────────────────────────────────────────────────

@router.post("/mode", response_class=HTMLResponse)
async def save_mode(
    request: Request,
    auto_mode: str = Form(...),
    session=Depends(get_session),
):
    value = auto_mode.lower() == "true"
    await set_setting(session, "auto_mode", value)
    return await _render_section(
        request, session, "mode",
        flash=("success", "Application mode saved."),
    )


# ── Rate Limits ───────────────────────────────────────────────────────

@router.post("/limits", response_class=HTMLResponse)
async def save_limits(
    request: Request,
    daily_cap: int = Form(...),
    delay_min_seconds: int = Form(...),
    delay_max_seconds: int = Form(...),
    timezone: str = Form(...),
    session=Depends(get_session),
    rate_limiter=Depends(get_rate_limiter),
):
    """Persist new rate-limit envelope AND update the live RateLimiter.

    Validates the same ranges the ``RateLimiter.__init__`` constructor
    checks so a rejected form does not leave the DB in a state that would
    crash the scheduler at next restart.
    """
    if daily_cap < 0 or daily_cap > 10000:
        raise HTTPException(400, "daily_cap out of range")
    if delay_min_seconds <= 0:
        raise HTTPException(400, "delay_min must be > 0")
    if delay_max_seconds <= delay_min_seconds:
        raise HTTPException(400, "delay_max must be > delay_min")
    if delay_max_seconds > 600:
        raise HTTPException(400, "delay_max must be <= 600")
    try:
        tz_obj = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as e:
        raise HTTPException(400, f"unknown timezone: {timezone}") from e

    await set_setting(session, "daily_cap", daily_cap)
    await set_setting(session, "delay_min_seconds", delay_min_seconds)
    await set_setting(session, "delay_max_seconds", delay_max_seconds)
    await set_setting(session, "timezone", timezone)

    # Live update the in-memory RateLimiter so the change takes effect
    # on the next pipeline run without restarting the process.
    rate_limiter.daily_cap = daily_cap
    rate_limiter.delay_min = delay_min_seconds
    rate_limiter.delay_max = delay_max_seconds
    rate_limiter.tz = tz_obj

    return await _render_section(
        request, session, "limits",
        flash=("success", "Rate limits saved."),
    )


# ── Safety ────────────────────────────────────────────────────────────

@router.post("/safety", response_class=HTMLResponse)
async def save_safety(
    request: Request,
    session=Depends(get_session),
):
    """Save kill-switch and dry-run toggles.

    Checkboxes only send a value when checked, so absence means False.
    We parse the raw form data to handle this correctly.
    """
    form = await request.form()
    kill_switch = form.get("kill_switch", "false").lower() == "true"
    dry_run = form.get("dry_run", "false").lower() == "true"

    await set_setting(session, "kill_switch", kill_switch)
    await set_setting(session, "dry_run", dry_run)

    return await _render_section(
        request, session, "safety",
        flash=("success", "Safety settings saved."),
    )


# ── Secrets CRUD (preserved from Phase 1) ─────────────────────────────

@router.post("/secrets", response_class=HTMLResponse)
async def save_secret(
    request: Request,
    name: str = Form(...),
    value: str = Form(...),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    """Upsert one Secret row. Plaintext is registered with the log scrubber."""
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="empty secret name")
    if not value:
        raise HTTPException(status_code=400, detail="empty secret value")
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
    names = await _secret_names(session)
    return templates.TemplateResponse(
        request,
        "partials/secrets_list.html.j2",
        {"stored_names": names, "known_names": KNOWN_SECRET_NAMES},
    )


@router.delete("/secrets/{name}", response_class=HTMLResponse)
async def delete_secret(name: str, request: Request, session=Depends(get_session)):
    await session.execute(sql_delete(Secret).where(Secret.name == name))
    await session.commit()
    names = await _secret_names(session)
    return templates.TemplateResponse(
        request,
        "partials/secrets_list.html.j2",
        {"stored_names": names, "known_names": KNOWN_SECRET_NAMES},
    )


__all__ = ["router"]
