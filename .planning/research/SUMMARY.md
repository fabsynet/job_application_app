# Project Research Summary

**Project:** Job Application Auto-Apply App
**Domain:** Autonomous job-application automation (single-user, Dockerized, Python/FastAPI)
**Researched:** 2026-04-11
**Confidence:** MEDIUM-HIGH overall (HIGH for stack/architecture; MEDIUM for anti-bot thresholds and legal specifics)

---

## Executive Summary

This is a scheduled-worker + web-UI + shared-store system with three atypical complexity centres: adversarial web scraping against platforms that actively fight bots (LinkedIn, Indeed), LLM-generated content that must never hallucinate factual claims on a resume, and a submission loop that must be reversible and auditable because mistakes have real career consequences. The core design principle that emerges from all four research tracks is "safe channel first, dangerous channel later": start with Greenhouse/Lever public JSON APIs (zero ToS risk, structured data, high reliability) and prove the full pipeline before touching LinkedIn automation at all.

The recommended stack is Python 3.13 + FastAPI 0.135 + APScheduler + SQLModel/SQLite + Playwright 1.58 + python-jobspy + Anthropic SDK (claude-sonnet-4-5) / Ollama dual-provider + python-docx + Fernet + aiosmtplib + HTMX, packaged in the official Microsoft Playwright Docker image. The single most important prescriptive decision from STACK.md: do not write a custom LinkedIn scraper and do not run LinkedIn Easy Apply unattended. LinkedIn 2026 enforcement is ML-based behavioral biometrics, not just rate-limit heuristics, and account loss is effectively a career-damage event for the user.

The top risks are: (1) permanent LinkedIn account ban from unthrottled automation, (2) LLM hallucinating experience onto the resume the user never had, (3) silent double-submissions from a race between discovery and submission logging, (4) PII leaking into LLM prompts or plaintext logs, and (5) LLM cost blowout from tailoring every discovered job before filtering. All five are architectural concerns that must be designed in from Phase 1 -- they cannot be bolted on later.

---

## Key Findings

### Recommended Stack

See full details in `.planning/research/STACK.md`.

The stack is chosen for zero-extra-service constraint (runs entirely on laptop) and pluggability. APScheduler in-process replaces Celery+Redis (second container). SQLite on a mounted volume replaces Postgres. HTMX+Jinja2 replaces React (no build step, no frontend repo). The LLMProvider Protocol with two implementations (Anthropic + Ollama) replaces LangChain (40+ transitive deps with leaky abstractions for a two-provider use case).

**Core technologies at a glance:**

| Technology | Version | Why |
|---|---|---|
| Python | 3.13.x | Current stable; all libraries supported |
| FastAPI | 0.135.3 | User-mandated; native HTMX/HTML fragment support |
| SQLModel + SQLite | 0.0.24 / 3.45+ | One class = DB row + API schema; zero-admin single-file DB |
| APScheduler | 3.10.x | In-process scheduler; no broker; persists to SQLite |
| Playwright | 1.58.0 + stealth 2.0.3 | Browser automation with fingerprint patching; MS-maintained |
| python-jobspy | 1.1.82+ | Only maintained OSS multi-board aggregator (LinkedIn/Indeed/Glassdoor) |
| httpx | 0.28.x | Async HTTP for Greenhouse/Lever JSON ATS endpoints |
| anthropic SDK | 0.94.0 | Claude API with prompt caching; use claude-sonnet-4-5 |
| ollama-python | 0.4.x | Local LLM via host Ollama daemon |
| instructor | 1.7.x | Forces LLM to return Pydantic-typed output; eliminates LLM-returned-garbage bugs |
| python-docx + docxtpl | 1.2.0 | DOCX parse + edit; docxtpl for template-mode to preserve formatting |
| cryptography (Fernet) | 44.x | AEAD encryption for creds at rest; key injected via env/Docker secret |
| aiosmtplib | 5.1.x | Async SMTP for per-job email notifications |
| HTMX + Jinja2 | 2.0.4 / 3.1.x | Server-rendered UI with partial updates; no build step |
| Docker (Playwright base) | v1.58.0-noble | Pre-bundles Chromium + all Linux deps; avoids libnss3 pain |

**Hard avoids:** linkedin-api (Voyager private API, triggers Tier-2+ bans), yagmail (Gmail-only, sync, dead since 2022), keyring inside Docker (silently falls back to plaintext), LangChain (40+ deps, leaky abstractions), Alpine base image (breaks lxml/cryptography/Playwright wheels), Celery+Redis (violates single-container constraint).

