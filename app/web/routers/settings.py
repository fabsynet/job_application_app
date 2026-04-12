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

from app.db.models import Profile, Secret
from app.settings.service import (
    get_profile_row,
    get_settings_row,
    set_setting,
    update_profile,
)
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
    "profile": ("partials/settings_profile.html.j2", "Profile"),
    "resume": ("partials/settings_placeholder.html.j2", "Resume"),
    "keywords": ("partials/settings_keywords.html.j2", "Keywords"),
    "threshold": ("partials/settings_placeholder.html.j2", "Threshold"),
    "credentials": ("partials/settings_credentials.html.j2", "Credentials"),
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

    # Section-specific context enrichment
    if section_name == "keywords":
        raw = row.keywords_csv or ""
        ctx["keywords"] = [k for k in raw.split("|") if k]

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


# ── Section partial loaders ───────────────────────────────────────────
# Specific section routes MUST be declared before the catch-all
# ``/section/{section_name}`` so FastAPI matches them first.

# ── Profile ──────────────────────────────────────────────────────────

@router.get("/section/profile", response_class=HTMLResponse)
async def get_profile_section(
    request: Request,
    session=Depends(get_session),
):
    """Load the profile form with current values."""
    profile = await get_profile_row(session)
    return templates.TemplateResponse(
        request,
        "partials/settings_profile.html.j2",
        {"profile": profile, "active_section": "profile"},
    )


# ── Keywords ─────────────────────────────────────────────────────────

@router.get("/section/keywords", response_class=HTMLResponse)
async def get_keywords_section(
    request: Request,
    session=Depends(get_session),
):
    """Load the keywords chip UI."""
    return await _render_section(request, session, "keywords")


@router.post("/keywords", response_class=HTMLResponse)
async def add_keyword(
    request: Request,
    keyword: str = Form(...),
    session=Depends(get_session),
):
    """Add a keyword to the pipe-delimited list."""
    keyword = keyword.strip()
    if not keyword:
        return await _render_section(
            request, session, "keywords",
            flash=("error", "Keyword cannot be blank."),
        )

    row = await get_settings_row(session)
    existing = [k for k in (row.keywords_csv or "").split("|") if k]

    if keyword.lower() in [k.lower() for k in existing]:
        return await _render_section(
            request, session, "keywords",
            flash=("error", f"Keyword \"{keyword}\" already exists."),
        )

    if len(existing) >= 50:
        return await _render_section(
            request, session, "keywords",
            flash=("error", "Maximum 50 keywords reached."),
        )

    existing.append(keyword)
    await set_setting(session, "keywords_csv", "|".join(existing))
    return await _render_section(
        request, session, "keywords",
        flash=("success", f"Added \"{keyword}\"."),
    )


@router.delete("/keywords/{keyword:path}", response_class=HTMLResponse)
async def remove_keyword(
    keyword: str,
    request: Request,
    session=Depends(get_session),
):
    """Remove a keyword from the pipe-delimited list."""
    row = await get_settings_row(session)
    existing = [k for k in (row.keywords_csv or "").split("|") if k]
    existing = [k for k in existing if k != keyword]
    await set_setting(session, "keywords_csv", "|".join(existing))
    return await _render_section(request, session, "keywords")


# ── Credentials ─────────────────────────────────────────────────────

@router.get("/section/credentials", response_class=HTMLResponse)
async def get_credentials_section(
    request: Request,
    session=Depends(get_session),
):
    """Load credentials form with configured/not-set status indicators."""
    names = await _secret_names(session)
    return templates.TemplateResponse(
        request,
        "partials/settings_credentials.html.j2",
        {
            "active_section": "credentials",
            "anthropic_configured": "anthropic_api_key" in names,
            "smtp_configured": all(
                n in names for n in ("smtp_host", "smtp_port", "smtp_user", "smtp_password")
            ),
        },
    )


# ── Generic section loader (catch-all — keep last among GET /section/*) ──

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


# ── Profile POST ─────────────────────────────────────────────────────

