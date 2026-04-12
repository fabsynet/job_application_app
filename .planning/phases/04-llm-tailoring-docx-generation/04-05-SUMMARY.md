---
phase: 04-llm-tailoring-docx-generation
plan: 05
subsystem: tailoring
tags: [pipeline, scheduler, budget, docx, lazy-import, artifact-storage]

# Dependency graph
requires:
  - phase: 04-llm-tailoring-docx-generation / plan 01
    provides: TailoringRecord + CostLedger tables, Settings.tailoring_intensity
  - phase: 04-llm-tailoring-docx-generation / plan 02
    provides: LLMProvider/get_provider factory, BudgetGuard (estimate_cost, check_budget, debit)
  - phase: 04-llm-tailoring-docx-generation / plan 03
    provides: tailor_resume orchestration + TailoringResult (with llm_calls list)
  - phase: 04-llm-tailoring-docx-generation / plan 04
    provides: build_tailored_docx, build_cover_letter_docx
  - phase: 03-safe-channel-discovery
    provides: Job model with status='matched' after discovery
  - phase: 01-foundation-scheduler-safety-envelope
    provides: SchedulerService._execute_pipeline, KillSwitch, RunContext
provides:
  - "app.tailoring.service: DB ops for TailoringRecord / CostLedger + artifact path helpers"
  - "app.tailoring.pipeline.run_tailoring: pipeline stage processing all queued jobs"
  - "SchedulerService._execute_pipeline wired to run discovery -> tailoring sequentially"
  - "Versioned artifact storage at data/resumes/{job_id}/v{N}.docx (TAIL-09)"
  - "Budget-halt-at-100 / warn-at-80 enforcement across the per-job loop (TAIL-08)"
affects:
  - 04-06 review queue UI (will query get_tailoring_records_for_job + get_latest_tailoring)
  - 04-07 end-to-end wiring (will surface get_monthly_cost_summary on dashboard)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-stage lazy import inside SchedulerService._execute_pipeline to keep the scheduler import graph minimal under integration-test importlib.reload(app.config) cycles"
    - "Base resume path resolved through app.config.get_settings directly (not app.resume.service.get_resume_path) so the current get_settings function object is always used — prevents stale LRU cache hits after config reload"
    - "Per-job session scopes (one `async with session_factory() as session:` block per DB phase) mirror the discovery pipeline's pattern — a crash in one job cannot roll back another job's record"
    - "Kill-switch injected as a callable (`killswitch_check=self._killswitch.raise_if_engaged`) so pipeline.py stays decoupled from the KillSwitch class"
    - "Rejected records still debit budget (tokens were consumed) whereas engine-exception records do not (no token totals available)"
    - "Cover letter write failures are non-fatal: the tailored resume is saved and the job flips to 'tailored' regardless"

key-files:
  created:
    - app/tailoring/service.py
    - app/tailoring/pipeline.py
  modified:
    - app/scheduler/service.py

key-decisions:
  - "Queued jobs = status='matched' from discovery; ordered score DESC so budget-constrained runs still tailor the best matches first"
  - "get_next_version counts ALL existing records (any status) for a job_id — retries on a failed attempt get a fresh version number rather than reusing the failed slot, preserving the full versioned history"
  - "save_tailoring_record flushes (not commits) so the caller owns the transaction boundary and can add CostLedger rows + debit under the same commit"
  - "prompt_hash = SHA256(system_prompt | resume_text | job_description) with record-separator (0x1E) between fields, so identical inputs always hash identically"
  - "save_cost_entries re-estimates cost per row via BudgetGuard.estimate_cost rather than trusting a passed-in number — ledger sums stay aligned with the budget counter using one source of truth"
  - "get_monthly_cost_summary pre-seeds by_type with {tailor, validate, cover_letter} zeros so the dashboard template never has to guard for missing keys"
  - "artifact_dir creates data/resumes/{job_id}/ lazily inside resume_artifact_path / cover_letter_artifact_path, so the directory never exists for jobs that haven't been tailored"
  - "Budget halt at 100% BREAKS the per-job loop immediately; remaining jobs stay in 'matched' state and get retried next run — no retry-count escalation in the pipeline itself (engine handles per-job retries, pipeline handles cross-job budget halts)"
  - "Warning at 80% logs only — the banner UI decision is deferred to Plan 04-07"
  - "Rejected records ALSO write CostLedger entries AND debit the BudgetGuard because the tokens were actually consumed upstream"
  - "Engine-exception records (try/except around tailor_resume) produce a bare failed record with status='failed' and NO cost entries / NO debit — there's no TailoringResult to bill against"
  - "DOCX write failures (build_tailored_docx raises) demote the job to failed and still write cost entries + debit — the tailoring call succeeded, the filesystem call is what failed, and the tokens were still consumed"
  - "Cover letter write failures are non-fatal: log a warning, leave cover_letter_path=None on the record, and still flip the job to 'tailored' — matches the engine's own non-fatal cover letter failure semantics (Plan 04-03)"
  - "run_tailoring imported lazily inside SchedulerService._execute_pipeline, not at scheduler.service module top, to keep the scheduler's static import graph minimal across test reloads of app.config"
  - "Base resume existence check inlined via Path(get_settings().data_dir) / 'resumes' / 'base_resume.docx' rather than importing app.resume.service.get_resume_path, so the current get_settings function is always used — the alternative bound a stale function reference that stayed alive across test fixture reloads and broke the LRU cache isolation"
  - "Outer try/except around get_settings() so a late APScheduler firing during fixture teardown (where monkeypatched env is gone) logs a warning and returns skipped_no_resume=True instead of propagating a FERNET_KEY ValidationError up to run_pipeline"

