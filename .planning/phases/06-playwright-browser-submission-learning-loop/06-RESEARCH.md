# Phase 6: Playwright Browser Submission & Learning Loop - Research

**Researched:** 2026-04-15
**Domain:** Browser automation (Playwright), ATS form filling, LLM-assisted field matching
**Confidence:** MEDIUM

## Summary

Phase 6 adds browser-based job application submission via Playwright for Greenhouse, Lever, and Ashby ATS platforms (plus generic forms), and introduces a learning loop where unknown form fields are collected, answered by the user, and semantically matched for reuse on future applications. The PlaywrightStrategy plugs into the existing SubmitterStrategy Protocol from Phase 5 (05-03) without modifying the pipeline or registry selection logic.

Key finding: **All three target ATS platforms (Greenhouse, Lever, Ashby) offer public POST APIs** for application submission alongside their web forms. However, the user's locked decisions specify Playwright browser automation (SUBM-03), not API submission. The browser approach handles custom fields, GDPR consent checkboxes, and company-specific form variations that the APIs may not cover. The API details are still useful for understanding field naming conventions and validation requirements.

The Playwright base image (v1.58.0-noble) is already shipped in the Docker image from Phase 1 (01-01). The `storageState` API provides cookie/localStorage persistence across container restarts. The LLM semantic matching for answer reuse leverages the existing AnthropicProvider and BudgetGuard from Phase 4.

**Primary recommendation:** Build a three-layer architecture: (1) ATS-specific form fillers (Greenhouse/Lever/Ashby) using label-based heuristics as per locked decisions, (2) a generic form filler for unknown ATS platforms, (3) a learning loop service that collects unknowns, stores user answers, and matches them semantically via Claude on future encounters.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Form-filling strategy
- **Label-based heuristics** for matching form fields to profile data on known ATS platforms (Greenhouse/Lever/Ashby). Match by keyword patterns in field labels (contains 'name', 'email', 'phone', etc.) rather than hardcoded per-ATS field maps or LLM-assisted matching
- **Dropdown fields: profile stores exact values.** User pre-configures exact dropdown answers in their profile (e.g., work_auth='US Citizen'). Direct match against option text. No LLM fallback for dropdowns
- **File uploads: auto-detect resume + cover letter by label, skip unknown file fields.** If label contains 'resume' -> tailored DOCX, 'cover letter' -> cover letter file. Unknown file fields are skipped (not halted), but mandatory unknown file fields are logged/noted as unknown fields for the user to see
- **Multi-step forms: screenshot every step (audit trail) + halt on unknown fields.** A Settings toggle lets the user switch between "pause if unsure" mode (halt on unknown fields) and "always advance" mode (screenshot-only, no halts). Default to "pause if unsure" for initial runs; user switches to "always advance" after building confidence
- **Collect ALL unknown fields across all form pages before halting** -- scan the entire form, collect every unknown field, then present them all at once so the user answers everything in one session rather than one field per retry

#### Unknown field UX
- **Context shown: screenshot + field label + job title/company + full job description.** Helps the user answer in context of what the specific job is asking
- **Dedicated '/needs-info' queue page** listing all halted applications with their unknown fields. Not inline on job detail -- a standalone page for triaging halted applications
- **Immediate retry after user answers.** As soon as the user provides answers, Playwright re-opens the form and attempts submission right away. Instant feedback, no waiting for next scheduled run
- **Collect all unknowns before halting** -- user sees every unknown field from all form pages at once, answers them all, then retry fills the complete form

#### Answer reuse & matching
- **LLM semantic matching** for reusing saved answers on future forms. Send new field label + saved answer labels to Claude to determine equivalence. Catches paraphrases like "Are you authorized to work?" vs "Work Authorization"
- **Always auto-fill if LLM says it's a match.** No confidence threshold. Trust the model. Fewer halts, faster throughput
- **Reuse summary in success email.** The per-job success notification email includes a section listing which saved answers were auto-applied. User sees what was reused after the fact
- **'Saved Answers' section in Settings** for viewing and managing all question->answer pairs. User can edit or delete any saved answer from one place

#### Playwright session & reliability
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

