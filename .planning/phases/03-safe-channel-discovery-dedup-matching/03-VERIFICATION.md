---
phase: 03-safe-channel-discovery-dedup-matching
verified: 2026-04-12T00:00:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "The normalized job schema (title, company, location, description, url, source, posted_date) is visible in the UI for every discovered job regardless of source"
    status: failed
    reason: "location field is stored in the Job model and populated by all three fetchers, but is not rendered in any template - neither the jobs table row nor the job_detail_inline panel exposes it"
    artifacts:
      - path: "app/web/templates/partials/jobs_table.html.j2"
        issue: "Table columns are title, company, source, score, posted_date, status - no location column"
      - path: "app/web/templates/partials/job_detail_inline.html.j2"
        issue: "Detail panel shows title, company, url, description, keyword chips, score - no location field rendered"
    missing:
      - "Render job.location in the detail panel (app/web/templates/partials/job_detail_inline.html.j2)"
      - "Optionally surface location in the table row for quick scanning"
---
# Phase 3: Safe Channel Discovery, Dedup and Matching - Verification Report

Phase Goal: On every hourly tick, the app pulls jobs from Greenhouse/Lever/Ashby public JSON APIs, normalizes them, deduplicates against history, scores them against the user keywords, and queues matched jobs with zero submission risk and zero ToS exposure.

Verified: 2026-04-12
Status: gaps_found
Re-verification: No - initial verification

---

## Goal Achievement

### Observable Truths

Truth 1 - User sees real jobs in the UI within one hourly cycle: VERIFIED
Evidence: scheduler/service.py _execute_pipeline calls run_discovery. APScheduler CronTrigger(minute=0) fires hourly. GET /jobs renders jobs.html.j2 via list_jobs(). Full fetch->dedup->score->persist->UI pipeline wired end-to-end.

Truth 2 - A job cross-posted on two sources never shows up twice: VERIFIED
Evidence: job_fingerprint() SHA-256 hashes clean_url|clean_title|clean_company. pipeline.py lines 150-153 calls get_job_by_fingerprint() and skips existing records. Integration test test_dedup_prevents_duplicates confirms counts2[new] == 0 on second run.
Truth 3 - User sees each matched job keyword-overlap score, only at/above threshold jobs are queued: VERIFIED
Evidence: jobs_table.html.j2 renders color-coded score badges (green >= threshold, yellow >= 50% threshold, gray below). pipeline.py sets status=matched if score >= threshold else discovered. Queue button only shown for status==discovered and score < threshold.

Truth 4 - User can see per-source discovery counts and anomaly alerts in the run log: VERIFIED
Evidence: runs.py queries DiscoveryRunStats outerjoin Source per run. run_detail.html.j2 renders Source/Type/Discovered/Matched/Status table with totals. Dashboard includes anomaly_banner.html.j2. pipeline.py checks today_count < rolling_avg * 0.20 with >= 3 data points.

Truth 5 - Normalized job schema (title, company, location, description, url, source, posted_date) visible in UI: FAILED
Evidence: location field stored in Job model (models.py line 46) and populated by all three fetchers, but not rendered in any template. Table shows title/company/source/score/posted_date/status. Detail panel shows title/company/url/description/keywords/score. location absent from both jobs_table.html.j2 and job_detail_inline.html.j2.

Score: 4/5 truths verified

---

## Required Artifacts

app/discovery/models.py - VERIFIED - 74 lines, Source/Job/DiscoveryRunStats SQLModel classes with all required fields
app/db/migrations/versions/0003_phase3_discovery.py - VERIFIED - creates 3 tables, unique index on jobs.fingerprint, 5 indexes, FK constraints, chains from 0002
app/discovery/fetchers.py - VERIFIED - 288 lines, Greenhouse content=true, Lever flat array posted_date=None, Ashby descriptionPlain/descriptionHtml, detect_source, validate_source
app/discovery/scoring.py - VERIFIED - 70 lines, SHA-256 job_fingerprint, case-insensitive partial score_job returning (score, matched, unmatched)
app/discovery/service.py - VERIFIED - 252 lines, all 13 CRUD functions, rolling average with minimum 3 data points
app/discovery/pipeline.py - VERIFIED - 243 lines, asyncio.gather return_exceptions=True, dedup, score vs threshold, DiscoveryRunStats, anomaly 20%, _parse_posted_date
app/scheduler/service.py - VERIFIED - _execute_pipeline calls run_discovery, kill-switch checkpoints before and after, _last_counts pattern for finalize_run
app/web/routers/sources.py - VERIFIED - 172 lines, GET/POST/toggle/DELETE, detect+validate before create, inline error display
app/web/templates/partials/settings_sources.html.j2 - VERIFIED - 73 lines, add form, source table with toggle switch and remove button, error badge, empty state
app/web/routers/jobs.py - VERIFIED - 126 lines, GET/jobs, GET/jobs/{id}/detail, POST/jobs/{id}/queue, HTMX sort partials
app/web/templates/jobs.html.j2 - VERIFIED - 38 lines, HTMX sort macros on 6 columns, jobs-body target for HTMX swap
app/web/templates/partials/jobs_table.html.j2 - PARTIAL - 26 lines, color-coded badges, click-to-expand, MISSING location column
app/web/templates/partials/job_detail_inline.html.j2 - PARTIAL - 43 lines, HTML description, keyword chips, queue button, MISSING location field
app/web/routers/dashboard.py - VERIFIED - _get_discovery_context queries latest run, DiscoveryRunStats+Source outerjoin, anomaly warnings, cookie dismiss
app/web/templates/partials/dashboard_discovery_summary.html.j2 - VERIFIED - grid of source cards with discovered/matched counts and ERROR badge
app/web/templates/partials/anomaly_banner.html.j2 - VERIFIED - yellow banner, anomaly list, hx-post dismiss-anomaly hx-swap=delete

