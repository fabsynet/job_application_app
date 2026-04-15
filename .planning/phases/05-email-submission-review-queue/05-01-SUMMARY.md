---
phase: 05-email-submission-review-queue
plan: "05-01"
subsystem: db
tags: [alembic, sqlmodel, sqlite, partial-unique-index, state-machine, migrations]

# Dependency graph
requires:
  - phase: 04-llm-tailoring-docx-generation
    provides: tailoring_records table (FK target for submissions.tailoring_record_id)
  - phase: 03-discovery-matching-sources
    provides: jobs table (FK target for submissions.job_id) + Job.status column
provides:
  - submissions table with pending/sent/failed status lifecycle
  - Partial UNIQUE index ux_submissions_job_sent enforcing one-sent-per-job (SC-7)
  - failure_suppressions table with UNIQUE signature (SC-4 one-email-per-failure)
  - Settings.notification_email (SC-1 decoupled notification destination)
  - Settings.base_url (SC-1 link back to review UI in emails)
  - Settings.submissions_paused (SC-2 soft pause toggle)
  - Settings.auto_holdout_margin_pct (SC-4 low-confidence holdout margin)
  - app.review.states.CANONICAL_JOB_STATUSES (13 states) + assert_valid_transition
affects: [05-02, 05-03, 05-04, 05-05, 05-06, 05-07, submission, review, notifications]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Partial UNIQUE index via op.create_index(..., sqlite_where=sa.text(...)) (SQLite-safe; UniqueConstraint silently drops WHERE)"
    - "Service-layer state machine: module-level frozenset + transition dict + assert_valid_transition helper (mirrors CANONICAL_FAILURE_REASONS)"
    - "New feature packages (app.submission, app.review) re-exported from app.db.models so Alembic env.py auto-registers metadata"

key-files:
  created:
    - app/submission/__init__.py
    - app/submission/models.py
    - app/review/__init__.py
    - app/review/states.py
    - app/db/migrations/versions/0005_phase5_submission.py
    - .planning/phases/05-email-submission-review-queue/05-01-SUMMARY.md
  modified:
    - app/db/models.py

key-decisions:
  - "Partial UNIQUE index uses op.create_index with sqlite_where=sa.text(\"status = 'sent'\") — UniqueConstraint form silently drops WHERE on SQLite (research Pitfall 9)"
  - "CANONICAL_JOB_STATUSES includes legacy 'applied' status as a back-compat terminal state so Phase 3 rows do not fail validation"
  - "State machine enforcement is service-layer only — Job.status remains a plain str column, mirroring CANONICAL_FAILURE_REASONS precedent"
  - "Settings.notification_email is nullable; NULL means fall back to smtp_user at send time (no forced separate inbox)"
  - "Settings.base_url defaults to http://localhost:8000 — LAN-first; operator overrides in settings UI for remote access"
  - "Submission.submitter column added now (email | playwright) to avoid a schema bump when Phase 6 Playwright lands"

patterns-established:
  - "Phase 5 schema landing pattern: Wave 1 plan ships tables + Settings columns + state frozenset only, zero business logic, so downstream waves run in parallel"
  - "Partial unique idempotency: create_index(unique=True, sqlite_where=...) is the canonical way to express 'one row per key where status matches' on SQLite"
  - "assert_valid_transition(current, target) is the uniform service-layer gate before any Job.status write in Phase 5"

# Metrics
duration: ~15 min
completed: 2026-04-15
---

# Phase 5 Plan 01: Submission Schema Foundation Summary

**Alembic 0005 landing the submissions + failure_suppressions tables with a real SQLite partial UNIQUE index for send-idempotency, four new Settings columns, and a 13-state canonical job state machine with an assert_valid_transition helper.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2
- **Files created:** 6 (5 code + 1 summary)
- **Files modified:** 1 (app/db/models.py)
- **Test suite:** 216/216 green (no regressions)

## Accomplishments

- `submissions` table with pending/sent/failed lifecycle, FK to jobs and tailoring_records, failure signature column, submitter column future-proofed for Phase 6 Playwright
- `ux_submissions_job_sent` partial UNIQUE index — verified real via `CREATE UNIQUE INDEX ... WHERE status = 'sent'` in sqlite_master and proven by an IntegrityError on duplicate-sent insert
- `failure_suppressions` table with UNIQUE signature index — foundation for SC-4 "one email per root cause until cleared"
- Four new Settings columns applied to the existing singleton row via ALTER TABLE ADD COLUMN with explicit server_default values (SQLite requirement)
- `app.review.states` module: 13-state frozenset, allowed-transition dict, and assert_valid_transition() validator — rejects illegal transitions like `submitted -> matched`
- New packages (app.submission, app.review) wired through `app.db.models` import side-effect so Alembic env.py metadata auto-discovers them

## Task Commits

1. **Task 1: Submission/FailureSuppression SQLModels + state frozenset** — `47c88c2` (feat)
2. **Task 2: Alembic 0005 migration + Settings model additions** — `47f3ab3` (feat)