### Deferred Ideas (OUT OF SCOPE)
(None specified)
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | 1.58.0 | Browser automation for form filling | Already in Docker base image (01-01); async Python API matches existing codebase patterns |
| anthropic | 0.94.0 | LLM semantic matching for answer reuse | Already installed; AnthropicProvider + BudgetGuard reusable from Phase 4 |
| sqlmodel | >=0.0.24 | New tables (SavedAnswer, UnknownField) | Existing ORM; matches Phase 1-5 model pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pillow | N/A | NOT needed | Playwright screenshots save as PNG natively; no image processing required |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Browser form fill (Playwright) | ATS POST APIs directly | APIs exist for all 3 ATS but user locked Playwright; APIs miss custom fields/GDPR checkboxes/company-specific variations |
| storageState JSON | launch_persistent_context with user_data_dir | storageState is lighter (JSON file vs full Chrome profile dir); user decision locked storageState |
| LLM semantic matching | Fuzzy string matching (difflib/fuzzywuzzy) | LLM catches paraphrases ("authorized to work" vs "work authorization") that fuzzy matching misses; user locked LLM approach |

**Installation:**
```bash
# No new pip dependencies — playwright is in the Docker base image,
# anthropic + sqlmodel already installed. Playwright browsers are
# pre-installed in mcr.microsoft.com/playwright/python:v1.58.0-noble.
```

## Architecture Patterns

### Recommended Project Structure
```
app/
├── playwright_submit/           # NEW — Phase 6 browser submission
│   ├── __init__.py
│   ├── strategy.py              # PlaywrightStrategy (SubmitterStrategy Protocol)
│   ├── browser.py               # Browser lifecycle (launch, storageState, close)
│   ├── form_filler.py           # Base FormFiller + field-matching heuristics
│   ├── fillers/
│   │   ├── __init__.py
│   │   ├── greenhouse.py        # Greenhouse-specific form filler
│   │   ├── lever.py             # Lever-specific form filler
│   │   ├── ashby.py             # Ashby-specific form filler
│   │   └── generic.py           # Generic ATS form filler
│   ├── captcha.py               # CAPTCHA/2FA detection
│   └── screenshots.py           # Screenshot capture + storage
├── learning/                    # NEW — Phase 6 learning loop
│   ├── __init__.py
│   ├── models.py                # SavedAnswer + UnknownField models
│   ├── service.py               # Answer persistence + retrieval
│   ├── matcher.py               # LLM semantic matching
│   └── needs_info.py            # Needs-info queue aggregation
├── web/
│   ├── routers/
│   │   ├── needs_info.py        # NEW — /needs-info queue page
│   │   └── saved_answers.py     # NEW — Settings > Saved Answers
│   └── templates/
│       ├── needs_info/           # NEW — needs-info queue templates
│       └── partials/
│           └── settings_saved_answers.html.j2  # NEW
```

### Pattern 1: PlaywrightStrategy as SubmitterStrategy Protocol Implementation
**What:** PlaywrightStrategy satisfies the existing SubmitterStrategy Protocol from 05-03. It is prepended to the registry list so it takes priority over EmailStrategy for known-ATS jobs.
**When to use:** For any job where `job.source` is `greenhouse`, `lever`, or `ashby`, or where the job URL matches known ATS patterns.

```python
# app/playwright_submit/strategy.py
from app.submission.registry import (
    SubmissionContext,
    SubmissionOutcome,
    SubmitterStrategy,
)

class PlaywrightStrategy:
    """SUBM-03/04: submit via Playwright browser automation."""
    name: str = "playwright"

    def is_applicable(self, job: Job, description: str) -> bool:
        # Check job.source or URL pattern for known ATS
        return job.source in ("greenhouse", "lever", "ashby") or \
               _is_known_ats_url(job.url)

    async def submit(self, ctx: SubmissionContext) -> SubmissionOutcome:
        # 1. Launch/reuse browser context with storageState
        # 2. Navigate to application form URL
        # 3. Select appropriate filler (greenhouse/lever/ashby/generic)
        # 4. Fill known fields from profile + tailored resume
        # 5. Collect unknown fields across all form pages
        # 6. If unknowns and pause_if_unsure: return needs_info outcome
        # 7. Screenshot each step
        # 8. Submit form
        # 9. Save storageState
        ...
```

### Pattern 2: Registry Prepend for Strategy Priority
**What:** Phase 6 modifies `default_registry()` to return `[PlaywrightStrategy(), EmailStrategy()]`. Since `select_strategy` is first-applicable iteration, PlaywrightStrategy gets first crack at every job. It returns `False` from `is_applicable` for jobs without a known ATS form URL, falling through to EmailStrategy.
**When to use:** This is the only integration point with Phase 5 pipeline code.

```python
# Updated app/submission/registry.py::default_registry()
def default_registry() -> list[SubmitterStrategy]:
    from app.submission.strategies.email import EmailStrategy
    from app.playwright_submit.strategy import PlaywrightStrategy
    return [PlaywrightStrategy(), EmailStrategy()]
```

