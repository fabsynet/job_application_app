---
phase: 05-email-submission-review-queue
plan: "05-02"
subsystem: submission
tags: [aiosmtplib, smtp, email, python-docx, fernet, mime, starttls]

# Dependency graph
requires:
  - phase: 02-settings-credentials-keywords-profile
    provides: "Secret model + FernetVault + smtp_* credential rows (_upsert_secret stores smtp_port as str)"
  - phase: 04-llm-tailoring-docx-generation
    provides: "TailoringRecord.cover_letter_path points at a python-docx DOCX whose paragraphs become the email body"
provides:
  - "app.submission.builder: build_subject / build_attachment_filename / extract_cover_letter_plaintext / resolve_recipient_email / build_email_message"
  - "app.submission.sender: send_via_smtp + SmtpConfig + SubmissionSendError with stable error_class for failure signatures"
  - "app.submission.creds: load_smtp_creds + SmtpCreds + SmtpCredsMissing (port coerced str->int, pitfall 7)"
  - "New runtime dep: aiosmtplib==5.1.0 (async SMTP client with STARTTLS on 587 / implicit TLS on 465)"
affects: [submission, 05-03 submission-registry, 05-04 submission-pipeline, 05-05 notifications, 05-06 review-queue]

# Tech tracking
tech-stack:
  added: ["aiosmtplib==5.1.0"]
  patterns:
    - "Builder/sender split: pure helpers (builder.py) have zero I/O except DOCX read; side-effect layer (sender.py, creds.py) is the only place network or secret access happens"
    - "Exception-to-error_class wrapping: every aiosmtplib subclass collapses into SubmissionSendError with a stable string identifier so the failure suppression table in 05-05 can hash on it without importing aiosmtplib"
    - "Lazy get_settings import inside load_smtp_creds — matches the 04-05 run_tailoring fix for importlib.reload(app.config) live_app fixtures"
    - "Strict-ASCII slug (_slug_ascii) for attachment filenames — non-ASCII company names fall back to the ASCII residue or 'Unknown' so MIME headers are always RFC-safe"

key-files:
  created:
    - "app/submission/__init__.py"
    - "app/submission/builder.py"
    - "app/submission/creds.py"
    - "app/submission/sender.py"
    - "tests/submission/__init__.py"
    - "tests/submission/test_builder.py"
    - "tests/submission/test_sender.py"
  modified:
    - "requirements.txt"

key-decisions:
  - "Tests live under tests/submission/ (the pytest testpaths root), not app/tests/submission/ as the plan specified — the repo's pytest configuration only discovers the top-level tests/ directory and the conftest.py fixtures (async_session, env_with_fernet) are rooted there"
  - "load_smtp_creds imports get_settings lazily inside the function body, not at module scope — avoids the Phase 4 pitfall of integration-test live_app fixtures calling importlib.reload(app.config) and leaving this module holding a stale function reference with a stale LRU cache"
  - "_slug_ascii falls back to 'Unknown' for empty / pure-unicode inputs so build_attachment_filename always produces a safe [A-Za-z0-9_] stem — e.g. ('', '') -> 'Unknown_Unknown_Resume.docx', ('Café','Nestlé') -> 'Caf_Nestl_Resume.docx'"
  - "SubmissionSendError catches SMTPException as the fallback branch and uses type(exc).__name__ for error_class — future aiosmtplib subclasses (SMTPConnectError, SMTPHeloError, etc.) still get a stable identifier without a code change"
  - "Plain-connection (port != 587 and != 465) is permitted for dev/test only; start_tls and use_tls both default to False in that branch rather than raising — keeps unit tests simple without a real SMTP handshake"
  - "aiosmtplib.send is monkeypatched in tests; no real SMTP server is stood up in the suite, keeping test_sender.py network-free per plan success criteria"

patterns-established:
  - "Pattern: module lazy-imports get_settings inside functions that need fernet_key when the module also ships a live_app integration test — prevents stale LRU cache after importlib.reload(app.config)"
  - "Pattern: exception wrapping with stable error_class attribute — Plan 05-05 will hash (error_class, message[:N], stage) for the failure suppression table"
  - "Pattern: builder helpers keyword-only arguments — eliminates positional-argument mix-ups between role/company and from_addr/to_addr at call sites"

# Metrics
duration: ~22min
completed: 2026-04-15
---

# Phase 5 Plan 05-02: Email Submission Primitives Summary

**Pure-helper email builder + async aiosmtplib sender + Fernet-backed SMTP credential loader, all network-free and fully unit-tested, ready to be composed into the Plan 05-04 submission pipeline.**

## Performance

- **Duration:** ~22 min
- **Completed:** 2026-04-15
- **Tasks:** 2/2 executed
- **Files created:** 7 (4 app modules + 3 test files)
- **Files modified:** 1 (requirements.txt)

