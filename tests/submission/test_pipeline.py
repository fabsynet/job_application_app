"""Integration tests for app.submission.pipeline.run_submission (Plan 05-04).

These tests wire together the real Plan 05-01 schema, Plan 05-02
builder + sender, Plan 05-03 strategy registry, Plan 05-07 notification
senders, and the Plan 05-04 pipeline. They use an in-memory async
session factory, monkeypatch :func:`aiosmtplib.send` so no real network
traffic happens, and seed real DOCX artifacts under ``tmp_path``.

The 11 scenarios from the plan:

1. Auto-mode happy path (high-confidence tailored -> submitted once).
2. Idempotent double run (second pass is a clean no-op).
3. Low-confidence holdout leaves job in tailored.
4. Review mode never auto-submits tailored jobs.
5. Review mode drains an already-approved job.
6. Daily cap halt leaves remainder approved.
7. Pause toggle skips the entire stage.
8. Quiet hours halt leaves remainder approved.
9. Missing recipient flips job to needs_info + failure notification.
10. SMTP auth error flips failed + success notification suppressed.
11. Second same-signature failure is suppressed (one notify).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosmtplib
import pytest
import pytest_asyncio
from docx import Document
from sqlalchemy import select

from app.db.models import Profile, Secret, Settings
from app.discovery.models import Job
from app.runs.context import RunContext
from app.scheduler.rate_limit import RateLimitExceeded
from app.security.fernet import FernetVault
from app.submission.models import FailureSuppression, Submission
from app.tailoring.models import TailoringRecord


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class _FakeRateLimiter:
    """Minimal RateLimiter stand-in that the pipeline can call through.

    ``fail_after`` controls when ``await_precheck`` starts raising.
    ``record_submission`` increments a real counter so tests can
    assert on post-send accounting. ``random_action_delay`` always
    returns zero so tests never actually sleep.
    """

    def __init__(self, *, fail_after: int | None = None) -> None:
        self.fail_after = fail_after
        self.submitted_count = 0
        self.precheck_calls = 0
        self.record_calls = 0

    async def await_precheck(self, session: Any) -> None:
        self.precheck_calls += 1
        if self.fail_after is not None and self.submitted_count >= self.fail_after:
            raise RateLimitExceeded(
                f"cap {self.fail_after} reached ({self.submitted_count} submitted)"
            )

    async def record_submission(self, session: Any) -> int:
        self.record_calls += 1
        self.submitted_count += 1
        return self.submitted_count

    def random_action_delay(self) -> float:
        return 0.0


class _SmtpSpy:
    """Async callable that records every :func:`aiosmtplib.send` call."""

    def __init__(self, *, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, msg, **kwargs) -> None:
        self.calls.append({"msg": msg, **kwargs})
        if self.exc is not None:
            raise self.exc


def _write_docx(path: Path, *paragraphs: str) -> None:
    """Write a real DOCX with the given paragraphs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(str(path))


async def _seed_smtp_secrets(session, fernet_key: str) -> None:
    vault = FernetVault.from_env(fernet_key)
    for name, value in [
        ("smtp_host", "smtp.example.com"),
        ("smtp_port", "587"),
        ("smtp_user", "sender@example.com"),
        ("smtp_password", "hunter2"),
    ]:
        session.add(Secret(name=name, ciphertext=vault.encrypt(value)))
    await session.commit()


async def _seed_profile(session, full_name: str = "Jane Doe") -> None:
    from app.settings.service import update_profile

    await update_profile(
        session, full_name=full_name, email="jane@example.com"
    )


async def _seed_settings(
    session,
    *,
    auto_mode: bool = True,
    match_threshold: int = 10,
    auto_holdout_margin_pct: int = 10,
    submissions_paused: bool = False,
    quiet_hours_start: int = 0,
    quiet_hours_end: int = 0,
    notification_email: str | None = None,
    timezone: str = "UTC",
) -> None:
    from app.settings.service import get_settings_row, set_setting

    await get_settings_row(session)
    await set_setting(session, "auto_mode", auto_mode)
    await set_setting(session, "match_threshold", match_threshold)
    await set_setting(
        session, "auto_holdout_margin_pct", auto_holdout_margin_pct
    )
    await set_setting(session, "submissions_paused", submissions_paused)
    await set_setting(session, "quiet_hours_start", quiet_hours_start)
    await set_setting(session, "quiet_hours_end", quiet_hours_end)
    await set_setting(session, "notification_email", notification_email)
    await set_setting(session, "timezone", timezone)


