# Roadmap: Job Application Auto-Apply

## Overview

This roadmap delivers a single-user, Dockerized job-application auto-apply app in six phases. We build safe-first: a rock-solid container + scheduler + secrets vault before any network calls, then prove the full discover -> match -> tailor -> submit pipeline on zero-risk channels (Greenhouse/Lever/Ashby public JSON + email-apply) before ever touching a browser. LLM hallucination guardrails ship in the same phase as the first LLM call, dedup ships before any submission, rate limiting ships with the scheduler, and the learning loop ships with Playwright (the only channel where unknown fields appear). LinkedIn, Indeed, and local Ollama are deliberately deferred to v1.x.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Foundation, Scheduler & Safety Envelope** - Bootable Docker container with encrypted secrets, hourly scheduler, run-lock, kill-switch, dry-run, rate-limit envelope, and PII-safe logging
- [x] **Phase 2: Configuration, Profile & Resume Upload** - Web UI for keywords, profile, base DOCX upload, schedule/quiet hours, budget cap, mode toggle, and credential entry
- [x] **Phase 3: Safe-Channel Discovery, Dedup & Matching** - Greenhouse/Lever/Ashby JSON discovery, canonical fingerprint dedup, keyword-overlap matching, normalized job schema
- [ ] **Phase 4: LLM Tailoring & DOCX Generation** - Extractive-only Claude tailoring with hallucination validator, prompt caching, budget enforcement, and format-preserving DOCX render
- [ ] **Phase 5: Email Submission, Review Queue, Manual Apply & Notifications** - Email-apply submitter, full state machine, review queue with diff, paste-a-link flow, per-job summary emails
- [ ] **Phase 6: Playwright Browser Submission & Learning Loop** - Persistent-context Playwright submitter for Greenhouse/Lever/Ashby/generic forms with unknown-field capture, user answers, and retry

## Phase Details

### Phase 1: Foundation, Scheduler & Safety Envelope
**Goal**: A user can `docker compose up` on a fresh laptop and get a running, observable, safely-throttled scheduler with encrypted secret storage and a working kill-switch — even though no actual job work happens yet.
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, FOUND-06, FOUND-07, DISC-07, SAFE-01, SAFE-02, SAFE-03
**Success Criteria** (what must be TRUE):
  1. User runs `docker compose up` on a clean laptop and the app comes up with SQLite persisted to a mounted volume
  2. User can see an hourly heartbeat in the UI and in structured logs (discovered/matched/tailored/submitted/failed counts), and the run-lock prevents two runs from overlapping
  3. User can flip a dry-run toggle and a kill-switch from the UI, and the scheduler immediately respects both
  4. User's secrets (Fernet-encrypted) survive container restart, and no PII or resume content ever appears in stdout/log files
  5. The rate-limit envelope (daily application cap, randomized per-source delays, jittered inter-action waits) is enforced by the scheduler before any downstream stage is even wired up
**Plans**: 5 plans
  - [x] 01-01-PLAN.md — Docker + SQLite + Alembic foundation (config, models, migration)
  - [x] 01-02-PLAN.md — FernetVault + two-layer log scrubber + zero-PII assertion test
  - [x] 01-03-PLAN.md — SchedulerService, run-lock, kill-switch, rate limiter, FastAPI lifespan, /health
  - [x] 01-04-PLAN.md — Dashboard, toggles, runs list/detail, settings page (HTMX + Jinja + Pico.css)
  - [x] 01-05-PLAN.md — Setup wizard, rotation banner, end-to-end goal-backward test suite, README

### Phase 2: Configuration, Profile & Resume Upload
**Goal**: A user can configure every input the pipeline will need — keywords, threshold, profile, base resume, API keys, schedule, budget, mode — without any scraping, matching, or submission logic existing yet.
**Depends on**: Phase 1
**Requirements**: CONF-01, CONF-02, CONF-03, CONF-04, CONF-05, CONF-06, CONF-07, CONF-08
**Success Criteria** (what must be TRUE):
  1. User can upload and replace a base DOCX resume via the web UI and see it persisted across container restarts
  2. User can manage target-job keywords, match threshold (0-100%), quiet hours, and hourly schedule on/off from the UI
  3. User can fill a full application profile (name, contact, work auth, salary, experience, portfolio links) and edit it
  4. User can enter Claude API key, SMTP credentials, and a monthly LLM budget cap through the UI, with secrets stored Fernet-encrypted
  5. User can toggle between full-auto and review-queue mode from a single control in the UI
