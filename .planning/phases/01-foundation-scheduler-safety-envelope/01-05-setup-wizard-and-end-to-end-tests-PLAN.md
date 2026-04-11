---
phase: 01-foundation-scheduler-safety-envelope
plan: 05
type: execute
wave: 4
depends_on: ["01-04"]
files_modified:
  - app/web/routers/wizard.py
  - app/web/deps.py
  - app/web/templates/wizard/step_1_resume.html.j2
  - app/web/templates/wizard/step_2_secrets.html.j2
  - app/web/templates/wizard/step_3_keywords.html.j2
  - app/web/templates/wizard/_layout.html.j2
  - app/main.py
  - tests/integration/test_wizard_flow.py
  - tests/integration/test_first_boot_end_to_end.py
  - tests/integration/test_fernet_rotation_banner.py
  - README.md
autonomous: true

must_haves:
  truths:
    - "Fresh ./data volume boots the container, GET / redirects to /setup/1, user walks through upload resume → api keys → keywords, and subsequent visits go straight to the dashboard"
    - "The wizard is skippable (POST /setup/skip) without filling fields — wizard is guidance, not a gate per CONTEXT.md"
    - "wizard_complete flag persists across container restart"
    - "If FERNET_KEY rotated between restarts, a visible banner appears on the dashboard and /health still returns 200 (secrets left in DB, not auto-deleted)"
    - "End-to-end: docker compose up on a clean ./data yields running app with hourly scheduler, kill-switch, dry-run, rate-limit envelope, encrypted secrets, zero-PII logs, and a working setup wizard"
  artifacts:
    - path: "app/web/routers/wizard.py"
      provides: "GET /setup/1..3, POST /setup/1..3, POST /setup/skip, wizard state transitions"
      exports: ["router"]
    - path: "app/web/templates/wizard/step_1_resume.html.j2"
      provides: "DOCX upload form, writes to data/uploads/resume_base.docx"
    - path: "app/web/templates/wizard/step_2_secrets.html.j2"
      provides: "Anthropic + SMTP credential form (encrypted via FernetVault)"
    - path: "app/web/templates/wizard/step_3_keywords.html.j2"
      provides: "Keyword textarea stored in settings.keywords_csv"
    - path: "tests/integration/test_first_boot_end_to_end.py"
      provides: "The goal-backward success test for Phase 1"
    - path: "README.md"
      provides: "User-facing docker compose up instructions, FERNET_KEY generation, ./data backup note, rotation warning"
  key_links:
    - from: "app/main.py dashboard route"
      to: "require_wizard_complete"
      via: "FastAPI dependency that redirects to /setup/1 when settings.wizard_complete is False"
      pattern: "require_wizard"
    - from: "app/web/routers/wizard.py step 2"
      to: "FernetVault.encrypt + Secret table"
      via: "Same save_secret path as /settings/secrets"
      pattern: "vault\\.encrypt"
    - from: "end-to-end test"
      to: "Phase 1 must_haves"
      via: "asserts hourly job registered + run_pipeline succeeds + dry_run stamping + kill-switch cancel + rate-limit skip + zero-PII in logs file + wizard redirect"
      pattern: "wizard_complete"
---

<objective>
Close Phase 1 with the first-run setup wizard (the last locked decision from CONTEXT.md that touches new code) and a goal-backward end-to-end test suite that proves all five must_haves from the phase scope. Also add a dashboard banner for the Fernet rotation failure mode per RESEARCH.md pitfall, and a README.md that documents `docker compose up` as the one-line install path.

Purpose: Plan 01-04 built the dashboard assuming wizard completion. This plan installs the redirect guard and the three wizard steps, then shifts from per-plan testing to the actual Phase 1 goal-backward assertions: a user runs `docker compose up` on a fresh laptop and gets a running, observable, safely-throttled scheduler with encrypted secret storage and a working kill-switch — even though no actual job work happens yet.

Output: The full Phase 1 must_haves from the orchestrator scope are testable and green. The README gives a user the two commands they need to launch the app.
</objective>