### Pattern 3: Browser Lifecycle Management
**What:** A single Playwright browser instance is created per pipeline run (not per job). The browser context loads storageState from `data/browser/storageState.json` and saves it back after each successful form submission.
**When to use:** The browser is created at PlaywrightStrategy first use and closed after the drain loop completes.

```python
# app/playwright_submit/browser.py
from playwright.async_api import async_playwright

STORAGE_STATE_PATH = "data/browser/storageState.json"

class BrowserManager:
    """Manages a single Playwright browser instance per pipeline run."""

    async def get_context(self, headless: bool = True):
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
            )
        storage = STORAGE_STATE_PATH if Path(STORAGE_STATE_PATH).exists() else None
        self._context = await self._browser.new_context(
            storage_state=storage,
        )
        self._context.set_default_timeout(30000)  # 30s
        self._context.set_default_navigation_timeout(60000)  # 60s
        return self._context

    async def save_state(self):
        if self._context:
            await self._context.storage_state(path=STORAGE_STATE_PATH)

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
```

### Pattern 4: Label-Based Field Matching Heuristics
**What:** Map form field labels to profile data using keyword pattern matching. Priority order determines which profile field maps when multiple patterns could match.
**When to use:** For every form field on every ATS platform.

```python
# app/playwright_submit/form_filler.py
# Recommended heuristic priority order (Claude's discretion)
LABEL_HEURISTICS = [
    # (label_pattern, profile_field, input_method)
    (r"\bfirst\s*name\b", "first_name", "fill"),
    (r"\blast\s*name\b", "last_name", "fill"),
    (r"\bfull\s*name\b", "full_name", "fill"),
    (r"\bname\b", "full_name", "fill"),  # fallback after first/last
    (r"\bemail\b", "email", "fill"),
    (r"\bphone\b", "phone", "fill"),
    (r"\blinkedin\b", "linkedin_url", "fill"),
    (r"\bgithub\b", "github_url", "fill"),
    (r"\bportfolio\b|personal\s*(?:site|website|url)\b", "portfolio_url", "fill"),
    (r"\bresume\b|cv\b", "_resume_file", "upload"),
    (r"\bcover\s*letter\b", "_cover_letter_file", "upload"),
    (r"\bwork\s*auth", "work_authorization", "select_or_fill"),
    (r"\bsalary\b|compensation\b", "salary_expectation", "fill"),
    (r"\byears?\s*(?:of\s*)?exp", "years_experience", "fill"),
    (r"\blocation\b|city\b|address\b", "address", "fill"),
]
```

### Pattern 5: Multi-Step Form Scanning (Collect All Unknowns)
**What:** Before submitting, scan ALL form pages to collect unknown fields. Navigate through the form using "Next" / "Continue" buttons, collecting field metadata from each page. Only halt after all pages are scanned.
**When to use:** Multi-step forms (common on Greenhouse and Ashby).

```python
async def scan_form_pages(page, filler) -> tuple[list[KnownField], list[UnknownField]]:
    """Scan all form pages, collecting known and unknown fields."""
    all_known = []
    all_unknown = []

    while True:
        # Screenshot current step
        await page.screenshot(path=f"data/screenshots/{job_id}/step_{step}.png", full_page=True)

        # Collect fields on current page
        known, unknown = await filler.classify_fields(page)
        all_known.extend(known)
        all_unknown.extend(unknown)

        # Try to advance to next page (without submitting)
        next_btn = page.locator("button:has-text('Next'), button:has-text('Continue')")
        if await next_btn.count() > 0:
            await next_btn.click()
            await page.wait_for_load_state("networkidle")
            step += 1
        else:
            break

    return all_known, all_unknown
```

### Pattern 6: Learning Loop — Answer Storage and Semantic Matching
**What:** When the user provides an answer to an unknown field, it is stored as a SavedAnswer keyed by the field label. On future encounters, LLM semantic matching compares the new field label against all saved answer labels to find matches.

```python
# app/learning/matcher.py
async def find_matching_answer(
    field_label: str,
    saved_answers: list[SavedAnswer],
    provider: LLMProvider,
) -> SavedAnswer | None:
    """Use LLM to find a semantically matching saved answer."""
    if not saved_answers:
        return None

    labels = [sa.field_label for sa in saved_answers]
    prompt = f"""Given a new form field label: "{field_label}"

And these previously answered field labels:
{chr(10).join(f'- "{l}"' for l in labels)}

Which previously answered label (if any) is asking the same question?
Return ONLY the matching label text, or "NONE" if no match."""

    response = await provider.complete(
        system=[{"type": "text", "text": "You match form field labels semantically."}],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.0,
    )
    # Parse response, find matching SavedAnswer
    ...
```

