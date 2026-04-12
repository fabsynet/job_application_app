# Requirements: Job Application Auto-Apply

**Defined:** 2026-04-11
**Core Value:** Given a base resume + keywords, the app gets your tailored application in front of every matching job posting — with zero manual effort after setup.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation & Infrastructure

- [ ] **FOUND-01**: App runs as a single Docker container via `docker compose up` on any laptop
- [ ] **FOUND-02**: App persists all state in SQLite stored on a mounted volume
- [ ] **FOUND-03**: App runs an hourly background job (APScheduler) with a singleton run-lock preventing overlap
- [ ] **FOUND-04**: App emits structured logs of every run (discovered / matched / tailored / submitted / failed counts)
- [ ] **FOUND-05**: App supports a global dry-run toggle that simulates runs end-to-end without submitting
- [ ] **FOUND-06**: App stores all secrets (LLM API keys, SMTP password, LinkedIn creds) encrypted at rest using Fernet
- [ ] **FOUND-07**: App supports a kill-switch that halts all runs immediately from the web UI

### Configuration & Profile

- [ ] **CONF-01**: User can upload and replace a base DOCX resume via the web UI
- [ ] **CONF-02**: User can manage a list of target-job keywords via the web UI
- [ ] **CONF-03**: User can set a match threshold (0-100%) that controls when auto-discovered jobs get applied to
- [ ] **CONF-04**: User can enable/disable the hourly schedule and set quiet hours
- [ ] **CONF-05**: User can edit a profile with standard application fields (name, email, phone, address, work authorization, salary expectation, years of experience, LinkedIn/GitHub/portfolio links)
- [ ] **CONF-06**: User can toggle between full-auto mode and review-queue mode from the UI
- [ ] **CONF-07**: User can enter and update Claude API key, SMTP credentials via the UI (stored encrypted)
- [ ] **CONF-08**: User can set a monthly LLM budget cap; app halts tailoring when exceeded

### Job Discovery (Automatic)

- [x] **DISC-01**: App fetches jobs from Greenhouse public JSON API for user-specified companies/boards
- [x] **DISC-02**: App fetches jobs from Lever public JSON API for user-specified companies/boards
- [x] **DISC-03**: App fetches jobs from Ashby public JSON API for user-specified companies/boards
- [ ] **DISC-04**: App discovers ATS-hosted jobs via general web search matching user keywords
- [x] **DISC-05**: App normalizes all discovered jobs to a common schema (title, company, location, description, url, source, posted_date)
- [x] **DISC-06**: App dedupes jobs across sources by fingerprint hash (url + title + company) and skips jobs already in history
- [ ] **DISC-07**: App rate-limits discovery per source with randomized delays to avoid detection

### Manual Apply (Paste-a-Link)

- [ ] **MANL-01**: User can paste any job posting URL into the web UI to queue that job for application
- [ ] **MANL-02**: App auto-detects source (Greenhouse/Lever/Ashby/generic) from the URL
- [ ] **MANL-03**: App fetches and parses the job posting (title, company, description) from the URL
- [ ] **MANL-04**: Pasted jobs bypass keyword matching — they're applied to regardless of match score
- [ ] **MANL-05**: Pasted jobs route through the same tailoring → submission → tracking pipeline as auto-discovered jobs
- [ ] **MANL-06**: UI shows live status for each pasted job (fetched / tailored / submitted / failed)

### Matching

- [x] **MATCH-01**: App computes a keyword-overlap score (0-100%) between each auto-discovered job description and the user's keyword list
- [x] **MATCH-02**: App auto-applies only to jobs at or above the user's match threshold
- [x] **MATCH-03**: Match score is stored alongside each job record and shown in the UI

### Resume Tailoring

- [ ] **TAIL-01**: App rewrites the base DOCX resume per job using the Claude API
- [ ] **TAIL-02**: LLM calls are made through a provider abstraction so additional backends can be added later
- [ ] **TAIL-03**: Tailoring prompt is extractive-only — it may reword, reorder, and emphasize, but must never invent experience
- [ ] **TAIL-04**: App validates tailored output with a post-generation check that rejects any entity (company, title, skill) not present in the base resume
- [ ] **TAIL-05**: App renders the tailored content back into DOCX while preserving the base resume's formatting
- [ ] **TAIL-06**: App runs ATS-friendly output checks (no tables, standard fonts, keyword coverage reported)
- [ ] **TAIL-07**: App caches the master resume in prompt cache to reduce Claude API cost
- [ ] **TAIL-08**: App halts tailoring and notifies the user when the monthly LLM budget cap is hit
- [ ] **TAIL-09**: Every tailored resume is stored as a versioned artifact linked to its application record

### Submission

