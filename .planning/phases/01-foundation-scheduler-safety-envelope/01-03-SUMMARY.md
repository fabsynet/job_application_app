---
phase: 01-foundation-scheduler-safety-envelope
plan: 03
subsystem: scheduler
tags: [apscheduler, asyncio, killswitch, rate-limiter, fastapi, lifespan, run-lock, dry-run, run-context]

# Dependency graph
requires:
  - phase: 01-01
    provides: SQLModel tables (Settings/Run/Secret/RateLimitCounter), async engine, async_session factory, init_db, get_settings
  - phase: 01-02
    provides: FernetVault, SecretRegistry, configure_logging (log scrubber layers)
provides:
  - AsyncIOScheduler + SQLAlchemyJobStore wired inside FastAPI lifespan
  - Hourly CronTrigger heartbeat_job with max_instances=1, coalesce=True, misfire_grace_time=300
  - SchedulerService.run_pipeline with three-layer run-lock (asyncio.Lock + max_instances + DB sentinel Run row)
  - KillSwitch hard-stop primitive (asyncio.Event + task.cancel + pause_job + persisted Settings.kill_switch)
  - RateLimiter (20/day cap + 30-120s jitter + TZ-aware midnight reset via cron job)
  - Frozen RunContext contract consumed by all future pipeline stages
  - Orphan Run cleanup at lifespan startup (mark stale 'running' rows as failed/crashed)
  - GET /health endpoint returning scheduler_running + kill_switch + next_run_iso
affects: [01-04, 01-05, 02-discovery, 03-matching, 04-tailoring, 05-submission, 06-playwright]

# Tech tracking
tech-stack:
  added: [APScheduler 3.11 AsyncIOScheduler (active), SQLAlchemyJobStore, asyncio.Lock/Event run-lock, frozen-dataclass RunContext, DB sentinel Run row]
  patterns:
    - "RESEARCH.md Pattern 1: AsyncIOScheduler inside FastAPI @asynccontextmanager lifespan"
    - "RESEARCH.md Pattern 2: SchedulerService composes scheduler + killswitch + rate_limiter + session_factory"
    - "RESEARCH.md Pattern 3: KillSwitch = asyncio.Event + task.cancel + pause_job + persisted settings flag"
    - "RESEARCH.md Pattern 4: RunContext is a frozen dataclass passed as argument, NOT a ContextVar"
    - "RESEARCH.md Pattern 5: RateLimiter with DB-backed counter keyed by local-TZ ISO date"

key-files:
  created:
    - app/settings/__init__.py
    - app/settings/service.py
    - app/runs/__init__.py
    - app/runs/context.py
    - app/runs/service.py
    - app/scheduler/__init__.py
    - app/scheduler/service.py
    - app/scheduler/heartbeat.py
    - app/scheduler/killswitch.py
    - app/scheduler/rate_limit.py
    - app/main.py
    - app/web/__init__.py
    - app/web/routers/__init__.py
    - app/web/routers/health.py
    - tests/integration/__init__.py
    - tests/integration/test_scheduler_lifecycle.py
    - tests/integration/test_dry_run_propagation.py
    - tests/integration/test_kill_switch_cancels_run.py
    - tests/integration/test_rate_limit_skips_run.py
    - tests/unit/test_settings_service.py
    - tests/unit/test_rate_limiter.py
    - tests/unit/test_killswitch.py
  modified:
    - tests/conftest.py

