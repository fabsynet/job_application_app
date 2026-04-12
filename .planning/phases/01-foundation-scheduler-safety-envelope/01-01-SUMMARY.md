---
phase: 01-foundation-scheduler-safety-envelope
plan: 01
subsystem: infrastructure
tags: [docker, fastapi, sqlmodel, alembic, apscheduler, cryptography, pydantic-settings, sqlite, playwright-base]

requires:
  - phase: none
    provides: "First plan of Phase 1 — no upstream dependencies."
provides:
  - "Playwright-based Docker image with non-root app user and uvicorn --workers 1 CMD"
  - "docker compose deploy shape with ./data bind mount, BIND_ADDRESS passthrough, httpx healthcheck"
  - "pydantic-settings Settings model with fail-fast FERNET_KEY validation via get_settings() lru_cache"
  - "SQLModel schema for Settings, Secret, Run, RateLimitCounter plus CANONICAL_FAILURE_REASONS constant"
  - "Async SQLAlchemy engine, async_session factory, init_db() that enables WAL, mark_orphans_failed() recovery helper"
  - "Alembic baseline migration 0001_initial with include_object filter excluding apscheduler_* tables"
affects:
  - 01-02  # FernetVault / log scrubber imports app.config.get_settings
  - 01-03  # SchedulerService imports async_session, calls mark_orphans_failed on boot
  - 01-04  # Rate limiter writes to RateLimitCounter rows
  - 01-05  # Dashboard reads Run rows, writes Settings toggle rows

tech-stack:
  added:
    - fastapi==0.135.3
    - uvicorn[standard]==0.36.0
    - sqlmodel>=0.0.24
    - sqlalchemy[asyncio]==2.0.36
    - aiosqlite==0.20.0
    - alembic==1.14.0
    - apscheduler==3.11.0 (pinned now, wired in 01-03)
    - cryptography==44.0.0
    - pydantic==2.12.0
    - pydantic-settings==2.13.1
    - jinja2==3.1.4
    - structlog==24.4.0
    - httpx==0.28.1
    - python-multipart==0.0.17
  patterns:
    - "Fail-fast config: Settings validator instantiates Fernet(key) at construction time"
    - "Cached settings entrypoint: get_settings() with lru_cache(maxsize=1) for testability"
    - "SQLite WAL pragma at startup via init_db()"
    - "Single ./data bind mount for all persistent state (SQLite, logs, uploads, browser state)"
    - "Alembic include_object hook filters apscheduler_* tables out of target_metadata"
    - "Orphan run recovery: UPDATE runs SET status='failed', failure_reason='crashed' WHERE status='running'"

key-files:
  created:
    - Dockerfile
    - compose.yml
    - .env.example
    - .gitignore
    - requirements.txt
    - pyproject.toml
    - app/config.py
    - app/db/__init__.py
    - app/db/models.py
    - app/db/base.py
    - alembic.ini
    - app/db/migrations/env.py
    - app/db/migrations/script.py.mako
    - app/db/migrations/versions/0001_initial.py
    - tests/__init__.py
    - tests/unit/__init__.py
    - tests/conftest.py
    - tests/unit/test_config.py
    - tests/unit/test_models.py
  modified: []

key-decisions:
  - "APScheduler 3.11.x pinned (not 4.x alpha) — research resolved despite CONTEXT.md giving Claude's discretion"
  - "Single ./data host bind mount: one volume holds SQLite, logs, uploads, browser state"
  - "WAL mode enabled in init_db() so HTMX dashboard polls do not block scheduler writes"
  - "get_settings() cached function instead of module-level settings = Settings() for test-fixture override"
  - "keywords_csv kept as a column on settings (Phase 2 may promote to a keywords table)"
  - "Alembic owns production schema; init_db() leaves SQLModel.metadata.create_all commented for in-memory test use"
  - "include_object hook in alembic env.py excludes apscheduler_* tables from target_metadata"

