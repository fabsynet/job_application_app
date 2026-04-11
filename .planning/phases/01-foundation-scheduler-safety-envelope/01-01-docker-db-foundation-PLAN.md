---
phase: 01-foundation-scheduler-safety-envelope
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Dockerfile
  - compose.yml
  - .env.example
  - .gitignore
  - pyproject.toml
  - requirements.txt
  - alembic.ini
  - app/__init__.py
  - app/config.py
  - app/db/__init__.py
  - app/db/base.py
  - app/db/models.py
  - app/db/migrations/env.py
  - app/db/migrations/script.py.mako
  - app/db/migrations/versions/0001_initial.py
  - tests/__init__.py
  - tests/conftest.py
  - tests/unit/test_config.py
  - tests/unit/test_models.py
autonomous: true

must_haves:
  truths:
    - "docker compose up builds and starts a container bound to ./data host volume"
    - "The /data volume contains an SQLite file that persists Settings, Secret, Run, RateLimitCounter rows across container restarts"
    - "App fails fast at startup if FERNET_KEY env var is missing or malformed"
  artifacts:
    - path: "Dockerfile"
      provides: "Playwright-python base image, --workers 1 uvicorn CMD, non-root app user, /data volume"
      contains: "mcr.microsoft.com/playwright/python:v1.58.0-noble"
    - path: "compose.yml"
      provides: "Single 'app' service with ./data:/data bind mount, env_file, healthcheck, BIND_ADDRESS passthrough"
      contains: "./data:/data"
    - path: ".env.example"
      provides: "Documented FERNET_KEY, TZ, BIND_ADDRESS with generation instructions"
      contains: "FERNET_KEY"
    - path: "app/config.py"
      provides: "pydantic-settings BaseSettings with fail-fast Fernet key validator"
      exports: ["Settings", "settings"]
    - path: "app/db/base.py"
      provides: "Async SQLAlchemy engine, session factory, init_db() with WAL pragma"
      exports: ["engine", "async_session", "init_db"]
    - path: "app/db/models.py"
      provides: "SQLModel classes: Settings, Secret, Run, RateLimitCounter"
      exports: ["Settings", "Secret", "Run", "RateLimitCounter"]
    - path: "app/db/migrations/versions/0001_initial.py"
      provides: "Alembic baseline migration creating all four tables"
  key_links:
    - from: "compose.yml"
      to: "./data host volume"
      via: "volumes: ./data:/data bind mount"
      pattern: "\\./data:/data"
    - from: "app/config.py"
      to: "FERNET_KEY env var"
      via: "pydantic field_validator that instantiates Fernet(key) to validate"
      pattern: "Fernet\\(.*encode"
    - from: "app/db/base.py"
      to: "SQLite WAL mode"
      via: "PRAGMA journal_mode=WAL on first connect inside init_db"
      pattern: "journal_mode"
---

<objective>
Scaffold the Docker + SQLite + Alembic foundation that every later plan in Phase 1 sits on top of. No scheduler, no web UI, no security code yet — just the bootable container shell, the typed-config layer, the DB models, and the baseline migration.

Purpose: Lock FOUND-01 (docker compose boots app) and FOUND-02 (SQLite persists on mounted volume) plus the data model that the security, scheduler, and UI plans will read and write. This plan unblocks plans 01-02 and 01-03 to run in parallel with confidence in the schema.

Output: `docker compose build` succeeds, the image uses the Playwright base (Phase 6 ready), config fails fast on bad Fernet keys, Alembic migration creates all Phase 1 tables, and unit tests for config + models pass.
</objective>

<execution_context>
@C:/Users/abuba/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/abuba/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-CONTEXT.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-RESEARCH.md
@.planning/research/STACK.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Docker image, compose file, pyproject and env scaffolding</name>
  <files>
    Dockerfile,
    compose.yml,
    .env.example,
    .gitignore,
    pyproject.toml,
    requirements.txt
  </files>
  <action>
Create the container + packaging shell exactly as specified in RESEARCH.md "Docker & compose.yml" and "Standard Stack".

