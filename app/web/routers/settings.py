"""Settings page: secrets CRUD (Fernet-encrypted) + rate-limit envelope.

Two distinct form surfaces live here:

1. **Secrets** — API keys, SMTP credentials, etc. Each save runs the
   plaintext through :meth:`FernetVault.encrypt`, which both produces the
   ciphertext AND registers the plaintext with the log scrubber so it is
   redacted from every subsequent log line. The Secret table only ever
   stores ciphertext; there is no plaintext column.

2. **Rate-limit envelope** — ``daily_cap``, ``delay_min_seconds``,
   ``delay_max_seconds`` and ``timezone``. Saving updates the live
   ``RateLimiter`` singleton on ``app.state`` so the change takes effect
   on the very next ``run_pipeline`` call without a restart.

CONTEXT.md pitfall: losing or rotating ``FERNET_KEY`` makes every stored
secret unreadable. The template includes a prominent warning banner about
this; plan 01-05 may add a proactive "boot-time decrypt failed" banner as
well, but this page is the primary remediation surface.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

# Canonical well-known secret names the UI renders as a checklist. Users
# may still save ad-hoc names — this list just seeds the "is it set?" grid.
KNOWN_SECRET_NAMES = [
    "anthropic_api_key",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
]


async def _secret_names(session) -> list[str]:
    result = await session.execute(select(Secret.name).order_by(Secret.name))
    return [r[0] for r in result.all()]


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, session=Depends(get_session)):
    row = await get_settings_row(session)
    names = await _secret_names(session)
    return templates.TemplateResponse(
        request,
        "settings.html.j2",
        {
            "settings": row,
            "known_names": KNOWN_SECRET_NAMES,
            "stored_names": names,
        },
    )


@router.post("/secrets", response_class=HTMLResponse)
async def save_secret(
    request: Request,
    name: str = Form(...),
    value: str = Form(...),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    """Upsert one Secret row. Plaintext is registered with the log scrubber.

    Order of operations is deliberate: ``vault.encrypt`` registers the
    plaintext with the scrubber BEFORE returning the ciphertext, so any
    logging that happens between here and the DB commit is already safe.
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="empty secret name")
    if not value:
        raise HTTPException(status_code=400, detail="empty secret value")
    ciphertext = vault.encrypt(value)  # also registers with scrubber
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


@router.post("/limits")
async def save_limits(
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

    return RedirectResponse("/settings", status_code=303)


__all__ = ["router"]
