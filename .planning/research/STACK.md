# Stack Research

**Domain:** Dockerized single-user autonomous job-application bot (Python + FastAPI + Playwright + LLM)
**Researched:** 2026-04-11
**Confidence:** HIGH for web/LLM/scraping infra, MEDIUM-LOW for LinkedIn-specific automation (ToS risk, cat-and-mouse), HIGH for DOCX/scheduling/persistence/crypto.

---

## Executive Recommendation

Build on **Python 3.13 + FastAPI 0.135 + HTMX + SQLModel/SQLite + APScheduler + Playwright 1.58 (with playwright-stealth 2.0) + python-jobspy for aggregation + official Greenhouse/Lever JSON endpoints for ATS + Anthropic SDK 0.94 + ollama-python dual-provider for LLM + python-docx 1.2 for resume manipulation + Fernet for credential encryption + aiosmtplib for email**, packaged in a `python:3.13-slim-trixie` Docker image that also bundles the Playwright-official `mcr.microsoft.com/playwright/python:v1.58.0-noble` browser layer.

The single most important prescriptive decision: **do NOT write a custom LinkedIn scraper**. Use `python-jobspy` for search/discovery and restrict automated *submission* to (a) ATS direct endpoints (Greenhouse/Lever/Ashby) and (b) user-supervised Easy Apply with human-in-the-loop confirmation. LinkedIn's 2025–2026 enforcement is aggressive (Tier-2 / Tier-3 bans with <15% recovery), so the architecture must treat LinkedIn submission as opt-in, throttled, and reversible.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **Python** | 3.13.x | Runtime | Current stable with free-threaded GIL experiments; every library in this stack supports it; 3.12 is fine fallback. Avoid 3.14 until Playwright + lxml wheels stabilize. |
| **FastAPI** | 0.135.3 | Web framework / JSON+HTML API | User-mandated. Current release (Apr 1 2026). Ships streaming JSONL + strict content-type by default; requires Python 3.10+. Pairs natively with HTMX via `HTMLResponse`. |
| **Uvicorn** | 0.36.x | ASGI server | Standard dev + prod runner for FastAPI. For a single-user local container, run uvicorn directly (`--workers 1`) — gunicorn is overkill and complicates APScheduler state. |
| **Pydantic** | 2.12.x | Data validation | Pydantic-core (Rust) gives 5–50x model speedup; required by FastAPI 0.135. Use `pydantic-settings` 2.13.1 for `.env` config. |
| **SQLModel** | 0.0.24+ | ORM / schemas | Built by FastAPI author; one class is both DB row and API schema, removes boilerplate. Backed by SQLAlchemy 2.0 so you can drop to raw SQL for complex reporting. |
| **SQLAlchemy** | 2.0.x | DB engine | Transitive under SQLModel; use async engine (`aiosqlite`) so it plays nicely with FastAPI handlers. |
| **SQLite** | 3.45+ (bundled) | Persistence | Single-file, zero-admin, fits "runs on user's laptop" constraint perfectly. Store at `/data/app.db` mounted volume so container restarts don't wipe history. |
| **aiosqlite** | 0.20.x | Async SQLite driver | Required for SQLAlchemy 2.0 async + SQLite. |
| **Alembic** | 1.14.x | Migrations | Even single-user apps need schema migrations; SQLModel integrates cleanly. |

### Scraping & Browser Automation

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **python-jobspy** | 1.1.82+ | LinkedIn/Indeed/Glassdoor/ZipRecruiter/Google job *discovery* | Only maintained open-source aggregator covering all four required boards with one API. Returns normalized schema (title, company, salary, job_url, job_type, remote). Avoid writing per-site parsers. |
| **Playwright (Python)** | 1.58.0 | Browser automation for Easy Apply, custom ATS, form-fill | Microsoft-maintained, auto-waiting, context isolation, stable selectors. Better stealth surface than Selenium. Ship as `mcr.microsoft.com/playwright/python:v1.58.0-noble` base. |
| **playwright-stealth** | 2.0.3 | Fingerprint patching | Released Apr 4 2026, modern context-manager API. Defeats *basic* bot checks only — does NOT defeat Cloudflare/DataDome. Acceptable because LinkedIn/Indeed apply flows are not behind DataDome, but plan on rotating behavior. |
| **httpx** | 0.28.x | Async HTTP client | Powers Anthropic + OpenAI SDKs already; HTTP/2, sync+async, same API. Use for Greenhouse/Lever JSON ATS endpoints — no browser needed. |
| **selectolax** | 0.3.x | Fast HTML parsing | ~25x faster than BeautifulSoup, Cython-based. Use inside httpx flows for ATS page parsing. |
| **tenacity** | 9.0.x | Retry / backoff | Decorator-based retry for scraper flakiness; exponential jitter built-in. |

