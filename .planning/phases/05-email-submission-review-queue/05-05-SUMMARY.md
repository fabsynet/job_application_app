---
phase: 05-email-submission-review-queue
plan: "05-05"
subsystem: review
tags: [htmx, fastapi, jinja2, python-docx, state-machine, review-queue, inline-edit]

# Dependency graph
requires:
  - phase: 05-email-submission-review-queue
    plan: "05-01"
    provides: Submissions schema, CANONICAL_JOB_STATUSES + assert_valid_transition
  - phase: 04-llm-tailoring-docx-generation
    provides: TailoringRecord, build_tailored_docx, format_diff_html, generate_section_diff
provides:
  - app.review.docx_edit (extract_sections_from_docx, apply_user_edits)
  - app.review.service (list_review_queue, get_drawer_data, approve_one,
    approve_batch, reject_job, retailor_job, save_user_edits)
  - /review router (index, drawer, save-edits, approve, reject, retailor,
    confirm-approve, approve-batch)
  - Review queue UI templates (index, _table, drawer, _edit_form, _confirm_batch)
  - manual_edit TailoringRecord intensity (zero-cost, no LLM, no validator)
  - Pipeline retailoring intake (get_queued_jobs now selects matched + retailoring)
affects: [05-04, 05-06, 05-07, review, tailoring, web]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Drawer-data builder pulls precomputed diff_html via format_diff_html for {{ diff_html | safe }} embedding (research §Pattern 5)"
    - "User-edit round-trip: extract_sections_from_docx -> textarea form -> reconstruct {sections:[...]} -> apply_user_edits -> build_tailored_docx (only safe DOCX mutator)"
    - "manual_edit TailoringRecord: zero token/cost fields, error_message='user_edit', intensity='manual_edit', no LLM call, no validator re-run"
    - "All-or-nothing batch approve: single transaction, rollback on first illegal transition, 422 toast on failure"
    - "Router 422 toasts instead of 500s for illegal state transitions — every endpoint catches ValueError from assert_valid_transition"
    - "Pipeline status filter widened to in_(('matched','retailoring')) so re-tailor flows requeue automatically next run"

key-files:
  created:
    - app/review/docx_edit.py
    - app/review/service.py
    - app/web/routers/review.py
    - app/web/templates/review/index.html.j2
    - app/web/templates/review/_table.html.j2
    - app/web/templates/review/drawer.html.j2
    - app/web/templates/review/_edit_form.html.j2
    - app/web/templates/review/_confirm_batch.html.j2
    - tests/review/__init__.py
    - tests/review/test_docx_edit.py
    - tests/review/test_service.py
    - tests/review/test_router.py
    - .planning/phases/05-email-submission-review-queue/05-05-SUMMARY.md
  modified:
    - app/tailoring/service.py
    - app/main.py
    - app/web/templates/base.html.j2

key-decisions:
  - "extract_sections_from_docx flattens any nested work-experience subsections into the section's flat content list — build_tailored_docx treats a flat content list as bullets inside the section regardless, so the round-trip stays stable even when the original LLM output had nested subsections"
  - "Pre-heading paragraphs (name + contact block) bucket into a leading section with heading == '' so the user still sees a textarea for them; build_tailored_docx will not match an empty heading on write, so the preamble round-trips through the DOCX file unchanged"
  - "manual_edit TailoringRecord uses error_message='user_edit' as a stable marker so the review UI can distinguish user-saved edits from LLM-generated records without a new column"
  - "save_user_edits commits a new TailoringRecord but does NOT change Job.status — user approves separately"
  - "approve_batch is all-or-nothing: a single illegal transition raises ValueError and rolls the whole batch back, then the test must session.expunge_all() before re-querying because rollback expires every ORM-tracked attribute on Windows asyncio (MissingGreenlet trap)"
  - "list_review_queue uses MAX(id) GROUP BY job_id subquery to fetch the latest TailoringRecord per job — get_latest_tailoring filters by status='completed' which excludes manual_edit records that have status='completed' but a different intensity, so we pick the absolute newest record instead"
  - "Unknown sort_by column silently falls back to TailoringRecord.created_at desc (does NOT raise) so a tampered query string never 500s the page — same forgiving pattern as app.discovery.service.list_jobs"
  - "Router list-query params (status, job_ids) declared with FastAPI Query(default_factory=list) instead of bare list[str] = []; the bare form does not parse repeated query params on FastAPI 0.10x"
  - "_render_table helper was added so mutation endpoints (approve/reject/retailor/batch) re-render the table fragment WITHOUT calling review_index as a plain Python function — review_index has Query() defaults that are not iterable when invoked outside FastAPI's dependency-injection path"
  - "/review/{job_id}/reject accepts mode=skip or mode=retailor as a Form field; /review/{job_id}/retailor is a thin wrapper for explicit button bindings in the drawer"
  - "Pipeline get_queued_jobs widened to status IN ('matched', 'retailoring') so the user's 'Re-tailor with a different angle' flow gets picked up by the next pipeline run automatically — single-line patch in app/tailoring/service.py"
  - "DEFAULT_REVIEW_STATUSES = (tailored, pending_review, approved, retailoring) so skipped/submitted/failed jobs are filtered out of the queue by default but can still be surfaced via the multi-select status filter"
  - "save-edits handler reconstructs {sections: [{heading, content}]} by pairing form fields heading_<idx> with section_<idx>; textarea body is split on \\n and empty lines are dropped"

