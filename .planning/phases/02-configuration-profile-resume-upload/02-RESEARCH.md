# Phase 2: Configuration, Profile & Resume Upload - Research

**Researched:** 2026-04-11
**Domain:** Web UI (HTMX/Pico.css), file upload, DOCX parsing, credential validation, SQLAlchemy schema evolution
**Confidence:** HIGH

## Summary

Phase 2 transforms the existing flat `/settings` page into a sidebar-navigated settings hub and adds seven new configuration surfaces: profile, resume upload, keywords, credentials with validation, schedule/quiet hours, match threshold, budget cap, and mode toggle. The existing Phase 1 settings (rate limits, secrets, kill-switch, dry-run) must be folded into this sidebar as additional sections.

The implementation uses the existing stack (FastAPI + HTMX + Pico.css + SQLAlchemy async) with one new dependency: `python-docx` for DOCX text extraction. All new data lives in expanded `Settings` columns plus a new `Profile` model. File storage goes to `/data/resumes/` on the host-mounted volume. Each sidebar section saves independently via HTMX POST returning a partial with inline success/error flash.

**Primary recommendation:** Extend the Settings singleton with new columns via Alembic migration, add a Profile table, store the DOCX file on disk under `/data/resumes/`, and use `python-docx` for text extraction. The sidebar is pure CSS (flexbox with `<aside>` + `<main>`) with HTMX `hx-get` loading section content into the right pane.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Sidebar layout: one `/settings` page with left sidebar, content area on right
- Merge Phase 1 settings into sidebar as additional sections
- Top nav stays minimal: Dashboard, Settings
- Each section has its own Save button; saves via HTMX with inline success/error flash, no page reload
- Profile: three groups (Contact, Work Details, Links), all fields optional, collapsible sub-sections
- Resume: upload + basic preview with extracted text/headings, drag-and-drop + file picker, filename/date/replace
- Keywords: tag-style chips, Enter to add, X to remove
- Claude API key: validate on save via lightweight API call
- SMTP credentials: validate on save via SMTP connection attempt
- Credentials display: "Configured checkmark" or "Not set" only, no reveal/masked values
- Schedule: time range slider for quiet hours, enable/disable toggle
- Match threshold: slider with descriptive labels (Loose/Moderate/Strict), percentage displayed
- Budget cap: dollar input, usage progress bar ($X / $Y)
- Mode toggle: full-auto vs review-queue at top of sidebar

### Claude's Discretion
- SMTP field layout approach (provider presets vs explicit fields)
- Exact sidebar section ordering
- Slider implementation details (quiet hours and threshold)
- Success/error flash styling and duration
- Resume text extraction depth (headings only vs full content preview)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

### Core (already installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.135.3 | Route handlers, file upload via `UploadFile` | Already in stack |
| HTMX | 2.0.3 | Partial page updates, inline saves | Already in stack |
| Pico.css | v2 (bundled) | Semantic HTML styling, form elements | Already in stack |
| SQLAlchemy async | 2.0.36 | Database models and queries | Already in stack |
| Alembic | 1.14.0 | Schema migrations | Already in stack |
| python-multipart | 0.0.17 | Multipart form data parsing for file uploads | Already in stack |
| httpx | 0.28.1 | Async HTTP client for API key validation | Already in stack |
| cryptography | 44.0.0 | Fernet encryption for secrets | Already in stack |

### New Dependency
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-docx | 1.2.0 | Extract text and headings from DOCX files | De facto standard for DOCX manipulation in Python, pure Python, no system dependencies |

### Not Needed
| Instead of | Don't Use | Reason |
|------------|-----------|--------|
| python-docx | docx2python, docxpy | python-docx is the most mature, best documented; we only need paragraph iteration |
| Custom slider JS lib | noUiSlider, ion.rangeSlider | HTML5 `<input type="range">` with `oninput` + Pico.css styling is sufficient |
| Custom chip/tag JS lib | Tagify, Choices.js | HTMX `hx-trigger="keyup[key=='Enter']"` + server-rendered chips is simpler and aligns with hypermedia approach |

**Installation (addition to requirements.txt):**
```bash
python-docx==1.2.0
```

## Architecture Patterns

