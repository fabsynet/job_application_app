# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** Given a base resume + keywords, the app gets your tailored application in front of every matching job posting — with zero manual effort after setup.
**Current focus:** Phase 2 complete. Ready for Phase 3 — Discovery & Matching

## Current Position

Phase: 2 of 6 (Configuration, Profile & Resume Upload)
Plan: 5 of 5 in current phase (02-01, 02-02, 02-03, 02-04, 02-05 done)
Status: Phase complete
Last activity: 2026-04-12 — Completed 02-05-PLAN.md (integration tests for all CONF requirements)

Progress: [█████░░░░░] 50% (Phase 1 + Phase 2 complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: ~22 min
- Total execution time: ~3h 17min

**By Phase:**

| Phase | Plans | Total    | Avg/Plan |
|-------|-------|----------|----------|
| 01    | 5     | ~174 min | ~35 min  |
| 02    | 4     | ~23 min  | ~6 min   |

**Recent Trend:**
- Last 5 plans: 01-05 (~30 min, 3 tasks, 19 new tests green, 87 total) | 02-01 (~5 min, 2 tasks, 87 tests green) | 02-04 (~3 min, 2 tasks, 87 tests green) | 02-03 (~7 min, 2 tasks, 87 tests green) | 02-02 (~8 min, 2 tasks, 87 tests green)
- Trend: 02-02 profile + resume upload with DOCX extraction, no new tests needed

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

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

## Session Continuity

Last session: 2026-04-12
Stopped at: Completed 02-02-PLAN.md. Profile form with 10 fields across 3 collapsible groups + DOCX resume upload with drag-and-drop and structured text preview. All 87 tests green. 02-01, 02-03, 02-04 also complete.
Resume file: None