- [ ] **SUBM-01**: App submits applications via email (SMTP) to the contact email when the job posting provides one, attaching the tailored DOCX
- [ ] **SUBM-02**: Email submissions include an LLM-generated cover-letter body tailored to the job
- [ ] **SUBM-03**: App submits applications via Playwright browser automation to Greenhouse/Lever/Ashby form pages
- [ ] **SUBM-04**: App submits applications via Playwright browser automation to generic ATS form pages
- [ ] **SUBM-05**: Playwright runs in a persistent browser session (storageState volume-mounted) so cookies/logins survive across runs
- [ ] **SUBM-06**: A submitter-registry strategy selector picks the right submission channel per job (email if contact email present, Playwright otherwise)
- [ ] **SUBM-07**: Submitters are idempotent — re-running against the same application record never double-submits

### Learning Loop (ships with browser submission)

- [ ] **LEARN-01**: When a form field can't be answered from profile + resume, the submitter halts that application and logs the unknown field with full context (job, question, field type)
- [ ] **LEARN-02**: User can review unknown fields in the web UI and provide answers
- [ ] **LEARN-03**: Answers are persisted in the profile and reused on any future job asking a similar question
- [ ] **LEARN-04**: Similar questions are normalized/matched so minor wording differences still hit the cache
- [ ] **LEARN-05**: Next hourly run retries the halted application using the new answer, without creating a duplicate

### Review Queue & Tracking

- [ ] **REVW-01**: Every application moves through a state machine: `discovered → matched → tailored → pending_review → approved → submitted → confirmed | failed | needs_info`
- [ ] **REVW-02**: In review-queue mode, the user sees a list of tailored applications awaiting approval with job summary, match score, and tailored resume attached
- [ ] **REVW-03**: User can approve, reject, or regenerate any queued application
- [ ] **REVW-04**: User can view an inline diff of base vs tailored resume before approving
- [ ] **REVW-05**: App maintains an application history (job, company, status, resume version, match score, timestamp, source)
- [ ] **REVW-06**: Dashboard shows counts by state (applied / queued / skipped / failed) for today and the last 7 days
- [ ] **REVW-07**: User can download the tailored resume artifact for any past application
- [ ] **REVW-08**: Dashboard shows an applied-jobs table listing every submitted application with role/title, company, source, submission timestamp, match score, and status
- [ ] **REVW-09**: User can click any row to open a detail view showing the full job description/requirements, the tailored DOCX resume used (preview + download), the cover letter body used (if any), which submitter was used, and the submission timestamp
- [ ] **REVW-10**: Applied-jobs dashboard is filterable by source and status and sortable by date, match score, and company

### Notifications

- [ ] **NOTIF-01**: App sends one summary email per successful application (job info, match score, tailored resume attached, which submitter was used)
- [ ] **NOTIF-02**: App sends failure notifications when a run breaks (scraper down, LLM budget hit, login required on a target site)

### Safety

- [ ] **SAFE-01**: App enforces a daily cap on total applications submitted (default 30/day, user-configurable)
- [ ] **SAFE-02**: App inserts randomized human-like delays between actions within any browser session
- [ ] **SAFE-03**: App never logs the full resume content or PII (SSN, DOB) to stdout or log files
- [ ] **SAFE-04**: App never sends PII beyond what the tailoring prompt strictly requires to the LLM

## v1.x Requirements

Deferred additions to be delivered after v1 is stable. Tracked but not in current roadmap.

### LinkedIn

- **LINK-01**: LinkedIn job discovery via `python-jobspy`
- **LINK-02**: LinkedIn Easy Apply submitter via Playwright with stealth
- **LINK-03**: LinkedIn opt-in toggle (off by default) with explicit risk disclosure
- **LINK-04**: LinkedIn session persistence and captcha-pause flow

### Indeed

- **INDD-01**: Indeed job discovery via `python-jobspy`

### Local LLM

- **OLLAMA-01**: Local Ollama backend registered alongside Claude in the LLM provider abstraction
- **OLLAMA-02**: User can select LLM backend per run or as a default from the UI
- **OLLAMA-03**: Model selection and benchmarking UI for Ollama models

## v2 Requirements

Future considerations after v1.x ships.

### Discovery & Matching

- **SEM-01**: Semantic matching via sentence-transformer embeddings on top of keyword score
- **GHOST-01**: Ghost-job detection (posted > 60 days, repeated reposts, employer patterns)

### Tracking

- **IMAP-01**: IMAP inbox scan to auto-close applications when rejection/interview email arrives
- **IMAP-02**: LLM classifier for inbox email intent

### Profiles

