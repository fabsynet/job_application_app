"""Phase 5 notification senders (NOTIF-01, NOTIF-02).

Three public coroutines sit on top of the Phase 5 SMTP primitives:

* :func:`send_success_notification` — fires once per successful
  submission, attaches the tailored DOCX, never suppressed.
* :func:`send_failure_notification` — fires the first time a given
  failure signature appears in a stage; subsequent occurrences are
  suppressed until the bucket is cleared.
* :func:`send_pipeline_failure_notification` — wrapper for
  pipeline-level breakage (killswitch trip, budget halt, crash) using
  ``stage='pipeline'`` so it suppresses independently of submission
  failures.

CRITICAL — locked decision from CONTEXT.md and research pitfall 5:
**these functions are quiet-window-agnostic**. Notifications fire at
any time of day regardless of the operator's silence window. That
window gates outbound *applications* to recruiters, not inbox updates
to the operator. The unit test ``test_notification_sends_during_silence_window``
codifies this contract — do not add a time-of-day gate here.
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.settings.service import get_profile_row, get_settings_row
from app.submission.builder import build_attachment_filename
from app.submission.creds import SmtpCredsMissing, load_smtp_creds
from app.submission.sender import SmtpConfig, SubmissionSendError, send_via_smtp
from app.submission.suppression import build_signature, should_notify
from app.tailoring.models import TailoringRecord

log = structlog.get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent.parent / "web" / "templates" / "emails"
_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),  # plaintext only
    keep_trailing_newline=True,
)


async def send_success_notification(
    session: AsyncSession,
    *,
    job: Job,
    record: TailoringRecord,
    submission_id: int,
    recipient_email: str,
    reused_answers: list[tuple[str, str]] | None = None,
) -> bool:
    """SC-4: one summary email per successful submission.

    Always sends — no suppression. Idempotency is enforced by the
    submission pipeline (one call per successful send) and by the
    ``ux_submissions_job_sent`` partial UNIQUE index on the
    ``submissions`` table (Plan 05-01).

    Returns ``True`` if the email was sent, ``False`` if a precondition
    blocked it (missing SMTP credentials, missing tailored DOCX
    artifact, SMTP error). Failures here are logged structurally but
    NOT escalated to the failure-notification path — that would risk a
    feedback loop where a broken SMTP config produces a failure email
    that itself fails to send and recurses.
    """
    settings = await get_settings_row(session)
    try:
        creds = await load_smtp_creds(session)
    except SmtpCredsMissing as exc:
        log.error("notification_creds_missing", missing=exc.name)
        return False

    to_addr = settings.notification_email or creds.username
    base_url = settings.base_url or "http://localhost:8000"

    body = _jinja.get_template("success.txt.j2").render(
        job_title=job.title,
        company=job.company,
        source=job.source,
        score=job.score,
        recipient_email=recipient_email,
        submission_id=submission_id,
        base_url=base_url,
        review_url=f"{base_url}/review/{job.id}",
        tailored_resume_path=record.tailored_resume_path,
        reused_answers=reused_answers or [],
    )

    msg = EmailMessage()
    msg["From"] = creds.username
    msg["To"] = to_addr
    msg["Subject"] = f"[Applied] {job.title} at {job.company}"
    msg.set_content(body)

    # NOTIF-01: attach the tailored DOCX. Read Profile via the same
    # singleton helper the submission pipeline uses so the attachment
    # filename matches what was actually sent to the employer.
    profile = await get_profile_row(session)
    full_name = profile.full_name or ""
    attachment_filename = build_attachment_filename(
        full_name=full_name,
        company=job.company,
    )
    if not record.tailored_resume_path:
        log.error("notification_no_tailored_path", submission_id=submission_id)
        return False
    try:
        attachment_bytes = Path(record.tailored_resume_path).read_bytes()
    except OSError as exc:
        log.error(
            "notification_attachment_missing",
            path=record.tailored_resume_path,
            error=str(exc),
        )
        return False
    msg.add_attachment(
        attachment_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=attachment_filename,
    )

    try:
        await send_via_smtp(
            msg,
            SmtpConfig(
                host=creds.host,
                port=creds.port,
                username=creds.username,
                password=creds.password,
            ),
        )
    except SubmissionSendError as exc:
        log.error("notification_send_failed", error_class=exc.error_class)
        return False
    log.info(
        "notification_success_sent",
        submission_id=submission_id,
        job_id=job.id,
        to=to_addr,
    )
    return True


async def send_failure_notification(
    session: AsyncSession,
    *,
    stage: str,
    error_class: str,
    error_message: str,
    job: Optional[Job] = None,
) -> bool:
    """NOTIF-02: send a failure email, respecting signature suppression.

    Returns ``True`` if sent (first occurrence of this signature),
    ``False`` if suppressed (duplicate, missing creds, SMTP failure).
    """
    signature = build_signature(
        error_class=error_class, stage=stage, message=error_message,
    )
    sent_signal = await should_notify(
        session,
        signature=signature,
        stage=stage,
        error_class=error_class,
        message=error_message,
    )
    if not sent_signal:
        log.debug("failure_notification_suppressed", signature=signature[:12])
        return False

    settings = await get_settings_row(session)
    try:
        creds = await load_smtp_creds(session)
    except SmtpCredsMissing as exc:
        log.error("failure_notification_creds_missing", missing=exc.name)
        return False

    to_addr = settings.notification_email or creds.username
    base_url = settings.base_url or "http://localhost:8000"

    template_name = (
        "failure_submission.txt.j2"
        if stage == "submission"
        else "failure_pipeline.txt.j2"
    )
    body = _jinja.get_template(template_name).render(
        stage=stage,
        error_class=error_class,
        error_message=error_message,
        job=job,
        base_url=base_url,
        signature=signature[:12],
    )

    msg = EmailMessage()
    msg["From"] = creds.username
    msg["To"] = to_addr
    subject_prefix = (
        "[Submission failed]" if stage == "submission" else "[Pipeline failed]"
    )
    if job is not None:
        subject_tail = f" - {job.title} at {job.company} - {error_class}"
    else:
        subject_tail = f" - {error_class}"
    msg["Subject"] = subject_prefix + subject_tail
    msg.set_content(body)

    try:
        await send_via_smtp(
            msg,
            SmtpConfig(
                host=creds.host,
                port=creds.port,
                username=creds.username,
                password=creds.password,
            ),
        )
    except SubmissionSendError as exc:
        log.error(
            "failure_notification_smtp_failed",
            error_class=exc.error_class,
        )
        return False
    log.info(
        "failure_notification_sent",
        signature=signature[:12],
        stage=stage,
        error_class=error_class,
    )
    return True


async def send_pipeline_failure_notification(
    session: AsyncSession,
    *,
    error_class: str,
    error_message: str,
) -> bool:
    """Convenience wrapper for pipeline-level failures.

    Used for killswitch trips, budget halts, scheduler crashes, and
    >50% submission failure rate alerts. Uses ``stage='pipeline'`` so
    these suppress separately from submission failures — a recurring
    SMTPAuthenticationError in the submission stage does not silence
    a fresh KeyboardInterrupt at the pipeline stage and vice versa.
    """
    return await send_failure_notification(
        session,
        stage="pipeline",
        error_class=error_class,
        error_message=error_message,
        job=None,
    )


__all__ = [
    "send_success_notification",
    "send_failure_notification",
    "send_pipeline_failure_notification",
]