### Expected Features

See full details in `.planning/research/FEATURES.md`.

**Must have -- table stakes (v1):**
- Multi-source ingestion starting with Greenhouse/Lever public JSON APIs (T1/D5)
- Keyword + location + remote filters with user-adjustable threshold (T2, T5)
- URL + fingerprint deduplication before any submission (T4)
- Hourly background polling via APScheduler (T3) -- must ship with rate limiting (T22)
- LLM resume tailoring with extractive-only constraint (T7)
- DOCX round-trip preserving formatting (T8)
- ATS-friendly output validation (T9)
- Email-apply submission path as primary v1 channel (T11)
- Profile data store for standard form fields (T12)
- Review queue defaulted ON + dry-run mode (T14, D10) -- trust ramp before full-auto
- Application history + dashboard (T15, T16)
- Per-job email summary on submit (T19)
- Secrets management via env/Docker (T21)
- Persistent Playwright browser session/cookies (T23) -- load-bearing for automation

**Should have -- differentiators (v1.1):**
- LinkedIn/Indeed scraping via python-jobspy (T1) -- add after safe channels prove stable
- Playwright browser automation for Easy Apply (T10) -- deferred; high ban risk
- LLM unknown-field fallback + learning loop (T13, D3) -- only needed when browser flows ship
- Cover letter generation (D11)
- Review-queue inline diff showing master vs tailored (D9)

**Defer to v2+:**
- Semantic/embedding-based matching (D4) -- keyword scoring sufficient until user reports misses
- Ghost-job detection heuristics (D7) -- needs data to tune
- IMAP response tracking to auto-close on rejection/interview (D8) -- large scope
- Multi-profile support per role family (D12)
- Workday/Taleo/iCIMS full automation -- push to review queue instead

**Anti-features -- never build:**
- LinkedIn DM/InMail automation (A1) -- immediate account ban
- Fabricated resume content (A3) -- legal fraud, career destruction
- Unlimited concurrent browser sessions (A4) -- instant detection
- Captcha-solving service integration (A5) -- guaranteed permanent ban when detected
- Multi-user/SaaS mode (A9) -- 10x complexity, out of scope
- Salary negotiation / offer auto-acceptance (A10) -- automation must stop at submission

### Architecture Approach

See full details in `.planning/research/ARCHITECTURE.md`.

The architecture is a monolith with protocol boundaries: a single FastAPI process runs the web UI, the APScheduler hourly trigger, and the pipeline -- all sharing one event loop. The pipeline is structured as explicit, independently testable stages (discover -> dedupe -> match -> tailor -> submit -> notify) passing a RunContext through them. Every extensibility axis (scraper source, LLM backend, submission channel) is a Python Protocol with a registry, so adding LinkedIn Easy Apply or a new ATS never touches the orchestrator. The Application status machine (discovered -> matched -> tailored -> pending_review -> approved -> submitted -> confirmed | failed | needs_info) is the single source of truth for the full-auto toggle -- not scattered if-settings.full_auto branches.

**Major components:**

1. **Pipeline Orchestrator** (app/pipeline/orchestrator.py) -- sequences stages, writes Run/RunEvent records, honors dry-run and full-auto gate
2. **Scraper Registry** (app/scrapers/) -- Scraper protocol per source; Greenhouse/Lever use httpx + JSON; LinkedIn/Indeed use python-jobspy; generic fallback uses Playwright
3. **LLM Gateway** (app/llm/) -- LLMBackend ABC with ClaudeBackend and OllamaBackend; outputs schema-validated via instructor; prompt caching on master resume
4. **Submitter Registry** (app/submitters/) -- strategy selection by job shape (ATS type, Easy Apply flag, recruiter email); NeedsFieldAnswer exception is part of the contract
5. **Review Queue + Status Machine** (app/pipeline/stages/submit.py) -- pending_review -> approved is the only transition the full-auto flag affects
6. **Learning Loop** (app/profile/learning.py) -- captures UnknownField rows during submit, queues for user, merges answers into Profile.answers_json, retries next run
7. **Secrets Vault** (app/security/secrets.py) -- Fernet-encrypted secrets table; Fernet key is the only value in env
8. **Persistence Layer** -- SQLite on named Docker volume (/data/app.db), Alembic migrations, artifact files on second volume (/artifacts/)