- **MULTI-01**: Multi-profile support (different base resumes per role family)
- **MULTI-02**: Automatic routing of discovered jobs to best-fit profile

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Multi-user / SaaS accounts | Keeps scope tractable; single-user per Docker deployment. Others run their own container. |
| LinkedIn DMs / InMail automation | ToS §8.2 prohibited; behavioral biometrics detect it; permanent-ban risk. |
| LinkedIn connection-request automation | ToS violation; not part of the apply loop. |
| Captcha-solving service integration | Explicit ToS violation; permanent ban when detected. |
| Fabricated resume content (invented experience, inflated years) | Legal fraud + reputational destruction; hard prompt constraint says never invent. |
| Parallel browser sessions per account | Instant bot detection; serial queue with delays is the only safe posture. |
| Browser extension instead of containerized Playwright | Extensions are exactly what LinkedIn lists as prohibited; fights Docker-first architecture. |
| Real-time job streaming (< 1h polling) | Doesn't improve outcomes; ban-risk multiplier. |
| Salary negotiation / offer auto-acceptance | Life-impact decisions should never be automated. |
| Interview scheduling automation | Out of scope; ATS sends schedule links anyway. |
| Video / AI-avatar cover letters | Novelty, not adoption; ATS strip non-standard attachments. |
| Workday / Taleo / iCIMS full automation | Per-tenant complexity dwarfs value; detect → push to review queue for manual clickthrough. |
| Non-DOCX base resume formats (PDF, LaTeX, Markdown) in v1 | Single format keeps tailoring pipeline simple. |
| Mobile app | Local Docker deployment; desktop browser is sufficient. |

## Traceability

Populated by roadmap creation 2026-04-11. Each requirement maps to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 1 | Complete |
| FOUND-02 | Phase 1 | Complete |
| FOUND-03 | Phase 1 | Complete |
| FOUND-04 | Phase 1 | Complete |
| FOUND-05 | Phase 1 | Complete |
| FOUND-06 | Phase 1 | Complete |
| FOUND-07 | Phase 1 | Complete |
| CONF-01 | Phase 2 | Complete |
| CONF-02 | Phase 2 | Complete |
| CONF-03 | Phase 2 | Complete |
| CONF-04 | Phase 2 | Complete |
| CONF-05 | Phase 2 | Complete |
| CONF-06 | Phase 2 | Complete |
| CONF-07 | Phase 2 | Complete |
| CONF-08 | Phase 2 | Complete |
| DISC-01 | Phase 3 | Complete |
| DISC-02 | Phase 3 | Complete |
| DISC-03 | Phase 3 | Complete |
| DISC-04 | Phase 3 | Pending |
| DISC-05 | Phase 3 | Complete |
| DISC-06 | Phase 3 | Complete |
| DISC-07 | Phase 1 | Complete |
| MANL-01 | Phase 5 | Pending |
| MANL-02 | Phase 5 | Pending |
| MANL-03 | Phase 5 | Pending |
| MANL-04 | Phase 5 | Pending |
| MANL-05 | Phase 5 | Pending |
| MANL-06 | Phase 5 | Pending |
| MATCH-01 | Phase 3 | Complete |
| MATCH-02 | Phase 3 | Complete |
| MATCH-03 | Phase 3 | Complete |
| TAIL-01 | Phase 4 | Pending |
| TAIL-02 | Phase 4 | Pending |
| TAIL-03 | Phase 4 | Pending |
| TAIL-04 | Phase 4 | Pending |
| TAIL-05 | Phase 4 | Pending |
| TAIL-06 | Phase 4 | Pending |
| TAIL-07 | Phase 4 | Pending |
| TAIL-08 | Phase 4 | Pending |
| TAIL-09 | Phase 4 | Pending |
| SUBM-01 | Phase 5 | Pending |
| SUBM-02 | Phase 5 | Pending |
| SUBM-03 | Phase 6 | Pending |
| SUBM-04 | Phase 6 | Pending |
| SUBM-05 | Phase 6 | Pending |
| SUBM-06 | Phase 5 | Pending |
| SUBM-07 | Phase 5 | Pending |
| LEARN-01 | Phase 6 | Pending |
| LEARN-02 | Phase 6 | Pending |
| LEARN-03 | Phase 6 | Pending |
| LEARN-04 | Phase 6 | Pending |
| LEARN-05 | Phase 6 | Pending |
| REVW-01 | Phase 5 | Pending |
| REVW-02 | Phase 5 | Pending |
| REVW-03 | Phase 5 | Pending |
| REVW-04 | Phase 5 | Pending |
| REVW-05 | Phase 5 | Pending |
| REVW-06 | Phase 5 | Pending |
| REVW-07 | Phase 5 | Pending |
| REVW-08 | Phase 5 | Pending |
| REVW-09 | Phase 5 | Pending |
| REVW-10 | Phase 5 | Pending |
| NOTIF-01 | Phase 5 | Pending |
| NOTIF-02 | Phase 5 | Pending |
| SAFE-01 | Phase 1 | Complete |
| SAFE-02 | Phase 1 | Complete |
| SAFE-03 | Phase 1 | Complete |
| SAFE-04 | Phase 4 | Pending |

**Coverage:**
- v1 requirements enumerated: 68 total
- Mapped to phases: 68
- Unmapped: 0
- Distribution: Phase 1 = 11, Phase 2 = 8, Phase 3 = 9, Phase 4 = 10, Phase 5 = 22, Phase 6 = 8

---
*Requirements defined: 2026-04-11*
*Last updated: 2026-04-11 after roadmap creation (traceability populated)*
