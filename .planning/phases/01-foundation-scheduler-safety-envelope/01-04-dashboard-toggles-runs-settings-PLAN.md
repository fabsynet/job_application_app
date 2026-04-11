---
phase: 01-foundation-scheduler-safety-envelope
plan: 04
type: execute
wave: 3
depends_on: ["01-03"]
files_modified:
  - app/main.py
  - app/web/deps.py
  - app/web/routers/dashboard.py
  - app/web/routers/toggles.py
  - app/web/routers/runs.py
  - app/web/routers/settings.py
  - app/web/templates/base.html.j2
  - app/web/templates/dashboard.html.j2
  - app/web/templates/runs_list.html.j2
  - app/web/templates/run_detail.html.j2
  - app/web/templates/settings.html.j2
  - app/web/templates/partials/status_pill.html.j2
  - app/web/templates/partials/next_run.html.j2
  - app/web/templates/partials/toggles.html.j2
  - app/web/templates/partials/runs_rows.html.j2
  - app/web/templates/partials/secrets_list.html.j2
  - app/web/static/pico.min.css
  - app/web/static/app.css
  - tests/integration/test_dashboard_routes.py
  - tests/integration/test_toggles_routes.py
  - tests/integration/test_settings_routes.py
autonomous: true

must_haves:
  truths:
    - "Home page (/) renders a live status dashboard showing scheduler state, next run time, last run outcome, and counts from the last run"
    - "Kill-switch and dry-run are one-click toggles on the home page that write to the Settings row and take effect on the next scheduled run (kill switch cancels in-flight run immediately)"
    - "Runs list (/runs) shows the 50 most recent runs with HTMX 'show more' affordance; detail view (/runs/{id}) shows counts JSON"
    - "Settings page (/settings) lets the user save an encrypted secret (via FernetVault) and configure daily_cap, delay range, timezone — values persist across restart"
    - "HTMX polling (status pill every 5s, next run every 15s) refreshes dashboard without a full reload and pauses when the tab is hidden"
  artifacts:
    - path: "app/web/routers/dashboard.py"
      provides: "GET /, GET /fragments/status, GET /fragments/next-run, POST /runs/trigger"
      exports: ["router"]
    - path: "app/web/routers/toggles.py"
      provides: "POST /toggles/kill-switch, POST /toggles/dry-run returning toggles partial"
      exports: ["router"]
    - path: "app/web/routers/runs.py"
      provides: "GET /runs (last 50), GET /runs?offset=N (partial), GET /runs/{id}"
      exports: ["router"]
    - path: "app/web/routers/settings.py"
      provides: "GET /settings, POST /settings/secrets, DELETE /settings/secrets/{name}, POST /settings/limits"
      exports: ["router"]
    - path: "app/web/templates/dashboard.html.j2"
      provides: "Live status dashboard layout with toggles, counts, recent runs table"
    - path: "app/web/static/pico.min.css"
      provides: "Pico.css v2.x classless stylesheet"
      min_lines: 1
  key_links:
    - from: "app/web/routers/toggles.py POST /toggles/kill-switch"
      to: "app.state.killswitch.engage"
      via: "router handler calls killswitch.engage(scheduler_service, session)"
      pattern: "killswitch\\.engage"
    - from: "app/web/templates/dashboard.html.j2"
      to: "GET /fragments/status"
      via: "hx-get with hx-trigger every 5s document.hidden false"
      pattern: "hx-trigger=\"every 5s"
    - from: "app/web/routers/settings.py POST /settings/secrets"
      to: "FernetVault.encrypt + Secret table insert"
      via: "vault.encrypt(plaintext) then upsert Secret(name, ciphertext)"
      pattern: "vault\\.encrypt"
---

<objective>
Ship the Phase 1 landing surface: the live status dashboard with kill-switch + dry-run toggles (one click away per CONTEXT.md), runs list + detail, and a settings page that writes encrypted secrets via FernetVault and configures the rate-limit envelope. Uses HTMX + Jinja2 + Pico.css per RESEARCH.md — no JS build, no SPA.