---

## Key Link Verification

app/scheduler/service.py -> app/discovery/pipeline.py via run_discovery in _execute_pipeline: WIRED (line 246, two kill-switch checkpoints sandwich the call)
app/discovery/pipeline.py -> app/discovery/fetchers.py via asyncio.gather: WIRED (lines 80-84, return_exceptions=True)
app/discovery/pipeline.py -> app/discovery/scoring.py via score_job + job_fingerprint: WIRED (lines 142-156 in per-job loop)
app/web/routers/jobs.py -> app/discovery/service.py via list_jobs/get_job_detail/update_job_status: WIRED
app/web/routers/sources.py -> app/discovery/fetchers.py via detect_source + validate_source: WIRED (lines 90-122)
app/web/routers/dashboard.py -> app/discovery/models.py via DiscoveryRunStats+Source outerjoin: WIRED (lines 121-128)
app/web/routers/runs.py -> app/discovery/models.py via DiscoveryRunStats+Source per run_id: WIRED (lines 73-88)
app/main.py -> sources_router + jobs_router via app.include_router(): WIRED (lines 53-54 import, 176-177 register)
app/web/routers/settings.py -> settings_sources.html.j2 via _SECTION_MAP sources entry: WIRED (line 58 registered, lines 95-98 get_all_sources)

---

## Requirements Coverage

DISC-01 (Greenhouse): SATISFIED - fetch_greenhouse content=true, correct field mapping, 3 unit tests
DISC-02 (Lever): SATISFIED - fetch_lever flat array, posted_date=None, 2 unit tests
DISC-03 (Ashby): SATISFIED - fetch_ashby descriptionPlain/descriptionHtml, publishedAt, 1 unit test
DISC-04 (Web search): DEFERRED - explicitly deferred per research decision, no implementation
DISC-05 (Normalized schema): PARTIAL - all 7 fields in DB, 6/7 visible in UI, location missing from both templates
DISC-06 (Dedup): SATISFIED - SHA-256 fingerprint, pipeline skips duplicates, integration test confirms 0 new on second identical run
MATCH-01 (Scoring): SATISFIED - case-insensitive partial substring, score_job verified, 8 tests
MATCH-02 (Threshold status): SATISFIED - matched if score >= threshold, queue button gated on discovered + below threshold
MATCH-03 (Score + keywords stored): SATISFIED - score and pipe-delimited matched_keywords persisted, detail renders keyword chips

---

## Anti-Patterns Found

None. All Phase 3 discovery modules contain real implementations. No TODO/FIXME/placeholder patterns found in any file.

---

## Human Verification Required

1. Real ATS API Network Round-Trip
   Test: Add a real company slug via Settings > Sources and trigger a manual run.
   Expected: Source status shows OK, jobs appear in /jobs table within same run.
   Why human: validate_source makes real HTTP calls to ATS APIs, cannot verify in static analysis.

2. Dedup Observable in UI
   Test: Run pipeline twice with same source data.
   Expected: Jobs table row count does not grow on second run. No duplicate rows.
   Why human: Confirming no duplicate rows in the live UI requires an actual data run.

3. Anomaly Banner and Dismissal
   Test: Seed 3+ DiscoveryRunStats rows then run pipeline returning 0 jobs for that source.
   Expected: Yellow banner appears on dashboard. Dismiss removes it. New run with anomalies causes reappearance.
   Why human: Cookie-based dismissal state requires runtime.

---

## Gaps Summary

One gap blocks full goal achievement: the location field in the normalized job schema (DISC-05 / Success Criterion 5) is stored in the database and populated by all three ATS fetchers (fetch_greenhouse via location.name, fetch_lever via categories.location, fetch_ashby via location), but is not rendered in any web template. Neither jobs_table.html.j2 nor job_detail_inline.html.j2 includes job.location. The remaining six normalized fields (title, company, description, url, source, posted_date) are all visible in the UI through either the table row or the detail panel.

Fix: add job.location to app/web/templates/partials/job_detail_inline.html.j2, for example as a line in the article header beneath the company name.

All other success criteria are fully met: hourly pipeline runs end-to-end with kill-switch protection and zero submission risk, dedup prevents duplicates at the fingerprint level, scores display with color-coded badges and threshold-based queue gating, anomaly detection flags drops below 20% of 7-day rolling average, per-source counts appear in both the dashboard and run detail pages, and 57 new tests (38 unit + 19 integration) cover all 8 active requirements.

---

Verified: 2026-04-12
Verifier: Claude (gsd-verifier)
