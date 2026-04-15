"""Failure signature and suppression helpers (Phase 5 NOTIF-02).

The submission pipeline produces failures in many shapes — recipient
addresses change, error byte counts change, every transient TCP timeout
has a different epoch suffix. None of those substantive variations
should produce a *new* notification email when the underlying failure
is the same SMTP misconfiguration. This module provides the canonical
hash + suppression CRUD that the notification senders consult before
sending anything.

Locked decisions captured in CONTEXT.md / PROJECT.md:

* signature = SHA256 of ``stage|error_class|canon_message`` where the
  canonicalisation strips emails, digits, and collapses whitespace
  (research pitfall 4).
* "First-occurrence" semantics: row absent OR ``cleared_at IS NOT NULL``
  → fresh notification fires.
* Repeats while ``cleared_at IS NULL`` increment ``occurrence_count``
  but suppress the outbound email.
* Cleared rows are RE-USED on the next occurrence of the same
  signature: ``cleared_at`` resets to ``None``, ``cleared_by`` resets,
  ``notify_count`` increments (count of distinct bursts the user has
  been notified about), ``occurrence_count`` resets to ``1``,
  ``last_seen_at`` updates. This preserves the schema's
  ``signature UNIQUE`` constraint (Plan 05-01 wired the index that way)
  while still firing a fresh notification on each new burst — the
  ``notify_count`` column is the audit trail of "how many distinct
  bursts of this signature has the user been alerted about".
* Two clear paths: ``auto_next_success`` (the next successful
  submission for the same stage clears every uncleared row) and
  ``user_ack`` (the dashboard /notifications/ack/{id} endpoint).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.submission.models import FailureSuppression

log = structlog.get_logger(__name__)

# Canonicalisation regexes — order matters: strip emails first (they
# contain '.' which the email regex anchors on), then digits, then
# whitespace collapse. All three pre-compiled at module import.
_EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
_DIGIT_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def _canonicalize(message: str) -> str:
    """Lowercase, strip emails, strip digits, collapse whitespace.

    Research pitfall 4: raw exception messages carry recipient addresses
    and byte counts (``550 <foo@bar.com> user unknown``, ``timeout after
    30s``). Two different recipients hitting the same failure mode MUST
    yield the same signature so we don't spam the user with one email
    per recipient.

    Empty / ``None`` input returns ``""`` rather than raising — callers
    pass straight from ``str(exc)`` and an empty exception message is
    not an error condition for this layer.
    """
    if not message:
        return ""
    s = message.lower()
    s = _EMAIL_RE.sub("<email>", s)
    s = _DIGIT_RE.sub("N", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def build_signature(*, error_class: str, stage: str, message: str) -> str:
    """SHA-256 of the ``stage|error_class|canon_message`` tuple.

    Keyword-only so callers can never silently swap ``stage`` and
    ``error_class``; the hash would still be stable but partitioned
    incorrectly across submission/pipeline buckets.

    Stage is included in the hash so the same SMTPAuthenticationError
    surfacing in a discovery job vs a submission job suppresses
    independently — they come from different code paths and the user
    needs to be reminded separately when each clears.
    """
    canon = _canonicalize(message)
    payload = f"{stage}|{error_class}|{canon}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def should_notify(
    session: AsyncSession,
    *,
    signature: str,
    stage: str,
    error_class: str,
    message: str,
) -> bool:
    """Return True if this signature is new (and record it), False if suppressed.

    First call for a given signature: inserts a FailureSuppression row
    with ``notify_count=1``, ``occurrence_count=1``, returns True.

    Subsequent call while ``cleared_at IS NULL``: increments
    ``occurrence_count`` and ``last_seen_at``, returns False.

    After a successful clear (``cleared_at IS NOT NULL``): the row is
    re-opened in place — ``cleared_at`` reset to ``None``,
    ``cleared_by`` reset, ``notify_count`` incremented (this is the
    Nth distinct burst the user has been notified about),
    ``occurrence_count`` reset to ``1``, ``last_seen_at`` updated. We
    cannot insert a NEW row because Plan 05-01 wired
    ``failure_suppressions.signature`` as a UNIQUE index — a second row
    would violate the constraint. Re-using the row preserves the
    "fresh notification fires" contract while honouring the schema.
    """
    result = await session.execute(
        select(FailureSuppression).where(FailureSuppression.signature == signature)
    )
    row = result.scalar_one_or_none()
    if row is None:
        new_row = FailureSuppression(
            signature=signature,
            stage=stage,
            error_class=error_class,
            error_message_canon=_canonicalize(message),
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
            notify_count=1,
            occurrence_count=1,
        )
        session.add(new_row)
        await session.commit()
        log.info(
            "suppression_new",
            signature=signature[:12],
            stage=stage,
            error_class=error_class,
        )
        return True
    if row.cleared_at is not None:
        # Row was previously cleared — re-open as a fresh burst.
        row.cleared_at = None
        row.cleared_by = None
        row.notify_count += 1
        row.occurrence_count = 1
        row.last_seen_at = datetime.utcnow()
        await session.commit()
        log.info(
            "suppression_reopened",
            signature=signature[:12],
            stage=stage,
            notify_count=row.notify_count,
        )
        return True
    # Open row — suppress the email but record the additional occurrence.
    row.occurrence_count += 1
    row.last_seen_at = datetime.utcnow()
    await session.commit()
    log.debug(
        "suppression_hit",
        signature=signature[:12],
        occurrences=row.occurrence_count,
    )
    return False


async def clear_suppressions_for_stage(
    session: AsyncSession,
    stage: str,
    *,
    cleared_by: str = "auto_next_success",
) -> int:
    """Mark all uncleared suppression rows for a given stage as cleared.

    Called after every successful submission so that the next failure
    of a previously-suppressed signature once again reaches the user as
    a fresh notification (the underlying issue might have come back).

    Returns the number of rows cleared (zero if none were pending).
    """
    result = await session.execute(
        select(FailureSuppression)
        .where(FailureSuppression.stage == stage)
        .where(FailureSuppression.cleared_at.is_(None))
    )
    rows = result.scalars().all()
    now = datetime.utcnow()
    count = 0
    for row in rows:
        row.cleared_at = now
        row.cleared_by = cleared_by
        count += 1
    if count:
        await session.commit()
        log.info("suppression_cleared", stage=stage, count=count, cleared_by=cleared_by)
    return count


async def ack_suppression(session: AsyncSession, suppression_id: int) -> bool:
    """Mark one suppression row as user-acknowledged.

    Returns True on success, False if the row id does not exist.
    Used by the ``POST /notifications/ack/{id}`` route — the user has
    seen the failure email and wants future occurrences to fire again
    even before the next successful submission clears the bucket.
    """
    row = await session.get(FailureSuppression, suppression_id)
    if row is None:
        return False
    row.cleared_at = datetime.utcnow()
    row.cleared_by = "user_ack"
    await session.commit()
    log.info("suppression_user_ack", suppression_id=suppression_id)
    return True


__all__ = [
    "build_signature",
    "should_notify",
    "clear_suppressions_for_stage",
    "ack_suppression",
]
