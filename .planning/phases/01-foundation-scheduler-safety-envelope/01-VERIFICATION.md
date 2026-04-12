---
phase: 01-foundation-scheduler-safety-envelope
verified: 2026-04-11T00:00:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "User can see an hourly heartbeat in the UI and in structured logs (discovered/matched/tailored/submitted/failed counts)"
    status: partial
    reason: "run_pipeline emits no structured log line on successful completion. Counts visible in DB/UI but not in log stream."
    artifacts:
      - path: "app/scheduler/service.py"
        issue: "Lines 210-214: else branch calls finalize_run() with no log.info. No run_succeeded event exists anywhere in the codebase."
    missing:
      - "log.info in else-branch of run_pipeline emitting run_id, counts, dry_run, duration_ms"
---
# Phase 1: Foundation, Scheduler and Safety Envelope - Verification Report

**Phase Goal:** docker compose up on a fresh laptop gets a running, observable, safely-throttled scheduler with encrypted secrets and a working kill-switch.
**Verified:** 2026-04-11
**Status:** gaps_found
**Re-verification:** No - initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | docker compose up boots with SQLite on ./data volume | VERIFIED | compose.yml mounts ./data:/data; Dockerfile CMD --workers 1; DB_URL = sqlite+aiosqlite:///{data_dir}/app.db; init_db() calls data_dir.mkdir; test_must_have_1 asserts db file exists and survives restart |
| 2 | Hourly heartbeat visible in UI and structured logs with counts; run-lock prevents overlap | PARTIAL | Heartbeat CronTrigger(minute=0) with max_instances=1 and coalesce=True registered; UI dashboard renders last_run.counts for all 5 keys; asyncio.Lock serialises concurrent runs. GAP: else branch of run_pipeline calls finalize_run() with no log.info carrying counts |
| 3 | Dry-run toggle and kill-switch from UI; scheduler immediately respects both | VERIFIED | POST /toggles/kill-switch: sets asyncio.Event + persists + pauses scheduler + cancels in-flight task; POST /toggles/dry-run flips Settings.dry_run; RunContext frozen dataclass snapshots dry_run at entry; full test coverage in test_kill_switch_toggle_engage_release, test_dry_run_toggle, test_kill_switch_cancels_in_flight |
| 4 | Fernet-encrypted secrets survive restart; no PII in logs | VERIFIED | FernetVault.encrypt/decrypt both call REGISTRY.add_literal(plaintext) before I/O; configure_logging installs RedactingFilter on stdlib root + structlog_scrub_processor before JSONRenderer; register_all_secrets_with_scrubber pre-registers at startup; test_must_have_4 reads app.log off disk and asserts sentinel absent |
| 5 | Rate-limit envelope enforced before downstream stages exist | VERIFIED | RateLimiter.await_precheck() called before create_run() in run_pipeline; cap=20, delay 30-120s, midnight reset via CronTrigger(hour=0,minute=0); random_action_delay() = random.uniform; validated by test_must_have_5 and test_rate_limit_skips_run.py |