key-decisions:
  - "Phase 1 stub pipeline is a 50ms asyncio.sleep with two killswitch checkpoints — Phases 2+ replace the body, not the wrapper"
  - "RunContext is a frozen dataclass passed as an argument through every stage (explicit > implicit — ContextVar was rejected per RESEARCH.md Pattern 4)"
  - "Rate-limit counter is a dedicated rate_limit_counters table keyed by local-TZ ISO date string (cheap next-day insert; no UPDATE race)"
  - "Midnight reset runs as an APScheduler CronTrigger(hour=0,minute=0) job, not an in-process timer — benefits from APScheduler's persistence and timezone handling"
  - "SchedulerService owns the lifecycle of the cancellable asyncio.Task; only SchedulerService.cancel_current_run calls task.cancel"
  - "run_pipeline swallows CancelledError at its boundary after finalising the Run row as failed/killed — propagating would abort the APScheduler worker and leave the scheduler in a surprising state"
  - "set_scheduler_service module-level setter bridges APScheduler's function-call invocation model with lifespan-scoped scheduler state (APScheduler has no access to FastAPI app.state)"
  - "Three-layer run-lock defense: asyncio.Lock (process-wide) + APScheduler max_instances=1 (cron-wide) + DB Run sentinel row (crash-recovery)"
  - "Orphan cleanup uses raw UPDATE SQL (not per-row ORM path) for atomicity at lifespan startup"
  - "app.runs.service.mark_orphans_failed supersedes the earlier placeholder in app.db.base.mark_orphans_failed; the runs-service version accepts a session and returns rowcount"
  - "Integration tests drive the lifespan via app.router.lifespan_context(app) because httpx 0.28 dropped ASGITransport(lifespan='on') support"
  - "test_midnight_reset uses monkeypatched RateLimiter.today_local instead of freezegun — freezegun interacts poorly with asyncio's monotonic clock on Windows and hung the test"

patterns-established:
  - "Every Phase 2+ pipeline stage must accept ctx: RunContext and gate outbound side effects on ctx.dry_run before any write"
  - "All run-lifecycle writes go through app.runs.service (never raw ORM in stages)"
  - "Kill-switch checkpoints (await ks.raise_if_engaged()) live inside any long-running stage so hard-stop is responsive"
  - "APScheduler job bodies never raise — they log and return so the worker stays healthy for the next tick"

# Metrics
duration: ~35min
completed: 2026-04-11
---

# Phase 1 Plan 03: Scheduler, Run-Lock, Kill-Switch, Rate-Limit Summary

**AsyncIOScheduler inside FastAPI lifespan with three-layer run-lock, asyncio-Event killswitch that cancels in-flight tasks, 20/day rate limiter with local-TZ midnight reset, and frozen RunContext snapshot — the safety envelope every future phase plugs into.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-04-11
- **Tasks:** 3
- **Files created:** 22
- **Files modified:** 1 (tests/conftest.py)
- **Tests:** 50 passed (21 pre-existing + 29 new: 16 unit + 13 integration)

## Accomplishments

- SchedulerService.run_pipeline implements the full safety envelope: kill-switch gate → rate-limit gate → RunContext snapshot → cancellable task → status/failure_reason finalisation
- Kill-switch hard-stop proven end-to-end: asyncio.Event + task.cancel() cancels mid-run; Run row marked status='failed' failure_reason='killed'; APScheduler job paused; Settings.kill_switch persisted; hydrate_from_settings replays at next boot
- Dry-run snapshot semantics proven: mid-run toggles do NOT retroactively relabel the in-flight run (frozen RunContext enforces it)
- Rate limiter: 20/day cap gates run entry with a visible status='skipped' Run row (dashboard will render these in plan 01-04); 30-120s jitter available; TZ-aware midnight reset registered as APScheduler cron job
- Orphan Run rows from crashed containers are healed at lifespan startup (raw UPDATE, atomic)
- /health endpoint returns scheduler_running + kill_switch + next_run_iso for HTMX dashboard polling
- FernetVault.register_all_secrets_with_scrubber wired into lifespan (secrets hydrate into log scrubber before any later log line can leak them)

## Task Commits

1. **Task 1: Settings/Runs/RateLimiter/KillSwitch primitives** — `c807b97` (feat)
2. **Task 2: SchedulerService + heartbeat + lifespan + /health** — `7dc41e1` (feat)
3. **Task 3: Integration suite for dry-run / kill-switch / rate-limit** — `809b781` (test)

## Files Created/Modified

