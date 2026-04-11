# Feature Research

**Domain:** Autonomous job-application automation (single-user, self-hosted)
**Researched:** 2026-04-11
**Confidence:** MEDIUM-HIGH (ecosystem well-documented; specific anti-bot thresholds LOW confidence)

## Feature Landscape

Organized by the apply-loop stages: **Discovery → Matching → Tailoring → Submission → Tracking → Configuration → Notifications → Safety/Compliance**.

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete or unusable.

| # | Stage | Feature | Why Expected | Complexity | Notes |
|---|-------|---------|--------------|------------|-------|
| T1 | Discovery | Multi-source job ingestion (LinkedIn, Indeed, Greenhouse, Lever) | Limiting to one board ignores 60%+ of market | L | Greenhouse/Lever have public no-auth JSON APIs; LinkedIn/Indeed require scraping (ToS risk) |
| T2 | Discovery | Keyword + location + remote filters | Baseline filter criteria on every job board | S | Stored per-profile; passed to scrapers/APIs |
| T3 | Discovery | Hourly (or schedulable) background polling | "Autonomous" implies unattended operation | S | Already committed; cron/APScheduler/Celery beat |
| T4 | Discovery | URL-based deduplication | Re-applying to same job is embarrassing / burns credibility | S | Already committed; hash or canonical URL |
| T5 | Matching | Keyword score with user-adjustable threshold | Users must control apply/skip boundary | S | Already committed; simple TF-IDF or keyword-hit ratio is sufficient for v1 |
| T6 | Matching | Job metadata extraction (title, company, location, description, posted date) | Needed for all downstream steps | M | Per-source parsers; normalize to common schema |
| T7 | Tailoring | LLM-powered resume tailoring per job | Core value prop; generic resumes are table stakes failure | M | Already committed; Claude API + Ollama fallback |
| T8 | Tailoring | DOCX round-trip (parse → modify → regenerate) preserving formatting | Users upload DOCX, expect DOCX back | M | python-docx handles most cases; formatting preservation is the rub |
| T9 | Tailoring | ATS-friendly output (no tables, standard fonts, keyword alignment) | 75% of applications are filtered by ATS before human review | M | Jobscan-style keyword coverage check; section ordering |
| T10 | Submission | Easy Apply / direct form filling via browser automation | The "autonomous" in autonomous apply | L | Playwright preferred over Selenium for stealth + modern DOM |
| T11 | Submission | Email-based apply fallback (when posting lists "email resume to...") | ~30% of non-ATS postings are email-only | M | SMTP + attachment; tailored cover-letter body |
| T12 | Submission | Profile data store (name, email, phone, work auth, years exp, etc.) | Every form asks these 20 fields | S | Already committed; JSON/SQLite |
| T13 | Submission | LLM fallback for unknown form fields with learning loop | Forms have infinite long-tail questions | L | Already committed; key insight — cache answers by normalized question text |
| T14 | Submission | Full-auto vs review-queue toggle | Users need trust ramp; review queue is the trust builder | M | Already committed; queue UI + approve/reject/edit |
| T15 | Tracking | Application history (job, status, resume version, timestamp) | Users need to know what they applied to | S | SQLite table; foreign-keyed to tailored resume artifact |
| T16 | Tracking | Dashboard with counts/status (applied, queued, skipped, failed) | Can't trust what you can't see | M | Single HTML page via FastAPI/Flask + HTMX is sufficient |
| T17 | Configuration | Web UI for profile, keywords, thresholds, schedule | Editing YAML is a deal-breaker for non-devs, and annoying even for devs | M | Same dashboard route |
| T18 | Configuration | Upload/replace base DOCX resume | Core input to the whole pipeline | S | File upload + storage on volume |
| T19 | Notifications | Per-job email summary (job info, match score, tailored resume link, status) | Already committed; primary user feedback channel | S | SMTP with HTML template + DOCX attachment |
| T20 | Notifications | Daily / run-summary digest | Per-job emails become spam at scale (100+/day) | S | Optional — toggle between per-job and digest |
| T21 | Safety | Secrets management (LLM API keys, SMTP, LinkedIn creds) | Never commit creds; user expects env-based config | S | .env + docker secrets; never log |
| T22 | Safety | Rate limiting / human-like delays | Avoid instant bans on LinkedIn/Indeed | M | Randomized 30-120s gaps, daily caps, session breaks |
| T23 | Safety | Persistent browser session / cookies across runs | Re-login every hour triggers anti-bot | M | Playwright storageState + volume mount |

