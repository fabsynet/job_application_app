---
phase: 02-configuration-profile-resume-upload
plan: 05
subsystem: testing
tags: [pytest, httpx, integration-tests, asyncio, python-docx, mock]

# Dependency graph
requires:
  - phase: 02-02
    provides: Profile form + resume upload with DOCX extraction
  - phase: 02-03
    provides: Keywords, threshold, schedule, budget sections
  - phase: 02-04
    provides: Credential save + validation with mocked network calls
provides:
  - 31 integration tests covering all 8 CONF requirements
  - Full green suite (118 tests) proving Phase 2 feature completeness
affects: [03-discovery-matching]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Phase 2 test fixture pattern: live_app with tmp_path, module reloads, lifespan context"
    - "DOCX creation in tests via python-docx in-memory buffer"
    - "Credential validation mocked at module level via unittest.mock.patch"

key-files:
  created:
    - tests/test_phase2_settings.py
    - tests/test_phase2_resume.py
    - tests/test_phase2_credentials.py
  modified: []

key-decisions:
  - "Resume replace test verifies content via python-docx re-read rather than filesystem glob (data_dir indirection)"
  - "Credential validation mocked via patch on app.credentials.validation module, not router-level"

patterns-established:
  - "Phase 2 integration tests: same live_app fixture pattern as Phase 1 with wizard module reload"
  - "DOCX test helper: _make_docx() creates minimal files with headings for structured preview testing"

# Metrics
duration: 5min
completed: 2026-04-11
---

# Phase 2 Plan 5: Integration Tests Summary

**31 integration tests covering all 8 CONF requirements: settings, profile, resume upload, keywords, threshold, schedule, budget, and credentials with mocked validation**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-12T04:28:33Z
- **Completed:** 2026-04-12T04:33:31Z
- **Tasks:** 3
- **Files created:** 3

## Accomplishments
- 18 settings tests: sidebar, section navigation, mode, keywords (add/dedup/remove/empty), threshold (save/validation), schedule (enable/disable), budget (save/no-limit), profile (save/optional/edit/render)
- 5 resume tests: DOCX upload, non-DOCX rejection, replace, preview with headings, no-upload form
- 8 credential tests: Anthropic valid/invalid/timeout, SMTP valid/invalid, status configured/not-set, never-revealed
- Full suite: 118 tests pass (87 Phase 1 + 31 Phase 2), zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Settings integration tests** - `4b13681` (test)
2. **Task 2: Resume upload + credential validation tests** - `2cd44e3` (test)
3. **Task 3: Profile tests + full suite verification** - `0d2e321` (test)

## Files Created/Modified
- `tests/test_phase2_settings.py` - 432 lines, 18 tests for mode/keywords/threshold/schedule/budget/profile
- `tests/test_phase2_resume.py` - 187 lines, 5 tests for DOCX upload/replace/preview
- `tests/test_phase2_credentials.py` - 261 lines, 8 tests for credential save/validate/status

## Decisions Made
- Resume replace test reads the actual DOCX content back via python-docx rather than checking filesystem glob, because save_resume uses get_settings().data_dir which may resolve differently from tmp_path in fixture
- Credential validation mocked at `app.credentials.validation` module level using `unittest.mock.patch`, matching the dynamic import pattern used in the router

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed wizard module reload path**
- **Found during:** Task 1 (Settings integration tests)
- **Issue:** Plan referenced `app.web.wizard` but module is at `app.web.routers.wizard`
- **Fix:** Changed import to `app.web.routers.wizard`
- **Files modified:** tests/test_phase2_settings.py
- **Committed in:** 4b13681

**2. [Rule 1 - Bug] Fixed resume replace test assertion**
- **Found during:** Task 2 (Resume upload tests)
- **Issue:** `tmp_path / "resumes"` glob found 0 files because save_resume writes to `get_settings().data_dir / "resumes"` which resolves via cached settings, not directly from tmp_path
- **Fix:** Changed assertion to read DOCX content back via `get_resume_path()` and verify replacement
- **Files modified:** tests/test_phase2_resume.py
- **Committed in:** 2cd44e3

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Minor fixes for test correctness. No scope creep.

## Issues Encountered
None beyond the auto-fixed items above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 complete: all 5 plans executed, 118 tests green
- All CONF requirements (CONF-01 through CONF-08) verified by automated tests
- Ready to proceed to Phase 3 (Discovery & Matching)

## Self-Check: PASSED

---
*Phase: 02-configuration-profile-resume-upload*
*Completed: 2026-04-11*