**Dockerfile:**
- Base: `mcr.microsoft.com/playwright/python:v1.58.0-noble` (locked by STACK.md — Phase 6 uses Playwright, so ship this base now to avoid a mid-project rebuild).
- Create a non-root `app` user (uid 1000). `WORKDIR /app`.
- COPY requirements.txt first, `pip install --no-cache-dir -r requirements.txt`, then COPY the rest (layer caching).
- `mkdir -p /data && chown -R app:app /data`. `USER app`.
- `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1`.
- `EXPOSE 8000`.
- `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]`.
- Add a leading comment block explaining why `--workers 1` is load-bearing (singleton APScheduler). Per RESEARCH.md pitfall.

**compose.yml:**
Single service named `app`. `build: .`, `image: job-app:dev`, `restart: unless-stopped`, `init: true`, `env_file: .env`, `environment: PYTHONUNBUFFERED: "1"`.
- `ports: - "${BIND_ADDRESS:-0.0.0.0}:8000:8000"` — LAN-bound by default per CONTEXT.md locked decision.
- `volumes: - ./data:/data` — the ONE bind mount per CONTEXT.md.
- Healthcheck: python httpx GET /health, interval 30s, timeout 5s, retries 3, start_period 10s.

**.env.example:**
```
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=

# Container timezone (drives local-midnight rate-limit counter reset)
TZ=America/Los_Angeles

# 0.0.0.0 = LAN-bound (default). 127.0.0.1 = loopback only.
BIND_ADDRESS=0.0.0.0
```

**.gitignore:**
Ignore `data/`, `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `*.egg-info/`.

**requirements.txt** — pinned per RESEARCH.md "Standard Stack":
```
fastapi==0.135.3
uvicorn[standard]==0.36.0
sqlmodel>=0.0.24
sqlalchemy[asyncio]==2.0.36
aiosqlite==0.20.0
alembic==1.14.0
apscheduler==3.11.0
cryptography==44.0.0
pydantic==2.12.0
pydantic-settings==2.13.1
jinja2==3.1.4
structlog==24.4.0
httpx==0.28.1
python-multipart==0.0.17
```

**pyproject.toml** — minimal project table + pytest + ruff + mypy config.
- `[project]` name="job-app", version="0.1.0", requires-python=">=3.12".
- `[tool.pytest.ini_options]` `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
- `[tool.ruff]` line-length=100, target-version="py312", extend-select for basic rules.
- `[tool.mypy]` python_version="3.12", strict_optional=true, ignore_missing_imports=true.

Do NOT include APScheduler 4.x alpha under any circumstance — RESEARCH.md is explicit and CONTEXT.md gives Claude's Discretion here but research resolved it to 3.11.x.
  </action>
  <verify>
`docker compose config` parses compose.yml without errors.
`docker compose build` succeeds and tags job-app:dev.
`grep -q "v1.58.0-noble" Dockerfile` returns exit 0.
`grep -q "./data:/data" compose.yml` returns exit 0.
`grep -q "apscheduler==3.11" requirements.txt` returns exit 0.
  </verify>
  <done>
docker compose can build the image. requirements.txt pins all Phase 1 libraries at RESEARCH.md versions. .env.example documents FERNET_KEY generation and BIND_ADDRESS semantics.
  </done>
</task>

<task type="auto">
  <name>Task 2: Typed config (pydantic-settings) with fail-fast Fernet validation</name>
  <files>
    app/__init__.py,
    app/config.py,
    tests/__init__.py,
    tests/conftest.py,
    tests/unit/test_config.py
  </files>
  <action>
Implement `app/config.py` exactly per RESEARCH.md "Full config.py with fail-fast" code block. It MUST:

1. Subclass `pydantic_settings.BaseSettings`, load from `.env` via `SettingsConfigDict(env_file=".env", extra="ignore")`.
2. Declare typed fields with env aliases:
   - `fernet_key: str` alias `FERNET_KEY` (required, no default)
   - `tz: str` alias `TZ`, default `"UTC"`
   - `bind_address: str` alias `BIND_ADDRESS`, default `"0.0.0.0"`
   - `data_dir: Path`, default `Path("/data")`
   - `log_level: str`, default `"INFO"`