<execution_context>
@C:/Users/abuba/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/abuba/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-foundation-scheduler-safety-envelope/01-CONTEXT.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-RESEARCH.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-01-SUMMARY.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-02-SUMMARY.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-03-SUMMARY.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-04-SUMMARY.md
@app/web/routers/dashboard.py
@app/web/routers/settings.py
@app/main.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Setup wizard routes + templates + dashboard redirect guard + rotation banner</name>
  <files>
    app/web/routers/wizard.py,
    app/web/deps.py,
    app/web/templates/wizard/_layout.html.j2,
    app/web/templates/wizard/step_1_resume.html.j2,
    app/web/templates/wizard/step_2_secrets.html.j2,
    app/web/templates/wizard/step_3_keywords.html.j2,
    app/main.py
  </files>
  <action>
**Redirect guard** — add to `app/web/deps.py`:

```python
from fastapi.responses import RedirectResponse

async def require_wizard_complete(session=Depends(get_session)):
    from app.settings.service import get_settings_row
    row = await get_settings_row(session)
    if not row.wizard_complete:
        return RedirectResponse("/setup/1", status_code=307)
    return None
```

In `app/web/routers/dashboard.py`, update the `dashboard()` handler: before rendering, call the guard manually (since returning a RedirectResponse from a dependency is awkward with templates). Simpler form: inline the check.

```python
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session=Depends(get_session), svc=Depends(get_scheduler), ks=Depends(get_killswitch), vault=Depends(get_vault)):
    row = await get_settings_row(session)
    if not row.wizard_complete:
        return RedirectResponse("/setup/1", status_code=307)
    # Fernet rotation detection banner
    rotation_banner = None
    async with session.begin():
        pass  # session already open via get_session; skip
    # Try decrypting any stored secret to detect rotation. Failure → banner.
    from sqlalchemy import select
    from app.db.models import Secret
    from app.security.fernet import InvalidFernetKey
    result = await session.execute(select(Secret).limit(1))
    sample = result.scalar_one_or_none()
    if sample is not None:
        try:
            vault.decrypt(sample.ciphertext)
        except InvalidFernetKey:
            rotation_banner = (
                "Stored secrets cannot be decrypted. The master key (FERNET_KEY) "
                "has changed. Re-enter your API keys in Settings."
            )
    ctx = await _common_ctx(request, session, svc, ks)
    ctx["rotation_banner"] = rotation_banner
    return templates.TemplateResponse("dashboard.html.j2", ctx)
```

Update `dashboard.html.j2` to render the banner at the top of the article when `rotation_banner` is truthy — use Pico's `<article class="contrast">` with a red heading and clear CTA "Go to Settings".

**app/web/routers/wizard.py:**

```python
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import select
from datetime import datetime
from app.web.deps import get_session, get_vault
from app.config import get_settings
from app.settings.service import get_settings_row, set_setting
from app.db.models import Secret

router = APIRouter(prefix="/setup")
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

@router.get("/skip")
async def skip_get():
    return RedirectResponse("/setup/1", status_code=307)

@router.post("/skip")
async def skip_wizard(session=Depends(get_session)):
    await set_setting(session, "wizard_complete", True)
    return RedirectResponse("/", status_code=303)

@router.get("/1", response_class=HTMLResponse)
async def step1_get(request: Request, session=Depends(get_session)):
    cfg = get_settings()
    uploads = cfg.data_dir / "uploads"
    existing = (uploads / "resume_base.docx").exists()
    return templates.TemplateResponse("wizard/step_1_resume.html.j2", {
        "request": request, "existing": existing,
    })

@router.post("/1", response_class=HTMLResponse)
async def step1_post(request: Request, resume: UploadFile = File(...), session=Depends(get_session)):
    if not resume.filename or not resume.filename.lower().endswith(".docx"):
        raise HTTPException(400, "resume must be a .docx file")
    cfg = get_settings()
    uploads = cfg.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    target = uploads / "resume_base.docx"
    content = await resume.read()
    if len(content) == 0:
        raise HTTPException(400, "empty upload")
    target.write_bytes(content)
    await set_setting(session, "updated_at", datetime.utcnow())
    return RedirectResponse("/setup/2", status_code=303)

@router.get("/2", response_class=HTMLResponse)
async def step2_get(request: Request, session=Depends(get_session)):
    names = [r[0] for r in (await session.execute(select(Secret.name))).all()]
    return templates.TemplateResponse("wizard/step_2_secrets.html.j2", {
        "request": request, "stored": names,
    })

@router.post("/2", response_class=HTMLResponse)
async def step2_post(
    request: Request,
    anthropic_api_key: str = Form(""),
    smtp_host: str = Form(""),
    smtp_port: str = Form(""),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    session=Depends(get_session),
    vault=Depends(get_vault),
):
    fields = {
        "anthropic_api_key": anthropic_api_key,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_user": smtp_user,
        "smtp_password": smtp_password,
    }
    for name, value in fields.items():
        if not value:
            continue
        ciphertext = vault.encrypt(value)
        existing = (await session.execute(select(Secret).where(Secret.name == name))).scalar_one_or_none()
        if existing:
            existing.ciphertext = ciphertext
            existing.updated_at = datetime.utcnow()
        else:
            session.add(Secret(name=name, ciphertext=ciphertext))
    await session.commit()
    return RedirectResponse("/setup/3", status_code=303)

@router.get("/3", response_class=HTMLResponse)
async def step3_get(request: Request, session=Depends(get_session)):
    row = await get_settings_row(session)
    return templates.TemplateResponse("wizard/step_3_keywords.html.j2", {
        "request": request, "keywords_csv": row.keywords_csv or "",
    })

@router.post("/3", response_class=HTMLResponse)
async def step3_post(keywords: str = Form(""), session=Depends(get_session)):
    # Normalize: one per line → comma-separated
    lines = [l.strip() for l in keywords.splitlines() if l.strip()]
    csv = ",".join(lines)
    await set_setting(session, "keywords_csv", csv)
    await set_setting(session, "wizard_complete", True)
    return RedirectResponse("/", status_code=303)
```