**Key data model:** Job (source/source_id unique, simhash for cross-post dedup) -> Application (status machine, tailored artifact paths) -> UnknownField/FieldAnswer (learning loop) -> Run/RunEvent (observability).

### Critical Pitfalls

See full details in `.planning/research/PITFALLS.md`.

1. **LinkedIn Account Ban (BLOCKER)** -- LinkedIn uses ML-based behavioral biometrics, not just rate limits. Use launch_persistent_context (real user-data-dir), run headful or xvfb, playwright-stealth patches, max 10-15 LinkedIn applications/day with 3-15 min random jitter, warm up with user-confirmed applies for first 2 weeks. Architecture must assume persistent context from day one -- retrofitting is painful. Treat LinkedIn as submission target only, not discovery source.

2. **LLM Resume Hallucination (BLOCKER)** -- LLMs optimize for JD match over source faithfulness and will invent skills and metrics. Use extractive-only tailoring via structured output (JSON array of bullet IDs from source), maintain canonical master_resume.yaml of atomic facts, post-generation diff validator, temperature <= 0.2, explicit system-prompt constraint (never introduce any skill/employer/date/metric not in the source resume). Must be in the prompt architecture, not bolted on.

3. **Duplicate Submissions (MAJOR)** -- Same job cross-posted on multiple boards with different IDs; crash mid-submit leaves application in-progress for next run. Use canonical fingerprint sha256(normalize(company+title+location+jd_first_500_chars)), atomic status-machine transitions (SQLite WAL), singleton run lock, confirmation scraping after submit.

4. **PII Leakage into LLM / Logs (BLOCKER)** -- SSN, address, phone, visa status sent to Anthropic API or printed in crash traces. Enforce strict PII boundary (LLM sees bullets and skills -- never contact info), SecretStr on all models, disable Playwright tracing on PII forms, use Anthropic zero-data-retention endpoint, git pre-commit hook scanning for resume files and .env.

5. **LLM Cost Blowout (MAJOR)** -- Tailoring 200 jobs/run with Sonnet at default settings = $10k/month. Pipeline order: cheap filter -> keyword score -> Haiku relevance (200 tokens) -> Sonnet tailoring (top N only); prompt caching on master resume; hard daily/monthly budget cap from the very first call. Target < $0.10/application.

6. **DOCX Round-Trip Formatting Loss (MAJOR)** -- python-docx full rewrite destroys custom fonts, tables, columns, bullet styles. Use docxtpl (Jinja2-in-Word with named placeholders) to preserve 100% of formatting; visual regression test via LibreOffice headless PDF render.

7. **Silent Scraper Breakage (MAJOR)** -- LinkedIn/Indeed change DOM; scraper returns 0 results silently for weeks. Pydantic schema validation on every scraped job (missing title = hard fail); canary assertion (must return >= 1 job); anomaly alert if today count < 20% of 7-day rolling average; prefer Greenhouse/Lever JSON APIs which never change DOM.

---

## Implications for Roadmap

The dependency graph from FEATURES.md and the build order from ARCHITECTURE.md converge on the same phase structure. Each phase must be demoable end-to-end before the next begins.

### Phase 1: Foundation and Skeleton
**Rationale:** Everything else depends on these. Secrets vault, DB schema, and observability must be correct before the first credential is entered or the first run fires. Retrofitting security is always more expensive than getting it right first.
**Delivers:** Bootable Docker container, authenticated web UI, SQLAlchemy models with Alembic migrations, Fernet secrets vault, APScheduler singleton with run lock, structured logging to SQLite, /healthz endpoint, dry-run mode flag.
**Addresses:** T21 (secrets), T3 (scheduler skeleton), D10 (dry-run flag), T17 (config UI skeleton)
**Avoids:** Pitfall 5 (PII leakage), Pitfall 11 (credential storage), Pitfall 13 (overlapping runs), Pitfall 15 (silent failures)
**Research flag:** Standard patterns -- no additional research needed.

### Phase 2: Profile, Configuration UI, and Resume Upload
**Rationale:** The pipeline is data-driven from the user profile. Before any scraping or LLM work, the user must configure keywords, thresholds, profile fields, and upload their base DOCX. Test with the user actual resume file immediately -- not a clean template.
**Delivers:** Full profile CRUD, base DOCX upload + storage on volume, keyword/threshold/schedule config, review-queue UI shell, dashboard skeleton.
**Addresses:** T17 (web config UI), T18 (DOCX upload), T12 (profile store), T16 (dashboard), T14 (review queue shell)
**Avoids:** Pitfall 8 (DOCX formatting -- test with real file from day one)
**Research flag:** Standard patterns -- no additional research needed.

