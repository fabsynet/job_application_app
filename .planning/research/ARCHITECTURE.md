# Architecture Research

**Domain:** Autonomous job-application automation (single-user, Dockerized, laptop-hosted)
**Researched:** 2026-04-11
**Confidence:** HIGH (standard patterns for scraper + worker + web UI systems; MEDIUM for submission-strategy abstractions since those are bespoke)

## Standard Architecture

This is a classic **scheduled-worker + web-UI + shared-store** topology. A single FastAPI process exposes the UI and API; an APScheduler-driven worker runs the pipeline hourly inside the same process (or a sibling process sharing the volume). All state lives in SQLite on a mounted Docker volume. The LLM, scrapers, and submitters are behind narrow interfaces so any of them can be swapped without touching the pipeline.

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Presentation Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│  │  FastAPI     │  │  Jinja2      │  │  HTMX / tiny │                │
│  │  routes /api │  │  templates   │  │  JS partials │                │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │
│         │                 │                 │                        │
├─────────┴─────────────────┴─────────────────┴────────────────────────┤
│                         Orchestration Layer                          │
│  ┌────────────────────┐   ┌──────────────────────────────────────┐   │
│  │  APScheduler       │──▶│       Pipeline Orchestrator          │   │
│  │  (hourly cron)     │   │  discover→match→tailor→submit→notify │   │
│  └────────────────────┘   └──────┬───────────────────────────────┘   │
│                                  │                                   │
├──────────────────────────────────┴───────────────────────────────────┤
│                            Domain Services                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐   │
│  │ Scraper  │ │ Matcher  │ │  LLM     │ │Submitter │ │ Notifier  │   │
│  │ Registry │ │ (kw/rank)│ │ Gateway  │ │ Registry │ │ (SMTP)    │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘   │
│       │            │            │            │             │         │
│  ┌────┴────────────┴────────────┴────────────┴─────────────┴────┐    │
│  │               Profile / Learning / Review Services            │    │
│  └───────────────────────────┬───────────────────────────────────┘    │
├──────────────────────────────┴────────────────────────────────────────┤
│                          Persistence Layer                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐   │
│  │ SQLite   │ │ Fernet   │ │ Artifact │ │ Playwright│ │  Logs /   │   │
│  │ (SQLAlch)│ │ Secrets  │ │ FS (PDFs)│ │  profile  │ │  runs.db  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘   │
└───────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| FastAPI app | HTTP routes for UI + JSON API, auth gate | `app/web/` — routers for jobs, applications, profile, review, runs, settings |
| Jinja2 + HTMX | Server-rendered UI with partial updates (review queue, live run status) | `app/web/templates/` + `static/` |
| APScheduler | Fires the hourly pipeline run, retry on failure, holds full-auto toggle gate | `AsyncIOScheduler` inside the FastAPI process |
| Pipeline Orchestrator | Sequences stages, writes a `Run` record, emits events, honors dry-run/full-auto | `app/pipeline/orchestrator.py` |
| Scraper Registry | Holds `Scraper` plugins keyed by source; fans out per-source queries | Plugin pattern — one module per source implementing a common protocol |
| Scraper plugins | Fetch and normalize job listings from one source | `linkedin.py`, `indeed.py`, `greenhouse.py`, `lever.py`, `generic_web.py` |
| Deduplicator | Rejects already-seen jobs by canonical key + fuzzy hash | Uniqueness on `(source, source_id)` plus `simhash(title+company+desc)` |
| Matcher | Scores job vs profile (keywords, title, location, salary) | Pure Python scoring; no LLM in hot path for cost |
| LLM Gateway | Single interface over Claude API + Ollama, prompt + output schemas | `LLMBackend` ABC with `ClaudeBackend` and `OllamaBackend` |
| Resume Tailor | Builds tailored resume + cover letter per job using LLM gateway | Produces PDF via WeasyPrint/ReportLab, stored in artifact FS |
| Submitter Registry | Picks a submission strategy for a given job | `BrowserPlaywrightSubmitter`, `LinkedInEasyApplySubmitter`, `EmailRecruiterSubmitter` |
| Profile Store | Canonical user profile + answers to known questions | SQLAlchemy models; versioned snapshots |
| Learning Loop | Captures unknown form fields during submit, queues them for user answer, re-applies next run | `UnknownField` + `FieldAnswer` tables, merged back into Profile |
| Review Queue | Human approval gate for non-full-auto jobs and for unknown-field resolution | Status machine: `proposed → approved → submitted` |
| Notifier | Sends per-job email on submit / on review needed / on failure | `aiosmtplib` + Jinja email templates |
| Secrets Vault | Encrypts API keys, site credentials, SMTP creds at rest | Fernet key from env, `secrets` table with encrypted blobs |
| Runs Ledger | Every scheduled run recorded with stage timings, counts, errors | `runs` and `run_events` tables, surfaced in UI |

