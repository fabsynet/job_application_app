# Setup & Exhaustive Testing Guide

How to set up the Job Application Auto-Apply app on a MacBook Pro (or any machine) and test every feature across all six phases.

---

## Prerequisites

| Requirement | Why |
|-------------|-----|
| **Docker Desktop for Mac** (recommended) | Bundles Playwright + Chromium. Works on both Intel and Apple Silicon (M1/M2/M3/M4). |
| OR **Python 3.12+** via Homebrew | For local dev without Docker. You must install Playwright browsers separately. |
| **A .docx resume** | Needed for the setup wizard and tailoring pipeline. |
| **Anthropic API key** | For LLM tailoring (Phase 4+). Get one at https://console.anthropic.com/settings/keys |
| **SMTP credentials** | For email submission (Phase 5+). Gmail app passwords work: https://myaccount.google.com/apppasswords |

---

## Option A: Docker on Mac (Recommended)

Works on both Intel Macs and Apple Silicon (M1/M2/M3/M4). The Playwright base image ships arm64 and amd64 variants — Docker Desktop pulls the right one automatically.

### 1. Install Docker Desktop

Download from https://www.docker.com/products/docker-desktop/ and install.

Open Docker Desktop, wait until the whale icon in the menu bar shows "Docker Desktop is running".

### 2. Get the code onto your Mac

```bash
# Option 1: clone
git clone <your-repo-url>
cd job_application_app

# Option 2: copy from USB / AirDrop / network share
# then cd into the folder
```

### 3. Generate a Fernet encryption key

macOS ships with Python 3 (or install via Homebrew: `brew install python`):

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

If you don't have Python or cryptography installed yet, generate inside Docker:

```bash
docker run --rm python:3.12-slim python -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output key.

### 4. Create .env

```bash
cp .env.example .env
```

Open `.env` in any editor (TextEdit, VS Code, nano) and paste the key:

```
FERNET_KEY=<paste-your-key-here>
TZ=America/Los_Angeles
BIND_ADDRESS=0.0.0.0
```

### 5. Build and start

```bash
docker compose up -d --build
```

**First build takes 3-5 minutes** on Apple Silicon (downloads the ~1.5 GB Playwright base image and installs Python deps). Subsequent builds use cache and take seconds.

Watch logs until the app is ready:

```bash
docker compose logs -f
```

Wait for this line:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 6. Open the app

Open Safari or Chrome and go to: http://localhost:8000

You should see the setup wizard on first boot.

### Useful commands

```bash
docker compose logs -f              # Stream live logs
docker compose restart              # Restart (all data persists)
docker compose down                 # Stop the app
docker compose exec app bash        # Open a shell inside the container
docker compose exec app python -m pytest tests/ -v   # Run test suite inside container
rm -rf ./data && docker compose up -d   # Full reset (wipe all data, fresh start)
```

### Headed Playwright on Mac (Docker)

To watch Playwright fill forms visually, you need to forward the display from the Docker container. The simplest approach:

1. Set headless=off in Settings > Playwright (inside the app UI).
2. Screenshots are still captured at `data/screenshots/{job_id}/` — you can inspect them even in headless mode.
3. For a live browser window, use **Option B (local Python)** instead — Playwright opens a real Chromium window on your Mac desktop.

---

## Option B: Local Python on Mac (No Docker)

Best for visual Playwright debugging — opens real browser windows on your desktop.

### 1. Install Python 3.12+ via Homebrew

```bash
# Install Homebrew if you don't have it:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.12
```

Verify:

```bash
python3 --version
# Should show Python 3.12.x or higher
```

### 2. Create virtual environment

```bash
cd job_application_app
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` in your terminal prompt.

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright system dependencies + Chromium

```bash
# Install Chromium browser (downloads ~200 MB)
playwright install chromium

