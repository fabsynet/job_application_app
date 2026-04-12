---
phase: 01-foundation-scheduler-safety-envelope
plan: 05
subsystem: onboarding + e2e
tags: [setup-wizard, multipart-upload, fernet-rotation, end-to-end-tests, readme]

# Dependency graph
requires:
  - phase: 01-04
    provides: dashboard, toggles, runs list, settings page, HTMX fragments, Pico.css, Fernet secrets CRUD
provides:
  - Setup wizard (3-step: resume upload, API keys, keywords) with skip path
  - Dashboard wizard redirect guard (Settings.wizard_complete)
  - Fernet rotation detection banner on dashboard
  - Phase 1 goal-backward end-to-end test suite (7 tests, all 6 must_haves asserted)
  - README.md with docker compose quickstart + env var documentation
affects: [Phase 2]

# Tech tracking
tech-stack:
  added: [FastAPI UploadFile multipart (python-multipart already in requirements)]
  patterns:
    - "Wizard writes wizard_complete only on step 3 POST or /setup/skip POST — partial completion does not flip the flag"
    - "Rotation banner probes a single Secret row decrypt on full dashboard render (not on HTMX fragment polls)"
    - "Integration tests reload app.web.routers.wizard alongside app.config to avoid stale get_settings reference across test boundaries"

key-files:
  created:
    - app/web/routers/wizard.py
    - app/web/templates/wizard/_layout.html.j2
    - app/web/templates/wizard/step_1_resume.html.j2
    - app/web/templates/wizard/step_2_secrets.html.j2
    - app/web/templates/wizard/step_3_keywords.html.j2
    - tests/integration/test_wizard_flow.py
    - tests/integration/test_fernet_rotation_banner.py
    - tests/integration/test_first_boot_end_to_end.py
    - README.md
  modified:
    - app/main.py
    - app/web/routers/dashboard.py
    - app/web/templates/dashboard.html.j2
    - tests/integration/test_dashboard_routes.py

key-decisions:
  - "Wizard writes wizard_complete only on step 3 or skip — going back and forth does not flip the flag"
  - "Wizard step 2 allows blank submissions (guidance, not a gate per CONTEXT.md)"
  - "Rotation banner does not delete unreadable secrets — preserved for forensic recovery"
  - "End-to-end tests run against the real lifespan with tmp_path data dirs, not mocks"
  - "Reload wizard module in test fixtures to avoid stale get_settings reference from importlib.reload(app.config)"

patterns-established:
  - "Wizard guard pattern: dashboard handler checks Settings.wizard_complete before rendering, redirects to /setup/1 if False"
  - "Rotation detection pattern: dashboard probes one Secret.decrypt before rendering, surfaces banner on InvalidFernetKey without auto-deleting data"

# Metrics
duration: ~30min
completed: 2026-04-11
---

# Phase 1 Plan 05: Setup Wizard and End-to-End Tests Summary

**First-run wizard (resume + API keys + keywords), Fernet rotation banner, goal-backward test suite asserting all 6 Phase 1 must_haves, and README with docker compose quickstart**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-04-11T20:00:00Z
- **Completed:** 2026-04-11T20:30:00Z
- **Tasks:** 3
- **Files modified:** 13

## Accomplishments
- Setup wizard with 3 steps and a skip path, integrated with dashboard redirect guard
- Fernet rotation detection banner on dashboard — surfaces remediation without data loss
- 19 new integration tests (9 wizard flow + 3 rotation banner + 7 end-to-end)
- All 6 Phase 1 must_haves assertable and green (87/87 total tests)
- README.md with complete user-facing setup documentation

## Task Commits

Each task was committed atomically:

1. **Task 1: Setup wizard routes + templates + dashboard redirect guard + rotation banner** - `5b356ed` (feat)
2. **Task 2: Wizard flow tests + rotation banner test** - `4d63fd7` (test)
3. **Task 3: End-to-end Phase 1 goal-backward test suite + README.md** - `768302f` (feat)

## Files Created/Modified
- `app/web/routers/wizard.py` - GET/POST /setup/1..3 + POST /setup/skip
- `app/web/templates/wizard/_layout.html.j2` - Wizard base template with step counter + skip button
- `app/web/templates/wizard/step_1_resume.html.j2` - DOCX upload form
- `app/web/templates/wizard/step_2_secrets.html.j2` - API key + SMTP credential form (encrypted)
- `app/web/templates/wizard/step_3_keywords.html.j2` - Keywords textarea
- `app/web/routers/dashboard.py` - Added wizard redirect guard + rotation banner detection
- `app/web/templates/dashboard.html.j2` - Renders rotation banner when present
- `app/main.py` - Registered wizard router before dashboard router
- `tests/integration/test_wizard_flow.py` - 9 tests covering happy path, skip, validation, persistence
- `tests/integration/test_fernet_rotation_banner.py` - 3 tests: rotated banner, no banner, health 200
- `tests/integration/test_first_boot_end_to_end.py` - 7 goal-backward tests for all Phase 1 must_haves
- `tests/integration/test_dashboard_routes.py` - Updated to seed wizard_complete=True
- `README.md` - Docker compose quickstart, env vars, wizard, rotation, security posture

