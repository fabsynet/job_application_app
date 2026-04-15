# Phase 5: Email Submission, Review Queue, Manual Apply & Notifications - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

A user's first real job applications go out — via email-apply only, through the full review-queue state machine, with per-job summary emails and support for pasting a URL to apply manually. The full-auto toggle goes live here, gated only by user intent (no hard trust gate), and is backed by a "low-confidence holdout" that still routes risky tailored apps to the review queue even in auto mode. Browser submission and the learning loop are Phase 6 — NOT this phase.

Covers: SUBM-01, SUBM-02, SUBM-06, SUBM-07, REVW-01..10, NOTIF-01..02, MANL-01..06 (22 requirements).

</domain>

<decisions>
## Implementation Decisions

### Review Queue Flow

- **Layout:** Sortable/filterable table with row actions as the primary queue view. Columns include company, role, match score, tailored-on date, status. Row click opens a detail drawer/page with the full base-vs-tailored diff (uses `format_diff_html` from 04-04, already self-contained CSS).
- **Edit before approve:** **Full inline edit** is supported. User can edit the tailored DOCX bullets/content in the browser before approving. Planner must design this edit surface so it does NOT reintroduce hallucinations — edits should be clearly user-authored (no re-run of the LLM on save), and the saved version becomes the canonical DOCX that ships in the email. The validator does NOT re-run on manual edits (user is trusted to not invent their own experience).
- **Batch approve:** Checkbox column on each row + "Approve selected" action. Confirmation dialog shows count + company/role list + total attachments before firing any sends. Single-button batch firing.
- **Reject behavior:** Rejecting a tailored app opens an explicit prompt: "Skip this job permanently" vs "Re-tailor with a different angle." Re-tailor pushes the job back through the Phase 4 tailoring engine (costs budget; respects budget guard). Skip moves the job to `skipped` state and it never re-surfaces.
- **State machine** must therefore include: `matched → tailored → approved → submitted` happy path, plus `tailored → skipped` (explicit reject), `tailored → retailoring → tailored` (explicit re-tailor), `approved → failed` (SMTP error). Phase 4's existing `matched`/`tailored`/`failed` states extend here.

### Auto-Mode Trust Gate

- **Free toggle, no gate.** User flips Settings > Mode = full-auto at any time. The safety net is: daily submission cap, kill switch, per-run logs, and the low-confidence holdout below. No forced "approve N first" ramp.
- **Low-confidence holdout in auto mode:** Even in full-auto, a tailored job is only auto-submitted when BOTH conditions hold:
  1. Validator passed on first try (no retries needed)
  2. Keyword coverage is at or above the user's match threshold + a safety margin
  Anything else falls back to the review queue as if mode were review-only. Planner should expose the safety margin as a setting (default ~10 percentage points — confirm during planning).
- **Daily cap hit behavior:** Mirror Phase 4 budget-halt pattern. When cap hits mid-run:
  1. Halt the submission loop; unsent approved jobs stay `approved` for next day's run
  2. Persistent dashboard banner: "Daily cap hit — N jobs waiting for tomorrow"
  3. Offer a "Raise cap by N for today" action so user can push through remainder on good days
  4. **Explicit manual-completion path:** remainder jobs must be fully accessible — tailored DOCX download, cover letter text, diff view — so user can complete the application externally (copy/paste into a portal or send manually) without waiting for the next run. This is not a new capability; it's a commitment that the applied-jobs table + artifact download already required by REVW-05 MUST work for `approved`-but-unsent jobs, not only `submitted` ones.
- **Emergency stop (both layers):**
  1. **Global killswitch** (Phase 1) still halts the entire pipeline — discovery + tailoring + submission. Unchanged.
  2. **NEW: "Pause submissions" toggle** — softer, Phase-5-owned. Pauses only the submission stage. Discovery and tailoring keep running, and the queue fills up for the next review cycle. Use case: "something looks off in the tailoring output, let me catch up on review."

### Email Format & Identity

- **From address:** The user's own SMTP address (as configured in Phase 2 Credentials). No per-source From, no Reply-To override. Recruiter replies land in the same inbox the user sends from.
- **Subject line:** `Application for {role} at {company}` — e.g. "Application for Senior Backend Engineer at Stripe." Explicit company name helps recruiters who post for multiple orgs.
- **Body content:** **The tailored cover letter IS the email body.** The Phase 4 cover letter generator already produces plain-text cover letter content — that text becomes the email body directly. NO separate cover letter attachment. Only the resume DOCX is attached.
- **Attachment name:** `{FullName}_{Company}_Resume.docx` — e.g. `Omobolaji_Abubakre_Stripe_Resume.docx`. Unique per company. `{FullName}` comes from the Phase 2 profile (replace spaces with underscores; strip punctuation). `{Company}` is slugified from the job record (alnum + underscore only).
- **Planner responsibilities:**
  - Decide how to render the plain-text cover letter into an email body (keep line breaks, no HTML styling needed — recruiters read these in plain clients).
  - Decide whether the signature block at the bottom of the cover letter needs dedup with a standard email signature (probably NOT — cover letter already includes "Sincerely, Name").
  - Handle special chars in company names for the attachment filename.

### Notifications & Destination

- **Per-submission cadence:** One email per successful submission (NOTIF-01 strict interpretation). Content: job title, company, source, match score, link to the applied-jobs detail view, and the tailored resume attached or linked.
- **Failure alert strategy (TWO layers):**
  1. **Submission-level failures:** Every SMTP error / bounce / individual failed send fires one failure email describing which job failed and why. **Suppress duplicates for the same root cause until cleared** — e.g., if SMTP auth is broken and 10 sends fail in one run, the user gets ONE email, not ten. A "cleared" state is either: next successful send, or user action in the UI to acknowledge.
  2. **Pipeline-level breakage:** Run crash, budget halt, killswitch trip, >50% submission failure rate in one run — each fires one email. Same one-and-suppress semantics: once fired, don't fire again for the same root cause until it clears.
  - Planner must design a "failure signature" key (e.g., error class + message hash + stage) so the suppression table can dedupe reliably.
