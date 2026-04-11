---
phase: 01-foundation-scheduler-safety-envelope
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - app/security/__init__.py
  - app/security/fernet.py
  - app/security/log_scrubber.py
  - app/logging_setup.py
  - tests/unit/test_fernet_vault.py
  - tests/unit/test_log_scrubber.py
autonomous: true

must_haves:
  truths:
    - "Any string registered with the secret registry is replaced with ***REDACTED*** before it reaches stdout, the app.log file, or any structlog JSON output"
    - "Static patterns redact Anthropic, OpenAI, Fernet-token, and password-shaped strings even if the registry has never seen them"
    - "FernetVault encrypts and decrypts round-trip, auto-registers decrypted plaintexts with the scrubber, and fails loudly on InvalidToken"
  artifacts:
    - path: "app/security/fernet.py"
      provides: "FernetVault with from_env, encrypt, decrypt, register_literal_with_scrubber"
      exports: ["FernetVault", "InvalidFernetKey"]
    - path: "app/security/log_scrubber.py"
      provides: "SecretRegistry singleton, RedactingFilter, structlog_scrub_processor"
      exports: ["REGISTRY", "RedactingFilter", "structlog_scrub_processor", "SecretRegistry"]
    - path: "app/logging_setup.py"
      provides: "configure_logging(level, log_dir) wiring stdlib + structlog with redaction"
      exports: ["configure_logging"]
    - path: "tests/unit/test_log_scrubber.py"
      provides: "The mandated zero-PII-in-logs assertion test (CONTEXT.md makes this testable)"
      contains: "REGISTRY"
  key_links:
    - from: "app/security/fernet.py"
      to: "app/security/log_scrubber.REGISTRY"
      via: "FernetVault.decrypt auto-calls REGISTRY.add_literal(plaintext)"
      pattern: "REGISTRY\\.add_literal"
    - from: "app/logging_setup.py"
      to: "root logger handlers"
      via: "addFilter(RedactingFilter()) on stdout and file handlers"
      pattern: "addFilter\\(RedactingFilter"
    - from: "structlog processor chain"
      to: "structlog_scrub_processor"
      via: "processors list places scrub BEFORE JSONRenderer"
      pattern: "structlog_scrub_processor.*JSONRenderer|JSONRenderer.*\\(\\)"
---

<objective>
Build the security primitives Phase 1 is ultimately judged on: Fernet encryption and the two-layer log scrubber that enforces SAFE-03 ("PII/resume never in logs") and FOUND-06 ("Fernet-encrypted secrets"). This plan ships the mandatory "zero PII in logs" assertion test — CONTEXT.md makes it an explicit testable property, not a vibe.

Purpose: Every later plan and every later phase writes logs. If the scrubber is not in place before the scheduler runs, the first log line has a chance to leak. This plan must be complete before any code that handles a secret ever runs.

Output: `FernetVault.from_env` fails fast on bad keys, encrypts/decrypts round-trip, and auto-registers decrypted plaintexts with the scrubber. `configure_logging` wires `RedactingFilter` onto the root logger and `structlog_scrub_processor` onto the structlog chain. `tests/unit/test_log_scrubber.py` contains the sentinel-based assertion CONTEXT.md mandates.
</objective>

<execution_context>
@C:/Users/abuba/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/abuba/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-CONTEXT.md
@.planning/phases/01-foundation-scheduler-safety-envelope/01-RESEARCH.md
@.planning/research/PITFALLS.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Log scrubber (SecretRegistry + RedactingFilter + structlog processor) and logging setup</name>
  <files>
    app/security/__init__.py,
    app/security/log_scrubber.py,
    app/logging_setup.py
  </files>
  <action>
Implement the two-layer scrubber EXACTLY per RESEARCH.md "Log Scrubbing (zero-tolerance PII/secret leakage)".

**app/security/log_scrubber.py:**