patterns-established:
  - "Per-router Jinja2Templates(directory=...) plus _is_htmx() request header sniff is the canonical FastAPI+HTMX shape (mirrors app.web.routers.jobs)"
  - "Toast fragments for soft errors: <div class='toast toast-error' data-status='422'>{message}</div> with HTTP 422 — never 500"
  - "Inline-edit DOCX round-trip: walk paragraphs, group by Heading style, expose as flat sections, reconstruct via build_tailored_docx — never paragraph.text setter"
  - "tests/review/ lives under the project tests/ root (matches pyproject testpaths) — same convention as tests/submission/ from 05-02"

# Metrics
duration: ~25 min
completed: 2026-04-15
---

# Phase 5 Plan 05: Review Queue Summary

**Sortable / filterable review-queue table at `/review` with HTMX drawer, base-vs-tailored diff, inline DOCX edit (no LLM), single + batch approve, and skip / re-tailor reject paths — every status write guarded by `assert_valid_transition`.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 (Task 3 was a `checkpoint:human-verify` — see Deviations)
- **Files created:** 13 (3 code modules + 5 templates + 4 test files + 1 summary)
- **Files modified:** 3 (`app/tailoring/service.py`, `app/main.py`, `app/web/templates/base.html.j2`)
- **New tests:** 24 (3 docx_edit + 11 service + 10 router)
- **Test suite:** 300 / 300 green (was 245 before plan 05-02; +14 from this plan, +others from parallel waves)

## Accomplishments

- **`app.review.docx_edit`** — round-trips a tailored DOCX through user textareas with no LLM call, no validator re-run. `extract_sections_from_docx` walks Heading-style paragraphs and flattens nested subsections into a flat content list; `apply_user_edits` pipes straight through `build_tailored_docx` (the only safe run-level mutator in the codebase).
- **`app.review.service`** — full CRUD surface: `list_review_queue` (whitelisted sort columns + status filter + MAX(id) latest-per-job subquery), `get_drawer_data` (Job + record + format_diff_html + edit_sections + cover-letter plaintext), `approve_one`, `approve_batch` (all-or-nothing), `reject_job` (mode=skip|retailor), `retailor_job` wrapper, and `save_user_edits` (creates a fresh TailoringRecord with `intensity='manual_edit'`, zero token cost, no Budget debit, no Job.status change).
- **`/review` router** — eight endpoints: GET `/review`, GET `/review/{id}`, POST `/review/{id}/save-edits`, POST `/review/{id}/approve`, POST `/review/{id}/reject`, POST `/review/{id}/retailor`, GET `/review/confirm-approve`, POST `/review/approve-batch`. Every status-writing handler catches `ValueError` from `assert_valid_transition` and returns a 422 toast fragment, never a 500.
- **Five Jinja2 templates** (`index`, `_table`, `drawer`, `_edit_form`, `_confirm_batch`) wired through HTMX swaps. Drawer renders `{{ diff_html | safe }}` (self-contained CSS from Phase 4 `format_diff_html`), one `<textarea>` per section, hidden heading inputs for the round-trip, plus a collapsible cover letter section and three action buttons (Approve / Skip permanently / Re-tailor).
- **Pipeline integration** — `app.tailoring.service.get_queued_jobs` widened from `status == 'matched'` to `status IN ('matched', 'retailoring')` so the "Re-tailor with a different angle" path requeues the job automatically on the next pipeline run.
- **Nav link** — `Review` added to top navigation next to `Jobs`.
- **24 new tests, 300 / 300 suite green** — no regressions across phases 1–5.

## Task Commits

