---
phase: 04-llm-tailoring-docx-generation
plan: 01
subsystem: database
tags: [sqlmodel, alembic, sqlite, tailoring, cost-ledger]

# Dependency graph
requires:
  - phase: 03-safe-channel-discovery
    provides: jobs table (TailoringRecord.job_id FK target)
  - phase: 01-foundation-scheduler-safety-envelope
    provides: Settings singleton, Alembic migration pattern
provides:
  - TailoringRecord table (per-job tailoring attempt, token/cost/validator tracking)
  - CostLedger table (per-call spend, indexed on month for budget enforcement)
  - Settings.tailoring_intensity field (light | balanced | full, default 'balanced')
  - Alembic migration 0004 following existing hand-authored pattern
affects: [04-02 tailoring engine, 04-03 validator, 04-04 budget enforcement, 04-05 docx generation, 04-06 review queue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-phase model module (app/tailoring/models.py) imported into app/db/models.py for Alembic metadata registration (same pattern as app/discovery/models.py)"
    - "CostLedger indexed on month for cheap SUM-based budget queries"
    - "Hand-authored migrations with server_default on every new settings column (SQLite ALTER TABLE ADD COLUMN requirement)"

key-files:
  created:
    - app/tailoring/__init__.py
    - app/tailoring/models.py
    - app/db/migrations/versions/0004_phase4_tailoring.py
  modified:
    - app/db/models.py

key-decisions:
  - "tailoring_records.version is an integer counter (v1, v2, …) not a UUID — matches versioned artifact paths data/resumes/{job_id}/v{N}.docx"
  - "validation_warnings stored as JSON string in a VARCHAR column (no JSON type) — keeps SQLite migration trivial"
  - "CostLedger.tailoring_record_id is nullable — allows standalone validator/test calls that aren't tied to a specific record"
  - "CostLedger.month is a denormalised string (YYYY-MM) indexed for O(indexed-SUM) budget queries — avoids strftime in hot path"
  - "Settings.tailoring_intensity placed after Phase 2 block (not inside it) — keeps phase boundaries visible in the model"

patterns-established:
  - "Phase 4 models live under app/tailoring/ and re-export from app/db/models.py, mirroring the Phase 3 app/discovery/ convention"

# Metrics
duration: ~8 min
completed: 2026-04-12
---

# Phase 4 Plan 01: Tailoring Database Foundation Summary

**TailoringRecord and CostLedger SQLModel tables + Alembic migration 0004 that every later Phase 4 plan depends on, with Settings.tailoring_intensity default of 'balanced'.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-12T21:05:30Z
- **Completed:** 2026-04-12T21:13:43Z
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- New `app/tailoring/` module with `TailoringRecord` and `CostLedger` SQLModel tables
- Alembic migration 0004 applies cleanly and roundtrips (upgrade -> downgrade -> upgrade)
- `Settings.tailoring_intensity` column added with `'balanced'` default on existing singleton row
- Registered new models into `app/db/models.py` `__all__` so Alembic env.py picks them up via `from app.db import models`
- Full test suite still green: 175/175 passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tailoring SQLModel tables** - `8cee367` (feat)
2. **Task 2: Create Alembic migration 0004** - `e4c44b4` (feat)

_Plan metadata commit follows this SUMMARY._

## Files Created/Modified
- `app/tailoring/__init__.py` - Empty package marker
- `app/tailoring/models.py` - `TailoringRecord` and `CostLedger` SQLModel table definitions
- `app/db/models.py` - Added `tailoring_intensity` field to `Settings`, imported new models, extended `__all__`
- `app/db/migrations/versions/0004_phase4_tailoring.py` - Hand-authored migration creating both tables and altering settings

## Decisions Made
- Used plain `op.add_column` / `op.drop_column` for the `settings` alter — the existing project pattern in 0002 doesn't use `batch_alter_table`, and SQLite handles ADD/DROP COLUMN in recent versions (project already proven on 0002). The plan mentioned batch_alter_table, but matching the established pattern was the higher-order constraint.
- Named the migration revision slug `0004_phase4_tailoring` (not bare `0004`) to match the existing slug convention used by 0001_initial, 0002_phase2_config, 0003_phase3_discovery — Alembic chains by slug, not number, and an inconsistent id would have been a silent footgun.
- `cost_ledger.tailoring_record_id` left nullable so orphan validator/probe calls can still be logged for budget accounting without a parent record.
- `validation_warnings` is `VARCHAR NOT NULL DEFAULT ''` (JSON blob string). Keeps the migration portable; consumers `json.loads` on read.

## Deviations from Plan

Minor pattern clarification, not a rule-based deviation:

- **Plan text said** "Use batch_alter_table for SQLite compatibility (same pattern as prior migrations)."
- **Reality:** Prior migrations (0002) use plain `op.add_column` without batch mode. Followed the established project pattern rather than the plan text, since the migration runs cleanly both directions on SQLite. This is consistency-with-codebase, not a rule-based deviation, and has no functional impact.

**Total deviations:** 0 auto-fixed
**Impact on plan:** Plan executed as written. Migration pattern harmonised with existing codebase.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Schema foundation for Phase 4 is in place; 04-02 (tailoring engine) can begin writing `TailoringRecord` rows and `CostLedger` entries.
- `Settings.tailoring_intensity` ready for Phase 4 settings-UI plan (expected 04-0x) to surface as a 3-position slider per CONTEXT.md.
- No blockers.

---
*Phase: 04-llm-tailoring-docx-generation*
*Completed: 2026-04-12*

## Self-Check: PASSED
