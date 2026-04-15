---
phase: 05-email-submission-review-queue
plan: "05-06"
subsystem: manual_apply
tags: [manual_apply, paste_a_link, htmx, httpx, fastapi, jinja2, dedup]

# Dependency graph
requires:
  - phase: 03-job-discovery
    provides: detect_source + strip_html + job_fingerprint + get_job_by_fingerprint + Job model
  - phase: 05-email-submission-review-queue
    provides: 05-01 CANONICAL_JOB_STATUSES (matched status entry point) + 05-04 run_submission consumer for downstream
provides:
  - POST /manual-apply paste-a-link flow (MANL-01..06)
  - app.manual_apply.fetcher.fetch_and_parse with stable FetchError reasons
  - app.manual_apply.service.create_manual_job (idempotent, fingerprint-dedup, status=matched bypass)
  - 4 Jinja templates under app/web/templates/manual_apply/
  - 26 new tests (13 fetcher + 5 service + 8 router) — network-free via httpx.MockTransport + monkeypatched fetch_and_parse
affects: [manual_apply, web, review_queue, tailoring_pipeline, submission_pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "httpx.MockTransport for async fetch unit tests (no network in suite)"
    - "Router degrades FetchError to a fallback form fragment instead of returning 5xx"
    - "Idempotent manual-apply insert via canonical job_fingerprint (same hash Phase 3 discovery uses)"

key-files:
  created:
    - app/manual_apply/__init__.py
    - app/manual_apply/fetcher.py
    - app/manual_apply/service.py
    - app/web/routers/manual_apply.py
    - app/web/templates/manual_apply/index.html.j2
    - app/web/templates/manual_apply/_preview.html.j2
    - app/web/templates/manual_apply/_fallback.html.j2
    - app/web/templates/manual_apply/_result.html.j2
    - tests/manual_apply/__init__.py
    - tests/manual_apply/test_fetcher.py
    - tests/manual_apply/test_service.py
    - tests/manual_apply/test_router.py
  modified:
    - app/main.py
    - app/web/templates/base.html.j2

key-decisions:
  - "detect_source returns (slug, source_type) — plan snippet had the tuple flipped; fetcher unpacks slug first"
  - "FetchError reasons are a small stable vocabulary: not_found | auth_wall | timeout | empty_body | connect_failed | request_error | http_NNN | unexpected_error | empty_url | title_and_company_required"
  - "Empty URL (<200 chars after strip) treated as auth-wall — catches LinkedIn/Indeed SPA shells that 200 with a login prompt"
  - "Manual-apply jobs use score=100 + matched_keywords='manual_paste' as a stable sentinel so the Jobs list can visually distinguish manual from auto-discovered jobs"
  - "Idempotency: create_manual_job returns the existing Job when fingerprint matches rather than raising — router layer decides whether to surface 'Already in the queue' via check_duplicate as a read-before-write"
  - "Fallback path synthesizes a stable URL ('manual://<company>/<title>') when the user has no URL at all, so the fingerprint still differentiates two different fallback pastes"
  - "Router /preview uses Form('') for url so an empty string reaches the handler and renders fallback instead of FastAPI raising a 422 at the dependency layer"
  - "Task 3 checkpoint:human-verify deferred to phase-end visual sweep (same precedent as 05-05 Deviation #1) — 8 live_app router integration tests cover the equivalent flows automatically"

patterns-established:
  - "Pattern: router catches domain-specific error class (FetchError) AND broad Exception, degrades to a friendly form fragment — never propagates to the ASGI error handler"
  - "Pattern: tests for routers that need a DB live under tests/<feature>/ and drive the full lifespan via app.router.lifespan_context + httpx.ASGITransport — same shape as tests/review/test_router.py"
  - "Pattern: monkeypatch both app.manual_apply.fetcher.fetch_and_parse AND app.web.routers.manual_apply.fetch_and_parse when stubbing — the router imports the symbol at module load, so patching only the source module is insufficient"

# Metrics
duration: ~30min
completed: 2026-04-15
---

# Phase 5 Plan 05-06: Manual Apply (Paste-a-Link) Summary

**Paste-a-link manual-apply flow (/manual-apply) that fetches known ATS + generic URLs, shows a preview card, dedupes via canonical job_fingerprint, and routes pasted jobs through the standard tailoring + submission pipeline — with graceful FetchError degradation to a fallback textarea form.**

## Performance

- **Duration:** ~30 min (including 05-08 parallel wave coordination)
- **Started:** 2026-04-15
- **Completed:** 2026-04-15
- **Tasks:** 2 auto + 1 checkpoint (deferred to phase-end sweep)
- **Files created:** 12
- **Files modified:** 2 (additive merges with 05-08 parallel wave)
- **Tests added:** 26 (all green)
- **Full project suite:** 358/358 green in ~56s

## Accomplishments

- **MANL-01..06 shipped**: SC-3 ("user pastes a random job posting URL into the UI and that job routes through the same fetch → tailor → email pipeline, bypassing keyword match but respecting dedup") now holds end-to-end.
- **Three-step UX**: GET /manual-apply (paste form) → POST /preview (fetch + parse + preview card OR fallback form on FetchError) → POST /confirm (idempotent create_manual_job with duplicate detection).
- **Fallback direct-entry path**: POST /manual-apply/fallback accepts title/company/description/source/url from a textarea form and creates a Job without a network fetch — the escape hatch for LinkedIn/Indeed/bot-walled URLs.
- **Dedup via canonical fingerprint**: Pasting the same URL twice returns the existing job (linked to /jobs/{id}) instead of creating a duplicate. Same hash function Phase 3 discovery uses, so a manual paste also dedupes against auto-discovered jobs with the same URL.
- **Threshold bypass + pipeline entry**: Manual-apply jobs land at `status='matched'` regardless of keyword overlap. Plan 04-05's `get_queued_jobs` (widened to `status IN ('matched', 'retailoring')` in 05-05) picks them up automatically on the next scheduler tick. Zero changes needed in the tailoring or submission stages.
- **No crashes on hostile URLs**: `FetchError` (via either detected HTTP 401/403/404, timeouts, connection errors, or the <200-char "empty body" heuristic) always degrades to the fallback form with a human-readable reason — verified in `test_linkedin_url_degrades_to_fallback`.
- **26 network-free tests**: `httpx.MockTransport` drives every async HTTP path in `test_fetcher.py`; router tests monkeypatch both the source module and the router-local symbol binding.

## Task Commits

1. **Task 1: Fetcher + service + unit tests** — `e1cffc4` (feat)
   - `app/manual_apply/fetcher.py` (ParsedJob dataclass, FetchError, fetch_and_parse, _best_effort_parse)
   - `app/manual_apply/service.py` (check_duplicate, create_manual_job)
   - `tests/manual_apply/test_fetcher.py` (13 tests)
   - `tests/manual_apply/test_service.py` (5 tests)

2. **Task 2: Router + templates + nav + main mount + router tests** — `47a9ec3` (feat)
   - `app/web/routers/manual_apply.py` (4 endpoints)
   - `app/web/templates/manual_apply/` (4 templates: index, _preview, _fallback, _result)
   - `app/main.py` (include_router additive merge)
   - `app/web/templates/base.html.j2` (nav link additive merge)
   - `tests/manual_apply/test_router.py` (8 live_app integration tests)

3. **Task 3: Human verification checkpoint** — DEFERRED to phase-end visual sweep (same precedent as 05-05 Deviation #1 documented in STATE.md).

**Plan metadata:** pending (this commit).

## Files Created/Modified

### Created

- `app/manual_apply/__init__.py` — empty package marker
- `app/manual_apply/fetcher.py` — async httpx fetcher + best-effort HTML parser + stable FetchError vocabulary
- `app/manual_apply/service.py` — idempotent `create_manual_job` + `check_duplicate`, reuses `job_fingerprint` + `get_job_by_fingerprint`
- `app/web/routers/manual_apply.py` — 4 endpoints (GET /manual-apply, POST /preview, POST /confirm, POST /fallback) with defensive FetchError → fallback-form degradation
- `app/web/templates/manual_apply/index.html.j2` — paste form + HTMX preview-slot
- `app/web/templates/manual_apply/_preview.html.j2` — preview card with hidden-field Tailor form + Cancel button
- `app/web/templates/manual_apply/_fallback.html.j2` — textarea direct-entry form with source dropdown + error banner
- `app/web/templates/manual_apply/_result.html.j2` — success/duplicate confirmation fragment with links to /jobs/{id} and /review
- `tests/manual_apply/__init__.py` — package marker
- `tests/manual_apply/test_fetcher.py` — 13 unit tests (5 HTTP errors + 5 best-effort parse + 3 source stamping)
- `tests/manual_apply/test_service.py` — 5 unit tests (status/score stamping + dedup + threshold bypass + None lookup)
- `tests/manual_apply/test_router.py` — 8 live_app integration tests

### Modified (additive merges with 05-08 parallel wave)

- `app/main.py` — added `from app.web.routers import manual_apply as manual_apply_router` + `app.include_router(manual_apply_router.router)`. Plan 05-08 landed `applied_router` additively in the same file; both coexist cleanly.
- `app/web/templates/base.html.j2` — added `<li><a href="/manual-apply">Manual Apply</a></li>` after Review. Plan 05-08 landed `<li><a href="/applied">Applied</a></li>` in parallel; both present in nav.

## Decisions Made

- **FetchError vocabulary is a small stable string set** (not_found | auth_wall | timeout | empty_body | connect_failed | request_error | http_NNN | unexpected_error | empty_url | title_and_company_required). UI renders the reason directly via `<code>` block. No localization layer in v1.
- **<200-char empty-body heuristic** catches LinkedIn/Indeed SPA shells that 200 with a login wall. Empirically the shortest real job posting HTML is well over 5k chars.
- **Idempotent `create_manual_job`** — if fingerprint exists, returns the existing Job. Router calls `check_duplicate` first as a read-before-write so it can render a distinct "Already in the queue" fragment without needing an exception to disambiguate.
- **Manual-apply score=100 + matched_keywords='manual_paste'** — a stable sentinel that lets the Jobs list UI (Phase 3) distinguish manual from auto-discovered jobs at a glance without a new column. `score=100` also unblocks any downstream filter that still uses the original match-threshold gate.
- **Fallback synthesizes a stable URL** (`manual://<company_slug>/<title_slug>`) when the user has no real URL. Two separate fallback pastes for the same company+title still produce the same fingerprint (intentional — same role, same entity), but differing titles produce different fingerprints.
- **Router-local symbol binding** — `from app.manual_apply.fetcher import fetch_and_parse` at module load pins the function reference, so tests monkeypatch BOTH `app.manual_apply.fetcher.fetch_and_parse` AND `app.web.routers.manual_apply.fetch_and_parse`. Documented as a pattern note in `_install_parsed` / `_install_fetch_error` helpers.
- **Form('') for url on /preview** — FastAPI's `Form(...)` rejects empty strings with 422 before the handler runs; relaxing to `Form('')` lets an empty submission reach the handler which renders the fallback form with `error='empty_url'`. Same applies to the other optional fields.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] detect_source tuple unpacking order**

- **Found during:** Task 1 (fetcher implementation)
- **Issue:** The plan's code snippet at line 138 shows `source_type, slug = detect_source(url)`, but the real Phase 3 signature in `app/discovery/fetchers.py` returns `(slug, source_type)` — slug FIRST. Following the plan verbatim would have stamped every URL with `source='<slug-text>'`, producing nonsense like `source='stripe'` for a greenhouse URL and breaking the downstream dedup tracking.
- **Fix:** Unpack as `_slug, detected = detect_source(url)` and check `detected in ("greenhouse", "lever", "ashby")`.
- **Files modified:** `app/manual_apply/fetcher.py`
- **Verification:** `test_fetch_greenhouse_url_stamps_source_greenhouse` + `test_fetch_lever_url_stamps_source_lever` + `test_fetch_unknown_url_stamps_source_manual` all green.
- **Committed in:** `e1cffc4` (Task 1 commit)

**2. [Rule 3 - Blocking] Tests directory relocation**

- **Found during:** Task 1 (before writing tests)
- **Issue:** Plan specifies `app/tests/manual_apply/` but the project's `pyproject.toml` has `testpaths = ["tests"]`. Tests under `app/tests/` would be silently ignored by the full-suite runner — the same trap Plan 05-02 documented in its Deviation #1 and 05-05 inherited.
- **Fix:** Created tests under `tests/manual_apply/` instead. Applied the 05-02 precedent preemptively.
- **Files modified:** created `tests/manual_apply/__init__.py` + 3 test files
- **Verification:** `python -m pytest tests/manual_apply/ -v` collects all 26 tests; full suite picks them up at 358/358.
- **Committed in:** `e1cffc4` (Task 1 commit) and `47a9ec3` (Task 2 commit)

**3. [Rule 1 - Bug] Router /preview Form(...) rejects empty URL**

- **Found during:** Task 2 (running router tests)
- **Issue:** `test_post_preview_empty_url_returns_fallback` returned 422 instead of rendering the fallback form. FastAPI's `Form(...)` dependency rejects empty string for required fields with a 422 Unprocessable Entity before the handler runs, which means the router never gets a chance to render the fallback. That contradicts the plan's "graceful degradation — never 5xx/4xx on user-facing flow" contract (MANL-03).
- **Fix:** Changed `url: str = Form(...)` to `url: str = Form("")` on POST /preview. The handler checks `if not url:` and renders the fallback form with `error='empty_url'`.
- **Files modified:** `app/web/routers/manual_apply.py`
- **Verification:** `test_post_preview_empty_url_returns_fallback` green; no regression on the valid-URL path.
- **Committed in:** `47a9ec3` (Task 2 commit)

**4. [Rule 3 - Process] Task 3 checkpoint:human-verify deferred to phase-end visual sweep**

- **Found during:** Task 2 completion (evaluating next step)
- **Issue:** Per `config.json.mode="yolo"` and the explicit precedent set by Plan 05-05 (see STATE.md 2026-04-15 session note: "parallel waves cannot accommodate per-plan blocking checkpoints"), a per-plan blocking checkpoint cannot run inside an autonomous executor when 05-08 is running in parallel.
- **Fix:** Task 3 deferred to the phase-end visual sweep scheduled by Plan 05-05. The 8 live_app router integration tests cover the equivalent UX flows automatically: preview success, preview FetchError fallback, empty URL fallback, confirm creates Job(status=matched), confirm duplicate detection, fallback direct-entry path (with a sentinel asserting `fetch_and_parse` is never called), LinkedIn URL graceful degradation, and full page render.
- **Files modified:** None (process deferral)
- **Verification:** 26 manual_apply tests + 358/358 full suite green. Visual sweep covered separately at phase end per 05-05 precedent.
- **Committed in:** N/A (no code change)

---

**Total deviations:** 4 auto-fixed (1 Rule 1 bug, 2 Rule 3 blockers, 1 Rule 3 process)
**Impact on plan:** None — all four are necessary for correctness (tuple order, test discovery, empty-URL UX) or parallel-wave logistics (checkpoint deferral). Zero scope creep — the plan shipped exactly the 4 endpoints + 4 templates + 2 service modules + 26 tests it specified.

## Issues Encountered

None beyond the auto-fixed deviations. The 05-08 parallel wave landed cleanly between my two task commits (its `bb7c881` only added `app/review/applied_service.py` + tests, touched no file I was editing). Later in Task 2 it added its own nav link + `applied_router` mount into the SAME `app/main.py` and `base.html.j2` I had already edited — the merges were purely additive (different lines, different routers), so no conflict occurred.

## User Setup Required

None — no external service configuration required. `/manual-apply` is immediately usable on a freshly booted instance.

## Next Phase Readiness

**Ready for phase-end visual sweep:**

1. Paste a real Greenhouse URL from an enabled source → expect preview card with title + company + description excerpt + "greenhouse" source badge.
2. Click "Tailor this job" → expect "Queued for tailoring" fragment with job #N link.
3. Paste the SAME URL again → expect "Already in the queue" fragment with link to the existing job, no new row.
4. Paste a LinkedIn job URL → expect fallback form with `auth_wall` error banner (or `empty_body` if the SPA shell returns 200). Fill in title/company/description and click Tailor → expect Job row with `status='matched'`.
5. Paste a bogus URL (`https://example.com/does-not-exist`) → expect fallback form with `not_found` or `http_404` error (NOT a 500).
6. Force-run the scheduler via `/runs/trigger` → expect the manually-pasted jobs to proceed through tailoring and land in `/review`.

**Phase 5 completion status:**

- 05-01 schema ✓
- 05-02 email primitives ✓
- 05-03 submitter strategy registry ✓
- 05-04 submission pipeline drain loop ✓
- 05-05 review queue UI + state machine ✓
- 05-07 notification subsystem ✓
- 05-06 manual-apply paste-a-link ✓ (this plan)
- 05-08 applied-jobs dashboard — in parallel, partially landed (Task 1 committed in `bb7c881`)

Once 05-08 finishes, Phase 5 is complete pending the deferred phase-end visual sweep.

## Self-Check: PASSED

Files verified to exist:

- app/manual_apply/__init__.py ✓
- app/manual_apply/fetcher.py ✓
- app/manual_apply/service.py ✓
- app/web/routers/manual_apply.py ✓
- app/web/templates/manual_apply/index.html.j2 ✓
- app/web/templates/manual_apply/_preview.html.j2 ✓
- app/web/templates/manual_apply/_fallback.html.j2 ✓
- app/web/templates/manual_apply/_result.html.j2 ✓
- tests/manual_apply/__init__.py ✓
- tests/manual_apply/test_fetcher.py ✓
- tests/manual_apply/test_service.py ✓
- tests/manual_apply/test_router.py ✓

Commits verified via `git log --oneline`:

- e1cffc4 feat(05-06): manual_apply fetcher + service + 18 unit tests ✓
- 47a9ec3 feat(05-06): manual-apply router + 4 templates + 8 router tests ✓

Full suite at summary time: 358/358 green.

---
*Phase: 05-email-submission-review-queue*
*Completed: 2026-04-15*