1. `SecretRegistry` class:
   - `_literals: set[str]` — exact strings to redact.
   - `_patterns: list[re.Pattern]` — regex fallbacks.
   - `_lock: threading.Lock` — thread-safe add/scrub (FastAPI + APScheduler touch it from multiple tasks).
   - Constructor pre-registers static patterns from RESEARCH.md:
     - `r"sk-ant-[A-Za-z0-9\-_]{20,}"` (Anthropic)
     - `r"sk-[A-Za-z0-9]{32,}"` (OpenAI-shape)
     - `r"gAAAAA[A-Za-z0-9\-_=]{20,}"` (Fernet token prefix)
     - `r"(?i)password[\"'=:\s]+[^\s\"']{4,}"` (password=value leak shape)
   - `add_literal(value: str)` — lock-guarded; ignores values shorter than 4 chars (avoids nuking everyday words).
   - `scrub(text: str) -> str` — replace literals then apply patterns; return "***REDACTED***" substitutions. Non-string input returns unchanged.
   - `clear_literals()` method for test isolation ONLY (document it as test-only).

2. `REGISTRY = SecretRegistry()` module-level singleton.

3. `RedactingFilter(logging.Filter)`:
   - Override `filter(record)`.
   - Scrub `record.msg` if str.
   - Scrub `record.args` tuple element-wise if str.
   - Also scrub common `record.__dict__` extras that might carry user-provided strings: `record.getMessage()` is NOT recomputed after mutation, so we DO mutate msg/args before format — that's the whole point.
   - Always return True (never drop records).

4. `structlog_scrub_processor(logger, name, event_dict)`:
   - Iterate `event_dict.items()`, replace string values via `REGISTRY.scrub`.
   - Also scrub nested dicts/lists one level deep (shallow recursion — logs rarely go deeper).
   - Return event_dict.

**app/logging_setup.py:**

`configure_logging(level: str, log_dir: Path) -> None`:
1. Ensure `log_dir` exists (`mkdir(parents=True, exist_ok=True)`).
2. Build `RedactingFilter()` once.
3. Stdout `StreamHandler(sys.stdout)` + `FileHandler(log_dir / "app.log", encoding="utf-8")`. Both get the filter via `addFilter`.
4. Replace `logging.getLogger().handlers` with `[stdout, file]`, set root level.
5. Also lower uvicorn/apscheduler/sqlalchemy verbose loggers to WARNING so their INFO lines don't spam and don't bypass the filter.
6. `structlog.configure` with processors: `[merge_contextvars, add_log_level, TimeStamper(fmt="iso"), structlog_scrub_processor, JSONRenderer()]`.
   - CRITICAL: scrub MUST precede JSONRenderer per RESEARCH.md pitfall "Structlog vs stdlib redaction ordering" — scrub typed values, not rendered JSON strings.
7. `wrapper_class=structlog.make_filtering_bound_logger(level_int)`, `logger_factory=structlog.stdlib.LoggerFactory()`, `cache_logger_on_first_use=True`.

**app/security/__init__.py** — re-export `REGISTRY` for convenience: `from app.security.log_scrubber import REGISTRY, SecretRegistry`.
  </action>
  <verify>
`python -c "from app.security.log_scrubber import REGISTRY, RedactingFilter, structlog_scrub_processor; REGISTRY.add_literal('supersecret123'); assert REGISTRY.scrub('leaking supersecret123 here') == 'leaking ***REDACTED*** here'; print('ok')"` prints ok.
`python -c "from app.logging_setup import configure_logging; from pathlib import Path; import tempfile; configure_logging('INFO', Path(tempfile.mkdtemp())); print('ok')"` prints ok.
  </verify>
  <done>
SecretRegistry, RedactingFilter, structlog_scrub_processor exist. configure_logging installs the filter on the root logger and places the scrub processor before JSONRenderer in the structlog chain. Uvicorn/SQLA/APScheduler loggers are throttled to WARNING.
  </done>
</task>

<task type="auto">
  <name>Task 2: FernetVault + fail-fast env loading + auto-registration with log scrubber</name>
  <files>
    app/security/fernet.py,
    tests/unit/test_fernet_vault.py
  </files>
  <action>
Implement `app/security/fernet.py` per RESEARCH.md "Fernet Secrets Pattern" with one addition: every decrypted plaintext must auto-register with the log scrubber so a secret loaded from DB at startup cannot later accidentally print.

**Class `InvalidFernetKey(Exception)`.**

**Class `FernetVault`:**