# Install system dependencies Playwright needs on macOS
playwright install-deps chromium
```

If `playwright install-deps` asks for your password, that's normal — it installs system libraries via Homebrew.

### 5. Set environment variables

```bash
export FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export DATA_DIR=./data
export TZ=America/Los_Angeles
```

To persist these across terminal sessions, add them to `~/.zshrc`:

```bash
echo 'export FERNET_KEY="<your-key>"' >> ~/.zshrc
echo 'export DATA_DIR="./data"' >> ~/.zshrc
echo 'export TZ="America/Los_Angeles"' >> ~/.zshrc
```

### 6. Start the app

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 7. Open the app

http://localhost:8000

### Running the test suite locally

```bash
# Make sure venv is activated
source .venv/bin/activate

# Run all tests
python -m pytest tests/ -v

# Run just the Phase 6 integration tests
python -m pytest tests/integration/test_phase6_requirements.py -v

# Run with output (useful for debugging)
python -m pytest tests/ -v -s
```

Expected: 579+ tests, all passing.

---

## Exhaustive Manual Testing Checklist

Work through each section in order. Each phase builds on the previous one.

### Phase 1-2: Foundation & Configuration

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 1 | First boot wizard | Open http://localhost:8000 with empty data/ | Redirects to /setup/1 |
| 2 | Resume upload (wizard) | Upload a .docx in step 1 | File accepted, text preview shown |
| 3 | API keys (wizard) | Enter Anthropic API key in step 2 | Saved (fields are optional, can skip) |
| 4 | Keywords (wizard) | Type keywords in step 3, one per line | Saved, redirects to dashboard |
| 5 | Skip wizard | Wipe data/ (`rm -rf ./data`), restart, click "Skip setup" | Goes directly to dashboard |
| 6 | Dashboard | Visit / after wizard | Heartbeat timer, run counts, toggles visible |
| 7 | Kill switch | Toggle kill switch ON in dashboard | Next scheduled run is skipped |
| 8 | Dry-run mode | Toggle dry-run ON | Runs execute but submission stage is skipped |
| 9 | Settings > Profile | Fill: name, email, phone, LinkedIn, GitHub, portfolio, work auth, salary, experience | All fields saved, persist on page refresh |
| 10 | Settings > Resume | Upload/replace a .docx | New file shown in preview, old file replaced |
| 11 | Settings > Keywords | Add "python", "fastapi", "docker" as chips | Chips appear, each deletable with X |
| 12 | Settings > Match threshold | Drag slider to 70% | Value persists on refresh |
| 13 | Settings > Credentials > Anthropic | Enter a valid API key | Shows "Configured" with green indicator |
| 14 | Settings > Credentials > SMTP | Enter host, port, user, password | Shows "Configured" after validation |
| 15 | Settings > Budget | Set monthly cap (e.g. $5.00) | Progress bar shows $0.00 / $5.00 |
| 16 | Settings > Schedule | Toggle hourly schedule on/off | Scheduler starts/stops |
| 17 | Settings > Quiet hours | Set quiet hours (e.g. 22:00 - 07:00) | Persists on refresh |
| 18 | Mode toggle | Switch between "Full Auto" and "Review Queue" | Toggle persists, visible on dashboard |
| 19 | Restart persistence | `docker compose restart` (or Ctrl+C and re-run uvicorn), reload page | All settings, secrets, resume still present |

### Phase 3: Discovery & Matching

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 20 | Add a Greenhouse source | Settings > Sources > type a company slug (e.g. "stripe") | Validates via API, green checkmark |
| 21 | Add a Lever source | Add a Lever company slug (e.g. "netlify") | Validates, shows as active source |
| 22 | Add an Ashby source | Add an Ashby company slug | Validates and saves |
| 23 | Trigger a run | Dashboard > click "Run Now" | Run starts, progress visible in logs |
| 24 | Jobs appear | Visit /jobs after run completes | Table with title, company, score, source columns |
| 25 | Job detail expand | Click any job row | Full description, keywords highlighted in yellow |
| 26 | Dedup works | Run again with same sources | Job count does NOT double |
| 27 | Score filtering | Set threshold to 80%, run again | Only jobs scoring >= 80% are queued |
| 28 | Source toggle | Disable a source, run | No new jobs from that source |
| 29 | Run detail | Dashboard > click a completed run | Per-source counts, duration, anomaly info |
| 30 | Manual queue | On /jobs, click "Queue" on a below-threshold job | Job status changes to "matched" |

### Phase 4: LLM Tailoring

Requires: Anthropic API key configured, at least one queued/matched job, a base resume uploaded.

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 31 | Tailoring runs | Trigger a run (or wait for scheduled) | Matched jobs move to "tailored" status |
| 32 | Tailored preview | Click a tailored job on /jobs | Shows tailored resume preview |
| 33 | Download DOCX | Click download button | .docx file downloads, opens in Word/Pages/LibreOffice |
| 34 | Format preserved | Open downloaded DOCX | Same fonts, bullets, and layout as base resume |
| 35 | No hallucination | Read the tailored content | No invented companies, titles, or skills |
| 36 | Cover letter | Check if cover letter was generated | Visible in the tailoring detail view |
| 37 | Budget tracking | Visit Settings > Budget | Spent amount updated, progress bar reflects usage |
| 38 | Budget halt | Set budget to $0.01, trigger run | Tailoring stops with "Budget exhausted" banner |
| 39 | Settings > Tailoring | Change intensity (light/balanced/full) | Persists on refresh |

### Phase 5: Submission, Review & Notifications

Requires: SMTP credentials configured, at least one tailored job.

For Gmail SMTP: host=smtp.gmail.com, port=587, user=your@gmail.com, password=your-app-password.

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 40 | Review queue | Visit /review | Tailored jobs listed with approve/reject buttons |
| 41 | Diff view | Click a review item | Side-by-side base vs tailored diff |
| 42 | Inline DOCX edit | Edit a section in the review drawer, save | Changes saved (creates manual_edit record) |
| 43 | Approve | Click approve on a job | Status flips to "approved" |
| 44 | Reject + skip | Reject with mode=skip | Job moves to "skipped" |
| 45 | Reject + re-tailor | Reject with mode=retailor | Job moves to "retailoring", picked up on next run |
| 46 | Batch approve | Select multiple jobs, click batch approve | All selected flip to "approved" |
| 47 | Email submission | With approved job, trigger run | Email sent to job's contact address |
| 48 | Check inbox | Open your notification email inbox | Per-job summary email: job title, company, match score, DOCX attached |
| 49 | Full-auto mode | Switch to full-auto, trigger run | Tailored jobs auto-submit without review step |
| 50 | Daily cap | Set daily cap to 1, trigger run with 2 approved jobs | First submits, second stays approved, cap banner shows |
| 51 | Raise cap banner | Click "Raise cap" on the banner | Cap setting page opens |
| 52 | Manual apply | Visit /manual-apply | Paste-a-link form shown |
| 53 | Paste valid URL | Paste a real Greenhouse job URL | Fetches job, shows preview with title/company/description |
| 54 | Confirm manual | Click confirm on preview | Job created, enters tailoring pipeline |
| 55 | Paste bad URL | Paste a LinkedIn URL (will fail fetch) | Fallback textarea form shown (no 500 error) |
| 56 | Fallback submit | Fill title + company in fallback form, submit | Manual job created with score=100 |
| 57 | Applied page | Visit /applied | Table of all submitted applications |
| 58 | Applied filters | Filter by source, status; sort by date/score | Filters work correctly |
| 59 | Applied detail | Click any applied row | Full job description, tailored DOCX preview + download |
| 60 | Failure notification | Break SMTP creds, trigger run | Failure email sent (or suppressed if same signature) |
| 61 | Notification ack | Click ack on a notification | Marked as acknowledged |
| 62 | Idempotency | Force a re-run against same approved job | No duplicate email sent |
| 63 | Quiet hours | Set quiet hours to current time, trigger run | Submission stage skipped entirely |

### Phase 6: Playwright Browser Submission & Learning Loop

Requires: Docker (recommended) OR local Python with `playwright install chromium`. A real ATS job posting to submit to.

**Settings UI:**

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 64 | Settings > Playwright | Click Playwright section in settings sidebar | Three controls visible: Headless, Pause on Unknown, Retention |
| 65 | Headless default | Check initial state | Checkbox is checked (headless=True) |
| 66 | Toggle headless off | Uncheck, save | Unchecked persists on refresh |
| 67 | Pause if unsure default | Check initial state | Checkbox is checked (pause_if_unsure=True) |
| 68 | Toggle pause off | Uncheck, save | Unchecked persists on refresh |
| 69 | Retention default | Check initial value | Shows 30 |
| 70 | Change retention | Set to 7, save | Shows 7 on refresh |
| 71 | Retention bounds | Try 0 or 999, save | Clamped to 1-365 |

**Saved Answers UI:**

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 72 | Settings > Saved Answers | Click Saved Answers section | "No saved answers yet" empty state |
| 73 | (Answers appear after unknown field resolution -- see items 84-85) | | |

**Needs Info Queue:**

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 74 | Needs Info page (empty) | Visit /needs-info | "No halted applications" message |
| 75 | Nav link | Check navigation bar on any page | "Needs Info" link present |

**Playwright Form Submission (end-to-end):**

Playwright auto-activates for Greenhouse/Lever/Ashby jobs. Email is the fallback for everything else.

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 76 | Playwright submits ATS job | Have a tailored+approved Greenhouse job, trigger run | Playwright opens form, fills fields, submits |
| 77 | Headed mode (local Python only) | Set headless=off in Settings, trigger run | Real Chromium window opens on your desktop, watch it fill the form |
| 78 | StorageState persists | Check data/browser/storageState.json after success | File exists with cookies/session data |
| 79 | Screenshots captured | Check data/screenshots/{job_id}/ | step_1.png, step_2.png, etc. exist |
| 80 | CAPTCHA halt | Submit to a form with CAPTCHA protection | Job fails with error_class="captcha" in run log |

**Learning Loop (end-to-end):**

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 81 | Unknown field halt | Submit to an ATS form with custom questions (pause_if_unsure=on) | Job halts at "needs_info" status |
| 82 | Needs Info queue populated | Visit /needs-info | Halted job appears with unknown field count |
| 83 | Needs Info detail | Click the halted job | Unknown fields shown: label, type, screenshot, required badge |
| 84 | Answer all unknowns | Fill every field in the answer form, submit | Fields resolved, job flips to "approved" |
| 85 | Saved Answers created | Visit Settings > Saved Answers | New answers visible with field labels and your text |
| 86 | Edit a saved answer | Click edit, change text, save | Updated text shown |
| 87 | Delete a saved answer | Click delete on one answer | Removed from list |
| 88 | Retry after answering | After answering, click retry (or trigger run) | Playwright retries submission with the answers |
| 89 | Semantic matching | Submit to a DIFFERENT job with a similar question | Previously saved answer auto-fills (check run log for "reused") |
| 90 | Reuse count | Check Settings > Saved Answers after auto-fill | "Times Reused" counter incremented |
| 91 | Success email with reused answers | Check notification email after auto-match submit | "Saved Answers Applied" section lists the reused answers |

### Cross-Cutting & Regression

| # | What to test | Steps | Expected result |
|---|-------------|-------|-----------------|
| 92 | Full pipeline cycle | Configure everything, set full-auto, wait 1 hour | Discovery -> match -> tailor -> submit runs automatically |
| 93 | Container restart | `docker compose restart`, check all pages | All data, settings, secrets intact |
| 94 | No PII in logs | Docker: `docker compose exec app cat /data/logs/app.log`. Local: `cat data/logs/app.log` | No names, emails, phone numbers in log output |
| 95 | Secret encryption | `sqlite3 data/app.db "SELECT value FROM secrets;"` | Values are Fernet-encrypted blobs, not plaintext |
| 96 | Rate limit respected | Set daily cap to 2, trigger multiple runs | Only 2 submissions per day |
| 97 | Fernet key loss | Change FERNET_KEY in .env (or env var), restart | Dashboard shows rotation banner, secrets unreadable but app still runs |
| 98 | All pages render | Visit every page: /, /jobs, /review, /needs-info, /manual-apply, /applied, /settings | No 500 errors, all render correctly |

---

## Tips for Phase 6 Testing

**Headed mode (watch Playwright fill forms):**
- **Local Python (Option B):** Set headless=off in Settings > Playwright. Playwright opens a real Chromium window on your Mac desktop. Best for visual debugging.
- **Docker (Option A):** The container has no display. Screenshots are still saved to `data/screenshots/`. To watch live, use Option B.

**Finding test ATS forms with open roles:**
- Greenhouse: `https://boards.greenhouse.io/{company}/jobs` -- try "stripe", "airbnb", "figma"
- Lever: `https://jobs.lever.co/{company}` -- try "netlify"
- Ashby: `https://jobs.ashbyhq.com/{company}`