### Recommended Project Structure (new/modified files)
```
app/
├── db/
│   ├── models.py              # Add Profile model, extend Settings with new columns
│   └── migrations/versions/
│       └── 0002_phase2_config.py  # Alembic migration for new columns + profile table
├── settings/
│   └── service.py             # Extend with bulk-set, profile CRUD
├── resume/
│   ├── __init__.py
│   └── service.py             # DOCX upload, storage, text extraction
├── credentials/
│   ├── __init__.py
│   └── validation.py          # Anthropic API key + SMTP connection validation
├── web/
│   ├── routers/
│   │   └── settings.py        # Refactor: sidebar hub + section endpoints
│   ├── templates/
│   │   ├── settings.html.j2   # Rewrite: sidebar layout shell
│   │   └── partials/
│   │       ├── settings_sidebar.html.j2
│   │       ├── settings_mode.html.j2
│   │       ├── settings_profile.html.j2
│   │       ├── settings_resume.html.j2
│   │       ├── settings_keywords.html.j2
│   │       ├── settings_credentials.html.j2
│   │       ├── settings_threshold.html.j2
│   │       ├── settings_schedule.html.j2
│   │       ├── settings_budget.html.j2
│   │       ├── settings_limits.html.j2
│   │       ├── settings_safety.html.j2
│   │       └── flash_message.html.j2
│   └── static/
│       └── app.css            # Extend with sidebar, chip, slider, flash styles
```

### Pattern 1: Sidebar with HTMX Section Loading
**What:** Left sidebar with section links; clicking a link loads that section's partial into the right content area.
**When to use:** Single settings page with many sections.

```html
<!-- settings.html.j2 -->
<div class="settings-layout">
  <aside class="settings-sidebar">
    <nav>
      <ul>
        <li><a href="#" hx-get="/settings/section/mode" hx-target="#settings-content"
               hx-push-url="false" class="active">Mode</a></li>
        <li><a href="#" hx-get="/settings/section/profile" hx-target="#settings-content"
               hx-push-url="false">Profile</a></li>
        <!-- ... more sections -->
      </ul>
    </nav>
  </aside>
  <div id="settings-content" class="settings-content">
    {% include "partials/settings_mode.html.j2" %}
  </div>
</div>
```

**CSS for sidebar layout (Pico.css compatible):**
```css
.settings-layout {
  display: flex;
  gap: 2rem;
  min-height: 60vh;
}
.settings-sidebar {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--pico-muted-border-color);
  padding-right: 1rem;
}
.settings-sidebar nav ul {
  list-style: none;
  padding: 0;
}
.settings-sidebar nav a {
  display: block;
  padding: 0.5rem 0.75rem;
  border-radius: 0.25rem;
  text-decoration: none;
}
.settings-sidebar nav a.active {
  background: var(--pico-primary-background);
  color: var(--pico-primary-inverse);
}
.settings-content {
  flex: 1;
  min-width: 0;
}
```

### Pattern 2: HTMX Inline Save with Flash
**What:** Each section form POSTs via HTMX, server returns the updated section partial with a flash message.
**When to use:** Every settings section save.

```html
<!-- Example: threshold section partial -->
<form hx-post="/settings/threshold" hx-target="#settings-content" hx-swap="innerHTML">
  <label>
    Match Threshold
    <input type="range" name="match_threshold" min="0" max="100" value="{{ settings.match_threshold }}"
           oninput="this.nextElementSibling.textContent = this.value + '%'">
    <output>{{ settings.match_threshold }}%</output>
  </label>
  <div class="threshold-labels">
    <span>Loose (30%)</span><span>Moderate (60%)</span><span>Strict (85%)</span>
  </div>
  <button type="submit">Save</button>
</form>
{% if flash %}
<div class="flash flash-{{ flash.type }}" role="alert">{{ flash.message }}</div>
{% endif %}
```

**Server pattern:**
```python
@router.post("/settings/threshold")
async def save_threshold(
    request: Request,
    match_threshold: int = Form(...),
    session=Depends(get_session),
):
    if not 0 <= match_threshold <= 100:
        return _render_section(request, session, "threshold", flash=("error", "Must be 0-100"))
    await set_setting(session, "match_threshold", match_threshold)
    return _render_section(request, session, "threshold", flash=("success", "Threshold saved"))
```

### Pattern 3: HTMX Keyword Chips
**What:** Input field with `hx-trigger="keyup[key=='Enter']"` adds a keyword chip server-side.
**When to use:** Keyword management.

