# Phase 2: Configuration, Profile & Resume Upload - Context

**Gathered:** 2026-04-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Web UI for all pipeline inputs — keywords, match threshold, profile, base DOCX resume, API keys, SMTP credentials, schedule/quiet hours, budget cap, and mode toggle. No scraping, matching, or submission logic exists yet. This phase delivers the configuration surface that later phases consume.

</domain>

<decisions>
## Implementation Decisions

### Page structure & navigation
- Sidebar layout: one `/settings` page with a left sidebar listing sections, content area on the right
- Merge Phase 1 settings (rate limits, dry-run, kill-switch) into this sidebar as additional sections — single source of truth for all settings
- Top nav stays minimal: Dashboard, Settings. Clicking Settings opens the sidebar layout
- Each section has its own Save button; saves via HTMX with inline success/error flash, no page reload

### Profile fields
- Three groups: Contact (name, email, phone, address), Work Details (work auth, salary, experience), Links (LinkedIn, GitHub, portfolio)
- All fields optional — no validation gates. Missing fields become a problem only when submission needs them in Phase 5
- Each group is a collapsible or distinct sub-section within the Profile sidebar item

### Resume upload
- Upload + basic preview: after uploading a DOCX, render extracted text/headings so user can confirm it parsed correctly
- Support drag-and-drop and file picker
- Show filename, upload date, and a re-upload/replace option

### Keywords
- Tag-style chips: user types a keyword, presses Enter, it becomes a removable chip/tag
- Click X to remove individual keywords

### Credentials display & validation
- Claude API key: validate on save (lightweight API call to verify the key works, show inline success/failure)
- SMTP credentials: validate on save (attempt SMTP connection, no email sent, show inline success/failure)
- After saving, display "Configured ✓" or "Not set" status only — no reveal, no masked values, no last-4-chars
- To change a credential, user enters a new value which replaces the old one
- SMTP field layout: Claude's Discretion (provider presets vs all-fields-visible)

### Schedule & quiet hours
- Time range slider for quiet hours start/end (e.g., drag to set 10 PM - 7 AM window)
- Schedule enable/disable toggle alongside quiet hours

### Match threshold
- Slider with descriptive labels at key points (e.g., Loose 30% / Moderate 60% / Strict 85%)
- Exact percentage displayed alongside the slider

### Budget cap
- Dollar input for monthly LLM budget cap
- Usage progress bar showing spend vs cap (e.g., "$4.20 / $20.00")
- Bar starts at $0 since no tailoring exists yet — infrastructure ready for Phase 4

### Mode toggle
- Full-auto vs review-queue toggle positioned at the top of the settings sidebar — most consequential setting gets prime placement
- Clear labeling of what each mode means (auto-submit vs human approval required)

### Claude's Discretion
- SMTP field layout approach (provider presets vs explicit fields)
- Exact sidebar section ordering
- Slider implementation details (quiet hours and threshold)
- Success/error flash styling and duration
- Resume text extraction depth (headings only vs full content preview)

</decisions>

<specifics>
## Specific Ideas

- Quiet hours slider should visually show a 24-hour range the user can drag
- Match threshold slider should have semantic labels so user understands what the percentage means in practice
- Budget progress bar provides at-a-glance awareness even before Phase 4 starts consuming budget

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-configuration-profile-resume-upload*
*Context gathered: 2026-04-11*
