---
phase: 02-configuration-profile-resume-upload
plan: 01
subsystem: configuration
tags: [sidebar, settings, database, migration, profile, mode-toggle, htmx]

dependency_graph:
  requires: [01-01, 01-04]
  provides: [sidebar-shell, phase2-schema, mode-toggle, section-endpoints]
  affects: [02-02, 02-03, 02-04, 02-05]

tech_stack:
  added: [python-docx==1.1.2]
  patterns: [sidebar-section-partials, htmx-section-loading, flash-messages]

file_tracking:
  key_files:
    created:
      - app/db/migrations/versions/0002_phase2_config.py
      - app/web/templates/partials/settings_sidebar.html.j2
      - app/web/templates/partials/settings_mode.html.j2
      - app/web/templates/partials/settings_limits.html.j2
      - app/web/templates/partials/settings_safety.html.j2
      - app/web/templates/partials/flash_message.html.j2
      - app/web/templates/partials/settings_placeholder.html.j2
    modified:
      - app/db/models.py
      - app/web/routers/settings.py
      - app/web/templates/settings.html.j2
      - app/web/static/app.css
      - requirements.txt
      - tests/integration/test_settings_routes.py

decisions:
  - id: 02-01-01
    summary: "Settings page uses sidebar shell with HTMX section loading"
  - id: 02-01-02
    summary: "POST /settings/limits returns partial HTML (not 303 redirect) for HTMX compatibility"
  - id: 02-01-03
    summary: "Safety toggles (kill-switch, dry-run) accessible from both dashboard and settings sidebar"
  - id: 02-01-04
    summary: "Placeholder partials for unimplemented sections prevent 404 errors"

metrics:
  duration: ~5 min
  completed: 2026-04-12
---

# Phase 2 Plan 1: Database Foundation + Sidebar Layout Shell Summary

**One-liner:** Sidebar-navigated settings page with Mode toggle, Phase 1 settings migrated into partials, Profile table + 10 new Settings columns via migration, python-docx dependency added.

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Database migration + Profile model + python-docx | 1970f43 | models.py, 0002_phase2_config.py, requirements.txt |
| 2 | Sidebar layout shell + section endpoints + merge Phase 1 | 86a3c03 | settings.py, settings.html.j2, 6 new partials, app.css |

## What Was Built

### Database Schema (Task 1)
- Extended Settings model with 10 new Phase 2 columns: auto_mode, match_threshold, schedule_enabled, quiet_hours_start/end, budget_cap/spent_dollars, budget_month, resume_filename, resume_uploaded_at
- Created Profile model (singleton table) with 11 fields for auto-filling application forms
- Alembic migration 0002_phase2_config adds columns with proper server_defaults for SQLite
- Added python-docx==1.1.2 to requirements.txt

### Sidebar Layout (Task 2)
- Settings page now uses flexbox sidebar (220px aside + flex:1 content area)
- 10 sidebar section links: Mode, Profile, Resume, Keywords, Threshold, Credentials, Schedule, Budget, Rate Limits, Safety
- HTMX-driven section loading via GET /settings/section/{name}
- Active sidebar link highlighted via hx-on::after-request JS

### Section Endpoints
- GET /settings/section/{name} - loads any section partial
- POST /settings/mode - saves auto_mode, returns partial with flash
- POST /settings/limits - refactored from redirect to partial response
- POST /settings/safety - saves kill_switch + dry_run, returns partial with flash
- Placeholder partials for Profile, Resume, Keywords, Threshold, Credentials, Schedule, Budget

### Flash Messages
- Reusable flash_message partial with auto-dismiss (3 second timeout)
- Green left-border for success, red for error

## Decisions Made

1. **Sidebar + HTMX sections pattern:** Each settings section is a separate partial loaded via HTMX hx-get. This means each subsequent plan only needs to create its partial template and POST endpoint.
2. **Limits endpoint returns partial (not redirect):** Changed POST /settings/limits from returning 303 redirect to returning the limits partial with a flash message, consistent with all other section endpoints.
3. **Safety section in sidebar:** Kill-switch and dry-run toggles are now accessible from both the dashboard (existing /toggles routes) and the settings sidebar (new /settings/safety route).
4. **Placeholder sections:** Unimplemented sections return a "Coming soon" partial so the sidebar is fully navigable without errors.

## Deviations from Plan

None - plan executed exactly as written.

## Test Results

All 87 existing tests pass. Two test assertions updated:
- `test_settings_page_renders`: Updated to check for sidebar layout and Mode section instead of old flat layout
- `test_save_limits_updates_live_rate_limiter`: Updated to expect 200 partial response instead of 303 redirect

## Next Phase Readiness

All subsequent Phase 2 plans can now:
- Create their section partial template
- Add a POST endpoint to the settings router
- Register in _SECTION_MAP (replacing the placeholder entry)
- The database schema supports all Phase 2 data

## Self-Check: PASSED
