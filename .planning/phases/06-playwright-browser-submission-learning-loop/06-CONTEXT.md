# Phase 6: Playwright Browser Submission & Learning Loop - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Browser-based submission goes live for Greenhouse/Lever/Ashby and generic ATS forms via a persistent Playwright context. The learning loop turns every unknown form field into a permanent, reusable profile answer that makes the app get better the longer the user runs it. PlaywrightStrategy plugs into the existing SubmitterStrategy Protocol from Phase 5 (05-03) and the submission pipeline (05-04) without touching those layers.

Requirements: SUBM-03, SUBM-04, SUBM-05, LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05

</domain>

<decisions>
## Implementation Decisions

### Form-filling strategy
- **Label-based heuristics** for matching form fields to profile data on known ATS platforms (Greenhouse/Lever/Ashby). Match by keyword patterns in field labels (contains 'name', 'email', 'phone', etc.) rather than hardcoded per-ATS field maps or LLM-assisted matching
- **Dropdown fields: profile stores exact values.** User pre-configures exact dropdown answers in their profile (e.g., work_auth='US Citizen'). Direct match against option text. No LLM fallback for dropdowns
- **File uploads: auto-detect resume + cover letter by label, skip unknown file fields.** If label contains 'resume' -> tailored DOCX, 'cover letter' -> cover letter file. Unknown file fields are skipped (not halted), but mandatory unknown file fields are logged/noted as unknown fields for the user to see
- **Multi-step forms: screenshot every step (audit trail) + halt on unknown fields.** A Settings toggle lets the user switch between "pause if unsure" mode (halt on unknown fields) and "always advance" mode (screenshot-only, no halts). Default to "pause if unsure" for initial runs; user switches to "always advance" after building confidence
- **Collect ALL unknown fields across all form pages before halting** -- scan the entire form, collect every unknown field, then present them all at once so the user answers everything in one session rather than one field per retry

### Unknown field UX
- **Context shown: screenshot + field label + job title/company + full job description.** Helps the user answer in context of what the specific job is asking
- **Dedicated '/needs-info' queue page** listing all halted applications with their unknown fields. Not inline on job detail -- a standalone page for triaging halted applications
- **Immediate retry after user answers.** As soon as the user provides answers, Playwright re-opens the form and attempts submission right away. Instant feedback, no waiting for next scheduled run
- **Collect all unknowns before halting** -- user sees every unknown field from all form pages at once, answers them all, then retry fills the complete form

### Answer reuse & matching
- **LLM semantic matching** for reusing saved answers on future forms. Send new field label + saved answer labels to Claude to determine equivalence. Catches paraphrases like "Are you authorized to work?" vs "Work Authorization"
- **Always auto-fill if LLM says it's a match.** No confidence threshold. Trust the model. Fewer halts, faster throughput
- **Reuse summary in success email.** The per-job success notification email includes a section listing which saved answers were auto-applied. User sees what was reused after the fact
- **'Saved Answers' section in Settings** for viewing and managing all question->answer pairs. User can edit or delete any saved answer from one place

### Playwright session & reliability
- **User toggle for headless vs headed mode** in Settings. Power users can watch the browser fill forms in real time. Default headless for Docker production
- **CAPTCHA/2FA: halt, notify, skip.** When detected, take a screenshot, mark the application as needing info, send a notification, then move on to the next job (don't block the pipeline). The halted application stays in the needs-info queue so the user can return later and retry manually when available
- **Persist session state via storageState.** Save Playwright's storageState.json to the mounted data/ volume. Survives container restarts. User stays logged into ATS portals across runs
- **Fail fast on mid-form errors.** Network error, page timeout, unexpected layout -> take a screenshot of the failure state, mark job as 'failed' with error details, move on to the next job. No automatic retry. User can retry from the UI (same pattern as Phase 5 email retry button)

### Claude's Discretion
- Exact label-matching heuristic patterns and their priority order
- Generic ATS form selector strategy (outside Greenhouse/Lever/Ashby)
- Screenshot storage format and retention policy
- How to detect CAPTCHA vs 2FA vs other blocking elements
- Playwright page timeout values and navigation wait strategies

</decisions>

<specifics>
## Specific Ideas

- Multi-step mode toggle should be in Settings alongside the existing Phase 5 controls (submissions_paused, auto_holdout_margin_pct, etc.)
- The "always advance" vs "pause if unsure" toggle is the Phase 6 equivalent of Phase 5's full-auto vs review-queue mode -- user gains confidence over time and loosens the guardrails
- Saved Answers management page should feel like the existing Keywords management page -- simple list with edit/delete actions
- PlaywrightStrategy must plug into the Phase 5 SubmitterStrategy Protocol (05-03) and be prepended to the registry for known-ATS jobs, with EmailStrategy as fallback (per 05-03 decision)
- The drain-loop guard order from 05-04 should be reused by the Playwright drain loop (per 05-04 decision)
- `extract_docx_plaintext` from 05-04 can be reused for transcript checks (per 05-04 decision)
- `Submission.submitter` column already ships with 'playwright' value (per 05-01 decision) -- no schema bump needed

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 06-playwright-browser-submission-learning-loop*
*Context gathered: 2026-04-15*