## Files Created/Modified

- `app/submission/__init__.py` — package marker
- `app/submission/models.py` — Submission + FailureSuppression SQLModels
- `app/review/__init__.py` — package marker
- `app/review/states.py` — CANONICAL_JOB_STATUSES, _ALLOWED_TRANSITIONS, assert_valid_transition
- `app/db/migrations/versions/0005_phase5_submission.py` — create tables, indexes, partial unique index, settings columns; full downgrade
- `app/db/models.py` — Phase 5 import side-effect, Settings gains four new fields, `__all__` re-exports Submission/FailureSuppression

## Decisions Made

- **Partial UNIQUE via create_index, not UniqueConstraint.** Research Pitfall 9 confirms SQLite silently drops `sqlite_where` on `UniqueConstraint`. The migration uses `op.create_index("ux_submissions_job_sent", unique=True, sqlite_where=sa.text("status = 'sent'"))` which materialises as a real partial index in sqlite_master.
- **State machine includes legacy 'applied'.** Phase 3 writes `applied` as a terminal state for some code paths. Rather than retroactively remap those rows, `applied` joins CANONICAL_JOB_STATUSES as a terminal with no outgoing transitions — zero-churn back-compat.
- **Settings.notification_email nullable.** NULL means "send notifications to smtp_user" at runtime (a resolve_notification_recipient helper is a later-plan concern). Avoids forcing users to configure a second inbox upfront.
- **Settings.base_url default http://localhost:8000.** Matches the LAN-first deployment story; operators override via Settings UI when the app is exposed beyond localhost.
- **Submission.submitter column added now.** "email" default today, "playwright" in Phase 6 — avoids a schema bump mid-phase.
- **Python Settings model mirrors new columns.** The plan specified migration-only, but SQLModel attribute access (`Settings.notification_email`) requires field declarations. Added four Optional/typed fields to the model class matching the migration defaults — catches this in Task 2 before any downstream plan imports.

## Deviations from Plan

**None.** Both tasks executed exactly as written. One minor addition: the plan spec focused on the migration for Settings columns but the verify step (`Settings has attrs notification_email, base_url, submissions_paused, auto_holdout_margin_pct`) required matching SQLModel field declarations in `app/db/models.py::Settings`. Those four declarations were added alongside the migration in Task 2 — this is implicit in the verify step, not a deviation.

## Issues Encountered

- Local shell has `alembic` only reachable as `python -m alembic` (not on PATH). Worked around by running migrations via `python -m alembic upgrade head / downgrade -1`. Non-blocking.
- `app/tests/db/` directory does not yet exist for the `pytest -k "migration or schema"` verify step. Migration verification ran inline via Python snippets: partial index SQL inspection, duplicate-sent IntegrityError proof, downgrade/upgrade roundtrip, full suite re-run (216/216 green).

## Verification Evidence

- `python -m alembic upgrade head` then `downgrade -1` then `upgrade head` again — all clean, no errors.
- `sqlite_master` query returns `CREATE UNIQUE INDEX ux_submissions_job_sent ON submissions (job_id) WHERE status = 'sent'` — partial WHERE clause verified.
- Inserting two `(job_id=9999, status='failed')` rows then one `status='sent'` succeeds; a second `status='sent'` row raises `sqlite3.IntegrityError: UNIQUE constraint failed: submissions.job_id` — idempotency enforced.
- `from app.review.states import assert_valid_transition; assert_valid_transition('submitted', 'matched')` raises `ValueError: illegal transition 'submitted' -> 'matched'; allowed: ['confirmed', 'failed']`.
- `len(CANONICAL_JOB_STATUSES) == 13`.
- `from app.db.models import Submission, FailureSuppression` succeeds (re-exported).
- Full test suite: **216/216 passed** in 59s.

## Next Phase Readiness

- Schema foundation complete — Wave 2 plans (submitter, pipeline, review UI, notifications) can run in parallel against stable tables.
- `app.review.states` is importable today; any new Phase 5 code writing `Job.status` should route through `assert_valid_transition` as the uniform gate.
- `Settings.notification_email` is nullable — downstream notification plans must provide a runtime resolver (`notification_email or smtp_user`).
- Pattern confirmed: future partial-unique idempotency indexes on SQLite must use `op.create_index(..., sqlite_where=...)`; do not use `UniqueConstraint(..., sqlite_where=...)`.

## Self-Check: PASSED

All declared created files exist on disk:
- app/submission/__init__.py — FOUND
- app/submission/models.py — FOUND
- app/review/__init__.py — FOUND
- app/review/states.py — FOUND
- app/db/migrations/versions/0005_phase5_submission.py — FOUND
- .planning/phases/05-email-submission-review-queue/05-01-SUMMARY.md — FOUND (this file)

All commit hashes exist in git log:
- 47c88c2 — FOUND (Task 1)
- 47f3ab3 — FOUND (Task 2)

---
*Phase: 05-email-submission-review-queue*
*Completed: 2026-04-15*