## Recommended Project Structure

```
job_application_app/
├── app/
│   ├── main.py                 # FastAPI factory, startup: scheduler, DB, secrets
│   ├── config.py               # Pydantic Settings, env loading
│   ├── db/
│   │   ├── base.py             # SQLAlchemy metadata + session
│   │   ├── models.py           # Job, Application, Profile, UnknownField, Run, Secret
│   │   └── migrations/         # Alembic
│   ├── web/
│   │   ├── routers/            # jobs, applications, profile, review, runs, settings
│   │   ├── templates/          # Jinja2 pages + HTMX partials
│   │   ├── static/
│   │   └── deps.py             # auth, db session, current settings
│   ├── pipeline/
│   │   ├── orchestrator.py     # discover→match→tailor→submit→notify
│   │   ├── stages/
│   │   │   ├── discover.py     # calls scraper registry
│   │   │   ├── dedupe.py
│   │   │   ├── match.py        # keyword matcher / scoring
│   │   │   ├── tailor.py       # calls LLM gateway
│   │   │   ├── submit.py       # picks submitter, handles review gate
│   │   │   └── notify.py
│   │   └── events.py           # stage event bus (for UI streaming)
│   ├── scrapers/
│   │   ├── base.py             # Scraper protocol + JobListing dataclass
│   │   ├── linkedin.py
│   │   ├── indeed.py
│   │   ├── greenhouse.py       # ATS JSON APIs
│   │   ├── lever.py
│   │   ├── generic_web.py      # fallback via Playwright + readability
│   │   └── registry.py
│   ├── llm/
│   │   ├── base.py             # LLMBackend ABC, prompts, response schemas
│   │   ├── claude.py           # anthropic SDK
│   │   ├── ollama.py           # local HTTP client
│   │   └── prompts/            # resume/cover-letter/field-answer templates
│   ├── submitters/
│   │   ├── base.py             # Submitter protocol, SubmissionResult
│   │   ├── playwright_form.py  # generic browser form filler
│   │   ├── linkedin_easy.py
│   │   ├── email_recruiter.py
│   │   └── registry.py         # chooses strategy per JobListing
│   ├── profile/
│   │   ├── service.py          # profile CRUD, resume base, answers
│   │   └── learning.py         # unknown-field capture + merge
│   ├── notifier/
│   │   ├── email.py            # SMTP via aiosmtplib
│   │   └── templates/
│   ├── scheduler/
│   │   └── jobs.py             # APScheduler bindings + cron config
│   ├── security/
│   │   ├── secrets.py          # Fernet wrapper
│   │   └── auth.py             # single-user session / basic auth
│   └── artifacts/              # tailored resumes/cover letters on disk
├── tests/
│   ├── unit/
│   ├── integration/            # pipeline with fakes
│   └── fixtures/
├── docker/
│   ├── Dockerfile              # python:3.12-slim + playwright deps
│   ├── docker-compose.yml      # one service, volumes for db + artifacts
│   └── entrypoint.sh
├── alembic.ini
├── pyproject.toml
└── .planning/
```

### Structure Rationale

- **`app/pipeline/stages/`:** each stage is a pure, testable function that takes a `Run` context and writes to the store, making it trivial to add retries, dry-run, and per-stage metrics.
- **`app/scrapers/`, `app/submitters/`, `app/llm/` as registries with a `base.py` protocol:** this is the core pluggability axis. Adding a new source or new submission strategy never touches the orchestrator.
- **`app/web/` separate from `app/pipeline/`:** the orchestrator must be callable without the HTTP stack (for cron, CLI, tests). The web layer only *observes* and *triggers*.
- **`app/profile/learning.py` isolated:** the learning loop is cross-cutting — it reads from submits and writes back to profile; keeping it in its own module prevents the submitter from knowing about profile internals.
- **`artifacts/` on a Docker volume:** tailored PDFs must outlive container rebuilds; SQLite stores only metadata paths.

