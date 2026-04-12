# Phase 3: Safe-Channel Discovery, Dedup & Matching - Research

**Researched:** 2026-04-12
**Domain:** ATS public API integration, job deduplication, keyword scoring, HTMX UI
**Confidence:** HIGH

## Summary

Phase 3 adds job discovery from three ATS public APIs (Greenhouse, Lever, Ashby), normalizes them to a common schema, deduplicates by fingerprint, scores against user keywords, and displays results in a sortable table with inline expansion. The technical domain is straightforward: all three ATS providers offer unauthenticated JSON GET endpoints, `httpx` is already in requirements, and the existing patterns (SQLModel tables, HTMX partials, settings sidebar, APScheduler pipeline) map cleanly to the new features.

The main complexity areas are: (1) source auto-detection from user-pasted URLs/slugs, (2) dedup fingerprint canonicalization, (3) keyword scoring with partial matching, and (4) anomaly detection against a rolling average. None require external libraries beyond what is already installed.

**Primary recommendation:** Use httpx.AsyncClient with per-source fetcher functions that return a list of normalized `Job` dicts, compose them in the scheduler pipeline, and persist via SQLAlchemy. The UI follows the existing HTMX partial pattern with a new "Sources" settings section and a new "Jobs" page.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- User adds companies by pasting a careers page URL or slug (e.g., `stripe` or `https://boards.greenhouse.io/stripe`). App auto-detects the source (Greenhouse/Lever/Ashby)
- Company list lives in a new "Sources" section in the existing settings sidebar
- Validate on add -- hit the API immediately when user submits the slug. Show inline error if it doesn't resolve. Don't save invalid entries
- Each company has an enable/disable toggle. Disabled companies are skipped during discovery but kept in the list for easy re-enabling
- Table/list view with sortable columns: title, company, source, score, posted date, status
- Show ALL discovered jobs by default with score column -- not filtered to matched-only
- Match score displayed as color-coded badge (green = high match, yellow = borderline, gray = low)
- Clicking a job row expands inline to show full description, matched keywords highlighted, and original posting URL. No page navigation
- Keyword matching is case-insensitive and partial -- "python" matches "Python", "python3", "Python/Django"
- Expanded job view shows keyword breakdown: matched keywords highlighted green, unmatched keywords grayed out
- Below-threshold jobs are visible and scored but NOT auto-queued for tailoring
- User can manually queue a below-threshold job from the expanded view ("Queue for apply" button)
- Per-source discovery counts (discovered/matched) shown in both dashboard summary and run detail view
- Anomaly alerts (today < 20% of 7-day rolling average) surface as yellow warning banner on dashboard
- Anomaly banners are dismissable -- won't reappear until a new anomaly is detected on a subsequent run
- Failed source fetches (404, timeout) are a SEPARATE error state from anomalies -- red "Error" badge on the source in the sources list, distinct error banner

### Claude's Discretion
- Exact table column widths and responsive behavior
- Inline expansion animation/transition
- Dedup fingerprint normalization details (URL canonicalization, title cleaning)
- API polling strategy (parallel vs sequential source fetching)
- Dashboard summary card layout for source counts

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | HTTP client for ATS API calls | Already in requirements, async-native, timeout support |
| SQLModel | 0.0.24+ | New Job and Source tables | Existing ORM pattern |
| SQLAlchemy async | 2.0.36 | Query layer | Existing pattern |
| Alembic | 1.14.0 | Schema migration for new tables | Existing pattern |
| APScheduler | 3.11.0 | Hourly discovery trigger | Existing pipeline stub |
| Jinja2 | 3.1.4 | Templates for jobs page + sources section | Existing pattern |
| HTMX | 2.0.3 | Inline expand, sorting, partial swap | Existing pattern |
| Pico.css | v2 | Styling for tables, badges, banners | Existing pattern |
| structlog | 24.4.0 | Logging discovery/matching events | Existing pattern |

### No New Dependencies Needed

All three ATS APIs return JSON over HTTP. `httpx.AsyncClient` handles this perfectly. No SDK or wrapper library is needed. The scoring algorithm is simple keyword overlap -- no NLP library required.