Purpose: The scheduler primitives from plan 01-03 need a control surface a human can actually use. This is the "big red button" surface CONTEXT.md demands: toggles are on the home page, status is visible at a glance, and secrets can be entered without touching env vars.

Output: Opening the browser to the LAN-bound port shows a colored status pill, a 47-minute next-run countdown, the last run outcome, prominent Kill switch and Dry run buttons, and a table of the 50 most recent runs. Clicking the kill switch aborts any in-flight run. Saving a Claude API key on /settings encrypts it with Fernet and adds it to the log scrubber's redaction set.
</objective>

<execution_context>
@C:/Users/abuba/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/abuba/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-foundation-scheduler-safety-envelope/01-CONTEXT.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-RESEARCH.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-03-SUMMARY.md
@app/main.py
@app/scheduler/service.py
@app/settings/service.py
@app/runs/service.py
@app/db/models.py
@app/security/fernet.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Jinja base template, Pico.css, dashboard page + HTMX polling fragments + force-run endpoint</name>
  <files>
    app/web/deps.py,
    app/web/routers/dashboard.py,
    app/web/templates/base.html.j2,
    app/web/templates/dashboard.html.j2,
    app/web/templates/partials/status_pill.html.j2,
    app/web/templates/partials/next_run.html.j2,
    app/web/templates/partials/toggles.html.j2,
    app/web/static/pico.min.css,
    app/web/static/app.css,
    app/main.py
  </files>
  <action>
**app/web/deps.py** — FastAPI dependencies:

```python
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.base import async_session

async def get_session() -> AsyncSession:
    async with async_session() as s:
        yield s

def get_scheduler(request: Request):
    return request.app.state.scheduler

def get_killswitch(request: Request):
    return request.app.state.killswitch

def get_vault(request: Request):
    return request.app.state.vault

def get_rate_limiter(request: Request):
    return request.app.state.rate_limiter
```

**Pico.css download:** During implementation, download Pico.css v2.x from `https://unpkg.com/@picocss/pico@2/css/pico.min.css` (or copy from a local npm cache). Commit the file directly to `app/web/static/pico.min.css`. Per RESEARCH.md: no build step, single ~35 KB file.

If unreachable at build time, fall back to writing a minimal custom CSS with the comment `/* Pico.css fallback — replace with official file when available */` and note in SUMMARY. Prefer the real file.

**app/web/static/app.css** — small custom additions:
```css
.status-pill {padding: .25rem .75rem; border-radius: 1rem; font-weight: bold;}
.status-ok {background: #2a9d8f; color: white;}
.status-killed {background: #e76f51; color: white;}
.status-paused {background: #e9c46a; color: #264653;}
.kill-switch {background: #e76f51; color: white; font-size: 1.1rem;}
.dry-run-on {background: #e9c46a; color: #264653;}
.dry-run-badge {background: #e9c46a; color: #264653; padding: .1rem .4rem; border-radius: .25rem; font-size: .75rem;}
```

**app/web/templates/base.html.j2:**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Job Apply{% endblock %}</title>
  <link rel="stylesheet" href="/static/pico.min.css">
  <link rel="stylesheet" href="/static/app.css">
  <script src="https://unpkg.com/htmx.org@2.0.3" crossorigin="anonymous"></script>
</head>
<body>
  <main class="container">
    <nav>
      <ul><li><strong>Job Apply</strong></li></ul>
      <ul>
        <li><a href="/">Dashboard</a></li>
        <li><a href="/runs">Runs</a></li>
        <li><a href="/settings">Settings</a></li>
      </ul>
    </nav>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

**app/web/templates/partials/status_pill.html.j2:**

```html
{% if killed %}
  <span class="status-pill status-killed">● Paused by kill-switch</span>
{% elif paused %}
  <span class="status-pill status-paused">● Paused</span>
{% else %}
  <span class="status-pill status-ok">● Running{% if dry_run %} (dry-run){% endif %}</span>
{% endif %}
```

**app/web/templates/partials/next_run.html.j2:**