**ATS-specific endpoints (no library needed, just httpx + JSON):**
- **Greenhouse:** `https://boards-api.greenhouse.io/v1/boards/{company}/jobs` — official public Job Board API, no auth, returns JSON. This is the prescribed path.
- **Lever:** `https://api.lever.co/v0/postings/{company}?mode=json` — official public JSON feed, no auth.
- **Ashby:** `https://api.ashbyhq.com/posting-api/job-board/{company}` — official public.
- **Workday / iCIMS:** custom per-tenant URLs, require Playwright; treat as best-effort.

### LLM Integration

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **anthropic** (Python SDK) | 0.94.0 | Claude API client | Released Apr 10 2026. Async + sync clients via httpx, streaming, tool use, prompt caching. Use `claude-sonnet-4-5` for tailoring; cache the base resume across requests. |
| **ollama** (Python client) | 0.4.x | Local LLM client | Official ollama-python library, installs via pip, talks to local Ollama daemon over HTTP (`host.docker.internal:11434` from inside the container). |
| **instructor** | 1.7.x | Structured outputs | Wraps anthropic + ollama with Pydantic schema validation. Use it to force the LLM to return a typed `ResumeEdits` object instead of free-form markdown. Massively reduces "LLM returned garbage" bugs. |
| **tiktoken** | 0.8.x | Token accounting | Approximate token counting for cost/context budgeting. Anthropic SDK provides `count_tokens` but tiktoken is handy for pre-flight checks. |

**Provider abstraction pattern:** Define a single `LLMProvider` Protocol with `async def tailor(resume_text: str, job_desc: str) -> ResumeEdits`. Ship two implementations: `AnthropicProvider` and `OllamaProvider`. Config flag `LLM_PROVIDER=anthropic|ollama` selects at startup. Do NOT use LangChain — adds 40+ transitive deps, churns APIs, and the abstractions leak.

### DOCX Handling

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **python-docx** | 1.2.0 | Parse + edit + write DOCX | Only actively maintained pure-Python library for .docx. Supports runs, styles, tables, headers — enough to rewrite bullets without destroying formatting. Depends on lxml (already transitive). |
| **lxml** | 5.3.x | XML backend | Transitive under python-docx; explicitly pin so Alpine/musl images don't fall back to slow pure-Python ElementTree. |
| **docx2txt** | 0.8+ | Cheap text extraction | When you only need plain text (feeding the LLM), docx2txt is 10x faster than python-docx's full tree walk. Use it for LLM input; use python-docx for writing the tailored output. |

**Anti-recommendation:** Do NOT use `docx` (the PyPI package called `docx` without the `python-` prefix) — it's an abandoned fork and will silently corrupt files.

### Scheduling

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **APScheduler** | 3.10.x (or 4.0b if you want async-native) | Hourly cron inside the FastAPI process | No broker, no Redis, no Celery — runs inside the same Python process as FastAPI. Perfect for single-user single-container. Use `AsyncIOScheduler` + `CronTrigger(minute=0)` for hourly runs. Persist jobs to SQLite via `SQLAlchemyJobStore` so restarts survive. |

**Why not Celery/arq/Temporal:** They all require a broker (Redis/RabbitMQ), doubling container count and RAM footprint. The user's constraint is "runs entirely on laptop" — extra services violate that. APScheduler in-process is the correct answer. If you ever need distribution, swap to arq.

### Credentials & Encryption

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **cryptography** | 44.x | Fernet symmetric encryption for LinkedIn/Indeed/SMTP creds stored in SQLite | Fernet gives AEAD (AES-128-CBC + HMAC-SHA256), key rotation via `MultiFernet`, and is the standard answer for "encrypt a blob at rest in Python." Key lives in `/run/secrets/master.key` (Docker secret) or env var `APP_MASTER_KEY`. |
| **argon2-cffi** | 23.x | Hash the *UI* login password | Argon2id is OWASP's current recommendation; even a single-user app needs this so the SQLite file isn't walk-up-readable. |
| **pydantic-settings** | 2.13.1 | Env var loading | Already listed; mention here because all secrets flow through it — never hardcode. |

