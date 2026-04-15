"""Tests for app.submission.notifications.

Notification senders are exercised end-to-end with monkeypatched
``aiosmtplib.send`` (no real network) and an in-memory async session.
The Profile / Settings / Secret rows are seeded inline per test rather
than via a shared fixture so each case stays legible.
"""
from __future__ import annotations

import importlib
from email.message import EmailMessage
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Secret, Profile, Settings
from app.security.fernet import FernetVault
from app.submission.builder import build_attachment_filename
from app.submission.models import FailureSuppression
from app.submission.suppression import (
    build_signature,
    clear_suppressions_for_stage,
)


# ---- helpers ---------------------------------------------------------------


async def _seed_smtp_secrets(session, fernet_key: str) -> None:
    """Seed the four smtp_* Secret rows with valid encrypted values."""
    vault = FernetVault.from_env(fernet_key)
    for name, value in [
        ("smtp_host", "smtp.example.com"),
        ("smtp_port", "587"),
        ("smtp_user", "sender@example.com"),
        ("smtp_password", "hunter2"),
    ]:
        session.add(Secret(name=name, ciphertext=vault.encrypt(value)))
    await session.commit()


async def _seed_settings(
    session,
    *,
    notification_email: str | None = None,
    quiet_hours_start: int = 22,
    quiet_hours_end: int = 7,
) -> Settings:
    """Insert/update the Settings singleton with the provided overrides."""
    from app.settings.service import get_settings_row, set_setting

    row = await get_settings_row(session)
    await set_setting(session, "notification_email", notification_email)
    await set_setting(session, "quiet_hours_start", quiet_hours_start)
    await set_setting(session, "quiet_hours_end", quiet_hours_end)
    return await get_settings_row(session)


async def _seed_profile(session, full_name: str = "Jane Doe") -> Profile:
    from app.settings.service import update_profile

    return await update_profile(session, full_name=full_name, email="jane@example.com")


def _make_job(job_id: int = 1) -> "object":
    """Build a Job-like object that satisfies the template + builder.

    Notifications never persist this object; they only read attribute
    values for the email body and attachment filename. Constructing a
    light dataclass-style stand-in avoids needing to insert a real Job
    row + satisfy the fingerprint UNIQUE index.
    """
    class _J:
        pass

    j = _J()
    j.id = job_id
    j.title = "Senior Backend Engineer"
    j.company = "Stripe"
    j.source = "greenhouse"
    j.score = 87
    j.url = "https://example.com/jobs/1"
    return j


def _make_record(tmp_path: Path, name: str = "v1.docx") -> "object":
    """Build a TailoringRecord-like with a real DOCX file at tailored_resume_path."""
    docx_path = tmp_path / name
    # Minimal valid DOCX bytes — we never re-parse it, just attach it.
    docx_path.write_bytes(b"PK\x03\x04 fake docx bytes")

    class _R:
        pass

    r = _R()
    r.id = 99
    r.tailored_resume_path = str(docx_path)
    r.cover_letter_path = None
    return r


@pytest.fixture
def smtp_spy(monkeypatch):
    """Monkeypatch aiosmtplib.send to record calls without network I/O."""
    calls = []

    async def _fake_send(msg, **kwargs):
        calls.append((msg, kwargs))
        return None

    # Notifications module imports send_via_smtp which itself calls
    # aiosmtplib.send — patch at the lowest layer so both success and
    # failure helpers are covered.
    import aiosmtplib

    monkeypatch.setattr(aiosmtplib, "send", _fake_send)
    return calls


# ---- send_success_notification ---------------------------------------------


@pytest.mark.asyncio
async def test_success_notification_sent_with_docx_attachment(
    async_session, env_with_fernet, tmp_path, smtp_spy
):
    # importlib.reload mimics the live_app fixture pattern — proves the
    # lazy get_settings inside load_smtp_creds still resolves the
    # current FERNET_KEY after a reload.
    import app.config

    importlib.reload(app.config)

    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email=None)
    await _seed_profile(async_session, full_name="Jane Doe")

    from app.submission.notifications import send_success_notification

    job = _make_job()
    record = _make_record(tmp_path)

    sent = await send_success_notification(
        async_session,
        job=job,
        record=record,
        submission_id=42,
        recipient_email="recruiting@stripe.com",
    )

    assert sent is True
    assert len(smtp_spy) == 1
    msg: EmailMessage = smtp_spy[0][0]
    assert msg["Subject"].startswith("[Applied]")
    assert "Senior Backend Engineer" in msg["Subject"]
    assert "Stripe" in msg["Subject"]
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Senior Backend Engineer" in body
    assert "Stripe" in body
    assert "/review/1" in body
    # NOTIF-01: tailored resume DOCX attached with the canonical filename.
    expected_filename = build_attachment_filename(
        full_name="Jane Doe", company="Stripe"
    )
    matching = [
        part
        for part in msg.iter_attachments()
        if part.get_filename() == expected_filename
    ]
    assert len(matching) == 1
    assert (
        matching[0].get_content_type()
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.asyncio
async def test_success_notification_uses_notification_email_when_set(
    async_session, env_with_fernet, tmp_path, smtp_spy
):
    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email="inbox@personal.com")
    await _seed_profile(async_session)

    from app.submission.notifications import send_success_notification

    sent = await send_success_notification(
        async_session,
        job=_make_job(),
        record=_make_record(tmp_path),
        submission_id=1,
        recipient_email="r@example.com",
    )
    assert sent is True
    msg: EmailMessage = smtp_spy[0][0]
    assert msg["To"] == "inbox@personal.com"
    # From stays SMTP user.
    assert msg["From"] == "sender@example.com"