```html
{% if next_run_human %}
  Next run in {{ next_run_human }}
{% else %}
  No scheduled run
{% endif %}
```

**app/web/templates/partials/toggles.html.j2:**

```html
<div id="toggles" class="grid">
  <form hx-post="/toggles/kill-switch" hx-target="#toggles" hx-swap="outerHTML">
    <button type="submit" class="{% if kill_engaged %}status-killed{% else %}secondary{% endif %}">
      {% if kill_engaged %}Release kill-switch{% else %}Kill switch{% endif %}
    </button>
  </form>
  <form hx-post="/toggles/dry-run" hx-target="#toggles" hx-swap="outerHTML">
    <button type="submit" class="{% if dry_run %}dry-run-on{% else %}secondary{% endif %}">
      Dry run: {{ "ON" if dry_run else "OFF" }}
    </button>
  </form>
  <form hx-post="/runs/trigger" hx-target="#status-pill" hx-swap="outerHTML">
    <button type="submit" class="primary">Force run now</button>
  </form>
</div>
```

**app/web/templates/dashboard.html.j2:**

```html
{% extends "base.html.j2" %}
{% block content %}
<article>
  <header>
    <hgroup>
      <h2>Scheduler</h2>
      <p id="status-pill" hx-get="/fragments/status" hx-trigger="every 5s [document.hidden === false]" hx-swap="outerHTML">
        {% include "partials/status_pill.html.j2" %}
      </p>
    </hgroup>
    <p id="next-run" hx-get="/fragments/next-run" hx-trigger="every 15s [document.hidden === false]" hx-swap="innerHTML">
      {% include "partials/next_run.html.j2" %}
    </p>
  </header>

  {% include "partials/toggles.html.j2" %}

  <section>
    <h3>Last run</h3>
    {% if last_run %}
      <p>
        {{ last_run.started_at.isoformat() }} — {{ last_run.status }}
        {% if last_run.duration_ms %}({{ last_run.duration_ms }} ms){% endif %}
        {% if last_run.failure_reason %}— reason: {{ last_run.failure_reason }}{% endif %}
        {% if last_run.dry_run %}<span class="dry-run-badge">DRY</span>{% endif %}
      </p>
      <p>
        <small>
          discovered {{ last_run.counts.get("discovered", 0) }}
          · matched {{ last_run.counts.get("matched", 0) }}
          · tailored {{ last_run.counts.get("tailored", 0) }}
          · submitted {{ last_run.counts.get("submitted", 0) }}
          · failed {{ last_run.counts.get("failed", 0) }}
        </small>
      </p>
    {% else %}
      <p><em>No runs yet. Click "Force run now" to trigger one.</em></p>
    {% endif %}
  </section>

  <section>
    <h3>Recent runs</h3>
    <table role="grid">
      <thead><tr><th>Started</th><th>Status</th><th>Duration</th><th>Reason</th></tr></thead>
      <tbody>
      {% for r in recent_runs %}
        <tr>
          <td><a href="/runs/{{ r.id }}">{{ r.started_at.strftime("%Y-%m-%d %H:%M") }}</a></td>
          <td>{{ r.status }}{% if r.dry_run %} <span class="dry-run-badge">DRY</span>{% endif %}</td>
          <td>{{ r.duration_ms or "—" }} ms</td>
          <td>{{ r.failure_reason or "—" }}</td>
        </tr>
      {% else %}
        <tr><td colspan="4"><em>No runs yet.</em></td></tr>
      {% endfor %}
      </tbody>
    </table>
  </section>
</article>
{% endblock %}
```

**app/web/routers/dashboard.py:**

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.web.deps import get_session, get_scheduler, get_killswitch
from app.settings.service import get_settings_row
from app.runs.service import list_recent_runs

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter()

