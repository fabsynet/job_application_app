---
phase: 03-safe-channel-discovery-dedup-matching
plan: 04
subsystem: web-ui
tags: [jobs, htmx, sorting, inline-expand, keyword-highlighting]
depends_on: ["03-01", "03-02"]
provides: ["jobs-page", "jobs-table", "inline-detail", "manual-queue"]
affects: ["04-xx", "05-xx"]
tech_stack:
  added: []
  patterns: ["htmx-partial-swap", "inline-expand", "color-coded-badges"]
key_files:
  created:
    - app/web/routers/jobs.py
    - app/web/templates/jobs.html.j2
    - app/web/templates/partials/jobs_table.html.j2
    - app/web/templates/partials/job_detail_inline.html.j2
  modified:
    - app/main.py
    - app/web/templates/base.html.j2
    - app/web/static/app.css
metrics:
  duration: ~3 min
  completed: 2026-04-12
---

# Phase 3 Plan 4: Jobs Page UI Summary

**Jobs page with HTMX-sortable table, color-coded score badges, inline detail expansion with keyword highlighting, and manual queue action for below-threshold jobs.**

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Jobs router with sorting, detail, and queue endpoints | eeef374 | app/web/routers/jobs.py, app/main.py, base.html.j2 |
| 2 | Jobs templates with table, badges, and inline expand | 56a43bf | jobs.html.j2, jobs_table.html.j2, job_detail_inline.html.j2, app.css |

## What Was Built

### Jobs Router (app/web/routers/jobs.py)
- **GET /jobs** - Full page or HTMX table body partial with sorting (default: score desc)
- **GET /jobs/{id}/detail** - Inline expansion with keyword breakdown (matched green, unmatched gray)
- **POST /jobs/{id}/queue** - Manual queue action for below-threshold jobs
- All routes load settings for threshold and keywords, passing to templates for badge coloring

### Templates
- **jobs.html.j2** - Full page with sort macro generating HTMX column headers that swap tbody
- **jobs_table.html.j2** - Table rows with color-coded score badges (green/yellow/gray based on threshold)
- **job_detail_inline.html.j2** - Inline expansion with HTML description, keyword chips, queue button

### Navigation
- Added "Jobs" link to base template nav bar (between Dashboard and Runs)

### Styling
- Score badges: green (>= threshold), yellow (>= 50% threshold), gray (below)
- Keyword chips: matched (green background), unmatched (gray background)
- Detail row styling with left border accent and scrollable description

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Sort defaults to score desc | Most useful default - highest matches first |
| 500-job limit on list query | Reasonable ceiling for single-user app |
| Case-insensitive keyword matching | User may enter keywords differently than how they appear in job postings |
| Queue button only shown for discovered + below-threshold jobs | Per user decision: manual queue is for borderline jobs |

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- `python -c "from app.web.routers.jobs import router"` - passes
- `pytest tests/ -x -q` - 118 tests pass (no regressions)

## Next Phase Readiness

No blockers. Jobs page is ready to display discovery results once the pipeline runs. Phase 4 (resume tailoring) and Phase 5 (application submission) will add status transitions that this page already handles (queued, applied states).

## Self-Check: PASSED