patterns-established:
  - "Fail-fast env validation: pydantic field_validator instantiates the consuming primitive (Fernet) at load time, so bad config crashes before the HTTP port binds"
  - "Singleton scheduler invariant is documented in Dockerfile header AND enforced by --workers 1 in CMD"
  - "One ./data volume convention: every persistent path derived from DATA_DIR, no scattered bind mounts"
  - "Hand-authored baseline migration rather than autogenerate, because the async engine setup complicates Alembic autogenerate against a fresh DB"

duration: ~1h
completed: 2026-04-11
---

# Phase 1 Plan 01: Docker + DB Foundation Summary

**Bootable FastAPI-on-Playwright container with fail-fast Fernet-validated config, async SQLModel schema (Settings/Secret/Run/RateLimitCounter), and Alembic baseline migration that excludes APScheduler tables from target_metadata.**

## Performance

- **Duration:** ~1h
- **Started:** 2026-04-11T23:00Z
- **Completed:** 2026-04-12T00:06Z
- **Tasks:** 3 / 3
- **Files created:** 19

## Accomplishments

- Docker + compose deploy shape using the Playwright 1.58.0-noble base (Phase 6 ready), non-root app user, `--workers 1` uvicorn CMD, single `./data:/data` bind mount, httpx healthcheck, BIND_ADDRESS passthrough.
- Typed, fail-fast configuration layer: `app.config.Settings` validates `FERNET_KEY` by instantiating `Fernet(key)` inside a pydantic `field_validator`; `get_settings()` is an lru-cached entry point so tests can override env and call `cache_clear()`.
- Async SQLAlchemy engine, `async_sessionmaker` with `expire_on_commit=False`, `init_db()` that enables WAL mode, and `mark_orphans_failed()` recovery helper that heals `Run(status='running')` rows left by a hard kill.
- All four Phase 1 tables (`settings`, `secrets`, `runs`, `rate_limit_counters`) declared as SQLModel classes with correct defaults and indexes; baseline Alembic migration `0001_initial` creates them and filters `apscheduler_*` out of `target_metadata` via `include_object`.
- Unit test suite: 4 config tests + 5 model tests, all green.

## Task Commits

Task 1's files were already present in an earlier mixed commit (`fb9410f feat(01-02): add two-layer log scrubber and logging setup`) from a previous execution that bundled Phase 1 plan 01-01 scaffolding with plan 01-02 security code. The on-disk content exactly matches this plan's specification, so no re-commit was possible or necessary. Commit hashes:

1. **Task 1: Docker image, compose, pyproject, env scaffolding** — `fb9410f` (pre-existing mixed commit; files verified to match plan spec byte-for-byte)
2. **Task 2: Typed config with fail-fast Fernet validation** — `191e827` (feat)
3. **Task 3: SQLModel tables, async engine, Alembic baseline migration** — `3cd7ef8` (feat)

**Plan metadata commit:** to be added after this SUMMARY.md is written.

## Files Created/Modified

**Task 1 — Container + packaging shell (committed in `fb9410f`):**
- `Dockerfile` — Playwright 1.58.0-noble base, non-root `app` user (uid 1000), `PYTHONUNBUFFERED=1`, `EXPOSE 8000`, `CMD uvicorn --workers 1`, header comment explaining why `--workers 1` is load-bearing.
- `compose.yml` — single `app` service, `./data:/data` bind mount, env_file `.env`, httpx-based healthcheck, `${BIND_ADDRESS:-0.0.0.0}:8000:8000` port mapping.
- `.env.example` — documents `FERNET_KEY` generation command, `TZ`, `BIND_ADDRESS` semantics.
- `.gitignore` — ignores `data/`, `.env`, Python caches, editor junk.
- `requirements.txt` — pinned Phase 1 stack.
- `pyproject.toml` — `[project]` + pytest `asyncio_mode = "auto"` + ruff + mypy config.