### Anti-Patterns to Avoid
- **Per-field LLM calls for known ATS forms:** Use label heuristics first; only use LLM for answer reuse matching, never for initial field identification on known platforms
- **Global browser instance across pipeline runs:** Create per-run, close after. A leaked browser process consumes memory indefinitely
- **Retrying CAPTCHA'd forms automatically:** The user decision explicitly says halt+notify+skip. Do not add CAPTCHA solver dependencies
- **Storing screenshots in the DB:** Store as files on disk under `data/screenshots/{job_id}/`, reference by path in the UnknownField/Submission rows
- **Blocking the pipeline on a single form:** Fail fast, screenshot, mark failed/needs_info, move to next job

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser automation | Custom Selenium/Puppeteer wrapper | Playwright async Python API | Already in Docker image; first-class async support; storageState built-in |
| Cookie persistence | Manual cookie jar + file I/O | `context.storage_state(path=...)` | Handles cookies + localStorage + IndexedDB; JSON format; survives container restarts |
| Form field detection | DOM parsing with BeautifulSoup | `page.get_by_label()`, `page.locator()` | Playwright locators handle dynamic content, shadow DOM, iframes |
| File upload | Manual multipart construction | `locator.set_input_files(path)` | Handles file chooser dialogs, drag-and-drop, programmatic file input |
| Screenshot capture | PIL/Pillow image creation | `page.screenshot(path=..., full_page=True)` | Native PNG output; full-page support; no extra dependency |
| Semantic matching | difflib/fuzzywuzzy string comparison | Claude via existing AnthropicProvider | Catches paraphrases; user locked this approach |
| CAPTCHA detection | Complex ML-based detection | Simple selector checks for known CAPTCHA iframes/divs | reCAPTCHA uses `iframe[src*="recaptcha"]`, hCaptcha uses `iframe[src*="hcaptcha"]`, Cloudflare uses `#challenge-running` |

**Key insight:** Playwright's locator API (get_by_label, get_by_role, get_by_placeholder) already handles the hard parts of form field identification. The label-based heuristic layer sits ON TOP of Playwright's built-in label matching rather than replacing it.

## Common Pitfalls

### Pitfall 1: storageState vs launch_persistent_context
**What goes wrong:** Using `launch_persistent_context(user_data_dir=...)` instead of `browser.new_context(storage_state=...)`. Persistent context stores the entire Chrome profile (~100MB+) vs storageState which is a small JSON file (~10KB).
**Why it happens:** Both approaches "persist sessions" but at different levels.
**How to avoid:** Use `new_context(storage_state=path)` + `context.storage_state(path=path)` as the user decision specifies. Store the JSON file in `data/browser/storageState.json` on the mounted volume.
**Warning signs:** Large `user_data_dir` folder appearing in the data volume; Chrome lock files blocking concurrent access.

### Pitfall 2: Playwright Event Loop Conflict
**What goes wrong:** Playwright's `async_playwright()` creates its own event loop machinery. Starting it inside an already-running asyncio loop (FastAPI/uvicorn) can conflict.
**Why it happens:** Playwright uses a subprocess (node) for browser communication; the async API wraps it with asyncio futures.
**How to avoid:** Use `async with async_playwright() as p:` within an async function that is already on the event loop. Do NOT call `asyncio.run()` or `asyncio.get_event_loop().run_until_complete()` inside the strategy. The pipeline already runs in an async context via APScheduler's asyncio executor.
**Warning signs:** `RuntimeError: This event loop is already running` or `RuntimeError: Cannot run the event loop while another loop is running`.

### Pitfall 3: Greenhouse iframe Embedding
**What goes wrong:** Many companies embed Greenhouse forms in an iframe. Playwright's `page.goto(url)` loads the parent page, but the form lives inside `iframe[src*="boards.greenhouse.io"]`.
**Why it happens:** Greenhouse offers both hosted (`boards.greenhouse.io/company/jobs/123`) and embedded (iframe on company career page) forms.
**How to avoid:** When the job URL is a company career page (not boards.greenhouse.io directly), check for Greenhouse iframes and use `page.frame_locator("iframe[src*='boards.greenhouse.io']")` to interact with the form. Alternatively, rewrite the URL to the direct Greenhouse hosted form URL using the known `boards.greenhouse.io/{slug}/jobs/{id}` pattern.
**Warning signs:** `page.get_by_label("First Name")` returns 0 matches even though the form is visibly present.