**Plans**: 5 plans
  - [x] 02-01-PLAN.md — DB migration + sidebar layout shell + mode toggle
  - [x] 02-02-PLAN.md — Profile form + resume upload with DOCX preview
  - [x] 02-03-PLAN.md — Keywords chips + threshold slider + schedule + budget
  - [x] 02-04-PLAN.md — Credentials with validation (Anthropic API + SMTP)
  - [x] 02-05-PLAN.md — Integration tests for all CONF requirements

### Phase 3: Safe-Channel Discovery, Dedup & Matching
**Goal**: On every hourly tick, the app pulls jobs from Greenhouse/Lever/Ashby public JSON APIs, normalizes them, deduplicates against history, scores them against the user's keywords, and queues matched jobs — all with zero submission risk and zero ToS exposure.
**Depends on**: Phase 2
**Requirements**: DISC-01, DISC-02, DISC-03, DISC-04, DISC-05, DISC-06, MATCH-01, MATCH-02, MATCH-03
**Success Criteria** (what must be TRUE):
  1. User sees real jobs appear in the UI within one hourly cycle after configuring a Greenhouse/Lever/Ashby company list
  2. A job cross-posted on two sources never shows up twice — dedup by canonical fingerprint (url + title + company) is verifiable in the UI
  3. User sees each matched job's keyword-overlap score, and only jobs at or above the threshold are queued for downstream stages
  4. User can see per-source discovery counts and anomaly alerts (today < 20% of 7-day rolling average) in the run log
  5. The normalized job schema (title, company, location, description, url, source, posted_date) is visible in the UI for every discovered job regardless of source
**Plans**: 6 plans
  - [x] 03-01-PLAN.md — DB models (Source, Job, DiscoveryRunStats) + Alembic migration
  - [x] 03-02-PLAN.md — Discovery backend (fetchers, scoring, dedup, pipeline integration)
  - [x] 03-03-PLAN.md — Sources settings UI (add/validate/toggle/remove in sidebar)
  - [x] 03-04-PLAN.md — Jobs page UI (sortable table, inline expand, keyword highlight, manual queue)
  - [x] 03-05-PLAN.md — Dashboard discovery summary + anomaly banners + run detail stats
  - [x] 03-06-PLAN.md — Integration tests for all Phase 3 requirements

### Phase 4: LLM Tailoring & DOCX Generation
**Goal**: Every matched, queued job gets a tailored DOCX resume generated by Claude that provably contains zero invented experience, preserves the base resume's formatting, respects the user's monthly budget, and is stored as a versioned artifact.
**Depends on**: Phase 3
**Requirements**: TAIL-01, TAIL-02, TAIL-03, TAIL-04, TAIL-05, TAIL-06, TAIL-07, TAIL-08, TAIL-09, SAFE-04
**Success Criteria** (what must be TRUE):
  1. User opens any queued job and sees a tailored DOCX that preserves the base resume's fonts, bullets, and layout
  2. The hallucination validator rejects any tailored output containing a company, title, or skill not in the base resume — verifiable by a test case where an invented skill is injected
  3. User never sees PII (address, phone, SSN, DOB) anywhere in the LLM prompt logs — only bullets and skills cross the LLM boundary
  4. User can set a monthly budget cap and watch tailoring halt with a clear UI notification when the cap is hit
  5. Every tailored resume exists as a versioned, downloadable artifact linked to its pending application record, and prompt caching on the master resume visibly reduces cost per tailoring call
**Plans**: TBD

### Phase 5: Email Submission, Review Queue, Manual Apply & Notifications
**Goal**: A user's first real job applications go out — via email-apply only, through the full review-queue state machine, with per-job summary emails and support for pasting a URL to apply manually. The full-auto toggle goes live here, gated by the review queue the user has already built trust in.
**Depends on**: Phase 4
**Requirements**: SUBM-01, SUBM-02, SUBM-06, SUBM-07, REVW-01, REVW-02, REVW-03, REVW-04, REVW-05, REVW-06, REVW-07, REVW-08, REVW-09, REVW-10, NOTIF-01, NOTIF-02, MANL-01, MANL-02, MANL-03, MANL-04, MANL-05, MANL-06
**Success Criteria** (what must be TRUE):
  1. User approves a tailored application in the review queue (with inline base-vs-tailored diff) and an email with the tailored DOCX attached arrives at the posted contact email
  2. User flips to full-auto mode and watches the next hourly run submit applications without human approval, honoring the daily cap and randomized delays
  3. User pastes a random job posting URL into the UI and that job routes through the same fetch -> tailor -> email pipeline, bypassing keyword match but respecting dedup
  4. User receives exactly one per-job summary email on every successful submission (job, company, match score, tailored resume attached, submitter used) and one failure notification when a run breaks
  5. User sees a dashboard showing counts by state (applied/queued/skipped/failed) for today and the last 7 days, and can download the tailored resume artifact for any past application
  6. User sees an applied-jobs table listing every submitted application (role, company, source, timestamp, match score, status), can filter by source/status and sort by date/score/company, and can click any row to open a detail view with the full job description, tailored DOCX (preview + download), and cover letter body used
  7. Re-running against the same application record never double-submits — submitter idempotency is verifiable by forcing a mid-run crash and confirming no duplicate email on retry
