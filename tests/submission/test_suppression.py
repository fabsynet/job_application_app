"""Tests for app.submission.suppression — failure signature + suppression CRUD."""
from __future__ import annotations

import pytest

from app.submission.suppression import (
    _canonicalize,
    ack_suppression,
    build_signature,
    clear_suppressions_for_stage,
    should_notify,
)
from app.submission.models import FailureSuppression
from sqlalchemy import select


# ---- _canonicalize ---------------------------------------------------------


def test_canonicalize_strips_emails_and_digits():
    raw = "550 <Foo@Bar.com> user unknown after 30 retries"
    canon = _canonicalize(raw)
    # No literal email, no digits, lowercased.
    assert "foo@bar.com" not in canon
    assert "<email>" in canon
    assert "30" not in canon
    assert "550" not in canon
    # 'N' substitutes digit runs.
    assert "n" in canon


def test_canonicalize_empty_safe():
    assert _canonicalize("") == ""
    assert _canonicalize(None) == ""  # type: ignore[arg-type]


def test_canonicalize_collapses_whitespace():
    raw = "line1\n\n  line2\t\tline3"
    canon = _canonicalize(raw)
    assert "  " not in canon
    assert "\t" not in canon
    assert "\n" not in canon


# ---- build_signature -------------------------------------------------------


def test_build_signature_stable_for_canonicalized_messages():
    """Different recipients hitting the same SMTPRecipientsRefused
    must hash to the same signature (research pitfall 4)."""
    sig_a = build_signature(
        error_class="SMTPRecipientsRefused",
        stage="submission",
        message="550 <foo@bar.com> mailbox unavailable",
    )
    sig_b = build_signature(
        error_class="SMTPRecipientsRefused",
        stage="submission",
        message="550 <BAZ@qux.com> mailbox unavailable",
    )
    assert sig_a == sig_b


def test_build_signature_different_for_different_classes():
    sig_a = build_signature(
        error_class="SMTPRecipientsRefused", stage="submission", message="boom"
    )
    sig_b = build_signature(
        error_class="SMTPAuthenticationError", stage="submission", message="boom"
    )
    assert sig_a != sig_b


def test_build_signature_different_for_different_stages():
    """Stage partitioning: same error in submission vs pipeline must
    suppress in their own buckets."""
    sig_sub = build_signature(
        error_class="RuntimeError", stage="submission", message="kaboom"
    )
    sig_pipe = build_signature(
        error_class="RuntimeError", stage="pipeline", message="kaboom"
    )
    assert sig_sub != sig_pipe


def test_build_signature_is_hex_sha256():
    sig = build_signature(error_class="X", stage="submission", message="y")
    assert len(sig) == 64
    int(sig, 16)  # raises if not hex


# ---- should_notify ---------------------------------------------------------


@pytest.mark.asyncio
async def test_should_notify_first_time_true(async_session):
    sig = build_signature(
        error_class="SMTPAuthenticationError", stage="submission", message="auth bad"
    )
    notified = await should_notify(
        async_session,
        signature=sig,
        stage="submission",
        error_class="SMTPAuthenticationError",
        message="auth bad",
    )
    assert notified is True
    # Row must exist with notify_count=1, occurrence_count=1.
    row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig)
        )
    ).scalar_one()
    assert row.notify_count == 1
    assert row.occurrence_count == 1
    assert row.cleared_at is None
    assert row.stage == "submission"


@pytest.mark.asyncio
async def test_should_notify_duplicate_returns_false_and_increments_count(async_session):
    sig = build_signature(
        error_class="SMTPAuthenticationError", stage="submission", message="auth bad"
    )
    # First call → True
    first = await should_notify(
        async_session,
        signature=sig,
        stage="submission",
        error_class="SMTPAuthenticationError",
        message="auth bad",
    )
    # Second call → False (suppressed)
    second = await should_notify(
        async_session,
        signature=sig,
        stage="submission",
        error_class="SMTPAuthenticationError",
        message="auth bad",
    )
    assert first is True
    assert second is False
    row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig)
        )
    ).scalar_one()
    assert row.occurrence_count == 2


# ---- clear_suppressions_for_stage ------------------------------------------


@pytest.mark.asyncio
async def test_clear_suppressions_for_stage_marks_cleared(async_session):
    sig = build_signature(error_class="X", stage="submission", message="m")
    await should_notify(
        async_session, signature=sig, stage="submission", error_class="X", message="m"
    )
    cleared = await clear_suppressions_for_stage(async_session, "submission")
    assert cleared == 1
    row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig)
        )
    ).scalar_one()
    assert row.cleared_at is not None
    assert row.cleared_by == "auto_next_success"


@pytest.mark.asyncio
async def test_clear_only_targets_named_stage(async_session):
    sig_sub = build_signature(error_class="X", stage="submission", message="m")
    sig_pipe = build_signature(error_class="X", stage="pipeline", message="m")
    await should_notify(
        async_session, signature=sig_sub, stage="submission", error_class="X", message="m"
    )
    await should_notify(
        async_session, signature=sig_pipe, stage="pipeline", error_class="X", message="m"
    )
    cleared = await clear_suppressions_for_stage(async_session, "submission")
    assert cleared == 1
    # pipeline row untouched
    pipe_row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig_pipe)
        )
    ).scalar_one()
    assert pipe_row.cleared_at is None


@pytest.mark.asyncio
async def test_fresh_signature_after_clear_treated_as_new(async_session):
    """After clearing, a repeat of the same signature re-opens the row
    in place (signature is UNIQUE per Plan 05-01 schema) and returns
    True — notify_count increments so the audit trail records the
    distinct bursts even though the row is re-used."""
    sig = build_signature(error_class="X", stage="submission", message="m")
    await should_notify(
        async_session, signature=sig, stage="submission", error_class="X", message="m"
    )
    await clear_suppressions_for_stage(async_session, "submission")
    second = await should_notify(
        async_session, signature=sig, stage="submission", error_class="X", message="m"
    )
    assert second is True
    # Single row, re-opened: cleared_at None, notify_count=2,
    # occurrence_count reset to 1.
    rows = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig)
        )
    ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.cleared_at is None
    assert row.cleared_by is None
    assert row.notify_count == 2
    assert row.occurrence_count == 1


# ---- ack_suppression -------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_suppression_marks_user_ack(async_session):
    sig = build_signature(error_class="X", stage="submission", message="m")
    await should_notify(
        async_session, signature=sig, stage="submission", error_class="X", message="m"
    )
    row = (
        await async_session.execute(
            select(FailureSuppression).where(FailureSuppression.signature == sig)
        )
    ).scalar_one()
    ok = await ack_suppression(async_session, row.id)
    assert ok is True
    await async_session.refresh(row)
    assert row.cleared_at is not None
    assert row.cleared_by == "user_ack"


@pytest.mark.asyncio
async def test_ack_suppression_missing_row_returns_false(async_session):
    ok = await ack_suppression(async_session, 99999)
    assert ok is False
