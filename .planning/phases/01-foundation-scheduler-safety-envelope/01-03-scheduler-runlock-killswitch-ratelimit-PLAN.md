---
phase: 01-foundation-scheduler-safety-envelope
plan: 03
type: execute
wave: 2
depends_on: ["01-01", "01-02"]
files_modified:
  - app/main.py
  - app/scheduler/__init__.py
  - app/scheduler/service.py
  - app/scheduler/heartbeat.py
  - app/scheduler/killswitch.py
  - app/scheduler/rate_limit.py
  - app/runs/__init__.py
  - app/runs/context.py
  - app/runs/service.py
  - app/settings/__init__.py
  - app/settings/service.py
  - app/web/__init__.py
  - app/web/routers/__init__.py
  - app/web/routers/health.py
  - tests/unit/test_rate_limiter.py
  - tests/unit/test_killswitch.py
  - tests/unit/test_settings_service.py
  - tests/integration/__init__.py
  - tests/integration/test_scheduler_lifecycle.py
  - tests/integration/test_dry_run_propagation.py
  - tests/integration/test_kill_switch_cancels_run.py
  - tests/integration/test_rate_limit_skips_run.py
autonomous: true

must_haves:
  truths:
    - "An hourly CronTrigger job is registered on an AsyncIOScheduler that lives inside the FastAPI lifespan context"
    - "Only one run can execute at a time (asyncio.Lock + max_instances=1 + DB sentinel row with status='running')"
    - "Engaging the kill-switch cancels the in-flight asyncio task, marks the Run row failed with reason='killed', pauses the APScheduler job, and persists to settings.kill_switch"
    - "Toggling dry_run in the Settings row is picked up at run-start and stamped on every Run row; mid-run toggles do NOT retroactively affect the in-flight run"
    - "Daily cap of 20 submissions blocks run start (raises RateLimitExceeded → Run(status='skipped', failure_reason='rate_limit')); counter resets at local-TZ midnight"
    - "Orphaned Run(status='running') rows from a crashed container are marked failed at startup"
  artifacts:
    - path: "app/scheduler/service.py"
      provides: "SchedulerService: start/stop/run_pipeline/cancel_current_run/is_running/next_run_iso/pause/resume"
      exports: ["SchedulerService"]
    - path: "app/scheduler/killswitch.py"
      provides: "KillSwitch using asyncio.Event, engages/releases, hydrates from settings at boot"
      exports: ["KillSwitch"]
    - path: "app/scheduler/rate_limit.py"
      provides: "RateLimiter: await_precheck, random_action_delay, record_submission, midnight_reset job"
      exports: ["RateLimiter", "RateLimitExceeded"]
    - path: "app/scheduler/heartbeat.py"
      provides: "heartbeat_job coroutine registered with APScheduler CronTrigger(minute=0)"
      exports: ["heartbeat_job"]
    - path: "app/runs/context.py"
      provides: "Frozen RunContext dataclass — the contract Phases 2-6 consume"
      exports: ["RunContext"]
    - path: "app/runs/service.py"
      provides: "create_run, finalize_run, mark_run_killed, mark_orphans_failed, list_recent_runs"
      exports: ["create_run", "finalize_run", "mark_run_killed", "list_recent_runs"]
    - path: "app/settings/service.py"
      provides: "get_or_create_settings_row, get_setting, set_setting — atomic single-row service"
      exports: ["get_settings_row", "set_setting", "get_setting"]
    - path: "app/main.py"
      provides: "FastAPI app factory with lifespan hosting scheduler + killswitch + rate_limiter + vault"
      exports: ["app", "lifespan"]
    - path: "app/web/routers/health.py"
      provides: "GET /health endpoint returning scheduler state, next_run_iso, kill_switch flag"
      exports: ["router"]
  key_links:
    - from: "app/main.py lifespan"
      to: "AsyncIOScheduler + SchedulerService"
      via: "create scheduler, start inside lifespan, shutdown on exit"
      pattern: "AsyncIOScheduler|lifespan"
    - from: "KillSwitch.engage"
      to: "SchedulerService.cancel_current_run"
      via: "sets asyncio.Event + pauses APScheduler job + cancels current task"
      pattern: "cancel_current_run"
    - from: "SchedulerService.run_pipeline"
      to: "RateLimiter.await_precheck"
      via: "precheck raises RateLimitExceeded before create_run"
      pattern: "await_precheck"
    - from: "RunContext.dry_run"
      to: "settings.dry_run"
      via: "snapshot at run-start in SchedulerService.run_pipeline"
      pattern: "RunContext\\("
    - from: "heartbeat_job"
      to: "SchedulerService.run_pipeline"
      via: "APScheduler CronTrigger(minute=0) invokes heartbeat_job → run_pipeline"
      pattern: "run_pipeline\\(triggered_by=\"scheduler\""