**Score: 4/5 truths verified (1 partial)**
---

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| compose.yml | VERIFIED | Single ./data:/data mount; healthcheck via httpx; env_file: .env |
| Dockerfile | VERIFIED | FROM playwright/python:v1.58.0-noble; USER app uid 1000; CMD --workers 1 |
| app/config.py | VERIFIED | field_validator calls Fernet(v.encode()); fails fast on bad key |
| app/db/base.py | VERIFIED (minor) | WAL pragma; data_dir.mkdir. Dead code: no-arg mark_orphans_failed() exported but never called - production imports session-arg version from app.runs.service |
| app/db/models.py | VERIFIED | Settings, Secret, Run, RateLimitCounter; counts is JSON column; CANONICAL_FAILURE_REASONS frozenset |
| app/db/migrations/versions/0001_initial.py | VERIFIED | Hand-authored Alembic migration matches models exactly |
| app/security/fernet.py | VERIFIED | from_env registers master key; encrypt/decrypt register plaintext; register_all_secrets_with_scrubber at startup |
| app/security/log_scrubber.py | VERIFIED | SecretRegistry singleton; RedactingFilter (stdlib); structlog_scrub_processor; static regex fallback; thread-safe |
| app/logging_setup.py | VERIFIED | RedactingFilter on stdout + file; structlog_scrub_processor before JSONRenderer; file sink at log_dir/app.log |
| app/scheduler/heartbeat.py | VERIFIED | heartbeat_job() delegates to svc.run_pipeline(); set_scheduler_service called from lifespan |
| app/scheduler/killswitch.py | VERIFIED | engage() set+persist+pause+cancel; release() clear+resume; hydrate_from_settings(); raise_if_engaged() raises CancelledError |
| app/scheduler/rate_limit.py | VERIFIED | await_precheck() raises RateLimitExceeded at cap; random_action_delay() uniform; midnight_reset() idempotent; TZ-aware via ZoneInfo |
| app/scheduler/service.py | PARTIAL | All safety gates present; kill/rate-limit/error paths log. MISSING: no structured log on success path |
| app/runs/service.py | VERIFIED | create_run, finalize_run, mark_run_killed, mark_orphans_failed (session-arg), list_recent_runs all substantive |
| app/runs/context.py | VERIFIED | frozen=True dataclass with run_id, started_at, dry_run, triggered_by, tz |
| app/settings/service.py | VERIFIED | get_settings_row get-or-create; set_setting with updated_at bump |
| app/web/routers/dashboard.py | VERIFIED | GET /, /fragments/status, /fragments/next-run, POST /runs/trigger; wizard guard; rotation banner |
| app/web/routers/toggles.py | VERIFIED | HTMX partial re-render; engage/release wired |
| app/web/routers/health.py | VERIFIED | Returns scheduler_running, kill_switch, next_run_iso; safe before scheduler ready |
| app/web/routers/wizard.py | VERIFIED | /setup/1 DOCX upload, /setup/2 secrets, /setup/3 keywords+wizard_complete; /setup/skip |
| app/web/routers/settings.py | VERIFIED | Secrets CRUD; /settings/limits updates DB and live rate_limiter singleton |
| app/web/templates/dashboard.html.j2 | VERIFIED | All 5 count keys rendered; HTMX polling 5s/15s; toggles present |
| app/web/templates/partials/toggles.html.j2 | VERIFIED | HTMX forms; visual state from kill_engaged/dry_run context vars |
| app/main.py | VERIFIED | Full boot: Fernet, init_db, scrubber pre-registration, orphan cleanup, KillSwitch hydration, RateLimiter, APScheduler, heartbeat+midnight_reset jobs, conditional pause |
---

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| main.py lifespan | FernetVault | FernetVault.from_env(cfg.fernet_key) line 73 | WIRED |
| main.py lifespan | KillSwitch | KillSwitch.hydrate_from_settings(session) line 89 | WIRED |
| main.py lifespan | RateLimiter | constructed from settings row lines 97-103 | WIRED |
| main.py lifespan | APScheduler | AsyncIOScheduler + SQLAlchemyJobStore same SQLite file | WIRED |
| heartbeat_job | SchedulerService.run_pipeline | set_scheduler_service module-level setter | WIRED |
| SchedulerService.run_pipeline | KillSwitch.is_engaged() | direct call before lock line 142 | WIRED |
| SchedulerService.run_pipeline | RateLimiter.await_precheck() | direct call inside lock line 152 before create_run | WIRED |
| SchedulerService.run_pipeline | asyncio.Task | asyncio.create_task(_execute_stub) line 187 stored on _current_task | WIRED |
| KillSwitch.engage() | scheduler_service.cancel_current_run() | direct call killswitch.py line 56 | WIRED |
| FernetVault.encrypt/decrypt | REGISTRY.add_literal() | side-effect before return in both methods | WIRED |
| configure_logging | RedactingFilter | addFilter on stdout + file handlers | WIRED |
| configure_logging | structlog_scrub_processor | placed in chain before JSONRenderer | WIRED |
| settings_router.save_limits | live RateLimiter singleton | Depends(get_rate_limiter) + direct mutation lines 155-161 | WIRED |
| toggles_router.toggle_kill | KillSwitch.engage/release | dependency-injected ks | WIRED |