**Anti-recommendation:** Do NOT use `keyring` inside Docker. The OS-keyring backends (Secret Service, macOS Keychain, Windows Credential Manager) don't exist inside a Linux container — keyring will silently fall back to plaintext `PlaintextKeyring`. Use Fernet with an externally-injected master key instead.

### Email

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **aiosmtplib** | 5.1.x | Async SMTP for per-application summaries | Non-blocking, integrates with FastAPI event loop, TLS/SSL support. Python 3.10+. Works with Gmail app passwords, Fastmail, SES-SMTP, etc. |
| **jinja2** | 3.1.x | HTML email templates | Transitive through FastAPI's Jinja2Templates anyway; use the same engine for email bodies as for HTMX fragments. |
| **premailer** | 3.10.x | Inline CSS for email clients | Gmail strips `<style>` blocks; premailer bakes CSS into inline attrs. |

**Anti-recommendation:** Do NOT use `yagmail` — Gmail-only, unmaintained since 2022, synchronous, wraps smtplib in a way that breaks under asyncio.

### Web UI

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **HTMX** | 2.0.4 | Interactivity without a JS build step | For a single-user local-only app, HTMX + Jinja2 is 100x less complexity than React+Vite. 14KB, no build, hypermedia-native, server is source of truth. FastAPI returns HTML fragments from handlers — no separate frontend repo, no CORS. |
| **Jinja2** | 3.1.x | Server-side templating | Idiomatic pairing with FastAPI + HTMX. |
| **Tailwind CSS** (via CDN Play) | 3.4.x | Styling | Use the Play CDN (`<script src="https://cdn.tailwindcss.com">`) to avoid a Node toolchain. For a personal tool, CDN is acceptable. |
| **Alpine.js** | 3.14.x | Tiny client-side state (modals, dropdowns) | 15KB, no build, complements HTMX perfectly. Use only where HTMX alone is awkward. |

**Anti-recommendation:** Do NOT introduce React/Next.js/Vue. It would double the container size, require a Node build step, split the repo in two, and deliver zero value for a single-user local dashboard.

### Docker

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **Base image** | `mcr.microsoft.com/playwright/python:v1.58.0-noble` | Python 3.12 + Playwright + all Chromium/Firefox/WebKit dependencies pre-installed | Using the official Playwright image avoids the "which libnss3 does Ubuntu need now" pain. ~1.2 GB but that's the cost of bundling a browser. Ubuntu Noble (24.04 LTS) base. |
| **Alternative base** | `python:3.13-slim-trixie` | Slim Debian 13 if you use Ollama-only (no Playwright flows) | 41 MB; use for a "headless" variant that only hits ATS JSON endpoints. Not the primary recommendation because most users will want browser submission. |
| **docker-compose** | v2 (compose spec) | Orchestration | Single `docker-compose.yml` with one service (the app) + named volume for SQLite + bind mount for user's resume DOCX. If the user wants Ollama, add a second service or require host Ollama via `host.docker.internal`. |
| **tini** | 0.19 | PID 1 init | Reaps zombies from Playwright's chromium child processes. Passed via `--init` flag or `init: true` in compose. |

**Prescriptive Dockerfile skeleton:**
```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
RUN useradd -m -u 1000 app
WORKDIR /app
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . .
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Development Tools

| Tool | Purpose | Notes |
|---|---|---|
| **uv** (0.5.x) | Package/venv manager | 10–100x faster than pip; emits `requirements.txt` compatible lockfile via `uv pip compile`. |
| **ruff** (0.8.x) | Linter + formatter | Replaces black + isort + flake8 + pyupgrade in one tool. `ruff check && ruff format`. |
| **mypy** (1.13.x) or **pyright** | Type checking | SQLModel + Pydantic 2 have excellent types; turn this on day one. |
| **pytest** (8.3.x) + **pytest-asyncio** + **httpx** TestClient | Test runner | FastAPI's `TestClient` is httpx-based. |
| **pytest-playwright** (0.6.x) | Browser test fixtures | For E2E tests of the Easy Apply flow against a mock page. |
| **pre-commit** (4.0.x) | Git hooks | Run ruff + mypy on commit. |
| **respx** (0.22.x) | httpx mocking | Mock Greenhouse/Lever/Anthropic calls in unit tests. |

---

## Installation

```bash
# Lock with uv (recommended)
uv pip compile pyproject.toml -o requirements.txt