**app/web/templates/wizard/_layout.html.j2:**

```html
{% extends "base.html.j2" %}
{% block content %}
<article>
  <header>
    <h2>Setup wizard — step {{ step }} of 3</h2>
    <nav>
      <ul><li>{% if step > 1 %}<a href="/setup/{{ step - 1 }}">← Back</a>{% endif %}</li></ul>
      <ul><li><form method="post" action="/setup/skip"><button type="submit" class="outline">Skip setup</button></form></li></ul>
    </nav>
  </header>
  {% block wizard_content %}{% endblock %}
</article>
{% endblock %}
```

**step_1_resume.html.j2:** extends _layout with step=1. Form with `enctype="multipart/form-data"`, `<input type="file" name="resume" accept=".docx" required>`, submit button "Upload and continue". Shows "Current resume: resume_base.docx" + overwrite notice if `existing`.

**step_2_secrets.html.j2:** extends _layout with step=2. Five password-type inputs (anthropic_api_key, smtp_host, smtp_port, smtp_user, smtp_password). All optional on this step. Show which are already stored (list of names from `stored`). Submit button "Save and continue". Prominent note: "All fields are encrypted at rest with your FERNET_KEY. You can leave blanks now and fill them later in Settings."

**step_3_keywords.html.j2:** extends _layout with step=3. Textarea labeled "One keyword per line". Submit button "Finish setup". Pre-fill from `keywords_csv` (convert csv back to newlines for display).

**app/main.py update:** register wizard router BEFORE the dashboard router in create_app() (order matters for the redirect flow):

```python
from app.web.routers import wizard as wizard_router
app.include_router(wizard_router.router)
```
  </action>
  <verify>
Fresh DB: GET / → 307 to /setup/1. Complete all three steps → GET / → 200 dashboard.
POST /setup/skip → settings.wizard_complete=True → GET / → 200 dashboard without any resume/secrets/keywords.
Uploading a non-.docx file returns 400.
Saving a secret via wizard step 2 writes an encrypted Secret row.
  </verify>
  <done>
Wizard flow implemented: three steps + skip path. Dashboard guard redirects when incomplete. Rotation banner rendered when FernetVault fails to decrypt an existing secret. All wizard routes + templates in place.
  </done>
</task>

<task type="auto">
  <name>Task 2: Wizard flow tests + rotation banner test</name>
  <files>
    tests/integration/test_wizard_flow.py,
    tests/integration/test_fernet_rotation_banner.py
  </files>
  <action>
**tests/integration/test_wizard_flow.py:**