def _humanize_seconds(iso_next: str | None) -> str | None:
    if not iso_next:
        return None
    from datetime import datetime, timezone
    try:
        nxt = datetime.fromisoformat(iso_next)
        now = datetime.now(nxt.tzinfo or timezone.utc)
        delta = (nxt - now).total_seconds()
        if delta < 0:
            return "any moment"
        m, s = divmod(int(delta), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"
    except Exception:
        return None

async def _common_ctx(request, session, svc, ks):
    row = await get_settings_row(session)
    # Guard: if wizard not complete, plan 01-05 installs a redirect middleware. For now just render.
    runs = await list_recent_runs(session, limit=50)
    last_run = runs[0] if runs else None
    return {
        "request": request,
        "killed": ks.is_engaged(),
        "paused": False,
        "dry_run": row.dry_run,
        "kill_engaged": ks.is_engaged(),
        "next_run_human": _humanize_seconds(svc.next_run_iso()),
        "last_run": last_run,
        "recent_runs": runs,
    }

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch)):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("dashboard.html.j2", ctx)

@router.get("/fragments/status", response_class=HTMLResponse)
async def status_pill(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch)):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("partials/status_pill.html.j2", ctx)

@router.get("/fragments/next-run", response_class=HTMLResponse)
async def next_run(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch)):
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("partials/next_run.html.j2", ctx)

@router.post("/runs/trigger", response_class=HTMLResponse)
async def trigger_run(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch)):
    # Fire-and-forget; dashboard polling will pick up the new state
    import asyncio
    asyncio.create_task(svc.run_pipeline(triggered_by="manual"))
    ctx = await _common_ctx(request, session, svc, ks)
    return templates.TemplateResponse("partials/status_pill.html.j2", ctx)
```

**app/main.py update:** add StaticFiles mount and the dashboard router. Edit the existing `create_app()`:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.web.routers import dashboard as dashboard_router

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, title="Job Application Auto-Apply")
    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(health_router.router)
    app.include_router(dashboard_router.router)
    return app
```
  </action>
  <verify>
Start app locally (via pytest TestClient with lifespan). GET / returns 200 and body contains "Scheduler", "Kill switch", "Dry run", "Force run now".
GET /fragments/status returns 200 with a status-pill HTML fragment.
GET /fragments/next-run returns 200.
POST /runs/trigger returns 200 and schedules a background run.
`grep -q "hx-trigger=\"every 5s" app/web/templates/dashboard.html.j2` returns 0.
  </verify>
  <done>
Dashboard renders with live polling. Force-run button triggers a background run via SchedulerService. Static files mounted. HTMX + Pico wired end-to-end. No build step introduced.
  </done>
</task>

<task type="auto">
  <name>Task 2: Toggle routes (kill-switch, dry-run) + runs list/detail pages</name>
  <files>
    app/web/routers/toggles.py,
    app/web/routers/runs.py,
    app/web/templates/runs_list.html.j2,
    app/web/templates/run_detail.html.j2,
    app/web/templates/partials/runs_rows.html.j2,
    app/main.py,
    tests/integration/test_dashboard_routes.py,
    tests/integration/test_toggles_routes.py
  </files>
  <action>
**app/web/routers/toggles.py:**

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.web.deps import get_session, get_scheduler, get_killswitch
from app.settings.service import get_settings_row, set_setting

router = APIRouter(prefix="/toggles")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

async def _toggles_ctx(request, session, ks):
    row = await get_settings_row(session)
    return {
        "request": request,
        "kill_engaged": ks.is_engaged(),
        "dry_run": row.dry_run,
    }

@router.post("/kill-switch", response_class=HTMLResponse)
async def toggle_kill(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch)):
    if ks.is_engaged():
        await ks.release(svc, session)
    else:
        await ks.engage(svc, session)
    ctx = await _toggles_ctx(request, session, ks)
    return templates.TemplateResponse("partials/toggles.html.j2", ctx)

@router.post("/dry-run", response_class=HTMLResponse)
async def toggle_dry_run(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch)):
    row = await get_settings_row(session)
    await set_setting(session, "dry_run", not row.dry_run)
    ctx = await _toggles_ctx(request, session, ks)
    return templates.TemplateResponse("partials/toggles.html.j2", ctx)