@pytest.mark.asyncio
async def test_success_notification_falls_back_to_smtp_user_when_unset(
    async_session, env_with_fernet, tmp_path, smtp_spy
):
    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email=None)
    await _seed_profile(async_session)

    from app.submission.notifications import send_success_notification

    sent = await send_success_notification(
        async_session,
        job=_make_job(),
        record=_make_record(tmp_path),
        submission_id=1,
        recipient_email="r@example.com",
    )
    assert sent is True
    msg: EmailMessage = smtp_spy[0][0]
    assert msg["To"] == "sender@example.com"


# ---- send_failure_notification ---------------------------------------------


@pytest.mark.asyncio
async def test_failure_first_occurrence_sends(
    async_session, env_with_fernet, smtp_spy
):
    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email=None)
    await _seed_profile(async_session)

    from app.submission.notifications import send_failure_notification

    sent = await send_failure_notification(
        async_session,
        stage="submission",
        error_class="SMTPAuthenticationError",
        error_message="535 5.7.8 Username and Password not accepted",
    )
    assert sent is True
    assert len(smtp_spy) == 1
    msg = smtp_spy[0][0]
    assert "[Submission failed]" in msg["Subject"]
    assert "SMTPAuthenticationError" in msg["Subject"]


@pytest.mark.asyncio
async def test_failure_duplicate_suppressed(
    async_session, env_with_fernet, smtp_spy
):
    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email=None)
    await _seed_profile(async_session)

    from app.submission.notifications import send_failure_notification

    sent_a = await send_failure_notification(
        async_session,
        stage="submission",
        error_class="SMTPAuthenticationError",
        error_message="auth bad",
    )
    sent_b = await send_failure_notification(
        async_session,
        stage="submission",
        error_class="SMTPAuthenticationError",
        error_message="auth bad",
    )
    assert sent_a is True
    assert sent_b is False
    # Sender only invoked once.
    assert len(smtp_spy) == 1


@pytest.mark.asyncio
async def test_failure_after_clear_sends_again(
    async_session, env_with_fernet, smtp_spy
):
    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email=None)
    await _seed_profile(async_session)

    from app.submission.notifications import send_failure_notification

    sent_a = await send_failure_notification(
        async_session,
        stage="submission",
        error_class="X",
        error_message="m",
    )
    await clear_suppressions_for_stage(async_session, "submission")
    sent_b = await send_failure_notification(
        async_session,
        stage="submission",
        error_class="X",
        error_message="m",
    )
    assert sent_a is True
    assert sent_b is True
    assert len(smtp_spy) == 2


# ---- CRITICAL: quiet hours bypass ------------------------------------------


@pytest.mark.asyncio
async def test_notification_sends_during_silence_window(
    async_session, env_with_fernet, tmp_path, smtp_spy
):
    """Locked decision (CONTEXT.md + research pitfall 5): notifications
    MUST fire regardless of Settings.quiet_hours_*. Quiet hours gate
    outbound applications, not inbox updates."""
    await _seed_smtp_secrets(async_session, env_with_fernet)
    # 24-hour quiet window: start=0, end=23 → every hour is "quiet".
    await _seed_settings(
        async_session,
        notification_email=None,
        quiet_hours_start=0,
        quiet_hours_end=23,
    )
    await _seed_profile(async_session)

    from app.submission.notifications import send_success_notification

    sent = await send_success_notification(
        async_session,
        job=_make_job(),
        record=_make_record(tmp_path),
        submission_id=1,
        recipient_email="r@example.com",
    )
    assert sent is True
    assert len(smtp_spy) == 1, "notification was suppressed during quiet hours"


# ---- pipeline failure stage partition --------------------------------------


@pytest.mark.asyncio
async def test_pipeline_failure_uses_pipeline_stage(
    async_session, env_with_fernet, smtp_spy
):
    await _seed_smtp_secrets(async_session, env_with_fernet)
    await _seed_settings(async_session, notification_email=None)
    await _seed_profile(async_session)

    from app.submission.notifications import send_pipeline_failure_notification

    sent = await send_pipeline_failure_notification(
        async_session,
        error_class="RuntimeError",
        error_message="kaboom",
    )
    assert sent is True
    # The corresponding suppression row carries stage='pipeline'.
    sig = build_signature(
        error_class="RuntimeError", stage="pipeline", message="kaboom"
    )
    row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig)
        )
    ).scalar_one()
    assert row.stage == "pipeline"
    msg = smtp_spy[0][0]
    assert "[Pipeline failed]" in msg["Subject"]


# ---- ack router -------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_router_marks_suppression_cleared(
    async_session, env_with_fernet, monkeypatch
):
    # Seed a single open suppression row to ack.
    from app.submission.suppression import should_notify

    await should_notify(
        async_session,
        signature="sig-router",
        stage="submission",
        error_class="X",
        message="m",
    )
    row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == "sig-router")
        )
    ).scalar_one()

    # FastAPI TestClient with a get_session override pointing at our
    # in-memory async_session — same pattern Phase 4 used for the
    # tailoring router tests.
    from fastapi.testclient import TestClient

    from app.web.routers import notifications as notifications_router
    from app.web.deps import get_session
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(notifications_router.router)

    async def _override_session():
        yield async_session

    app.dependency_overrides[get_session] = _override_session

    with TestClient(app) as client:
        resp = client.post(f"/notifications/ack/{row.id}")
    assert resp.status_code == 200
    assert "Acknowledged" in resp.text

    await async_session.refresh(row)
    assert row.cleared_at is not None
    assert row.cleared_by == "user_ack"

    # 404 path
    with TestClient(app) as client:
        resp = client.post("/notifications/ack/99999")
    assert resp.status_code == 404