# Or direct pip install into venv
pip install \
  "fastapi==0.135.3" \
  "uvicorn[standard]==0.36.*" \
  "pydantic==2.12.*" \
  "pydantic-settings==2.13.1" \
  "sqlmodel>=0.0.24" \
  "sqlalchemy[asyncio]==2.0.*" \
  "aiosqlite==0.20.*" \
  "alembic==1.14.*" \
  "httpx==0.28.*" \
  "selectolax==0.3.*" \
  "tenacity==9.0.*" \
  "playwright==1.58.0" \
  "playwright-stealth==2.0.3" \
  "python-jobspy>=1.1.82" \
  "python-docx==1.2.0" \
  "docx2txt==0.8" \
  "lxml==5.3.*" \
  "anthropic==0.94.0" \
  "ollama>=0.4.0" \
  "instructor==1.7.*" \
  "tiktoken==0.8.*" \
  "apscheduler==3.10.*" \
  "cryptography==44.*" \
  "argon2-cffi==23.*" \
  "aiosmtplib==5.1.*" \
  "jinja2==3.1.*" \
  "premailer==3.10.*"

# Dev
pip install -U \
  "ruff==0.8.*" \
  "mypy==1.13.*" \
  "pytest==8.3.*" \
  "pytest-asyncio==0.24.*" \
  "pytest-playwright==0.6.*" \
  "respx==0.22.*" \
  "pre-commit==4.0.*"

# Playwright browser binaries (only if NOT using the MS Playwright base image)
playwright install --with-deps chromium
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|---|---|---|
| FastAPI | Litestar, Starlette raw | Litestar has better DI and docs but smaller ecosystem; stick with FastAPI because the user mandated it. |
| SQLModel | SQLAlchemy 2.0 raw | If you need advanced relationships or query optimization beyond single-user scale. For this app, SQLModel wins on ergonomics. |
| SQLite | Postgres | Only if multi-user or > 50 GB of data. Otherwise SQLite is faster (no network hop) and simpler. |
| APScheduler | arq + Redis | If you later deploy multiple replicas. For single container, APScheduler is correct. |
| APScheduler | OS-level cron | Cron can't introspect app state, can't pause/resume via UI, can't share the SQLite session. In-process scheduling is the right call. |
| python-jobspy | Apify actors, Bright Data, Proxycurl | Paid managed scrapers ($10–$500/mo) handle proxies + anti-bot. Use them ONLY if python-jobspy gets rate-limited in practice. Start free, escalate if needed. |
| Playwright | Selenium 4 | Playwright is faster, has auto-waiting, better trace viewer, and its official Docker image bundles everything. Selenium only wins if you need IE/Safari ancient versions. |
| Playwright | Puppeteer (pyppeteer) | pyppeteer is unmaintained since 2023. Avoid. |
| Anthropic SDK + ollama | LangChain, LlamaIndex | LangChain's abstractions leak, churn, and add 40+ dependencies. A 50-line `LLMProvider` Protocol beats it for a two-provider setup. |
| Anthropic SDK | litellm | litellm is a reasonable alternative if you want to add OpenAI/Gemini later without code changes. Trade-off: extra abstraction layer. Fine to adopt if "add more providers" is on the roadmap. |
| python-docx | docxtpl | docxtpl (Jinja-in-Word) is great if you have a fixed template and just fill fields. For LLM-driven *rewriting* of bullets, python-docx's run-level API is more flexible. |
| HTMX | React/Next.js | Never for this app. Reconsider only if the UI grows to a multi-user SaaS. |
| HTMX | Streamlit, Gradio | Streamlit is tempting for an "AI tool" vibe, but it fights you on routing, auth, and background jobs. FastAPI+HTMX is the grown-up path. |
| aiosmtplib | SendGrid/Postmark/Resend API | Use a provider API if SMTP gets blocked by the user's ISP. aiosmtplib is free and works for personal use. |
| Fernet | HashiCorp Vault, AWS KMS | Overkill for a single-user laptop app. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|---|---|---|
| **linkedin-api** (tomquirk) | Reverse-engineers the Voyager private API; not blessed by LinkedIn; triggers Tier-2+ account restrictions quickly; repo explicitly warns of ban risk. | `python-jobspy` for discovery; user-supervised Playwright for Easy Apply. |
| **selenium + undetected-chromedriver** | Cat-and-mouse with Chrome releases; undetected-chromedriver is often 1–2 Chrome versions behind; slower than Playwright. | Playwright + playwright-stealth. |
| **pyppeteer** | Unmaintained since 2023. | Playwright. |
| **yagmail** | Gmail-only, sync, unmaintained since 2022. | aiosmtplib. |
| **keyring** *inside Docker* | OS keyring backends don't exist in containers; silently falls back to plaintext. | Fernet with externally-injected master key. |
| **python-crontab** | Edits host crontab — pointless inside a container. | APScheduler. |
| **BeautifulSoup** (for hot paths) | 25x slower than selectolax. Fine for prototypes. | selectolax for production scraping loops. |
| **LangChain** for a 2-provider LLM switcher | Overhead, churn, leaky abstractions, 40+ transitive deps. | `LLMProvider` Protocol + anthropic SDK + ollama client directly. |
| **requests** (sync) | Blocks the event loop, can't stream LLM responses properly. | httpx (it even has a drop-in sync API if you want it). |
| **`docx` package (no `python-` prefix)** | Abandoned fork; silently corrupts files. | `python-docx`. |
| **Alpine Linux base image** | musl libc breaks prebuilt wheels for lxml, cryptography, Playwright; compile-from-source is slow and often fails. | `python:3.13-slim-trixie` (Debian) or `mcr.microsoft.com/playwright/python`. |
| **Running as root in Docker** | Any Playwright RCE or LLM prompt injection that shells out now owns the container with root. | `USER app` (uid 1000) in Dockerfile. |
| **Celery + Redis** for hourly schedule | Requires a second service; violates "runs on laptop" constraint. | APScheduler in-process. |
| **Custom LinkedIn Easy Apply bot that runs unattended** | LinkedIn's 2026 behavioral biometrics flag scripted rhythm; Tier-3 permanent ban success rate < 15%. | Human-in-the-loop: bot opens tab, pre-fills form, user clicks Submit. Or skip LinkedIn and prioritize Greenhouse/Lever direct. |

