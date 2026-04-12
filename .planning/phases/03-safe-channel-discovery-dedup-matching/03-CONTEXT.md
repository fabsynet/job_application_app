# Phase 3: Safe-Channel Discovery, Dedup & Matching - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Pull jobs from Greenhouse/Lever/Ashby public JSON APIs, normalize to a common schema, deduplicate against history by canonical fingerprint (url + title + company), score against user keywords, and queue matched jobs. Zero submission risk, zero ToS exposure. Company list management, job display UI, and anomaly alerting are in scope. Creating/submitting applications is NOT in scope.

</domain>

<decisions>
## Implementation Decisions

### Company list management
- User adds companies by pasting a careers page URL or slug (e.g., `stripe` or `https://boards.greenhouse.io/stripe`). App auto-detects the source (Greenhouse/Lever/Ashby)
- Company list lives in a new "Sources" section in the existing settings sidebar
- Validate on add — hit the API immediately when user submits the slug. Show inline error if it doesn't resolve. Don't save invalid entries
- Each company has an enable/disable toggle. Disabled companies are skipped during discovery but kept in the list for easy re-enabling

### Job listing display
- Table/list view with sortable columns: title, company, source, score, posted date, status
- Show ALL discovered jobs by default with score column — not filtered to matched-only
- Match score displayed as color-coded badge (green = high match, yellow = borderline, gray = low)
- Clicking a job row expands inline to show full description, matched keywords highlighted, and original posting URL. No page navigation

### Matching & scoring
- Keyword matching is case-insensitive and partial — "python" matches "Python", "python3", "Python/Django"
- Expanded job view shows keyword breakdown: matched keywords highlighted green, unmatched keywords grayed out
- Below-threshold jobs are visible and scored but NOT auto-queued for tailoring
- User can manually queue a below-threshold job from the expanded view ("Queue for apply" button) — deliberate action after reviewing the description

### Anomaly & run feedback
- Per-source discovery counts (discovered/matched) shown in both dashboard summary and run detail view
- Anomaly alerts (today < 20% of 7-day rolling average) surface as yellow warning banner on dashboard (e.g., "Greenhouse returned 3 jobs today (avg: 45). API may be down or slug changed.")
- Anomaly banners are dismissable — won't reappear until a new anomaly is detected on a subsequent run
- Failed source fetches (404, timeout) are a SEPARATE error state from anomalies — red "Error" badge on the source in the sources list, distinct error banner. Different visual treatment from low-count anomaly warnings

### Claude's Discretion
- Exact table column widths and responsive behavior
- Inline expansion animation/transition
- Dedup fingerprint normalization details (URL canonicalization, title cleaning)
- API polling strategy (parallel vs sequential source fetching)
- Dashboard summary card layout for source counts

</decisions>

<specifics>
## Specific Ideas

- Below-threshold manual queueing is important: "sometimes the applicant might want to give it a try" — the user wants agency over borderline jobs, not just algorithmic gatekeeping
- Company management should feel lightweight — add a slug, see it validate, toggle on/off. Not a heavy configuration form

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-safe-channel-discovery-dedup-matching*
*Context gathered: 2026-04-12*