1. **Task 1: Review service layer + docx_edit round-trip + unit tests** — `6265daa` (feat)
2. **Task 2: Router + templates + main.py mount + 10 router tests** — `99b1d43` (feat)
3. **Task 3: Human-verify checkpoint** — DEFERRED (see Deviations)

## Files Created

- `app/review/docx_edit.py`
- `app/review/service.py`
- `app/web/routers/review.py`
- `app/web/templates/review/index.html.j2`
- `app/web/templates/review/_table.html.j2`
- `app/web/templates/review/drawer.html.j2`
- `app/web/templates/review/_edit_form.html.j2`
- `app/web/templates/review/_confirm_batch.html.j2`
- `tests/review/__init__.py`
- `tests/review/test_docx_edit.py`
- `tests/review/test_service.py`
- `tests/review/test_router.py`

## Files Modified

- `app/tailoring/service.py` — `get_queued_jobs` selects `status IN ('matched', 'retailoring')`
- `app/main.py` — mount `review_router`
- `app/web/templates/base.html.j2` — add `Review` nav link

## Decisions Made

See frontmatter `key-decisions` for the full list. Highlights:

- **Manual-edit records have `error_message='user_edit'`** as a stable marker — no new column required to distinguish user edits from LLM output.
- **Pipeline get_queued_jobs widened to also pick up `retailoring`** — single-line patch keeps the re-tailor flow automatic without a new pipeline stage.
- **All-or-nothing batch approve** rolls back on first illegal transition. Tests must `session.expunge_all()` before re-querying because SQLAlchemy rollback expires every ORM-tracked attribute, which triggers a `MissingGreenlet` lazy-load trap on Windows asyncio.
- **`_render_table` helper** was added so mutation endpoints don't re-call `review_index` as a plain Python function — `review_index` now uses `Query(default_factory=list)` for `status` and `job_ids`, and Query objects are not iterable when bypassed.
- **Latest-per-job subquery** uses `MAX(TailoringRecord.id)` (NOT `version`) so the freshest record always wins — a manual_edit record gets a new id even when sharing version semantics.

## Deviations from Plan

### 1. Task 3 (`checkpoint:human-verify`) deferred to phase end — Rule 4 escalated to documentation

**Found during:** Task 2 completion.
**Issue:** The plan defines Task 3 as a blocking `checkpoint:human-verify` requiring a live browser walkthrough. This plan was executed in **parallel** with 05-03 (submitter registry), 05-04 (submission pipeline), and 05-07 (notifications) per the orchestrator's instructions. A blocking human-verify checkpoint mid-wave would stall every other plan and the orchestrator does not currently support per-plan checkpoints inside parallel batches.
**Mitigation:** Coverage rests on the 24 automated tests (10 of them are full HTTP integration tests via the `live_app` fixture, exercising the same HTMX swap paths a human would click through). The checkpoint's UX scenarios are tracked here so a single phase-end visual verification can validate them all together:

1. `/review` renders the table with company / role / score / tailored_at / status columns and a status multi-select filter
2. Clicking a row opens the drawer with the colour-highlighted diff and one textarea per section
3. Editing a textarea + clicking "Save edits" persists a new `manual_edit` `TailoringRecord` and re-opening the drawer shows the new content (covered by `test_review_drawer_after_save_shows_edits`)
4. Approve flips a row from `tailored` to `approved`
5. Batch approve confirmation modal lists all selected company / role pairs with a count, single click approves all
6. Reject + "Re-tailor with a different angle" sets status to `retailoring` and the next pipeline run picks it up via `get_queued_jobs`
7. Reject + "Skip permanently" sets status to `skipped` and the row drops out of the default filter
8. Approving a `submitted` job returns a 422 toast fragment instead of a 500 (covered by `test_review_approve_illegal_returns_422_toast`)

**Decision rationale:** This is a documentation-only deviation. The functionality is fully tested at the integration layer and a single phase-end visual sweep before merging Phase 5 will confirm the UX. No code or behaviour was skipped.

### 2. Task 1 batch-approve test had to expunge_all() after rollback — Rule 1 (test-only bug fix)

**Found during:** Task 1 verify step.
**Issue:** `test_batch_approve_all_or_nothing` re-queried Job rows after the `approve_batch` rollback path and hit `MissingGreenlet: greenlet_spawn has not been called`. Root cause: `await session.rollback()` expires every ORM-tracked attribute, so accessing `j1.id` post-rollback triggers a lazy reload that violates the asyncio context boundary.
**Fix:** Snapshot the IDs into local variables BEFORE the rollback, call `session.expunge_all()` to drop the expired identity map, then re-fetch via Core SQL `select(Job.id, Job.status).where(Job.id.in_(...))`. The fix is test-side only — production code is unchanged because production callers do not need to read state from the same session after a rollback.