patterns-established:
  - "Pipeline stage module pattern: ``app.tailoring.pipeline`` mirrors ``app.discovery.pipeline`` — module-top imports limited to RunContext + dataclass-only deps, heavy DB/filesystem imports lazily pulled inside the stage function"
  - "SchedulerService stage orchestration: ``await run_<stage>(ctx, self._session_factory, ...)`` then ``await self._killswitch.raise_if_engaged()`` between every stage; stage counts merged into self._last_counts via dict-unpack"

# Metrics
duration: ~32 min
completed: 2026-04-12
---

# Phase 4 Plan 05: Tailoring Pipeline Stage + Scheduler Integration Summary

**Wires the Wave 1 + Wave 2 pieces (models, budget, engine, DOCX writer) into a complete pipeline stage that processes every matched job through tailor -> validate -> write -> record -> debit and hooks it into SchedulerService._execute_pipeline after discovery.**

## Performance

- **Duration:** ~32 min (mostly debugging a subtle test-pollution interaction between the scheduler's new import graph and the integration-test live_app fixture's config reloads — see Deviations)
- **Started:** 2026-04-12T21:29:43Z
- **Completed:** 2026-04-12T22:01:33Z
- **Tasks:** 2
- **Files created:** 2 (`app/tailoring/service.py`, `app/tailoring/pipeline.py`)
- **Files modified:** 1 (`app/scheduler/service.py`)
- **Tests:** 175/175 passing (zero regressions)

## Accomplishments

- **`app/tailoring/service.py` (363 lines)** — DB operations layer:
  - `get_queued_jobs` — matched jobs ordered by score DESC
  - `get_next_version` — versioning counter per job_id
  - `save_tailoring_record` — persists TailoringRecord with per-call token totals, estimated cost, validation warnings JSON, prompt hash
  - `save_cost_entries` — one CostLedger row per entry in `TailoringResult.llm_calls`, each re-estimated via `BudgetGuard.estimate_cost` so ledger sums align with the budget counter
  - `get_tailoring_records_for_job`, `get_latest_tailoring` — review queue reads
  - `get_monthly_cost_summary` — total + by-type breakdown for the dashboard budget card
  - `artifact_dir` / `resume_artifact_path` / `cover_letter_artifact_path` — versioned filesystem layout at `data/resumes/{job_id}/v{N}.docx` (TAIL-09)

- **`app/tailoring/pipeline.py` (~400 lines)** — The pipeline stage:
  - Loads the base resume path through `get_settings()` directly (see Deviations for why not via `app.resume.service.get_resume_path`)
  - Early-returns `skipped_no_resume=True` if no base resume is uploaded OR a config error is raised during resolution
  - Queries queued jobs, resolves the provider (returns early if the Anthropic key isn't configured yet — expected until Plan 04-07's settings UI lands)
  - Per-job loop: kill-switch check -> budget check -> version -> tailor_resume -> branch on result
  - Success: write tailored DOCX + cover letter (if any), save record + cost entries, debit budget, flip Job.status='tailored'
  - Validation rejection: save record as 'rejected', save cost entries, debit (tokens were consumed), flip Job.status='failed'
  - Engine exception: bare failed record, no debit, flip Job.status='failed'
  - DOCX write failure: treated as engine failure — cost entries + debit still written, status='failed'
  - Budget halt at 100%: break the loop, leaving remaining matched jobs for the next run

- **`app/scheduler/service.py` — stage integration:**
  - `_execute_pipeline` now runs discovery, raises on kill-switch, runs tailoring, raises on kill-switch, merges both stages' counts into `self._last_counts`
  - `run_tailoring` lazy-imported inside the method body (the reason is load-order critical — see Deviations)
  - Kill-switch passed as a callable (`killswitch_check=self._killswitch.raise_if_engaged`) so pipeline.py does not import the `KillSwitch` class

