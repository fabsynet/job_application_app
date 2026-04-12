---
phase: "03"
plan: "02"
subsystem: "discovery-backend"
tags: ["ats-api", "httpx", "dedup", "scoring", "pipeline", "asyncio"]
dependency_graph:
  requires: ["03-01"]
  provides: ["discovery-fetchers", "keyword-scoring", "dedup-fingerprint", "discovery-pipeline"]
  affects: ["03-04", "03-05", "03-06"]
tech_stack:
  added: []
  patterns: ["asyncio.gather parallel fetching", "SHA-256 fingerprint dedup", "substring keyword scoring", "rolling-average anomaly detection"]
key_files:
  created:
    - "app/discovery/fetchers.py"
    - "app/discovery/scoring.py"
    - "app/discovery/pipeline.py"
  modified:
    - "app/discovery/service.py"
    - "app/scheduler/service.py"
decisions:
  - id: "03-02-01"
    description: "detect_source returns (slug, source_type) tuple to match existing sources router contract"
  - id: "03-02-02"
    description: "validate_source returns (bool, str) tuple for router compatibility"
  - id: "03-02-03"
    description: "_execute_pipeline stores counts via self._last_counts attribute; wrapper's else-branch passes them to finalize_run to avoid double-finalize"
  - id: "03-02-04"
    description: "Pipeline uses session_factory context manager pattern -- separate sessions for load, fetch-status-update, persist, stats, and anomaly phases"
metrics:
  duration: "~8 min"
  completed: "2026-04-12"
---

# Phase 3 Plan 02: Discovery Backend (Fetchers, Scoring, Pipeline) Summary

**ATS fetchers for Greenhouse/Lever/Ashby with normalised output, SHA-256 dedup fingerprinting, case-insensitive partial keyword scoring, and the async pipeline that replaced the Phase 1 stub.**

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create fetchers, scoring, and service modules | 43443f9 | fetchers.py, scoring.py, service.py |
| 2 | Create discovery pipeline and integrate with scheduler | 9c84f93 | pipeline.py, scheduler/service.py |

## What Was Built

### ATS Fetchers (app/discovery/fetchers.py)
- `fetch_greenhouse` -- GET boards-api with `content=true`, maps HTML content to description via `strip_html` helper
- `fetch_lever` -- handles flat JSON array response (not wrapped in object), posted_date=None
- `fetch_ashby` -- uses `descriptionPlain` for scoring, `descriptionHtml` for display
- `detect_source` -- parses Greenhouse/Lever/Ashby URLs and plain slugs, returns `(slug, source_type)`
- `validate_source` -- hits real ATS API with 10s timeout, probes all three for unknown slugs
- `fetch_source` -- dispatcher that routes to the correct fetcher by source_type

### Keyword Scoring (app/discovery/scoring.py)
- `job_fingerprint` -- SHA-256 of canonicalised `(url|title|company)`, strips query/fragment/trailing slash
- `score_job` -- case-insensitive partial substring matching, returns `(score_0_to_100, matched, unmatched)`

### Discovery Service (app/discovery/service.py)
- Full CRUD for sources (get_enabled, get_all, create, toggle, delete, update_fetch_status)
- Job operations (get_by_fingerprint, create, list with sorting, get_detail, update_status)
- DiscoveryRunStats (save_discovery_stats, get_rolling_average with min 3 data points)

### Pipeline (app/discovery/pipeline.py)
- `run_discovery` orchestrates: load sources/keywords, parallel fetch, dedup, score, persist, stats, anomaly check
- Uses `asyncio.gather(*tasks, return_exceptions=True)` for parallel fetching
- Failed sources get error status, do not crash the pipeline
- Jobs at/above threshold get `status=matched`, below get `status=discovered`
- Anomaly detection: today < 20% of 7-day rolling avg with >= 3 data points

### Scheduler Integration (app/scheduler/service.py)
- `_execute_stub` replaced with `_execute_pipeline`
- Kill-switch checkpoints before and after discovery stage
- Pipeline counts merged into Run.counts via finalize_run

## Decisions Made

1. **detect_source tuple order** -- returns `(slug, source_type)` to match the existing sources router contract from plan 03-03 (not `(source_type, slug)` as originally specified in the plan)
2. **validate_source return type** -- returns `(bool, str)` to match existing router usage
3. **Counts passing pattern** -- `_execute_pipeline` stores counts on `self._last_counts`; the wrapper's else-branch passes them to `finalize_run` to avoid double-finalizing the Run row
4. **Session lifecycle** -- separate session scopes for load, fetch-status-update, persist, stats, and anomaly detection to keep transactions short

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] detect_source return order adjusted for router compatibility**
- **Found during:** Task 1
- **Issue:** Plan specified `detect_source` returning `(source_type, slug)` but the existing sources router (from 03-03 wave) calls `slug, source_type = detect_source(...)` expecting `(slug, source_type)`
- **Fix:** Reversed the return tuple order to `(slug, source_type)` to maintain compatibility
- **Files modified:** app/discovery/fetchers.py

**2. [Rule 3 - Blocking] validate_source return type adjusted for router compatibility**
- **Found during:** Task 1
- **Issue:** Plan specified `validate_source` returning `bool | tuple[str, str]` but the existing router calls `is_valid, error_msg = await validate_source(...)` expecting `(bool, str)`
- **Fix:** Changed return type to `tuple[bool, str]` matching the router's destructuring pattern
- **Files modified:** app/discovery/fetchers.py

**3. [Rule 1 - Bug] Prevented double-finalize on Run row**
- **Found during:** Task 2
- **Issue:** Plan said to call `finalize_run` inside `_execute_pipeline`, but the wrapper's else-branch already calls `finalize_run(status="succeeded")`, which would double-finalize
- **Fix:** Pipeline stores counts on `self._last_counts`; wrapper passes them to `finalize_run`
- **Files modified:** app/scheduler/service.py

## Verification

- All 118 existing tests pass (stub replacement preserves safety envelope)
- `score_job("I know Python3 and Django", ["python", "java"])` returns `(50, ["python"], ["java"])`
- `job_fingerprint` produces consistent hashes for equivalent inputs with different casing/whitespace/query params
- `detect_source` correctly handles Greenhouse/Lever/Ashby URLs and plain slugs
- Pipeline import succeeds, all three fetcher modules importable with correct exports

## Next Phase Readiness

No blockers. The discovery backend is ready for:
- 03-04/05: Jobs page UI and sources settings section (can call `list_jobs`, `get_job_detail`, etc.)
- 03-06: Dashboard integration (discovery counts in Run.counts, anomaly data available)

## Self-Check: PASSED