**Learning loop full cycle:**
1. First submission hits an unknown custom question on the form
2. Job halts at `needs_info` status
3. You answer in /needs-info UI
4. Retry succeeds
5. Next similar job auto-fills from the saved answer (check run log)

**Screenshot inspection:**
```bash
# Docker:
ls data/screenshots/
open data/screenshots/1/step_1.png    # macOS opens in Preview

# Or use Quick Look:
qlmanage -p data/screenshots/1/step_1.png
```

---

## Mac-Specific Troubleshooting

| Problem | Solution |
|---------|----------|
| **Docker Desktop not starting** | Open Docker Desktop app from Applications, wait for the whale icon. Check System Preferences > Privacy > allow Docker if prompted. |
| **"Cannot connect to the Docker daemon"** | Docker Desktop isn't running. Open it and wait for the green "running" indicator. |
| **Build fails on Apple Silicon** | The Playwright image supports arm64 natively. If issues persist: `docker compose build --no-cache` |
| **Port 8000 in use** | Check what's using it: `lsof -i :8000`. Kill it or change port in compose.yml: `"8001:8000"` |
| **`python3` not found** | Install via Homebrew: `brew install python@3.12` |
| **`playwright install` fails** | Run `playwright install-deps chromium` first (installs system libraries via Homebrew) |
| **Permission denied on data/** | `chmod -R 755 ./data` or `sudo chown -R $(whoami) ./data` |
| **FERNET_KEY error on startup** | Generate a new key: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| **SMTP validation fails** | Gmail: use smtp.gmail.com, port 587, your email, and an App Password (not your regular password). Create at https://myaccount.google.com/apppasswords |
| **SQLite "database is locked"** | Only one instance should run at a time. Check: `docker compose ps` or `ps aux \| grep uvicorn` |
| **Playwright "Executable doesn't exist"** | Docker: rebuild with `docker compose build --no-cache`. Local: run `playwright install chromium`. |
| **No jobs discovered** | Ensure Sources are configured in Settings. Try known slugs: "stripe" (Greenhouse). Check run logs for errors. |
| **Tailoring not running** | Check: (1) Anthropic API key configured, (2) budget not exhausted, (3) kill switch off, (4) matched jobs exist |
| **Budget exhausted** | Increase budget in Settings > Budget, or wait for month rollover (automatic on 1st of month) |
| **`.docx opens in Pages but looks wrong`** | Normal for Pages -- the formatting target is Microsoft Word. Try LibreOffice if you need pixel-perfect DOCX rendering on Mac. |