3. `@field_validator("fernet_key")` that calls `Fernet(v.encode())` inside a try/except and raises `ValueError` on empty or malformed keys. This is the fail-fast gate.
4. Export a module-level `settings = Settings()` instance, BUT only instantiate inside a `get_settings()` cached function (lru_cache) so tests can override env vars before import. Pattern:
```python
from functools import lru_cache
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Why `get_settings()` vs top-level `settings`: tests need to set FERNET_KEY via monkeypatch before the Settings instance is built. RESEARCH.md shows both patterns; use the cached-function form for testability.

**tests/conftest.py:**
- Module-level fixture `tmp_fernet_key` that yields `Fernet.generate_key().decode()`.
- Fixture `env_with_fernet(monkeypatch, tmp_fernet_key)` that sets `FERNET_KEY`, `TZ=UTC`, `BIND_ADDRESS=127.0.0.1`, `DATA_DIR=tmp_path`.
- Auto-use nothing — tests opt in.

**tests/unit/test_config.py:**
- `test_missing_fernet_key_raises`: unset env, clear cache, expect `ValidationError`.
- `test_malformed_fernet_key_raises`: set `FERNET_KEY=not-a-key`, expect validation error.
- `test_valid_fernet_key_loads`: set a freshly generated Fernet key, expect `Settings()` to construct and `settings.tz == "UTC"` default.
- Use `importlib.reload` or `get_settings.cache_clear()` between tests.
  </action>
  <verify>
`python -c "from app.config import get_settings; import os; os.environ['FERNET_KEY']='x'; get_settings()"` raises ValueError.
`pytest tests/unit/test_config.py -q` — all three tests pass.
  </verify>
  <done>
Config module fails fast on missing/malformed Fernet key. All three config unit tests pass. get_settings() is the single entry point.
  </done>
</task>

<task type="auto">
  <name>Task 3: SQLModel tables + async engine + Alembic baseline migration</name>
  <files>
    app/db/__init__.py,
    app/db/base.py,
    app/db/models.py,
    alembic.ini,
    app/db/migrations/env.py,
    app/db/migrations/script.py.mako,
    app/db/migrations/versions/0001_initial.py,
    tests/unit/test_models.py
  </files>
  <action>
**app/db/models.py** — implement the four SQLModel classes EXACTLY per RESEARCH.md "SQLModel Schema (Phase 1 tables)":

- `Settings` (table=True, `__tablename__ = "settings"`): `id: int = Field(default=1, primary_key=True)` (single-row convention), `kill_switch: bool = False`, `dry_run: bool = False`, `daily_cap: int = 20`, `delay_min_seconds: int = 30`, `delay_max_seconds: int = 120`, `timezone: str = "UTC"`, `wizard_complete: bool = False`, `keywords_csv: str = ""` (per RESEARCH.md Open Question #2 resolution — column for Phase 1, promote to table later), `updated_at: datetime` default_factory `datetime.utcnow`.

- `Secret` (`__tablename__ = "secrets"`): `id: int primary_key`, `name: str indexed, unique`, `ciphertext: bytes` with `sa_column=Column(LargeBinary, nullable=False)`, `created_at`, `updated_at`. No plaintext column ever.

- `Run` (`__tablename__ = "runs"`): `id`, `started_at: datetime indexed default_factory utcnow`, `ended_at: Optional[datetime]`, `duration_ms: Optional[int]`, `status: str = "running"` (running|succeeded|failed|skipped), `failure_reason: Optional[str]`, `dry_run: bool = False`, `triggered_by: str = "scheduler"`, `counts: dict` with `sa_column=Column(JSON)` default_factory dict.

- `RateLimitCounter` (`__tablename__ = "rate_limit_counters"`): `day: str primary_key` (ISO local-TZ date string), `submitted_count: int = 0`.

Add a module-level `CANONICAL_FAILURE_REASONS = {"killed", "rate_limit", "error", "dry_run_skip", "crashed"}` constant — documented per RESEARCH.md (not enforced at DB level, but a named set for service code to pick from).

**app/db/base.py** — async engine + session + init_db per RESEARCH.md:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import event, text
from app.config import get_settings

_settings = get_settings()
DB_URL = f"sqlite+aiosqlite:///{_settings.data_dir}/app.db"

engine = create_async_engine(DB_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db() -> None:
    # Ensure data dir exists
    _settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        # WAL mode — prevents reader/writer contention between HTMX polling and run writes
        # (RESEARCH.md pitfall: default DELETE mode blocks readers)
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        # Importing models registers them on SQLModel.metadata
        from app.db import models  # noqa: F401
        # Alembic owns real schema; this is for in-memory test DBs
        # await conn.run_sync(SQLModel.metadata.create_all)

async def mark_orphans_failed() -> None:
    """Mark any Run(status='running') rows from a previous crashed container as failed.
    Per RESEARCH.md pitfall: 'DB sentinel run-lock orphan rows'."""
    async with async_session() as s:
        await s.execute(text(
            "UPDATE runs SET status='failed', failure_reason='crashed', "
            "ended_at=CURRENT_TIMESTAMP WHERE status='running'"
        ))
        await s.commit()
```