---

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| FOUND-01: docker compose up starts the app | SATISFIED | compose.yml + Dockerfile verified |
| FOUND-02: SQLite persisted to mounted volume | SATISFIED | ./data:/data mount + DB_URL /data/app.db |
| FOUND-03: Hourly scheduler with run-lock | SATISFIED | APScheduler CronTrigger + asyncio.Lock |
| FOUND-04: Kill-switch hard stop | SATISFIED | KillSwitch.engage() + task.cancel() + pause_scheduler() |
| FOUND-05: Dry-run toggle with UI | SATISFIED | Settings.dry_run + RunContext snapshot + toggles route |
| FOUND-06: Fernet-encrypted secret storage | SATISFIED | FernetVault + Secret table with LargeBinary ciphertext only |
| FOUND-07: First-run wizard | SATISFIED | 3-step wizard with skip affordance |
| DISC-07: Structured logging with counts visible | PARTIAL | Logging is JSON-structured and scrubbed; counts in DB/UI but no structured log line on run success |
| SAFE-01: No PII in stdout/log files | SATISFIED | Two-layer scrubber + startup pre-registration + static regex fallback |
| SAFE-02: Rate-limit envelope enforced | SATISFIED | await_precheck() before create_run; random_action_delay; midnight reset |
| SAFE-03: Secrets survive container restart | SATISFIED | Fernet ciphertext in SQLite on mounted volume; decryptable across restarts |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| app/db/base.py lines 72-92 | mark_orphans_failed() no-arg version exported in __all__ but never called | Warning | Dead code; production path in app.runs.service is correct |
| app/scheduler/service.py lines 210-214 | Success path calls finalize_run() without log.info() | Blocker for must_have 2 | Operator cannot observe heartbeat completion in structured log stream |
---

### Human Verification Required

#### 1. Docker Build and First Boot

**Test:** On a machine with Docker, set FERNET_KEY in .env (generate via python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"), run docker compose up.
**Expected:** Container starts, http://localhost:8000 redirects to /setup/1, /health returns status:ok with scheduler_running:true.
**Why human:** Docker daemon availability cannot be asserted programmatically in this test environment.

#### 2. HTMX Live Polling Behavior

**Test:** Open dashboard in a browser after completing wizard. Watch status pill and countdown for 30 seconds.
**Expected:** Status pill refreshes every 5 seconds; countdown updates every 15 seconds without full page reload.
**Why human:** Browser-rendered HTMX polling requires a real browser.

#### 3. Kill-Switch Visual Feedback

**Test:** On dashboard, click Kill switch button.
**Expected:** Button text changes to Release kill-switch; status pill shows Paused by kill-switch. Clicking again releases.
**Why human:** CSS rendering and visual state requires a browser.

---

## Gaps Summary

**One gap blocks full goal achievement.**

**Missing: structured log event on successful run completion (must_have 2, DISC-07)**

The run_pipeline success path (else branch, lines 210-214 of app/scheduler/service.py) silently calls finalize_run(session, ctx.run_id, status=succeeded) without emitting any structured log event. Every other outcome logs: kill-switch skip logs run_skipped_killswitch, rate-limit skip logs run_skipped_rate_limit, mid-run kill logs run_killed, error logs run_errored. Only success is silent.

The must-have explicitly requires counts to be visible in structured logs. In Phase 1 all counts are zero, but the log line shape is a contract for Phase 2+ operators who need to observe heartbeat completion in a log aggregator without querying the DB.

Fix: Add log.info(run_succeeded, run_id=ctx.run_id, counts=run.counts, dry_run=ctx.dry_run, triggered_by=ctx.triggered_by) in the else branch after finalize_run, with a DB read to fetch the finalized Run row.

Severity: Observability contract gap only. The system is functionally correct and deployable. All safety primitives (encryption, kill-switch, rate limiting, PII scrubbing) work. The missing log line is the only delta between current state and full must-have compliance.

---

_Verified: 2026-04-11_
_Verifier: Claude (gsd-verifier)_
