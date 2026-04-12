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

On first boot you will be walked through the setup wizard (resume upload,
API keys, keywords). The wizard is optional -- click "Skip setup" to go
straight to the dashboard.

## Data persistence

Everything lives under `./data`:

```
data/
  app.db            # SQLite (settings, secrets, runs, rate limit counters)
  logs/app.log      # structured JSON logs (PII/secrets scrubbed)
  uploads/          # base DOCX resume
  browser/          # (Phase 6) Playwright storageState
```

Back it up, wipe it to reset, or copy it to another machine to migrate.

## Important: Fernet key rotation

Your `FERNET_KEY` env var encrypts API keys and SMTP credentials in SQLite.
**If you change or lose the key, stored secrets become unreadable.** The app
will show a dashboard banner and keep running, but you will need to re-enter
your secrets in Settings. There is no rotation tool in v1.

To generate a new key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## .env.example

The only required variable is `FERNET_KEY`. Optional:

| Variable       | Default     | Description                                       |
|----------------|-------------|---------------------------------------------------|
| `FERNET_KEY`   | (required)  | 32-byte URL-safe base64 Fernet key                |
| `TZ`           | `UTC`       | IANA timezone for midnight reset + scheduler cron  |
| `BIND_ADDRESS` | `0.0.0.0`   | Network interface; `127.0.0.1` for loopback only  |
| `DATA_DIR`     | `/data`     | Container data volume (override for local dev)     |
| `LOG_LEVEL`    | `INFO`      | Python log level name                              |

## First-run setup wizard

When `./data` is empty the dashboard redirects to `/setup/1`:

1. **Step 1 -- Resume:** upload a `.docx` base resume.
2. **Step 2 -- API keys:** enter Anthropic API key and SMTP credentials
   (all fields optional, encrypted at rest with Fernet).
3. **Step 3 -- Keywords:** one keyword per line for job matching.

After step 3 the wizard marks setup as complete and redirects to the
dashboard. Subsequent container restarts skip the wizard automatically.

You can also hit **Skip setup** at any step to go directly to the dashboard.

## Kill switch and dry-run mode

Both toggles are on the dashboard home page:

- **Kill switch:** immediately cancels any in-flight run, pauses the
  scheduler, and persists across restarts. Release to resume.
- **Dry run:** the next pipeline run is stamped `dry_run=True`. Downstream
  stages (Phase 2+) will execute without side effects.

## Security posture

- Single-user per deployment. LAN-bound by default (`BIND_ADDRESS=0.0.0.0`);
  set `BIND_ADDRESS=127.0.0.1` for loopback only.
- Secrets encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256).
- Global log scrubber guarantees API keys, passwords, and registered
  plaintexts never appear in stdout or log files.
- No authentication in v1 (single-user LAN assumption). Do not expose to
  the public internet.

## Rate-limit envelope

Default safety bounds (configurable on Settings page):

| Parameter     | Default | Range      |
|---------------|---------|------------|
| Daily cap     | 20      | 0--10000   |
| Min delay (s) | 30      | 1--599     |
| Max delay (s) | 120     | 2--600     |

The counter resets at local midnight (per `TZ`).

## Development

```bash
# Create virtualenv and install deps
python -m venv .venv
source .venv/bin/activate      # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run the test suite
pytest

# Lint
ruff check .

# Apply migrations (container does this on boot)
alembic upgrade head
```

See `.planning/phases/01-foundation-scheduler-safety-envelope/` for the
Phase 1 plans and summaries.