**Plans**: TBD

### Phase 6: Playwright Browser Submission & Learning Loop
**Goal**: Browser-based submission goes live for Greenhouse/Lever/Ashby and generic ATS forms in a persistent Playwright context — and the learning loop turns every unknown form field into a permanent, reusable profile answer that makes the app get better the longer the user runs it.
**Depends on**: Phase 5
**Requirements**: SUBM-03, SUBM-04, SUBM-05, LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05
**Success Criteria** (what must be TRUE):
  1. User watches (or trusts) Playwright fill and submit a real Greenhouse/Lever/Ashby form end-to-end using profile + tailored resume, with cookies/session persisted across container restarts via mounted storageState
  2. When the form asks a question profile + resume can't answer, the application halts in state `needs_info` and appears in a UI queue with full context (job, question, field type, screenshot)
  3. User provides an answer once in the UI and the next hourly run retries that halted application successfully — without creating a duplicate
  4. A second job that asks a semantically similar question (minor wording differences) is answered automatically from the cached answer, verifiable in the run log
  5. Generic ATS form pages (outside Greenhouse/Lever/Ashby) are submitted via the same label-based matching engine, with per-step screenshots captured for debugging
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation, Scheduler & Safety Envelope | 5/5 | ✓ Complete | 2026-04-12 |
| 2. Configuration, Profile & Resume Upload | 5/5 | ✓ Complete | 2026-04-12 |
| 3. Safe-Channel Discovery, Dedup & Matching | 6/6 | ✓ Complete | 2026-04-12 |
| 4. LLM Tailoring & DOCX Generation | 0/TBD | Not started | - |
| 5. Email Submission, Review Queue, Manual Apply & Notifications | 0/TBD | Not started | - |
| 6. Playwright Browser Submission & Learning Loop | 0/TBD | Not started | - |

## Coverage

**Total v1 requirements mapped:** 68/68

- Phase 1: 11 requirements (FOUND-01..07, DISC-07, SAFE-01, SAFE-02, SAFE-03)
- Phase 2: 8 requirements (CONF-01..08)
- Phase 3: 9 requirements (DISC-01..06, MATCH-01..03)
- Phase 4: 10 requirements (TAIL-01..09, SAFE-04)
- Phase 5: 22 requirements (SUBM-01, SUBM-02, SUBM-06, SUBM-07, REVW-01..10, NOTIF-01..02, MANL-01..06)
- Phase 6: 8 requirements (SUBM-03, SUBM-04, SUBM-05, LEARN-01..05)

No orphans. No duplicates. v1.x (LinkedIn, Indeed, Ollama) and v2 (semantic matching, IMAP, multi-profile) are intentionally out of this roadmap.

## Constraint Compliance

| Constraint | Where Honored |
|------------|---------------|
| Safe channels (GH/Lever/Ashby + email) before browser automation | Phases 3+5 (safe) land before Phase 6 (browser) |
| Dedup (DISC-06) ships before any submission | DISC-06 in Phase 3; first submission in Phase 5 |
| Hallucination validator (TAIL-04) ships with first LLM call (TAIL-01) | Both in Phase 4 |
| Rate limiting (SAFE-01, SAFE-02, DISC-07) ships with scheduler (FOUND-03) | All four in Phase 1 |
| Learning loop (LEARN-01..05) ships with Playwright (SUBM-03..04) | All in Phase 6 |
| Manual paste-a-link (MANL-01..06) is first-class v1 and additive once discovery+tailoring+submission exist | All in Phase 5 |

---
*Roadmap created: 2026-04-11*