### Pitfall 4: Dynamic Form Fields (React/SPA)
**What goes wrong:** ATS forms built with React/Next.js may not have all fields rendered in the initial DOM. Fields appear after scrolling, clicking "Show more", or selecting dropdown values.
**Why it happens:** Modern ATS platforms use client-side rendering with lazy-loaded form sections.
**How to avoid:** After page load, wait for `page.wait_for_load_state("networkidle")` before scanning fields. For multi-step forms, wait after each "Next" click. Use `page.wait_for_selector()` with a reasonable timeout before interacting with specific fields.
**Warning signs:** Intermittent "element not found" errors that pass on retry; fields that appear in headed mode but not in headless mode.

### Pitfall 5: Dropdown Option Text Mismatch
**What goes wrong:** Profile stores "US Citizen" but dropdown options are "United States Citizen" or "I am a US Citizen". Direct text match fails.
**Why it happens:** Each company configures their own dropdown option text.
**How to avoid:** For known fields (work_authorization, etc.), try exact match first, then case-insensitive substring match. If no match, treat as an unknown field — the user corrects the profile value to match common option text. Do NOT use LLM for dropdown matching per user decision.
**Warning signs:** Work authorization and similar fields consistently showing as "unknown" despite being configured in the profile.

### Pitfall 6: Form Submission Without Proper Button Identification
**What goes wrong:** Clicking the wrong button (e.g., "Save Draft" instead of "Submit Application") or failing to find the submit button.
**Why it happens:** ATS forms have multiple buttons; the submit button text varies ("Apply", "Submit Application", "Send Application", "Apply Now").
**How to avoid:** Use a priority list of submit button patterns: `button:has-text("Submit"), button:has-text("Apply"), input[type="submit"]`. Screenshot BEFORE clicking to confirm the right button is targeted. For multi-step forms, distinguish "Next"/"Continue" from "Submit".
**Warning signs:** Applications stuck in "draft" state on the ATS side; duplicate submissions from clicking the wrong button.

### Pitfall 7: Screenshot Storage Unbounded Growth
**What goes wrong:** Screenshots accumulate indefinitely, filling the data volume.
**Why it happens:** Every form step generates a PNG screenshot; with hundreds of applications, this grows to GB.
**How to avoid:** Implement a retention policy. Recommendation: keep screenshots for 30 days, then auto-delete. Store under `data/screenshots/{job_id}/step_{N}.png`. A cleanup task in the pipeline can prune old screenshots.
**Warning signs:** Disk usage growing faster than expected; slow startup due to large data directory.

### Pitfall 8: Rate Limiting by ATS Platforms
**What goes wrong:** Submitting too many applications too quickly via Playwright triggers ATS-side rate limiting or IP bans.
**Why it happens:** Browser automation at scale looks like bot traffic.
**How to avoid:** The existing Phase 5 SAFE-02 randomized inter-submission delay already applies between jobs. Playwright submissions go through the same drain loop. Add a minimum 30-second delay between Playwright submissions specifically (browser interactions are inherently slower than email sends).
**Warning signs:** HTTP 429 responses; CAPTCHA challenges appearing more frequently; ATS blocking the user's IP.

## Code Examples

### Verified: Playwright Async Form Filling (from official docs)
```python
# Source: https://playwright.dev/python/docs/input
# Text input
await page.get_by_label("First Name").fill("John")
await page.get_by_label("Email").fill("john@example.com")

# Dropdown/select
await page.get_by_label("Country").select_option(label="United States")

# Checkbox
await page.get_by_label("I agree to the terms").check()

# File upload
await page.get_by_label("Upload resume").set_input_files("/path/to/resume.docx")

# Screenshot
await page.screenshot(path="step_1.png", full_page=True)
```

### Verified: StorageState Persistence (from official docs)
```python
# Source: https://playwright.dev/python/docs/auth
# Save after successful form submission
await context.storage_state(path="data/browser/storageState.json")

# Load on next run
context = await browser.new_context(
    storage_state="data/browser/storageState.json"
)
```

### Verified: CAPTCHA Detection Selectors
```python
# Source: research synthesis from oxylabs.io, playwright-recaptcha docs
async def detect_blocking_element(page) -> str | None:
    """Return blocking element type or None."""
    checks = [
        ("iframe[src*='recaptcha']", "recaptcha"),
        ("iframe[src*='hcaptcha']", "hcaptcha"),
        ("#challenge-running", "cloudflare"),
        ("[class*='captcha']", "generic_captcha"),
        # 2FA detection
        ("input[name*='otp']", "2fa_otp"),
        ("input[name*='verification_code']", "2fa_code"),
        ("[class*='two-factor']", "2fa"),
    ]
    for selector, label in checks:
        if await page.locator(selector).count() > 0:
            return label
    return None
```

