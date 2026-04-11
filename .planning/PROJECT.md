# Job Application Auto-Apply

## What This Is

A dockerized, single-user web app that autonomously finds and applies to jobs on your behalf. You upload a base DOCX resume and a list of keywords describing the jobs you want; every hour the app scrapes job boards (LinkedIn, Indeed, Greenhouse/Lever ATS, general web), tailors your resume per job using an LLM, submits the application (browser automation, Easy Apply, or email-the-recruiter), and emails you a summary for each job it applied to.

## Core Value

Given a base resume + keywords, the app gets your tailored application in front of every matching job posting — with zero manual effort after setup.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] User can upload a base DOCX resume
- [ ] User can configure a list of keywords describing target jobs
- [ ] User can set a match threshold (apply if ≥ N% keyword overlap; default floor 50%)
- [ ] User can choose LLM backend per run: Claude API or local Ollama model
- [ ] User can fill a profile (name, contact, work auth, salary expectations, etc.) reused across applications
- [ ] App runs on an hourly schedule as a background process inside the container
- [ ] App scrapes jobs from LinkedIn, Indeed, Greenhouse, and Lever boards
- [ ] App discovers jobs from general web search based on user keywords
- [ ] App filters jobs by keyword match against user's threshold
- [ ] App skips jobs it has already applied to (dedup by job URL / board ID)
- [ ] LLM rewrites the base DOCX resume to tailor bullets/keywords per job
- [ ] App submits applications via browser automation (Playwright) for custom ATS forms
- [ ] App submits applications via LinkedIn Easy Apply flow
- [ ] App submits applications via email (drafts + sends email with tailored resume attached) when contact email is available
- [ ] When the form asks a question the profile/LLM can't confidently answer, app logs the unknown field and skips or queues the application
- [ ] User can review logged unknown fields in the web UI and provide answers
- [ ] Answers to unknown fields are persisted and reused for future applications
- [ ] User can toggle between **full-auto** mode (submit without review) and **review queue** mode (app prepares application, user approves in UI before submit)
- [ ] App sends one summary email per job successfully applied to, including which job, which tailored resume version was sent, and match score
- [ ] Job board credentials are stored encrypted at rest (config/env-based)
- [ ] App ships as a Docker image; `docker run` (or compose) brings up the full stack
- [ ] Web UI for: uploading resume, managing keywords, editing profile, viewing application history, reviewing queue, answering unknown fields

### Out of Scope

- **Multi-user accounts / SaaS** — Single-user per deployment. Anyone can run their own Docker instance, but there is no signup/login/tenant isolation. *Why:* Keeps scope tractable; credential handling, auth, and isolation would multiply complexity.
- **Video interviews, assessments, take-home tests** — Only the application submission step is automated. *Why:* Outside the "apply" action, and highly variable.
- **Recruiter outreach / DM automation on LinkedIn** — Risk of account ban; not the core loop. *Why:* Terms-of-service risk and not required for core value.
- **Mobile app** — Web UI only. *Why:* Runs locally in Docker; desktop browser is sufficient.
- **Application tracking beyond summary emails** — No analytics dashboard, funnel reports, response-rate tracking in v1. *Why:* Ship the apply loop first; add tracking after it's validated.
- **Resume formats other than DOCX for input** — PDF/LaTeX/MD not supported as base input in v1. *Why:* Single format keeps tailoring pipeline simple; DOCX is the most common and editable.

## Context

- **Deployment target:** User's laptop, via Docker. Must run anywhere Docker runs. No cloud services required beyond optional Claude API key and SMTP for email.
- **LLM strategy:** Configurable backend. Claude API (quality, paid) OR local Ollama model (free, private, lower quality). User picks per run or as a default.
- **Resume pipeline:** Base DOCX → parse → send content + job description to LLM → receive tailored content → re-render as DOCX → attach to application.
- **Scraping reality:** LinkedIn/Indeed actively fight scrapers. Browser automation via Playwright is the only reliable path for those. Greenhouse/Lever boards have public JSON endpoints that are scraper-friendly. General web job discovery will likely use a search engine + URL classification.
- **Rate / ban risk:** Aggressive scraping + automated applies can get accounts flagged. App should throttle and respect per-board cadence.
- **Learning loop is a first-class feature:** The unknown-field → user-answer → save-and-reuse cycle is what makes the app get better per user over time.

## Constraints

- **Tech stack**: Python + FastAPI backend, simple web UI (Jinja or lightweight SPA) — Python has the best ecosystem for Playwright, DOCX parsing, and LLM libraries.
- **Packaging**: Must ship as a Docker image / docker-compose setup — user requirement for portability across laptops.
- **Runtime**: Runs fully on user's laptop. No required cloud infra beyond optional outbound API calls (Claude, SMTP, job boards).
- **Secrets**: Credentials (job board logins, API keys, SMTP password) encrypted at rest in config.
- **Resume input format**: DOCX only for v1.
- **LLM**: Must support both Claude API and a local Ollama-compatible model behind the same interface.
- **Schedule**: Hourly background job, in-container (e.g., APScheduler or cron inside the image).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single-user per deployment (not SaaS) | Keeps scope tractable; user explicitly chose "not hardcoded to me" over full multi-tenant | — Pending |
| Python / FastAPI stack | Best ecosystem for Playwright + LLM + DOCX; user preference | — Pending |
| Dockerized distribution | Portability across laptops is a user requirement | — Pending |
| LLM backend is pluggable (Claude API + local Ollama) | User wants the choice; privacy vs quality tradeoff at runtime | — Pending |
| Keyword-overlap matching (user-defined threshold, not LLM scoring) | User wants control over what "match" means; simpler and cheaper than LLM scoring per job | — Pending |
| Three apply methods supported (browser automation, Easy Apply, email) | Covers the spread of how real jobs are actually applied to | — Pending |
| Unknown-field learning loop | User-requested: unknown form fields logged → user answers → answers saved and reused | — Pending |
| Mode toggle: full-auto vs review queue | User wants both, as a preset | — Pending |
| One email per application (not digest) | User explicitly picked per-job emails | — Pending |
| Dedup by job URL / board ID | Prevent re-applying to the same posting across hourly runs | — Pending |

---
*Last updated: 2026-04-11 after initialization*
