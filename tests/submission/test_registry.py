"""Unit tests for app.submission.registry + app.submission.strategies.email.

The registry layer is intentionally DB-free, so these tests use plain
``Job(...)`` instances and a temporary DOCX attachment. ``send_via_smtp``
is monkeypatched on the strategy module so no real SMTP traffic occurs.

NOTE: tests live under ``tests/submission/`` (the pyproject testpaths
root), not ``app/tests/submission/``. This matches the Plan 05-02
deviation that relocated the directory after discovering ``testpaths =
["tests"]`` in pyproject.toml.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from app.discovery.models import Job
from app.submission.creds import SmtpCreds
from app.submission.registry import (
    SubmissionContext,
    SubmissionOutcome,
    SubmitterStrategy,
    default_registry,
    select_strategy,
)
from app.submission.sender import SubmissionSendError
from app.submission.strategies import email as email_strategy_module
from app.submission.strategies.email import EmailStrategy


# --- helpers --------------------------------------------------------------


def _make_job(description: str = "") -> Job:
    """Return a minimal Job populated only with what the strategy needs."""
    return Job(
        id=42,
        fingerprint="fp-42",
        external_id="ext-42",
        title="Senior Backend Engineer",
        company="Acme Co",
        url="https://example.com/jobs/42",
        source="manual",
        description=description,
    )


def _write_docx(path: Path, text: str = "Resume body") -> Path:
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))
    return path


def _make_ctx(tmp_path: Path) -> SubmissionContext:
    resume = _write_docx(tmp_path / "resume.docx")
    cover = _write_docx(tmp_path / "cover.docx", "Dear hiring manager,")
    return SubmissionContext(
        job=_make_job("Apply at hr@acme.com"),
        tailored_resume_path=resume,
        cover_letter_path=cover,
        recipient_email="hr@acme.com",
        subject="Application for Senior Backend Engineer at Acme Co",
        body_text="Hello, please find my resume attached.",
        attachment_filename="Test_User_Acme_Resume.docx",
        smtp_creds=SmtpCreds(
            host="smtp.example.com",
            port=587,
            username="me@example.com",
            password="hunter2",
        ),
    )


# --- is_applicable --------------------------------------------------------


def test_email_strategy_applicable_when_recipient_parseable():
    job = _make_job("Send your resume to hr@acme.com — looking forward!")
    assert EmailStrategy().is_applicable(job, job.description) is True


def test_email_strategy_not_applicable_for_noreply_only():
    job = _make_job("Replies are auto-handled at noreply@acme.com only.")
    assert EmailStrategy().is_applicable(job, job.description) is False


def test_email_strategy_not_applicable_for_empty_description():
    job = _make_job("")
    assert EmailStrategy().is_applicable(job, job.description) is False


# --- select_strategy ------------------------------------------------------


def test_select_strategy_returns_email_when_applicable():
    job = _make_job("Email applications to careers@acme.com")
    chosen = select_strategy(job, job.description, registry=[EmailStrategy()])
    assert chosen is not None
    assert isinstance(chosen, EmailStrategy)
    assert chosen.name == "email"


def test_select_strategy_returns_none_when_nothing_applies():
    job = _make_job("Apply at https://acme.example/careers (no email shown).")
    chosen = select_strategy(job, job.description, registry=[EmailStrategy()])
    assert chosen is None


def test_default_registry_contains_email_strategy():
    reg = default_registry()
    assert len(reg) == 1
    assert reg[0].name == "email"
    # SubmitterStrategy is runtime_checkable — registry contents must satisfy it.
    assert isinstance(reg[0], SubmitterStrategy)


# --- submit (async) -------------------------------------------------------


@pytest.mark.asyncio
async def test_email_strategy_submit_success(tmp_path, monkeypatch):
    sent_calls: list[tuple] = []

    async def _fake_send(msg, cfg):
        sent_calls.append((msg, cfg))

    monkeypatch.setattr(email_strategy_module, "send_via_smtp", _fake_send)

    ctx = _make_ctx(tmp_path)
    outcome = await EmailStrategy().submit(ctx)

    assert isinstance(outcome, SubmissionOutcome)
    assert outcome.success is True
    assert outcome.submitter == "email"
    assert outcome.error_class is None
    assert outcome.error_message is None
    assert len(sent_calls) == 1
    sent_msg, sent_cfg = sent_calls[0]
    # Headers built by builder.build_email_message
    assert sent_msg["To"] == "hr@acme.com"
    assert sent_msg["From"] == "me@example.com"
    assert sent_msg["Subject"] == ctx.subject
    # SmtpConfig faithfully populated from ctx.smtp_creds
    assert sent_cfg.host == "smtp.example.com"
    assert sent_cfg.port == 587
    assert sent_cfg.username == "me@example.com"
    assert sent_cfg.password == "hunter2"


@pytest.mark.asyncio
async def test_email_strategy_submit_auth_failure_returns_failed_outcome(
    tmp_path, monkeypatch
):
    async def _raise_auth(msg, cfg):
        raise SubmissionSendError(
            error_class="SMTPAuthenticationError",
            message="bad creds",
        )

    monkeypatch.setattr(email_strategy_module, "send_via_smtp", _raise_auth)

    ctx = _make_ctx(tmp_path)
    outcome = await EmailStrategy().submit(ctx)

    assert outcome.success is False
    assert outcome.submitter == "email"
    assert outcome.error_class == "SMTPAuthenticationError"
    assert outcome.error_message is not None
    assert "bad creds" in outcome.error_message