### Phase 3: Discovery, Deduplication, and Matching
**Rationale:** Start with Greenhouse and Lever JSON APIs only (zero ban risk, structured data). Validate the full discover -> dedupe -> match -> queue pipeline on safe channels before touching LinkedIn. Dedup must ship before submission -- never the reverse.
**Delivers:** Greenhouse + Lever scrapers via httpx JSON endpoints, Job + Application table writes, canonical fingerprint dedup, keyword scorer with threshold, review queue populated with real matched jobs, canary assertions and anomaly alerting, run observability in UI.
**Addresses:** D5 (ATS-direct ingestion), T6 (metadata extraction), T5 (keyword score), T4 (dedup)
**Avoids:** Pitfall 3 (duplicate submissions), Pitfall 4 (silent scraper breakage)
**Research flag:** Standard patterns -- Greenhouse/Lever JSON APIs are stable and well-documented.

### Phase 4: LLM Tailoring and DOCX Generation
**Rationale:** Now that matched jobs flow into the queue, add tailoring. The budget gates, extractive-only constraint, and post-generation validator must ship together with the first LLM call -- not after.
**Delivers:** LLM Gateway with ClaudeBackend + OllamaBackend (instructor schema enforcement), extractive tailoring prompt with master_resume.yaml atomic facts, post-generation diff validator, daily/monthly budget cap in LLM client wrapper, prompt caching on master resume, DOCX artifact generation via docxtpl, Haiku for scoring / Sonnet for tailoring tiering.
**Addresses:** T7 (LLM tailoring), T8 (DOCX round-trip), T9 (ATS-friendly output), D2 (Ollama fallback), D11 (cover letter)
**Avoids:** Pitfall 2 (hallucination -- extractive-only + validator), Pitfall 5 (PII -- no contact info in LLM prompt), Pitfall 7 (cost -- budget cap + tiering + caching), Pitfall 8 (DOCX formatting -- docxtpl)
**Research flag:** LLM prompt design for extractive tailoring needs a spike before full pipeline integration. Key question: can instructor + structured output reliably constrain hallucination across Claude and Ollama models?

### Phase 5: Email-Apply Submission and Notifications
**Rationale:** Email-apply is the simplest submission channel -- no browser automation, no ban risk. Proves the full pipeline end-to-end on a safe channel. The full-auto toggle and per-job notifications ship here as they depend on a complete application record.
**Delivers:** EmailRecruiterSubmitter (aiosmtplib + attachment), pending_review -> approved -> submitted status transitions, full-auto toggle, per-job email notification, daily digest option, application history in dashboard.
**Addresses:** T11 (email-apply), T14 (full-auto toggle), T15 (history), T19 (per-job email), T20 (daily digest), T22 (rate limiting)
**Avoids:** Pitfall 3 (idempotency key on fingerprint before submit), Pitfall 14 (email deliverability -- <20/day)
**Research flag:** Standard patterns -- no additional research needed.

### Phase 6: Playwright Browser Automation (Greenhouse/Lever forms first)
**Rationale:** Add Playwright submission for ATS forms, starting with Greenhouse/Lever (known structure, no ban risk) before LinkedIn. Submitter registry means this is additive -- no orchestrator changes. Learning loop ships here because unknown form fields only appear in browser flows.
**Delivers:** PlaywrightFormSubmitter with launch_persistent_context (headful/xvfb), label-based field matching, per-step screenshot, NeedsFieldAnswer exception path, UnknownField + FieldAnswer tables, learning loop write-back, review-queue needs_info UI, persistent Playwright storageState on volume.
**Addresses:** T10 (browser automation), T13 (LLM unknown-field fallback), T23 (persistent session), D3 (learning loop), D9 (review-queue diff)
**Avoids:** Pitfall 6 (Workday brittleness -- label-based matching, defer Workday to Phase 8), Pitfall 9 (Easy Apply multi-step -- state machine per step), Pitfall 5 (disable tracing on PII form pages)
**Research flag:** Shadow DOM piercing for Workday may need a dedicated spike. Greenhouse/Lever are safe to build now; Workday deferred to Phase 8.

