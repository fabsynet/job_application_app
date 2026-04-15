"""Email submitter strategy — the only Phase 5 concrete strategy (SUBM-01).

Wraps Plan 05-02's :func:`~app.submission.builder.build_email_message`
and :func:`~app.submission.sender.send_via_smtp` behind the
:class:`~app.submission.registry.SubmitterStrategy` protocol so the
Plan 05-04 pipeline can dispatch via ``select_strategy(...)`` and Phase 6
can plug in a Playwright strategy without touching the caller.

The strategy is stateless and never writes to the DB. Persistence (the
Submission row, Job.status transition, failure suppression) is owned by
the pipeline, which observes the returned :class:`SubmissionOutcome`.
"""
from __future__ import annotations

import structlog

from app.discovery.models import Job
from app.submission.builder import (
    build_email_message,
    resolve_recipient_email,
)
from app.submission.registry import (
    SubmissionContext,
    SubmissionOutcome,
    SubmitterStrategy,
)
from app.submission.sender import (
    SmtpConfig,
    SubmissionSendError,
    send_via_smtp,
)

log = structlog.get_logger(__name__)


class EmailStrategy:
    """SUBM-01: send via SMTP when a contact email is derivable.

    Applicable iff :func:`resolve_recipient_email` can extract a
    non-noreply address from the job description. The pipeline is
    responsible for populating ``ctx.recipient_email`` before calling
    :meth:`submit` — the strategy does not re-resolve the address inside
    ``submit`` so the pipeline can override it (e.g. for manual-paste
    jobs where the user supplied the recipient explicitly).
    """

    name: str = "email"

    def is_applicable(self, job: Job, description: str) -> bool:
        return resolve_recipient_email(description) is not None

    async def submit(self, ctx: SubmissionContext) -> SubmissionOutcome:
        msg = build_email_message(
            from_addr=ctx.smtp_creds.username,
            to_addr=ctx.recipient_email,
            subject=ctx.subject,
            body_text=ctx.body_text,
            attachment_path=ctx.tailored_resume_path,
            attachment_filename=ctx.attachment_filename,
        )
        cfg = SmtpConfig(
            host=ctx.smtp_creds.host,
            port=ctx.smtp_creds.port,
            username=ctx.smtp_creds.username,
            password=ctx.smtp_creds.password,
        )
        try:
            await send_via_smtp(msg, cfg)
        except SubmissionSendError as exc:
            log.warning(
                "email_strategy_failed",
                job_id=ctx.job.id,
                error_class=exc.error_class,
                error=exc.message,
            )
            return SubmissionOutcome(
                success=False,
                submitter=self.name,
                error_class=exc.error_class,
                error_message=exc.message,
            )
        log.info(
            "email_strategy_sent",
            job_id=ctx.job.id,
            to=ctx.recipient_email,
            subject=ctx.subject,
        )
        return SubmissionOutcome(success=True, submitter=self.name)


__all__ = ["EmailStrategy"]