```

Note: POST /runs/trigger already lives in dashboard router (matches the hx-post in partials/toggles.html.j2).

**app/web/routers/runs.py:**

```python
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select
from app.web.deps import get_session
from app.runs.service import list_recent_runs
from app.db.models import Run

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/runs", response_class=HTMLResponse)
async def runs_list(request: Request, offset: int = 0, session=Depends(get_session)):
    runs = await list_recent_runs(session, limit=50, offset=offset)
    template = "partials/runs_rows.html.j2" if offset > 0 else "runs_list.html.j2"
    return templates.TemplateResponse(template, {
        "request": request,
        "runs": runs,
        "next_offset": offset + 50 if len(runs) == 50 else None,
    })

@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(run_id: int, request: Request, session=Depends(get_session)):
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return templates.TemplateResponse("run_detail.html.j2", {"request": request, "run": run})
```

**app/web/templates/runs_list.html.j2:** extends base, renders a table of runs with a trailing HTMX "show more" row that `hx-get="/runs?offset={{next_offset}}"` targeting the tbody with hx-swap="beforeend".

**app/web/templates/partials/runs_rows.html.j2:** renders only `<tr>` rows (same shape as the table body in runs_list). Used for infinite-scroll appends.

**app/web/templates/run_detail.html.j2:** extends base, shows started_at, ended_at, duration, status, failure_reason, dry_run flag, triggered_by, and a `<pre>` with JSON-pretty-printed `run.counts`.

**main.py update:** register the new routers.

```python
from app.web.routers import toggles as toggles_router, runs as runs_router
app.include_router(toggles_router.router)
app.include_router(runs_router.router)
```

**tests/integration/test_dashboard_routes.py:**
- Fixture: standalone app with lifespan, in-memory-sqlite override (or real tmp_path file — RESEARCH.md recommends the latter for lifespan parity).
- `test_dashboard_renders`: GET / → 200, body contains "Kill switch", "Dry run", "Force run now".
- `test_fragment_status`: GET /fragments/status → 200, body contains "Running" or "Paused".
- `test_runs_list_empty`: GET /runs → 200, body contains "No runs" or an empty table.
- `test_run_detail_404`: GET /runs/999999 → 404.
- `test_force_run_creates_run_row`: POST /runs/trigger → 200 → wait a moment → query Run table → at least one row exists.

**tests/integration/test_toggles_routes.py:**
- `test_kill_switch_toggle_engage_release`: POST /toggles/kill-switch → settings.kill_switch=True + svc.killswitch.is_engaged()=True → POST again → False.
- `test_dry_run_toggle`: POST /toggles/dry-run → settings.dry_run=True → POST again → False.
- `test_kill_switch_cancels_in_flight`: Start a long-running stub via monkeypatched `_execute_stub`. POST /toggles/kill-switch → in-flight task gets CancelledError → Run row has failure_reason='killed'.
  </action>
  <verify>
`pytest tests/integration/test_dashboard_routes.py tests/integration/test_toggles_routes.py -v` all pass.
GET /runs in a live app returns a styled table.
POST /toggles/kill-switch round-trips.
  </verify>
  <done>
Toggles, runs list, and run detail pages implemented and tested. Kill-switch toggle from the UI actually aborts an in-flight run (verified by integration test). Runs infinite-scroll partial returns only rows for offset > 0.
  </done>
</task>

<task type="auto">
  <name>Task 3: Settings page — secrets CRUD (Fernet) + rate-limit config</name>
  <files>
    app/web/routers/settings.py,
    app/web/templates/settings.html.j2,
    app/web/templates/partials/secrets_list.html.j2,
    app/main.py,
    tests/integration/test_settings_routes.py
  </files>
  <action>
**app/web/routers/settings.py:**

```python
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select, delete as sql_delete
from datetime import datetime
from app.web.deps import get_session, get_vault, get_rate_limiter
from app.settings.service import get_settings_row, set_setting
from app.db.models import Secret

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

KNOWN_SECRET_NAMES = [
    "anthropic_api_key",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
]