## Architectural Patterns

### Pattern 1: Plugin Registry via Protocol

**What:** Every extensibility axis (scraper, LLM backend, submitter) is a Python `Protocol` or ABC with a registry that maps a key to an implementation.
**When to use:** Anywhere you will predictably add a new variant (new ATS, new model, new application flow).
**Trade-offs:** Slight indirection overhead; huge win for testability because you inject `FakeScraper`/`FakeLLM`/`FakeSubmitter` in integration tests.

```python
# app/scrapers/base.py
class Scraper(Protocol):
    source: str
    async def search(self, query: SearchQuery) -> list[JobListing]: ...

# app/scrapers/registry.py
_REGISTRY: dict[str, Scraper] = {}
def register(s: Scraper) -> None: _REGISTRY[s.source] = s
def all_scrapers() -> list[Scraper]: return list(_REGISTRY.values())
```

### Pattern 2: Pipeline as Explicit Stages with a Run Context

**What:** The orchestrator passes a `RunContext` (run_id, settings, db session, event bus) through a list of stage functions. Each stage returns a typed result that feeds the next.
**When to use:** Any multi-step batch job where you want observability and partial-replay.
**Trade-offs:** More boilerplate than a single "do it all" function, but lets you resume from `tailor` after a crash in `submit`.

```python
async def run_pipeline(ctx: RunContext) -> RunResult:
    jobs = await discover(ctx)
    jobs = dedupe(ctx, jobs)
    scored = match(ctx, jobs)
    for job in scored.accepted:
        tailored = await tailor(ctx, job)
        outcome = await submit(ctx, job, tailored)
        await notify(ctx, job, outcome)
```

### Pattern 3: Strategy Selection by Job Shape

**What:** `SubmitterRegistry.pick(job)` inspects the `JobListing` (has ATS URL? LinkedIn Easy Apply flag? only recruiter email?) and returns the right submitter.
**When to use:** When the same logical action has multiple physical channels.
**Trade-offs:** Selection logic must stay pure and explicit — resist hiding it inside each submitter's `can_handle`.

```python
def pick(job: JobListing) -> Submitter:
    if job.linkedin_easy_apply: return linkedin_easy
    if job.ats in ("greenhouse", "lever", "workday"): return playwright_form
    if job.recruiter_email: return email_recruiter
    raise NoSubmitterError(job)
```

### Pattern 4: Human-in-the-Loop Gate via Status Machine

**What:** Every `Application` has a status: `discovered → matched → tailored → pending_review → approved → submitted → confirmed | failed | needs_info`. Full-auto mode auto-transitions `pending_review → approved`; otherwise the web UI is the only thing that can advance the state.
**When to use:** Any automation where the user wants a kill switch.
**Trade-offs:** Adds state complexity but is the cleanest way to express "full-auto toggle" without branching code paths everywhere.

### Pattern 5: Learning Loop as Write-Back Queue

**What:** When a submitter hits an unknown form field, it writes an `UnknownField(job_id, field_name, field_type, options, context)` row and raises `NeedsFieldAnswer`. The pipeline marks the application `needs_info` and notifies the user. The UI lets the user answer; answers are merged into `Profile.answers`. The next hourly run retries the job using the enriched profile.
**When to use:** Any time the automation will encounter unpredictable inputs.
**Trade-offs:** Requires idempotent retry and careful dedup of unknown fields across jobs.

### Pattern 6: LLM Gateway with Schema-Enforced Output

**What:** A single `LLMGateway.complete(prompt, schema)` method that both Claude and Ollama backends implement. Outputs are validated against Pydantic schemas; invalid outputs trigger one retry with a repair prompt, then fall back to a templated default.
**When to use:** Any LLM call whose output feeds downstream deterministic code.
**Trade-offs:** Ollama models vary in JSON discipline — keep schemas narrow.