```python
from cryptography.fernet import Fernet, InvalidToken
from app.security.log_scrubber import REGISTRY

class FernetVault:
    def __init__(self, fernet: Fernet):
        self._fernet = fernet

    @classmethod
    def from_env(cls, key_str: str) -> "FernetVault":
        if not key_str:
            raise InvalidFernetKey("FERNET_KEY env var is required")
        try:
            key_bytes = key_str.encode() if isinstance(key_str, str) else key_str
            fernet = Fernet(key_bytes)
        except (ValueError, TypeError) as e:
            raise InvalidFernetKey(f"FERNET_KEY is not a valid Fernet key: {e}") from e
        # Register the master key itself so it cannot appear in any log line (belt+braces)
        REGISTRY.add_literal(key_str)
        return cls(fernet)

    def encrypt(self, plaintext: str) -> bytes:
        # Register BEFORE encrypting so any incidental logging during the write path is safe
        REGISTRY.add_literal(plaintext)
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            pt = self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as e:
            raise InvalidFernetKey(
                "stored secret cannot be decrypted — FERNET_KEY may have changed"
            ) from e
        REGISTRY.add_literal(pt)
        return pt

    async def register_all_secrets_with_scrubber(self, session) -> int:
        """Decrypt every Secret row at startup so its plaintext is in the scrubber registry.
        Returns count of secrets successfully registered. Rows that fail to decrypt are
        left in place (preserve for forensic) and counted as failures via logging."""
        from sqlalchemy import select
        from app.db.models import Secret
        result = await session.execute(select(Secret))
        rows = result.scalars().all()
        registered = 0
        for row in rows:
            try:
                self.decrypt(row.ciphertext)   # side effect: registers literal
                registered += 1
            except InvalidFernetKey:
                import structlog
                structlog.get_logger(__name__).error(
                    "secret_unreadable_on_boot",
                    secret_name=row.name,
                )
        return registered
```

**tests/unit/test_fernet_vault.py:**

- `test_from_env_missing_raises`: `FernetVault.from_env("")` raises `InvalidFernetKey`.
- `test_from_env_malformed_raises`: `FernetVault.from_env("not-a-key")` raises `InvalidFernetKey`.
- `test_roundtrip_encrypt_decrypt(tmp_fernet_key)`: encrypt "hello" → bytes → decrypt → "hello".
- `test_decrypt_wrong_key_raises`: encrypt with key A, attempt decrypt with key B → `InvalidFernetKey` with message mentioning "may have changed".
- `test_decrypt_auto_registers_with_scrubber(tmp_fernet_key, monkeypatch)`:
  - Use `REGISTRY.clear_literals()` at start.
  - Encrypt "auto-reg-sentinel-xyz".
  - Decrypt → verify `REGISTRY.scrub("contains auto-reg-sentinel-xyz inside") == "contains ***REDACTED*** inside"`.
- `test_from_env_registers_master_key`: generate key → `FernetVault.from_env(key)` → scrub(key) contains REDACTED.
  </action>
  <verify>
`pytest tests/unit/test_fernet_vault.py -q` — all tests pass.
`python -c "from app.security.fernet import FernetVault, InvalidFernetKey; from cryptography.fernet import Fernet; v=FernetVault.from_env(Fernet.generate_key().decode()); assert v.decrypt(v.encrypt('x')) == 'x'; print('ok')"` prints ok.
  </verify>
  <done>
FernetVault fails fast on bad keys, round-trips encrypt/decrypt, auto-registers plaintexts with the scrubber on decrypt+encrypt+from_env. InvalidToken is translated to InvalidFernetKey with a user-facing message about key rotation. All 6 unit tests pass.
  </done>
</task>

<task type="auto">
  <name>Task 3: The mandated "zero PII in logs" assertion test suite</name>
  <files>
    tests/unit/test_log_scrubber.py
  </files>
  <action>
This test file is called out in CONTEXT.md Specific Ideas: "Zero PII in logs is a testable property, not a vibe. The planner should write an explicit assertion for it." Ship it per RESEARCH.md "The required assertion test".

Implement all three tests from RESEARCH.md verbatim (with minor import adjustments for our module paths):

1. **`test_stdlib_logger_scrubs_registered_secrets(caplog)`:**
   - Define `SENTINELS = ["sk-ant-api03-DEADBEEFDEADBEEFDEADBEEFDEADBEEF", "gAAAAABmMYSECRETFERNETTOKENPAYLOAD==", "super-secret-smtp-password-123"]`.
   - Register each via `REGISTRY.add_literal`.
   - Add `RedactingFilter()` to a logger.
   - Log messages using each sentinel via both `%s` formatting and f-strings.
   - Assert none of the sentinels appear in caplog.records combined message text.
   - Assert "REDACTED" does appear.

2. **`test_structlog_processor_scrubs_event_dict()`:**
   - Configure a tiny structlog chain: `[structlog_scrub_processor, capture_processor]` where `capture_processor` appends the event_dict to a list and returns it.
   - Log with `api_key=SENTINELS[0], smtp_pwd=SENTINELS[2]`.
   - Assert the captured event_dict has no sentinel substring in any value.

3. **`test_static_patterns_catch_unregistered_anthropic_keys(caplog)`:**
   - Use an unregistered key matching the Anthropic pattern: `"sk-ant-api03-THISKEYWASNEVERREGISTEREDDEADBEEF"`.
   - Log it through a filtered logger.
   - Assert the raw key is not in `caplog.text`.

4. **BONUS — `test_scrubber_does_not_mutate_short_words()`:**
   - `REGISTRY.add_literal("a")` — should be rejected or no-op (4-char minimum).
   - Log "an apple a day".
   - Assert "an apple a day" is unchanged (no accidental "***REDACTED***" substitution).

5. **BONUS — `test_integration_configure_logging_then_log(tmp_path)`:**
   - Call `configure_logging("INFO", tmp_path)`.
   - Register a sentinel.
   - Emit one INFO log line from `logging.getLogger("test")` containing the sentinel.
   - Read `tmp_path / "app.log"` and assert the sentinel is NOT in the file contents.
   - This is the end-to-end confirmation.

Use a module-level fixture or `autouse` fixture that calls `REGISTRY.clear_literals()` before each test so tests don't leak state.

Also write one test at the top of the file that calls `REGISTRY.clear_literals()` in setup and asserts the static patterns still work (they live on `_patterns`, not `_literals`, so clear should not nuke them).
  </action>
  <verify>
`pytest tests/unit/test_log_scrubber.py -v` — all 5+ tests pass.
`pytest tests/unit/test_log_scrubber.py::test_integration_configure_logging_then_log -v` passes (the end-to-end file-sink assertion).
  </verify>
  <done>
The mandated zero-PII-in-logs assertion is in the test suite and green. Static pattern fallback is verified. Integration test reads the actual app.log file and confirms no sentinel ever reaches disk. Registry state is isolated between tests.
  </done>
</task>

</tasks>

<verification>
- `pytest tests/unit/test_fernet_vault.py tests/unit/test_log_scrubber.py -q` — all pass.
- `grep -q "structlog_scrub_processor" app/logging_setup.py` AND the processor is positioned BEFORE `JSONRenderer` in the chain (assert by line number or by reading the processors list).
- Importing `app.security.log_scrubber` has no side effects beyond creating REGISTRY.
- No plaintext secret ever returns from FernetVault without first being added to REGISTRY.
</verification>

<success_criteria>
1. FernetVault round-trips and fails loudly on key rotation / bad keys.
2. Every decrypt, every encrypt, and every `from_env` registers the relevant plaintext with the scrubber.
3. The required zero-PII-in-logs assertion test exists and passes — including the end-to-end integration test that asserts sentinels never reach the app.log file on disk.
4. Static regex patterns catch unregistered Anthropic / OpenAI / Fernet-token / password-shaped strings as a fallback.
5. Uvicorn/SQLA/APScheduler loggers are throttled to WARNING so they cannot spam with bypass paths.
6. No code in this plan imports from `app.scheduler` or `app.web` — security layer is a pure leaf and can run in Wave 1 in parallel with plan 01-01.
</success_criteria>

<output>
After completion, write `.planning/phases/01-foundation-scheduler-safety-envelope/01-02-SUMMARY.md` with frontmatter:
- `subsystem: security`
- `tech-stack.added: [cryptography.fernet (configured), structlog processor chain (configured), logging filter]`
- `affects: [01-03, 01-04, 01-05, all future phases]` — every future phase inherits this scrubber
- `key files: [app/security/fernet.py, app/security/log_scrubber.py, app/logging_setup.py, tests/unit/test_log_scrubber.py]`
- Decisions: "SecretRegistry is a module-level singleton with threading.Lock", "scrub processor precedes JSONRenderer", "4-char minimum on literal registration", "FernetVault auto-registers on encrypt+decrypt+from_env"
- Patterns: "Two-layer scrubber (stdlib filter + structlog processor) pulling from one registry"
</output>
</content>
</invoke>