### Pattern: ATS Form URL Detection (extends existing detect_source)
```python
# Builds on app.discovery.fetchers.detect_source
def get_ats_form_url(job: Job) -> str | None:
    """Return the direct application form URL for a known ATS job."""
    if job.source == "greenhouse":
        # boards.greenhouse.io/{slug}/jobs/{external_id}#app
        return f"https://boards.greenhouse.io/{job.company}/jobs/{job.external_id}#app"
    elif job.source == "lever":
        # jobs.lever.co/{slug}/{external_id}/apply
        return f"https://jobs.lever.co/{job.company}/{job.external_id}/apply"
    elif job.source == "ashby":
        # jobs.ashbyhq.com/{slug}/{external_id}/application
        return f"https://jobs.ashbyhq.com/{job.company}/{job.external_id}/application"
    return None
```

## ATS-Specific Form Details

### Greenhouse
- **Hosted form URL:** `https://boards.greenhouse.io/{slug}/jobs/{id}#app` (the `#app` anchor scrolls to the application section)
- **Standard fields:** `first_name`, `last_name`, `email`, `phone`, `location` (with hidden lat/lng)
- **File uploads:** `resume` (accepts PDF, DOC, DOCX, TXT, RTF), `cover_letter`
- **Custom questions:** `question_{ID}` — types vary (text, select, multi-select, file)
- **Form embed:** Often in an iframe; direct URL at boards.greenhouse.io bypasses iframe
- **Submit button:** Typically `<input type="submit" value="Submit Application">`
- **GDPR fields:** May include consent checkboxes depending on company configuration
- **API alternative:** POST to `boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}` with Basic Auth (but user locked browser approach)

### Lever
- **Application form URL:** `https://jobs.lever.co/{slug}/{posting_id}/apply`
- **Standard fields:** `name`, `email`, `phone`, `org` (current company), `urls` (LinkedIn, GitHub, etc.)
- **Resume:** File upload via multipart (only supported in multipart mode, not JSON)
- **Custom questions:** NOT supported via public API; only available through browser forms
- **Note:** Lever deduplicates candidates by email — important for testing
- **Rate limit:** Max 2 POST/sec on API; browser should respect similar cadence
- **Submit button:** Typically `<button type="submit">Submit application</button>` or similar

### Ashby
- **Application form URL:** `https://jobs.ashbyhq.com/{slug}/{posting_id}/application`
- **Standard fields:** `_systemfield_name`, `_systemfield_email`, `_systemfield_phone`, `_systemfield_location`
- **Field types:** Short answer, long answer, phone, email, multiple choice, checkboxes, date picker, yes/no, number, resume upload, file upload, candidate location
- **Custom questions:** Each has a `path` property identifying it; field definitions available via `jobPosting.info` API endpoint
- **File size:** Up to 50MB per file field
- **Form embed:** Uses JavaScript embed script (version=2 from jobs.ashbyhq.com)
- **API alternative:** POST to `api.ashbyhq.com/applicationForm.submit` with multipart/form-data

## Schema Design

### New Tables (Alembic migration 0006)

