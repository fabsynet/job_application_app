---
phase: "03"
plan: "06"
subsystem: "testing"
tags: ["pytest", "unit-tests", "integration-tests", "discovery", "scoring", "dedup"]
dependency_graph:
  requires: ["03-02", "03-03", "03-04", "03-05"]
  provides: ["Phase 3 test coverage: 57 new tests covering all 8 active requirements"]
  affects: ["04-xx (future phases can run full regression)"]
tech_stack:
  added: []
  patterns: ["mock httpx responses", "live_app fixture pattern for integration tests"]
key_files:
  created:
    - tests/test_phase3_discovery.py
    - tests/test_phase3_integration.py
  modified:
    - app/discovery/pipeline.py
decisions:
  - id: "03-06-01"
    description: "Pipeline posted_date parsing: added _parse_posted_date to convert ISO strings from ATS APIs to datetime objects"
    rationale: "SQLite datetime column rejects raw strings; fetchers return API JSON strings unchanged"
metrics:
  duration: "~9 min"
  completed: "2026-04-12"
---

# Phase 3 Plan 6: Phase 3 Test Coverage Summary

**One-liner:** 57 new tests (38 unit + 19 integration) proving all 8 active Phase 3 requirements, plus a bug fix for posted_date ISO string parsing in the pipeline.

## Task Commits

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | Unit tests for discovery modules | `4a96a16` | 38 tests: detect_source, score_job, job_fingerprint, fetcher parsing, strip_html, anomaly detection |
| 2 | Integration tests for pipeline and routes | `85d2c49` | 19 tests: pipeline e2e, dedup, scoring, jobs CRUD, sources CRUD, dashboard discovery, anomaly banner. Bug fix: _parse_posted_date |

## Requirement Coverage Matrix

| Requirement | Test File | Test Count | Description |
|-------------|-----------|------------|-------------|
| DISC-01 | test_phase3_discovery.py | 3 | Greenhouse fetcher parsing, content=true param |
| DISC-02 | test_phase3_discovery.py | 2 | Lever flat array parsing, posted_date=None |
| DISC-03 | test_phase3_discovery.py | 1 | Ashby descriptionPlain + descriptionHtml |
| DISC-04 | (deferred) | 0 | Web search explicitly deferred |
| DISC-05 | test_phase3_discovery.py + integration | 9 | Source detection + pipeline persists normalised fields |
| DISC-06 | test_phase3_discovery.py + integration | 7 | Fingerprint canonicalisation + pipeline dedup |
| MATCH-01 | test_phase3_discovery.py + integration | 8 | Case-insensitive partial scoring + pipeline scoring |
| MATCH-02 | test_phase3_integration.py | 1 | Status assignment: matched vs discovered |
| MATCH-03 | test_phase3_integration.py | 1 | Score + matched_keywords stored pipe-delimited |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pipeline posted_date ISO string crash**

- **Found during:** Task 2 (pipeline integration test)
- **Issue:** `pipeline.py` stored raw ISO string from ATS API JSON (e.g. `"2026-03-15T12:00:00Z"`) directly into `Job.posted_date: Optional[datetime]`, causing SQLite TypeError
- **Fix:** Added `_parse_posted_date()` helper that converts ISO strings to datetime objects, passes through None and existing datetime instances
- **Files modified:** app/discovery/pipeline.py
- **Commit:** 85d2c49

## Test Suite Status

- **Total tests:** 175 (all green)
- **Phase 1:** 80 tests
- **Phase 2:** 38 tests  
- **Phase 3:** 57 tests (38 unit + 19 integration)

## Self-Check: PASSED