```html
<div id="keywords-section">
  <div class="chips">
    {% for kw in keywords %}
    <span class="chip">
      {{ kw }}
      <button hx-delete="/settings/keywords/{{ kw|urlencode }}"
              hx-target="#keywords-section" hx-swap="outerHTML"
              class="chip-remove" aria-label="Remove {{ kw }}">&times;</button>
    </span>
    {% endfor %}
  </div>
  <input type="text" name="keyword" placeholder="Type keyword, press Enter"
         hx-post="/settings/keywords"
         hx-trigger="keyup[key=='Enter']"
         hx-target="#keywords-section"
         hx-swap="outerHTML"
         hx-include="this"
         autocomplete="off">
</div>
```

### Pattern 4: File Upload with HTMX
**What:** DOCX upload via HTMX multipart POST, returns preview partial.
**When to use:** Resume upload.

```html
<form hx-post="/settings/resume" hx-target="#resume-section" hx-swap="outerHTML"
      hx-encoding="multipart/form-data">
  <input type="file" name="resume" accept=".docx"
         onchange="this.form.requestSubmit()">
  <button type="submit">Upload Resume</button>
</form>

<!-- Drag-and-drop zone (vanilla JS, triggers same form) -->
<div id="drop-zone" class="drop-zone">
  Drop your .docx file here
</div>
```

### Anti-Patterns to Avoid
- **Don't store DOCX content in the database:** Binary files belong on the filesystem (`/data/resumes/`). Store only the filename and upload timestamp in the Settings row.
- **Don't validate all fields on profile save:** All profile fields are optional per user decision. Only validate format where it matters (email format if provided, phone format if provided).
- **Don't use SPA-style client routing:** HTMX partial loading is sufficient. No need for `hx-push-url` on sidebar clicks since it is all one `/settings` page.
- **Don't make credential validation blocking on save:** Save the credential first, then validate async. If validation fails, show a warning but keep the saved value.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DOCX text extraction | Custom XML parser for .docx ZIP | `python-docx` Document().paragraphs | DOCX is complex XML; python-docx handles styles, headings, edge cases |
| File upload handling | Manual multipart parsing | FastAPI `UploadFile` + `shutil.copyfileobj` | Already in stack via python-multipart; handles spooled temp files |
| Fernet encryption | Any custom encryption | Existing `FernetVault` | Already built and tested in Phase 1 |
| Slider UI | Custom JS slider widget | HTML5 `<input type="range">` + `oninput` | Native element, Pico.css styles it, works everywhere |
| Tag/chip input | Full JS tag library | HTMX `keyup[key=='Enter']` trigger + server chips | Hypermedia approach is simpler, no JS dependency |

## Common Pitfalls

### Pitfall 1: Settings Model Migration Complexity
**What goes wrong:** Adding many columns to the Settings singleton requires careful Alembic migration with `server_default` values for SQLite (which cannot add columns without defaults in some ALTER TABLE scenarios).
**Why it happens:** SQLite ALTER TABLE is limited compared to PostgreSQL.
**How to avoid:** Always provide `server_default` on new columns in the migration. Use `op.add_column("settings", sa.Column("match_threshold", sa.Integer(), server_default=sa.text("60")))` pattern.
**Warning signs:** Migration fails with "Cannot add a NOT NULL column with default value NULL."

### Pitfall 2: HTMX Form Encoding for File Upload
**What goes wrong:** File upload via HTMX fails silently because the default encoding is `application/x-www-form-urlencoded`, not `multipart/form-data`.
**Why it happens:** HTMX does not auto-detect file inputs.
**How to avoid:** Explicitly set `hx-encoding="multipart/form-data"` on the form element.
**Warning signs:** Server receives empty file, `UploadFile.size == 0`.

### Pitfall 3: Starlette TemplateResponse Positional Form
**What goes wrong:** `TemplateResponse(request, name, ctx)` must use positional args per Phase 1 findings.
**Why it happens:** Kwarg form `{"request": request}` breaks Jinja LRU cache (unhashable dict).
**How to avoid:** Always use positional: `templates.TemplateResponse(request, "partials/settings_profile.html.j2", {"profile": profile, "flash": flash})`.
**Warning signs:** Template caching stops working, performance degrades.