```python
# app/learning/models.py

class SavedAnswer(SQLModel, table=True):
    """A user-provided answer to a previously unknown form field."""
    __tablename__ = "saved_answers"

    id: Optional[int] = Field(default=None, primary_key=True)
    field_label: str = Field(index=True)        # original field label text
    field_label_normalized: str = Field()         # lowercase, stripped
    answer_text: str = Field()                    # user's answer
    answer_type: str = Field(default="text")      # text | select | checkbox | file
    source_job_id: Optional[int] = Field(default=None, foreign_key="jobs.id")  # first job that triggered this
    times_reused: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class UnknownField(SQLModel, table=True):
    """An unknown form field encountered during Playwright submission."""
    __tablename__ = "unknown_fields"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    field_label: str = Field()
    field_type: str = Field(default="text")       # text | select | checkbox | file | radio
    field_options: Optional[str] = Field(default=None)  # JSON array of options for select/radio
    screenshot_path: Optional[str] = Field(default=None)
    page_number: int = Field(default=1)            # which form step
    is_required: bool = Field(default=False)
    resolved: bool = Field(default=False)           # user has provided an answer
    saved_answer_id: Optional[int] = Field(default=None, foreign_key="saved_answers.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### New Settings Columns
```python
# Added to Settings model
playwright_headless: bool = Field(default=True)       # headless vs headed toggle
pause_if_unsure: bool = Field(default=True)            # halt on unknown fields vs always advance
screenshot_retention_days: int = Field(default=30)     # auto-cleanup threshold
```

### State Machine Extensions
The existing `needs_info` status (from Phase 5) already covers the "halted on unknown fields" case. No new statuses needed. Transitions:
- `approved -> needs_info` (unknown fields found, pause_if_unsure=True)
- `needs_info -> approved` (user answered all unknowns, retry queued)
- `approved -> submitted` (Playwright form submission succeeded)
- `approved -> failed` (Playwright error, timeout, etc.)

## Discretionary Recommendations

### Label-Matching Heuristic Priority Order
Recommended order (highest priority first):
1. **Exact known fields** — `first_name`, `last_name`, `email`, `phone` (these appear on virtually every form)
2. **Compound name** — `full_name` when only one name field exists
3. **URLs** — `linkedin`, `github`, `portfolio`/`website`
4. **File uploads** — `resume`/`cv`, `cover letter`
5. **Work eligibility** — `work authorization`, `legally authorized`, `sponsorship`
6. **Compensation** — `salary`, `compensation`, `pay`
7. **Experience** — `years of experience`, `experience level`
8. **Location** — `location`, `city`, `address`, `zip`

Use case-insensitive regex matching. Profile field `full_name` is split into first/last when the form has separate fields (use `profile.full_name.split()` heuristic).

### Generic ATS Form Selector Strategy
For forms outside Greenhouse/Lever/Ashby, use a progressive detection approach:
1. Look for `<form>` elements containing file upload inputs (likely application forms)
2. Look for `role="form"` or `aria-label` containing "application" or "apply"
3. Look for visible `<form>` elements with 3+ input fields
4. If multiple forms found, prefer the one with a file input (resume upload signals an application form)
5. Fall back to the largest visible form on the page

### Screenshot Storage Format and Retention
- **Format:** PNG (Playwright default; lossless; typically 100-500KB per screenshot)
- **Storage path:** `data/screenshots/{job_id}/step_{N}.png` and `data/screenshots/{job_id}/error.png`
- **Retention:** 30 days (configurable via Settings.screenshot_retention_days). Cleanup runs as a post-pipeline task. Screenshots for jobs in `needs_info` status are exempt from cleanup until resolved.
- **Audit trail:** Submission row stores `screenshot_paths` as a JSON list of relative paths

### CAPTCHA vs 2FA vs Other Blocking Detection
Check in this order:
1. **reCAPTCHA:** `iframe[src*="recaptcha"]` or `div.g-recaptcha`
2. **hCaptcha:** `iframe[src*="hcaptcha"]` or `div.h-captcha`
3. **Cloudflare Turnstile:** `iframe[src*="challenges.cloudflare.com"]` or `#challenge-running`
4. **Generic CAPTCHA:** Any element with class/id containing "captcha" (case-insensitive)
5. **2FA/MFA:** Input fields with name/placeholder containing "otp", "verification", "2fa", "mfa", "authenticator"
6. **Login wall:** The form page redirected to a login page (check URL for "/login", "/signin", "/sso")
All detections: screenshot the page, mark the job as `needs_info` with `reason="captcha"` or `reason="2fa"` or `reason="login_required"`.

### Playwright Page Timeout Values
- **Default action timeout:** 30,000ms (30s) — covers fill, click, select operations
- **Navigation timeout:** 60,000ms (60s) — covers goto, reload, wait_for_load_state
- **Network idle wait:** 10,000ms (10s) — after navigation, wait for network to settle
- **Form submission wait:** 30,000ms (30s) — after clicking submit, wait for response/redirect
- **Between form steps:** 2,000ms (2s) — brief pause after advancing to let the next page render

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Selenium WebDriver | Playwright (auto-wait, auto-retry locators) | 2020+ | No need for explicit waits on most operations; Playwright auto-waits for elements to be actionable |
| CSS selectors only | get_by_label / get_by_role semantic locators | Playwright 1.20+ | Label-based matching aligns perfectly with the user's heuristic decision |
| Manual cookie management | storageState JSON save/load | Playwright 1.15+ | One-liner persistence of entire auth state |
| Separate browser binary install | Pre-bundled in Docker base image | Phase 1 decision | Zero additional setup; browsers already installed in mcr.microsoft.com/playwright/python:v1.58.0-noble |