### Phase 7: LinkedIn and Indeed Discovery + LinkedIn Easy Apply
**Rationale:** Only after the full pipeline is proven on safe channels, add the high-risk discovery and submission channels. The architecture is already correct (persistent context, stealth, rate limiting) -- this phase adds scraper plugins and Easy Apply submitter under existing registries. Budget 2x estimate for this phase.
**Delivers:** python-jobspy integration for LinkedIn + Indeed discovery, LinkedInEasyApplySubmitter with multi-step state machine and question-answer knowledge base, strict rate caps (10-15/day, 3-15 min jitter, human-plausible hours only), warm-up mode (user confirms each click for first 2 weeks), ban warning detection and automatic pause.
**Addresses:** T1 (LinkedIn/Indeed scraping), T10 partial (LinkedIn Easy Apply), T22 (rate limiting -- tightened for LinkedIn)
**Avoids:** Pitfall 1 (LinkedIn ban -- headful, stealth, persistent context, rate caps, warm-up), Pitfall 12 (Cloudflare on Indeed -- stealth + residential IP + backoff)
**Research flag:** LinkedIn Easy Apply DOM changes frequently. Needs live integration testing in a throwaway LinkedIn account before shipping. Do not use the user real account for automated testing.

### Phase 8: Hardening, Observability, and v2 Differentiators
**Rationale:** Clean up technical debt, add differentiating features that require a stable pipeline to validate, and harden for long-running unattended operation.
**Delivers:** Resume version pinning (D6), ghost-job detection heuristics (D7), semantic/embedding-based matching upgrade (D4), multi-profile support (D12), Workday/Taleo push-to-review-queue path, SQLite WAL + backup cron, 90-day log retention, Sentry/self-hosted error tracking, pause button in UI, undo window (5-min delay before submit), per-job skip reason log.
**Addresses:** D4, D6, D7, D12
**Avoids:** Pitfall 15 (observability -- structured logs, daily summary, failure breakdown)
**Research flag:** Sentence-transformers model selection for semantic matching may need a spike (model size vs. accuracy vs. memory for a laptop container).

### Phase Ordering Rationale

- Phases 1-3 before any LLM or submission work: dedup, secrets, and observability are load-bearing for everything downstream. The most expensive bugs (duplicate submissions, PII leaks) are cheapest to prevent when the schema is still being designed.
- Greenhouse/Lever JSON first: the only channels with zero ban risk. Proving the pipeline here before touching LinkedIn means the user has real value before accepting any account risk.
- Email-apply before Playwright: closes the loop end-to-end without browser automation risk. Users see their first real application before any LinkedIn exposure.
- Full-auto toggle defaults OFF through Phase 5: review queue ON by default. Users manually approve ~20 applications, build confidence in tailoring quality, then enable full-auto.
- LinkedIn last (Phase 7): the correct engineering decision even though it feels backward. The architecture is identical -- only the scraper plugin and Easy Apply submitter are new. All risk is operational (ban), not technical.

---

### Research Flags

**Phases needing deeper research or spikes before building:**

- **Phase 4 (LLM Tailoring):** Prompt architecture for extractive-only tailoring is novel and high-stakes. Recommend a 1-2 day prompt design spike using the user actual resume and 5-10 real JDs before wiring into the pipeline.
- **Phase 6 (Playwright forms):** Shadow DOM piercing for modern ATS forms (Workday) is poorly documented. Greenhouse/Lever are safe to build now; Workday needs a dedicated research spike before Phase 8.
- **Phase 7 (LinkedIn Easy Apply):** LinkedIn multi-step Easy Apply DOM changes monthly. Needs live integration testing in a throwaway LinkedIn account before merging.

**Phases with well-documented standard patterns (no additional research needed):**