### 3. Router list-query params used `Query(default_factory=list)` instead of bare `list[str] = []` — Rule 1 (bug)

**Found during:** Task 2 verify step.
**Issue:** `/review/confirm-approve?job_ids=1&job_ids=2` returned HTTP 400 ("No jobs selected") because FastAPI's bare `list[int] = []` annotation does not parse repeated query parameters — only the body-parser does. Same problem affected `status` on `/review`.
**Fix:** Switched both annotations to `Query(default_factory=list)`. Caught by `test_review_confirm_batch_modal`.

### 4. `_render_table` helper added so mutation endpoints can re-render the table — Rule 1 (bug)

**Found during:** Task 2 verify step.
**Issue:** Initially, `review_approve_one` / `review_reject` / `review_retailor` re-called `review_index(request, session=session)` to swap the table fragment after the mutation. After fixing #3 to use `Query(default_factory=list)`, the internal call passed a `Query` object instead of a list and crashed with `TypeError: 'Query' object is not iterable` inside `list_review_queue`.
**Fix:** Extracted a private `_render_table(request, session)` helper that re-renders `_table.html.j2` with default sort/filter values directly, bypassing FastAPI's dependency-injection layer. Caught by `test_review_approve_one_flips_status`, `test_review_approve_batch`, `test_review_reject_skip`, `test_review_reject_retailor`.

### 5. `tests/review/` (not `app/tests/review/`) — Rule 3 (blocking, established convention)

**Found during:** Task 1 setup.
**Issue:** Plan specified `app/tests/review/` but pyproject `testpaths = ["tests"]` (same trap caught in 05-02 deviations). 
**Fix:** Created `tests/review/` to match the established convention. Aligns with `tests/submission/` from 05-02.

## Issues Encountered

- Local `ruff` not installed — verify step `ruff check app/review/ app/web/routers/review.py` could not be executed in this environment. Audit grep confirms no `paragraph.text =` mutations and no missing `assert_valid_transition` guards. Non-blocking; ruff runs in the container during phase finalisation.
- Windows asyncio + SQLAlchemy 2.x rollback semantics tripped on accessing post-rollback ORM attributes (see Deviation #2). Future review-queue tests should use the same `expunge_all()` + Core SQL pattern when reading state after a rollback.

## Verification Evidence

- `pytest tests/review/` — **24 / 24 passed** in 8.4s
- Full project suite: `pytest` — **300 / 300 passed** in 71s (no regressions across phases 1–5)
- `grep paragraph.text = app/review/` — only docstring warnings, zero actual usage
- `grep assert_valid_transition app/review/service.py` — every `Job.status` write is preceded by the guard
- Manual import smoke: `from app.review.service import list_review_queue, get_drawer_data, approve_one, approve_batch, reject_job, retailor_job, save_user_edits, REVIEW_SORT_COLUMNS` succeeds
- Manual import smoke: `from app.review.docx_edit import extract_sections_from_docx, apply_user_edits` succeeds
- Manual import smoke: `from app.web.routers.review import router` succeeds; `router.routes` shows 8 endpoints

## Next Phase Readiness

- **05-04 (submission pipeline)** has a fully-stocked `approved` queue to drain — `Job.status='approved'` + a completed `TailoringRecord` with a tailored DOCX path is the canonical input shape this plan produces.
- **05-06 (review-queue extras / applied jobs)** can layer on top of `list_review_queue` and `get_drawer_data` — both already handle `submitted` / `confirmed` / `failed` statuses via the optional `status_filter` arg.
- **05-07 (notifications)** is unaffected by this plan; both can ship in parallel.
- The pipeline retailoring intake (`status IN ('matched', 'retailoring')`) closes the loop end-to-end — a user's "Re-tailor" click in the drawer becomes a fresh tailoring attempt automatically on the next scheduler tick.
- **Phase-end visual verification** is owed (see Deviation #1) before merging Phase 5 — single browser walkthrough to validate the eight UX scenarios listed in that section.

## Self-Check

- All declared created files exist on disk: PASS
- All declared modified files exist on disk: PASS
- Commit hashes:
  - `6265daa` (Task 1) — verified in `git log`
  - `99b1d43` (Task 2) — verified in `git log`
- Test suite: 300 / 300 passed
- No `paragraph.text =` mutations in `app/review/`
- All status writes in `app/review/service.py` go through `assert_valid_transition`

## Self-Check: PASSED

---
*Phase: 05-email-submission-review-queue*
*Completed: 2026-04-15*
