"""Unit tests for app.submission.sender + app.submission.creds (Plan 05-02).

No real SMTP server is stood up — aiosmtplib.send is monkeypatched. Credential
tests use the in-memory ``async_session`` fixture from tests/conftest.py.
"""
from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib
import pytest

from app.submission.creds import SmtpCreds, SmtpCredsMissing, load_smtp_creds
from app.submission.sender import (
    SmtpConfig,
    SubmissionSendError,
    send_via_smtp,
)


# --- aiosmtplib fake ------------------------------------------------------


class _FakeSend:
    """Async callable replacement for :func:`aiosmtplib.send`."""

    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, msg: EmailMessage, **kwargs: Any) -> None:
        self.calls.append({"msg": msg, **kwargs})
        if self.exc is not None:
            raise self.exc


# --- send_via_smtp --------------------------------------------------------


@pytest.mark.asyncio
async def test_send_uses_starttls_on_587(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSend()
    monkeypatch.setattr(aiosmtplib, "send", fake)
    cfg = SmtpConfig(host="smtp.example.com", port=587, username="u", password="p")
    await send_via_smtp(EmailMessage(), cfg)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["hostname"] == "smtp.example.com"
    assert call["port"] == 587
    assert call["username"] == "u"
    assert call["password"] == "p"
    assert call["start_tls"] is True
    assert call["use_tls"] is False
    assert call["timeout"] == 30.0


@pytest.mark.asyncio
async def test_send_uses_implicit_tls_on_465(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSend()
    monkeypatch.setattr(aiosmtplib, "send", fake)
    cfg = SmtpConfig(host="h", port=465, username="u", password="p")
    await send_via_smtp(EmailMessage(), cfg)
    assert fake.calls[0]["use_tls"] is True
    assert fake.calls[0]["start_tls"] is False


@pytest.mark.asyncio
async def test_send_plain_on_other_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSend()
    monkeypatch.setattr(aiosmtplib, "send", fake)
    cfg = SmtpConfig(host="h", port=25, username="u", password="p")
    await send_via_smtp(EmailMessage(), cfg)
    assert fake.calls[0]["start_tls"] is False
    assert fake.calls[0]["use_tls"] is False


@pytest.mark.asyncio
async def test_send_propagates_custom_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeSend()
    monkeypatch.setattr(aiosmtplib, "send", fake)
    cfg = SmtpConfig(host="h", port=587, username="u", password="p", timeout=5.5)
    await send_via_smtp(EmailMessage(), cfg)
    assert fake.calls[0]["timeout"] == 5.5


@pytest.mark.asyncio
async def test_auth_error_wraps_as_submission_send_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        aiosmtplib,
        "send",
        _FakeSend(aiosmtplib.SMTPAuthenticationError(535, "bad creds")),
    )
    with pytest.raises(SubmissionSendError) as exc_info:
        await send_via_smtp(
            EmailMessage(), SmtpConfig("h", 587, "u", "p")
        )
    assert exc_info.value.error_class == "SMTPAuthenticationError"
    assert isinstance(exc_info.value.cause, aiosmtplib.SMTPAuthenticationError)


@pytest.mark.asyncio
async def test_recipients_refused_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SMTPRecipientsRefused takes a list of refused recipient records.
    err = aiosmtplib.SMTPRecipientsRefused([])
    monkeypatch.setattr(aiosmtplib, "send", _FakeSend(err))
    with pytest.raises(SubmissionSendError) as exc_info:
        await send_via_smtp(EmailMessage(), SmtpConfig("h", 587, "u", "p"))
    assert exc_info.value.error_class == "SMTPRecipientsRefused"


@pytest.mark.asyncio
async def test_server_disconnected_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        aiosmtplib,
        "send",
        _FakeSend(aiosmtplib.SMTPServerDisconnected("gone")),
    )
    with pytest.raises(SubmissionSendError) as exc_info:
        await send_via_smtp(EmailMessage(), SmtpConfig("h", 587, "u", "p"))
    assert exc_info.value.error_class == "SMTPServerDisconnected"


@pytest.mark.asyncio
async def test_timeout_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        aiosmtplib,
        "send",
        _FakeSend(aiosmtplib.SMTPTimeoutError("slow")),
    )
    with pytest.raises(SubmissionSendError) as exc_info:
        await send_via_smtp(EmailMessage(), SmtpConfig("h", 587, "u", "p"))
    assert exc_info.value.error_class == "SMTPTimeoutError"


@pytest.mark.asyncio
async def test_generic_smtp_exception_preserves_class_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WeirdError(aiosmtplib.SMTPException):
        pass

    monkeypatch.setattr(
        aiosmtplib, "send", _FakeSend(_WeirdError("odd"))
    )
    with pytest.raises(SubmissionSendError) as exc_info:
        await send_via_smtp(EmailMessage(), SmtpConfig("h", 587, "u", "p"))
    assert exc_info.value.error_class == "_WeirdError"


# --- load_smtp_creds ------------------------------------------------------


async def _seed_smtp_secret(session, name: str, plaintext: str) -> None:
    from app.config import get_settings
    from app.db.models import Secret
    from app.security.fernet import FernetVault

    vault = FernetVault.from_env(get_settings().fernet_key)
    ct = vault.encrypt(plaintext)
    session.add(Secret(name=name, ciphertext=ct))
    await session.flush()


@pytest.mark.asyncio
async def test_load_smtp_creds_happy_path(
    env_with_fernet: str,
    async_session,
) -> None:
    await _seed_smtp_secret(async_session, "smtp_host", "smtp.example.com")
    await _seed_smtp_secret(async_session, "smtp_port", "587")
    await _seed_smtp_secret(async_session, "smtp_user", "user@example.com")
    await _seed_smtp_secret(async_session, "smtp_password", "hunter2")

    creds = await load_smtp_creds(async_session)

    assert isinstance(creds, SmtpCreds)
    assert creds.host == "smtp.example.com"
    assert creds.port == 587
    assert isinstance(creds.port, int)  # Pitfall 7 guard
    assert creds.username == "user@example.com"
    assert creds.password == "hunter2"


@pytest.mark.asyncio
async def test_load_smtp_creds_raises_on_missing_password(
    env_with_fernet: str,
    async_session,
) -> None:
    await _seed_smtp_secret(async_session, "smtp_host", "h")
    await _seed_smtp_secret(async_session, "smtp_port", "587")
    await _seed_smtp_secret(async_session, "smtp_user", "u")
    # smtp_password intentionally omitted.

    with pytest.raises(SmtpCredsMissing) as exc_info:
        await load_smtp_creds(async_session)

    assert exc_info.value.name == "smtp_password"
    assert "smtp_password" in str(exc_info.value)


@pytest.mark.asyncio
async def test_load_smtp_creds_coerces_port_from_string(
    env_with_fernet: str,
    async_session,
) -> None:
    # Even weird whitespace survives int() because aiosmtplib writes
    # Settings via str(smtp_port) — here we just ensure int coercion.
    await _seed_smtp_secret(async_session, "smtp_host", "h")
    await _seed_smtp_secret(async_session, "smtp_port", "465")
    await _seed_smtp_secret(async_session, "smtp_user", "u")
    await _seed_smtp_secret(async_session, "smtp_password", "p")

    creds = await load_smtp_creds(async_session)
    assert creds.port == 465
    assert isinstance(creds.port, int)
