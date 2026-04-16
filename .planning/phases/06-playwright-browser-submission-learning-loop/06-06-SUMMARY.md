---
phase: 06-playwright-browser-submission-learning-loop
plan: 06
subsystem: web-ui
tags: [needs-info, queue, learning-loop, templates, router]
depends_on:
  requires: ["06-01", "06-04", "06-05"]
  provides: ["needs-info-queue-ui", "needs-info-router", "reused-answers-email"]
  affects: ["06-08"]
tech-stack:
  added: []
  patterns: ["needs-info queue page", "answer form partial", "reused answers in email"]
key-files:
  created:
    - app/web/routers/needs_info.py
    - app/web/templates/needs_info/index.html.j2
    - app/web/templates/needs_info/detail.html.j2
    - app/web/templates/needs_info/answer_form.html.j2
    - tests/needs_info/__init__.py
    - tests/needs_info/test_needs_info_router.py
  modified:
    - app/main.py
    - app/web/templates/base.html.j2
    - app/submission/notifications.py
    - app/web/templates/emails/success.txt.j2
decisions:
  - id: "06-06-d1"
    decision: "Mount router in Task 1 instead of Task 2 to unblock tests"
    rationale: "Rule 3 blocking: live_app fixture reloads app.main, router must be mounted for GET /needs-info to return 200"
  - id: "06-06-d2"
    decision: "Retry endpoint flips to approved for pipeline pickup instead of inline Playwright"
    rationale: "Inline Playwright requires browser context lifecycle management that belongs in the scheduler pipeline, not the web request layer"
metrics:
  duration: "~8 min"
  completed: "2026-04-16"
---

# Phase 6 Plan 06: Needs-Info Queue Router Summary

**Needs-info queue UI with list/detail/answer/retry endpoints, nav link, and reused answers in success email.**

## Task Commits

| Task | Name | Commit | Key Change |
|------|------|--------|------------|
| 1 | Needs-info queue router + templates | fd47137 | Router with 4 endpoints, 3 templates, 7 tests |
| 2 | Nav link + email reuse summary + app mount | 83d7892 | Nav link, reused_answers param, email template update |

## What Was Built

### Needs-Info Queue Router (app/web/routers/needs_info.py)
- **GET /needs-info** -- Lists all jobs with `needs_info` status, showing unknown field counts
- **GET /needs-info/{job_id}** -- Detail page with job context, unknown fields (screenshots, labels, types), and answer form
- **POST /needs-info/{job_id}/answer** -- Resolves unknown fields via `resolve_all_for_job`, creates SavedAnswer rows, flips job to `approved`
- **POST /needs-info/{job_id}/retry** -- Flips job to `approved` for pipeline pickup

### Templates (Pico.css styled, extends base.html.j2)
- **index.html.j2** -- Table with Job, Company, Source, Unknown Fields, Unresolved columns. Empty state message.
- **detail.html.j2** -- Two-column grid: left=job context, right=unknown fields with answer form
- **answer_form.html.j2** -- Partial rendering text inputs, selects, checkboxes, radio buttons per field type

### Navigation + Email
- "Needs Info" nav link added between Review and Applied
- `send_success_notification` accepts optional `reused_answers: list[tuple[str, str]]`
- Success email template renders "Saved Answers Applied" section when reused_answers provided

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Router mounted in Task 1 instead of Task 2**
- **Found during:** Task 1
- **Issue:** Tests require the router to be mounted in `app/main.py` but plan assigns that to Task 2
- **Fix:** Added import + `app.include_router(needs_info_router.router)` in Task 1 commit
- **Files modified:** app/main.py
- **Commit:** fd47137

## Test Results

- 7 new tests in `tests/needs_info/test_needs_info_router.py` -- all pass
- Full suite: 564 passed, 1 deselected (pre-existing `test_unknown_field_matched_via_llm` failure)

## Self-Check: PASSED
