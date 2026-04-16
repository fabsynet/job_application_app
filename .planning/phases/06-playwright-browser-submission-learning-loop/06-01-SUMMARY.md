---
phase: 06-playwright-browser-submission-learning-loop
plan: 01
subsystem: learning-loop-schema
tags: [sqlmodel, alembic, migration, playwright, learning]
requires:
  - "Phase 5 complete (migration 0005, Settings model)"
  - "Phase 3 Job table (FK target for saved_answers and unknown_fields)"
provides:
  - "SavedAnswer and UnknownField SQLModel table classes"
  - "Alembic migration 0006 creating Phase 6 tables"
  - "Settings extensions: playwright_headless, pause_if_unsure, screenshot_retention_days"
affects:
  - "06-02 through 06-08 (all depend on these models)"
tech-stack:
  added: []
  patterns:
    - "Import side-effect for Alembic metadata registration (same as Phases 3-5)"
key-files:
  created:
    - app/learning/__init__.py
    - app/learning/models.py
    - app/db/migrations/versions/0006_phase6_playwright_learning.py
  modified:
    - app/db/models.py
key-decisions:
  - decision: "Follow existing hand-authored migration pattern (not autogenerate)"
    rationale: "Consistent with 0001-0005; explicit control over server_defaults and indexes"
  - decision: "Use op.add_column for Settings (not batch_alter_table)"
    rationale: "Matches 0002/0005 pattern; simpler for SQLite column additions"
duration: ~2 min
completed: 2026-04-15
---

# Phase 6 Plan 01: Phase 6 Database Schema Summary

**One-liner:** SavedAnswer + UnknownField tables with Alembic migration 0006 and three Playwright Settings columns

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create learning models + register with Alembic metadata | 78bef07 | app/learning/models.py, app/db/models.py |
| 2 | Create Alembic migration 0006 | af4d0fc | app/db/migrations/versions/0006_phase6_playwright_learning.py |

## What Was Built

### SavedAnswer model
- Stores learned field-label/answer pairs from previous applications
- Fields: field_label (indexed), field_label_normalized, answer_text, answer_type, source_job_id (FK to jobs), times_reused, created_at, updated_at

### UnknownField model
- Queues form fields the bot could not auto-fill for human resolution
- Fields: job_id (indexed, FK to jobs), field_label, field_type, field_options (JSON), screenshot_path, page_number, is_required, resolved, saved_answer_id (FK to saved_answers), created_at

### Settings extensions
- `playwright_headless: bool = True` -- headless vs headed browser toggle
- `pause_if_unsure: bool = True` -- halt on unknown fields vs always advance
- `screenshot_retention_days: int = 30` -- auto-cleanup threshold

### Migration 0006
- Creates saved_answers and unknown_fields tables with proper FKs and indexes
- Adds three new columns to settings with correct server_defaults
- Clean upgrade/downgrade roundtrip

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `from app.learning.models import SavedAnswer, UnknownField` -- OK
- `from app.db.models import SavedAnswer, UnknownField` -- OK
- Settings defaults: True, True, 30 -- confirmed
- Full test suite: 369/369 passed, zero regressions

## Next Phase Readiness

All subsequent Phase 6 plans (06-02 through 06-08) can now import these models and depend on migration 0006.

## Self-Check: PASSED