## Accomplishments

- Five pure helpers in `app/submission/builder.py` cover the entire email-construction surface: locked `Application for {role} at {company}` subject, strict-ASCII `{FullName}_{Company}_Resume.docx` attachment name, python-docx cover-letter plaintext extraction (`\n\n` separator), first-non-noreply recipient resolver, and a modern `EmailMessage` constructor using `add_attachment` (no legacy MIMEMultipart hand-rolling).
- `app/submission/sender.py` wraps `aiosmtplib.send` with implicit transport selection by port (587 STARTTLS, 465 implicit TLS, anything else plain) and collapses every aiosmtplib exception into a single `SubmissionSendError` carrying a stable `error_class` string — the exact shape Plan 05-05's failure suppression table needs.
- `app/submission/creds.py` decrypts the four `smtp_*` Secret rows via FernetVault, coerces `smtp_port` to `int` (research pitfall 7), and raises `SmtpCredsMissing(name=...)` with a typed `.name` attribute so the pipeline can flip a job to `needs_info` without parsing exception messages.
- 29 unit tests green (17 builder + 12 sender/creds); full project suite 245 passed in ~59s with zero real network traffic.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add aiosmtplib dep and email builder primitives** — `6c38d70` (feat)
2. **Task 2: SMTP credential loader + async sender wrapper** — `12064fa` (feat)

## Files Created/Modified

- `requirements.txt` — added `aiosmtplib==5.1.0` (first entry, alphabetical by package name)
- `app/submission/__init__.py` — package marker with 1-line docstring
- `app/submission/builder.py` — five pure helpers; only `extract_cover_letter_plaintext` performs I/O (DOCX read); lazy `from docx import Document` inside the function keeps the module importable without python-docx in memory
- `app/submission/creds.py` — `load_smtp_creds`, `SmtpCreds` (frozen dataclass), `SmtpCredsMissing`; uses lazy `get_settings` import inside the function body
- `app/submission/sender.py` — `send_via_smtp`, `SmtpConfig`, `SubmissionSendError`; wraps `SMTPAuthenticationError`, `SMTPRecipientsRefused`, `SMTPServerDisconnected`, `SMTPTimeoutError`, and a catch-all `SMTPException` that preserves `type(exc).__name__`
- `tests/submission/__init__.py` — empty package marker
- `tests/submission/test_builder.py` — 17 tests: subject formatting + defaults, ASCII slug (including unicode strip / empty fallback / punctuation), non-noreply resolver (all 5 noreply variants + first-match-wins + None cases), cover-letter paragraph join (drops blank + whitespace-only paragraphs), EmailMessage MIME shape + newline preservation, module exports
- `tests/submission/test_sender.py` — 12 tests: monkeypatched `aiosmtplib.send` fake captures all kwargs; asserts STARTTLS on 587, implicit TLS on 465, plain on others, custom timeout passthrough, and one wrapping test for every caught exception branch; plus three `load_smtp_creds` tests using the in-memory `async_session` + `env_with_fernet` fixtures from `tests/conftest.py`

## Decisions Made

- **Tests relocated from `app/tests/submission/` to `tests/submission/`** — the repository's `pyproject.toml` pins `testpaths = ["tests"]` and the shared fixtures (`async_session`, `env_with_fernet`, `async_session_factory`) live only in `tests/conftest.py`. A test tree under `app/tests/` is neither discovered nor fixture-reachable, so the plan's location was adjusted to match the existing convention.
- **Lazy `get_settings` import inside `load_smtp_creds`** — identical to the 04-05 `run_tailoring` pattern documented in STATE.md. The direct reason is that `tests/test_phase2_resume.py::live_app` calls `importlib.reload(app.config)`, which swaps `app.config.get_settings` for a new function object; any module that bound the old reference at import time ends up encrypting with one key and decrypting with another. Lazy import inside the function body dereferences the *current* `app.config.get_settings` attribute on each call.
- **`_slug_ascii` never raises** — empty, whitespace-only, and pure-non-ASCII inputs all fall through to the `"Unknown"` fallback rather than raising a ValueError. A crashing attachment filename would be a worse failure than a slightly ugly one, and the job can always be inspected in the review queue.
- **Builder helpers are keyword-only** — `build_subject(*, role, company)`, `build_email_message(*, from_addr, to_addr, ...)`, etc. This rules out positional-argument mix-ups at the 05-04 pipeline call site where `from_addr` and `to_addr` could otherwise swap silently.
- **No real SMTP server in tests** — the sender test harness monkeypatches `aiosmtplib.send` with an async callable that records kwargs and optionally raises; this is sufficient to exercise transport selection and error classification without any network I/O.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test directory moved from `app/tests/submission/` to `tests/submission/`**
- **Found during:** Task 2 verification (`pytest app/tests/submission/`)
- **Issue:** The plan specified `app/tests/submission/` for test files, but `pyproject.toml` sets `testpaths = ["tests"]` and the shared async_session/env_with_fernet fixtures live in `tests/conftest.py`. Running tests from `app/tests/` produced `fixture 'env_with_fernet' not found` errors for the `load_smtp_creds` cases.
- **Fix:** `git mv` (and plain `mv` for test_sender.py which was still untracked) all three files from `app/tests/submission/` to `tests/submission/`. Removed the now-empty `app/tests/` subtree.
- **Files modified:** `tests/submission/__init__.py`, `tests/submission/test_builder.py`, `tests/submission/test_sender.py` (created) + `app/tests/` (deleted)
- **Verification:** `pytest tests/submission/ -v` → 29 passed
- **Committed in:** `6c38d70` (Task 1 — rename captured via git-mv during same commit) + `12064fa` (Task 2)

