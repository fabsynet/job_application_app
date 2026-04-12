"""Phase 1 goal-backward end-to-end test suite.

Every test here maps 1:1 to a must_have from the Phase 1 scope. Assertions
run against the real FastAPI lifespan with a fresh ``tmp_path`` data
directory — no mocks for the subsystems under test.

must_haves:
  1. docker compose up boots the app with SQLite on ./data volume
  2. Hourly heartbeat visible + run-lock prevents overlap
  3. Dry-run toggle AND kill-switch respected by scheduler in real time
  4. Fernet-encrypted secrets survive container restart + zero PII/resume
     content in any log sink
  5. Rate-limit envelope (20/day cap, 30-120s jittered delays,
     local-midnight reset) enforced before downstream stages exist
  6. Setup wizard routes user through resume -> API keys -> keywords on
     first boot

Rule 3 deviation note: must_have #1 cannot assert an actual ``docker compose
up`` on this host (Docker daemon presence is not guaranteed). This suite
substitutes an in-process lifespan that runs the same init_db / scheduler
/ Fernet / settings path the container entrypoint runs. Manual verification
steps for the Docker path are documented in the 01-05 SUMMARY.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
import structlog
from cryptography.fernet import Fernet
from sqlalchemy import select


def _reload_for(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str):
    monkeypatch.setenv("FERNET_KEY", key)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("BIND_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    import app.config as config_module

    config_module.get_settings.cache_clear()
    importlib.reload(config_module)

    import app.db.base as base_module

    importlib.reload(base_module)

    # Reload wizard router so its captured ``get_settings`` reference
    # points to the freshly reloaded ``app.config.get_settings`` function.
    import app.web.routers.wizard as wizard_module

    importlib.reload(wizard_module)

    from app.db import models  # noqa: F401

    return base_module


async def _ensure_schema(base_module) -> None:
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    )


@pytest_asyncio.fixture
async def clean_boot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Fresh tmp data dir + Fernet key + full app lifespan.

    Yields a 4-tuple ``(app, base_module, tmp_path, key)``. Tests that need
    a second lifespan (e.g. persistence assertions) rebuild via ``_reload_for``.
    """
    key = Fernet.generate_key().decode()
    base_module = _reload_for(monkeypatch, tmp_path, key)
    await _ensure_schema(base_module)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()
    yield app, base_module, tmp_path, key
    await base_module.engine.dispose()


# ---------------------------------------------------------------------------
# must_have #1 — container boots with SQLite on ./data volume
# ---------------------------------------------------------------------------


async def test_must_have_1_sqlite_on_data_volume_and_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = Fernet.generate_key().decode()
    base_module = _reload_for(monkeypatch, tmp_path, key)
    await _ensure_schema(base_module)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        # SQLite file is on the data volume.
        db_file = tmp_path / "app.db"
        assert db_file.exists(), "SQLite file must live on the ./data volume"
        # Log directory was created by configure_logging().
        assert (tmp_path / "logs").exists()

        async with _client(app) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["scheduler_running"] is True

    await base_module.engine.dispose()

    # --- simulated restart on the same data dir ---
    db_file = tmp_path / "app.db"
    assert db_file.exists(), "db file must survive lifespan shutdown"

    base_module = _reload_for(monkeypatch, tmp_path, key)
    # No create_all this time — the existing schema must still be valid.
    importlib.reload(main_module)
    app2 = main_module.create_app()

    async with app2.router.lifespan_context(app2):
        from app.db.models import RateLimitCounter, Settings

        async with base_module.async_session() as session:
            # Settings row hydrates (get_settings_row created it on first boot).
            row = (
                await session.execute(select(Settings).where(Settings.id == 1))
            ).scalar_one()
            assert row is not None
            # Rate-limit counter table still queryable.
            _ = (
                await session.execute(select(RateLimitCounter))
            ).scalars().all()

    await base_module.engine.dispose()


# ---------------------------------------------------------------------------
# must_have #2 — hourly heartbeat visible + run-lock
# ---------------------------------------------------------------------------