---

<objective>
Implement the scheduler safety envelope: singleton run-lock, kill-switch with task cancellation, dry-run plumbing via RunContext, rate-limit envelope (20/day + 30-120s jitter + local-midnight reset), and the FastAPI lifespan that wires it all together. This is where FOUND-03, FOUND-04, FOUND-05, FOUND-07, DISC-07, SAFE-01, and SAFE-02 all ship.

Purpose: After this plan, the app boots, the hourly heartbeat fires, the DB receives run rows, the kill-switch aborts in-flight work, dry-run is stamped on every row, and the rate limiter gates everything — all before any pipeline stage exists. Phases 2+ inherit throttling and safety for free because this plan enforces them at `run_pipeline` entry.

Output: `docker compose up` boots the container to a healthy state, `/health` responds, the scheduler registers an hourly cron tick, all 11 scheduler/safety requirements are functionally satisfied (though not yet UI-exposed — plan 01-04 adds the dashboard).
</objective>

<execution_context>
@C:/Users/abuba/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/abuba/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-foundation-scheduler-safety-envelope/01-CONTEXT.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-RESEARCH.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-01-SUMMARY.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-02-SUMMARY.md
@app/config.py
@app/db/models.py
@app/db/base.py
@app/security/fernet.py
@app/security/log_scrubber.py
@app/logging_setup.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Settings service, RunContext, runs service, RateLimiter, KillSwitch</name>
  <files>
    app/settings/__init__.py,
    app/settings/service.py,
    app/runs/__init__.py,
    app/runs/context.py,
    app/runs/service.py,
    app/scheduler/__init__.py,
    app/scheduler/rate_limit.py,
    app/scheduler/killswitch.py,
    tests/unit/test_settings_service.py,
    tests/unit/test_rate_limiter.py,
    tests/unit/test_killswitch.py
  </files>
  <action>
Build the primitives first, then the service that composes them in Task 2. Every primitive is unit-testable without the scheduler or lifespan.

**app/settings/service.py** — single-row Settings accessor:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Settings