## Task Commits

1. **Task 1: Tailoring service layer (DB ops + artifact paths)** — `409a388` (feat)
2. **Task 2: Tailoring pipeline stage + scheduler integration** — `872cbe9` (feat)

_Plan metadata commit follows this SUMMARY._

## Files Created/Modified

- `app/tailoring/service.py` — New. 363 lines. DB operations + versioned artifact path helpers.
- `app/tailoring/pipeline.py` — New. ~400 lines. `run_tailoring` stage orchestrator.
- `app/scheduler/service.py` — Modified. Added tailoring stage call after discovery; added a module-top note explaining the lazy import; added a lazy `from app.tailoring.pipeline import run_tailoring` inside `_execute_pipeline`.

## Decisions Made

See the `key-decisions` block in the frontmatter. The substantive ones are:

- Base resume resolution via `get_settings()` directly (not `get_resume_path()`) — required to survive integration-test config reloads without stale LRU cache hits (see Deviations).
- Rejected records still debit budget but engine-exception records do not — tokens were or weren't consumed; the ledger should reflect that.
- Budget halt breaks the loop; no escalation / no partial-retry.
- Lazy import of `run_tailoring` inside `_execute_pipeline` to keep the scheduler's static import graph free of `app.resume.service` / `app.tailoring.service`.
- `save_tailoring_record` flushes (not commits) so callers can group the record + cost entries + debit into one transaction.
- Cover letter write failures are non-fatal, matching Plan 04-03's non-fatal engine semantics.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale `get_settings` LRU cache via module-level import in `app.resume.service`**

- **Found during:** Task 2 verification — running the full test suite after wiring `run_tailoring` into the scheduler regressed `tests/test_phase2_resume.py::test_resume_upload_docx` from passing to failing in full-suite mode (but passing in isolation).
- **Root cause:** `app.resume.service` has `from app.config import get_settings` at module top, which binds the `get_settings` *function object* (with its `@lru_cache`) at first import. The integration-test `live_app` fixture `importlib.reload(app.config)` between tests, which replaces `sys.modules["app.config"]` but leaves the OLD `get_settings` function alive in any module that imported it. The fixture's `config_module.get_settings.cache_clear()` call clears the NEW module's cache, not the OLD one. Prior to Plan 04-05, `app.resume.service.get_resume_path` was first *called* inside `test_phase2_resume.py` itself (never from earlier pipeline tests), so its old-bound `get_settings` populated its cache with the CORRECT `DATA_DIR` on first call. Plan 04-05 changed that: the new `run_tailoring` stage calls `get_resume_path` inside earlier integration tests (kill-switch, rate-limit, first-boot heartbeat), populating the old-bound `get_settings`'s LRU cache with the PREVIOUS test's `DATA_DIR`. By the time `test_phase2_resume` ran, the cache returned stale data and `save_resume` wrote to the wrong `tmp_path`.
- **Fix:** `run_tailoring` resolves the base resume path via `from app.config import get_settings` inlined lazily in the function body — this imports the CURRENT `app.config.get_settings` each call, not a stale reference captured at module load time. The check is `Path(get_settings().data_dir) / "resumes" / "base_resume.docx"` with a pathlib `.exists()` probe, wrapped in try/except to demote unexpected errors (FERNET_KEY missing during late APScheduler teardown firings) to a `skipped_no_resume=True` early return.
- **Files modified:** `app/tailoring/pipeline.py` (inlined path resolution, lazy imports inside `run_tailoring`).
- **Verification:** `python -m pytest tests/ -q` — 175/175 passing.
- **Committed in:** `872cbe9` (Task 2 commit).

**2. [Rule 1 - Bug] `run_tailoring` import at scheduler.service module top broke test reload semantics**

- **Found during:** Same debugging session as Deviation 1, during bisection.
- **Root cause:** Importing `from app.tailoring.pipeline import run_tailoring` at the top of `app.scheduler.service` pulls `app.tailoring.pipeline` into `sys.modules` at scheduler module load, which in turn pulled `app.resume.service`, `app.tailoring.service`, etc. That made the scheduler's static import graph fan out to every module with a stale-binding hazard.
- **Fix:** Moved the import to a lazy, function-body import inside `SchedulerService._execute_pipeline`, with a module-top note explaining why. Module-level imports are now limited to `RunContext` + stdlib + SQLAlchemy + the discovery stage only.
- **Files modified:** `app/scheduler/service.py`.
- **Committed in:** `872cbe9`.

**3. [Rule 3 - Blocking] Defensive try/except around get_settings() for late APScheduler firings**