**Task 2 — Config layer (commit `191e827`):**
- `app/config.py` — `Settings(BaseSettings)` with `FERNET_KEY`, `TZ`, `BIND_ADDRESS`, `DATA_DIR`, `LOG_LEVEL`; `field_validator` raises on missing/malformed Fernet key; `get_settings()` lru-cached entrypoint.
- `tests/__init__.py`, `tests/unit/__init__.py` — empty package markers.
- `tests/conftest.py` — `tmp_fernet_key` and `env_with_fernet` opt-in fixtures.
- `tests/unit/test_config.py` — missing/malformed/valid key tests plus a cache-identity test (4 tests, all green).

**Task 3 — DB models + migrations (commit `3cd7ef8`):**
- `app/db/__init__.py` — package marker.
- `app/db/models.py` — `Settings`, `Secret`, `Run`, `RateLimitCounter` SQLModel classes + `CANONICAL_FAILURE_REASONS` frozenset.
- `app/db/base.py` — `engine`, `async_session`, `init_db()` (enables WAL), `mark_orphans_failed()`.
- `alembic.ini` — `script_location = app/db/migrations`, sync SQLite URL for migrations.
- `app/db/migrations/env.py` — offline + online runners, `include_object` filter for `apscheduler_*`.
- `app/db/migrations/script.py.mako` — standard Alembic template.
- `app/db/migrations/versions/0001_initial.py` — hand-authored baseline creating all four tables with indexes (`ix_secrets_name` unique, `ix_runs_started_at`).
- `tests/unit/test_models.py` — import check, Settings defaults, empty counts dict, canonical failure reasons set (5 tests, all green).

## Decisions Made

All decisions were pre-specified by CONTEXT.md / RESEARCH.md. Execution-level choices:

- Used `get_settings()` lru-cached entrypoint rather than a top-level `settings = Settings()`, so `monkeypatch.setenv(...)` in tests can be followed by `get_settings.cache_clear()` without reimporting the module.
- Used `populate_by_name=True` on `SettingsConfigDict` so both the alias and the Python attribute name work (keeps `monkeypatch.setenv("DATA_DIR", ...)` honest against the `data_dir` field).
- `CANONICAL_FAILURE_REASONS` implemented as a `frozenset` (immutable) rather than a plain `set` so downstream code cannot accidentally mutate the vocabulary.
- `init_db()` leaves `SQLModel.metadata.create_all` commented out with a note that test fixtures call it explicitly on in-memory engines.
- Test `test_get_settings_is_cached` added beyond the three cases in the plan — the cache identity is a contract other plans rely on and is worth pinning.

## Deviations from Plan

### Process deviation (environment)