@router.post("/profile", response_class=HTMLResponse)
async def save_profile(
    request: Request,
    full_name: str = Form(None),
    email: str = Form(None),
    phone: str = Form(None),
    address: str = Form(None),
    work_authorization: str = Form(None),
    salary_expectation: str = Form(None),
    years_experience: str = Form(None),
    linkedin_url: str = Form(None),
    github_url: str = Form(None),
    portfolio_url: str = Form(None),
    session=Depends(get_session),
):
    """Save all profile fields. All fields are optional."""
    import re

    # Light validation
    if email and email.strip() and "@" not in email:
        profile = await get_profile_row(session)
        return templates.TemplateResponse(
            request,
            "partials/settings_profile.html.j2",
            {
                "profile": profile,
                "active_section": "profile",
                "flash": ("error", "Email must contain '@'."),
            },
        )

    # Strip non-digits from phone if provided
    cleaned_phone = re.sub(r"\D", "", phone) if phone and phone.strip() else phone

    # Convert years_experience to int or None
    years_exp: int | None = None
    if years_experience and years_experience.strip():
        try:
            years_exp = int(years_experience)
        except ValueError:
            years_exp = None

    # Normalise empty strings to None for optional text fields
    def _or_none(v: str | None) -> str | None:
        return v.strip() if v and v.strip() else None

    await update_profile(
        session,
        full_name=_or_none(full_name),
        email=_or_none(email),
        phone=_or_none(cleaned_phone),
        address=_or_none(address),
        work_authorization=_or_none(work_authorization),
        salary_expectation=_or_none(salary_expectation),
        years_experience=years_exp,
        linkedin_url=_or_none(linkedin_url),
        github_url=_or_none(github_url),
        portfolio_url=_or_none(portfolio_url),
    )

    profile = await get_profile_row(session)
    return templates.TemplateResponse(
        request,
        "partials/settings_profile.html.j2",
        {
            "profile": profile,
            "active_section": "profile",
            "flash": ("success", "Profile saved."),
        },
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


# ── Credential save + validate ────────────────────────────────────────

async def _upsert_secret(session, vault, name: str, value: str) -> None:
    """Encrypt and upsert a single secret row."""
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


async def _render_credentials(
    request: Request,
    session,
    flash: tuple[str, str] | None = None,
) -> HTMLResponse:
    """Re-render the credentials partial with current status."""
    names = await _secret_names(session)
    ctx: dict = {
        "active_section": "credentials",
        "anthropic_configured": "anthropic_api_key" in names,
        "smtp_configured": all(
            n in names for n in ("smtp_host", "smtp_port", "smtp_user", "smtp_password")
        ),
    }
    if flash:
        ctx["flash"] = flash
    return templates.TemplateResponse(
        request, "partials/settings_credentials.html.j2", ctx,
    )


@router.post("/credentials/anthropic", response_class=HTMLResponse)
async def save_anthropic_credential(
    request: Request,
    api_key: str = Form(...),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    """Save Anthropic API key (encrypted), then validate it."""
    if not api_key or not api_key.strip():
        return await _render_credentials(
            request, session,
            flash=("error", "API key cannot be empty."),
        )

    api_key = api_key.strip()
    await _upsert_secret(session, vault, "anthropic_api_key", api_key)

    # Validate after saving — network failure must not prevent storage
    try:
        from app.credentials.validation import validate_anthropic_key

        valid, message = await validate_anthropic_key(api_key)
        level = "success" if valid else "error"
        return await _render_credentials(
            request, session,
            flash=(level, f"Saved. {message}"),
        )
    except Exception:
        return await _render_credentials(
            request, session,
            flash=("success", "Saved but validation encountered an error."),
        )


@router.post("/credentials/smtp", response_class=HTMLResponse)
async def save_smtp_credentials(
    request: Request,
    smtp_host: str = Form(...),
    smtp_port: int = Form(587),
    smtp_user: str = Form(...),
    smtp_password: str = Form(...),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    """Save all four SMTP credential fields (encrypted), then validate."""
    # Validate presence
    missing = []
    if not smtp_host or not smtp_host.strip():
        missing.append("host")
    if not smtp_user or not smtp_user.strip():
        missing.append("username")
    if not smtp_password or not smtp_password.strip():
        missing.append("password")
    if missing:
        return await _render_credentials(
            request, session,
            flash=("error", f"Missing required fields: {', '.join(missing)}."),
        )

    smtp_host = smtp_host.strip()
    smtp_user = smtp_user.strip()
    smtp_password = smtp_password.strip()

    # Save all four fields encrypted
    await _upsert_secret(session, vault, "smtp_host", smtp_host)
    await _upsert_secret(session, vault, "smtp_port", str(smtp_port))
    await _upsert_secret(session, vault, "smtp_user", smtp_user)
    await _upsert_secret(session, vault, "smtp_password", smtp_password)

    # Validate after saving
    try:
        from app.credentials.validation import validate_smtp_credentials

        valid, message = await validate_smtp_credentials(
            smtp_host, smtp_port, smtp_user, smtp_password,
        )
        level = "success" if valid else "error"
        return await _render_credentials(
            request, session,
            flash=(level, f"Saved. {message}"),
        )
    except Exception:
        return await _render_credentials(
            request, session,
            flash=("success", "Saved but validation encountered an error."),
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