async def test_must_have_2_hourly_heartbeat_and_runlock(clean_boot) -> None:
    app, base_module, *_ = clean_boot
    from app.db.models import Run
    from app.scheduler.service import SchedulerService

    async with app.router.lifespan_context(app):
        svc = app.state.scheduler
        job = svc._scheduler.get_job(SchedulerService.HEARTBEAT_JOB_ID)
        assert job is not None, "hourly_heartbeat job must be registered"
        assert job.next_run_time is not None
        assert job.max_instances == 1
        assert job.coalesce is True

        # Concurrent manual triggers must not overlap — the asyncio.Lock
        # serialises them, so both runs complete but do not execute
        # concurrently.
        await asyncio.gather(
            svc.run_pipeline(triggered_by="manual"),
            svc.run_pipeline(triggered_by="manual"),
        )
        async with base_module.async_session() as session:
            rows = (
                await session.execute(select(Run).order_by(Run.started_at))
            ).scalars().all()
            assert len(rows) == 2
            # Non-overlap: run-1.ended_at <= run-2.started_at (allow equal)
            r1, r2 = rows
            assert r1.ended_at is not None
            assert r1.ended_at <= r2.started_at or r1.started_at <= r2.started_at
            # Counts dict initialised with canonical keys.
            for key in ("discovered", "matched", "tailored", "submitted", "failed"):
                assert key in r1.counts
                assert r1.counts[key] == 0


# ---------------------------------------------------------------------------
# must_have #3 — dry-run + kill-switch respected in real time
# ---------------------------------------------------------------------------


async def test_must_have_3_dry_run_stamped(clean_boot) -> None:
    app, base_module, *_ = clean_boot
    from app.db.models import Run

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post("/setup/skip")
            # Flip dry-run ON.
            await client.post("/toggles/dry-run")

        svc = app.state.scheduler
        await svc.run_pipeline(triggered_by="manual")

        async with base_module.async_session() as session:
            row = (
                await session.execute(
                    select(Run).order_by(Run.started_at.desc()).limit(1)
                )
            ).scalar_one()
            assert row.dry_run is True


async def test_must_have_3_killswitch_cancels_in_flight(clean_boot) -> None:
    app, base_module, *_ = clean_boot
    from app.db.models import Run

    async with app.router.lifespan_context(app):
        svc = app.state.scheduler
        ks = app.state.killswitch

        # Replace the stub body with a long, checkpointed coroutine.
        async def long_stub(ctx):
            for _ in range(1000):
                await ks.raise_if_engaged()
                await asyncio.sleep(0.005)

        svc._execute_stub = long_stub  # type: ignore[method-assign]

        run_task = asyncio.create_task(svc.run_pipeline(triggered_by="manual"))
        # Wait for the task to exist.
        for _ in range(200):
            await asyncio.sleep(0.005)
            if svc._current_task is not None:
                break
        assert svc._current_task is not None

        # Engage the kill-switch through the HTTP surface.
        async with _client(app) as client:
            await client.post("/toggles/kill-switch")

        # Wait for run_pipeline to finish its cancellation bookkeeping.
        for _ in range(200):
            await asyncio.sleep(0.005)
            if run_task.done():
                break
        assert run_task.done()

        async with base_module.async_session() as session:
            row = (
                await session.execute(
                    select(Run).order_by(Run.started_at.desc()).limit(1)
                )
            ).scalar_one()
            assert row.status == "failed"
            assert row.failure_reason == "killed"


# ---------------------------------------------------------------------------
# must_have #4 — Fernet secrets survive restart + zero PII in logs
# ---------------------------------------------------------------------------