## Data Flow

### Data Model (essentials)

```
Profile(id, basics_json, resume_base_md, answers_json, updated_at)
Secret(name, ciphertext, updated_at)

Job(id, source, source_id UNIQUE, url, title, company, location,
    salary_min, salary_max, remote, description_md, ats, recruiter_email,
    linkedin_easy_apply, raw_json, discovered_at, simhash)

Application(id, job_id FK, status, score, tailored_resume_path,
            tailored_cover_path, submitter, submitted_at, confirmation,
            error, last_update)

UnknownField(id, application_id FK, name, label, type, options_json,
             context, status, created_at)
FieldAnswer(id, name, value, source_application_id, created_at)

Run(id, started_at, finished_at, status, counts_json)
RunEvent(id, run_id FK, stage, level, message, ts)
```

### Request / Pipeline Flow

```
[APScheduler tick every 1h]
        ↓
[Orchestrator.start_run] ──writes──▶ Run row
        ↓
[discover]  ──uses──▶ ScraperRegistry ──▶ JobListings
        ↓
[dedupe]    ──reads/writes──▶ Job (unique on source/source_id + simhash)
        ↓
[match]     ──reads──▶ Profile, ──writes──▶ Application(status=matched, score)
        ↓
[tailor]    ──uses──▶ LLMGateway (Claude or Ollama)
            ──writes──▶ artifacts/*.pdf, Application.tailored_*_path=tailored
        ↓
[submit gate] ── full_auto? ──yes──▶ status=approved
              ── else ─────────────▶ status=pending_review  (STOP for this job)
        ↓
[submit]    ──uses──▶ SubmitterRegistry.pick(job)
            ── on NeedsFieldAnswer ─▶ UnknownField rows + status=needs_info (STOP)
            ── on success ─────────▶ status=submitted, confirmation
        ↓
[notify]    ──uses──▶ Notifier.email(user, application)
        ↓
[Run.finish] counts + errors
```

### UI Flow

```
Browser ── HTTP ──▶ FastAPI router ──▶ service (db/pipeline) ──▶ SQLite
                                         │
                                         └──▶ trigger_run()  ⇢  APScheduler.add_job(now)
HTMX poll /runs/{id}/events ◀── RunEvent rows (server-rendered partial)
```

### State Management

The Application status machine is the single source of truth; every UI action and every pipeline stage is a transition. No parallel in-memory state.

### Key Data Flows

1. **Discovery ingestion:** Scrapers normalize raw site data into `JobListing` dataclasses; dedupe stage converts accepted listings into `Job` + `Application(status=matched)` rows in one transaction.
2. **Tailoring artifact flow:** LLM output → Markdown → PDF via WeasyPrint → path stored on `Application`; originals kept for audit.
3. **Learning feedback:** `UnknownField` → user answers via UI → `FieldAnswer` merged into `Profile.answers_json` → next run's submitter reads enriched profile → same job retried (idempotent via `Application.id`).
4. **Review queue:** UI lists `Application.status in (pending_review, needs_info)`; approval calls `orchestrator.resume_application(app_id)` which jumps straight to the submit stage.
5. **Run observability:** Every stage emits `RunEvent`; UI streams via HTMX polling or SSE for a live run view.

## Scheduler ↔ Worker ↔ Web UI Relationship

All three live in one FastAPI process on startup:

- `main.py` creates the app, initializes SQLAlchemy engine, loads secrets, starts `AsyncIOScheduler`, registers the hourly job, and mounts web routers.
- The pipeline runs in the same event loop (async-first) so Playwright, HTTP scrapers, and LLM calls all cooperate without a separate worker broker. Single-user workload does not justify Celery/RQ.
- The web UI can force a run by calling `scheduler.add_job(run_pipeline, "date", run_date=now)` — the same code path as the hourly trigger.
- Long CPU work (PDF render) is pushed to `asyncio.to_thread` or a small `ProcessPoolExecutor` to avoid blocking the loop.
- Optional split: if Playwright stability demands isolation, move submitters behind a local subprocess using `multiprocessing` — the `Submitter` protocol makes this a drop-in change later.

## Pluggable Interfaces (Summary)

