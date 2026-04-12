---
phase: 03-safe-channel-discovery-dedup-matching
plan: 03
subsystem: web-ui
tags: [htmx, fastapi, settings, sources, ats, validation]

dependency_graph:
  requires: [03-01, 03-02]
  provides: [Sources settings UI, sources CRUD routes, sidebar integration]
  affects: [03-04, 03-05, 03-06]

tech_stack:
  added: []
  patterns: [sources router with HTMX partial swap, inline validation errors, settings section enrichment]

key_files:
  created:
    - app/web/routers/sources.py
    - app/web/templates/partials/settings_sources.html.j2
  modified:
    - app/web/routers/settings.py
    - app/web/templates/partials/settings_sidebar.html.j2
    - app/main.py

decisions:
  - Sources router uses _render_sources helper following _render_section pattern from settings.py
  - Toggle endpoint returns empty 200 with HX-Reswap none header (no DOM update needed)
  - Delete endpoint returns empty 200 for hx-swap outerHTML row removal
  - Unknown source type triggers probe of all three ATS APIs (greenhouse, lever, ashby) sequentially
  - display_name defaults to slug (refinement deferred)
  - Sources section positioned after Keywords in sidebar ordering

metrics:
  duration: ~4 min
  completed: 2026-04-12
---

# Phase 3 Plan 03: Sources Settings UI Summary

**HTMX-powered Sources settings section with add/validate/toggle/remove CRUD, inline error display, and settings sidebar integration for managing ATS board sources.**

## What Was Done

### Task 1: Create sources router with CRUD + validation
Created `app/web/routers/sources.py` with four endpoints:
- **GET /settings/sources** -- Renders sources section partial with all sources
- **POST /settings/sources** -- Adds new source: detect type from URL/slug, validate against real ATS API, persist if valid, show inline error if not
- **POST /settings/sources/{id}/toggle** -- Toggle enable/disable via checkbox switch
- **DELETE /settings/sources/{id}** -- Remove source with confirmation

Created stub files for `app/discovery/fetchers.py` and `app/discovery/service.py` (parallel agent 03-02 was still in progress). These stubs provided the import chain (`detect_source`, `validate_source`, `get_all_sources`, `create_source`, `toggle_source`, `delete_source`) so the router could be verified. The parallel agent subsequently replaced these stubs with full implementations.

### Task 2: Create sources template and integrate into settings sidebar
Created `app/web/templates/partials/settings_sources.html.j2`:
- Section header with description text
- Add source form with `hx-post` targeting the sources section
- Inline error display for validation failures
- Source table with columns: Company, Type (badge), Status (Error/OK/Pending), Enabled (switch toggle), Remove button
- Red "Error" badge with tooltip for sources with `last_fetch_status == "error"`
- Empty state message when no sources configured
- Source count summary

Updated `app/web/routers/settings.py`:
- Added "sources" to `_SECTION_MAP` after "keywords"
- Added context enrichment for sources section (loads all sources via `get_all_sources`)

Updated `app/web/templates/partials/settings_sidebar.html.j2`:
- Added "Sources" link after "Keywords" in sidebar navigation

Updated `app/main.py`:
- Registered sources router via `app.include_router(sources_router.router)`

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create sources router with CRUD + validation | e9a68f7 | app/web/routers/sources.py, app/discovery/fetchers.py (stub), app/discovery/service.py (stub) |
| 2 | Create sources template and integrate into settings sidebar | 30f535c | settings_sources.html.j2, settings.py, settings_sidebar.html.j2, main.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created stub fetchers.py and service.py for import chain**
- **Found during:** Task 1
- **Issue:** Plan 03-02 (parallel agent) had not yet created `app/discovery/fetchers.py` and `app/discovery/service.py`, blocking the sources router import
- **Fix:** Created minimal stub files with the expected function signatures (`detect_source`, `validate_source`, `get_all_sources`, `create_source`, `toggle_source`, `delete_source`)
- **Files created:** app/discovery/fetchers.py, app/discovery/service.py
- **Commit:** e9a68f7
- **Resolution:** The parallel agent (03-02) subsequently replaced these stubs with full implementations during execution. The final state has complete implementations.

## Verification

- Sources router imports successfully: `from app.web.routers.sources import router` passes
- All 118 existing tests pass (no regressions)
- Sources section added to settings sidebar and section map
- Router registered in main.py

## Notes

- The fetchers.py and service.py files were initially created as stubs by this plan but were overwritten by the parallel 03-02 agent with full implementations. Only the sources router and template are uniquely owned by this plan.
- Validation against real ATS APIs requires network access; the flow handles failures gracefully with inline error messages.

## Self-Check: PASSED
