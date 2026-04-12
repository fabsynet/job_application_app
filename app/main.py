"""FastAPI application factory with the full Phase 1 lifespan.

RESEARCH.md Pattern 1. The lifespan context is the single place that
instantiates every long-lived collaborator:

* Configure logging (scrubber filters are applied to every handler).
* Build the FernetVault from ``$FERNET_KEY`` — fails fast on bad key.
* ``init_db()`` — WAL pragma, data dir creation.
* Hydrate stored secrets into the log scrubber.
* Heal orphaned ``Run(status='running')`` rows from a crashed container.
* Hydrate the kill-switch from ``Settings.kill_switch``.
* Build the RateLimiter from the Settings row defaults.
* Build the AsyncIOScheduler with a SQLAlchemyJobStore pointed at the same
  SQLite file (via a sync URL).
* Register the ``hourly_heartbeat`` CronTrigger(minute=0) job.
* Register the ``midnight_reset`` CronTrigger(hour=0, minute=0) job that
  creates the next day's rate-limit counter row.
* Start the scheduler, pause the hourly job if kill-switch came up engaged.

On shutdown: stop the scheduler and dispose the DB engine.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from pathlib import Path

import structlog
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db.base import async_session, engine, init_db
from app.logging_setup import configure_logging
from app.runs.service import mark_orphans_failed
from app.scheduler.heartbeat import heartbeat_job, set_scheduler_service
from app.scheduler.killswitch import KillSwitch
from app.scheduler.rate_limit import RateLimiter
from app.scheduler.service import SchedulerService
from app.security.fernet import FernetVault
from app.settings.service import get_settings_row
from app.web.routers import dashboard as dashboard_router
from app.web.routers import health as health_router
from app.web.routers import runs as runs_router
from app.web.routers import settings as settings_router
from app.web.routers import toggles as toggles_router
from app.web.routers import sources as sources_router
from app.web.routers import jobs as jobs_router
from app.web.routers import wizard as wizard_router

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


async def _midnight_reset_coro(rate_limiter: RateLimiter) -> None:
    """Wrapper so the rate limiter can be invoked by APScheduler without args."""
    async with async_session() as session:
        await rate_limiter.midnight_reset(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configure_logging(cfg.log_level, cfg.data_dir / "logs")

    # Fernet vault — fails fast on a bad master key.
    app.state.vault = FernetVault.from_env(cfg.fernet_key)

    # DB init (WAL pragma + data dir).
    await init_db()

    async with async_session() as session:
        # Pre-register every stored secret with the scrubber so no later
        # log line can leak them.
        await app.state.vault.register_all_secrets_with_scrubber(session)

        # Heal orphan runs from a previous crash.
        orphans = await mark_orphans_failed(session)
        if orphans:
            log.info("orphans_cleaned", count=orphans)

        # Hydrate the killswitch from the persisted flag.
        app.state.killswitch = await KillSwitch.hydrate_from_settings(session)

        # Snapshot the tunable rate-limit fields from the Settings row.
        settings_row = await get_settings_row(session)
        rl_daily_cap = settings_row.daily_cap
        rl_delay_min = settings_row.delay_min_seconds
        rl_delay_max = settings_row.delay_max_seconds

    rate_limiter = RateLimiter(
        daily_cap=rl_daily_cap,
        delay_min=rl_delay_min,
        delay_max=rl_delay_max,
        tz=cfg.tz,
    )
    app.state.rate_limiter = rate_limiter

    # APScheduler uses a *sync* SQLAlchemy URL for its jobstore, pointed at
    # the same SQLite file. This is safe because WAL journal mode is on.
    jobstore_url = f"sqlite:///{cfg.data_dir}/app.db"
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
        id=SchedulerService.HEARTBEAT_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _midnight_reset_coro,
        trigger=CronTrigger(hour=0, minute=0, timezone=tz_obj),
        id="midnight_reset",
        replace_existing=True,
        args=[rate_limiter],
    )

    scheduler.start()

    # If the kill-switch hydrated as engaged, the hourly job must start paused.
    if app.state.killswitch.is_engaged():
        svc.pause_scheduler()

    log.info(
        "lifespan_ready",
        scheduler_running=svc.is_running(),
        kill_switch=app.state.killswitch.is_engaged(),
        tz=cfg.tz,
    )

    try:
        yield
    finally:
        try:
            scheduler.shutdown(wait=True)
        except Exception as e:  # noqa: BLE001
            log.warning("scheduler_shutdown_error", error=str(e))
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, title="Job Application Auto-Apply")
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(health_router.router)
    app.include_router(wizard_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(toggles_router.router)
    app.include_router(runs_router.router)
    app.include_router(settings_router.router)
    app.include_router(sources_router.router)
    app.include_router(jobs_router.router)
    return app


app = create_app()


__all__ = ["app", "create_app", "lifespan"]