async def get_settings_row(session: AsyncSession) -> Settings:
    """Get-or-create the single Settings row (id=1)."""
    result = await session.execute(select(Settings).where(Settings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = Settings(id=1)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row

async def set_setting(session: AsyncSession, field: str, value) -> Settings:
    row = await get_settings_row(session)
    if not hasattr(row, field):
        raise AttributeError(f"Settings has no field {field!r}")
    setattr(row, field, value)
    from datetime import datetime
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return row

async def get_setting(session: AsyncSession, field: str):
    row = await get_settings_row(session)
    return getattr(row, field)
```

**app/runs/context.py** — frozen dataclass per RESEARCH.md Pattern 4:

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class RunContext:
    run_id: int
    started_at: datetime
    dry_run: bool
    triggered_by: str    # "scheduler" | "manual" | "wizard"
    tz: str
```

**app/runs/service.py** — CRUD for Run rows + orphan cleanup:

- `async def create_run(session, *, dry_run, triggered_by) -> Run`: inserts `Run(status='running', dry_run=dry_run, triggered_by=triggered_by, counts={"discovered":0,"matched":0,"tailored":0,"submitted":0,"failed":0})`, commits, refreshes, returns.
- `async def finalize_run(session, run_id, *, status, failure_reason=None, counts=None) -> None`: updates ended_at, duration_ms = (ended - started).total_seconds()*1000, status, failure_reason, optionally counts (merging).
- `async def mark_run_killed(session, run_id) -> None`: calls finalize_run with status="failed", failure_reason="killed".
- `async def mark_orphans_failed(session) -> int`: UPDATE runs SET status='failed', failure_reason='crashed', ended_at=CURRENT_TIMESTAMP WHERE status='running'. Returns rowcount for logging. Called once at lifespan startup.
- `async def list_recent_runs(session, *, limit=50, offset=0) -> list[Run]`: ORDER BY started_at DESC.

**app/scheduler/rate_limit.py** — per RESEARCH.md Pattern 5, with DB-backed counter:

```python
import random
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import RateLimitCounter

class RateLimitExceeded(Exception):
    pass

class RateLimiter:
    def __init__(self, daily_cap: int, delay_min: int, delay_max: int, tz: str):
        if delay_min <= 0 or delay_max <= delay_min or delay_max > 600:
            raise ValueError(f"invalid delay range: {delay_min}..{delay_max}")
        if daily_cap < 0:
            raise ValueError("daily_cap must be >= 0")
        self.daily_cap = daily_cap
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.tz = ZoneInfo(tz)

    def today_local(self) -> date:
        return datetime.now(self.tz).date()

    async def _get_or_create_counter(self, session: AsyncSession) -> RateLimitCounter:
        day_str = self.today_local().isoformat()
        row = (await session.execute(
            select(RateLimitCounter).where(RateLimitCounter.day == day_str)
        )).scalar_one_or_none()
        if row is None:
            row = RateLimitCounter(day=day_str, submitted_count=0)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def await_precheck(self, session: AsyncSession) -> None:
        row = await self._get_or_create_counter(session)
        if row.submitted_count >= self.daily_cap:
            raise RateLimitExceeded(
                f"daily cap {self.daily_cap} reached ({row.submitted_count} submitted)"
            )

    async def record_submission(self, session: AsyncSession) -> int:
        row = await self._get_or_create_counter(session)
        row.submitted_count += 1
        await session.commit()
        return row.submitted_count

    def random_action_delay(self) -> float:
        return random.uniform(self.delay_min, self.delay_max)

    async def midnight_reset(self, session: AsyncSession) -> None:
        """APScheduler invokes this at local midnight. Idempotent: if today's row
        already exists (from a prior call), it's a no-op."""
        await self._get_or_create_counter(session)
```

**app/scheduler/killswitch.py** — `asyncio.Event`-backed per RESEARCH.md Pattern 3:

```python
import asyncio

class KillSwitch:
    def __init__(self):
        self._event = asyncio.Event()

    def is_engaged(self) -> bool:
        return self._event.is_set()

    def _set(self) -> None:
        self._event.set()

    def _clear(self) -> None:
        self._event.clear()

    async def engage(self, scheduler_service, session) -> None:
        self._set()
        from app.settings.service import set_setting
        await set_setting(session, "kill_switch", True)
        scheduler_service.pause_scheduler()
        scheduler_service.cancel_current_run()

    async def release(self, scheduler_service, session) -> None:
        self._clear()
        from app.settings.service import set_setting
        await set_setting(session, "kill_switch", False)
        scheduler_service.resume_scheduler()

    async def raise_if_engaged(self) -> None:
        if self._event.is_set():
            raise asyncio.CancelledError("kill_switch_engaged")

    @classmethod
    async def hydrate_from_settings(cls, session) -> "KillSwitch":
        from app.settings.service import get_settings_row
        row = await get_settings_row(session)
        ks = cls()
        if row.kill_switch:
            ks._set()
        return ks
```

**Unit tests:**

*tests/unit/test_settings_service.py:*
- `test_get_or_create_is_idempotent` — calling twice returns same row with id=1.
- `test_set_setting_persists(dry_run=True)` then re-read → True.
- `test_set_setting_rejects_unknown_field` raises AttributeError.
- Use in-memory SQLite fixture `async_session` (add helper to `tests/conftest.py`: creates engine `sqlite+aiosqlite:///:memory:`, runs `SQLModel.metadata.create_all`, yields session).

*tests/unit/test_rate_limiter.py:*
- `test_below_cap_precheck_passes`: seed counter=5, cap=20 → no raise.
- `test_at_cap_raises`: seed counter=20, cap=20 → raises RateLimitExceeded.
- `test_record_submission_increments`: start 0, call record_submission twice → counter == 2.
- `test_random_action_delay_in_range`: call 100 times, assert all values in [30, 120].
- `test_invalid_delay_range_constructor`: delay_min=0 raises; delay_min=120 delay_max=30 raises; delay_max=700 raises.
- `test_today_local_uses_configured_tz`: freezegun to "2026-04-11T07:30:00Z". With tz="America/Los_Angeles", today should still be "2026-04-11" (midnight is -07:00). With tz="Asia/Tokyo", today should be "2026-04-11" too but +09:00 (after midnight). Use freezegun.
- `test_midnight_reset_is_idempotent`: call twice, no error, row exists with count=0.

*tests/unit/test_killswitch.py:*
- `test_engage_sets_event`: mock scheduler_service with `pause_scheduler` and `cancel_current_run` as MagicMock. Engage → `is_engaged()` is True, mocks called once each, settings row persists kill_switch=True.
- `test_release_clears_event`: engage then release → `is_engaged()` False, scheduler.resume_scheduler called.
- `test_raise_if_engaged_raises_cancelled_error`: engaged → `await raise_if_engaged()` raises asyncio.CancelledError with message "kill_switch_engaged".
- `test_hydrate_from_settings_preserves_state`: seed settings.kill_switch=True → new KillSwitch is engaged.
  </action>
  <verify>
`pytest tests/unit/test_settings_service.py tests/unit/test_rate_limiter.py tests/unit/test_killswitch.py -q` all pass.
`python -c "from app.scheduler.rate_limit import RateLimiter, RateLimitExceeded; from app.scheduler.killswitch import KillSwitch; from app.runs.context import RunContext; print('ok')"` prints ok.
`python -c "from app.runs.service import create_run, finalize_run, mark_run_killed, mark_orphans_failed, list_recent_runs; print('ok')"` prints ok.
  </verify>
  <done>
Settings service, RunContext, runs service, RateLimiter, KillSwitch all implemented and unit-tested. Rate limiter correctly enforces cap and TZ-aware midnight math via freezegun tests. KillSwitch drives scheduler mock and persists to settings. All tests green.
  </done>
</task>

<task type="auto">
  <name>Task 2: SchedulerService, heartbeat_job, FastAPI main.py lifespan, /health router</name>
  <files>
    app/scheduler/service.py,
    app/scheduler/heartbeat.py,
    app/main.py,
    app/web/__init__.py,
    app/web/routers/__init__.py,
    app/web/routers/health.py,
    tests/integration/__init__.py,
    tests/integration/test_scheduler_lifecycle.py
  </files>
  <action>
**app/scheduler/service.py** — compose everything per RESEARCH.md Pattern 2:

```python
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.scheduler.killswitch import KillSwitch
from app.scheduler.rate_limit import RateLimiter, RateLimitExceeded
from app.runs.context import RunContext
from app.runs.service import create_run, finalize_run, mark_run_killed
from app.settings.service import get_settings_row

log = logging.getLogger(__name__)

class SchedulerService:
    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        killswitch: KillSwitch,
        rate_limiter: RateLimiter,
        session_factory,
        tz: str,
    ):
        self._scheduler = scheduler
        self._killswitch = killswitch
        self._rate_limiter = rate_limiter
        self._session_factory = session_factory
        self._tz = tz
        self._lock = asyncio.Lock()
        self._current_task: Optional[asyncio.Task] = None

    @property
    def killswitch(self) -> KillSwitch:
        return self._killswitch

    def is_running(self) -> bool:
        return self._scheduler.running

    def next_run_iso(self) -> Optional[str]:
        try:
            job = self._scheduler.get_job("hourly_heartbeat")
            if job and job.next_run_time:
                return job.next_run_time.isoformat()
        except Exception:
            pass
        return None

    def pause_scheduler(self) -> None:
        try:
            self._scheduler.pause_job("hourly_heartbeat")
        except Exception as e:
            log.warning("pause_job_failed", exc_info=e)

    def resume_scheduler(self) -> None:
        try:
            self._scheduler.resume_job("hourly_heartbeat")
        except Exception as e:
            log.warning("resume_job_failed", exc_info=e)

    def cancel_current_run(self) -> bool:
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            return True
        return False

    async def run_pipeline(self, *, triggered_by: str) -> None:
        # Kill-switch gate
        if self._killswitch.is_engaged():
            log.info("run_skipped_killswitch")
            return

        async with self._lock:
            async with self._session_factory() as session:
                # Rate-limit gate
                try:
                    await self._rate_limiter.await_precheck(session)
                except RateLimitExceeded as e:
                    # Write a visible skipped Run row for the dashboard
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
                    log.info("run_skipped_rate_limit", detail=str(e))
                    return

                # Snapshot dry_run at run-start (never reread mid-run)
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

            # Execute the stub pipeline in a cancellable task
            task = asyncio.create_task(self._execute_stub(ctx))
            self._current_task = task
            try:
                await task
            except asyncio.CancelledError:
                async with self._session_factory() as session:
                    await mark_run_killed(session, ctx.run_id)
                log.info("run_killed", run_id=ctx.run_id)
                raise
            except Exception as e:
                async with self._session_factory() as session:
                    await finalize_run(
                        session, ctx.run_id, status="failed",
                        failure_reason="error",
                    )
                log.exception("run_errored", run_id=ctx.run_id)
                raise
            else:
                async with self._session_factory() as session:
                    await finalize_run(session, ctx.run_id, status="succeeded")
            finally:
                self._current_task = None

    async def _execute_stub(self, ctx: RunContext) -> None:
        """Phase 1 stub pipeline: sleeps briefly so tests can cancel it,
        yields to the event loop so kill-switch can interrupt, writes nothing.
        Phases 2+ replace this body with real stage calls."""
        await self._killswitch.raise_if_engaged()
        await asyncio.sleep(0.05)
        await self._killswitch.raise_if_engaged()
```

**app/scheduler/heartbeat.py:**

```python
import structlog

log = structlog.get_logger(__name__)
_scheduler_service = None

def set_scheduler_service(service):
    global _scheduler_service
    _scheduler_service = service

def get_scheduler_service():
    return _scheduler_service

async def heartbeat_job():
    svc = get_scheduler_service()
    if svc is None:
        log.error("heartbeat_no_scheduler_service")
        return
    try:
        await svc.run_pipeline(triggered_by="scheduler")
    except Exception as e:
        log.exception("heartbeat_failed", error=str(e))
```

Why a module-level setter vs passing app.state: APScheduler's CronTrigger invokes the job coroutine as a standalone function; it does not have access to FastAPI's request scope. The setter is called during lifespan startup so the function finds its dependency.

**app/web/routers/health.py:**

```python
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/health")
async def health(request: Request):
    svc = getattr(request.app.state, "scheduler", None)
    if svc is None:
        return {"status": "starting"}
    return {
        "status": "ok",
        "scheduler_running": svc.is_running(),
        "kill_switch": svc.killswitch.is_engaged(),
        "next_run_iso": svc.next_run_iso(),
    }
```

**app/main.py** — per RESEARCH.md Pattern 1:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db.base import engine, async_session, init_db
from app.logging_setup import configure_logging
from app.security.fernet import FernetVault
from app.scheduler.killswitch import KillSwitch
from app.scheduler.rate_limit import RateLimiter
from app.scheduler.service import SchedulerService
from app.scheduler.heartbeat import heartbeat_job, set_scheduler_service
from app.runs.service import mark_orphans_failed
from app.settings.service import get_settings_row
from app.web.routers import health as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configure_logging(cfg.log_level, cfg.data_dir / "logs")

    # Fernet vault — fails fast on bad key
    app.state.vault = FernetVault.from_env(cfg.fernet_key)

    # DB init (WAL pragma)
    await init_db()

    # Hydrate secrets into scrubber + clean up crashed runs
    async with async_session() as session:
        await app.state.vault.register_all_secrets_with_scrubber(session)
        orphans = await mark_orphans_failed(session)
        if orphans:
            import structlog
            structlog.get_logger(__name__).info("orphans_cleaned", count=orphans)

        # Hydrate killswitch + settings row
        app.state.killswitch = await KillSwitch.hydrate_from_settings(session)
        settings_row = await get_settings_row(session)

    rate_limiter = RateLimiter(
        daily_cap=settings_row.daily_cap,
        delay_min=settings_row.delay_min_seconds,
        delay_max=settings_row.delay_max_seconds,
        tz=cfg.tz,
    )
    app.state.rate_limiter = rate_limiter

    # APScheduler with SQLAlchemy jobstore pointed at the SAME SQLite file
    jobstore_url = f"sqlite:///{cfg.data_dir}/app.db"  # sync url for APScheduler jobstore
    tz_obj = ZoneInfo(cfg.tz)
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=jobstore_url)},
        timezone=tz_obj,
    )

    svc = SchedulerService(
        scheduler=scheduler,
        killswitch=app.state.killswitch,
        rate_limiter=rate_limiter,
        session_factory=async_session,
        tz=cfg.tz,
    )
    app.state.scheduler = svc
    set_scheduler_service(svc)

    scheduler.add_job(
        heartbeat_job,
        trigger=CronTrigger(minute=0, timezone=tz_obj),
        id="hourly_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    # Midnight reset job for rate limiter counter row
    scheduler.add_job(
        lambda: _midnight_reset_coro(rate_limiter),
        trigger=CronTrigger(hour=0, minute=0, timezone=tz_obj),
        id="midnight_reset",
        replace_existing=True,
    )
    scheduler.start()
    # If kill-switch is already engaged from prior session, pause the job
    if app.state.killswitch.is_engaged():
        svc.pause_scheduler()

    try:
        yield
    finally:
        scheduler.shutdown(wait=True)
        await engine.dispose()

async def _midnight_reset_coro(rate_limiter):
    async with async_session() as session:
        await rate_limiter.midnight_reset(session)

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, title="Job Application Auto-Apply")
    app.include_router(health_router.router)
    return app

