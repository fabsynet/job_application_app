---
phase: 04-llm-tailoring-docx-generation
plan: 06
subsystem: ui
tags: [fastapi, htmx, jinja2, mammoth, pico-css, tailoring-review, budget-widget]

# Dependency graph
requires:
  - phase: 04-llm-tailoring-docx-generation
    provides: TailoringRecord/CostLedger models (04-01), BudgetGuard (04-02), tailoring engine (04-03), docx_to_html + format_diff_html + check_ats_friendly + compute_keyword_coverage (04-04), tailoring service + pipeline stage (04-05)
  - phase: 01-foundation-scheduler-safety-envelope
    provides: Sidebar settings pattern (_render_section, _SECTION_MAP), dashboard HTMX polling pattern
provides:
  - "/tailoring/{job_id} detail route with HTML preview, side-by-side diff, validator findings, ATS audit, per-call cost with cache savings"
  - "/tailoring/{job_id}/preview/{version} HTMX version-swap partial"
  - "/tailoring/{job_id}/download/{version} and /cover-letter/{version} DOCX FileResponse endpoints"
  - "Settings > Tailoring three-position intensity selector (light/balanced/full)"
  - "Dashboard budget widget with progress bar, dismissible 80% warning, non-dismissible 100% halt banner, per-call-type breakdown"
affects: [review-queue, application-submission, phase-5]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tailoring review surface follows the existing HTMX+Jinja partial pattern (TemplateResponse positional form)"
    - "Detail view shims the tailored DOCX back into the diff input shape via extract_resume_text since the engine JSON is not persisted"
    - "Budget widget context assembled in dashboard._get_budget_context — mirrors _get_discovery_context"
    - "Cache savings math duplicated inline against Sonnet 4.5 pricing constants (kept in sync with BudgetGuard.PRICING)"

key-files:
  created:
    - app/web/routers/tailoring.py
    - app/web/templates/partials/tailoring_detail.html.j2
    - app/web/templates/partials/resume_preview.html.j2
    - app/web/templates/partials/settings_tailoring.html.j2
    - app/web/templates/partials/budget_widget.html.j2
  modified:
    - app/main.py
    - app/web/routers/settings.py
    - app/web/routers/dashboard.py
    - app/web/templates/partials/settings_sidebar.html.j2
    - app/web/templates/dashboard.html.j2

key-decisions:
  - "Detail view recomputes keyword_coverage on each render via compute_keyword_coverage because TailoringRecord has no keyword_coverage column"
  - "Diff shim re-extracts tailored DOCX text and reshapes into {sections:[{heading,content}]} since the engine's structured JSON is not persisted to the DB"
  - "Cache savings constant (_INPUT_PRICE_PER_MTOK=3.00, _CACHE_READ_PRICE_PER_MTOK=0.30) duplicated in router — documented as must-stay-in-sync with BudgetGuard.PRICING"
  - "Tailoring sidebar entry placed after Budget (before Rate Limits); Credentials already sits above Budget in the existing sidebar so 'before Credentials' was not achievable without reordering unrelated items"
  - "Intensity POST rejects values outside {light, balanced, full} with 400 so the pipeline can trust Settings.tailoring_intensity without defensive normalisation"
  - "80% budget warning banner is dismissible via POST /dismiss-budget-warning (client-only swap=delete, no cookie); 100% halt banner is non-dismissible"
  - "Budget widget reads Settings row for cap/spent/month as source of truth and augments with get_monthly_cost_summary for by-call-type breakdown"

patterns-established:
  - "Router template responses use Jinja2Templates(directory=...parent/templates) + positional TemplateResponse(request, name, ctx)"
  - "Detail view swallows preview/diff/ATS exceptions at warning level so a broken DOCX never 500s the review page"
  - "Budget context dict keys (budget_cap_dollars, budget_spent_dollars, budget_pct, budget_warning, budget_halt, budget_by_type, budget_month) are the contract between dashboard.py and budget_widget.html.j2"

# Metrics
duration: ~8min
completed: 2026-04-12
---

# Phase 4 Plan 6: Review UI + Budget Surfaces Summary

**Tailoring review page with mammoth HTML preview, side-by-side diff, validator findings, cache-savings cost breakdown, plus three-position intensity selector in Settings and a dashboard budget widget with 80% warning / 100% halt banners.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-12T22:05:42Z
- **Completed:** 2026-04-12T22:13:??Z
- **Tasks:** 2
- **Files modified:** 10 (5 created, 5 modified)

## Accomplishments

- `/tailoring/{job_id}` detail page wires together every Wave 1-3 deliverable: TailoringRecord reads (04-05), preview via `docx_to_html` (04-04), side-by-side diff via `generate_section_diff` + `format_diff_html` (04-04), `check_ats_friendly` + `compute_keyword_coverage` (04-04), and validator findings decoded from the JSON blob on the record
- SC-5 made visible in the UI: cache read tokens and estimated dollar savings shown explicitly in the token-usage table
- TAIL-06 keyword coverage percentage rendered in the ATS audit section ("XX% keyword match"), recomputed on render from the tailored DOCX text
- Three-position Tailoring intensity control added to the Settings sidebar, following the existing `_SECTION_MAP` + `_render_section` pattern
- Dashboard gains a budget widget with a coloured progress bar (green < 80%, amber 80–99%, red at 100%), a dismissible 80% warning banner, and a non-dismissible 100% halt banner linking back to Settings
- All 175 existing tests still green