## Decisions Made
- **Wizard flag timing:** wizard_complete is set only on step 3 POST or /setup/skip POST. Navigating between steps does not flip the flag, so an abandoned wizard on container restart re-enters at step 1.
- **Step 2 blanks allowed:** All credential fields are optional per CONTEXT.md "guidance, not a gate". Users configure secrets later from the Settings page.
- **Rotation banner preserves data:** Unreadable Secret rows are NOT deleted. The banner points users to Settings for re-entry, matching RESEARCH.md forensic preservation pitfall.
- **Rotation probe scope:** Only the full dashboard render probes Secret.decrypt (not HTMX fragment polls). Avoids repeated decrypt overhead on every 5-second status poll.
- **Test isolation fix:** Wizard module must be reloaded alongside app.config in integration test fixtures. The `from app.config import get_settings` import in wizard.py captures a function reference that becomes stale after `importlib.reload(app.config)`.
- **e2e tests substitute lifespan for docker:** Must-have #1 (docker compose up) is asserted via in-process lifespan startup rather than actual Docker daemon, since Docker availability is not guaranteed on the test host.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fix stale get_settings reference in wizard module across test boundaries**
- **Found during:** Task 3 (end-to-end test suite)
- **Issue:** After `importlib.reload(app.config)` in test fixtures, the wizard module's captured `get_settings` function reference still pointed to the OLD module's function. This caused wizard step 1 to write the uploaded resume to the PREVIOUS test's tmp_path instead of the current test's tmp_path, failing file existence assertions.
- **Fix:** Added `importlib.reload(app.web.routers.wizard)` after reloading `app.config` in all test reload helper functions.
- **Files modified:** tests/integration/test_wizard_flow.py, tests/integration/test_first_boot_end_to_end.py, tests/integration/test_fernet_rotation_banner.py
- **Verification:** Full suite passes (87/87) with tests in any order.
- **Committed in:** 768302f (Task 3 commit)

**2. [Rule 1 - Bug] Existing dashboard tests fail with 307 after wizard guard added**
- **Found during:** Task 1 (dashboard redirect guard)
- **Issue:** Existing dashboard integration tests expected GET / -> 200, but the wizard guard now redirects to /setup/1 when wizard_complete is False (fresh test DB).
- **Fix:** Seeded `wizard_complete=True` in the live_app fixture of `test_dashboard_routes.py` before yielding.
- **Files modified:** tests/integration/test_dashboard_routes.py
- **Verification:** All 7 existing dashboard tests pass without changes to assertions.
- **Committed in:** 5b356ed (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes necessary for test correctness. No scope creep.

## Issues Encountered

- **Docker must-have testing:** Must-have #1 ("docker compose up boots the app with SQLite on ./data volume") cannot be asserted deterministically on this host because Docker Desktop daemon availability is not guaranteed. The end-to-end test substitutes an in-process lifespan startup that runs the identical init_db / scheduler / Fernet / settings code path. Manual verification: run `docker compose up -d` on a clean machine, confirm `data/app.db` is created, and `curl localhost:8000/health` returns `{"status":"ok","scheduler_running":true}`.

## User Setup Required

None - no external service configuration required beyond the documented `.env` setup in README.md.

## Next Phase Readiness

**Phase 1 is complete.** All 6 must_haves from the phase scope are assertable and green:

1. SQLite on ./data volume, persistence across restart
2. Hourly heartbeat registered + run-lock prevents overlap
3. Dry-run toggle and kill-switch respected in real time
4. Fernet-encrypted secrets survive restart + zero PII in logs
5. Rate-limit envelope (daily cap, jittered delays, midnight reset) enforced
6. Setup wizard routes user through first-boot onboarding

**Ready for Phase 2:** Resume model extraction, job discovery, and the first real pipeline stage replacement.

**Outstanding concerns carried forward:**
- Docker image has not been built on this host (Docker Desktop daemon was not running). First `docker compose build` still pending.
- Local test venv is Python 3.11.9 but pyproject requires >=3.12. Tests run green on 3.11; production image uses 3.12+.
- requirements.txt should be split into prod vs dev (pytest/freezegun are test-only).
- HTMX loaded from CDN; offline LAN deployments need a local bundle.

## Self-Check: PASSED

---
*Phase: 01-foundation-scheduler-safety-envelope*
*Completed: 2026-04-11*
