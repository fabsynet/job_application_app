---
phase: 04-llm-tailoring-docx-generation
plan: 02
subsystem: tailoring
tags: [anthropic, llm, prompt-caching, budget, asyncio, structlog]

# Dependency graph
requires:
  - phase: 01-foundation-scheduler-safety-envelope
    provides: FernetVault (app/security/fernet.py), Secret model, Settings.budget_cap_dollars / budget_spent_dollars / budget_month, structlog scrub pipeline, get_settings_row
  - phase: 04-llm-tailoring-docx-generation / plan 01
    provides: app/tailoring/__init__.py (so app.tailoring is a package), app/tailoring/models.py (TailoringRecord, CostLedger)
provides:
  - "LLMProvider Protocol (runtime_checkable) decoupling callers from backend SDKs"
  - "AnthropicProvider wrapping AsyncAnthropic with lazy SDK import and normalised LLMResponse"
  - "get_provider factory resolving anthropic_api_key through FernetVault"
  - "BudgetGuard with month rollover, 80% warn / 100% halt thresholds, and asyncio.Lock-serialized debit"
  - "Central PRICING table for claude-sonnet-4-5 (input/output/cache_read/cache_write per-MTok)"
  - "anthropic==0.94.0 and mammoth==1.12.0 added to requirements.txt"
affects: [04-03 prompt templates, 04-04 tailoring service, 04-05 cover letter generation, 04-06 validator calls, 04-07 tailoring UI/budget banner]

# Tech tracking
tech-stack:
  added: [anthropic==0.94.0, mammoth==1.12.0]
  patterns:
    - "Protocol + runtime_checkable LLM abstraction (single-backend today, swappable later)"
    - "Lazy SDK import inside __init__ so the module file can exist before pip install completes"
    - "Factory (get_provider) reads credentials from FernetVault, never from environment directly"
    - "asyncio.Lock-serialized check/debit for spend counters (research Pitfall 6)"
    - "Month rollover performed inline on first call of a new month instead of via a cron job"

key-files:
  created:
    - app/tailoring/provider.py
    - app/tailoring/budget.py
  modified:
    - requirements.txt

key-decisions:
  - "LLMResponse keeps input/output/cache_creation/cache_read tokens as four separate ints so BudgetGuard can price prompt-cached calls correctly without re-parsing the SDK object"
  - "AnthropicProvider imports anthropic.AsyncAnthropic inside __init__ (not at module top) so the file can be imported in environments where pip install hasn't run yet"
  - "get_provider uses FernetVault.from_env(get_settings().fernet_key) instead of caching a vault singleton — rotation-friendly and matches existing settings/credentials pattern"
  - "Unknown model names fall back to claude-sonnet-4-5 pricing rather than raising KeyError — mis-estimation is recoverable in the ledger, a crash is not"
  - "cap <= 0 (including 0.0 default) means 'uncapped' — zero is the 'not configured' sentinel, not 'no spend allowed'"
  - "Month rollover resets budget_spent_dollars inline during check_budget instead of running a separate scheduled job"
  - "debit writes Settings increment AND CostLedger row inside a single transaction and inside the asyncio.Lock so two concurrent tailoring coroutines cannot race the cap check"
  - "CostLedger import inside debit() (local import) so app.tailoring.budget remains importable during Wave 1 parallel execution with 04-01"

patterns-established:
  - "Provider abstraction: runtime_checkable Protocol + concrete class + DB-backed factory"
  - "Spend bookkeeping: (can_proceed, spent, cap, is_warning) tuple return so the caller decides UX"
  - "BudgetGuard is instantiated once per process (it owns the asyncio.Lock) and passed as a dependency"

# Metrics
duration: ~6 min
completed: 2026-04-12
---

# Phase 4 Plan 02: LLM Provider and Budget Guard Summary

**Anthropic-backed LLMProvider protocol with AsyncAnthropic prompt caching, vault-resolved API key, and a lock-serialized BudgetGuard that handles month rollover and 80/100 thresholds.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-04-12T21:08Z (approx)
- **Completed:** 2026-04-12T21:14Z
- **Tasks:** 2
- **Files created:** 2 (`app/tailoring/provider.py`, `app/tailoring/budget.py`)
- **Files modified:** 1 (`requirements.txt`)
- **Tests:** 175 existing tests still green, zero regressions

## Accomplishments