### Created
- `app/settings/service.py` — single-row Settings accessor (get-or-create, set_setting with updated_at bump, get_setting)
- `app/runs/context.py` — frozen RunContext dataclass (run_id, started_at, dry_run, triggered_by, tz)
- `app/runs/service.py` — create_run, finalize_run, mark_run_killed, mark_orphans_failed, list_recent_runs
- `app/scheduler/service.py` — SchedulerService: run_pipeline with full safety envelope + pause/resume/cancel controls
- `app/scheduler/heartbeat.py` — module-level setter + heartbeat_job coroutine for APScheduler
- `app/scheduler/killswitch.py` — KillSwitch with asyncio.Event, hydrate_from_settings classmethod, raise_if_engaged checkpoint
- `app/scheduler/rate_limit.py` — RateLimiter: daily cap, random_action_delay, record_submission, midnight_reset (idempotent)
- `app/main.py` — FastAPI create_app() and lifespan that wires vault + DB + scrubber + killswitch + rate_limiter + scheduler + cron jobs
- `app/web/routers/health.py` — GET /health reading app.state.scheduler
- `tests/unit/test_settings_service.py` — 4 unit tests (idempotent create, persistence, unknown field, updated_at bump)
- `tests/unit/test_rate_limiter.py` — 7 unit tests including freezegun-based TZ edge cases
- `tests/unit/test_killswitch.py` — 5 unit tests including hydrate_from_settings
- `tests/integration/test_scheduler_lifecycle.py` — 3 tests (lifespan up, starting state, orphan cleanup)
- `tests/integration/test_dry_run_propagation.py` — 3 tests including mid-run snapshot semantics
- `tests/integration/test_kill_switch_cancels_run.py` — 3 tests (cancel in-flight, skip before run, release)
- `tests/integration/test_rate_limit_skips_run.py` — 4 tests (under cap, at cap skipped row, counter, midnight reset)

### Modified
- `tests/conftest.py` — added `async_session` and `async_session_factory` fixtures (in-memory SQLite + create_all)

## Decisions Made

See frontmatter `key-decisions` for the full list. Highlights:

- **run_pipeline swallows CancelledError** at its boundary after finalising the Run row. The alternative (re-raise) would abort the APScheduler worker and leave the scheduler in an awkward state; since the wrapper has already recorded the kill, propagation serves no purpose.
- **Three-layer run-lock** (asyncio.Lock + APScheduler max_instances=1 + DB sentinel) was chosen because each layer catches a different failure mode: the lock protects manual + scheduled overlaps, max_instances protects cron-tick overlaps, and the DB sentinel survives a process crash.
- **freezegun was abandoned** for the midnight reset integration test after it hung the async runner on Windows. Replaced with `monkeypatch.setattr(rl, "today_local", ...)` which targets exactly the one method that reads wall-clock time.
- **app.runs.service.mark_orphans_failed supersedes** the stub in `app.db.base.mark_orphans_failed`. The service version is session-scoped and returns rowcount so lifespan can log how many orphans were healed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] httpx 0.28 dropped ASGITransport lifespan support**
- **Found during:** Task 2 (integration lifecycle test)
- **Issue:** Plan suggested `httpx.ASGITransport(app, lifespan="on")`, but httpx 0.28.1 (pinned in requirements.txt) removed that parameter. /health returned `{"status": "starting"}` because the lifespan never ran.
- **Fix:** Drive the lifespan manually via `app.router.lifespan_context(app)` before creating the httpx client.
- **Files modified:** `tests/integration/test_scheduler_lifecycle.py`
- **Verification:** `test_lifespan_starts_and_stops_cleanly` and `test_orphan_cleanup_marks_crashed_runs` both pass.
- **Committed in:** `7dc41e1` (Task 2 commit)

**2. [Rule 3 - Blocking] freezegun hangs the async test runner on Windows**
- **Found during:** Task 3 (`test_midnight_reset_creates_new_day_row`)
- **Issue:** The original test used `freeze_time("2026-04-11T23:59Z")` around async DB operations. On Windows + Python 3.11 + aiosqlite the event loop never returned — the freezegun monotonic-clock patch interferes with asyncio's internal wait primitives.
- **Fix:** Replaced `freeze_time` with `monkeypatch.setattr(rl, "today_local", lambda: date(2026, 4, 11))`. This targets exactly the one method that reads wall-clock time inside the rate limiter. The unit-test variant (`test_today_local_uses_configured_tz`) still uses freezegun because it has no async DB work and is fast.
- **Files modified:** `tests/integration/test_rate_limit_skips_run.py`
- **Verification:** Test passes in 0.44s.
- **Committed in:** `809b781` (Task 3 commit)