async def _secret_names(session):
    result = await session.execute(select(Secret.name).order_by(Secret.name))
    return [r[0] for r in result.all()]

@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, session=Depends(get_session)):
    row = await get_settings_row(session)
    names = await _secret_names(session)
    return templates.TemplateResponse("settings.html.j2", {
        "request": request,
        "settings": row,
        "known_names": KNOWN_SECRET_NAMES,
        "stored_names": names,
    })

@router.post("/secrets", response_class=HTMLResponse)
async def save_secret(
    request: Request,
    name: str = Form(...),
    value: str = Form(...),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    if not value or len(value) < 1:
        raise HTTPException(status_code=400, detail="empty secret value")
    ciphertext = vault.encrypt(value)   # also registers plaintext with scrubber
    # Upsert
    existing = (await session.execute(select(Secret).where(Secret.name == name))).scalar_one_or_none()
    if existing:
        existing.ciphertext = ciphertext
        existing.updated_at = datetime.utcnow()
    else:
        session.add(Secret(name=name, ciphertext=ciphertext))
    await session.commit()
    names = await _secret_names(session)
    return templates.TemplateResponse("partials/secrets_list.html.j2", {
        "request": request,
        "stored_names": names,
        "known_names": KNOWN_SECRET_NAMES,
    })

@router.delete("/secrets/{name}", response_class=HTMLResponse)
async def delete_secret(name: str, request: Request, session=Depends(get_session)):
    await session.execute(sql_delete(Secret).where(Secret.name == name))
    await session.commit()
    names = await _secret_names(session)
    return templates.TemplateResponse("partials/secrets_list.html.j2", {
        "request": request,
        "stored_names": names,
        "known_names": KNOWN_SECRET_NAMES,
    })

@router.post("/limits")
async def save_limits(
    daily_cap: int = Form(...),
    delay_min_seconds: int = Form(...),
    delay_max_seconds: int = Form(...),
    timezone: str = Form(...),
    session=Depends(get_session),
    rate_limiter=Depends(get_rate_limiter),
):
    if daily_cap < 0 or daily_cap > 10000:
        raise HTTPException(400, "daily_cap out of range")
    if delay_min_seconds <= 0 or delay_max_seconds <= delay_min_seconds or delay_max_seconds > 600:
        raise HTTPException(400, "invalid delay range")
    await set_setting(session, "daily_cap", daily_cap)
    await set_setting(session, "delay_min_seconds", delay_min_seconds)
    await set_setting(session, "delay_max_seconds", delay_max_seconds)
    await set_setting(session, "timezone", timezone)
    # Update live rate_limiter to reflect new values without restart
    rate_limiter.daily_cap = daily_cap
    rate_limiter.delay_min = delay_min_seconds
    rate_limiter.delay_max = delay_max_seconds
    from zoneinfo import ZoneInfo
    rate_limiter.tz = ZoneInfo(timezone)
    return RedirectResponse("/settings", status_code=303)
```

**app/web/templates/settings.html.j2:** extends base. Two sections:

1. **Rate limit envelope** form POSTing to `/settings/limits` with fields daily_cap, delay_min_seconds, delay_max_seconds, timezone. Pre-filled from settings row.

2. **Secrets** section with:
   - Form to save: a `<select name="name">` of KNOWN_SECRET_NAMES (or text input), a `<input type="password" name="value">`, hx-post to /settings/secrets, hx-target="#secrets-list", hx-swap="outerHTML".
   - A `<div id="secrets-list">` including partials/secrets_list.html.j2.

Include a prominent warning callout: "Secrets are encrypted with your FERNET_KEY. If you change or lose the key, stored secrets become unrecoverable — you will need to re-enter them."

**app/web/templates/partials/secrets_list.html.j2:**

```html
<div id="secrets-list">
  <ul>
    {% for name in known_names %}
      <li>
        {{ name }}:
        {% if name in stored_names %}
          ✓ stored
          <button hx-delete="/settings/secrets/{{ name }}" hx-target="#secrets-list" hx-swap="outerHTML" hx-confirm="Delete {{ name }}?" class="outline contrast">Delete</button>
        {% else %}
          <em>not set</em>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
</div>
```

**main.py update:** register settings router.

```python
from app.web.routers import settings as settings_router
app.include_router(settings_router.router)
```

**tests/integration/test_settings_routes.py:**
- `test_settings_page_renders`: GET /settings → 200 → body contains "Rate limit", "Secrets", and the warning about FERNET_KEY rotation.
- `test_save_secret_encrypts_and_scrubs`:
  - POST /settings/secrets with name=anthropic_api_key, value="sk-ant-api03-TESTSENTINELDEADBEEF"
  - Query Secret table → row exists, ciphertext is bytes, is NOT the plaintext.
  - Call `FernetVault.decrypt(row.ciphertext)` → equals the plaintext.
  - Log something containing the plaintext → scrubber replaces with REDACTED.
- `test_delete_secret`: save one → DELETE /settings/secrets/anthropic_api_key → row gone.
- `test_save_limits_validates_and_updates_live_rate_limiter`:
  - POST /settings/limits with daily_cap=10, delay_min=45, delay_max=90, timezone="America/Los_Angeles"
  - settings row reflects new values.
  - app.state.rate_limiter.daily_cap == 10 immediately (no restart).
- `test_save_limits_rejects_invalid_range`: POST with delay_min=100 delay_max=50 → 400.
- `test_save_limits_rejects_invalid_cap`: daily_cap=-1 → 400.
  </action>
  <verify>
`pytest tests/integration/test_settings_routes.py -v` all pass.
GET /settings in live app shows the form and the rotation warning.
Save a test secret → re-read from DB → ciphertext is not the plaintext.
  </verify>
  <done>
Settings page implemented with secrets CRUD going through FernetVault and rate-limit envelope config that updates the live RateLimiter without restart. Tests verify encryption, scrubbing, deletion, and live update. Rotation warning banner per RESEARCH.md pitfall is present.
  </done>
</task>

</tasks>

<verification>
- `pytest tests/ -q` entire suite passes.
- Opening the browser to a running container shows: status pill, next run countdown, big Kill switch button, big Dry run button, Force run now, last run summary, recent runs table.
- Clicking Kill switch while a force-triggered run is in flight aborts it and produces a Run row with failure_reason='killed'.
- Saving a secret on /settings stores ciphertext only and registers the plaintext with the scrubber.
- Rate-limit envelope updates from /settings take effect on the next run_pipeline call without restart.
</verification>

<success_criteria>
1. Dashboard is the landing page and shows scheduler state, next run, last run outcome, and counts.
2. Kill switch and Dry run are one click away from home per CONTEXT.md (big buttons on the dashboard).
3. HTMX polling refreshes status every 5s and next-run every 15s, paused when tab hidden.
4. Runs list page shows 50 most recent runs with HTMX "show more" infinite scroll.
5. Settings page encrypts secrets via FernetVault, updates rate-limit envelope live, and warns about FERNET_KEY rotation.
6. All dashboard/toggles/runs/settings integration tests pass.
</success_criteria>

<output>
Write `.planning/phases/01-foundation-scheduler-safety-envelope/01-04-SUMMARY.md` frontmatter:
- `subsystem: web-ui`
- `tech-stack.added: [Jinja2 templates active, HTMX 2.0.3 via CDN, Pico.css v2.x static, FastAPI StaticFiles]`
- `affects: [01-05, Phase 2, all UI phases]`
- `requires: [01-03]`
- `key files: [app/web/routers/dashboard.py, toggles.py, runs.py, settings.py, app/web/templates/*, app/web/static/*, app/main.py]`
- Decisions: "Pico.css classless (no Tailwind, no build)", "HTMX fragments served from the same routers as full pages", "settings/limits updates the live RateLimiter to avoid restart", "humanize_seconds helper for next-run countdown server-side (no client-side JS timers)", "secrets use upsert, decrypt path goes through vault which auto-registers with scrubber"
</output>
</content>
</invoke>