- LLMProvider Protocol + LLMResponse dataclass give every future tailoring call a single, stable contract independent of the underlying SDK.
- AnthropicProvider wraps AsyncAnthropic with prompt-cache-aware token accounting and structlog observability (`llm_call_complete` event logs input/output/cache_creation/cache_read tokens and the cache hit ratio).
- get_provider factory pulls the Anthropic key from the encrypted Secret table through FernetVault, so rotation is a settings-UI action (no env-var plumbing required).
- BudgetGuard covers all three spend responsibilities in one place: month rollover, threshold evaluation (80% soft / 100% hard), and atomic debit + ledger write under asyncio.Lock.
- PRICING table centralizes per-MTok rates for claude-sonnet-4-5 (input/output/cache_read/cache_write) so tests and the pipeline share one source of truth.
- anthropic==0.94.0 and mammoth==1.12.0 installed and pinned in requirements.txt. mammoth is included here because it ships in the same dependency wave (04-06 will need it for DOCX → markdown extraction).

## Task Commits

1. **Task 1: LLM provider protocol and Anthropic implementation** - `150669e` (feat)
2. **Task 2: BudgetGuard with month rollover and atomic debit** - `4131cf1` (feat)

**Plan metadata commit:** added after this SUMMARY.md is written.

_Note: commit `e4c44b4` sitting between these two belongs to plan 04-01, which ran in parallel (Wave 1). 04-01 owns `app/tailoring/__init__.py`, `app/tailoring/models.py`, `app/db/models.py`, and the Alembic migration — this plan did not touch any of them._

## Files Created/Modified

- `app/tailoring/provider.py` — LLMResponse dataclass, LLMProvider Protocol (runtime_checkable), AnthropicProvider class (lazy AsyncAnthropic import, token-bucket normalization, cache_hit_ratio logging), get_provider factory resolving anthropic_api_key via FernetVault.
- `app/tailoring/budget.py` — BudgetGuard class with PRICING dict, WARN_THRESHOLD constant, estimate_cost static method (rounded to 6dp, unknown-model fallback), check_budget (inline month rollover + threshold evaluation returning 4-tuple), debit (asyncio.Lock-serialized Settings increment + CostLedger insert in one transaction).
- `requirements.txt` — appended `anthropic==0.94.0` and `mammoth==1.12.0`.

## Decisions Made

- **Lazy SDK import.** AnthropicProvider imports `anthropic.AsyncAnthropic` inside `__init__`, not at module top level. This keeps the file importable even in environments where `pip install` hasn't finished — important during Wave 1 parallel execution and during CI bootstrap.
- **Vault-sourced credentials.** `get_provider` always goes through `FernetVault.from_env(get_settings().fernet_key)` rather than reading `ANTHROPIC_API_KEY` from the environment. This matches the existing pattern for SMTP and ATS credentials and makes the settings UI the single rotation point.
- **Four-bucket token accounting.** LLMResponse separately tracks `input_tokens`, `output_tokens`, `cache_creation_tokens`, and `cache_read_tokens` so BudgetGuard can price each bucket at its correct rate. Flattening to a single `total_input` would lose the 10%-of-input cache-read rate.
- **Unknown-model fallback in estimate_cost.** If a new Anthropic model ships before PRICING is updated, calls are priced at `claude-sonnet-4-5` rates rather than raising KeyError. Mis-estimation surfaces in the ledger and can be corrected; a crash would abort an in-flight tailoring run.
- **`budget_cap_dollars == 0` means unlimited.** Zero is the default for a never-configured singleton row, so it has to map to "no cap". Users who want a zero-spend halt set `kill_switch=True` instead.
- **Month rollover inline, not cron.** `check_budget` compares the stored `budget_month` string (UTC YYYY-MM) to the current month and resets spend on mismatch. This piggybacks on the first call of each month and removes an APScheduler job we'd otherwise have to maintain and test.
- **Lock granularity.** The asyncio.Lock lives on the BudgetGuard instance, so there must be exactly one BudgetGuard per process. Plan 04-04 will instantiate it in the tailoring service and pass it down.
- **debit is one transaction.** Settings.budget_spent_dollars increment and the CostLedger insert happen inside the same `async with self._lock:` block with a single commit, so a crash between them cannot leave the counter diverged from the ledger.
- **CostLedger local import.** Imported inside `debit()` rather than at module top so `budget.py` stays importable in Wave 1 even if the module graph resolves 04-02 before 04-01 has finished writing models.py (belt-and-braces — in practice 04-01 landed first).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Vault module path correction**