- **Notification destination is DECOUPLED from SMTP From:**
  - NEW Phase 2-adjacent setting: `notification_email` — the address that RECEIVES summary and failure emails. Defaults to the same as the SMTP From if unset.
  - The SMTP sender (From address on applications) stays as-is. This only adds a destination.
  - Planner should put this in the Settings UI near the Budget/Notifications area.
- **Quiet hours do NOT apply to notifications.** Notification emails can fire at any time, regardless of the Phase 2 schedule/quiet hours config. Quiet hours gate outbound *applications*, not inbox updates to the user.

### Paste-a-Link Manual Flow (MANL-01..06)

- **Three-step UX: paste → preview → confirm.**
  1. User pastes a URL into a single input field on a `/manual-apply` route (or similar — planner decides exact path).
  2. App fetches the URL and attempts to parse it. If source is Greenhouse/Lever/Ashby, reuse the Phase 3 normalizer. If generic, do best-effort parse (title, company, description text — no structured schema required).
  3. App shows a preview card: parsed title, company, description excerpt, detected source. User reviews and clicks **Tailor** to proceed, or **Cancel** to abandon.
- **After confirm:**
  - Job record is created with source `manual` (or the detected source if it's a known ATS).
  - Job **bypasses the keyword match threshold** — user opted in explicitly.
  - Job **respects dedup** (canonical fingerprint check). If already in the system, show "Already exists as job #N" and link to it instead of creating a duplicate.
  - Job enters the standard tailoring + review/auto pipeline from that point. In review mode, the user will still approve before send. In auto mode, the low-confidence holdout rules apply normally.
- **If the URL fetch fails** (404, timeout, auth wall, robots block):
  - Show the error in the UI with the specific reason.
  - Offer a fallback: "Paste the job description manually" — a textarea for raw description + separate fields for title/company/source. User fills in → same tailoring pipeline.
- **Unfetchable edge cases** (LinkedIn, Indeed, any source with aggressive bot walls) should degrade gracefully to the manual-paste fallback, NOT crash or hang.

### Claude's Discretion

- Exact URL patterns for `/review`, `/manual-apply`, and detail routes — follow existing sidebar/HTMX patterns from Phases 2–4.
- State machine column additions vs. new table design — planner decides based on existing Job model schema.
- Suppression-window duration / "cleared" detection heuristic for failure alerts — planner picks sensible default (e.g., 6h window or until next successful run).
- HTMX vs. full-page reload for batch-approve confirmation dialog.
- Inline-edit UI widget choice: contenteditable vs textarea vs a minimal rich-text — pick the simplest thing that preserves line breaks and bullet structure when saved back to DOCX.
- Failure email body format and structure.
- Exact low-confidence margin threshold default (suggested ~10pp above user threshold; planner can tune).

</decisions>

<specifics>
## Specific Ideas

- **"I should be able to complete the application myself."** When the daily cap hits and jobs are left in `approved` state, the UI must make it trivial to download the tailored DOCX and cover letter body so the user can paste into a company portal or send a manual email without waiting for the next run. This is an explicit requirement, not an incidental capability.
- **Inline edit is a real feature, not a flourish.** The user wants to be able to tweak tailored bullets before approval — this is about feeling in control of the words that represent them, not just a "nice to have." Plan the edit flow as a first-class path.
- **Notification inbox is separate from sending inbox.** The user sends applications from one address but wants summary/failure emails to land in a different inbox (possibly a personal address vs a professional one). This is a real separation of concerns.
- **Failure suppression is about signal, not silence.** User wants to know about failures but not get 10 emails for one broken SMTP config — the first failure is the signal, the rest is noise until something changes.
- **Preview-before-tailor on manual paste** matters because paste-a-link is inherently user-driven risk (bad URLs, bot walls, wrong company). The confirmation step is a safety net, not a UX tax.

</specifics>

<deferred>
## Deferred Ideas

- **"Approve N first" trust gate** for enabling auto-mode — considered and rejected. User prefers a free toggle with safety via daily cap + holdout + killswitch. If auto-mode quality turns out to be unreliable in practice, revisit in a future phase.
- **Inline re-tailor with custom guidance** (e.g., "emphasize Rust experience" on a re-tailor) — not in Phase 5. Current re-tailor just re-runs the same prompt. Custom-guidance re-tailoring could ship as a v1.x enhancement.
- **Browser-based submission for jobs that reject email** — Phase 6 territory (Playwright). Phase 5 stays strictly email-apply.
- **Learning loop for unknown fields** — Phase 6 (LEARN-01..05), explicit in roadmap.
- **Per-source From addresses** — considered and rejected as overkill for v1.
- **Per-run digest notification mode** — considered and rejected for v1. If per-submission cadence turns out too noisy, revisit.
- **Semantic dedup** (e.g., matching "Sr Backend Eng" to "Senior Backend Engineer" across sources) — explicitly out of v1 per ROADMAP Coverage section.
- **Applied-jobs analytics / success-rate dashboard** — Phase 5 delivers counts by state + filterable table (REVW-05, REVW-06 equivalent). Trend charts and response-rate tracking are backlog.

</deferred>

---

*Phase: 05-email-submission-review-queue*
*Context gathered: 2026-04-15*
