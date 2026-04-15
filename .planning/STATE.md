# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** Given a base resume + keywords, the app gets your tailored application in front of every matching job posting — with zero manual effort after setup.
**Current focus:** Phase 5 (Email Submission / Review Queue) — Wave 1 in progress

## Current Position

Phase: 5 of 6 (Email Submission, Review Queue, Manual Apply & Notifications)
Plan: 05-01 of 7 in current phase (Wave 1 schema foundation complete)
Status: In progress
Last activity: 2026-04-15 — Completed 05-01-PLAN.md (submissions + failure_suppressions tables, partial UNIQUE index, 4 new Settings columns, canonical job state machine; 216/216 green)

Progress: [███████████░] ~80% (24 of 30 plans complete: Phases 1-4 + 05-01) — Phase 5 opened

## Performance Metrics

**Velocity:**
- Total plans completed: 23
- Average duration: ~13 min
- Total execution time: ~5h 12min

**By Phase:**

| Phase | Plans | Total    | Avg/Plan |
|-------|-------|----------|----------|
| 01    | 5     | ~174 min | ~35 min  |
| 02    | 4     | ~23 min  | ~6 min   |
| 03    | 6     | ~32 min  | ~5 min   |
| 04    | 7     | ~78 min  | ~11 min  |

**Recent Trend:**
- Last 5 plans: 04-03 (~5 min) | 04-04 (~7 min) | 04-05 (~32 min, 3 deviations) | 04-06 (~8 min, 2 minor deviations, 175 tests green) | 04-07 (~12 min, 0 deviations, 216 tests green)
- Trend: 04-07 (Wave 5 phase-closing tests) landed cleanly with no deviations. 41 new tests (1,167 lines) covering TAIL-01..09 + SAFE-04 using FakeLLMProvider. 216/216 green. Phase 4 is now feature-complete and fully tested — ready for Phase 5.

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- 05-01: Partial UNIQUE index MUST use `op.create_index(..., sqlite_where=sa.text(...))` — `UniqueConstraint(..., sqlite_where=...)` silently drops the WHERE clause on SQLite (research Pitfall 9). Applied to `ux_submissions_job_sent` (SC-7 idempotency).
- 05-01: CANONICAL_JOB_STATUSES is a 13-element frozenset in `app.review.states`; enforcement is service-layer only (Job.status stays a plain str column, mirroring CANONICAL_FAILURE_REASONS precedent). `assert_valid_transition(current, target)` is the uniform gate before any Phase 5 Job.status write.
- 05-01: Legacy `applied` status kept in CANONICAL_JOB_STATUSES as a terminal (no outgoing transitions) — zero-churn Phase 3 back-compat, avoids retroactive row rewriting.
- 05-01: `Settings.notification_email` nullable — NULL means "resolve to smtp_user at send time" so users are not forced to configure a second inbox upfront. Downstream plans need a resolver helper.
- 05-01: `Settings.base_url` default `http://localhost:8000` — LAN-first; operator overrides via Settings UI when exposing beyond localhost. Used to build review-page links in notification emails.
- 05-01: `Submission.submitter` column ships now with values `email | playwright` so Phase 6 Playwright lands without a schema bump.
- 05-01: New feature packages (`app.submission`, `app.review`) register with Alembic metadata via import side-effect at the bottom of `app/db/models.py` (mirrors Phase 3 discovery / Phase 4 tailoring pattern).
- 05-01: Python `Settings` SQLModel class mirrors the four new columns at field-declaration level (not just the migration) — SQLModel attribute access requires the Python-side fields and catching this in Task 2 avoids AttributeError in every downstream Phase 5 consumer.
- 04-07: FakeLLMProvider is a local test class (not a shared conftest fixture) — Phase 4 is its only consumer and local definition keeps the test surface legible
- 04-07: Base resume DOCX fixture built via python-docx in a pytest helper rather than checked into the repo — fully deterministic, version-tracked as code
- 04-07: SC-5 cache-token-visibility test asserts against the template file via read_text+substring checks rather than rendering through Jinja2 — avoids needing a full Jinja env + dummy context
- 04-07: SC-2 end-to-end invented-skill test scripts 6 FakeLLMProvider responses (tailor/validate × 3) to exercise the full retry+escalation loop and prove success=False at max_retries
- 04-07: SAFE-04 PII-in-prompt test flattens every recorded provider call (system blocks + messages) into one blob and greps for literal name/email/phone — strictest possible assertion
- 04-07: Service-layer tests use the async_session conftest fixture directly rather than live_app because they only need DB state, not HTTP surface
- 04-07: Job fixtures in Phase 4 tests must include external_id='ext-N' (NOT NULL constraint); Phase 3 tests implicitly satisfied this via real ATS payloads
- 04-07: resume_artifact_path test normalises to forward slashes before asserting '42/v1.docx' so it passes on Windows and Linux
- 04-06: Tailoring detail view recomputes keyword_coverage on each render via compute_keyword_coverage — TailoringRecord has no keyword_coverage column so the value is derived from (tailored_docx_text, job.description) at render time
- 04-06: Detail-view diff shim re-extracts the tailored DOCX and reshapes into {sections:[{heading,content}]} — the engine's tailored_sections JSON is not persisted, so the diff rebuilds input from the artifact (line-level diff still highlights bullet changes correctly)
- 04-06: Cache savings pricing constants (_INPUT_PRICE_PER_MTOK=3.00, _CACHE_READ_PRICE_PER_MTOK=0.30) inlined in tailoring router rather than re-exported from BudgetGuard.PRICING to avoid UI↔budget import coupling — marked must-stay-in-sync
- 04-06: /settings/tailoring POST rejects values outside {light, balanced, full} with HTTP 400 so the pipeline (04-05) can trust Settings.tailoring_intensity without defensive normalisation
- 04-06: 80% budget warning banner is dismissible via POST /dismiss-budget-warning (client-only swap=delete, no cookie); 100% halt banner is non-dismissible and links to Settings > Budget
- 04-06: Dashboard budget widget reads Settings row for cap/spent/month as source of truth and augments with CostLedger get_monthly_cost_summary for the per-call-type breakdown — two different sources because the Settings row is the authoritative budget counter BudgetGuard debits, while CostLedger is the audit trail
- 04-06: Tailoring sidebar entry placed immediately after Budget (Credentials already sits above Budget in existing order, so the plan's "before Credentials" was not literally achievable without reordering unrelated items)
- 04-06: Detail route swallows preview/diff/ATS exceptions at warning level so a broken or missing DOCX never 500s the review page
- 04-05: Queued jobs = status='matched' from discovery; ordered score DESC so budget-constrained runs tailor the best matches first
- 04-05: get_next_version counts ALL existing records (any status) so retries get a fresh version number rather than reusing a failed slot
- 04-05: save_tailoring_record flushes (not commits) so callers can group record + cost entries + debit into one transaction
- 04-05: prompt_hash = SHA256(system_prompt | resume_text | job_description) with 0x1E separator between fields
- 04-05: save_cost_entries re-estimates cost per row via BudgetGuard.estimate_cost — ledger sums stay aligned with the budget counter using one source of truth
- 04-05: Budget halt at 100% BREAKS the per-job loop; remaining jobs stay 'matched' for next run — no partial-retry in the pipeline layer
- 04-05: Rejected records ALSO write CostLedger entries and debit BudgetGuard because tokens were consumed; engine-exception records do NOT (no result to bill)
- 04-05: DOCX write failures still debit (tokens were consumed) but flip job to 'failed'; cover letter write failures are non-fatal (resume saved, status='tailored')
- 04-05: run_tailoring lazy-imported inside SchedulerService._execute_pipeline to keep the scheduler's static import graph minimal under test reload cycles
- 04-05: Base resume path resolved via inlined Path(get_settings().data_dir) / 'resumes' / 'base_resume.docx' instead of app.resume.service.get_resume_path — avoids stale LRU cache hits after importlib.reload(app.config) in integration tests
- 04-05: run_tailoring wraps get_settings() in try/except so late APScheduler firings during pytest monkeypatch teardown log skipped_no_resume instead of propagating ValidationError
- 04-04: DOCX replacement goes through replace_paragraph_text_preserving_format exclusively — paragraph.text setter is only used in the no-runs fallback branch (research Pitfall 1 enforced in code)
- 04-04: Section overflow drops excess tailored bullets with a warning log rather than cloning paragraph XML; underflow clears extras instead of deleting them so spacing stays stable
- 04-04: Work-experience subsection matching uses a fixed 2-line skip after the company header (title + dates) before collecting bullets — heuristic, not style-parsed, because python-docx has no semantic bullet notion
- 04-04: check_ats_friendly returns keyword_coverage=None; compute_keyword_coverage is a separate function so ATS audits can run without a job description in scope
- 04-04: Cover letter font is auto-detected from the base resume's first run, falling back to Calibri — only affects the cover letter, resume template is untouched
- 04-04: format_diff_html emits a scoped <style> prelude so <ins>/<del> colour themselves without requiring the review-queue template to ship matching CSS — the fragment is fully self-contained
- 04-04: generate_section_diff appends tailored-only sections at the end (not interleaved) with empty base_text; interleaving would need base-order tracking that extract_resume_text does not expose
- 04-03: TAILORING_SYSTEM_PROMPT is one monolithic constant — easier prompt-injection review and cleaner prompt caching than fragment assembly
- 04-03: Temperature schedule pinned in engine: validator 0.1, tailoring 0.3, cover letter 0.4 — codified once so consumers cannot drift
- 04-03: get_escalated_prompt_suffix escalates only the tailoring prompt on retries; validator strictness stays constant (research Pitfall 4)
- 04-03: strip_pii_sections drops ANY section matching contact-hint keywords (contact/info/personal/details/profile), not just section 0 — handles mid-document contact blocks
- 04-03: Regex email/phone redaction runs AFTER heading-based stripping as belt-and-braces for stray PII embedded in non-contact sections
- 04-03: TailoringResult.retry_count is 1-indexed (retry+1) — 'how many attempts did this take', not 'loop index we stopped at'
- 04-03: Cover letter failures are NON-fatal — a validated tailored resume is not discarded because the cover letter JSON was malformed; success=True with a warning
- 04-03: validate_output returns (passed, violations, LLMResponse) as a 3-tuple so validator tokens flow into the same per-call ledger as tailoring tokens
- 04-03: parse_tailoring_response only validates sections is a list, not strict per-section schema — resume structure varies too much; DOCX writer (04-04) handles mapping
- 04-03: Violations from earlier retries preserved in validation_warnings even when a later retry passes — review queue shows the full 'what did we catch and fix' history per CONTEXT.md trust-building requirement
- 04-03: Cache_control breakpoint placed AFTER base resume (not after instructions) so prompt caching hits on sequential jobs — minimum-token threshold requires enough content before the breakpoint
- 04-02: LLMProvider is a runtime_checkable Protocol; AnthropicProvider lazy-imports AsyncAnthropic inside __init__ so the file loads even when anthropic isn't installed yet
- 04-02: get_provider resolves anthropic_api_key through FernetVault.from_env (same pattern as SMTP / ATS credentials) — never reads ANTHROPIC_API_KEY from env directly
- 04-02: LLMResponse keeps input/output/cache_creation/cache_read tokens as four separate ints so BudgetGuard can price cached calls at the correct per-bucket rate
- 04-02: BudgetGuard.PRICING is class-level; unknown models fall back to claude-sonnet-4-5 rates rather than raising KeyError (mis-estimation recoverable, crash is not)
- 04-02: budget_cap_dollars == 0 means "unlimited" (the default singleton value); users who want a zero-spend halt set kill_switch instead
- 04-02: Month rollover runs inline inside check_budget on first call of a new month — no separate APScheduler cron job
- 04-02: debit serializes through a per-instance asyncio.Lock and writes Settings increment + CostLedger row in one transaction (research Pitfall 6)
- 04-02: BudgetGuard must be a singleton per process because the asyncio.Lock lives on the instance — Plan 04-04 owns construction
- 04-02: CostLedger imported locally inside debit() so app.tailoring.budget stays importable during Wave 1 parallel execution with 04-01
- 04-01: tailoring_records.version is integer counter (v1, v2, …) matching versioned artifact paths data/resumes/{job_id}/v{N}.docx
- 04-01: cost_ledger.tailoring_record_id nullable so orphan validator/probe calls can still be logged for budget
- 04-01: cost_ledger.month is denormalised string (YYYY-MM) indexed for cheap SUM-based budget queries (no strftime in hot path)
- 04-01: validation_warnings stored as JSON string in VARCHAR column — portable SQLite migration, consumers json.loads on read
- 04-01: Phase 4 models live under app/tailoring/, re-exported from app/db/models.py (mirrors Phase 3 app/discovery/ convention)
- 04-01: Settings alter uses plain op.add_column (matches existing 0002 pattern, not batch_alter_table as plan suggested)
- 04-01: Migration revision slug is 0004_phase4_tailoring (not bare 0004) to match existing chain convention
- 03-06: Pipeline _parse_posted_date converts ISO strings from ATS APIs to datetime objects (was crashing SQLite)
- 03-04: Sort defaults to score desc (highest matches first)
- 03-04: 500-job limit on list query (reasonable ceiling for single-user app)
- 03-04: Case-insensitive keyword matching for breakdown display
- 03-04: Queue button only shown for discovered + below-threshold jobs
- 03-02: detect_source returns (slug, source_type) tuple to match existing sources router contract
- 03-02: validate_source returns (bool, str) tuple for router compatibility
- 03-02: _execute_pipeline stores counts via self._last_counts; wrapper passes to finalize_run to avoid double-finalize
- 03-02: Pipeline uses separate session scopes for load, fetch-status-update, persist, stats, anomaly phases
- 03-05: Anomaly dismiss uses cookie (dismissed_anomaly_run_id) keyed on run_id -- no DB schema change
- 03-05: Discovery summary queries DiscoveryRunStats joined with Source, not Run.counts JSON
- 03-05: POST /dismiss-anomaly returns empty HTML for hx-swap=delete pattern
- 03-03: Sources router uses _render_sources helper following _render_section pattern from settings.py
- 03-03: Toggle endpoint returns empty 200 with HX-Reswap none header (no DOM update needed)
- 03-03: Unknown source type triggers probe of all three ATS APIs sequentially
- 03-03: Sources section positioned after Keywords in sidebar ordering
- 03-01: Discovery models live in app/discovery/models.py, imported into app/db/models.py for Alembic metadata registration
- 03-01: Job.fingerprint is SHA256, unique-indexed for O(1) dedup lookups
- 03-01: posted_date nullable (Lever public API lacks this field)
- 03-01: description and description_html stored separately (plain text for scoring, HTML for display)
- 03-01: DiscoveryRunStats tracks per-source per-run counts for anomaly detection rolling averages
- 02-02: Profile fields normalise empty strings to None; phone strips non-digits
- 02-02: Resume stored as single file base_resume.docx, replaced on re-upload (no versioning)
- 02-02: DOCX text extraction splits on Heading styles; full_text capped at 500 lines
- 02-02: Dedicated GET routes for profile/resume declared before generic catch-all for correct FastAPI routing
- 02-03: Keywords use {keyword:path} path param in DELETE route for URL-encoded special chars
- 02-03: Schedule checkbox parsed via raw form data (same pattern as safety toggles) — missing = False
- 02-03: Budget progress bar calculated server-side in Jinja2 — no client JS needed for bar rendering
- 02-03: _render_section enriches context per-section (keywords list parsing from pipe-delimited CSV)
- 02-04: Save-first-validate-second pattern for credentials — encrypt+persist before async validation so network failures never prevent storage
- 02-04: Credentials section never pre-fills inputs or shows masked values — always empty fields with Configured/Not set status
- 02-04: SMTP validation runs synchronously via asyncio.to_thread to avoid blocking event loop
- 02-04: _upsert_secret helper DRYs Secret row upsert for credential routes
- 02-01: Settings page uses sidebar shell with HTMX section loading; each section is a partial loaded via hx-get
- 02-01: POST /settings/limits returns partial HTML (not 303 redirect) for HTMX sidebar consistency
- 02-01: Safety toggles accessible from both dashboard (/toggles) and settings sidebar (/settings/safety)
- 02-01: Placeholder partials for unimplemented sections prevent 404 errors during sidebar navigation
- 01-05: Wizard writes wizard_complete only on step 3 or skip — going back and forth does not flip the flag
- 01-05: Wizard step 2 allows blank submissions (guidance, not a gate per CONTEXT.md)
- 01-05: Rotation banner does not delete unreadable secrets — preserved for forensic recovery
- 01-05: End-to-end tests run against the real lifespan with tmp_path data dirs, not mocks
- 01-05: Reload wizard module in test fixtures to avoid stale get_settings reference from importlib.reload(app.config)
- 01-04: Pico.css v2 bundled local (83KB), HTMX 2.0.3 via unpkg CDN, no build step
- 01-04: HTMX fragments served from the same routers as full pages, sharing one `_common_ctx` builder so polled fragments never drift from initial render
- 01-04: `_humanize_seconds` runs server-side — no client-side JS timers
- 01-04: `/settings/limits` mutates `app.state.rate_limiter.{daily_cap,delay_min,delay_max,tz}` in-place so changes take effect without restart
- 01-04: Starlette 1.0 `TemplateResponse(request, name, ctx)` positional form required — kwarg `{"request": request}` breaks Jinja LRU cache (unhashable dict)
- 01-04: `get_session` dependency lazy-imports `async_session` inside the generator body so integration tests that reload `app.db.base` get the freshly bound engine
- 01-04: Secrets CRUD routes `vault.encrypt` auto-registers plaintext with `SecretRegistry` BEFORE DB commit — scrubber armed at the same point as the write
- 01-04: Runs show-more uses `hx-swap="outerHTML"` on a load-more `<tr>` (self-replacing) rather than `beforeend` on tbody — cleaner button lifecycle
- 01-04: `/settings/limits` validation mirrors `RateLimiter.__init__` bounds exactly, keeping DB state guaranteed-startable
- 01-04: POST `/runs/trigger` is fire-and-forget via `asyncio.create_task(svc.run_pipeline)` — HTTP returns fast, pipeline runs on same event loop
- Roadmap: Safe-channel-first ordering (GH/Lever/Ashby + email before Playwright; LinkedIn/Indeed deferred to v1.x)
- Roadmap: Rate limiting (SAFE-01/02, DISC-07) ships in Phase 1 with the scheduler, not later
- Roadmap: Hallucination validator (TAIL-04) ships in the same phase as first LLM call (TAIL-01)
- Roadmap: Learning loop (LEARN-01..05) ships with Playwright (Phase 6), not earlier
- Roadmap: Manual paste-a-link (MANL-01..06) is first-class v1, landing in Phase 5
- 01-03: Phase 1 stub pipeline is a 50ms asyncio.sleep with killswitch checkpoints — Phases 2+ replace the body, not the wrapper
- 01-03: RunContext is a frozen dataclass passed as argument (explicit > implicit; ContextVar rejected)
- 01-03: Rate-limit counter is a dedicated table keyed by local-TZ ISO date string (cheap next-day insert)
- 01-03: Midnight reset runs as an APScheduler CronTrigger job, not an in-process timer
- 01-03: run_pipeline swallows CancelledError at its boundary after finalising the Run row — propagating would abort the APScheduler worker
- 01-03: Three-layer run-lock defense (asyncio.Lock + max_instances=1 + DB sentinel Run row)
- 01-03: set_scheduler_service module-level setter bridges APScheduler function-call invocation with lifespan-scoped state
- 01-03: app.runs.service.mark_orphans_failed supersedes earlier placeholder in app.db.base (session-scoped, returns rowcount)
- 01-03: Integration tests drive lifespan via app.router.lifespan_context(app) — httpx 0.28 dropped ASGITransport(lifespan='on')
- 01-03: freezegun abandoned for midnight-reset integration test (hangs async runner on Windows); replaced with monkeypatched today_local
- 01-02: SecretRegistry is a module-level singleton with threading.Lock (FastAPI + APScheduler share state)
- 01-02: structlog scrub processor precedes JSONRenderer (scrub typed values, not rendered strings)
- 01-02: 4-char minimum on literal registration to prevent common-word redaction soup
- 01-02: FernetVault auto-registers plaintext on encrypt (pre), decrypt (post), and from_env (master key)
- 01-02: InvalidToken collapses into InvalidFernetKey with a "may have changed" message
- 01-01: APScheduler pinned at 3.11.x (not 4.x alpha); Playwright 1.58.0-noble base shipped now to avoid mid-project rebuild
- 01-01: Single ./data host bind mount holds SQLite, logs, uploads, browser state
- 01-01: SQLite WAL mode enabled in init_db() so HTMX polls never block scheduler writes
- 01-01: get_settings() lru-cached entrypoint (not module-level `settings`) for test-fixture override
- 01-01: Alembic include_object hook excludes apscheduler_* tables from target_metadata
- 01-01: Fail-fast config — Fernet(key) instantiated inside pydantic field_validator at construction time
- 01-01: Hand-authored baseline migration 0001_initial (not autogenerated) because async engine setup complicates autogenerate

### Pending Todos

None.

### Blockers/Concerns

- REQUIREMENTS.md summary says "58 total v1 requirements" but the enumerated list contains 65. Discrepancy flagged in ROADMAP.md Coverage section; correct during Phase 2 planning.
- Phase 4 needs a prompt-design spike (extractive tailoring) before full pipeline integration, per research SUMMARY.md.
- Phase 6 generic-ATS form matching may need a selector-stability spike before implementation.
- 01-01: Docker image has not been built on this host (Docker Desktop daemon was not running during execution). `docker compose config` validated the compose file; first `docker compose build` still pending.
- 01-01: Local test venv is Python 3.11.9 but pyproject requires >=3.12. Tests run green on 3.11 against pinned deps; production (Playwright base) uses 3.12+. Re-validate inside the container during Phase 2.
- 01-03: requirements.txt should be split into prod vs dev — freezegun + pytest-asyncio were installed into .venv for tests but are NOT in requirements.txt. Non-blocking; flag as Phase 2 cleanup.
- 01-03: `app.db.base._settings = get_settings()` executes at module import time, so integration tests that need a different DATA_DIR must reload `app.config` and `app.db.base` before importing `app.main`. Future plans should consider refactoring to lazy-init inside `init_db()`. **Partially mitigated in 01-04/01-05**: `get_session` dependency now lazy-imports `async_session`; wizard module must also be reloaded alongside `app.config` in test fixtures.
- 01-04: HTMX is loaded from `unpkg.com/htmx.org@2.0.3` via CDN. Fully offline LAN deployments will render the dashboard but not poll. Consider bundling htmx.min.js locally (trivial, ~47KB, same pattern as `pico.min.css`) in a later cleanup plan.
- 01-04: POST `/runs/trigger` has no CSRF protection. LAN-bound + "no auth in v1" makes this acceptable; revisit if the app is ever exposed to a wider network.
- 04-02: BudgetGuard instance lifecycle — asyncio.Lock is per-instance, so Plan 04-04 must instantiate exactly one BudgetGuard and pass it to every tailoring consumer (validator calls and cover-letter calls must debit through the same instance).
- 04-02: Anthropic SDK streaming vs. non-streaming not yet decided. Current AnthropicProvider.complete assumes non-streaming (simpler for validator + DOCX rewrite that need the full text). Revisit during 04-03 if prompt design requires streaming.
- 04-05: **`app.resume.service` module-level `from app.config import get_settings` binding is a latent fragility.** It captures the get_settings function object at first import, so any module-level reload of `app.config` (as the integration-test `live_app` fixture does) leaves `app.resume.service` holding a stale reference with a stale LRU cache. Any future code path that calls `get_resume_path()` or `save_resume()` from a pipeline stage must route through a lazy `get_settings()` import (the way `run_tailoring` now does) OR refactor `_resume_dir()` to call `app.config.get_settings()` lazily. Cleanup plan: refactor `app.resume.service._resume_dir()` to `return Path(__import__("app.config", fromlist=["get_settings"]).get_settings().data_dir) / "resumes"` or similar — a single-line change that eliminates the binding hazard.
- 04-05: APScheduler teardown race — late pipeline firings during pytest monkeypatch teardown can still propagate exceptions up the stack. `run_tailoring` is defensive, but `run_discovery` and `run_pipeline` itself are not. Non-blocking for now; flag if more pipeline stages land in Phase 5.
- 04-05: BudgetGuard instance lifecycle — `run_tailoring` currently constructs a fresh `BudgetGuard()` per stage invocation. Safe today (asyncio.Lock is per-instance; each `_execute_pipeline` owns exactly one), but if a future stage needs cross-call concurrency (parallel tailoring inside one run) the BudgetGuard should be promoted to a `SchedulerService` attribute initialised at lifespan. Flag for 04-07.

## Session Continuity

Last session: 2026-04-15
Stopped at: Completed 05-01-PLAN.md (Wave 1 schema foundation). Alembic 0005_phase5_submission ships submissions + failure_suppressions tables plus four new Settings columns (notification_email, base_url, submissions_paused, auto_holdout_margin_pct). Partial UNIQUE index `ux_submissions_job_sent` (WHERE status='sent') verified real via sqlite_master inspection AND proven by IntegrityError on duplicate-sent insert. `app.review.states` ships a 13-element CANONICAL_JOB_STATUSES frozenset plus assert_valid_transition() service-layer validator; illegal transitions like submitted->matched raise ValueError. New `app.submission` and `app.review` packages register with Alembic metadata via import side-effect at the bottom of `app/db/models.py`. Python Settings SQLModel class mirrors the four new migration columns. Downgrade/upgrade roundtrip clean. 216/216 suite green (no regressions). Two atomic commits: 47c88c2 (Task 1: models + state frozenset) and 47f3ab3 (Task 2: migration + Settings field additions). Zero deviations. Note: a parallel wave-1 plan 05-02 landed commit 6c38d70 between my two commits (email builder primitives + aiosmtplib dep) — non-overlapping, both waves integrate cleanly. Phase 5 Wave 1 schema is now stable; Wave 2 plans (submitter, pipeline, review UI, notifications) can run in parallel against the tables.
Resume file: None