## Architecture Patterns

### Recommended Project Structure (new files)
```
app/
  discovery/
    __init__.py
    models.py          # Source, Job SQLModel tables
    service.py         # CRUD for sources, jobs, dedup, anomaly detection
    fetchers.py        # greenhouse_fetch, lever_fetch, ashby_fetch
    scoring.py         # keyword_score(), highlight_keywords()
    pipeline.py        # run_discovery(ctx) -- orchestrates fetch+normalize+dedup+score+persist
  web/
    routers/
      sources.py       # Settings sources section CRUD
      jobs.py          # Jobs page, inline expand, manual queue
    templates/
      jobs.html.j2
      partials/
        settings_sources.html.j2
        jobs_table.html.j2
        job_detail_inline.html.j2
        dashboard_discovery_summary.html.j2
        anomaly_banner.html.j2
  db/
    migrations/
      versions/
        0003_phase3_discovery.py
```

### Pattern 1: ATS Fetcher Functions
**What:** Each ATS source gets a dedicated async function that returns a list of normalized dicts. A single `fetch_source()` dispatcher calls the right one based on `source.source_type`.
**When to use:** Always -- keeps API-specific parsing isolated from the pipeline.

```python
import httpx
from typing import Optional

async def fetch_greenhouse(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Fetch all jobs from Greenhouse public API. Returns normalized dicts."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    resp = await client.get(url, params={"content": "true"})
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "external_id": str(j["id"]),
            "title": j["title"],
            "company": slug,
            "location": j.get("location", {}).get("name", ""),
            "description": j.get("content", ""),
            "url": j["absolute_url"],
            "source": "greenhouse",
            "posted_date": j.get("updated_at"),
        })
    return jobs


async def fetch_lever(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Fetch all jobs from Lever public API. Returns normalized dicts."""
    url = f"https://api.lever.co/v0/postings/{slug}"
    resp = await client.get(url, params={"mode": "json"})
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for j in data:
        # Lever returns a flat list, not wrapped in {"jobs": [...]}
        jobs.append({
            "external_id": j["id"],
            "title": j["text"],
            "company": slug,
            "location": j.get("categories", {}).get("location", ""),
            "description": j.get("descriptionPlain", j.get("description", "")),
            "url": j["hostedUrl"],
            "source": "lever",
            "posted_date": None,  # Lever does not expose posted date in public API
        })
    return jobs


async def fetch_ashby(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Fetch all jobs from Ashby public API. Returns normalized dicts."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "external_id": j.get("id", ""),
            "title": j["title"],
            "company": slug,
            "location": j.get("location", ""),
            "description": j.get("descriptionPlain", j.get("descriptionHtml", "")),
            "url": j.get("jobUrl", ""),
            "source": "ashby",
            "posted_date": j.get("publishedAt"),
        })
    return jobs
```

### Pattern 2: Source Auto-Detection from URL/Slug
**What:** Parse the user input to determine ATS type and extract the slug.
**When to use:** On source add in the settings UI.

```python
import re
from urllib.parse import urlparse

def detect_source(input_str: str) -> tuple[str, str]:
    """Return (source_type, slug) from user input.

    Supports:
      - Plain slug: "stripe" -> tries all three, first success wins
      - Greenhouse URL: boards.greenhouse.io/stripe or boards-api.greenhouse.io/v1/boards/stripe
      - Lever URL: jobs.lever.co/stripe or api.lever.co/v0/postings/stripe
      - Ashby URL: jobs.ashbyhq.com/stripe
    
    Raises ValueError if pattern not recognized.
    """
    input_str = input_str.strip().rstrip("/")
    
    # URL patterns
    if "greenhouse.io" in input_str:
        parsed = urlparse(input_str)
        # Extract slug from path: /stripe or /v1/boards/stripe/jobs
        parts = [p for p in parsed.path.split("/") if p and p not in ("v1", "boards", "jobs")]
        if parts:
            return ("greenhouse", parts[0])
    
    if "lever.co" in input_str:
        parsed = urlparse(input_str)
        parts = [p for p in parsed.path.split("/") if p and p not in ("v0", "postings")]
        if parts:
            return ("lever", parts[0])
    
    if "ashbyhq.com" in input_str:
        parsed = urlparse(input_str)
        parts = [p for p in parsed.path.split("/") if p and p not in ("posting-api", "job-board")]
        if parts:
            return ("ashby", parts[0])
    
    # Plain slug -- no URL pattern matched
    if re.match(r"^[a-zA-Z0-9_-]+$", input_str):
        return ("unknown", input_str)  # caller must probe all three
    
    raise ValueError(f"Cannot parse source from: {input_str}")
```