### Differentiators (Competitive Advantage vs LoopCV, PitchMeAI, Huntr, Jobscan)

Features that set this app apart from $22-50/month SaaS competitors.

| # | Stage | Feature | Value Proposition | Complexity | Notes |
|---|-------|---------|-------------------|------------|-------|
| D1 | All | Self-hosted / dockerized single-container deploy | Data sovereignty: resume + answers never leave your box; no subscription; LinkedIn cookies stay local | M | `docker compose up` as the whole install story |
| D2 | Tailoring | Local LLM via Ollama as primary or fallback | Zero API cost at scale (100+ apps/day); privacy for resume data | M | Already committed; test with Llama 3.1 8B / Qwen2.5 |
| D3 | Submission | Unknown-field learning loop (ask LLM once, persist answer, reuse) | Forms get smarter over time instead of repeatedly guessing | M | Already committed; this is the real moat — very few OSS bots do this |
| D4 | Matching | Semantic matching (embeddings) on top of keyword score | Catches "software engineer" jobs using "developer" in title; Huntr differentiates on this | M | Sentence-transformers local; optional upgrade from pure keyword |
| D5 | Discovery | ATS-direct mode (Greenhouse/Lever public API) bypassing LinkedIn | Structured JSON, no ban risk, richer metadata | S | Greenhouse boards-api.greenhouse.io is free & documented |
| D6 | Tailoring | Per-job resume version pinning (git-like history) | User can see exactly what was sent for any past application | S | Store artifact path in application row |
| D7 | Tracking | Ghost-job detection (age, re-post frequency, employer patterns) | 18-22% of listings are ghost jobs per Greenhouse 2024 report; skipping them saves effort | M | Heuristics: posted > 60 days, same title re-posted monthly |
| D8 | Tracking | Response tracking via IMAP inbox scan | Auto-close applications when rejection/interview email arrives | L | IMAP + LLM classifier; strong differentiator but complex |
| D9 | Configuration | Review-queue with inline resume diff and LLM re-generation | User sees exact diff from base → tailored; can regenerate before send | M | Monaco diff viewer or simple unified diff |
| D10 | Safety | Kill-switch + dry-run mode | User can simulate an entire run without actually submitting | S | Global flag; critical for trust during onboarding |
| D11 | Tailoring | Cover letter generation (optional, per-job) | Most OSS bots skip this; meaningful lift for competitive roles | S | Same LLM call, different prompt; attach to email |
| D12 | Submission | Multi-profile support (different resumes per role family) | Frontend/backend/data roles need different base resumes | M | "Profile = {base_resume + keywords + threshold}"; route job to best profile |

### Anti-Features (Deliberately NOT Built)

Features that seem good but create legal, ethical, ban, or complexity risk.