**1. [Rule 3 — Blocking] `docker compose build` verification could not run because the Docker daemon was not running on the host**
- **Found during:** Task 1 verify step.
- **Issue:** `docker --version` shows Docker Desktop 28.5.1 is installed, but the Linux engine pipe was unavailable when `docker compose build` was invoked (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`).
- **Fix:** Ran `docker compose config` instead, which fully validates `compose.yml` (service, ports, volume, healthcheck, env_file) without requiring the daemon. Syntax and resolved output were both correct.
- **Files modified:** none.
- **Verification:** `docker compose config` parses cleanly; `grep` spot-checks for `v1.58.0-noble`, `./data:/data`, and `apscheduler==3.11` all exit 0.
- **Committed in:** n/a — environment-only; image build should be re-run locally once Docker Desktop is started, and before first `docker compose up`.

**2. [Rule 3 — Blocking] Task 1 files were already committed in a prior mixed commit**
- **Found during:** Task 1 commit step.
- **Issue:** Commit `fb9410f feat(01-02): add two-layer log scrubber and logging setup` from an earlier execution had already staged `Dockerfile`, `compose.yml`, `.env.example`, `.gitignore`, `requirements.txt`, and `pyproject.toml`. My freshly written files byte-matched what was already on disk, so `git commit` produced "nothing to commit". No clean way to retroactively split the earlier mixed commit without destructive history rewriting.
- **Fix:** Left the existing files in place, recorded `fb9410f` as the Task 1 commit hash in this SUMMARY's Task Commits table, and documented the blending here. Tasks 2 and 3 were committed cleanly under the `feat(01-01): ...` prefix.
- **Files modified:** none (files were re-verified to match spec).
- **Verification:** `git diff HEAD -- Dockerfile compose.yml requirements.txt pyproject.toml .env.example .gitignore` returned empty.
- **Committed in:** `fb9410f` (pre-existing).

### Test-environment deviation

**3. [Rule 3 — Blocking] Local Python is 3.11.9, but pyproject requires >=3.12**
- **Found during:** Task 2 verify step (running pytest).
- **Issue:** Only Python 3.11.9 is installed on the host; pyproject declares `requires-python = ">=3.12"`. Pip cannot install the package under 3.11 if that floor is enforced.
- **Fix:** Installed the test dependencies directly via `pip install pydantic==2.12.0 pydantic-settings==2.13.1 cryptography==44.0.0 pytest pytest-asyncio sqlmodel sqlalchemy aiosqlite alembic` in a 3.11 venv, bypassing `pip install -e .`. The runtime Python version check only bites package install, not individual dependencies at these versions. Test suite runs green against 3.11.
- **Files modified:** none (pyproject floor kept at 3.12 because the production Docker image uses Playwright-noble Python 3.12+).
- **Verification:** `pytest tests/unit/test_config.py tests/unit/test_models.py -q` → 9 passed.
- **Committed in:** n/a — environment-only.

### Code-level additions

- `test_get_settings_is_cached` added to `test_config.py` beyond the three tests listed in the plan. Reason: the lru_cache identity is a contract other plans rely on and is worth pinning with an assertion.
- `test_rate_limit_counter_defaults` added to `test_models.py` beyond the four tests listed. Reason: the fourth table was only implicitly covered by `test_models_import_cleanly`; adding an explicit defaults test costs nothing and matches the shape of the other model tests.

---

**Total deviations:** 3 environment blockers (documented, not fixable in-scope) + 2 additive test cases (strict supersets of plan).
**Impact on plan:** Zero scope creep. The image has not been locally built, but the Dockerfile and compose.yml are syntactically valid and grep-verified against RESEARCH.md contracts; the first `docker compose up` in the next plan will exercise them end-to-end.

## Issues Encountered

- `pytest tests/unit -q` picked up a stray `tests/unit/test_log_scrubber.py` from the earlier 01-02 execution, which fails to collect because `structlog` is not in the test venv. Scoping the test run to `test_config.py + test_models.py` sidestepped the issue; the structlog-dependent tests will pass once the full Phase 1 venv is assembled.

## User Setup Required

None — plan 01-01 is pure scaffolding. Before the first `docker compose up` the user must:

1. Copy `.env.example` → `.env`.
2. Generate and paste a Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
3. Start Docker Desktop (host-level requirement for the build).

These are the same steps already documented inside `.env.example` and the Dockerfile header.

## Next Phase Readiness

- **Ready:** 01-02 (FernetVault + log scrubber — already partially present on disk from a prior run) and 01-03 (scheduler) can both proceed in parallel. They import `app.config.get_settings`, `app.db.base.async_session`, and `app.db.base.mark_orphans_failed`, all of which are now committed.
- **Concerns:**
  - `fb9410f` bundles 01-01 and 01-02 code in a single commit. Future `git log --grep=01-01` searches will under-count this plan's work by one commit. Consider noting this in STATE.md so the phase-complete check understands the blend.
  - Docker image has not yet been built on this host. Running `docker compose build` before 01-03 lands is recommended so the `--workers 1` CMD and Playwright base are exercised end-to-end.
  - Production target is Python 3.12 (per pyproject and the Playwright base image). The local venv used for running tests is 3.11.9; results should be re-validated inside the container at least once during Phase 1.

## Self-Check: PASSED

All files listed in `key-files.created` exist on disk. Commits `191e827` and `3cd7ef8` exist in `git log`; `fb9410f` exists in `git log` and byte-matches the Task 1 specification (verified via `git diff HEAD -- ...` returning empty).

---
*Phase: 01-foundation-scheduler-safety-envelope*
*Completed: 2026-04-11*