Note: leave `create_all` commented out in `init_db` — production uses Alembic. Tests use an in-memory fixture that calls `SQLModel.metadata.create_all` via a helper.

**alembic.ini** — standard alembic init, `script_location = app/db/migrations`, `sqlalchemy.url = sqlite:///./data/app.db` (sync URL — Alembic uses sync engine).

**app/db/migrations/env.py** — configure offline + online modes, target_metadata = SQLModel.metadata, **exclude apscheduler_jobs table** via `include_object` filter (RESEARCH.md pitfall: APScheduler manages its own tables):

```python
def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name.startswith("apscheduler_"):
        return False
    return True
```

**app/db/migrations/versions/0001_initial.py** — manually authored (do not run `alembic revision --autogenerate` since the async setup is non-trivial). Create the four tables with all columns, indexes (`ix_runs_started_at`, `ix_secrets_name` unique). Provide proper `upgrade()` and `downgrade()`.

**tests/unit/test_models.py:**
- `test_models_import_cleanly`: import app.db.models, assert all four tables registered on SQLModel.metadata.
- `test_settings_defaults`: construct Settings(), assert all defaults per RESEARCH.md (kill_switch=False, daily_cap=20, delay_min=30, delay_max=120, wizard_complete=False).
- `test_run_counts_is_empty_dict_by_default`: Run() has counts == {}.
- `test_canonical_failure_reasons_set`: the constant exists and contains expected reasons.
  </action>
  <verify>
`python -c "from app.db.models import Settings, Secret, Run, RateLimitCounter; print('ok')"` prints ok.
`alembic -c alembic.ini check` or `alembic upgrade head --sql` renders the DDL without error (offline mode avoids needing a running DB).
`pytest tests/unit/test_models.py -q` all pass.
  </verify>
  <done>
All four Phase 1 tables defined with correct columns, indexes, and defaults. Alembic baseline migration generates the schema and excludes apscheduler_* tables. mark_orphans_failed helper exists. Unit tests validate defaults.
  </done>
</task>

</tasks>

<verification>
- `docker compose build` succeeds against the authored Dockerfile + compose.yml.
- `pytest tests/unit -q` reports all config + model tests passing.
- `alembic upgrade head --sql` (offline) emits CREATE TABLE statements for settings, secrets, runs, rate_limit_counters and does NOT mention apscheduler_jobs.
- `grep -c "apscheduler==3.11" requirements.txt` equals 1 (not 4.x).
- FERNET_KEY empty/bad raises before any import side effect.
</verification>

<success_criteria>
1. The container image builds from the Playwright base and exposes port 8000 under a non-root user.
2. `./data` is the single host bind mount; SQLite will persist there (plans 01-03/04/05 will write to it).
3. `app.config.get_settings()` fails fast on missing/malformed FERNET_KEY.
4. `app.db.models` declares Settings, Secret, Run, RateLimitCounter matching the RESEARCH.md schema verbatim.
5. Alembic `0001_initial` creates all four tables and excludes APScheduler's own tables from target_metadata.
6. Unit tests for config and models all pass.
</success_criteria>

<output>
After completion, write `.planning/phases/01-foundation-scheduler-safety-envelope/01-01-SUMMARY.md` using the summary template. Frontmatter MUST record:
- `subsystem: infrastructure`
- `tech-stack.added: [fastapi 0.135.3, sqlmodel, alembic 1.14, apscheduler 3.11.x (pinned, unused yet), cryptography 44, pydantic-settings, structlog, pico-ready]`
- `affects: [01-02, 01-03]` (security layer imports config; scheduler layer imports db)
- `key files: [Dockerfile, compose.yml, app/config.py, app/db/models.py, app/db/base.py, app/db/migrations/versions/0001_initial.py]`
- Decisions: "APScheduler 3.11.x (not 4.x alpha)", "Single ./data bind mount", "WAL mode at init_db", "get_settings() cached for testability", "keywords_csv as column (promote in Phase 2)"
</output>
</content>
</invoke>