### Pattern 3: Dedup Fingerprint
**What:** Canonical fingerprint = SHA256 of normalized (url + title + company). Used as a UNIQUE index to prevent duplicates across runs and sources.
**When to use:** Before inserting any job into the DB.

```python
import hashlib

def job_fingerprint(url: str, title: str, company: str) -> str:
    """Canonical fingerprint for dedup.

    Normalization:
      - URL: lowercase, strip trailing slash, strip query params and fragments
      - Title: lowercase, strip whitespace, collapse internal whitespace
      - Company: lowercase, strip whitespace
    """
    # URL: strip query/fragment, lowercase, strip trailing slash
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url.lower().strip())
    clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
    
    clean_title = " ".join(title.lower().split())
    clean_company = company.lower().strip()
    
    raw = f"{clean_url}|{clean_title}|{clean_company}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

### Pattern 4: Keyword Scoring
**What:** Case-insensitive partial match of user keywords against job description text. Score = (matched_keywords / total_keywords) * 100.
**When to use:** After normalization, before persisting.

```python
import re

def score_job(description: str, keywords: list[str]) -> tuple[int, list[str], list[str]]:
    """Score a job description against user keywords.
    
    Returns (score_0_to_100, matched_keywords, unmatched_keywords).
    Partial matching: "python" matches "python3", "Python/Django".
    """
    if not keywords:
        return (0, [], [])
    
    desc_lower = description.lower()
    matched = []
    unmatched = []
    
    for kw in keywords:
        # Case-insensitive substring search (partial match)
        if kw.lower() in desc_lower:
            matched.append(kw)
        else:
            unmatched.append(kw)
    
    score = round(len(matched) / len(keywords) * 100)
    return (score, matched, unmatched)
```

### Pattern 5: Anomaly Detection
**What:** Compare today's per-source discovery count against the 7-day rolling average. If today < 20% of average, flag as anomaly.
**When to use:** After each discovery run completes.

```python
async def check_anomaly(session, source_id: int, today_count: int) -> bool:
    """Return True if today's count is anomalously low (< 20% of 7-day avg)."""
    # Query last 7 days of discovery counts for this source
    # from a discovery_runs or source_run_stats table
    # avg = sum(counts) / len(counts)
    # return today_count < avg * 0.20
    pass
```

### Pattern 6: Pipeline Integration
**What:** Replace the `_execute_stub` with a real discovery pipeline stage.
**When to use:** The `SchedulerService.run_pipeline` already wraps execution with safety envelope. Phase 3 replaces the stub body.

```python
async def run_discovery(ctx: RunContext, session_factory) -> dict:
    """Execute discovery pipeline stage.
    
    Returns counts dict: {"discovered": N, "matched": M, "new": K, "errors": [...]}
    """
    async with session_factory() as session:
        sources = await get_enabled_sources(session)
        settings = await get_settings_row(session)
        keywords = [k for k in (settings.keywords_csv or "").split("|") if k]
        
    all_jobs = []
    errors = []
    source_counts = {}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch from all enabled sources (parallel with asyncio.gather)
        for source in sources:
            try:
                jobs = await fetch_source(client, source)
                source_counts[source.slug] = {"discovered": len(jobs)}
                all_jobs.extend(jobs)
            except Exception as e:
                errors.append({"source": source.slug, "error": str(e)})
                # Mark source as errored in DB
    
    # Dedup + score + persist
    new_count = 0
    matched_count = 0
    async with session_factory() as session:
        for job_data in all_jobs:
            fp = job_fingerprint(job_data["url"], job_data["title"], job_data["company"])
            existing = await get_job_by_fingerprint(session, fp)
            if existing:
                continue  # skip duplicate
            
            score, matched_kw, unmatched_kw = score_job(job_data["description"], keywords)
            # Persist job with score
            job = Job(
                fingerprint=fp,
                score=score,
                status="matched" if score >= settings.match_threshold else "discovered",
                **job_data,
            )
            session.add(job)
            new_count += 1
            if score >= settings.match_threshold:
                matched_count += 1
        
        await session.commit()
    
    return {
        "discovered": len(all_jobs),
        "new": new_count,
        "matched": matched_count,
        "source_counts": source_counts,
        "errors": errors,
    }
