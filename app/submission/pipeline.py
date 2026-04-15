"""Phase 5 submission pipeline stage — ``run_submission``.

This is the stage where SC-1, SC-2, SC-4, and SC-7 come true:

* **SC-1 (fail-closed):** missing recipient / no applicable strategy →
  ``Job.status='needs_info'`` + failure notification, never a silent
  drop.
* **SC-2 (low-confidence holdout + daily cap halt):** auto-mode leaves
  risky tailored jobs in ``tailored`` for manual review; daily cap
  halt leaves the remainder in ``approved`` for tomorrow's run.
* **SC-4 (per-submission cadence):** every successful send emits one
  success notification and clears any matching failure-suppression
  row; every failed send emits one failure notification (subject to
  signature suppression).
* **SC-7 (idempotency):** the partial UNIQUE index
  ``ux_submissions_job_sent`` prevents double-sends, and a second
  pipeline run over the same job is a clean no-op because the job
  has already transitioned out of ``approved``.

Order of operations (the "drain loop" guards):

1. **Pause toggle.** ``Settings.submissions_paused`` → early return
   ``{submitted: 0, paused: True}``. Discovery + tailoring still run
   and fill the queue for the next review cycle.
2. **Auto-mode holdout.** If ``Settings.auto_mode`` is True, iterate
   all ``status='tailored'`` jobs and call
   :func:`app.submission.holdout.should_auto_submit`. Eligible jobs
   flip ``tailored -> approved`` automatically. Everything else stays
   ``tailored`` so the review UI shows it with a reason badge.
3. **Drain the approved queue.** For each ``(job, record)`` in
   :func:`list_approved_jobs`:

   a. Kill-switch check (injected callable).
   b. Quiet hours check — Phase 5 is the **first enforcement site**
      for ``Settings.quiet_hours_start`` / ``quiet_hours_end``. If the
      local hour is within the window, log and break out of the drain
      loop (leave remaining jobs ``approved`` for the next run).
      Research "surprise finding #1": grep confirms no prior code
      reads these two columns.
   c. Rate-limit precheck. ``RateLimitExceeded`` flips
      ``counts['rate_limited']=True`` and breaks out of the drain loop
      (remaining jobs stay ``approved``).
   d. Recipient resolution from ``job.description`` via the 05-02
      regex. ``None`` → ``needs_info``.
   e. Strategy selection via 05-03's ``select_strategy``. ``None`` →
      ``needs_info``.
   f. Build ``SubmissionContext`` (SMTP creds + Profile cached once
      at drain-loop entry).
   g. Insert pending :class:`Submission` row (audit trail survives a
      crash).
   h. Call ``strategy.submit(ctx)``. Success branch:
      ``mark_sent`` (idempotent-guarded) →
      ``flip_job_status(job.id, 'submitted')`` →
      ``rate_limiter.record_submission`` (this is the
      **first real consumer** of that method — research "surprise
      finding #2") →
      ``send_success_notification`` →
      ``clear_suppressions_for_stage('submission')``.
      Failure branch: ``mark_failed`` with classified error →
      ``flip_job_status(job.id, 'failed')`` →
      ``send_failure_notification`` (suppression is internal to the
      sender; do NOT call ``build_signature`` here).
   i. Random inter-submission delay via
      ``rate_limiter.random_action_delay()`` (SAFE-02).

4. **Return counts** dict merged into the scheduler's ``_last_counts``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

import structlog

from app.runs.context import RunContext

log = structlog.get_logger(__name__)


KillSwitchCheck = Callable[[], Awaitable[None]]


# Count-dict keys that stay flat across merges with discovery + tailoring
# counts. The boolean ``paused`` and ``rate_limited`` keys double as
# "halt reason" markers for the dashboard.
def _empty_counts(**overrides: Any) -> dict:
    base = {
        "submitted": 0,
        "submission_failed": 0,
        "needs_info": 0,
        "held_out": 0,
        "paused": False,
        "rate_limited": False,
        "quiet_hours_skipped": False,
        "submission_skipped": 0,
    }
    base.update(overrides)
    return base


def _in_quiet_hours(
    now_hour: int, quiet_start: int, quiet_end: int
) -> bool:
    """Return True iff ``now_hour`` falls within the quiet window.

    Handles wrap-around when ``quiet_end < quiet_start`` (e.g.
    22..7 = 22, 23, 0, 1, 2, 3, 4, 5, 6). ``quiet_start == quiet_end``
    means the window is effectively disabled (zero-length).
    """
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= now_hour < quiet_end
    # Wrap-around: e.g. 22..7 → [22, 23] ∪ [0..7)
    return now_hour >= quiet_start or now_hour < quiet_end


async def run_submission(
    ctx: RunContext,
    session_factory: Any,
    *,
    rate_limiter: Any,
    killswitch_check: Optional[KillSwitchCheck] = None,
    registry: Optional[list] = None,
    clock: Optional[Callable[[], datetime]] = None,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
) -> dict:
    """Execute the submission pipeline stage for all eligible jobs.

    Parameters:
        ctx: Current run context (used for structured logging).
        session_factory: ``async_sessionmaker`` — matches the discovery
            and tailoring stages.
        rate_limiter: ``RateLimiter`` — this is the **first real
            consumer** of :meth:`RateLimiter.record_submission` in the
            live pipeline.
        killswitch_check: Optional async callable raising on kill.
        registry: Optional strategy registry for test injection.
            Defaults to :func:`app.submission.registry.default_registry`.
        clock: Optional callable returning ``datetime`` for quiet-hours
            testing. Defaults to :func:`datetime.now` with the
            ``Settings.timezone`` ``ZoneInfo``.
        sleep: Optional async callable for inter-submission delay
            injection. Defaults to :func:`asyncio.sleep`.

    Returns:
        ``{
            "submitted": int,
            "submission_failed": int,
            "needs_info": int,
            "held_out": int,
            "paused": bool,
            "rate_limited": bool,
            "quiet_hours_skipped": bool,
            "submission_skipped": int,
        }``
    """
    # Lazy imports to match the tailoring-stage reload-safety pattern
    # (integration tests reload ``app.config`` and re-bind
    # ``app.db.base`` between runs; a top-level import here locks a
    # stale ``get_settings`` reference into the scheduler's static
    # import graph).
    from app.scheduler.rate_limit import RateLimitExceeded
    from app.settings.service import get_profile_row, get_settings_row
    from app.submission.builder import (
        build_attachment_filename,
        build_subject,
        extract_cover_letter_plaintext,
        extract_docx_plaintext,
        resolve_recipient_email,
    )
    from app.submission.creds import SmtpCredsMissing, load_smtp_creds
    from app.submission.holdout import should_auto_submit
    from app.submission.notifications import (
        send_failure_notification,
        send_success_notification,
    )
    from app.submission.registry import (
        SubmissionContext,
        default_registry,
        select_strategy,
    )
    from app.submission.service import (
        IdempotentDuplicate,
        flip_job_status,
        insert_pending,
        list_approved_jobs,
        list_tailored_jobs,
        mark_failed,
        mark_sent,
    )
    from app.submission.suppression import clear_suppressions_for_stage

    _sleep = sleep if sleep is not None else asyncio.sleep
    _registry = registry if registry is not None else default_registry()

    counts = _empty_counts()

    # -- 1. Pause check ------------------------------------------------------
    async with session_factory() as session:
        settings = await get_settings_row(session)
    if settings.submissions_paused:
        log.info("submission_paused", run_id=ctx.run_id)
        return _empty_counts(paused=True)

    # -- 2. Auto-mode holdout branch: tailored -> approved -------------------
    if settings.auto_mode:
        async with session_factory() as session:
            tailored_pairs = await list_tailored_jobs(session)

        for job, record in tailored_pairs:
            if killswitch_check is not None:
                await killswitch_check()
            if record.tailored_resume_path is None:
                log.info(
                    "holdout_no_artifact",
                    run_id=ctx.run_id,
                    job_id=job.id,
                )
                continue
            try:
                tailored_text = extract_docx_plaintext(
                    record.tailored_resume_path
                )
            except Exception as exc:
                log.warning(
                    "holdout_extract_failed",
                    run_id=ctx.run_id,
                    job_id=job.id,
                    error=str(exc),
                )
                continue

            decision = should_auto_submit(
                record=record,
                job=job,
                tailored_text=tailored_text,
                user_threshold=settings.match_threshold,
                holdout_margin_pct=settings.auto_holdout_margin_pct,
            )
            if decision.auto_eligible:
                async with session_factory() as session:
                    await flip_job_status(
                        session,
                        job.id,
                        "approved",
                        reason="auto_holdout_pass",
                    )
                log.info(
                    "holdout_auto_approved",
                    run_id=ctx.run_id,
                    job_id=job.id,
                    coverage_pct=decision.coverage_pct,
                    required_pct=decision.required_pct,
                )
            else:
                counts["held_out"] += 1
                log.info(
                    "holdout_held_out",
                    run_id=ctx.run_id,
                    job_id=job.id,
                    reason=decision.reason,
                    coverage_pct=decision.coverage_pct,
                    required_pct=decision.required_pct,
                )

    # -- 3. Drain the approved queue -----------------------------------------
    async with session_factory() as session:
        approved_pairs = await list_approved_jobs(session)

    if not approved_pairs:
        log.info(
            "submission_no_jobs",
            run_id=ctx.run_id,
            held_out=counts["held_out"],
        )
        return counts

    # Quiet hours gate (Phase 5 first enforcement site — research
    # surprise finding #1). Sampled once before the drain loop; if we
    # are inside the window we leave every approved job in place and
    # let the next run pick them up. We do NOT re-sample per job.
    try:
        tz = ZoneInfo(settings.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    now = clock() if clock is not None else datetime.now(tz)
    now_hour = now.hour if now.tzinfo is not None else datetime.now(tz).hour
    if _in_quiet_hours(
        now_hour, settings.quiet_hours_start, settings.quiet_hours_end
    ):
        log.info(
            "submission_quiet_hours_skip",
            run_id=ctx.run_id,
            now_hour=now_hour,
            quiet_start=settings.quiet_hours_start,
            quiet_end=settings.quiet_hours_end,
            pending=len(approved_pairs),
        )
        counts["quiet_hours_skipped"] = True
        return counts

    # Load SMTP creds + Profile once per drain loop (not per job).
    async with session_factory() as session:
        try:
            smtp_creds = await load_smtp_creds(session)
        except SmtpCredsMissing as exc:
            log.error(
                "submission_creds_missing",
                run_id=ctx.run_id,
                missing=exc.name,
            )
            # Fire a pipeline-level failure notification so the operator
            # hears about broken credentials even though no per-job
            # failure rows are written. Then return — nothing can be
            # sent until creds are fixed.
            async with session_factory() as notif_session:
                await send_failure_notification(
                    notif_session,
                    stage="submission",
                    error_class="SmtpCredsMissing",
                    error_message=f"missing credential: {exc.name}",
                )
            counts["submission_skipped"] = len(approved_pairs)
            return counts
        profile = await get_profile_row(session)

    full_name = (profile.full_name or "").strip()

    # -- Drain loop ---------------------------------------------------------
    for job, record in approved_pairs:
        if killswitch_check is not None:
            await killswitch_check()

        # 3c. Rate-limit precheck.
        async with session_factory() as session:
            try:
                await rate_limiter.await_precheck(session)
            except RateLimitExceeded as exc:
                counts["rate_limited"] = True
                log.warning(
                    "submission_daily_cap_halt",
                    run_id=ctx.run_id,
                    detail=str(exc),
                    pending=len(approved_pairs)
                    - counts["submitted"]
                    - counts["submission_failed"]
                    - counts["needs_info"],
                )
                break

        description = job.description or ""

        # 3d. Recipient resolution.
        recipient_email = resolve_recipient_email(description)
        if recipient_email is None:
            counts["needs_info"] += 1
            async with session_factory() as session:
                await flip_job_status(
                    session,
                    job.id,
                    "needs_info",
                    reason="no_recipient_email",
                )
                await send_failure_notification(
                    session,
                    stage="submission",
                    error_class="NoRecipientEmail",
                    error_message=(
                        f"no recipient email found in description for "
                        f"job {job.id} ({job.company})"
                    ),
                    job=job,
                )
            log.info(
                "submission_no_recipient",
                run_id=ctx.run_id,
                job_id=job.id,
            )
            continue

        # 3e. Strategy selection.
        strategy = select_strategy(job, description, _registry)
        if strategy is None:
            counts["needs_info"] += 1
            async with session_factory() as session:
                await flip_job_status(
                    session,
                    job.id,
                    "needs_info",
                    reason="no_applicable_strategy",
                )
                await send_failure_notification(
                    session,
                    stage="submission",
                    error_class="NoApplicableStrategy",
                    error_message=(
                        f"no submitter strategy applies to job {job.id}"
                    ),
                    job=job,
                )
            log.info(
                "submission_no_strategy",
                run_id=ctx.run_id,
                job_id=job.id,
            )
            continue

        # 3f. Build context.
        subject = build_subject(role=job.title, company=job.company)
        try:
            body_text = (
                extract_cover_letter_plaintext(record.cover_letter_path)
                if record.cover_letter_path
                else ""
            )
        except Exception as exc:
            log.warning(
                "submission_cover_letter_read_failed",
                run_id=ctx.run_id,
                job_id=job.id,
                error=str(exc),
            )
            body_text = ""
        attachment_filename = build_attachment_filename(
            full_name=full_name, company=job.company
        )

        ctx_subm = SubmissionContext(
            job=job,
            tailored_resume_path=Path(record.tailored_resume_path),
            cover_letter_path=(
                Path(record.cover_letter_path)
                if record.cover_letter_path
                else Path("")
            ),
            recipient_email=recipient_email,
            subject=subject,
            body_text=body_text,
            attachment_filename=attachment_filename,
            smtp_creds=smtp_creds,
        )

        # 3g. Insert pending submission row.
        async with session_factory() as session:
            submission = await insert_pending(
                session,
                job_id=job.id,
                tailoring_record_id=record.id,
                smtp_from=smtp_creds.username,
                smtp_to=recipient_email,
                subject=subject,
                attachment_filename=attachment_filename,
                submitter=strategy.name,
            )
            submission_id = submission.id

        # 3h. Attempt the send.
        outcome = await strategy.submit(ctx_subm)

        if outcome.success:
            async with session_factory() as session:
                try:
                    await mark_sent(session, submission_id)
                except IdempotentDuplicate:
                    log.warning(
                        "submission_idempotent_noop",
                        run_id=ctx.run_id,
                        job_id=job.id,
                        submission_id=submission_id,
                    )
                    # Do not double-notify; still count as submitted.
                    counts["submitted"] += 1
                    continue
                await flip_job_status(
                    session,
                    job.id,
                    "submitted",
                    reason="email_strategy_sent",
                )
                await rate_limiter.record_submission(session)
                await send_success_notification(
                    session,
                    job=job,
                    record=record,
                    submission_id=submission_id,
                    recipient_email=recipient_email,
                )
                await clear_suppressions_for_stage(session, "submission")
            counts["submitted"] += 1
            log.info(
                "submission_sent",
                run_id=ctx.run_id,
                job_id=job.id,
                submission_id=submission_id,
                to=recipient_email,
            )
        else:
            async with session_factory() as session:
                await mark_failed(
                    session,
                    submission_id,
                    error_class=outcome.error_class or "UnknownError",
                    error_message=outcome.error_message or "",
                )
                await flip_job_status(
                    session,
                    job.id,
                    "failed",
                    reason="submission_error",
                )
                # Suppression logic is internal to
                # send_failure_notification via should_notify — do NOT
                # call build_signature here.
                await send_failure_notification(
                    session,
                    stage="submission",
                    error_class=outcome.error_class or "UnknownError",
                    error_message=outcome.error_message or "",
                    job=job,
                )
            counts["submission_failed"] += 1
            log.warning(
                "submission_failed",
                run_id=ctx.run_id,
                job_id=job.id,
                submission_id=submission_id,
                error_class=outcome.error_class,
            )

        # 3i. SAFE-02 randomised inter-submission delay.
        delay = rate_limiter.random_action_delay()
        await _sleep(delay)

    log.info(
        "submission_complete",
        run_id=ctx.run_id,
        **{k: v for k, v in counts.items()},
    )
    return counts


__all__ = ["run_submission"]