| Axis | Protocol | Swap without touching |
|------|----------|-----------------------|
| Scraper source | `Scraper.search(query) -> list[JobListing]` | Orchestrator, matcher, UI |
| LLM backend | `LLMBackend.complete(prompt, schema) -> Model` | Tailor stage, prompt templates |
| Submission strategy | `Submitter.submit(job, tailored, profile) -> SubmissionResult` | Pipeline gate, review queue |
| Notifier | `Notifier.send(event, payload)` | Rest of pipeline |
| Secret store | `SecretStore.get(name)/put(name, value)` | All callers |

## Suggested Build Order

This ordering keeps each step demoable end-to-end.

1. **Skeleton + persistence** — FastAPI app, SQLAlchemy models, Alembic, Docker, secrets vault, single-user auth. Bootable container with empty UI.
2. **Profile + settings UI** — CRUD for profile, resume base, keywords, sources, toggle for full-auto. No pipeline yet.
3. **Scraper protocol + one real scraper** — pick Greenhouse (JSON API, easiest) to validate the shape. Add `Job` table + dedupe.
4. **Matcher + Applications table** — deterministic scoring against profile. UI lists matched jobs.
5. **Pipeline orchestrator + APScheduler** — wire discover→dedupe→match on an hourly tick, with Run/RunEvent observability. Review queue UI appears here.
6. **LLM Gateway + Tailor stage** — Claude backend first (easier to get reliable JSON), then Ollama backend behind the same interface. Generate PDF artifacts.
7. **Submitter protocol + Playwright generic form submitter** — against Greenhouse/Lever test job pages. Introduce the `pending_review → approved → submitted` gate and full-auto toggle.
8. **Learning loop** — `UnknownField` capture during submit, UI to answer, write-back to profile, retry on next run.
9. **Remaining scrapers** — Lever, Indeed, LinkedIn, generic web. Each is additive under the registry.
10. **LinkedIn Easy Apply submitter** and **email-the-recruiter submitter** — added under the existing registry with no pipeline changes.
11. **Notifier (email)** — per-job emails on submit / review / failure.
12. **Hardening** — rate limits, proxy support, Playwright persistent profile, backup of SQLite volume, run-history UI.

Steps 1–5 deliver a working "find and queue jobs" system. Step 6 adds tailoring. Step 7 closes the loop to actual submission. Everything after is additive because the protocols are set.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 user, ~50 jobs/hour | Monolith FastAPI + SQLite is ideal; nothing more is needed. |
| 1 user, ~500 jobs/hour | Add per-scraper concurrency limits, move PDF render to process pool, batch LLM calls, consider WAL mode for SQLite (already default good with `PRAGMA journal_mode=WAL`). |
| Multi-user (hypothetical) | Swap SQLite → Postgres, move scheduler to its own container, promote submitters to Celery/Arq workers, artifact FS → object storage. Protocols stay identical. |

### Scaling Priorities

1. **First bottleneck:** LLM latency and cost during tailoring. Mitigate with caching by `(resume_base_hash, job_description_hash)` and preferring Ollama for first-pass, Claude only for top-scored jobs.
2. **Second bottleneck:** Playwright memory and flakiness. Mitigate with a shared persistent browser context, strict per-submit timeouts, subprocess isolation if needed.
3. **Third bottleneck:** Scraper rate-limits / bans. Mitigate with per-source token buckets, randomized delays, and a pluggable proxy field on the scraper base class.

## Anti-Patterns

### Anti-Pattern 1: LLM in the Hot Path of Matching

**What people do:** Call the LLM to score every discovered job.
**Why it's wrong:** Cost explodes, latency kills the hourly cadence, and the LLM is a worse classifier than a 20-line keyword ranker for top-of-funnel filtering.
**Do this instead:** Deterministic match stage for filtering, LLM only for tailoring accepted jobs.

### Anti-Pattern 2: One Submitter Class Per Company

**What people do:** `GoogleSubmitter`, `MetaSubmitter`, `StripeSubmitter`, …
**Why it's wrong:** 10,000 dead classes. Companies share ATS vendors.
**Do this instead:** Submitters are keyed by channel (ATS type / Easy Apply / email), and per-company quirks live in small config, not code.

