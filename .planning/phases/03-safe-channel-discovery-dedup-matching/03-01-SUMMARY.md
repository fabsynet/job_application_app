---
phase: 03-safe-channel-discovery-dedup-matching
plan: 01
subsystem: database-schema
tags: [sqlmodel, alembic, discovery, source, job, dedup]

dependency_graph:
  requires: [01-01, 02-01]
  provides: [Source table, Job table, DiscoveryRunStats table, migration 0003]
  affects: [03-02, 03-03, 03-04, 03-05, 03-06]

tech_stack:
  added: []
  patterns: [discovery models in separate app/discovery/ package, cross-package model import for Alembic metadata]

key_files:
  created:
    - app/discovery/__init__.py
    - app/discovery/models.py
    - app/db/migrations/versions/0003_phase3_discovery.py
  modified:
    - app/db/models.py

decisions:
  - Discovery models live in app/discovery/models.py, imported into app/db/models.py for Alembic metadata registration
  - Job.fingerprint is SHA256, unique-indexed for O(1) dedup lookups
  - posted_date is nullable (Lever public API lacks this field)
  - description and description_html stored separately (plain text for scoring, HTML for display)
  - DiscoveryRunStats tracks per-source per-run counts for anomaly detection rolling averages

metrics:
  duration: ~4 min
  completed: 2026-04-12
---

# Phase 3 Plan 01: Discovery Schema Summary

**SQLModel tables (Source, Job, DiscoveryRunStats) and Alembic migration 0003 creating three discovery tables with fingerprint dedup index, foreign keys to runs and sources.**

## What Was Done

### Task 1: Create discovery models
Created `app/discovery/` package with three SQLModel table classes:
- **Source** (9 fields): ATS board config with slug, type, enable toggle, fetch status tracking
- **Job** (17 fields): Normalised posting with fingerprint dedup, keyword score, status lifecycle
- **DiscoveryRunStats** (7 fields): Per-source per-run counts for anomaly rolling average

Imported all three into `app/db/models.py` so Alembic's `env.py` metadata picks them up.

### Task 2: Create Alembic migration 0003
Hand-authored migration following the established pattern (0001/0002). Creates all three tables with:
- Unique index on `jobs.fingerprint`
- Regular indexes on `jobs.company`, `sources.slug`, `discovery_run_stats.run_id`, `discovery_run_stats.source_id`
- Foreign keys: `jobs.source_id` -> `sources.id`, `jobs.run_id` -> `runs.id`, `discovery_run_stats.run_id` -> `runs.id`, `discovery_run_stats.source_id` -> `sources.id`
- Proper `server_default` values for all non-nullable columns with defaults

Migration chain verified: 0001_initial -> 0002_phase2_config -> 0003_phase3_discovery.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created data/ directory for Alembic migration run**
- **Found during:** Task 2 verification
- **Issue:** `data/` directory did not exist, causing SQLite `unable to open database file` error
- **Fix:** Created `data/` directory (already in `.gitignore`)
- **Files modified:** None (directory only)

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create discovery models | a91bf13 | app/discovery/models.py, app/db/models.py |
| 2 | Create Alembic migration 0003 | 46e199b | app/db/migrations/versions/0003_phase3_discovery.py |

## Verification Results

- All three model classes importable: PASS
- Migration chain 0001 -> 0002 -> 0003: PASS
- `alembic upgrade head` clean: PASS
- Tables exist with correct columns: PASS (sources: 9 cols, jobs: 17 cols, discovery_run_stats: 7 cols)
- Indexes present: PASS (5 indexes across 3 tables)
- Foreign keys correct: PASS (4 FK constraints)

## Next Phase Readiness

All subsequent Phase 3 plans (02-06) can now reference Source, Job, and DiscoveryRunStats tables. No blockers.

## Self-Check: PASSED