### Pitfall 4: Anthropic API Key Validation Consuming Tokens
**What goes wrong:** Using the `/v1/messages` endpoint to test the key sends a real request and costs tokens.
**Why it happens:** Developer picks the first documented endpoint.
**How to avoid:** Use `GET /v1/models` endpoint instead -- it is read-only, requires only a valid API key, and consumes zero tokens. Send `httpx.AsyncClient.get("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})`. A 200 means valid, 401 means invalid.
**Warning signs:** Unexpected API charges from settings page saves.

### Pitfall 5: SMTP Validation Timeout
**What goes wrong:** SMTP connection attempt hangs for 30+ seconds on wrong host/port, making the save feel broken.
**Why it happens:** Default socket timeout is very long.
**How to avoid:** Use `smtplib.SMTP(host, port, timeout=5)` with a short timeout. Wrap in try/except for `socket.timeout`, `SMTPAuthenticationError`, `ConnectionRefusedError`. Run validation in a thread pool (`asyncio.to_thread`) since smtplib is synchronous.
**Warning signs:** Save button appears to hang; no flash appears for 30+ seconds.

### Pitfall 6: Keywords Storage Migration
**What goes wrong:** Phase 1 stores keywords as `keywords_csv` (comma-separated string). Phase 2 wants chip-based add/remove. CSV manipulation for add/remove is error-prone (escaping, duplicates, ordering).
**Why it happens:** Phase 1 kept it simple for the wizard.
**How to avoid:** Keep using `keywords_csv` but treat it as a pipe-delimited or comma-delimited set. Parse to list on read, join on write. A dedicated keywords table is over-engineering for a single-user app with likely <50 keywords. The service layer handles dedup and trimming.
**Warning signs:** Keywords with commas in them break parsing. Use a delimiter unlikely to appear in keywords (pipe `|` is safer than comma).

### Pitfall 7: Resume File Persistence Across Container Restarts
**What goes wrong:** File uploaded but lost on container restart.
**Why it happens:** File saved inside the container filesystem instead of the mounted volume.
**How to avoid:** Save to `/data/resumes/base_resume.docx` which is on the host-mounted `./data` volume. The compose.yml already maps `./data:/data`.
**Warning signs:** Resume shows "not uploaded" after `docker compose restart`.

### Pitfall 8: Drag-and-Drop Requires JavaScript
**What goes wrong:** Developer assumes HTMX can handle drag-and-drop natively.
**Why it happens:** HTMX does not have built-in drag-and-drop file support.
**How to avoid:** Write a small vanilla JS snippet (15-20 lines) that listens for `dragover`/`drop` events on a drop zone, extracts the file, and submits it via the HTMX form. The JS sets the file input's files and triggers form submit.
**Warning signs:** Drop zone does nothing when file is dropped.

## Code Examples

### DOCX Text Extraction with python-docx
```python
# Source: python-docx 1.2.0 docs
from docx import Document

def extract_resume_text(file_path: str) -> dict:
    """Extract text and headings from a DOCX file."""
    doc = Document(file_path)
    sections = []
    current_heading = None
    current_text = []

    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            if current_heading or current_text:
                sections.append({"heading": current_heading, "text": "\n".join(current_text)})
            current_heading = para.text
            current_text = []
        elif para.text.strip():
            current_text.append(para.text)

    if current_heading or current_text:
        sections.append({"heading": current_heading, "text": "\n".join(current_text)})

    return {
        "full_text": "\n".join(p.text for p in doc.paragraphs if p.text.strip()),
        "sections": sections,
    }
```

### Anthropic API Key Validation
```python
# Source: Anthropic API docs - GET /v1/models is zero-cost
import httpx

async def validate_anthropic_key(api_key: str) -> tuple[bool, str]:
    """Validate an Anthropic API key without consuming tokens."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        if resp.status_code == 200:
            return True, "API key is valid"
        elif resp.status_code == 401:
            return False, "Invalid API key"
        else:
            return False, f"Unexpected response: {resp.status_code}"
    except httpx.TimeoutException:
        return False, "Validation timed out"
    except httpx.ConnectError:
        return False, "Could not reach Anthropic API"
```

