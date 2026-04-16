---
phase: "06"
plan: "04"
subsystem: "learning-loop"
tags: ["llm", "semantic-matching", "crud", "unknown-fields", "needs-info"]
dependency-graph:
  requires: ["06-01"]
  provides: ["SavedAnswer CRUD", "UnknownField persistence", "LLM semantic matcher", "needs-info aggregation"]
  affects: ["06-05", "06-06", "06-07", "06-08"]
tech-stack:
  added: []
  patterns: ["LLM batch matching", "graceful degradation on LLM failure", "label normalization for dedup"]
key-files:
  created:
    - app/learning/service.py
    - app/learning/matcher.py
    - app/learning/needs_info.py
    - tests/learning/__init__.py
    - tests/learning/test_service.py
    - tests/learning/test_matcher.py
    - tests/learning/test_needs_info.py
  modified: []
decisions:
  - id: "DEC-0604-01"
    title: "No confidence threshold for LLM matching"
    choice: "Auto-fill if LLM says match"
    why: "Per locked design decision — simplicity over false-negative risk"
  - id: "DEC-0604-02"
    title: "Graceful degradation on LLM failure"
    choice: "Return all-None matches instead of raising"
    why: "Pipeline continues without auto-fill rather than blocking"
metrics:
  duration: "~4 min"
  completed: "2026-04-15"
---

# Phase 6 Plan 4: Learning Service + Semantic Matcher Summary

SavedAnswer CRUD with label normalization, UnknownField bulk persistence with dedup, LLM semantic matcher batching all labels in one call, and needs-info aggregation queries for the resolution dashboard.

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | SavedAnswer CRUD + UnknownField persistence | bbfb1d9 | app/learning/service.py, tests/learning/test_service.py |
| 2 | LLM semantic matcher + needs-info aggregation | 0273df7 | app/learning/matcher.py, app/learning/needs_info.py, tests/learning/test_matcher.py, tests/learning/test_needs_info.py |

## Decisions Made

1. **No confidence threshold** (DEC-0604-01): LLM match results are accepted as-is. If the LLM says two labels are equivalent, the answer is auto-filled. No secondary confidence gate.

2. **Graceful degradation** (DEC-0604-02): When the LLM call fails (timeout, error, malformed JSON), `find_matching_answers` returns all-None instead of raising. The submission pipeline proceeds without auto-fill for that batch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `func.case` SQLAlchemy API**

- **Found during:** Task 2
- **Issue:** `func.case()` is not a valid SQLAlchemy construct; `case()` must be imported directly from `sqlalchemy`
- **Fix:** Changed `func.case(...)` to `case(...)` with direct import
- **Files modified:** app/learning/needs_info.py
- **Commit:** 0273df7

## Test Summary

- **33 tests total**, all passing
- Task 1: 17 tests (CRUD, ordering, dedup, resolve_all_for_job)
- Task 2: 16 tests (match/unmatch/empty/failure, batch call, reuse increment, aggregation, detail)

## Next Phase Readiness

All learning data-access and matching functions are ready for consumption by:
- 06-05 (form filler pipeline) — uses `try_match_and_fill` and `create_unknown_fields`
- 06-06/07 (dashboard) — uses `get_needs_info_jobs`, `get_needs_info_detail`, `resolve_all_for_job`

## Self-Check: PASSED