- Fixture: fresh tmp_path data_dir, fresh Fernet key, full lifespan app.
- `test_fresh_boot_redirects_to_wizard`: GET / → 307, Location header contains "/setup/1".
- `test_step_1_requires_docx`: POST /setup/1 with a non-docx file → 400. With an empty file → 400.
- `test_step_1_accepts_docx_and_persists`: POST /setup/1 with `("resume", ("r.docx", b"fakebinary", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))` → 303 to /setup/2. File exists at `data_dir/uploads/resume_base.docx` with content `b"fakebinary"`.
- `test_step_2_encrypts_secrets`: POST /setup/2 with `anthropic_api_key=sk-ant-test-SENTINEL-123`. After → Secret table has row `anthropic_api_key`. `FernetVault.decrypt(row.ciphertext) == "sk-ant-test-SENTINEL-123"`. Redirect to /setup/3.
- `test_step_2_allows_blanks`: POST /setup/2 with all empty → 303 /setup/3 (wizard is guidance, not a gate). No secrets inserted.
- `test_step_3_sets_wizard_complete_and_keywords`: POST /setup/3 with keywords="python\nrust\ngolang" → 303 /. settings.wizard_complete=True. settings.keywords_csv == "python,rust,golang".
- `test_full_happy_path`: step1 → step2 → step3 → GET / returns 200 dashboard.
- `test_skip_short_circuits`: fresh boot → POST /setup/skip → GET / → 200 dashboard. No secrets, no resume, no keywords; wizard_complete=True.
- `test_wizard_complete_persists_across_restart`: complete wizard, shut down lifespan, start a NEW lifespan on the same data_dir/db, GET / → 200 dashboard directly.

**tests/integration/test_fernet_rotation_banner.py:**

- `test_rotated_key_surfaces_banner`:
  1. Start app with fernet_key=KEY_A. Save a secret via /settings/secrets.
  2. Shut down lifespan.
  3. Restart app with fernet_key=KEY_B (different).
  4. Complete wizard (or use skip).
  5. GET / → 200, body contains "Stored secrets cannot be decrypted" and "FERNET_KEY".
  6. Secret row is STILL present in DB (not auto-deleted — forensic preservation per RESEARCH.md pitfall).
- `test_non_rotated_key_no_banner`: Start with KEY_A, save secret, restart with same KEY_A → no banner in dashboard body.
- `test_health_still_200_after_rotation`: Same rotation setup → GET /health → 200 (rotation is not a fatal error for the app; only stored secrets are unreadable).
  </action>
  <verify>
`pytest tests/integration/test_wizard_flow.py tests/integration/test_fernet_rotation_banner.py -v` all pass.
  </verify>
  <done>
Wizard happy path, skip path, validation paths, and persistence-across-restart all tested. Fernet rotation surfaces a banner without data loss or app crash. Both test files green.
  </done>
</task>

<task type="auto">
  <name>Task 3: End-to-end Phase 1 goal-backward test suite + README.md</name>
  <files>
    tests/integration/test_first_boot_end_to_end.py,
    README.md
  </files>
  <action>
This is the goal-backward test suite that asserts the Phase 1 scope must_haves from the orchestrator. Every assertion maps directly to a line in the <phase_scope> must_haves list.

**tests/integration/test_first_boot_end_to_end.py:**

Fixture `clean_boot` — fresh tmp_path data dir, fresh Fernet key, fresh settings, full lifespan. Yields AsyncClient + app + session factory.

- **`test_must_have_1_docker_compose_up_yields_running_app_with_sqlite_on_data_volume(clean_boot)`:**
  - Assert `data_dir / "app.db"` exists after lifespan startup.
  - Assert `data_dir / "logs"` exists.
  - GET /health → 200 with `scheduler_running: true`.
  - Shut down lifespan.
  - Assert `data_dir / "app.db"` STILL exists (persistence across the simulated restart).
  - Restart lifespan with same data_dir → settings row still has defaults, rate_limit_counters table still queryable.

- **`test_must_have_2_hourly_heartbeat_visible_with_runlock(clean_boot)`:**
  - Assert `scheduler.get_job("hourly_heartbeat")` exists with a non-null `next_run_time`.
  - Assert the job's `max_instances == 1` and `coalesce is True`.
  - Manually call `run_pipeline(triggered_by="manual")` twice concurrently via `asyncio.gather` — both complete, but exactly one Run row is created before the second is serialized by the asyncio.Lock. (Or: second one also creates a row but they do not overlap — observable by started_at/ended_at ordering.)
  - Assert the Run.counts dict has the five stage keys initialized to 0.