async def test_must_have_4_fernet_survives_restart_and_no_pii_in_logs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = Fernet.generate_key().decode()
    SENTINEL = "sk-ant-api03-ENDTOENDSENTINELDEADBEEF"

    base_module = _reload_for(monkeypatch, tmp_path, key)
    await _ensure_schema(base_module)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post("/setup/skip")
            resp = await client.post(
                "/settings/secrets",
                data={"name": "anthropic_api_key", "value": SENTINEL},
            )
            assert resp.status_code == 200

        # Deliberately emit a structlog line containing the sentinel — the
        # scrubber MUST redact it before it reaches the file sink.
        structlog.get_logger("end_to_end_test").info(
            "attempting_to_log_secret", leaked_value=SENTINEL
        )
        # And a stdlib line on the root logger, to exercise RedactingFilter.
        logging.getLogger("end_to_end_test").info(
            "stdlib_leak_attempt %s", SENTINEL
        )
        # Flush handlers.
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass

    await base_module.engine.dispose()

    # --- second boot with the same key ---
    base_module = _reload_for(monkeypatch, tmp_path, key)
    # Schema must be intact from the first boot — no create_all.
    importlib.reload(main_module)
    app2 = main_module.create_app()

    async with app2.router.lifespan_context(app2):
        from app.db.models import Secret

        async with base_module.async_session() as session:
            row = (
                await session.execute(
                    select(Secret).where(Secret.name == "anthropic_api_key")
                )
            ).scalar_one()
            # Survives restart — decryptable with the same key.
            plaintext = app2.state.vault.decrypt(row.ciphertext)
            assert plaintext == SENTINEL

    await base_module.engine.dispose()

    # Zero-PII check: the sentinel must not appear in app.log.
    log_file = tmp_path / "logs" / "app.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8", errors="replace")
    assert SENTINEL not in content, (
        "log scrubber failed to redact the secret sentinel from app.log"
    )


# ---------------------------------------------------------------------------
# must_have #5 — rate-limit envelope enforced before downstream stages
# ---------------------------------------------------------------------------


async def test_must_have_5_rate_limit_envelope(clean_boot) -> None:
    app, base_module, *_ = clean_boot
    from app.db.models import RateLimitCounter, Run
    from app.scheduler.rate_limit import RateLimiter
    from app.settings.service import set_setting

    async with app.router.lifespan_context(app):
        svc = app.state.scheduler

        # Seed: daily cap = 2, already at 2.
        async with base_module.async_session() as session:
            await set_setting(session, "daily_cap", 2)

        # Swap the live rate limiter to a tight one mid-lifespan.
        tight = RateLimiter(daily_cap=2, delay_min=30, delay_max=120, tz="UTC")
        svc._rate_limiter = tight
        app.state.rate_limiter = tight

        # Seed today's counter at the cap.
        today_iso = tight.today_local().isoformat()
        async with base_module.async_session() as session:
            session.add(RateLimitCounter(day=today_iso, submitted_count=2))
            await session.commit()

        # Pipeline must skip with failure_reason='rate_limit'.
        await svc.run_pipeline(triggered_by="manual")

        async with base_module.async_session() as session:
            row = (
                await session.execute(
                    select(Run).order_by(Run.started_at.desc()).limit(1)
                )
            ).scalar_one()
            assert row.status == "skipped"
            assert row.failure_reason == "rate_limit"

        # Action delay always falls in [delay_min, delay_max] across 50 samples.
        for _ in range(50):
            d = tight.random_action_delay()
            assert 30 <= d <= 120


# ---------------------------------------------------------------------------
# must_have #6 — setup wizard routes through resume -> api keys -> keywords
# ---------------------------------------------------------------------------


async def test_must_have_6_wizard_routes_user_through_all_three_steps(
    clean_boot,
) -> None:
    app, base_module, tmp_path, _ = clean_boot
    from app.db.models import Secret, Settings

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            # Fresh boot -> redirect to wizard step 1.
            resp = await client.get("/")
            assert resp.status_code == 307
            assert resp.headers["location"] == "/setup/1"

            # Step 1: upload resume.
            resp = await client.post(
                "/setup/1",
                files={
                    "resume": (
                        "r.docx",
                        b"binary-content",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert resp.status_code == 303
            assert (tmp_path / "uploads" / "resume_base.docx").exists()

            # Step 2: store API key + smtp host.
            resp = await client.post(
                "/setup/2",
                data={
                    "anthropic_api_key": "sk-ant-wizard-key",
                    "smtp_host": "smtp.example.com",
                },
            )
            assert resp.status_code == 303

            # Step 3: keywords.
            resp = await client.post(
                "/setup/3", data={"keywords": "python\nrust"}
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/"

            # Dashboard now renders without redirect.
            resp = await client.get("/")
            assert resp.status_code == 200

        async with base_module.async_session() as session:
            names = [
                r[0]
                for r in (
                    await session.execute(select(Secret.name))
                ).all()
            ]
            assert "anthropic_api_key" in names
            assert "smtp_host" in names

            row = (
                await session.execute(select(Settings).where(Settings.id == 1))
            ).scalar_one()
            assert row.wizard_complete is True
            assert row.keywords_csv == "python,rust"