---

## Stack Patterns by Variant

**If user wants 100% local / offline:**
- Use `ollama` provider with a small local model (llama3.1:8b or qwen2.5:14b).
- Skip Anthropic SDK (install but don't configure).
- Run Ollama on the host, connect from container via `host.docker.internal:11434`.
- Reason: user's constraint says "runs entirely on laptop" — Ollama satisfies that literally.

**If user wants best resume quality and has an Anthropic API key:**
- Use `anthropic` provider with `claude-sonnet-4-5` and prompt caching for the base resume.
- Cost: ~$0.003 per tailored application with caching.
- Reason: Sonnet 4.5 beats any locally-runnable model at following formatting instructions without hallucinating.

**If user is worried about LinkedIn bans:**
- Disable LinkedIn scraping; run with JobSpy in "indeed, glassdoor, google" mode only.
- Disable Easy Apply submission; only auto-apply to Greenhouse/Lever/Ashby direct.
- Reason: ATS direct endpoints have no ToS risk; LinkedIn's 2025 enforcement is the highest-risk vector.

**If user needs to scale past one laptop (out-of-scope but noted):**
- Swap SQLite → Postgres, APScheduler → arq + Redis, add Nginx in front.
- Otherwise the stack transfers cleanly.

---

## Version Compatibility Notes

| Package | Compatible With | Notes |
|---|---|---|
| `fastapi==0.135.3` | `pydantic==2.12.*`, `starlette==0.47.*` | FastAPI 0.135 requires Pydantic v2; do not mix v1. |
| `sqlmodel>=0.0.24` | `sqlalchemy==2.0.*`, `pydantic==2.12.*` | SQLModel 0.0.24 is the first release fully compatible with Pydantic 2.10+; older versions pin-conflict. |
| `playwright==1.58.0` | `playwright-stealth==2.0.3` | Stealth 2.0 dropped the old monkey-patch API; pin both together. |
| `anthropic==0.94.0` | `httpx>=0.27,<0.30` | Anthropic SDK requires recent httpx; compatible with FastAPI TestClient's httpx. |
| `python-docx==1.2.0` | `lxml>=4.9,<6.0` | Explicit lxml pin avoids fallback to slow ElementTree. |
| `apscheduler==3.10.*` | `sqlalchemy==2.0.*` via `SQLAlchemyJobStore` | APScheduler 3.10 supports SQLA 2.0; APScheduler 4.0 beta is async-native and worth watching but still beta as of Apr 2026. |
| `cryptography==44.*` | OpenSSL 3.x | slim-trixie ships OpenSSL 3.2; all good. |
| `ollama>=0.4.0` | Ollama daemon >= 0.5 | Client library pins a minimum server version — run `ollama -v` on host to verify. |

---

## Legal / ToS Risk Flags (critical — feed into PITFALLS.md)

1. **LinkedIn ToS Section 8.2** explicitly prohibits automated access, including Easy Apply bots. Penalties escalate: feature restriction → account lock → permanent ban with < 15% recovery rate. The architecture MUST make LinkedIn automation opt-in, human-confirmed, and throttled (< 20 actions/day, randomized delays).
2. **Indeed ToS** similarly prohibits automated scraping; `python-jobspy`'s Indeed backend uses their public search endpoint which has been tolerated historically but can rate-limit.
3. **Greenhouse / Lever / Ashby** publish official public JSON endpoints — **no ToS risk**, no authentication needed, designed for aggregation. Prioritize these.
4. **hiQ v. LinkedIn (9th Cir. 2022)** affirmed scraping *public* data is not CFAA violation, but this does NOT protect against account suspension for automated *authenticated* actions. Submission flows are authenticated → higher risk.
5. **Copyright on job descriptions**: storing and re-displaying full JD text is arguably fair use for personal analysis; re-publishing is not. Keep the app single-user.

---

## Sources

### HIGH confidence (Context7 / official docs)
- FastAPI release notes — https://fastapi.tiangolo.com/release-notes/ (verified 0.135.3, Apr 1 2026)
- FastAPI PyPI — https://pypi.org/project/fastapi/
- Playwright PyPI — https://pypi.org/project/playwright/ (1.58.0)
- playwright-stealth PyPI — https://pypi.org/project/playwright-stealth/ (2.0.3, Apr 4 2026)
- Anthropic SDK releases — https://github.com/anthropics/anthropic-sdk-python/releases (0.94.0, Apr 10 2026)
- ollama-python — https://github.com/ollama/ollama-python
- python-docx docs — https://python-docx.readthedocs.io/ (1.2.0)
- python-jobspy — https://github.com/speedyapply/JobSpy (1.1.82+)
- SQLModel — https://sqlmodel.tiangolo.com/
- cryptography Fernet — https://cryptography.io/en/latest/fernet/
- aiosmtplib — https://aiosmtplib.readthedocs.io/ (5.1.0)
- APScheduler — https://apscheduler.readthedocs.io/
- Pydantic 2.12 release — https://pydantic.dev/articles/pydantic-v2-12-release
- Greenhouse Job Board API — https://developers.greenhouse.io/job-board.html
- Docker Playwright image — https://hub.docker.com/r/microsoft/playwright-python

### MEDIUM confidence (WebSearch verified with multiple sources)
- "The best Docker base image for Python" — https://pythonspeed.com/articles/base-image-python-docker-images/ (Feb 2026)
- HTMX vs React performance 2026 — https://plus8soft.com/blog/htmx-vs-react-comparison/
- FastAPI + HTMX — https://testdriven.io/blog/fastapi-htmx/
- HTTPX vs requests vs aiohttp 2026 — https://decodo.com/blog/httpx-vs-requests-vs-aiohttp
- Scrapfly — https://scrapfly.io/blog/posts/how-to-scrape-linkedin (2026 anti-bot landscape)

### LOW confidence (single source / needs later validation)
- LinkedIn ban tier statistics ("<15% Tier-3 recovery") — cited by growleads.io and dux-soup.com, no official LinkedIn source. Treat as directionally correct, exact numbers unverified.
- JobSpy weekly downloads (2,490) — from Snyk snapshot, could be stale.
- APScheduler 4.0 beta async status — needs verification before relying on it; recommend sticking with 3.10 stable.

---

*Stack research for: Dockerized single-user job application auto-applier*
*Researched: 2026-04-11*