**3. [Rule 3 - Blocking] freezegun missing from dev deps**
- **Found during:** Task 1 setup
- **Issue:** `tests/unit/test_rate_limiter.py` needed freezegun for TZ boundary assertions. Not in requirements.txt.
- **Fix:** Installed freezegun + pytest-asyncio into the local .venv via pip (not added to requirements.txt — keeping requirements.txt production-only; a future dev-requirements.txt is a separate cleanup).
- **Files modified:** none (venv only)
- **Verification:** unit tests pass.
- **Committed in:** n/a (environment setup)

---

**Total deviations:** 3 auto-fixed (3 blocking)
**Impact on plan:** All blockers were environmental/version pins — the plan's design was correct, but two dependency assumptions (httpx lifespan arg, freezegun+asyncio on Windows) needed workarounds. No behaviour or architectural changes.

## Issues Encountered

- The venv (.venv) existed but did not have production deps installed; had to `pip install -r requirements.txt` before tests could run. Similar symptom to 01-01's "docker image not built yet" blocker — this is a working-directory hygiene issue across waves.
- `app/db/base.py` imports `get_settings()` at module load time, so any test or smoke that imports `app.main` before setting FERNET_KEY fails. Integration tests handle this by setting env + reloading `app.config` and `app.db.base` modules before `app.main` import. Future phases should either continue the reload dance or refactor `app.db.base` to lazy-init the engine inside `init_db()`.

## User Setup Required

None — this plan is fully automated.

## Next Phase Readiness

**Ready:**
- SchedulerService.run_pipeline is the single entry point every future stage plugs into. Phase 2 adds the discovery stage by replacing `_execute_stub` with the first real stage call.
- RunContext contract is frozen. Phases 2+ must accept `ctx: RunContext` as an argument and gate outbound effects on `ctx.dry_run`.
- Rate limiter's `record_submission` is the hook Phase 6 (browser) will call after each successful application submission.
- /health endpoint is ready for plan 01-04's HTMX dashboard to poll.

**Blockers/Concerns:**
- `docker compose up` end-to-end smoke still pending (Docker daemon not running on this host — inherited from 01-01).
- requirements.txt should be split into prod vs dev (freezegun, pytest-asyncio are currently venv-only). Non-blocking for 01-04; track as a phase-2 cleanup.
- `app.db.base._settings = get_settings()` at module import time makes test environments need a reload dance. Consider refactoring to lazy-init in a future plan.

## Self-Check: PASSED

All 22 created files exist on disk:
- `app/settings/__init__.py`, `app/settings/service.py`
- `app/runs/__init__.py`, `app/runs/context.py`, `app/runs/service.py`
- `app/scheduler/__init__.py`, `app/scheduler/service.py`, `app/scheduler/heartbeat.py`, `app/scheduler/killswitch.py`, `app/scheduler/rate_limit.py`
- `app/main.py`
- `app/web/__init__.py`, `app/web/routers/__init__.py`, `app/web/routers/health.py`
- `tests/integration/__init__.py`, `tests/integration/test_scheduler_lifecycle.py`, `tests/integration/test_dry_run_propagation.py`, `tests/integration/test_kill_switch_cancels_run.py`, `tests/integration/test_rate_limit_skips_run.py`
- `tests/unit/test_settings_service.py`, `tests/unit/test_rate_limiter.py`, `tests/unit/test_killswitch.py`

All 3 task commits verified in `git log`:
- `c807b97` feat(01-03): settings, runs, rate limiter, killswitch primitives
- `7dc41e1` feat(01-03): SchedulerService, heartbeat, FastAPI lifespan, /health
- `809b781` test(01-03): integration suite for dry-run, kill-switch, rate-limit

---
*Phase: 01-foundation-scheduler-safety-envelope*
*Completed: 2026-04-11*