- **`test_must_have_3_dry_run_and_killswitch_respected_in_realtime(clean_boot)`:**
  - Set settings.dry_run=True via POST /toggles/dry-run. Manually trigger a run. Assert the resulting Run.dry_run is True.
  - Monkeypatch SchedulerService._execute_stub to a long sleep. Start run in background. POST /toggles/kill-switch → the in-flight background task receives CancelledError within 100ms. Query Run → status='failed', failure_reason='killed'.
  - POST /toggles/kill-switch again (release). Trigger a new run → succeeds.

- **`test_must_have_4_fernet_secrets_survive_restart_and_zero_pii_in_logs(clean_boot, tmp_path)`:**
  - POST /settings/secrets name=anthropic_api_key, value="sk-ant-api03-ENDTOENDSENTINELDEADBEEF".
  - Shut down lifespan, reopen with same fernet key + same data_dir.
  - Query Secret table → row exists. Call vault.decrypt → returns the original plaintext.
  - Read `data_dir/logs/app.log` contents. Assert the sentinel string "sk-ant-api03-ENDTOENDSENTINELDEADBEEF" does NOT appear anywhere.
  - For good measure: emit a structlog line containing the sentinel before reading the file. Assert file still does not contain the raw sentinel (scrubber active).

- **`test_must_have_5_rate_limit_envelope_enforced_before_downstream(clean_boot)`:**
  - Seed settings: daily_cap=2, delay_min=30, delay_max=120.
  - Seed rate_limit_counters(today_local_iso, submitted_count=2).
  - Trigger run_pipeline → resulting Run row has status='skipped', failure_reason='rate_limit'.
  - Assert `rate_limiter.random_action_delay()` returns a value in [30, 120] for 50 samples.
  - Freeze time to just before midnight → call `rate_limiter.midnight_reset(session)` after time rolls to next day → new day's counter row exists with count=0 → run_pipeline succeeds.

- **`test_must_have_6_setup_wizard_routes_through_resume_api_keys_keywords(clean_boot)`:**
  - Clear settings.wizard_complete. GET / → 307 to /setup/1.
  - POST step 1 with a fake docx → redirect to /setup/2. File exists at uploads/resume_base.docx.
  - POST step 2 with anthropic_api_key + smtp_host → redirect to /setup/3. Secret rows exist, encrypted, and their plaintexts are registered with the scrubber.
  - POST step 3 with "python\nrust" → redirect to /. Settings row has keywords_csv="python,rust" and wizard_complete=True.
  - GET / → 200 dashboard (no more redirect).

Use pytest's `asyncio_mode=auto`. Structure each test so the assertions tie 1:1 to must_have #N.

**README.md:**

```markdown
# Job Application Auto-Apply

Dockerized, single-user, LAN-bound web app that autonomously applies to jobs on your behalf.

> **Phase 1 status:** Foundation only. The scheduler, safety envelope, and encrypted
> secret storage are live; no job discovery, tailoring, or submission yet.

## Quick start

```bash
# 1. Generate a Fernet master key and save it somewhere safe
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Copy the example env file and paste the key
cp .env.example .env
$EDITOR .env   # set FERNET_KEY, optionally TZ and BIND_ADDRESS

# 3. Boot the app
docker compose up -d