| # | Feature | Why Requested | Why Problematic | Alternative |
|---|---------|---------------|-----------------|-------------|
| A1 | LinkedIn DM/InMail to recruiters | "Get past the ATS by reaching out directly" | Violates LinkedIn ToS §8.2 prohibited automation; triggers restricted-account flags within days; behavioral biometrics detect scripted messaging | If user wants outreach, surface recruiter name + profile link in review queue and let user message manually |
| A2 | Connection request spam on LinkedIn | "Grow network to surface more jobs" | Hard rate limit (~100/week) + any automation = account ban; LinkedIn's anti-bot tracks behavioral rhythm, not just volume | Out of scope. App does job apply, not network growth |
| A3 | Fake/fabricated resume content (invented experience, inflated years) | "Match every JD keyword to pass ATS" | Legal fraud, reputational destruction if caught, and degrades all downstream trust signals | Tailor = reword/reorder/emphasize REAL experience. Hard prompt constraint: "never invent facts" |
| A4 | Unlimited concurrent browser sessions | "Apply faster" | LinkedIn/Indeed detect parallel sessions from same account instantly; one session is the only safe posture | Serial queue with randomized delays (T22) |
| A5 | Captcha-solving service integration (2Captcha, Anti-Captcha) | "Handle LinkedIn's login captcha" | Explicit ToS violation; when (not if) detected, permanent ban; also costs money per apply | Pause run + notify user to solve manually; persist session (T23) to minimize recurrences |
| A6 | Credential harvesting for new accounts on user's behalf | "Create fresh LinkedIn accounts when old one bans" | LinkedIn real-name policy + device fingerprinting; creates legal exposure for user | Accept that LinkedIn is high-risk; lean on ATS-direct (D5) as the durable channel |
| A7 | Scraping LinkedIn candidate/people data | "Build a network map" | Separate ToS violation from job scraping; data broker territory; irrelevant to apply loop | Scope discipline: this app applies to jobs, not sources candidates |
| A8 | "Apply to 1000 jobs/day" marketing stance | "Maximize funnel" | Guarantees LinkedIn/Indeed ban; also produces 0 interviews (spray-and-pray fails ATS quality signals) | Position as "quality-first automation"; enforce sane daily caps (e.g. 30/day default) |
| A9 | Multi-user / SaaS mode (tenant isolation, billing, auth) | "Let friends use it too" | 10x complexity (auth, quotas, credential isolation, RBAC, legal liability for their apply activity) | Single-user is a feature. Friend wants it? They run their own container |
| A10 | Salary negotiation / offer auto-acceptance | "Full autonomy" | Life-impact decisions should never be automated; also no meaningful data to train on | Hard boundary: automation stops at application submission |
| A11 | Interview scheduling automation | "Close the loop" | Calendar integration + timezone + recruiter email parsing = large scope; most ATS send schedule links anyway | Out of scope v1. Surface interview emails in dashboard via D8 |
| A12 | Browser extension instead of headless container | "Use my real browser session" | Extensions are exactly what LinkedIn's ToS lists as prohibited; also fights docker-first architecture | Playwright with persistent storageState is the right primitive |
| A13 | AI avatar / video cover letters | "Stand out" | Novelty, not adoption; most ATS strip non-standard attachments; hallucination risk if voice-cloned | Text cover letter (D11) is the boring correct answer |
| A14 | Workday / Taleo / iCIMS full automation | "Cover every ATS" | These ATSs have aggressive bot detection + multi-page flows + account creation per employer; engineering cost dwarfs value | Detect and push to review queue with pre-filled data; user clicks through manually |
| A15 | Real-time job streaming (websockets, sub-minute) | "Apply before others" | LinkedIn/Indeed don't expose streams; polling <1h doesn't improve outcomes (ATS doesn't rank by submission time); ban-risk multiplier | Hourly poll is already the correct cadence |

## Feature Dependencies

```
[T18 base resume upload]
    └─requires─> [T7 LLM tailoring]
                     ├─requires─> [T8 DOCX round-trip]
                     └─enhances─> [D11 cover letter]

[T1 multi-source ingestion]
    ├─requires─> [T6 metadata extraction]
    │                 └─requires─> [T5 keyword scoring]
    │                                   └─enhances─> [D4 semantic matching]
    └─enhances──> [D5 ATS-direct mode]  (lower-risk channel)

[T10 browser automation]
    ├─requires─> [T12 profile store]
    ├─requires─> [T13 LLM field fallback]
    ├─requires─> [T23 persistent session]
    ├─requires─> [T22 rate limiting]
    └─conflicts─> [A4 parallel sessions], [A5 captcha solving], [A12 extensions]

[T14 full-auto/review toggle]
    ├─requires─> [T15 application history]
    ├─requires─> [T16 dashboard]
    └─enhances─> [D9 review-queue diff]

[T15 history] ──enhances──> [T4 URL dedup]  (dedup reads history)
[T15 history] ──enhances──> [D8 IMAP response tracking]
[T15 history] ──enhances──> [D6 resume version pinning]

[T19 email notifications]
    └─requires─> [T21 secrets] (SMTP creds)

[T3 scheduler]
    └─requires─> [T22 rate limiting]  (else schedule = ban)

[D2 local Ollama] ──enhances──> [T7 tailoring]  (cost/privacy)
[D3 learning loop] ──requires──> [T13 LLM fallback] (stores its outputs)

[T2 filters] ──requires──> [T17 config UI]
[D12 multi-profile] ──requires──> [T17 config UI], [T18 base resume]
[D10 dry-run] ──enhances──> [T14 review toggle]  (trust ramp)
```

### Dependency Notes

- **Scheduler (T3) hard-requires rate limiting (T22):** an unthrottled hourly loop against LinkedIn = 24h to ban. These must ship together.
- **Browser automation (T10) depends on session persistence (T23):** every login triggers captcha/verification, which breaks automation. Persistent storageState is load-bearing.
- **Learning loop (D3) depends on LLM fallback (T13):** D3 is the cache layer for T13's outputs. Shipping T13 without persistence means the LLM is re-queried for the same questions forever (cost + latency).
- **Review queue (T14) should ship before full-auto:** trust ramp. Users approve ~20 applications manually, build confidence, then flip the toggle.
- **ATS-direct (D5) is the safest discovery channel:** prioritize over LinkedIn/Indeed scraping. Greenhouse/Lever public APIs have zero ban risk and richer structured data.
- **Semantic matching (D4) enhances but doesn't replace keyword matching (T5):** ship T5 first, add D4 as opt-in upgrade once keyword score is validated.
- **IMAP tracking (D8) conflicts nothing but is expensive:** defer to v1.x — not MVP. Depends on stable application history schema (T15).

## MVP Definition

### Launch With (v1) — the minimum to prove "autonomous apply works"

- [ ] **T18** Base DOCX upload — input to everything
- [ ] **T17** Web UI for profile + keywords + threshold + schedule — non-devs use it
- [ ] **T12** Profile data store — standard form fields
- [ ] **D5** Greenhouse + Lever public API ingestion — safe, structured, zero ban risk (start here, not LinkedIn)
- [ ] **T6** Metadata extraction + normalization
- [ ] **T5** Keyword match score with threshold — already committed
- [ ] **T4** URL dedup — already committed
- [ ] **T7** LLM resume tailoring (Claude + Ollama fallback) — already committed
- [ ] **T8** DOCX round-trip — required to produce output
- [ ] **T9** ATS-friendly output checks — or tailoring is decorative
- [ ] **T11** Email-apply submission path — simpler than browser; many ATSs accept email
- [ ] **T14** Review queue (default ON) + **D10** dry-run mode — trust ramp from day 1
- [ ] **T15** Application history + **T16** dashboard — users need to see what happened
- [ ] **T19** Per-job email summary — already committed; primary feedback channel
- [ ] **T21** Secrets via env/docker — basic hygiene
- [ ] **T3** Hourly scheduler — already committed
- [ ] **T22** Rate limiting — must ship with scheduler

**Deliberately NOT in v1:** browser automation for LinkedIn/Indeed. Start with email-apply + ATS-direct. Add browser automation in v1.1 once the pipeline is proven on safe channels.

### Add After Validation (v1.x)

- [ ] **T10 + T23** Playwright browser automation with persistent session — trigger: v1 is stable and user wants LinkedIn Easy Apply coverage
- [ ] **T13 + D3** LLM field fallback + learning loop — trigger: shipping T10 (unknown fields only appear in browser flows; email flows don't have them)
- [ ] **T1** LinkedIn + Indeed scrapers — trigger: v1 is stable; accept ban risk explicitly
- [ ] **D11** Cover letter generation — trigger: user feedback requests it
- [ ] **D9** Review-queue inline diff — trigger: review queue is the main interaction surface
- [ ] **T20** Daily digest mode — trigger: per-job email volume exceeds ~20/day
- [ ] **D6** Resume version pinning — trigger: first "what did you send for X?" support question

### Future Consideration (v2+)

- [ ] **D4** Semantic matching with embeddings — defer: keyword is good enough until user reports misses
- [ ] **D7** Ghost-job detection — defer: needs data to tune heuristics
- [ ] **D8** IMAP response tracking — defer: large scope (auth, classifiers, mailbox perms)
- [ ] **D12** Multi-profile support — defer: single profile validates first
- [ ] **A14** Workday/Taleo/iCIMS partial automation — defer: high effort; fall back to review queue for now

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| T7 LLM resume tailoring | HIGH | MEDIUM | P1 |
| T8 DOCX round-trip | HIGH | MEDIUM | P1 |
| T11 Email-apply submission | HIGH | MEDIUM | P1 |
| T14 Review queue toggle | HIGH | MEDIUM | P1 |
| T19 Per-job email notifications | HIGH | LOW | P1 |
| D5 Greenhouse/Lever ATS-direct | HIGH | LOW | P1 |
| T22 Rate limiting | HIGH | MEDIUM | P1 (with T3) |
| D10 Dry-run mode | HIGH | LOW | P1 |
| T16 Dashboard | MEDIUM | MEDIUM | P1 |
| T17 Web config UI | HIGH | MEDIUM | P1 |
| T10 Browser automation (LinkedIn) | HIGH | HIGH | P2 |
| T13 LLM unknown-field fallback | MEDIUM | HIGH | P2 |
| D3 Field learning loop | HIGH | MEDIUM | P2 |
| D2 Ollama local LLM | MEDIUM | MEDIUM | P2 |
| D11 Cover letter generation | MEDIUM | LOW | P2 |
| D9 Review-queue diff | MEDIUM | MEDIUM | P2 |
| T1 LinkedIn/Indeed scrapers | MEDIUM | HIGH | P2 |
| D4 Semantic matching | LOW | MEDIUM | P3 |
| D7 Ghost-job detection | LOW | MEDIUM | P3 |
| D8 IMAP response tracking | MEDIUM | HIGH | P3 |
| D12 Multi-profile | LOW | MEDIUM | P3 |

## Competitor Feature Analysis

| Feature | LoopCV (SaaS, $) | PitchMeAI (SaaS, $22/mo) | Huntr (SaaS) | OSS LinkedIn Bots (GodsScion, wodsuz) | Our Approach |
|---------|---|---|---|---|---|
| LinkedIn Easy Apply | Yes (extension) | Yes | Partial | Yes (headless) | Deferred to v1.1; start with ATS-direct |
| Resume tailoring | Basic | LLM-powered | Semantic matching | No / template-based | LLM (Claude + Ollama) with ATS checks |
| Multi-source discovery | LinkedIn primary | LinkedIn + indeed | Manual + extension | LinkedIn only | Greenhouse + Lever first, LinkedIn in v1.1 |
| Self-hosted | No | No | No | Yes (scripts) | Yes, docker-first |
| Cost | Subscription | $22/mo | Freemium | Free but brittle | Free + optional Claude API usage |
| Field learning loop | No | No | No | Hardcoded Q&A | Yes (LLM + persistent cache) — key differentiator |
| Review queue | No (auto only) | Chat-based | Manual | No | Yes, default on |
| Response tracking | Basic | Yes | Yes | No | v2 via IMAP |
| Ghost job filter | No | No | Partial | No | v2 heuristics |
| DOCX output | PDF usually | PDF | PDF | N/A | DOCX (user input was DOCX) |

**Our positioning:** "Self-hosted autonomous apply with a learning loop — no subscription, your data stays on your machine, quality over volume."

## Sources

- [LoopCV LinkedIn Auto Apply](https://www.loopcv.pro/linkedin-auto-apply/)
- [GodsScion Auto_job_applier_linkedIn (OSS)](https://github.com/GodsScion/Auto_job_applier_linkedIn)
- [wodsuz EasyApplyJobsBot (OSS)](https://github.com/wodsuz/EasyApplyJobsBot)
- [NathanDuma LinkedIn-Easy-Apply-Bot (OSS)](https://github.com/NathanDuma/LinkedIn-Easy-Apply-Bot)
- [Huntr best resume tailor comparison 2026](https://huntr.co/blog/best-resume-tailor)
- [PitchMeAI end-to-end automation](https://pitchmeai.com/blog/best-ai-resume-tailoring-tools)
- [Reztune AI resume tailoring roundup](https://www.reztune.com/blog/best-ai-resume-tailoring-2025/)
- [Best AI tools for ATS optimization 2026](https://bestjobsearchapps.com/articles/en/6-best-ai-tools-for-atsoptimized-job-applications-in-2026)
- [LinkedIn prohibited software and extensions](https://www.linkedin.com/help/linkedin/answer/a1341387)
- [LinkedIn automated activity policy](https://www.linkedin.com/help/linkedin/answer/a1340567)
- [LinkedIn automation safety guide 2026](https://getsales.io/blog/linkedin-automation-safety-guide-2026/)
- [Is LinkedIn automation safe 2026](https://connectsafely.ai/articles/is-linkedin-automation-safe-tos-scraping-guide-2026)
- [LinkedIn ToS enforcement triggers](https://pettauer.net/en/linkedin-tos-breaches-risk-enforcement-comparison/)
- [Can you get banned for scraping LinkedIn](https://konnector.ai/banned-for-scraping-linkedin/)
- [Greenhouse Jobs Scraper API (Apify)](https://apify.com/automation-lab/greenhouse-jobs-scraper)
- [15 ATS APIs to integrate with 2026](https://unified.to/blog/15_ats_apis_to_integrate_with_in_2026_greenhouse_lever_workable)
- [How to scrape job postings 2026 legal risks](https://cavuno.com/blog/job-scraping)

---
*Feature research for: autonomous single-user job-application automation*
*Researched: 2026-04-11*