### SMTP Credential Validation
```python
# Source: Python smtplib docs
import asyncio
import smtplib
import socket

async def validate_smtp_credentials(
    host: str, port: int, username: str, password: str
) -> tuple[bool, str]:
    """Validate SMTP credentials without sending email. Runs in thread pool."""
    def _check():
        try:
            with smtplib.SMTP(host, int(port), timeout=5) as server:
                server.ehlo()
                if port == 587:
                    server.starttls()
                    server.ehlo()
                server.login(username, password)
                return True, "SMTP credentials valid"
        except smtplib.SMTPAuthenticationError:
            return False, "Authentication failed"
        except (socket.timeout, TimeoutError):
            return False, "Connection timed out"
        except (ConnectionRefusedError, OSError) as e:
            return False, f"Connection failed: {e}"

    return await asyncio.to_thread(_check)
```

### FastAPI File Upload to Disk
```python
# Source: FastAPI docs - Request Files
import shutil
from pathlib import Path
from fastapi import UploadFile

RESUME_DIR = Path("/data/resumes")

async def save_resume(file: UploadFile) -> Path:
    """Save uploaded DOCX to persistent volume."""
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESUME_DIR / "base_resume.docx"
    with open(dest, "wb") as buf:
        shutil.copyfileobj(file.file, buf)
    return dest
```

### Alembic Migration Pattern for New Settings Columns
```python
# Source: Alembic docs + Phase 1 migration pattern
def upgrade() -> None:
    # Settings table: add Phase 2 columns with server_default (SQLite requirement)
    op.add_column("settings", sa.Column("match_threshold", sa.Integer(),
                  server_default=sa.text("60"), nullable=False))
    op.add_column("settings", sa.Column("schedule_enabled", sa.Boolean(),
                  server_default=sa.false(), nullable=False))
    op.add_column("settings", sa.Column("quiet_hours_start", sa.Integer(),
                  server_default=sa.text("22"), nullable=False))  # 10 PM
    op.add_column("settings", sa.Column("quiet_hours_end", sa.Integer(),
                  server_default=sa.text("7"), nullable=False))   # 7 AM
    op.add_column("settings", sa.Column("budget_cap_dollars", sa.Float(),
                  server_default=sa.text("0"), nullable=False))    # 0 = no cap
    op.add_column("settings", sa.Column("budget_spent_dollars", sa.Float(),
                  server_default=sa.text("0"), nullable=False))
    op.add_column("settings", sa.Column("auto_mode", sa.Boolean(),
                  server_default=sa.true(), nullable=False))       # full-auto default
    op.add_column("settings", sa.Column("resume_filename", sa.String(),
                  server_default=sa.text("''"), nullable=True))
    op.add_column("settings", sa.Column("resume_uploaded_at", sa.DateTime(),
                  nullable=True))

    # Profile table: separate from settings for cleaner modeling
    op.create_table(
        "profile",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        # Contact
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        # Work Details
        sa.Column("work_authorization", sa.String(), nullable=True),
        sa.Column("salary_expectation", sa.String(), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        # Links
        sa.Column("linkedin_url", sa.String(), nullable=True),
        sa.Column("github_url", sa.String(), nullable=True),
        sa.Column("portfolio_url", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.current_timestamp()),
    )
```

## Discretion Recommendations

### SMTP Field Layout: All-Fields-Visible (RECOMMENDED)
**Recommendation:** Show all SMTP fields explicitly (host, port, username, password) rather than provider presets.
**Reasoning:** Provider presets add complexity (preset data, edge cases for custom providers) with little value for a single-user app. The user knows their SMTP server. Four fields is not overwhelming. This is also more transparent -- the user sees exactly what is configured.

### Sidebar Section Ordering (RECOMMENDED)
```
1. Mode (full-auto / review-queue) — most consequential, per user decision
2. Profile
3. Resume
4. Keywords
5. Match Threshold
6. Credentials (API Key + SMTP)
7. Schedule & Quiet Hours
8. Budget Cap
9. Rate Limits (Phase 1 settings)
10. Safety (Kill Switch + Dry Run from Phase 1)
```
**Reasoning:** Ordered by frequency of use and consequence. Mode at top per user decision. Profile/Resume/Keywords are the core inputs users set up first. Rate limits and safety toggles are "set and forget" so they go last.