```

### Anti-Patterns to Avoid
- **Storing raw API responses:** Normalize immediately, store only the common schema. Raw responses are large and vary by source.
- **Synchronous HTTP calls:** Always use `httpx.AsyncClient` within the async pipeline. Never use `requests`.
- **Fetching without timeout:** Always set `timeout=30.0` on the client. ATS APIs can be slow.
- **Re-scoring on every page load:** Score once at discovery time, store in DB. Only re-score if keywords change.
- **Client-side JavaScript for sorting:** Use HTMX with query params (e.g., `hx-get="/jobs?sort=score&dir=desc"`) and server-side sorting via SQL ORDER BY. No JS framework needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client | Raw urllib/aiohttp | httpx.AsyncClient | Already in deps, async-native, built-in timeout/retry |
| URL parsing | Manual string splitting | urllib.parse.urlparse | Handles edge cases (ports, query strings, encoding) |
| Hashing | MD5 or custom | hashlib.sha256 | Standard, collision-resistant |
| Date parsing | strptime with format guessing | datetime.fromisoformat | All three APIs return ISO 8601 |
| HTML rendering in description | Custom HTML sanitizer | Jinja2 `|safe` filter on stored HTML | Descriptions come from ATS, not user input |

## Common Pitfalls

### Pitfall 1: Lever API Returns Flat Array, Not Object
**What goes wrong:** Calling `resp.json()["jobs"]` on Lever response raises KeyError because Lever returns a bare JSON array `[{...}, {...}]`, not `{"jobs": [...]}`.
**Why it happens:** Greenhouse and Ashby wrap in an object; Lever does not.
**How to avoid:** Each fetcher must handle its own response shape. Never assume uniform structure.
**Warning signs:** KeyError in production logs from Lever fetches.

### Pitfall 2: Lever Lacks Posted Date
**What goes wrong:** The Lever public postings API does not include a `createdAt` or `publishedAt` field. The `posted_date` will be None for Lever jobs.
**Why it happens:** Lever's public API is intentionally minimal.
**How to avoid:** Make `posted_date` nullable in the Job model. UI should show "N/A" or the first-seen date from the app's own DB.
**Warning signs:** Empty date column for all Lever jobs.

### Pitfall 3: Ashby Returns descriptionHtml Not Plain Text by Default
**What goes wrong:** Using `j["description"]` on Ashby returns nothing -- the field is called `descriptionHtml` or `descriptionPlain`.
**Why it happens:** Ashby uses explicit suffixed field names.
**How to avoid:** Prefer `descriptionPlain` for scoring, store `descriptionHtml` for display.
**Warning signs:** Empty descriptions for Ashby jobs, zero scores.

### Pitfall 4: Greenhouse content=true Required for Descriptions
**What goes wrong:** Greenhouse `/jobs` endpoint without `?content=true` omits the `content` field (job description HTML).
**Why it happens:** It's a performance optimization -- description bodies are large.
**How to avoid:** Always pass `params={"content": "true"}` to the Greenhouse jobs endpoint.
**Warning signs:** All Greenhouse jobs have empty descriptions and score 0.

### Pitfall 5: Plain Slug Auto-Detection Requires Probing
**What goes wrong:** User types "stripe" -- which ATS is it? Could be any of the three.
**Why it happens:** Many companies use just their name as the slug across all ATS providers.
**How to avoid:** When the URL pattern doesn't match a known ATS domain, probe all three APIs in sequence (Greenhouse first as most common) and use the first that returns 200. Display the detected source to the user for confirmation.
**Warning signs:** User frustration if the wrong ATS is detected, or if all three are probed and none match.

### Pitfall 6: Large Boards Can Return Hundreds of Jobs
**What goes wrong:** Some companies (Google, Amazon) have thousands of open positions. Fetching with `?content=true` on Greenhouse returns megabytes of data.
**Why it happens:** No pagination on public APIs (Greenhouse and Ashby return all jobs at once).
**How to avoid:** Set reasonable httpx timeout (30s), use streaming if needed, be aware of memory. Consider storing description separately or truncating for scoring purposes. Lever has `skip` and `limit` params that can be used.
**Warning signs:** Slow fetches, high memory usage, timeouts on large boards.

### Pitfall 7: Anomaly False Positives on New Sources
**What goes wrong:** A newly added source has no 7-day history, so any discovery triggers an anomaly.
**Why it happens:** Rolling average with insufficient data defaults to 0.
**How to avoid:** Require at least 3 data points before enabling anomaly detection for a source. Skip anomaly check if fewer than 3 historical runs.
**Warning signs:** Permanent yellow banner for recently added sources.

## SQLModel Schema

### Source Table
```python
class Source(SQLModel, table=True):
    """An ATS board the user wants to discover jobs from."""
    __tablename__ = "sources"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True)                    # e.g. "stripe"
    source_type: str = Field()                        # greenhouse | lever | ashby
    display_name: Optional[str] = Field(default=None) # user-friendly label
    enabled: bool = Field(default=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    last_fetch_status: Optional[str] = Field(default=None)  # ok | error
    last_error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Job Table
```python
class Job(SQLModel, table=True):
    """A normalized job posting discovered from any ATS source."""
    __tablename__ = "jobs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    fingerprint: str = Field(unique=True, index=True)  # SHA256 dedup key
    external_id: str = Field()                          # ATS-specific ID
    title: str = Field()
    company: str = Field(index=True)
    location: str = Field(default="")
    description: str = Field(default="")                # plain text for scoring
    description_html: str = Field(default="")           # HTML for display
    url: str = Field()                                  # original posting URL
    source: str = Field()                               # greenhouse | lever | ashby
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id")
    posted_date: Optional[datetime] = Field(default=None)
    score: int = Field(default=0)                       # 0-100 keyword overlap
    matched_keywords: str = Field(default="")           # pipe-delimited
    status: str = Field(default="discovered")           # discovered | matched | queued | applied
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    run_id: Optional[int] = Field(default=None, foreign_key="runs.id")
```

### DiscoveryRunStats Table (for anomaly detection)
```python
class DiscoveryRunStats(SQLModel, table=True):
    """Per-source discovery counts for each run, for anomaly rolling average."""
    __tablename__ = "discovery_run_stats"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="runs.id", index=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    discovered_count: int = Field(default=0)
    matched_count: int = Field(default=0)
    error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

## ATS API Reference

### Greenhouse Public Job Board API
- **List jobs:** `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- **No auth required** for GET endpoints
- **Response:** `{"jobs": [...], "meta": {"total": N}}`
- **Job fields:** id, internal_job_id, title, updated_at, location.name, absolute_url, content (HTML, only with content=true), departments[], offices[]
- **No pagination** -- returns all jobs at once
- **Validate slug:** `GET https://boards-api.greenhouse.io/v1/boards/{slug}` returns board info or 404
- **Confidence:** HIGH (verified via official docs at developers.greenhouse.io/job-board.html)

### Lever Public Postings API
- **List jobs:** `GET https://api.lever.co/v0/postings/{slug}?mode=json`
- **EU variant:** `https://api.eu.lever.co/v0/postings/{slug}?mode=json`
- **No auth required** for GET endpoints
- **Response:** Flat JSON array `[{...}, {...}]` (NOT wrapped in an object)
- **Job fields:** id, text (title), categories.location, categories.commitment, categories.team, hostedUrl, applyUrl, description, descriptionPlain, lists[], workplaceType
- **No posted_date field** in public API
- **Pagination:** `skip` and `limit` query params available
- **Validate slug:** Returns empty array `[]` for invalid slug (not 404)
- **Confidence:** HIGH (verified via github.com/lever/postings-api)

### Ashby Public Job Board API
- **List jobs:** `GET https://api.ashbyhq.com/posting-api/job-board/{slug}`
- **Optional:** `?includeCompensation=true` for salary data
- **No auth required**
- **Response:** `{"apiVersion": "1", "jobs": [...]}`
- **Job fields:** title, location, secondaryLocations[], department, team, isRemote, workplaceType, descriptionHtml, descriptionPlain, publishedAt, employmentType, jobUrl, applyUrl, isListed
- **No pagination or filtering** -- returns all jobs
- **Validate slug:** Returns 404 or error for invalid slug
- **Confidence:** HIGH (verified via developers.ashbyhq.com/docs/public-job-posting-api)

## UI Patterns

### Settings Sources Section
The settings sidebar currently has 10 sections. Add "Sources" as a new section between "Keywords" and "Threshold" (or after "Budget"). The section renders a list of configured sources with enable/disable toggles and an "Add source" form.

```html
<!-- Add source form -->
<form hx-post="/settings/sources" hx-target="#sources-list" hx-swap="innerHTML">
  <input type="text" name="slug_or_url" placeholder="e.g. stripe or https://boards.greenhouse.io/stripe" required>
  <button type="submit">Add</button>
</form>

<!-- Source list with toggles -->
<div id="sources-list">
  {% for source in sources %}
  <div class="source-row">
    <span>{{ source.display_name or source.slug }}</span>
    <span class="badge">{{ source.source_type }}</span>
    {% if source.last_fetch_status == "error" %}
      <span class="badge error">Error</span>
    {% endif %}
    <input type="checkbox" role="switch"
           {% if source.enabled %}checked{% endif %}
           hx-post="/settings/sources/{{ source.id }}/toggle"
           hx-swap="none">
    <button hx-delete="/settings/sources/{{ source.id }}"
            hx-confirm="Remove {{ source.slug }}?"
            hx-target="closest .source-row"
            hx-swap="outerHTML">Remove</button>
  </div>
  {% endfor %}
</div>
```

### Jobs Table with Inline Expand
Use HTMX `hx-get` on table rows to load the detail partial into a hidden `<tr>` below. Server-side sorting via query params.

```html
<table role="grid">
  <thead>
    <tr>
      <th><a hx-get="/jobs?sort=title" hx-target="#jobs-body">Title</a></th>
      <th><a hx-get="/jobs?sort=company" hx-target="#jobs-body">Company</a></th>
      <th><a hx-get="/jobs?sort=source" hx-target="#jobs-body">Source</a></th>
      <th><a hx-get="/jobs?sort=score" hx-target="#jobs-body">Score</a></th>
      <th><a hx-get="/jobs?sort=posted_date" hx-target="#jobs-body">Posted</a></th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody id="jobs-body">
    {% for job in jobs %}
    <tr hx-get="/jobs/{{ job.id }}/detail"
        hx-target="next tr"
        hx-swap="innerHTML"
        style="cursor: pointer;">
      <td>{{ job.title }}</td>
      <td>{{ job.company }}</td>
      <td>{{ job.source }}</td>
      <td><span class="badge {{ 'green' if job.score >= threshold else 'yellow' if job.score >= threshold * 0.5 else 'gray' }}">{{ job.score }}%</span></td>
      <td>{{ job.posted_date.strftime("%Y-%m-%d") if job.posted_date else "N/A" }}</td>
      <td>{{ job.status }}</td>
    </tr>
    <tr class="detail-row" style="display:none;"><td colspan="6"></td></tr>
    {% endfor %}
  </tbody>
</table>
```

### Score Badge Colors (Pico.css compatible)
```css
.badge.green { background: var(--pico-ins-color, #2a7); color: white; }
.badge.yellow { background: #c90; color: white; }
.badge.gray { background: var(--pico-muted-color, #888); color: white; }
.badge.error { background: var(--pico-del-color, #d33); color: white; }
```

### Anomaly Banner (dismissable)
```html
{% if anomaly_warning %}
<article class="warning" id="anomaly-banner" style="border: 2px solid #c90; background: #ffd;">
  <p><strong>Low discovery count detected.</strong> {{ anomaly_warning }}</p>
  <button hx-post="/dismiss-anomaly" hx-swap="delete" hx-target="#anomaly-banner">Dismiss</button>
</article>
{% endif %}
```

## API Polling Strategy (Claude's Discretion)

**Recommendation: Parallel with asyncio.gather, per-source timeout.**

```python
import asyncio

async def fetch_all_sources(client: httpx.AsyncClient, sources: list[Source]) -> dict:
    """Fetch from all sources in parallel. Individual failures don't block others."""
    tasks = [fetch_source(client, s) for s in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Process results, separating successes from errors
    ...
```

**Rationale:** Sources are independent. A slow Ashby response should not delay Greenhouse results. `return_exceptions=True` ensures one failure does not cancel all tasks. The hourly interval is generous enough that parallel fetching is not rate-limit-risky.

**Per-source timeout:** 30 seconds via httpx.AsyncClient(timeout=30.0). If a source times out, mark it as errored and continue.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| requests library | httpx | 2023+ | Async native, better timeout handling |
| MD5 for fingerprints | SHA-256 | Industry standard | Collision resistance |
| Client-side table sorting (JS) | Server-side sort via HTMX params | HTMX pattern | No JS framework needed |

## Open Questions

1. **Lever EU vs Global API**
   - What we know: Lever has `api.lever.co` (global) and `api.eu.lever.co` (EU). Some companies may be EU-only.
   - What's unclear: Whether we need to support both or can assume global.
   - Recommendation: Try global first; if 404, try EU. Store the resolved base URL in the Source row for future fetches.

2. **Greenhouse boards-api.greenhouse.io vs boards.greenhouse.io**
   - What we know: The API endpoint is `boards-api.greenhouse.io`, but users will paste `boards.greenhouse.io` URLs.
   - What's unclear: Nothing -- this is a known URL rewrite.
   - Recommendation: Auto-detect handles this in the URL parser; always use `boards-api.greenhouse.io` for API calls.

3. **Re-scoring when keywords change**
   - What we know: Score is stored at discovery time. If user adds/removes keywords, existing jobs' scores are stale.
   - What's unclear: Whether to re-score all jobs on keyword change or wait for next run.
   - Recommendation: Re-score all existing jobs when keywords change (background task triggered by POST /settings/keywords). This keeps the jobs table accurate between runs.

4. **DISC-04: General web search discovery**
   - What we know: The requirements mention "discovers ATS-hosted jobs via general web search matching user keywords."
   - What's unclear: This is not mentioned in CONTEXT.md decisions and is a significantly different feature (requires a web search API, not just ATS fetching).
   - Recommendation: Defer DISC-04 or mark it as out-of-scope for Phase 3. The three ATS APIs cover the core use case. If needed, it can be a Phase 4 addition.

5. **MATCH-02: Auto-applies only to jobs at/above threshold**
   - What we know: The user decision says "below-threshold jobs are NOT auto-queued." Jobs at/above threshold should be auto-queued (status = "matched").
   - What's unclear: The requirement says "auto-applies" but Phase 3 does not do submission -- it queues for downstream.
   - Recommendation: Set status to "matched" for at-or-above-threshold jobs. "queued" status is set when user manually queues below-threshold jobs. Actual submission is a later phase.

## Sources

### Primary (HIGH confidence)
- [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html) - Full endpoint documentation, response schemas, query parameters
- [Lever Postings API](https://github.com/lever/postings-api) - Official GitHub repo with complete API docs
- [Ashby Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) - Official developer docs

### Secondary (MEDIUM confidence)
- WebSearch results confirming API patterns and field names across multiple sources

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in requirements.txt, no new deps
- Architecture: HIGH - follows established project patterns (SQLModel, HTMX, sidebar settings)
- ATS API shapes: HIGH - verified via official documentation for all three providers
- Pitfalls: HIGH - derived from API documentation and common integration patterns
- Anomaly detection: MEDIUM - algorithm is simple but edge cases (new sources, sparse data) need testing

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (APIs are stable, public endpoints rarely change)
