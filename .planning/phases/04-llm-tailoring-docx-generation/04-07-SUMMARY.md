---
phase: 04-llm-tailoring-docx-generation
plan: 07
subsystem: testing
tags: [pytest, pytest-asyncio, mock-llm, docx, phase-closing]

# Dependency graph
requires:
  - phase: 04-llm-tailoring-docx-generation
    provides: TailoringRecord/CostLedger models (04-01), LLMProvider + BudgetGuard (04-02), tailoring engine + prompts + validator (04-03), docx_writer + preview + ATS checks (04-04), service + pipeline stage (04-05), review UI + settings intensity + dashboard budget widget (04-06)
  - phase: 01-foundation-scheduler-safety-envelope
    provides: live_app pytest fixture pattern, async_session conftest fixture
  - phase: 02-configuration-credentials
    provides: httpx.AsyncClient + ASGITransport integration pattern
provides:
  - "tests/test_phase4_tailoring.py — 41 tests covering TAIL-01..TAIL-09 and SAFE-04"
  - "FakeLLMProvider test double that records every call for payload inspection (critical for SAFE-04 PII-in-prompt assertion)"
  - "Reusable _make_base_resume_docx fixture for future DOCX-touching tests"
affects: [phase-5-submission, regression-safety-net]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FakeLLMProvider exposes .calls list so tests can assert on outgoing system/messages payloads — proves PII never leaves the engine"
    - "Full tailor_resume end-to-end test scripts N tailor+validate response pairs through one FakeLLMProvider to exercise the retry+escalation loop without mocking the engine internals"
    - "Settings UI integration test inlines the live_app pattern (config + db.base + wizard + main reload) since test_phase4_tailoring.py doesn't need a shared live_app fixture"

key-files:
  created:
    - tests/test_phase4_tailoring.py
  modified: []

key-decisions:
  - "FakeLLMProvider is a class in test_phase4_tailoring.py, not a shared conftest fixture — Phase 4 is the only consumer and local definition keeps the test surface legible"
  - "Base resume DOCX fixture is built via python-docx in a pytest fixture rather than checked into the repo — fully deterministic and version-tracked as code"
  - "SC-5 cache-token-visibility test asserts against the template file text directly (read_text + substring checks) rather than rendering the template — avoids needing a full Jinja2 env + dummy context"
  - "The SC-2 invented-skill end-to-end test scripts the full 3-retry cycle (6 responses: tailor/validate x3) to prove the escalation loop actually stops at max_retries with success=False"
  - "The SAFE-04 PII-in-prompt test flattens every recorded provider call (system blocks + messages) into one blob and greps for literal name/email/phone — the strictest possible assertion"
  - "Service-layer tests use the existing async_session conftest fixture directly rather than the live_app pattern because the tests only need DB state, not HTTP surface"
  - "Job fixtures include external_id='ext-N' — the Job model has a NOT NULL constraint on external_id that Phase 3 tests implicitly satisfied via real ATS payloads"
  - "resume_artifact_path test asserts forward-slash-normalised path contains '42/v1.docx' so it works on both Windows and Linux"
  - "Budget test uses BudgetGuard._current_month() to stamp the settings row rather than datetime.utcnow().strftime() — stays in lockstep with the guard's own month computation if it ever changes"

patterns-established:
  - "Phase-closing test files live at tests/test_phase{N}_*.py one per subsystem (mirroring test_phase3_discovery.py + test_phase3_integration.py)"
  - "DOCX fixture helpers live at module level in the test file that consumes them — not in conftest.py — so test-local dependencies stay visible"

# Metrics
duration: ~12min
completed: 2026-04-12

---

# Phase 4 Plan 7: Test Coverage Summary

**One-liner:** Phase-closing test hardening — 41 tests covering all TAIL-01..TAIL-09 and SAFE-04 requirements with a FakeLLMProvider that proves PII never leaves the engine.

## What was built

`tests/test_phase4_tailoring.py` (1,167 lines) adds comprehensive coverage for every Phase 4 requirement, organised into nine test groups:

| Group | Tests | Requirements |
|---|---|---|
| PII stripping | 5 | SAFE-04 |
| Prompts | 4 | TAIL-03 |
| Validator | 4 | TAIL-04, SC-2 |
| Budget guard | 8 | TAIL-08, SC-4 |
| DOCX writer | 9 | TAIL-05, SC-1 |
| Preview | 3 | TAIL-06 |
| Service layer | 5 | TAIL-09 |
| Settings UI | 1 | TAIL-07 (intensity) |
| Cache token visibility | 2 | SC-5 |

**Total: 41 new tests. 175 existing tests remain green. Suite total: 216.**

## Key tests (success criteria)

**SC-1 (format preservation):** `test_replace_preserves_run_formatting_bold` + `test_build_tailored_docx_preserves_formatting` — bold/italic runs survive the writer's `replace_paragraph_text_preserving_format` path.

**SC-2 (hallucination rejection):** `test_invented_skill_rejected_end_to_end` — scripts 6 FakeLLMProvider responses (tailor/validate × 3), injects "React" into every tailored output, and asserts `tailor_resume` returns `success=False` with the full violation history in `validation_warnings`.

**SC-3 (PII absent from prompts):** `test_pii_never_in_llm_prompt` — runs a full tailoring cycle against `sample_resume_sections` (which contains "Jane Doe", "jane.doe@example.com", "555-123-4567", "Main St"), flattens every recorded provider call into one blob, and asserts **literal PII never appears** anywhere in the outgoing payload. This is the strictest possible SAFE-04 assertion.

**SC-4 (budget halt):** `test_budget_check_halts_at_cap` — sets spent=cap=$10 and asserts `can_proceed=False`. Supported by `test_budget_warning_at_80_percent` and `test_budget_month_rollover`.

**SC-5 (cache token visibility):** `test_tailoring_detail_template_shows_cache_tokens` reads `tailoring_detail.html.j2` directly and asserts it contains both `cache_read_tokens` and "cache savings" text. Supported by `test_tailoring_result_tracks_cache_tokens` proving the dataclass exposes the field.

## Test doubles

**`FakeLLMProvider`** — scriptable mock that records every `complete` call into `self.calls`. Accepts either raw content strings (wrapped in a default `LLMResponse` with `cache_read_tokens=80` for testing cache flow) or fully-formed `LLMResponse` instances for per-test token-count customisation. Raises `AssertionError` if the engine asks for more responses than were scripted — catches engine bugs that loop incorrectly.

**`_make_base_resume_docx`** — builds a realistic base resume DOCX in-memory via `python-docx`: contact header (name, email, phone, address), Professional Summary (italic), Work Experience (bold bullet), Skills, Education. Used by writer and preview tests.

## Deviations from Plan

**None — plan executed exactly as written.** One minor fixture-shape fix: Job model has a NOT NULL constraint on `external_id` that wasn't called out in the plan, so the three Job fixtures were stamped with `ext-1/2/3`. This was a mechanical correction, not a design deviation.

## Authentication Gates

None — all tests use mocked LLM calls, no real Anthropic traffic.

## Verification

```
$ python -m pytest tests/test_phase4_tailoring.py -q
41 passed in 2.10s

$ python -m pytest tests/ -q
216 passed in 82.41s (0:01:22)
```

## Task Commits

| Task | Commit | Description |
|---|---|---|
| 1 | 25b630e | test(04-07): phase 4 tailoring test coverage (41 tests, all TAIL-01..09 + SAFE-04) |

## Next Phase Readiness

Phase 4 (LLM Tailoring & DOCX Generation) is now **feature-complete and fully tested**. The 216-test safety net will catch regressions in any Phase 5 (submission) work that touches the tailoring pipeline, budget guard, or artifact layout.

**Open items flagged for Phase 5 or cleanup:**
- Real AnthropicProvider integration (network-bound) is still untested — intentional; the plan scope is mocked-LLM coverage only.
- `app.resume.service` module-level `get_settings` binding fragility (flagged in 04-05 STATE blockers) is unaffected by these tests and remains a latent cleanup item.
- BudgetGuard instance lifecycle (currently constructed per pipeline stage) remains as flagged in 04-05 — no change here, and the new tests happily construct fresh instances per test so they don't depend on the lifecycle decision either way.

## Self-Check: PASSED

Files created:
- tests/test_phase4_tailoring.py: FOUND

Commits:
- 25b630e: FOUND