### Slider Implementation: HTML5 Range with oninput (RECOMMENDED)
**For match threshold:** `<input type="range" min="0" max="100" step="5">` with an `<output>` element updated via `oninput`. Descriptive labels are static text positioned below the slider with CSS flexbox.
**For quiet hours:** Two `<input type="range">` elements (start hour 0-23, end hour 0-23) with `<output>` showing formatted time (e.g., "10:00 PM"). This is simpler than a dual-handle slider which would require a JS library.
**Reasoning:** Native HTML5 range inputs are styled by Pico.css, work on mobile, need zero JS libraries. Two separate range inputs for quiet hours avoids a dual-range slider dependency.

### Flash Styling and Duration (RECOMMENDED)
**Style:** Green left-border for success, red left-border for error (matching existing `.warning-banner` pattern).
**Duration:** Auto-dismiss after 3 seconds using HTMX `hx-swap="innerHTML settle:3s"` or a simple CSS animation + `setTimeout` to remove.
```css
.flash-success { border-left: 4px solid #2a9d8f; background: #f0fff4; padding: 0.75rem 1rem; margin: 1rem 0; }
.flash-error   { border-left: 4px solid #e76f51; background: #fff3f0; padding: 0.75rem 1rem; margin: 1rem 0; }
```

### Resume Text Extraction Depth: Full Content Preview (RECOMMENDED)
**Recommendation:** Show headings as bold section labels with body text beneath them, capped at ~500 lines. This gives the user enough to confirm the parser read their resume correctly.
**Reasoning:** Headings-only would not let the user verify that bullet points, skills lists, and descriptions were captured. Full content (truncated) is more reassuring.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| python-docx 0.8.x | python-docx 1.2.0 | 2024 | New API for styles, better type hints |
| Custom slider libraries | HTML5 range + oninput | Stable | No JS dependency needed for basic sliders |
| Full SPA for settings | HTMX partial loading | HTMX 2.0 | Server-rendered sections, no client state |

## Open Questions

1. **Keywords delimiter**
   - What we know: Phase 1 uses `keywords_csv` with comma separator. Commas in keywords (e.g., "machine learning, AI") could break parsing.
   - Recommendation: Switch to pipe `|` delimiter in the migration, or better, use JSON array stored as text. JSON is safest since `json.dumps/loads` handles all edge cases.

2. **Budget tracking granularity**
   - What we know: `budget_spent_dollars` is a float column. Phase 4 will increment it.
   - What's unclear: Whether to track per-month or all-time. The column name says "monthly" but resets need to happen.
   - Recommendation: Store as monthly with a `budget_month` string column (e.g., "2026-04"). Phase 4 resets when the month changes.

3. **Quiet hours representation**
   - What we know: User wants a time range slider (e.g., 10 PM - 7 AM).
   - What's unclear: Whether to store as hour integers (22, 7) or full datetime/time.
   - Recommendation: Store as two integer columns `quiet_hours_start` (0-23) and `quiet_hours_end` (0-23). The scheduler interprets the range, handling the wrap-around case (start > end means overnight).

## Sources

### Primary (HIGH confidence)
- Existing codebase: `app/db/models.py`, `app/settings/service.py`, `app/security/fernet.py`, `app/web/routers/settings.py` -- direct inspection of Phase 1 patterns
- FastAPI official docs: Request Files (file upload via UploadFile)
- python-docx 1.2.0 official docs: Document API, paragraph iteration, style names
- Anthropic API docs: GET /v1/models endpoint for zero-cost key validation

### Secondary (MEDIUM confidence)
- HTMX docs: `hx-trigger="keyup[key=='Enter']"` for chip input, `hx-encoding` for file upload
- Pico.css docs: `<aside>` for vertical nav, `.grid` class for layout
- Python smtplib docs: `login()` for credential validation without sending

### Tertiary (LOW confidence)
- Pico.css sidebar layout: community discussions suggest flexbox `<aside>` + `<main>` approach (no official sidebar component)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all existing dependencies known, only python-docx is new
- Architecture: HIGH -- sidebar+HTMX partial pattern is well-established, codebase patterns are clear
- Pitfalls: HIGH -- identified from direct code inspection and known SQLite/HTMX limitations
- Credential validation: MEDIUM -- Anthropic /v1/models endpoint confirmed by multiple sources but not tested firsthand

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (stable stack, no fast-moving dependencies)