# 4. Open the dashboard
open http://localhost:8000
```

On first boot you'll be walked through the setup wizard (resume upload → API keys → keywords). The wizard is optional — click "Skip setup" to go straight to the dashboard.

## Data persistence

Everything lives under `./data`:

```
data/
├── app.db            # SQLite (settings, secrets, runs, rate limit counters)
├── logs/app.log      # structured JSON logs (PII/secrets scrubbed)
├── uploads/          # base DOCX resume
└── browser/          # (Phase 6) Playwright storageState
```

Back it up, wipe it to reset, or copy it to another machine to migrate.

## Important: Fernet key rotation

Your `FERNET_KEY` env var encrypts API keys and SMTP credentials in SQLite. **If you change or lose the key, stored secrets become unreadable.** The app will show a banner and keep running, but you'll need to re-enter your secrets in Settings. There is no rotation tool in v1.

## Security posture

- Single-user per deployment. LAN-bound by default (`BIND_ADDRESS=0.0.0.0`); set `BIND_ADDRESS=127.0.0.1` for loopback only.
- Secrets encrypted at rest with Fernet.
- Global log scrubber guarantees API keys, passwords, and registered plaintexts never appear in stdout or log files.
- Kill switch and dry-run toggles one click away on the home page.

## Development

```bash
pytest                        # run the test suite
ruff check .                  # lint
mypy app                      # type check
alembic upgrade head          # apply migrations (container does this on boot)
```

See `.planning/phases/01-foundation-scheduler-safety-envelope/` for the Phase 1 plans and summaries.
```
  </action>
  <verify>
`pytest tests/integration/test_first_boot_end_to_end.py -v` — all six must_have tests pass.
`pytest tests/ -q` — entire test suite passes.
`docker compose up -d` on a clean machine boots the app, `/health` returns 200 within 30s, `data/app.db` is created.
Browsing to http://localhost:8000 redirects to /setup/1 on fresh data; after wizard or skip, dashboard renders.
Engaging kill switch during a `/runs/trigger` request aborts the in-flight run.
  </verify>
  <done>
End-to-end Phase 1 test suite asserts all six scope must_haves and is green. README gives a user the three commands to launch the app, documents the FERNET_KEY rotation pitfall, and describes the ./data volume layout. Phase 1 is complete.
  </done>
</task>

</tasks>

<verification>
- `pytest tests/ -q` — entire suite passes (unit + integration + end-to-end).
- `docker compose up -d` on a clean `./data` boots to healthy `/health` within 30s.
- All 11 Phase 1 requirements functionally satisfied and observably tested:
  - FOUND-01 ✓ (test_must_have_1)
  - FOUND-02 ✓ (test_must_have_1 — persistence-across-restart)
  - FOUND-03 ✓ (test_must_have_2)
  - FOUND-04 ✓ (structured logs + counts JSON on Run)
  - FOUND-05 ✓ (test_must_have_3 — dry-run stamping)
  - FOUND-06 ✓ (test_must_have_4 — Fernet survives restart)
  - FOUND-07 ✓ (test_must_have_3 — kill-switch hard stop)
  - DISC-07 ✓ (random_action_delay tested)
  - SAFE-01 ✓ (test_must_have_5 — daily cap)
  - SAFE-02 ✓ (test_must_have_5 — delay range)
  - SAFE-03 ✓ (test_must_have_4 — zero PII in app.log)
</verification>

<success_criteria>
1. A user who has never seen the app can run `docker compose up -d`, open http://localhost:8000, walk through the wizard, and see a working dashboard — all documented in README.md.
2. The Phase 1 goal-backward test suite asserts all six must_haves from the phase scope and is green.
3. Wizard is skippable (guidance, not a gate) per CONTEXT.md.
4. Fernet rotation between restarts surfaces a visible banner without crashing the app or deleting data.
5. wizard_complete flag survives container restart; second boot goes straight to the dashboard.
6. All 11 Phase 1 requirements trace to specific green tests.
</success_criteria>

<output>
Write `.planning/phases/01-foundation-scheduler-safety-envelope/01-05-SUMMARY.md` with frontmatter:
- `subsystem: onboarding + e2e`
- `tech-stack.added: [FastAPI UploadFile multipart, python-multipart]`
- `affects: [Phase 2]` — Phase 2 will replace wizard step 2 inputs with real editing, and step 1 with the Resume model
- `requires: [01-04]`
- `key files: [app/web/routers/wizard.py, app/web/templates/wizard/*, tests/integration/test_first_boot_end_to_end.py, README.md]`
- Decisions: "Wizard writes wizard_complete only on step 3 or skip — going back and forth does not flip the flag", "Wizard step 2 allows blank submissions (guidance, not a gate)", "Rotation banner does not delete unreadable secrets — preserved for forensic", "End-to-end tests run against the real lifespan with tmp_path data dirs, not mocks"
- "Phase 1 complete" — all must_haves green.
</output>
</content>
</invoke>