- **Phase 1 (Foundation):** FastAPI + SQLModel + APScheduler + Docker patterns thoroughly documented. STACK.md has the exact versions and compatibility matrix.
- **Phase 2 (Profile/Config UI):** FastAPI + HTMX + Jinja2 CRUD is standard.
- **Phase 3 (Greenhouse/Lever discovery):** Both have official public JSON APIs with stable schemas.
- **Phase 5 (Email submission):** aiosmtplib + Jinja2 email is well-documented.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against official release notes and PyPI as of 2026-04-11. Version compatibility matrix in STACK.md is explicit. |
| Features | MEDIUM-HIGH | Table stakes and anti-features well-validated via competitor analysis. Specific anti-bot thresholds (e.g. 10-15 LinkedIn applies/day) are community-derived -- treat as directional, not official limits. |
| Architecture | HIGH | Plugin-registry + pipeline-stages + status-machine is a well-established Python data-engineering pattern. Domain-specific mapping validated against multiple community job-bot implementations. |
| Pitfalls | HIGH for categories, MEDIUM for specifics | LinkedIn ban rates (<15% Tier-3 recovery) are from tool vendor blogs, not official LinkedIn sources. Legal specifics (EU automated-decision-making on applicant side) need jurisdiction-specific counsel if ever distributed publicly. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address During Implementation

- **LinkedIn Easy Apply selector stability:** highest-maintenance element of the codebase. Store selectors in a config YAML (not code) so they can be updated without a redeploy. Plan a monthly maintenance budget.
- **Ollama model quality for extractive tailoring:** hallucination risk is higher with local models (llama3.1:8b, qwen2.5:14b) than with Claude Sonnet. The diff validator is the safety net, but its thresholds need calibration per model before enabling Ollama as a primary provider.
- **Workday/iCIMS automation ROI:** may be correct to never fully automate Workday and instead offer pre-fill + user-clicks-submit as the permanent ceiling. Validate during Phase 6 planning.
- **Cost per application target:** <$0.10 with prompt caching and Haiku/Sonnet tiering is achievable but needs empirical validation on the user actual resume and real JDs. Measure cost-per-run from Phase 4 day one.
- **LinkedIn legality per jurisdiction:** hiQ v. LinkedIn (2022) affirmed public-data scraping is not a CFAA violation, but authenticated submission flows are higher risk. Personal-use framing is the defensible zone; legal review required before any public distribution.

---

## Sources

### Primary (HIGH confidence -- official docs, verified 2026-04-11)
- FastAPI 0.135.3 release notes -- https://fastapi.tiangolo.com/release-notes/
- Playwright Python 1.58.0 -- https://pypi.org/project/playwright/
- playwright-stealth 2.0.3 -- https://pypi.org/project/playwright-stealth/
- Anthropic SDK 0.94.0 -- https://github.com/anthropics/anthropic-sdk-python/releases
- python-jobspy 1.1.82+ -- https://github.com/speedyapply/JobSpy
- SQLModel docs -- https://sqlmodel.tiangolo.com/
- Greenhouse Job Board API -- https://developers.greenhouse.io/job-board.html
- Lever Public Postings API -- https://api.lever.co/v0/postings/{company}?mode=json
- cryptography Fernet -- https://cryptography.io/en/latest/fernet/
- aiosmtplib 5.1.x -- https://aiosmtplib.readthedocs.io/
- APScheduler 3.10.x -- https://apscheduler.readthedocs.io/
- Pydantic 2.12 release -- https://pydantic.dev/articles/pydantic-v2-12-release
- Docker Playwright image -- https://hub.docker.com/r/microsoft/playwright-python

### Secondary (MEDIUM confidence -- community consensus, multiple sources)
- Best Docker base image for Python -- https://pythonspeed.com/articles/base-image-python-docker-images/
- LinkedIn automation safety guide 2026 -- https://getsales.io/blog/linkedin-automation-safety-guide-2026/
- Is LinkedIn automation safe 2026 -- https://connectsafely.ai/articles/is-linkedin-automation-safe-tos-scraping-guide-2026
- 15 ATS APIs to integrate with in 2026 -- https://unified.to/blog/15_ats_apis_to_integrate_with_in_2026_greenhouse_lever_workable
- How to scrape job postings legal risks -- https://cavuno.com/blog/job-scraping
- HTMX vs React 2026 -- https://plus8soft.com/blog/htmx-vs-react-comparison/
- Competitor analysis: LoopCV, PitchMeAI, Huntr, OSS bots (GodsScion, wodsuz, NathanDuma)

### Tertiary (LOW confidence -- single source or inference, needs validation)
- LinkedIn ban tier recovery rate <15% for Tier-3 -- cited by growleads.io and dux-soup.com; no official LinkedIn source; treat as directional
- APScheduler 4.0 beta async-native status -- needs re-verification; recommend sticking with 3.10 stable
- JobSpy weekly download count -- Snyk snapshot, possibly stale

---

*Research completed: 2026-04-11*
*Ready for roadmap: yes*
