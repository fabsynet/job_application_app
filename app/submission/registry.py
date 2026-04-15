"""Submitter registry + strategy protocol (SUBM-06).

Phase 5 ships the :class:`~app.submission.strategies.email.EmailStrategy`.
Phase 6 will add a ``PlaywrightStrategy`` behind the same Protocol without
touching the caller (``run_submission`` in Plan 05-04).

The pipeline (05-04) calls::

    strategy = select_strategy(job, job.description, registry)
    if strategy is None:
        # No submitter applies — flip Job.status = 'needs_info'
        ...
    outcome = await strategy.submit(ctx)

Strategies are stateless — they do NOT write to the DB. The pipeline
owns persistence of :class:`~app.submission.models.Submission` rows,
``Job.status`` transitions, and failure-suppression calls. Keeping the
registry DB-free means it is unit-testable without a database fixture.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.discovery.models import Job
from app.submission.creds import SmtpCreds


@dataclass
class SubmissionContext:
    """All inputs a strategy needs to build + send one application.

    Populated by ``run_submission`` (Plan 05-04). The strategy reads from
    this context, does not mutate it, and returns a
    :class:`SubmissionOutcome`. Phase 6 will extend this dataclass with
    optional Playwright fields without changing the email strategy.
    """

    job: Job
    tailored_resume_path: Path
    cover_letter_path: Path
    recipient_email: str
    subject: str
    body_text: str
    attachment_filename: str
    smtp_creds: SmtpCreds  # only used by EmailStrategy; Playwright will ignore


@dataclass
class SubmissionOutcome:
    """What a strategy returns to the pipeline after attempting a send.

    On success: ``success=True``, ``error_class=None``. On failure:
    ``success=False`` plus ``error_class`` + ``error_message`` populated
    for the Plan 05-05 failure-suppression signature.
    """

    success: bool
    submitter: str  # matches Submission.submitter ('email' | 'playwright' | ...)
    error_class: str | None = None
    error_message: str | None = None


@runtime_checkable
class SubmitterStrategy(Protocol):
    """Submitter strategy protocol — one implementation per channel."""

    name: str

    def is_applicable(self, job: Job, description: str) -> bool:
        """Return True iff this strategy can submit the given job.

        :class:`~app.submission.strategies.email.EmailStrategy` returns
        True iff a non-noreply recipient email can be parsed out of the
        description. ``PlaywrightStrategy`` (Phase 6) will return True
        iff the source is a known ATS with a browser-fillable form.

        ``description`` is passed explicitly (not read from ``job``) so
        the pipeline can pass a cleaned / best-effort description for
        manual-paste jobs without shadowing the ``Job`` row.
        """
        ...

    async def submit(self, ctx: SubmissionContext) -> SubmissionOutcome:
        """Attempt the actual send. Must NOT write to the DB."""
        ...


def default_registry() -> list[SubmitterStrategy]:
    """Return the Phase 5 default registry: ``[EmailStrategy()]``."""
    # Lazy import to avoid a circular: the email strategy imports
    # SubmissionContext / SubmissionOutcome / SubmitterStrategy from this
    # module.
    from app.submission.strategies.email import EmailStrategy

    return [EmailStrategy()]


def select_strategy(
    job: Job,
    description: str,
    registry: list[SubmitterStrategy] | None = None,
) -> SubmitterStrategy | None:
    """Pick the first strategy whose :meth:`is_applicable` returns True.

    Returns ``None`` if no strategy applies — the pipeline (Plan 05-04)
    treats this as ``needs_info`` and emits a failure notification (SC-1
    fail-closed).

    Phase 5 behaviour with ``registry == [EmailStrategy()]``:

    * ``resolve_recipient_email(description)`` not None → ``EmailStrategy``
    * otherwise                                        → ``None``
    """
    reg = registry if registry is not None else default_registry()
    for strategy in reg:
        if strategy.is_applicable(job, description):
            return strategy
    return None


__all__ = [
    "SubmissionContext",
    "SubmissionOutcome",
    "SubmitterStrategy",
    "default_registry",
    "select_strategy",
]