_DEFAULT_DESCRIPTION = (
    "Python FastAPI Postgres Docker Kubernetes async services. "
    "Contact us at hr@acme.example.com to apply."
)


async def _seed_job(
    session,
    *,
    fingerprint: str,
    status: str = "tailored",
    description: str = _DEFAULT_DESCRIPTION,
    title: str = "Senior Backend Engineer",
    company: str = "Acme",
) -> Job:
    job = Job(
        fingerprint=fingerprint,
        external_id=f"ext-{fingerprint}",
        title=title,
        company=company,
        url=f"https://example.com/{fingerprint}",
        source="greenhouse",
        description=description,
        status=status,
        score=80,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _seed_tailoring_record(
    session,
    *,
    job_id: int,
    tailored_path: Path,
    cover_letter_path: Path | None,
    retry_count: int = 1,
    validation_passed: bool = True,
) -> TailoringRecord:
    record = TailoringRecord(
        job_id=job_id,
        version=1,
        intensity="balanced",
        status="completed",
        base_resume_path="/tmp/base.docx",
        tailored_resume_path=str(tailored_path),
        cover_letter_path=str(cover_letter_path) if cover_letter_path else None,
        validation_passed=validation_passed,
        retry_count=retry_count,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


def _make_ctx() -> RunContext:
    return RunContext(
        run_id=1,
        started_at=datetime.utcnow(),
        dry_run=False,
        triggered_by="test",
        tz="UTC",
    )


@pytest_asyncio.fixture
async def pipeline_env(
    async_session_factory, env_with_fernet, tmp_path, monkeypatch
):
    """Bundle everything a pipeline test needs.

    Yields a dataclass with the session factory, a SMTP spy with
    ``aiosmtplib.send`` already monkeypatched, a path to a tailored
    DOCX, a path to a cover letter DOCX, and a ``FakeRateLimiter``
    with cap=100 by default.
    """
    import importlib
    import app.config

    importlib.reload(app.config)

    tailored_path = tmp_path / "v1.docx"
    _write_docx(
        tailored_path,
        "Jane Doe",
        "Senior Backend Engineer",
        "Python FastAPI Postgres Docker Kubernetes",
        "Led async Python services for a fintech startup.",
    )
    cover_letter_path = tmp_path / "cover_letter_v1.docx"
    _write_docx(
        cover_letter_path,
        "Dear Hiring Manager,",
        "I am excited to apply for the Senior Backend Engineer role.",
        "Sincerely, Jane Doe",
    )

    spy = _SmtpSpy()
    monkeypatch.setattr(aiosmtplib, "send", spy)

    async with async_session_factory() as session:
        await _seed_smtp_secrets(session, env_with_fernet)
        await _seed_profile(session)
        await _seed_settings(session)

    @dataclass
    class _Env:
        session_factory: Any
        spy: _SmtpSpy
        tailored_path: Path
        cover_letter_path: Path
        rate_limiter: _FakeRateLimiter

    return _Env(
        session_factory=async_session_factory,
        spy=spy,
        tailored_path=tailored_path,
        cover_letter_path=cover_letter_path,
        rate_limiter=_FakeRateLimiter(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_submits_high_confidence_job_once(pipeline_env):
    """SC-1 + SC-4 happy path: auto mode -> one sent email, rate limiter credited."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        job = await _seed_job(
            session,
            fingerprint="happy1",
            description=(
                "Python FastAPI Postgres Docker Kubernetes async services. "
                "Reach recruiting@acme.example.com to apply."
            ),
        )
        record = await _seed_tailoring_record(
            session,
            job_id=job.id,
            tailored_path=pipeline_env.tailored_path,
            cover_letter_path=pipeline_env.cover_letter_path,
            retry_count=1,
            validation_passed=True,
        )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["submitted"] == 1
    assert counts["submission_failed"] == 0
    assert counts["needs_info"] == 0
    assert pipeline_env.rate_limiter.record_calls == 1
    # 1 application email + 1 success notification (both hit the SMTP spy).
    assert len(pipeline_env.spy.calls) == 2

    # Job flipped to submitted, submission row sent.
    async with pipeline_env.session_factory() as session:
        job_row = await session.get(Job, job.id)
        assert job_row.status == "submitted"
        subs = (
            (await session.execute(select(Submission))).scalars().all()
        )
        assert len(subs) == 1
        assert subs[0].status == "sent"
        assert subs[0].smtp_to == "recruiting@acme.example.com"


@pytest.mark.asyncio
async def test_idempotent_double_run_no_double_send(pipeline_env):
    """SC-7: second pass sees no approved/tailored jobs and is a clean no-op."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        job = await _seed_job(
            session,
            fingerprint="idem1",
        )
        await _seed_tailoring_record(
            session,
            job_id=job.id,
            tailored_path=pipeline_env.tailored_path,
            cover_letter_path=pipeline_env.cover_letter_path,
        )

    counts_a = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )
    counts_b = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts_a["submitted"] == 1
    assert counts_b["submitted"] == 0
    # Application was sent exactly once (plus one success notification).
    app_msgs = [
        c for c in pipeline_env.spy.calls
        if not str(c["msg"]["Subject"]).startswith("[")
    ]
    assert len(app_msgs) == 1

    async with pipeline_env.session_factory() as session:
        subs = (
            (await session.execute(select(Submission))).scalars().all()
        )
        assert len(subs) == 1
        assert subs[0].status == "sent"


@pytest.mark.asyncio
async def test_low_confidence_holdout_leaves_job_in_tailored(pipeline_env):
    """Retry_count=3 -> not first-try -> held out, no Submission row."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        job = await _seed_job(
            session,
            fingerprint="holdout1",
            description="Email us at talent@acme.example.com",
        )
        await _seed_tailoring_record(
            session,
            job_id=job.id,
            tailored_path=pipeline_env.tailored_path,
            cover_letter_path=pipeline_env.cover_letter_path,
            retry_count=3,
            validation_passed=True,
        )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["held_out"] == 1
    assert counts["submitted"] == 0
    assert pipeline_env.spy.calls == []

    async with pipeline_env.session_factory() as session:
        job_row = await session.get(Job, job.id)
        assert job_row.status == "tailored"
        subs = (
            (await session.execute(select(Submission))).scalars().all()
        )
        assert subs == []


@pytest.mark.asyncio
async def test_review_mode_never_auto_submits(pipeline_env):
    """auto_mode=False leaves tailored jobs alone; drain loop sees zero approved."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        await _seed_settings(session, auto_mode=False)
        job = await _seed_job(
            session,
            fingerprint="review1",
            description="Send to people@acme.example.com",
        )
        await _seed_tailoring_record(
            session,
            job_id=job.id,
            tailored_path=pipeline_env.tailored_path,
            cover_letter_path=pipeline_env.cover_letter_path,
        )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["submitted"] == 0
    assert counts["held_out"] == 0
    assert pipeline_env.spy.calls == []
    async with pipeline_env.session_factory() as session:
        job_row = await session.get(Job, job.id)
        assert job_row.status == "tailored"


@pytest.mark.asyncio
async def test_approved_queue_drains_in_review_mode(pipeline_env):
    """Review mode drains jobs already approved by the review UI."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        await _seed_settings(session, auto_mode=False)
        job = await _seed_job(
            session,
            fingerprint="rev-approved",
            status="approved",
            description="Reach out to hiring@acme.example.com",
        )
        await _seed_tailoring_record(
            session,
            job_id=job.id,
            tailored_path=pipeline_env.tailored_path,
            cover_letter_path=pipeline_env.cover_letter_path,
        )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["submitted"] == 1
    async with pipeline_env.session_factory() as session:
        job_row = await session.get(Job, job.id)
        assert job_row.status == "submitted"


@pytest.mark.asyncio
async def test_daily_cap_halt_leaves_remainder_approved(pipeline_env):
    """Cap=1 -> first job sends, remainder stays approved, counts['rate_limited']=True."""
    from app.submission.pipeline import run_submission

    pipeline_env.rate_limiter.fail_after = 1  # 1 allowed then halt

    async with pipeline_env.session_factory() as session:
        for i in range(3):
            job = await _seed_job(
                session,
                fingerprint=f"cap{i}",
                status="approved",
                description=f"apply to hr{i}@acme.example.com",
            )
            await _seed_tailoring_record(
                session,
                job_id=job.id,
                tailored_path=pipeline_env.tailored_path,
                cover_letter_path=pipeline_env.cover_letter_path,
            )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["submitted"] == 1
    assert counts["rate_limited"] is True

    async with pipeline_env.session_factory() as session:
        rows = (
            await session.execute(select(Job).order_by(Job.id))
        ).scalars().all()
        statuses = [j.status for j in rows]
        # One submitted, two still approved for tomorrow's run.
        assert statuses.count("submitted") == 1
        assert statuses.count("approved") == 2


@pytest.mark.asyncio
async def test_pause_toggle_skips_entire_stage(pipeline_env):
    """Pause -> returns paused=True, no SMTP calls, jobs stay approved."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        await _seed_settings(session, submissions_paused=True)
        for i in range(3):
            job = await _seed_job(
                session,
                fingerprint=f"pause{i}",
                status="approved",
                description=f"send to hr{i}@acme.example.com",
            )
            await _seed_tailoring_record(
                session,
                job_id=job.id,
                tailored_path=pipeline_env.tailored_path,
                cover_letter_path=pipeline_env.cover_letter_path,
            )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["paused"] is True
    assert counts["submitted"] == 0
    assert pipeline_env.spy.calls == []

    async with pipeline_env.session_factory() as session:
        rows = (
            await session.execute(select(Job).order_by(Job.id))
        ).scalars().all()
        assert all(j.status == "approved" for j in rows)


@pytest.mark.asyncio
async def test_quiet_hours_halt_leaves_remainder_approved(pipeline_env):
    """Quiet hours 0..23 (23 hours) -> any UTC hour is quiet."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        await _seed_settings(session, quiet_hours_start=0, quiet_hours_end=23)
        for i in range(2):
            job = await _seed_job(
                session,
                fingerprint=f"quiet{i}",
                status="approved",
                description=f"send to hr{i}@acme.example.com",
            )
            await _seed_tailoring_record(
                session,
                job_id=job.id,
                tailored_path=pipeline_env.tailored_path,
                cover_letter_path=pipeline_env.cover_letter_path,
            )

    # Force clock to hour 5 (definitely inside 0..23).
    def _fixed_clock():
        return datetime(2026, 4, 15, 5, 0, 0)

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
        clock=_fixed_clock,
    )

    assert counts["submitted"] == 0
    assert counts["quiet_hours_skipped"] is True
    assert pipeline_env.spy.calls == []

    async with pipeline_env.session_factory() as session:
        rows = (
            await session.execute(select(Job).order_by(Job.id))
        ).scalars().all()
        assert all(j.status == "approved" for j in rows)


@pytest.mark.asyncio
async def test_missing_recipient_flips_needs_info(pipeline_env):
    """No email in description -> needs_info + failure notification."""
    from app.submission.pipeline import run_submission

    async with pipeline_env.session_factory() as session:
        job = await _seed_job(
            session,
            fingerprint="noemail1",
            status="approved",
            description="No email anywhere, just plain text.",
        )
        await _seed_tailoring_record(
            session,
            job_id=job.id,
            tailored_path=pipeline_env.tailored_path,
            cover_letter_path=pipeline_env.cover_letter_path,
        )

    counts = await run_submission(
        _make_ctx(),
        pipeline_env.session_factory,
        rate_limiter=pipeline_env.rate_limiter,
    )

    assert counts["needs_info"] == 1
    assert counts["submitted"] == 0

    async with pipeline_env.session_factory() as session:
        job_row = await session.get(Job, job.id)
        assert job_row.status == "needs_info"

    # One failure notification email hit the spy.
    failure_msgs = [
        c for c in pipeline_env.spy.calls
        if "[Submission failed]" in str(c["msg"]["Subject"])
    ]
    assert len(failure_msgs) == 1
    assert "NoRecipientEmail" in str(failure_msgs[0]["msg"]["Subject"])


@pytest.mark.asyncio
async def test_smtp_auth_error_flips_failed_and_notifies(pipeline_env):
    """SMTP auth error -> Submission=failed, Job=failed, failure notify fired."""
    from app.submission.pipeline import run_submission

    # First send (application) fails with auth error; subsequent sends
    # (failure notification) succeed so the notification path itself
    # is exercised.
    call_count = {"n": 0}
    original_send = pipeline_env.spy

    async def _side_effect_send(msg, **kwargs):
        call_count["n"] += 1
        original_send.calls.append({"msg": msg, **kwargs})
        if call_count["n"] == 1:
            raise aiosmtplib.SMTPAuthenticationError(535, "bad creds")

    import app.submission.sender as sender_mod

    # Patch the aiosmtplib.send at the module lookup points used by both
    # the sender and the notifications helper.
    from unittest.mock import patch

    with patch.object(aiosmtplib, "send", _side_effect_send):
        async with pipeline_env.session_factory() as session:
            job = await _seed_job(
                session,
                fingerprint="authfail1",
                status="approved",
                description="apply to hr@acme.example.com",
            )
            await _seed_tailoring_record(
                session,
                job_id=job.id,
                tailored_path=pipeline_env.tailored_path,
                cover_letter_path=pipeline_env.cover_letter_path,
            )

        counts = await run_submission(
            _make_ctx(),
            pipeline_env.session_factory,
            rate_limiter=pipeline_env.rate_limiter,
        )

    assert counts["submission_failed"] == 1
    assert counts["submitted"] == 0

    async with pipeline_env.session_factory() as session:
        job_row = await session.get(Job, job.id)
        assert job_row.status == "failed"
        subs = (
            (await session.execute(select(Submission))).scalars().all()
        )
        assert len(subs) == 1
        assert subs[0].status == "failed"
        assert subs[0].error_class == "SMTPAuthenticationError"
        # One suppression row recorded for this signature.
        supps = (
            (await session.execute(select(FailureSuppression))).scalars().all()
        )
        assert len(supps) == 1
        assert supps[0].error_class == "SMTPAuthenticationError"


@pytest.mark.asyncio
async def test_second_same_signature_failure_suppressed(pipeline_env):
    """Two identical auth failures -> only one failure notification email."""
    from app.submission.pipeline import run_submission

    call_count = {"n": 0}
    notification_msgs: list[Any] = []

    async def _side_effect_send(msg, **kwargs):
        call_count["n"] += 1
        subject = str(msg["Subject"])
        if "[Submission failed]" in subject:
            notification_msgs.append(msg)
            return
        # Fail every application send with the same auth error so the
        # signature stays stable.
        raise aiosmtplib.SMTPAuthenticationError(535, "bad creds")

    from unittest.mock import patch

    with patch.object(aiosmtplib, "send", _side_effect_send):
        async with pipeline_env.session_factory() as session:
            for i in range(2):
                job = await _seed_job(
                    session,
                    fingerprint=f"supp{i}",
                    status="approved",
                    description=f"apply to hr{i}@acme.example.com",
                )
                await _seed_tailoring_record(
                    session,
                    job_id=job.id,
                    tailored_path=pipeline_env.tailored_path,
                    cover_letter_path=pipeline_env.cover_letter_path,
                )

        counts = await run_submission(
            _make_ctx(),
            pipeline_env.session_factory,
            rate_limiter=pipeline_env.rate_limiter,
        )

    # Both jobs flipped to failed but only one notification email sent
    # (suppression kicks in for the second).
    assert counts["submission_failed"] == 2
    assert len(notification_msgs) == 1

    async with pipeline_env.session_factory() as session:
        rows = (
            await session.execute(select(Job).order_by(Job.id))
        ).scalars().all()
        assert all(j.status == "failed" for j in rows)
        supps = (
            (await session.execute(select(FailureSuppression))).scalars().all()
        )
        assert len(supps) == 1
        # Two occurrences recorded against the single signature.
        assert supps[0].occurrence_count == 2