app = create_app()
```

**tests/integration/test_scheduler_lifecycle.py:**

- Use FastAPI `LifespanManager` from `asgi-lifespan` OR simply `async with app.router.lifespan_context(app):` (starlette ≥0.26 supports it). Spin up the app with monkeypatched data_dir and a fresh Fernet key.
- `test_lifespan_starts_and_stops_cleanly`: enter lifespan, assert `app.state.scheduler.is_running()` is True and the hourly_heartbeat job exists. Exit lifespan cleanly.
- `test_health_endpoint`: use httpx AsyncClient + ASGITransport, GET /health → 200, body has `scheduler_running: True, kill_switch: False, next_run_iso: <iso string>`.
- `test_orphan_cleanup_marks_crashed_runs`: pre-insert a Run(status='running') row → start lifespan → assert row now has status='failed', failure_reason='crashed'.

Note: add an `asgi-lifespan` dependency to requirements.txt OR use `httpx` with `base_url` + `transport=ASGITransport(app, lifespan="on")`. Prefer the latter to avoid an extra dep.
  </action>
  <verify>
`pytest tests/integration/test_scheduler_lifecycle.py -q` — all pass.
`python -c "from app.main import app; print(app.title)"` prints "Job Application Auto-Apply".
Spin up the app locally (or via test client): GET /health returns 200 with scheduler_running=True.
`grep -q "CronTrigger(minute=0" app/main.py` returns 0.
`grep -q "max_instances=1" app/main.py` returns 0.
  </verify>
  <done>
SchedulerService implements run_pipeline with asyncio.Lock + kill-switch gate + rate-limit gate + DB sentinel. heartbeat_job is registered on an hourly CronTrigger. main.py lifespan boots cleanly, hydrates killswitch, cleans orphan runs, and tears down cleanly. /health endpoint returns scheduler state. Integration test suite green.
  </done>
</task>

<task type="auto">
  <name>Task 3: Integration tests for dry-run, kill-switch cancellation, and rate-limit skip</name>
  <files>
    tests/integration/test_dry_run_propagation.py,
    tests/integration/test_kill_switch_cancels_run.py,
    tests/integration/test_rate_limit_skips_run.py
  </files>
  <action>
These tests prove that the three must-haves CONTEXT.md calls out — dry-run stamping, kill-switch hard-stop with in-flight cancellation, and 20/day enforcement — actually work end-to-end through SchedulerService.run_pipeline.

**tests/integration/test_dry_run_propagation.py:**

- Fixture: fresh in-memory DB, SchedulerService constructed directly (no full lifespan needed) with a no-op scheduler mock for `pause_job`/`resume_job`/`get_job`.
- `test_dry_run_false_stamps_false`: settings.dry_run=False → run_pipeline → the resulting Run row has dry_run=False.
- `test_dry_run_true_stamps_true`: set settings.dry_run=True → run_pipeline → Run.dry_run=True.
- `test_mid_run_toggle_does_not_retroactively_change_current_run`: start a run_pipeline task; while it's in its 0.05s sleep, toggle settings.dry_run; wait for completion; assert the already-created Run row still reflects the ORIGINAL dry_run value (snapshot semantics).

**tests/integration/test_kill_switch_cancels_run.py:**

- Fixture with a `SchedulerService` whose `_execute_stub` is temporarily replaced via monkeypatch with a long-sleeping coroutine (e.g. `asyncio.sleep(10)` + `killswitch.raise_if_engaged` checkpoints).
- `test_engage_cancels_in_flight`:
  1. Start `run_pipeline(triggered_by="manual")` as a background task.
  2. Wait until `svc._current_task is not None`.
  3. Await `killswitch.engage(svc, session)`.
  4. Await the background task — expect `asyncio.CancelledError`.
  5. Query the Run row — assert `status='failed'`, `failure_reason='killed'`.
- `test_engage_before_run_skips_entirely`: engage kill-switch → call run_pipeline → no Run row created, function returns silently with `log.info("run_skipped_killswitch")`.
- `test_release_allows_new_runs`: engage → release → run_pipeline completes normally with status='succeeded'.

**tests/integration/test_rate_limit_skips_run.py:**

- Fixture: SchedulerService with `RateLimiter(daily_cap=2, delay_min=30, delay_max=120, tz="UTC")`.
- `test_under_cap_run_succeeds`: rate_limit_counters row for today has 0 submissions. run_pipeline → succeeds. Run.status='succeeded'.
- `test_at_cap_run_is_skipped`: seed rate_limit_counters(today, 2). run_pipeline → a Run row is written with status='skipped', failure_reason='rate_limit'. Assert `list_recent_runs()` shows it.
- `test_record_submission_moves_counter`: call `rate_limiter.record_submission(session)` twice → counter=2 → next run_pipeline is skipped.
- `test_midnight_reset_creates_new_day_row(freezer)`: freeze to 2026-04-11 23:59 local → run, counter=1 → advance to 2026-04-12 00:01 local → call `rate_limiter.midnight_reset(session)` → new row for 2026-04-12 exists with count=0 → run succeeds.

Use `freezegun.freeze_time` for the TZ/midnight test. Mock the APScheduler object (pause/resume/get_job/running=True) since we're testing the service logic, not APScheduler's internals.
  </action>
  <verify>
`pytest tests/integration/test_dry_run_propagation.py tests/integration/test_kill_switch_cancels_run.py tests/integration/test_rate_limit_skips_run.py -v` all pass.
`pytest tests/ -q` entire suite passes.
  </verify>
  <done>
Dry-run snapshot semantics proven (mid-run toggle does not retroactively relabel). Kill-switch hard-stop proven (asyncio.CancelledError propagates, Run row marked failed with reason='killed'). Rate limit enforcement proven at entry with a visible skipped Run row. Midnight reset proven TZ-aware via freezegun. All integration tests green.
  </done>
</task>

</tasks>

<verification>
Phase-level checks (overall):
- `pytest tests/ -q` entire suite passes (unit + integration).
- `python -m app.main` (or `uvicorn app.main:app`) starts without error given a valid FERNET_KEY.
- `docker compose up` boots the container, `/health` returns 200 with `scheduler_running: true` within 30s.
- All 11 Phase 1 requirements are functionally satisfied at the service level (UI exposure is plan 01-04's job, but the primitives they bind to all exist here):
  - FOUND-03: hourly CronTrigger + max_instances=1 + asyncio.Lock + DB sentinel ✓
  - FOUND-04: structured logs via structlog JSONRenderer, Run row with counts ✓
  - FOUND-05: RunContext.dry_run snapshot, stamped on Run rows ✓
  - FOUND-06: FernetVault hydrates at lifespan ✓ (plan 01-02 supplied vault)
  - FOUND-07: KillSwitch engage/release + task.cancel ✓
  - DISC-07: random_action_delay exposed (consumed in Phase 6) ✓
  - SAFE-01: daily_cap=20 default + await_precheck ✓
  - SAFE-02: delay_min=30 delay_max=120 defaults ✓
  - SAFE-03: inherited from plan 01-02 ✓
- FOUND-01 (docker compose up boots) + FOUND-02 (SQLite persists) inherited from plan 01-01.
</verification>

<success_criteria>
1. Fresh `docker compose up` brings the app to a healthy `/health` response with `scheduler_running: true`.
2. An hourly CronTrigger job named `hourly_heartbeat` is registered on the AsyncIOScheduler with max_instances=1, coalesce=True, misfire_grace_time=300.
3. `run_pipeline` gates: kill-switch first, rate-limit second, dry-run stamp at run creation, asyncio.Lock around the body, cancellable task for the stub execution.
4. KillSwitch.engage cancels the in-flight task, marks its Run row failed/killed, and pauses the APScheduler job. Release re-enables it.
5. RateLimiter enforces a 20/day default (from Settings row) with TZ-aware local-midnight reset. Random action delay in [30,120].
6. Mid-run dry_run toggles do NOT retroactively relabel the in-flight run — snapshot semantics in RunContext.
7. Orphaned Run(status='running') rows from a crashed container are marked failed on lifespan startup.
8. All unit tests (settings, rate limiter, kill switch) and all integration tests (lifecycle, dry-run, kill-switch, rate-limit) pass.
</success_criteria>

<output>
Write `.planning/phases/01-foundation-scheduler-safety-envelope/01-03-SUMMARY.md` with frontmatter:
- `subsystem: scheduler`
- `tech-stack.added: [apscheduler AsyncIOScheduler (active), asyncio.Lock/Event run-lock, RunContext contract, DB sentinel run-lock]`
- `affects: [01-04, 01-05, all future phases]` — every later phase plugs a stage into SchedulerService.run_pipeline
- `requires: [01-01, 01-02]`
- `key files: [app/main.py, app/scheduler/service.py, app/scheduler/killswitch.py, app/scheduler/rate_limit.py, app/runs/context.py, app/runs/service.py, app/settings/service.py]`
- Decisions: "Stub pipeline is a 50ms sleep with killswitch checkpoints — Phase 2+ replaces the body, not the wrapper", "RunContext is passed as arg, not ContextVar", "Rate-limit counter is a dedicated table keyed by local-TZ ISO date", "Midnight reset runs as an APScheduler cron job, not a cron-in-code timer", "SchedulerService owns lifespan of the cancellable task; only it calls task.cancel", "set_scheduler_service module-level setter bridges APScheduler's function-call invocation with lifespan-scoped state"
- Pattern: "Stages in Phases 2+ must accept RunContext and gate on ctx.dry_run before any outbound effect"
</output>
</content>
</invoke>