### Anti-Pattern 3: Hidden Full-Auto Branching

**What people do:** Sprinkle `if settings.full_auto:` checks across stages.
**Why it's wrong:** Impossible to audit and test; user cannot trust the kill switch.
**Do this instead:** Express full-auto as a single transition rule on the `Application` status machine. Every stage is unaware of the mode.

### Anti-Pattern 4: Storing Secrets in Environment Variables Only

**What people do:** Put Claude API key, LinkedIn password, SMTP password in `.env` and call it done.
**Why it's wrong:** Laptop snapshots, backups, and screen-shares leak `.env`. Rotation requires container restart.
**Do this instead:** A Fernet-encrypted `secrets` table; the Fernet key is the only thing in env. The UI rotates values without a restart.

### Anti-Pattern 5: Blocking the Event Loop with Playwright/PDF

**What people do:** Call sync Playwright APIs or WeasyPrint directly in an async handler.
**Why it's wrong:** Freezes the web UI during submit/tailor.
**Do this instead:** Use async Playwright (`playwright.async_api`), and push PDF rendering through `asyncio.to_thread`.

### Anti-Pattern 6: Treating the Web UI as the Source of Truth

**What people do:** Keep some toggles/state only in UI session or in-memory globals.
**Why it's wrong:** Loses state on container restart; pipeline can't see it.
**Do this instead:** All settings and state in SQLite; UI is a view over the database.

### Anti-Pattern 7: Re-Scraping Everything Every Run

**What people do:** No dedupe; every hour re-discovers and re-processes the same listings.
**Why it's wrong:** Wastes LLM budget, risks double-submission, spams notifier.
**Do this instead:** Dedupe on `(source, source_id)` plus fuzzy simhash, and idempotency at the `Application` level.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Claude API | `anthropic` SDK via `ClaudeBackend` behind `LLMGateway` | Respect token budgets; schema-validate outputs |
| Ollama | Local HTTP on `http://host.docker.internal:11434` | Needs host networking or explicit extra_hosts in compose |
| LinkedIn | Playwright persistent context with logged-in profile; Easy Apply submitter | Expect frequent DOM changes; isolate selectors in one module |
| Indeed | Playwright + rotating UA; optional proxy | Aggressive anti-bot; throttle hard |
| Greenhouse / Lever | Public JSON endpoints per company board | Cheapest source; start here |
| SMTP | `aiosmtplib` with STARTTLS; creds from secrets vault | Gmail needs app password |
| Docker | single-service compose, mounted volumes for `data/` and `artifacts/` | Playwright base image or install chromium on first run |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Web layer ↔ pipeline | Direct async function call (trigger_run) | Never HTTP; same process |
| Pipeline ↔ scraper registry | Protocol call, fan-out with `asyncio.gather` + per-source semaphore | Each scraper isolated; one failure does not abort the run |
| Pipeline ↔ LLM gateway | Protocol call; retries + schema repair owned by gateway | Cache layer sits here too |
| Pipeline ↔ submitter registry | Protocol call; selection is pure | `NeedsFieldAnswer` exception is part of the contract |
| Submitter ↔ profile | Read-only on submit, write via `LearningService` only | Prevents hidden profile mutation |
| Notifier ↔ pipeline | Fire-and-forget async task with retry | Never blocks pipeline progression |

## Sources

- FastAPI official docs: lifespan events, dependency injection, background tasks — HIGH confidence
- APScheduler docs (AsyncIOScheduler + FastAPI integration patterns) — HIGH confidence
- Playwright for Python — async API and persistent context docs — HIGH confidence
- Anthropic Python SDK docs (structured output, message schema) — HIGH confidence
- Ollama REST API docs — HIGH confidence
- SQLAlchemy 2.x + Alembic docs — HIGH confidence
- Standard plugin-registry and pipeline-stage patterns from the Python data-engineering ecosystem (Airflow stages, Prefect tasks) — generalized, MEDIUM confidence as mapping to this specific domain
- Community write-ups of job-application bots (submitter selection, unknown-field learning) — MEDIUM confidence; validated against the component model above

---
*Architecture research for: autonomous job-application automation (single-user, Dockerized Python/FastAPI)*
*Researched: 2026-04-11*