**2. [Rule 1 - Bug] `load_smtp_creds` stale `get_settings` reference under live_app reloads**
- **Found during:** Task 2 verification (`pytest` full suite)
- **Issue:** The initial `creds.py` imported `get_settings as get_app_settings` at module scope. When `tests/test_phase2_resume.py::live_app` ran before the submission tests, it called `importlib.reload(app.config)`, replacing `app.config.get_settings` with a new function object. The stale module-level reference still pointed at the pre-reload LRU-cached function, which returned a prior FERNET_KEY. My `_seed_smtp_secret` helper imported `get_settings` fresh each call (new key), so encryption used key A and `load_smtp_creds` decryption used key B → `InvalidFernetKey`. Exactly the Phase 4 pitfall documented in STATE.md 04-05 blockers (`app.resume.service`).
- **Fix:** Removed the module-level `from app.config import get_settings as get_app_settings` and replaced with a lazy `from app.config import get_settings as _get_settings` inside the `load_smtp_creds` function body, matching the 04-05 `run_tailoring` pattern.
- **Files modified:** `app/submission/creds.py`
- **Verification:** Full suite `pytest` → 245 passed; submission cred tests run green both in isolation and after `test_phase2_resume.py`.
- **Committed in:** `12064fa` (Task 2 commit — lazy import was in the initial Task 2 push-up of creds.py after discovering the failure during full-suite run)

---

**Total deviations:** 2 auto-fixed (1 blocking directory convention, 1 bug from cross-test `importlib.reload` pollution)
**Impact on plan:** Both fixes were essential for test discoverability and correctness. No scope creep — module surface and exports are exactly what the plan specified.

## Issues Encountered

- **ruff not available in venv** — the verification step called for `ruff check app/submission/` but ruff is not installed in this host's venv. Python import check and pytest both pass, and no ruff violations are apparent on inspection. Non-blocking; logged here so the next phase's lint setup can close the gap.
- **`aiosmtplib.SMTPRecipientsRefused` construction** — the test for this branch originally passed a dict; the actual constructor takes a list of refused-recipient records. Fixed inline with an empty list argument.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready to be consumed by:**
- Plan 05-03 (submission registry) — can import `SubmissionSendError` for its state-machine exception catalog
- Plan 05-04 (submission pipeline) — composes `build_subject` + `build_attachment_filename` + `extract_cover_letter_plaintext` + `resolve_recipient_email` + `build_email_message` + `load_smtp_creds` + `send_via_smtp` into one `async def submit_one_job(job, tailoring_record)` call
- Plan 05-05 (failure notifications) — can hash `(SubmissionSendError.error_class, message[:N], stage)` for the suppression table

**Blockers/concerns for next plans:**
- Per-job `from_addr` must come from the user's Phase 2 profile email (not the SMTP username) — Plan 05-04 should resolve this before calling `build_email_message`
- `SmtpConfig` has no retry/backoff. Plan 05-04 or 05-05 must decide whether transient errors (`SMTPServerDisconnected`, `SMTPTimeoutError`) get in-run retries or just bubble up to the pipeline's normal failure path
- The plain-port fallback (no TLS) is dev-only; Plan 05-04 should reject ports outside `{25, 465, 587, 2525}` at configuration save time rather than trusting this layer's permissiveness

## Self-Check: PASSED

All declared `key-files.created` exist on disk:
- `app/submission/__init__.py`
- `app/submission/builder.py`
- `app/submission/creds.py`
- `app/submission/sender.py`
- `tests/submission/__init__.py`
- `tests/submission/test_builder.py`
- `tests/submission/test_sender.py`

All Task commits resolve in `git log`:
- `6c38d70` → Task 1 (feat(05-02): add aiosmtplib dep and email builder primitives)
- `12064fa` → Task 2 (feat(05-02): add SMTP credential loader and async sender wrapper)

---
*Phase: 05-email-submission-review-queue*
*Completed: 2026-04-15*
