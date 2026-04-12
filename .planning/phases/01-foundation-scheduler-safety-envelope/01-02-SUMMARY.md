---
phase: 01-foundation-scheduler-safety-envelope
plan: 02
subsystem: security
tags: [fernet, cryptography, structlog, logging, secret-scrubber, redaction, safe-03, found-06]

# Dependency graph
requires:
  - phase: 01-foundation-scheduler-safety-envelope
    provides: "Python runtime, structlog + cryptography dependencies (from plan 01-01 scaffolding, installed on demand here)"
provides:
  - "SecretRegistry singleton (app.security.log_scrubber.REGISTRY) with thread-safe runtime registration"
  - "RedactingFilter: stdlib logging.Filter mutating record.msg/args in place"
  - "structlog_scrub_processor: typed-value scrubber for structlog chain"
  - "configure_logging(level, log_dir): root-logger wiring + structlog chain with scrub BEFORE JSONRenderer"
  - "FernetVault: fail-fast from_env, encrypt, decrypt, and startup helper register_all_secrets_with_scrubber"
  - "InvalidFernetKey: unified boot exception for missing/malformed/rotated keys"
  - "The mandated zero-PII-in-logs assertion test suite (6 tests, end-to-end integration included)"
affects: [01-03, 01-04, 01-05, 01-06, 02-all, 03-all, 04-all, 05-all, 06-all]

# Tech tracking
tech-stack:
  added:
    - "structlog 25.5.0 (chain configured with scrub processor before JSONRenderer)"
    - "cryptography 44.x Fernet (wrapped in FernetVault)"
    - "stdlib logging.Filter wired on root logger"
  patterns:
    - "Two-layer scrubber: stdlib Filter + structlog processor pulling from one registry"
    - "Scrubber auto-registration from the only code that can produce plaintexts (FernetVault)"
    - "Fail-fast boot exceptions (InvalidFernetKey) collapse cryptography stack traces"

key-files:
  created:
    - "app/__init__.py"
    - "app/security/__init__.py"
    - "app/security/log_scrubber.py"
    - "app/security/fernet.py"
    - "app/logging_setup.py"
    - "tests/unit/test_log_scrubber.py"
    - "tests/unit/test_fernet_vault.py"
  modified: []

key-decisions:
  - "SecretRegistry is a module-level singleton guarded by threading.Lock"
  - "structlog_scrub_processor precedes JSONRenderer so typed values are scrubbed, not rendered strings"
  - "4-character minimum on literal registration to prevent common-word redaction soup"
  - "FernetVault auto-registers plaintext on encrypt (pre), decrypt (post), and from_env (master key)"
  - "InvalidToken is translated into InvalidFernetKey with a 'may have changed' message for operator clarity"
  - "Uvicorn/APScheduler/SQLAlchemy loggers throttled to WARNING and forced to propagate through root"

patterns-established:
  - "Two-layer scrubber: stdlib Filter catches uvicorn/SQLA/APScheduler, structlog processor catches structured events; both read from a single SecretRegistry singleton"
  - "Every path that can produce a plaintext secret (FernetVault.encrypt/decrypt/from_env) registers the plaintext with the scrubber before returning"
  - "Static regex fallback patterns (Anthropic sk-ant-*, OpenAI sk-*, Fernet gAAAAA*, password=value) catch unregistered leaks"
  - "Test isolation via autouse fixture that calls REGISTRY.clear_literals() — static patterns survive the clear"

# Metrics
duration: 4min
completed: 2026-04-11
---

# Phase 1 Plan 02: Security & Log Scrubber Summary

**Two-layer secret scrubber (stdlib Filter + structlog processor) backed by a threaded SecretRegistry singleton, FernetVault with auto-registration on every plaintext path, and the mandated zero-PII-in-logs assertion suite asserted end-to-end against a real app.log file on disk.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-11T23:59:29Z
- **Completed:** 2026-04-12T00:03:31Z
- **Tasks:** 3
- **Files created:** 7 (2 app/ modules, 3 security/logging modules, 2 test files)

## Accomplishments
- Shipped the SAFE-03 enforcement layer before any code that handles a secret can run.
- SecretRegistry supports runtime registration (CONTEXT.md locked decision: UI-entered keys added at entry time).
- Static regex fallback patterns cover Anthropic, OpenAI-shape, Fernet tokens, and password=value leaks without requiring registration.
- FernetVault round-trips encrypt/decrypt, fails loud on missing/malformed keys, and surfaces rotation failures with an operator-friendly message.
- End-to-end integration test writes to a real `app.log` file via `configure_logging`, logs a sentinel, and asserts the sentinel never reaches disk — the exact testable property CONTEXT.md mandates.

## Task Commits

Each task was committed atomically:

1. **Task 1: Log scrubber + logging setup** - `fb9410f` (feat)
2. **Task 2: FernetVault + unit tests** - `a0470d4` (feat)
3. **Task 3: Zero-PII assertion suite** - `820bd09` (test)

Note: Commit `fb9410f` also captured scaffolding files (`.env.example`, `.gitignore`, `Dockerfile`, `compose.yml`, `pyproject.toml`, `requirements.txt`) that were created concurrently by plan 01-01 running in parallel Wave 1. These files were not produced by this plan but were swept into the first commit because they appeared in the working tree at commit time. See "Issues Encountered" below.

## Files Created/Modified
- `app/__init__.py` — package root marker (needed for `app.security` imports)
- `app/security/__init__.py` — re-exports REGISTRY, RedactingFilter, SecretRegistry, structlog_scrub_processor
- `app/security/log_scrubber.py` — SecretRegistry + RedactingFilter + structlog_scrub_processor (152 lines)
- `app/security/fernet.py` — FernetVault, InvalidFernetKey, register_all_secrets_with_scrubber helper
- `app/logging_setup.py` — configure_logging(level, log_dir) wiring root logger and structlog chain
- `tests/unit/test_fernet_vault.py` — 6 unit tests (missing/malformed key, round-trip, wrong-key, auto-register, master key)
- `tests/unit/test_log_scrubber.py` — 6 tests including the mandated end-to-end disk assertion

## Decisions Made
- **Singleton + threading.Lock** for SecretRegistry because FastAPI and APScheduler will touch it from multiple tasks; a per-instance registry would fragment state and break the single-source-of-truth property the two-layer scrubber depends on.
- **4-character minimum on literal registration** to prevent `REGISTRY.add_literal("a")` from turning `"an apple a day"` into `"REDACTEDn REDACTEDpple REDACTED day"`. A bonus test locks this in.
- **Scrub processor before JSONRenderer** in the structlog chain — mandatory per RESEARCH.md pitfall "Structlog vs stdlib redaction ordering". Test `test_structlog_processor_scrubs_event_dict` uses a `DropEvent`-raising capture processor to inspect the post-scrub typed event_dict without engaging the terminal renderer.
- **FernetVault registers plaintext BEFORE encrypting and AFTER decrypting.** Pre-encrypt registration makes exception paths on the write side safe; post-decrypt registration is the only moment we see the plaintext on the read side.
- **InvalidToken collapses to InvalidFernetKey** with the specific phrase "may have changed" so operators see rotation guidance rather than a cryptography stack trace.

## Deviations from Plan

None from the plan's specified behavior — all tasks executed as written, including task commit ordering and the exact verification commands. Three minor implementation notes:

1. **Added `app/__init__.py`** — the plan's `files_modified` list did not include this, but without it `from app.security...` imports fail. This is a Rule 3 (blocking) auto-fix. Single line marker file.
2. **Capture processor in `test_structlog_processor_scrubs_event_dict` raises `structlog.DropEvent`** after recording the event_dict. The plan's description implied returning the event_dict, but structlog's filtering bound logger then forwards the dict to `PrintLogger.msg()` which errors on unexpected kwargs. Raising DropEvent is the idiomatic way to capture-and-halt. Test passes and asserts exactly what the plan intended (no sentinel in captured event_dict).
3. **Nested-dict scrubbing** in `structlog_scrub_processor` covers dicts AND lists/tuples one level deep, matching the plan's shallow-recursion requirement; the test exercises a nested dict (`nested={"token": SENTINELS[1]}`) to lock this in.

---

**Total deviations:** 1 Rule-3 auto-fix (`app/__init__.py`), 2 implementation clarifications.
**Impact on plan:** None — all success criteria met, all verification commands green, 12/12 tests passing.

## Issues Encountered

1. **Parallel Wave 1 file interleaving.** Plan 01-01 was running concurrently in the same working directory and wrote scaffolding files (`.env.example`, `.gitignore`, `Dockerfile`, `compose.yml`, `pyproject.toml`, `requirements.txt`) during Task 1 execution. Despite using `git add` with explicit file paths, those files ended up in commit `fb9410f` because the working tree contained them at commit time. No content conflict occurred (this plan never touched them) and no data was lost. Future Wave parallelism should either (a) isolate working directories per plan, (b) gate commits through a single serialized committer, or (c) accept benign commit interleaving as we did here.
2. **Missing `pytest`/`structlog`/`cryptography` at task start.** Installed on demand via `pip install structlog cryptography pytest pytest-asyncio`. Plan 01-01's `requirements.txt` (swept into commit `fb9410f`) almost certainly already listed these; the pip install was redundant but harmless.

## User Setup Required

None. All security primitives are pure-Python and require no external service configuration.

## Next Phase Readiness

- Every subsequent plan (01-03 scheduler, 01-04 rate limiting, 01-05 DB, all Phase 2+ work) can safely `from app.logging_setup import configure_logging` at app startup and trust that no registered or statically-shaped secret will ever reach stdout or `app.log`.
- `FernetVault.register_all_secrets_with_scrubber(session)` is ready to be called by the DB startup task in plan 01-05 as soon as the `Secret` model lands (see local import in `fernet.py`).
- CI can assert the zero-PII property via `pytest tests/unit/test_log_scrubber.py::test_integration_configure_logging_then_log` — a single end-to-end green check protects the whole property going forward.

**Blockers:** None.
**Concerns:** The parallel Wave 1 commit interleaving (Issue 1) is worth fixing in the `/gsd:execute-phase` orchestrator before the next multi-plan wave.

---
*Phase: 01-foundation-scheduler-safety-envelope*
*Completed: 2026-04-11*

## Self-Check: PASSED

All 7 `key-files.created` entries exist on disk. All 3 task commit hashes (`fb9410f`, `a0470d4`, `820bd09`) exist in git history.
