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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models import Profile, Secret
from app.resume.service import extract_resume_text, get_resume_path, save_resume
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
    "resume": ("partials/settings_resume.html.j2", "Resume"),
    "keywords": ("partials/settings_keywords.html.j2", "Keywords"),
    "threshold": ("partials/settings_threshold.html.j2", "Threshold"),
    "credentials": ("partials/settings_credentials.html.j2", "Credentials"),
    "schedule": ("partials/settings_schedule.html.j2", "Schedule"),
    "sources": ("partials/settings_sources.html.j2", "Sources"),
    "budget": ("partials/settings_budget.html.j2", "Budget"),
    "tailoring": ("partials/settings_tailoring.html.j2", "Tailoring"),
    "limits": ("partials/settings_limits.html.j2", "Rate Limits"),
    "safety": ("partials/settings_safety.html.j2", "Safety"),
    "notifications": ("partials/settings_notifications.html.j2", "Notifications"),
    "submission": ("partials/settings_submission.html.j2", "Submission"),
    "playwright": ("partials/settings_playwright.html.j2", "Playwright"),
    "saved-answers": ("partials/settings_saved_answers.html.j2", "Saved Answers"),
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
    elif section_name == "sources":
        from app.discovery.service import get_all_sources

        ctx["sources"] = await get_all_sources(session)
    elif section_name == "saved-answers":
        from app.learning.service import get_all_saved_answers

        ctx["answers"] = await get_all_saved_answers(session)

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


# ── Resume ──────────────────────────────────────────────────────────

