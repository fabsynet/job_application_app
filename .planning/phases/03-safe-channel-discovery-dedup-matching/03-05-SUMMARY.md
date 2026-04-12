---
phase: "03"
plan: "05"
subsystem: "dashboard-discovery-ui"
tags: ["htmx", "jinja2", "discovery", "anomaly-detection", "dashboard"]
dependency_graph:
  requires: ["03-01", "03-02"]
  provides: ["dashboard-discovery-summary", "anomaly-banner", "run-detail-discovery-stats"]
  affects: ["03-06"]
tech_stack:
  added: []
  patterns: ["cookie-based dismiss state", "outerjoin for optional Source display"]
key_files:
  created:
    - "app/web/templates/partials/dashboard_discovery_summary.html.j2"
    - "app/web/templates/partials/anomaly_banner.html.j2"
  modified:
    - "app/web/routers/dashboard.py"
    - "app/web/templates/dashboard.html.j2"
    - "app/web/routers/runs.py"
    - "app/web/templates/run_detail.html.j2"
decisions:
  - id: "03-05-01"
    description: "Anomaly dismiss uses cookie (dismissed_anomaly_run_id) keyed on run_id -- no DB schema change needed"
  - id: "03-05-02"
    description: "Discovery summary queries DiscoveryRunStats table joined with Source, not Run.counts JSON -- per-source breakdown with display names"
  - id: "03-05-03"
    description: "POST /dismiss-anomaly returns empty HTML for hx-swap=delete pattern"
metrics:
  duration: "~5 min"
  completed: "2026-04-12"
---

# Phase 3 Plan 05: Dashboard Discovery UI Summary

**Per-source discovery counts on dashboard and run detail, dismissable yellow anomaly banner with cookie-based persistence, red error badges for failed sources.**

## Task Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add discovery summary and anomaly banner to dashboard | 23f4c10 | dashboard.py, anomaly_banner.html.j2, dashboard_discovery_summary.html.j2 |
| 2 | Enrich run detail view with per-source discovery stats | e062568 | runs.py, run_detail.html.j2 |

## What Was Built

### Dashboard Discovery Summary (Task 1)
- **_get_discovery_context helper** in dashboard.py: queries latest succeeded Run, joins DiscoveryRunStats with Source for per-source breakdown, extracts anomaly warnings from Run.counts
- **dashboard_discovery_summary.html.j2**: grid of per-source cards showing discovered/matched counts, with red ERROR badge for failed sources and total row
- **anomaly_banner.html.j2**: yellow warning banner listing anomaly messages, dismiss button uses hx-post="/dismiss-anomaly" with hx-swap="delete"
- **POST /dismiss-anomaly**: sets httponly cookie with current run_id; banner reappears only when a new run produces fresh anomalies
- Dashboard template updated to include both partials

### Run Detail Discovery Stats (Task 2)
- **runs.py run_detail route**: queries DiscoveryRunStats outerjoin Source for the specific run_id
- **run_detail.html.j2**: discovery results table with Source, Type, Discovered, Matched, Status columns; green "OK" or red error badge; total row at bottom

## Decisions Made

1. **Cookie-based anomaly dismiss** -- dismissed_anomaly_run_id cookie stores the run_id of the last dismissed anomaly. When a new run produces anomalies, the run_id changes and the banner reappears. No DB schema change needed.
2. **DiscoveryRunStats as source of truth** -- per-source counts come from the DiscoveryRunStats table (not Run.counts JSON) so we get proper Source display names via join.
3. **Empty HTML response for dismiss** -- POST /dismiss-anomaly returns empty content with the cookie set; HTMX hx-swap="delete" removes the banner DOM element.

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED
