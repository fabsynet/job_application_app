"""SchedulerService: compose run-lock + kill-switch + rate limiter + Run rows.

RESEARCH.md Pattern 2. This is the single entry point into the pipeline from
APScheduler (hourly heartbeat) and from the /runs/run-now route (manual).

The class owns three pieces of safety state:

* ``_lock`` — an ``asyncio.Lock`` that serialises pipeline execution on top
  of APScheduler's ``max_instances=1``. Two layers because the lock also
  protects manual runs, which APScheduler does not know about.
* ``_current_task`` — the asyncio.Task wrapping the pipeline body. Held so
  :meth:`cancel_current_run` can call ``task.cancel()`` — this is the hook
  the kill-switch uses for mid-run hard-stop.
* ``_killswitch``, ``_rate_limiter`` — injected collaborators, both async-safe.

Phase 3 replaced the Phase 1 stub with :meth:`_execute_pipeline` which calls
``run_discovery`` for ATS fetching, dedup, scoring, and persistence.  The
*wrapper* semantics (lock, kill-switch gate, rate-limit gate, RunContext
snapshot, finalise on success/error/cancel) stay identical across phases.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.discovery.pipeline import run_discovery
from app.runs.context import RunContext
from app.runs.service import create_run, finalize_run, mark_run_killed
from app.scheduler.killswitch import KillSwitch
from app.scheduler.rate_limit import RateLimiter, RateLimitExceeded
from app.settings.service import get_settings_row

log = structlog.get_logger(__name__)
_stdlog = logging.getLogger(__name__)


class SchedulerService:
    """Composes APScheduler + kill-switch + rate limiter + Run CRUD."""

    HEARTBEAT_JOB_ID = "hourly_heartbeat"

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        killswitch: KillSwitch,
        rate_limiter: RateLimiter,
        session_factory: async_sessionmaker,
        tz: str,
    ) -> None:
        self._scheduler = scheduler
        self._killswitch = killswitch
        self._rate_limiter = rate_limiter
        self._session_factory = session_factory
        self._tz = tz
        self._lock = asyncio.Lock()
        self._current_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Read-only accessors (dashboard + /health)
    # ------------------------------------------------------------------

    @property
    def killswitch(self) -> KillSwitch:
        return self._killswitch

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    def is_running(self) -> bool:
        """Return True if the APScheduler event loop is running."""
        try:
            return bool(self._scheduler.running)
        except Exception:
            return False

    def next_run_iso(self) -> Optional[str]:
        """Return the ISO-8601 timestamp of the next hourly heartbeat, or None."""
        try:
            job = self._scheduler.get_job(self.HEARTBEAT_JOB_ID)
            if job and job.next_run_time:
                return job.next_run_time.isoformat()
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Scheduler control surface (called by KillSwitch + lifespan)
    # ------------------------------------------------------------------

    def pause_scheduler(self) -> None:
        """Pause the hourly heartbeat job. Idempotent under missing job."""
        try:
            self._scheduler.pause_job(self.HEARTBEAT_JOB_ID)
        except Exception as e:  # noqa: BLE001
            _stdlog.warning("pause_job_failed: %s", e)

    def resume_scheduler(self) -> None:
        """Resume the hourly heartbeat job. Idempotent under missing job."""
        try:
            self._scheduler.resume_job(self.HEARTBEAT_JOB_ID)
        except Exception as e:  # noqa: BLE001
            _stdlog.warning("resume_job_failed: %s", e)

    def cancel_current_run(self) -> bool:
        """Cancel the in-flight pipeline task if one exists.

        Returns True if a task was cancelled, False if nothing was running.
        Called by :meth:`KillSwitch.engage`.
        """
        task = self._current_task
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    # ------------------------------------------------------------------
    # Pipeline entry point
    # ------------------------------------------------------------------

    async def run_pipeline(self, *, triggered_by: str) -> None:
        """Execute one pipeline invocation with full safety envelope.

        Gates (in order):
          1. Kill-switch — if engaged, log and return (no Run row).
          2. Rate-limit precheck — if today's cap met, write a visible
             ``status='skipped'`` Run row with ``failure_reason='rate_limit'``
             and return.
          3. Create Run row with dry_run snapshot from Settings.
          4. Construct frozen RunContext.
          5. Execute _execute_pipeline inside a cancellable asyncio.Task.
          6. On CancelledError → finalise as failed/killed.
             On Exception → finalise as failed/error.
             On success → finalise as succeeded.
        """
        if self._killswitch.is_engaged():
            log.info("run_skipped_killswitch", triggered_by=triggered_by)
            return

        async with self._lock:
            # Gate + create in a single session; then release the session
            # before handing off to the cancellable task to keep session
            # lifetime tight.
            async with self._session_factory() as session:
                try:
                    await self._rate_limiter.await_precheck(session)
                except RateLimitExceeded as e:
                    settings_row = await get_settings_row(session)
                    run = await create_run(
                        session,
                        dry_run=settings_row.dry_run,
                        triggered_by=triggered_by,
                    )
                    await finalize_run(
                        session,
                        run.id,
                        status="skipped",
                        failure_reason="rate_limit",
                    )
                    log.info(
                        "run_skipped_rate_limit",
                        detail=str(e),
                        run_id=run.id,
                    )
                    return

                settings_row = await get_settings_row(session)
                run = await create_run(
                    session,
                    dry_run=settings_row.dry_run,
                    triggered_by=triggered_by,
                )
                ctx = RunContext(
                    run_id=run.id,
                    started_at=datetime.now(timezone.utc),
                    dry_run=settings_row.dry_run,
                    triggered_by=triggered_by,
                    tz=self._tz,
                )

            task = asyncio.create_task(self._execute_pipeline(ctx))
            self._current_task = task
            try:
                await task
            except asyncio.CancelledError:
                async with self._session_factory() as session:
                    await mark_run_killed(session, ctx.run_id)
                log.info("run_killed", run_id=ctx.run_id)
                # Swallow the CancelledError at the pipeline boundary — the
                # wrapper has completed its cleanup. Propagating would abort
                # the APScheduler job worker and leave the scheduler itself
                # in a surprising state.
                return
            except Exception:
                async with self._session_factory() as session:
                    await finalize_run(
                        session,
                        ctx.run_id,
                        status="failed",
                        failure_reason="error",
                    )
                log.exception("run_errored", run_id=ctx.run_id)
                raise
            else:
                pipeline_counts = getattr(self, "_last_counts", None)
                self._last_counts = None
                async with self._session_factory() as session:
                    run = await finalize_run(
                        session,
                        ctx.run_id,
                        status="succeeded",
                        counts=pipeline_counts,
                    )
                log.info(
                    "run_succeeded",
                    run_id=ctx.run_id,
                    counts=run.counts if run else {},
                    dry_run=ctx.dry_run,
                    triggered_by=ctx.triggered_by,
                )
            finally:
                self._current_task = None

    async def _execute_pipeline(self, ctx: RunContext) -> None:
        """Execute the discovery pipeline with kill-switch checkpoints.

        Replaces the Phase 1 stub. Calls ``run_discovery`` which fetches
        from all enabled ATS sources, deduplicates, scores, and persists
        jobs. The kill-switch is checked before and after the discovery
        stage to honour mid-run hard-stop requests.

        The wrapper ``run_pipeline`` handles final status (succeeded/failed)
        and calls ``finalize_run`` -- this method only stores stage counts
        on the Run row so the wrapper can read them back.
        """
        await self._killswitch.raise_if_engaged()

        # Run discovery stage
        discovery_counts = await run_discovery(ctx, self._session_factory)

        await self._killswitch.raise_if_engaged()

        # Store discovery counts on the Run row.  The wrapper's else-branch
        # will call finalize_run(status="succeeded") which merges counts.
        self._last_counts = discovery_counts


__all__ = ["SchedulerService"]