- **Found during:** Task 1 (provider factory implementation)
- **Issue:** Plan specified `from app.security.vault import FernetVault`, but the Phase 1 module actually lives at `app/security/fernet.py`. Also, the constructor is `FernetVault.from_env(key_str)` rather than `FernetVault(key)`.
- **Fix:** Used `from app.security.fernet import FernetVault` and `FernetVault.from_env(get_settings().fernet_key)` so the factory matches the existing settings/credentials pattern from Phase 2.
- **Files modified:** `app/tailoring/provider.py`
- **Verification:** `python -c "from app.tailoring.provider import get_provider"` imports cleanly; 175 existing tests still green.
- **Committed in:** `150669e` (Task 1 commit)

**2. [Rule 3 - Blocking] Settings field name correction**

- **Found during:** Task 2 (BudgetGuard.check_budget)
- **Issue:** Plan text referred conceptually to a "monthly cap" and the Settings row was expected to expose a `budget_monthly_cap` attribute, but the actual Phase 2 Settings column is `budget_cap_dollars` (paired with `budget_spent_dollars` and `budget_month`).
- **Fix:** BudgetGuard reads and writes `row.budget_cap_dollars`, `row.budget_spent_dollars`, and `row.budget_month` — no schema change needed.
- **Files modified:** `app/tailoring/budget.py`
- **Verification:** `bg.estimate_cost(1000, 500)` returns `0.0105`; `BudgetGuard.WARN_THRESHOLD` is `0.8`; 175 tests still green.
- **Committed in:** `4131cf1` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 3 blocking — both module-path / field-name mismatches between the plan text and the actual Phase 1/2 codebase).
**Impact on plan:** Neither deviation affected the external contract of this plan — same classes, same method signatures, same behavior. They were straightforward corrections against reality.

## Issues Encountered

- None beyond the two deviations above.

## User Setup Required

None for this plan on its own. Plan 04-07 (settings UI) will add the "Anthropic API key" field that writes into the `anthropic_api_key` Secret row. Until then, `get_provider` raises `ValueError("Anthropic API key not configured")` — intentional, since no tailoring calls exist yet.

## Next Phase Readiness

- **Ready for 04-03** (prompt templates): LLMProvider/LLMResponse are the surface area prompts will target. Prompt assembly code should build the `system` list with `cache_control` blocks and pass it straight into `provider.complete(...)`.
- **Ready for 04-04** (tailoring service): Should instantiate one BudgetGuard at service construction time, call `check_budget` before every tailoring attempt, and `debit` after each successful LLM call. The tuple return shape `(can_proceed, spent, cap, is_warning)` lets the service emit both warning banners and hard halts without needing separate methods.
- **Ready for 04-06** (validator): Validator calls should also debit through the same BudgetGuard instance with `call_type="validate"` so they roll into the monthly cap.
- **Ready for 04-07** (tailoring UI): The settings-page Anthropic key field should write to `Secret(name="anthropic_api_key", ciphertext=vault.encrypt(...))` and the budget card should call `check_budget` to render the 80% banner.

### Blockers/Concerns

- **Python 3.11 local vs. 3.12+ container.** The test venv is still Python 3.11.9 (flagged in STATE.md from 01-01). anthropic==0.94.0 and mammoth==1.12.0 both installed cleanly on 3.11; no action needed, but re-validate inside the Playwright-noble container during 04-03.
- **BudgetGuard instance lifecycle.** The asyncio.Lock is per-instance, so there must be exactly one BudgetGuard per process. Plan 04-04 needs to own construction (likely as an attribute on the tailoring service, created at startup). Flag for 04-04.
- **Anthropic SDK usage pattern.** The `messages.create` call is synchronous-looking in code; verify in 04-03 that we handle streaming vs. non-streaming consistently once real prompts land. For now, we assume non-streaming (simpler for validator and DOCX generation, since we need the complete text before rewriting the resume).

## Self-Check: PASSED

- `app/tailoring/provider.py` — FOUND
- `app/tailoring/budget.py` — FOUND
- `requirements.txt` — FOUND (modified)
- commit `150669e` — FOUND
- commit `4131cf1` — FOUND

---
*Phase: 04-llm-tailoring-docx-generation*
*Completed: 2026-04-12*
