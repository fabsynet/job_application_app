"""Tailoring pipeline stage (TAIL-01 + TAIL-08 + TAIL-09).

``run_tailoring`` is the second pipeline stage in
``SchedulerService._execute_pipeline``. It runs after ``run_discovery``
has produced a batch of ``status="matched"`` jobs and processes each
one through the full engine: budget check → LLM tailor → validate →
write DOCX artifacts → save record → debit budget.

Control flow per job:

1. Optional kill-switch check (callable injected by scheduler).
2. Budget check — if cap is exhausted, halt the whole stage, leaving
   remaining jobs in ``matched`` state so they retry next run.
3. Compute next version number, build artifact paths.
4. Call ``tailor_resume`` with the ``quality`` profile inputs.
5. On success: write DOCX artifacts, save ``TailoringRecord`` +
   ``CostLedger`` rows, debit budget, flip job status to ``tailored``.
6. On validation rejection: save record with ``status="rejected"``,
   still debit (tokens were consumed), flip job to ``failed``.
7. On engine exception: save bare record with ``status="failed"``,
   flip job to ``failed`` — no debit (no result to bill).

Every branch commits the session inside its own ``session_factory()``
block so a crash in one job cannot roll back another job's record.

The stage returns a counts dict merged into ``self._last_counts`` on
the ``SchedulerService`` so the run summary shows both discovery and
tailoring numbers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import structlog

from app.runs.context import RunContext
from app.tailoring.engine import TailoringResult

# NOTE: The rest of the intra-app imports (``app.resume.service``,
# ``app.settings.service``, ``app.tailoring.*``) are pulled lazily
# inside :func:`run_tailoring`. Integration tests reload ``app.config``
# and ``app.db.base`` between runs; eagerly importing ``app.resume.service``
# here would lock a stale ``get_settings`` reference into ``sys.modules``
# via ``app.scheduler.service``'s transitive import, breaking the reload
# semantics of the ``live_app`` pytest fixture. Deferring the imports
# keeps the scheduler import graph minimal at module load time.

log = structlog.get_logger(__name__)


# Shape of the optional kill-switch hook passed in from the scheduler.
# ``SchedulerService`` passes ``self._killswitch.raise_if_engaged``;
# tests can pass ``None`` to skip the check.
KillSwitchCheck = Callable[[], Awaitable[None]]


def _empty_counts(**overrides: Any) -> dict:
    base = {
        "tailored": 0,
        "failed": 0,
        "budget_halted": False,
        "skipped_no_resume": False,
        "queued_count": 0,
    }
    base.update(overrides)
    return base


async def run_tailoring(
    ctx: RunContext,
    session_factory: Any,
    killswitch_check: Optional[KillSwitchCheck] = None,
) -> dict:
    """Execute the tailoring pipeline stage for all matched jobs.

    Parameters:
        ctx: Current run context (used for structured logging only).
        session_factory: ``async_sessionmaker`` — same object the
            discovery stage uses.
        killswitch_check: Optional async callable raising on kill.
            ``SchedulerService`` wires ``self._killswitch.raise_if_engaged``.
            Left ``None`` in tests.

    Returns:
        ``{
            "tailored": int,           # successful tailorings
            "failed":   int,           # rejected / errored attempts
            "budget_halted": bool,     # True if cap hit mid-run
            "skipped_no_resume": bool, # True if no base resume uploaded
            "queued_count": int,       # total jobs seen this run
        }``
    """
    # Lazy imports — see module docstring for rationale (reload safety).
    from app.config import get_settings
    from app.discovery.models import Job
    from app.resume.service import extract_resume_text
    from app.settings.service import get_settings_row
    from app.tailoring.budget import BudgetGuard
    from app.tailoring.docx_writer import (
        build_cover_letter_docx,
        build_tailored_docx,
    )
    from app.tailoring.engine import tailor_resume
    from app.tailoring.prompts import TAILORING_SYSTEM_PROMPT
    from app.tailoring.provider import get_provider
    from app.tailoring.service import (
        cover_letter_artifact_path,
        get_next_version,
        get_queued_jobs,
        resume_artifact_path,
        save_cost_entries,
        save_tailoring_record,
    )

    # -- 1. Load base resume --------------------------------------------------
    # Resolve the resume path via ``app.config.get_settings`` directly
    # rather than through ``app.resume.service.get_resume_path`` so we
    # always hit the *current* ``get_settings`` function reference.
    # Importing ``app.resume.service`` lazily would snapshot the
    # ``get_settings`` binding against whichever ``app.config`` was in
    # ``sys.modules`` at first-import time, which the integration-test
    # ``live_app`` fixture reloads between runs — causing stale DATA_DIR
    # resolution if another test populated that snapshot's LRU cache.
    # Wrapped in try/except to stay robust against transient config
    # errors (late APScheduler firings after monkeypatch teardown).
    try:
        base_resume_path: Optional[Path] = (
            Path(get_settings().data_dir) / "resumes" / "base_resume.docx"
        )
        if not base_resume_path.exists():
            base_resume_path = None
    except Exception as exc:
        log.warning(
            "tailoring_skipped_config_error",
            run_id=ctx.run_id,
            error=str(exc),
        )
        return _empty_counts(skipped_no_resume=True)

    if base_resume_path is None:
        log.info(
            "tailoring_skipped_no_resume",
            run_id=ctx.run_id,
            msg="no base resume uploaded; tailoring stage is a no-op",
        )
        return _empty_counts(skipped_no_resume=True)

    resume_data = extract_resume_text(base_resume_path)
    resume_sections = resume_data["sections"]
    base_resume_text = resume_data["full_text"]

    # -- 2. Load Settings (intensity) and queued jobs -------------------------
    async with session_factory() as session:
        settings_row = await get_settings_row(session)
        intensity = settings_row.tailoring_intensity or "balanced"
        jobs = await get_queued_jobs(session)

    if not jobs:
        log.info(
            "tailoring_no_jobs",
            run_id=ctx.run_id,
            msg="no matched jobs awaiting tailoring",
        )
        return _empty_counts()

    log.info(
        "tailoring_start",
        run_id=ctx.run_id,
        queued_count=len(jobs),
        intensity=intensity,
    )

    # -- 3. Resolve provider + budget guard ----------------------------------
    try:
        async with session_factory() as session:
            provider = await get_provider(session)
    except Exception as exc:
        log.warning(
            "tailoring_provider_unavailable",
            run_id=ctx.run_id,
            error=str(exc),
        )
        return _empty_counts(queued_count=len(jobs))

    budget = BudgetGuard()

    tailored_count = 0
    failed_count = 0
    budget_halted = False

    # -- 4. Per-job loop ------------------------------------------------------
    for job in jobs:
        # 4a. Kill-switch check between jobs
        if killswitch_check is not None:
            await killswitch_check()

        # 4b. Budget check (aborts stage when cap hit)
        async with session_factory() as session:
            can_proceed, spent, cap, is_warning = await budget.check_budget(
                session
            )

        if not can_proceed:
            budget_halted = True
            log.warning(
                "tailoring_budget_halt",
                run_id=ctx.run_id,
                spent=spent,
                cap=cap,
                remaining_jobs=len(jobs) - (tailored_count + failed_count),
            )
            break

        if is_warning:
            log.warning(
                "tailoring_budget_warning",
                run_id=ctx.run_id,
                spent=spent,
                cap=cap,
                threshold_pct=80,
            )

        # 4c. Assign next artifact version
        async with session_factory() as session:
            version = await get_next_version(session, job.id)

        resume_path: Path = resume_artifact_path(job.id, version)
        cl_path: Path = cover_letter_artifact_path(job.id, version)

        job_desc = job.description or ""
        company = job.company or ""
        title = job.title or ""

        # 4d. Run the tailoring engine
        result: Optional[TailoringResult]
        try:
            result = await tailor_resume(
                provider=provider,
                resume_sections=resume_sections,
                job_description=job_desc,
                intensity=intensity,
                company=company,
                title=title,
            )
        except Exception as exc:
            log.exception(
                "tailoring_engine_error",
                run_id=ctx.run_id,
                job_id=job.id,
                error=str(exc),
            )
            async with session_factory() as session:
                await save_tailoring_record(
                    session=session,
                    job_id=job.id,
                    version=version,
                    intensity=intensity,
                    base_resume_path=str(base_resume_path),
                    tailored_resume_path=None,
                    cover_letter_path=None,
                    result=None,
                    status="failed",
                    resume_text=base_resume_text,
                    job_description=job_desc,
                    system_prompt=TAILORING_SYSTEM_PROMPT,
                )
                job_row = await session.get(Job, job.id)
                if job_row is not None:
                    job_row.status = "failed"
                await session.commit()
            failed_count += 1
            continue

        # 4e. Branch on result.success
        if result.success and result.tailored_sections is not None:
            # Write DOCX artifacts
            try:
                build_tailored_docx(
                    base_resume_path=base_resume_path,
                    tailored_sections=result.tailored_sections,
                    output_path=resume_path,
                )
            except Exception as exc:
                log.exception(
                    "tailored_docx_write_failed",
                    run_id=ctx.run_id,
                    job_id=job.id,
                    error=str(exc),
                )
                # Treat as failure — without the artifact the record
                # has no review value.
                async with session_factory() as session:
                    record = await save_tailoring_record(
                        session=session,
                        job_id=job.id,
                        version=version,
                        intensity=intensity,
                        base_resume_path=str(base_resume_path),
                        tailored_resume_path=None,
                        cover_letter_path=None,
                        result=result,
                        status="failed",
                        resume_text=base_resume_text,
                        job_description=job_desc,
                        system_prompt=TAILORING_SYSTEM_PROMPT,
                    )
                    await save_cost_entries(
                        session, record.id, result.llm_calls
                    )
                    job_row = await session.get(Job, job.id)
                    if job_row is not None:
                        job_row.status = "failed"
                    await session.commit()
                failed_count += 1
                continue

            cl_output: Optional[str] = None
            if result.cover_letter_paragraphs:
                try:
                    build_cover_letter_docx(
                        paragraphs=result.cover_letter_paragraphs,
                        output_path=cl_path,
                        base_resume_path=base_resume_path,
                    )
                    cl_output = str(cl_path)
                except Exception as exc:
                    # Non-fatal: resume is still valid, log and continue.
                    log.warning(
                        "cover_letter_write_failed",
                        run_id=ctx.run_id,
                        job_id=job.id,
                        error=str(exc),
                    )

            # Persist record + cost entries + debit + flip status
            async with session_factory() as session:
                record = await save_tailoring_record(
                    session=session,
                    job_id=job.id,
                    version=version,
                    intensity=intensity,
                    base_resume_path=str(base_resume_path),
                    tailored_resume_path=str(resume_path),
                    cover_letter_path=cl_output,
                    result=result,
                    status="completed",
                    resume_text=base_resume_text,
                    job_description=job_desc,
                    system_prompt=TAILORING_SYSTEM_PROMPT,
                )
                await save_cost_entries(session, record.id, result.llm_calls)

                total_cost = BudgetGuard.estimate_cost(
                    input_tokens=result.total_input_tokens,
                    output_tokens=result.total_output_tokens,
                    cache_read_tokens=result.total_cache_read_tokens,
                    cache_write_tokens=result.total_cache_write_tokens,
                )
                await budget.debit(
                    session=session,
                    cost_dollars=total_cost,
                    record_id=record.id,
                    call_type="tailor",
                    model="claude-sonnet-4-5",
                    input_tokens=result.total_input_tokens,
                    output_tokens=result.total_output_tokens,
                    cache_read_tokens=result.total_cache_read_tokens,
                    cache_write_tokens=result.total_cache_write_tokens,
                )

                job_row = await session.get(Job, job.id)
                if job_row is not None:
                    job_row.status = "tailored"
                await session.commit()

            tailored_count += 1
            log.info(
                "tailoring_job_completed",
                run_id=ctx.run_id,
                job_id=job.id,
                version=version,
                cost=round(total_cost, 6),
                retries=result.retry_count,
            )
        else:
            # Validation failed after all retries (or engine returned a
            # soft failure). Tokens were consumed so we still debit and
            # write a ``rejected`` record for the review queue.
            async with session_factory() as session:
                record = await save_tailoring_record(
                    session=session,
                    job_id=job.id,
                    version=version,
                    intensity=intensity,
                    base_resume_path=str(base_resume_path),
                    tailored_resume_path=None,
                    cover_letter_path=None,
                    result=result,
                    status="rejected",
                    resume_text=base_resume_text,
                    job_description=job_desc,
                    system_prompt=TAILORING_SYSTEM_PROMPT,
                )
                await save_cost_entries(session, record.id, result.llm_calls)

                total_cost = BudgetGuard.estimate_cost(
                    input_tokens=result.total_input_tokens,
                    output_tokens=result.total_output_tokens,
                    cache_read_tokens=result.total_cache_read_tokens,
                    cache_write_tokens=result.total_cache_write_tokens,
                )
                if total_cost > 0:
                    await budget.debit(
                        session=session,
                        cost_dollars=total_cost,
                        record_id=record.id,
                        call_type="tailor",
                        model="claude-sonnet-4-5",
                        input_tokens=result.total_input_tokens,
                        output_tokens=result.total_output_tokens,
                        cache_read_tokens=result.total_cache_read_tokens,
                        cache_write_tokens=result.total_cache_write_tokens,
                    )

                job_row = await session.get(Job, job.id)
                if job_row is not None:
                    job_row.status = "failed"
                await session.commit()

            failed_count += 1
            log.info(
                "tailoring_job_rejected",
                run_id=ctx.run_id,
                job_id=job.id,
                version=version,
                retries=result.retry_count if result else 0,
                error=result.error if result else None,
            )

    counts = {
        "tailored": tailored_count,
        "failed": failed_count,
        "budget_halted": budget_halted,
        "skipped_no_resume": False,
        "queued_count": len(jobs),
    }

    log.info(
        "tailoring_complete",
        run_id=ctx.run_id,
        **counts,
    )
    return counts


__all__ = ["run_tailoring"]