## Open Questions

1. **Greenhouse iframe vs direct URL**
   - What we know: Many companies embed Greenhouse forms in iframes on their own career pages. The direct URL (boards.greenhouse.io) bypasses the iframe.
   - What's unclear: For jobs discovered via the Greenhouse API (Phase 3), do we always have the direct boards.greenhouse.io URL, or do some `job.url` values point to the company's career page?
   - Recommendation: Check `job.url` — if it contains `boards.greenhouse.io`, use directly. Otherwise, construct the direct URL from `job.company` (slug) and `job.external_id`. The construction pattern is reliable for Greenhouse.

2. **LLM cost for semantic matching at scale**
   - What we know: Each unknown field requires an LLM call to check against saved answers. With many saved answers and many jobs, this could add up.
   - What's unclear: How many unique unknown field labels will users encounter in practice? The matching prompt is very short (~100 tokens in, ~10 tokens out), so cost per call is minimal.
   - Recommendation: Batch all unknown fields from a single form into one LLM call (send all field labels + all saved answer labels in one prompt). This reduces calls from O(fields * answers) to O(1) per form. Budget cost through existing BudgetGuard.

3. **SubmissionContext extension for Playwright**
   - What we know: The current SubmissionContext carries SMTP-specific fields (smtp_creds, recipient_email, subject, body_text). PlaywrightStrategy ignores these.
   - What's unclear: Should SubmissionContext be extended with Playwright-specific fields (browser_manager, headless setting), or should PlaywrightStrategy manage its own context?
   - Recommendation: Keep SubmissionContext unchanged. PlaywrightStrategy receives browser_manager and settings as constructor args or module-level singletons, not through SubmissionContext. The strategy already has access to `ctx.job` and `ctx.tailored_resume_path` which are the essential inputs.

4. **Retry semantics for needs_info -> approved -> submitted**
   - What we know: User answers unknowns, job flips back to `approved`, and "immediate retry" is locked. The existing pipeline drain loop picks up `approved` jobs.
   - What's unclear: Should the immediate retry be a dedicated endpoint that triggers a single-job Playwright submission, or should it re-run the full pipeline?
   - Recommendation: Dedicated POST `/needs-info/{job_id}/retry` endpoint that triggers a single-job Playwright submission inline (not via the scheduler). This gives instant feedback per the user decision. The pipeline's regular drain loop serves as the fallback if the immediate retry fails.

## Sources

### Primary (HIGH confidence)
- Playwright Python official docs — authentication (storageState): https://playwright.dev/python/docs/auth
- Playwright Python official docs — input actions (fill, select, upload): https://playwright.dev/python/docs/input
- Playwright Python official docs — BrowserContext API: https://playwright.dev/python/docs/api/class-browsercontext
- Playwright Python official docs — screenshots: https://playwright.dev/python/docs/screenshots
- Greenhouse Job Board API — application submission: https://developers.greenhouse.io/job-board.html
- Greenhouse API docs (GitHub): https://github.com/grnhse/greenhouse-api-docs/blob/master/source/includes/job-board/_applications.md
- Lever Postings API: https://github.com/lever/postings-api/blob/master/README.md
- Ashby applicationForm.submit API: https://developers.ashbyhq.com/reference/applicationformsubmit

### Secondary (MEDIUM confidence)
- Apify form automation guide (practical patterns): https://blog.apify.com/playwright-how-to-automate-forms/
- BrowserStack persistent context guide: https://www.browserstack.com/guide/playwright-persistent-context
- Oxylabs CAPTCHA bypass guide (detection selectors): https://oxylabs.io/blog/playwright-bypass-captcha

### Tertiary (LOW confidence)
- Greenhouse/Lever/Ashby form HTML selectors — need live form inspection to confirm exact selectors. The API docs describe field names, but browser form DOM structure may differ from API field names. Validate during implementation with headed browser inspection.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Playwright already in Docker image, all libraries confirmed
- Architecture: MEDIUM — Strategy Protocol integration point is well-defined from Phase 5; form filler patterns are sound but ATS-specific selectors need live validation
- Pitfalls: MEDIUM — Event loop, iframe, and dynamic form pitfalls are well-documented; CAPTCHA detection patterns are reasonable but not exhaustively verified
- Learning loop: MEDIUM — Schema design is straightforward; LLM matching pattern uses existing infrastructure; batching optimization needs validation
- ATS form details: LOW — Field names from API docs, but browser form DOM structure may differ; live inspection recommended during implementation

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (30 days — Playwright is stable; ATS form structures change infrequently)