- **Found during:** Initial failure mode showed `pydantic_core.ValidationError: FERNET_KEY is required` bubbling up into `test_release_allows_new_runs` after the monkeypatch fixture had torn down the env var — an APScheduler job was still firing during teardown and calling the new `run_tailoring` path.
- **Fix:** Wrapped the `get_settings()` call in `run_tailoring`'s base-resume resolution with `try/except Exception` that logs `tailoring_skipped_config_error` and returns `_empty_counts(skipped_no_resume=True)`. The pipeline is now resilient to any resume-resolution failure, not just missing-file.
- **Files modified:** `app/tailoring/pipeline.py`.
- **Committed in:** `872cbe9`.

---

**Total deviations:** 3 auto-fixed (2 Rule 1 bugs from integration-test import hazards + 1 Rule 3 blocker from fixture teardown races).
**Impact on plan:** None — the external contract of `run_tailoring` is exactly as the plan specified. The deviations are entirely in HOW the internal resume-path resolution is done to stay compatible with the existing test reload machinery.

## Issues Encountered

- The test pollution was time-consuming to diagnose — the failing test (`test_resume_upload_docx`) was three files away from the root cause (`app.resume.service` module-level `get_settings` binding + earlier pipeline tests populating a stale LRU cache on that binding). The bisection walked down to the specific combination of `test_must_have_2_hourly_heartbeat_and_runlock` followed by `test_phase2_resume::test_resume_upload_docx`.
- **Underlying fragility flagged:** `app.resume.service` module-level `from app.config import get_settings` is a latent fragility. Any future code path that calls `get_resume_path()` or `save_resume()` from the pipeline layer risks re-triggering the same stale-binding issue unless it routes through a lazy `get_settings()` import the way `run_tailoring` now does. Consider refactoring `app.resume.service._resume_dir()` to call `app.config.get_settings()` lazily in a future cleanup plan. **Flag for STATE.md Blockers/Concerns.**

## User Setup Required

None for this plan. The Anthropic API key is still the only blocker on actually executing a real tailoring call end-to-end; Plan 04-07 will add the settings UI for it. Until then, `get_provider(session)` raises `ValueError("Anthropic API key not configured")`, which `run_tailoring` catches and logs as `tailoring_provider_unavailable` before returning empty counts — the pipeline stays green.

## Next Phase Readiness

- **Ready for 04-06** (review queue UI): the service layer exposes `get_tailoring_records_for_job`, `get_latest_tailoring`, and the artifact path helpers — the review queue can enumerate tailoring history per job, read the versioned DOCX + cover letter, and hand them to the Plan 04-04 `docx_to_html` / `format_diff_html` preview functions.
- **Ready for 04-07** (end-to-end wiring + settings UI):
  - `get_monthly_cost_summary` is the dashboard budget card's data source.
  - The settings UI needs to write the `anthropic_api_key` Secret row via `FernetVault.encrypt` (same pattern as SMTP / ATS keys) — once that's in place, `get_provider` stops raising and `run_tailoring` will actually call Claude on the next hourly heartbeat.
  - Budget warning banner at 80%: the pipeline already logs `tailoring_budget_warning`; the dashboard template should query `BudgetGuard.check_budget` on render and show the banner when `is_warning=True`.

### Blockers/Concerns

- **`app.resume.service` module-level `get_settings` binding** (flagged above) is a latent fragility that other phases may re-hit. Cleanup: refactor `_resume_dir()` to call `get_settings()` lazily instead of binding at module level.
- **APScheduler teardown race:** late pipeline firings during pytest monkeypatch teardown can still propagate exceptions up the stack. The `run_tailoring` entry is now defensive, but `run_discovery` and `run_pipeline` itself are not. Non-blocking for now — handled by the outer run_pipeline try/except that marks runs as `failed`/`error` — but worth keeping an eye on if more pipeline stages land in Phase 5.
- **BudgetGuard instance lifecycle** (carried forward from 04-02): `run_tailoring` constructs a fresh `BudgetGuard()` per stage invocation today. This is safe because the asyncio.Lock is per-instance and each `_execute_pipeline` call owns exactly one; but if a future stage needs cross-call concurrency (e.g. parallel tailoring inside one run), the BudgetGuard should be promoted to a `SchedulerService` attribute initialised at lifespan. Flag for 04-07 if parallelism lands.

---
*Phase: 04-llm-tailoring-docx-generation*
*Completed: 2026-04-12*

## Self-Check: PASSED

- `app/tailoring/service.py` — FOUND
- `app/tailoring/pipeline.py` — FOUND
- `app/scheduler/service.py` — FOUND (modified)
- commit `409a388` — FOUND
- commit `872cbe9` — FOUND