@router.get("/section/resume", response_class=HTMLResponse)
async def get_resume_section(
    request: Request,
    session=Depends(get_session),
):
    """Load the resume upload form with preview if a resume exists."""
    row = await get_settings_row(session)
    resume_path = get_resume_path()
    preview = None
    if resume_path and resume_path.exists():
        try:
            preview = extract_resume_text(resume_path)
        except Exception:
            preview = None
    return templates.TemplateResponse(
        request,
        "partials/settings_resume.html.j2",
        {
            "settings": row,
            "resume_path": resume_path,
            "preview": preview,
            "active_section": "resume",
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


# ── Resume POST ──────────────────────────────────────────────────────

@router.post("/resume", response_class=HTMLResponse)
async def upload_resume(
    request: Request,
    resume: UploadFile = File(...),
    session=Depends(get_session),
):
    """Upload a DOCX resume, store it, and show extracted text preview."""
    # Validate file extension
    filename = resume.filename or ""
    if not filename.lower().endswith(".docx"):
        row = await get_settings_row(session)
        resume_path = get_resume_path()
        preview = None
        if resume_path and resume_path.exists():
            try:
                preview = extract_resume_text(resume_path)
            except Exception:
                preview = None
        return templates.TemplateResponse(
            request,
            "partials/settings_resume.html.j2",
            {
                "settings": row,
                "resume_path": resume_path,
                "preview": preview,
                "active_section": "resume",
                "flash": ("error", "Only .docx files are accepted."),
            },
        )

    # Save and extract
    saved_path = await save_resume(resume)

    # Update Settings metadata
    await set_setting(session, "resume_filename", filename)
    await set_setting(session, "resume_uploaded_at", datetime.utcnow())

    # Extract text for preview
    preview = None
    try:
        preview = extract_resume_text(saved_path)
    except Exception:
        preview = None

    row = await get_settings_row(session)
    return templates.TemplateResponse(
        request,
        "partials/settings_resume.html.j2",
        {
            "settings": row,
            "resume_path": saved_path,
            "preview": preview,
            "active_section": "resume",
            "flash": ("success", f"Resume '{filename}' uploaded successfully."),
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


# ── Threshold ────────────────────────────────────────────────────────

@router.post("/threshold", response_class=HTMLResponse)
async def save_threshold(
    request: Request,
    match_threshold: int = Form(...),
    session=Depends(get_session),
):
    """Save the match threshold (0-100)."""
    if match_threshold < 0 or match_threshold > 100:
        raise HTTPException(400, "Threshold must be between 0 and 100")
    await set_setting(session, "match_threshold", match_threshold)
    return await _render_section(
        request, session, "threshold",
        flash=("success", "Match threshold saved."),
    )


# ── Schedule ─────────────────────────────────────────────────────────

@router.post("/schedule", response_class=HTMLResponse)
async def save_schedule(
    request: Request,
    session=Depends(get_session),
):
    """Save schedule toggle and quiet hours.

    Checkboxes only submit when checked, so we parse raw form data.
    """
    form = await request.form()
    schedule_enabled = form.get("schedule_enabled", "").lower() == "true"
    quiet_hours_start = int(form.get("quiet_hours_start", "22"))
    quiet_hours_end = int(form.get("quiet_hours_end", "7"))

    if not (0 <= quiet_hours_start <= 23):
        raise HTTPException(400, "quiet_hours_start must be 0-23")
    if not (0 <= quiet_hours_end <= 23):
        raise HTTPException(400, "quiet_hours_end must be 0-23")

    await set_setting(session, "schedule_enabled", schedule_enabled)
    await set_setting(session, "quiet_hours_start", quiet_hours_start)
    await set_setting(session, "quiet_hours_end", quiet_hours_end)

    return await _render_section(
        request, session, "schedule",
        flash=("success", "Schedule settings saved."),
    )


# ── Budget ───────────────────────────────────────────────────────────

@router.post("/budget", response_class=HTMLResponse)
async def save_budget(
    request: Request,
    budget_cap_dollars: float = Form(...),
    session=Depends(get_session),
):
    """Save the monthly budget cap."""
    if budget_cap_dollars < 0:
        raise HTTPException(400, "Budget cap cannot be negative")
    await set_setting(session, "budget_cap_dollars", budget_cap_dollars)
    return await _render_section(
        request, session, "budget",
        flash=("success", "Budget cap saved."),
    )


# ── Tailoring intensity ──────────────────────────────────────────────

_VALID_INTENSITIES = {"light", "balanced", "full"}


@router.post("/tailoring", response_class=HTMLResponse)
async def save_tailoring(
    request: Request,
    tailoring_intensity: str = Form(...),
    session=Depends(get_session),
):
    """Persist the three-position tailoring intensity selector.

    Per CONTEXT.md this feels like a simple three-position control
    rather than a numeric slider — values outside the allowed set are
    rejected before hitting the DB so the pipeline (04-05) can trust
    ``Settings.tailoring_intensity`` without defensive normalisation.
    """
    value = (tailoring_intensity or "").strip().lower()
    if value not in _VALID_INTENSITIES:
        raise HTTPException(
            status_code=400,
            detail=f"tailoring_intensity must be one of {sorted(_VALID_INTENSITIES)}",
        )
    await set_setting(session, "tailoring_intensity", value)
    return await _render_section(
        request, session, "tailoring",
        flash=("success", f"Tailoring intensity set to {value}."),
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


# ── Phase 5 notifications + submission controls (Plan 05-08) ─────────


@router.post("/notification-email", response_class=HTMLResponse)
async def save_notification_email(
    request: Request,
    notification_email: str = Form(""),
    session=Depends(get_session),
):
    """Persist ``Settings.notification_email``.

    Empty string is coerced to ``None`` so the downstream resolver
    falls back to the SMTP username — matches the 05-01 decision that
    notification_email is nullable.
    """
    value = (notification_email or "").strip()
    if value and "@" not in value:
        return await _render_section(
            request, session, "notifications",
            flash=("error", "Notification email must contain '@'."),
        )
    await set_setting(session, "notification_email", value or None)
    return await _render_section(
        request, session, "notifications",
        flash=("success", "Notification email saved."),
    )


@router.post("/base-url", response_class=HTMLResponse)
async def save_base_url(
    request: Request,
    base_url: str = Form(...),
    session=Depends(get_session),
):
    """Persist ``Settings.base_url`` (used to build review-page links in emails)."""
    value = (base_url or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="base_url cannot be empty")
    if not (value.startswith("http://") or value.startswith("https://")):
        return await _render_section(
            request, session, "notifications",
            flash=("error", "Base URL must start with http:// or https://"),
        )
    await set_setting(session, "base_url", value)
    return await _render_section(
        request, session, "notifications",
        flash=("success", "Base URL saved."),
    )


@router.post("/playwright", response_class=HTMLResponse)
async def save_playwright(
    request: Request,
    session=Depends(get_session),
):
    """Save Playwright browser automation settings.

    Checkboxes only submit when checked — absence means False.
    Screenshot retention is clamped to 1-365 days.
    """
    form = await request.form()
    headless = form.get("playwright_headless", "false").lower() == "true"
    pause = form.get("pause_if_unsure", "false").lower() == "true"
    retention_raw = int(form.get("screenshot_retention_days", "30"))
    retention = max(1, min(365, retention_raw))

    await set_setting(session, "playwright_headless", headless)
    await set_setting(session, "pause_if_unsure", pause)
    await set_setting(session, "screenshot_retention_days", retention)

    return await _render_section(
        request, session, "playwright",
        flash=("success", "Playwright settings saved."),
    )


@router.post("/submissions-paused", response_class=HTMLResponse)
async def save_submissions_paused(
    request: Request,
    session=Depends(get_session),
):
    """Flip ``Settings.submissions_paused``. Checkbox-only form."""
    form = await request.form()
    paused = form.get("submissions_paused", "false").lower() == "true"
    await set_setting(session, "submissions_paused", paused)
    return await _render_section(
        request, session, "submission",
        flash=("success", "Submission pause toggled."),
    )


@router.post("/auto-holdout-margin", response_class=HTMLResponse)
async def save_auto_holdout_margin(
    request: Request,
    auto_holdout_margin_pct: int = Form(...),
    session=Depends(get_session),
):
    """Persist ``Settings.auto_holdout_margin_pct`` — clamped to [0, 50]."""
    value = max(0, min(50, int(auto_holdout_margin_pct)))
    await set_setting(session, "auto_holdout_margin_pct", value)
    return await _render_section(
        request, session, "submission",
        flash=("success", f"Auto-mode holdout margin set to {value}%."),
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