## Task Commits

Each task was committed atomically:

1. **Task 1: Tailoring router with preview, download, and detail endpoints** — `983575c` (feat)
2. **Task 2: Settings intensity slider + dashboard budget widget** — `3ce775c` (feat)

**Plan metadata:** _(appended on final commit)_

## Files Created/Modified

- `app/web/routers/tailoring.py` — New APIRouter with detail / preview / download / cover-letter endpoints; diff shim + cache savings helpers
- `app/web/templates/partials/tailoring_detail.html.j2` — Extends base.html.j2; full detail page (version picker, downloads, preview, diff, validator, ATS audit, token/cost table)
- `app/web/templates/partials/resume_preview.html.j2` — Reusable mammoth-HTML wrapper card
- `app/web/templates/partials/settings_tailoring.html.j2` — Three-position intensity radio form (HTMX post to /settings/tailoring)
- `app/web/templates/partials/budget_widget.html.j2` — Monthly spend progress bar, warning/halt banners, per-call-type details
- `app/main.py` — Register tailoring router on the app
- `app/web/routers/settings.py` — `_SECTION_MAP` entry + `POST /settings/tailoring` handler with value validation
- `app/web/routers/dashboard.py` — `_get_budget_context` helper, dashboard handler wires it in, `POST /dismiss-budget-warning` endpoint
- `app/web/templates/partials/settings_sidebar.html.j2` — Add "Tailoring" nav item after Budget
- `app/web/templates/dashboard.html.j2` — Include budget_widget partial below the discovery summary

## Decisions Made

See frontmatter `key-decisions` list. Most significant:

- **keyword_coverage recomputed at render time** because the Wave 1 model (04-01) intentionally keeps TailoringRecord schema-stable across phases and Wave 3 (04-05) did not add the column. Recomputation is cheap (single DOCX extract + set-compare) and the value is deterministic for a given (tailored_path, job_description) pair.
- **Diff input shim** — the engine's tailored_sections JSON flows into the DOCX writer but is not persisted. For the detail view we re-extract the tailored DOCX via `extract_resume_text` and reshape each section into `{heading, content}` so `generate_section_diff` consumes it identically to a fresh engine output. This is lossy only in that subsection structure (company/title/dates/bullets) collapses into flat content text — the line-level diff still highlights changed bullets correctly.
- **Cache savings pricing constants inlined** rather than re-exported from `BudgetGuard.PRICING` to avoid introducing a circular-import risk between the UI layer and the budget singleton. A comment marks them as must-stay-in-sync.

## Deviations from Plan

### Minor

**1. Sidebar placement — "after Budget, before Credentials" not literally achievable**
- **Found during:** Task 2 (sidebar edit)
- **Issue:** The plan asked for Tailoring to sit between Budget and Credentials, but Credentials already lives above Budget in the existing sidebar ordering.
- **Fix:** Placed Tailoring immediately after Budget (before Rate Limits). Honours the "near Budget" intent without reordering unrelated items that would churn visual muscle memory.
- **Files modified:** app/web/templates/partials/settings_sidebar.html.j2
- **Verification:** Visual inspection; no tests exercise sidebar ordering.
- **Committed in:** 3ce775c

**2. TailoringRecord.keyword_coverage does not exist**
- **Found during:** Task 1 (wiring the ATS section of the detail view)
- **Issue:** Plan step said "Read keyword_coverage from the TailoringRecord (stored by pipeline in plan 05)" — but 04-01 schema has no such column and 04-05 pipeline does not write one.
- **Fix:** Recompute on demand via `compute_keyword_coverage(tailored_text, job.description)` inside the detail route. Documented as a key decision.
- **Files modified:** app/web/routers/tailoring.py
- **Verification:** 175 tests green; the detail view renders the percentage when job.description and the tailored DOCX are both present.
- **Committed in:** 983575c

---

**Total deviations:** 2 minor (both documentation/schema reconciliation, no auto-fixes for bugs or missing critical behaviour)
**Impact on plan:** Neither deviation changes the user-visible contract. Recomputation path adds O(single-DOCX-extract) to detail page render which is well inside HTMX interactive budgets.

## Issues Encountered

None — both tasks landed on first try, 175 tests stayed green across both commits.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 4 is now feature-complete except plan 04-07 (tests). Users can:
  - Configure tailoring intensity from Settings sidebar
  - Watch monthly spend on the dashboard with early warning + hard halt
  - Open any tailored job and inspect HTML preview + diff + validator findings + cache savings
  - Download the final DOCX and cover letter
- **Blockers for 04-07:** None. The test plan can target tailoring_router endpoints + the new budget context builder using the existing `live_app` fixture pattern.
- **Flagged for 04-07:** The diff shim (`_docx_sections_as_tailored_json`) and cache savings math deserve explicit unit coverage since they are the main review-queue correctness surface.

## Self-Check: PASSED

Files verified:
- app/web/routers/tailoring.py — exists
- app/web/templates/partials/tailoring_detail.html.j2 — exists
- app/web/templates/partials/resume_preview.html.j2 — exists
- app/web/templates/partials/settings_tailoring.html.j2 — exists
- app/web/templates/partials/budget_widget.html.j2 — exists

Commits verified:
- 983575c — task 1
- 3ce775c — task 2

---
*Phase: 04-llm-tailoring-docx-generation*
*Completed: 2026-04-12*
