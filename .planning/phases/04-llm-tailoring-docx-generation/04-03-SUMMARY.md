---
phase: 04-llm-tailoring-docx-generation
plan: 03
subsystem: tailoring
tags: [anthropic, prompts, prompt-caching, llm-as-judge, pii-stripping, retry, extractive]

# Dependency graph
requires:
  - phase: 04-llm-tailoring-docx-generation / plan 02
    provides: LLMProvider Protocol, LLMResponse dataclass, AnthropicProvider with prompt caching
  - phase: 02-configuration-and-settings
    provides: extract_resume_text returning sections list (app/resume/service.py)
provides:
  - "TAILORING_SYSTEM_PROMPT enforcing extractive-only tailoring with three intensity levels and locked fields"
  - "VALIDATOR_SYSTEM_PROMPT LLM-as-judge with 7 violation types and reasonable-inference examples"
  - "COVER_LETTER_SYSTEM_PROMPT for 3-4 grounded paragraphs"
  - "Prompt caching via build_system_messages (ephemeral cache_control after base resume)"
  - "strip_pii_sections helper dropping contact section + regex redaction fallback (SAFE-04)"
  - "tailor_resume orchestration with strip → tailor → validate → retry (escalating) → cover letter"
  - "TailoringResult dataclass carrying per-call llm_calls list ready for CostLedger writer"
  - "validate_output returning (passed, violations, LLMResponse) so validator tokens bill correctly"
affects: [04-04 tailoring service/pipeline, 04-05 cover letter integration, 04-06 review queue display, 04-07 settings/budget UI]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Extractive-only prompt with explicit reasonable-inference examples (FastAPI → Python backend OK; FastAPI → React NOT OK)"
    - "LLM-as-judge validation as a separate call (not self-validation) — research anti-pattern avoided"
    - "Prompt caching with cache_control ephemeral AFTER the base resume, so the 5-min cache window kicks in across sequential tailoring jobs"
    - "Escalating retry: tailoring prompt tightens on retries 1 and 2; validator strictness stays constant (Pitfall 4)"
    - "Per-call token accounting (llm_calls list) so each CostLedger row corresponds to exactly one provider.complete() call"
    - "PII stripping drops contact section first, then regex-redacts stray email/phone as belt-and-braces (SAFE-04)"
    - "Violations stamped with retry index so review queue can show 'Retry 1 removed invented skill X'"

key-files:
  created:
    - app/tailoring/prompts.py
    - app/tailoring/engine.py
  modified: []

key-decisions:
  - "TAILORING_SYSTEM_PROMPT is one monolithic constant (not built from fragments) — easier to review for prompt-injection resistance and cheaper to cache intact"
  - "Validator temperature pinned at 0.1 (deterministic fact-checking), tailoring at 0.3 (room for paraphrase), cover letter at 0.4 (mild voice)"
  - "get_escalated_prompt_suffix escalates only on the TAILORING side; the validator prompt stays constant — research Pitfall 4 explicitly warns against tightening the judge"
  - "strip_pii_sections drops any section whose heading matches contact-hint keywords (contact/info/personal/details/profile), not just the first section — some resumes have the header mid-document"
  - "Belt-and-braces regex redaction runs AFTER heading-based stripping so an email embedded inside a non-contact section still gets scrubbed before hitting Claude"
  - "TailoringResult.retry_count is the 1-indexed count of attempts made (retry+1), not the 0-indexed retry variable — consumers want 'how many tries did this take', not 'what index did we stop at'"
  - "Cover letter failures are NON-fatal: if tailoring+validation passed, we return success=True and append a warning; losing a cover letter should not discard a validated resume"
  - "validate_output returns the LLMResponse as a third tuple element so validator token usage flows into the same accounting as tailoring — the budget cap covers ALL phase-4 LLM traffic, not just the rewrite calls"
  - "parse_tailoring_response only validates that 'sections' is a list, not the full schema; Claude's JSON varies per resume and strict schema enforcement caused rewrite churn in Phase 4 research"
  - "Violations from earlier retries are kept in validation_warnings even when a later retry passes — the review queue needs the full 'what did we catch and fix' history"

patterns-established:
  - "Prompt module + engine module split: prompts.py is pure constants and message builders (no I/O, no provider calls), engine.py orchestrates LLM calls. Keeps the prompts diff-reviewable in isolation"
  - "LLM call records are plain dicts with (call_type, model, token-buckets), so plan 04-04's CostLedger writer is a simple loop over TailoringResult.llm_calls"

# Metrics
duration: ~5 min
completed: 2026-04-12
---

# Phase 4 Plan 03: Tailoring Engine and Prompts Summary

**Extractive-only prompt templates plus the orchestration engine that strips PII, calls Claude with prompt caching, runs an LLM-as-judge validator, auto-retries with escalating strictness, and generates a grounded cover letter — all while accumulating per-call token usage for the CostLedger.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-04-12T21:18:43Z
- **Completed:** 2026-04-12T21:23:52Z
- **Tasks:** 2
- **Files created:** 2 (`app/tailoring/prompts.py`, `app/tailoring/engine.py`)
- **Tests:** 175/175 still green, zero regressions

## Accomplishments

- **TAILORING_SYSTEM_PROMPT** (4346 chars) lays out extractive-only rules with concrete accept/reject inference examples, three intensity levels as strict upper bounds on transformation, locked fields (name/email/phone/address/company/title/dates/credentials), explicit instruction to reuse the exact section headings from the base resume (Pitfall 5), and a fully specified JSON output schema.
- **VALIDATOR_SYSTEM_PROMPT** defines 7 violation types (invented_company / title / skill / metric / credential, modified_dates, modified_locked_field) with a calibrated "reasonably inferable" definition and 10 worked examples across accept/reject so the judge is stable across resumes.
- **COVER_LETTER_SYSTEM_PROMPT** produces 3-4 short paragraphs, pruned of buzzwords and boilerplate, with the same extractive-only constraint.
- **Prompt caching wired correctly**: `build_system_messages` puts `cache_control: ephemeral` AFTER the base resume block (not the instructions), so the 5-minute cache window hits on sequential tailoring jobs. `build_cover_letter_messages` does the same for the cover-letter resume prefix.
- **PII stripping (SAFE-04)**: `strip_pii_sections` drops the first section if unlabelled OR if its heading matches contact-hint keywords, continues scanning for any mid-document contact sections, and runs regex redaction for stray email/phone patterns as a second pass. Warns via structlog if no contact section was found.
- **Retry loop with escalation**: up to 3 tailoring attempts by default, with `get_escalated_prompt_suffix` tightening the tailoring instructions on retries 1 and 2. Validator strictness is held constant (Pitfall 4). Each retry's violations are stamped with the retry index so the review queue can show the full "what did we catch and fix" history.
- **Per-call token accounting**: `TailoringResult.llm_calls` is a list of plain dicts `(call_type, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)` — one entry per `provider.complete()` call (tailor / validate / cover_letter). Plan 04-04's CostLedger writer is now a trivial loop.
- **Non-fatal cover letter failures**: if tailoring + validation passed but the cover letter call fails or parses badly, we still return `success=True` with a warning logged. A validated resume should not be discarded because of a cover letter glitch.

## Task Commits

1. **Task 1: Prompt templates for tailoring, validation, and cover letter** — `60a20b4` (feat)
2. **Task 2: Tailoring engine with validation and retry loop** — `a3d7633` (feat)

_Plan metadata commit follows this SUMMARY._

## Files Created/Modified

- `app/tailoring/prompts.py` — `TAILORING_SYSTEM_PROMPT`, `VALIDATOR_SYSTEM_PROMPT`, `COVER_LETTER_SYSTEM_PROMPT`, `TAILORING_OUTPUT_SCHEMA` reference dict, `get_escalated_prompt_suffix(retry)`, and the four message builders (`build_system_messages`, `build_tailoring_messages` / `build_tailoring_user_message`, `build_validator_messages`, `build_cover_letter_messages`).
- `app/tailoring/engine.py` — `TailoringResult` dataclass, `strip_pii_sections` with heuristic heading matching + regex redaction, tolerant JSON parsers (`parse_tailoring_response`, `parse_validation_response`, `parse_cover_letter_response`) that strip markdown fences, `validate_output` / `generate_cover_letter` LLM helpers, and `tailor_resume` as the top-level orchestrator.

## Decisions Made

- **Monolithic system prompt** rather than fragments. Easier to review for prompt-injection resistance, and cached as a single block so cache breakpoints stay predictable.
- **Temperature schedule**: validator 0.1 (deterministic), tailoring 0.3 (paraphrase room), cover letter 0.4 (mild voice). Codified once in the engine so consumers cannot accidentally drift.
- **Only TAILORING escalates on retry**, not the validator. Research Pitfall 4 explicitly warns that tightening the judge causes cascade rejections; tightening the candidate is the right lever.
- **`strip_pii_sections` also scans mid-document**, not just section 0. Some resumes put contact info in a "Personal Details" block after the summary. Keyword hints: `contact`, `info`, `personal`, `details`, `profile`.
- **Belt-and-braces regex redaction** runs after heading-based stripping so a stray email inside a non-contact section still gets scrubbed. Catches resumes with embedded portfolio links that double as contact info.
- **`TailoringResult.retry_count` is 1-indexed** (`retry + 1`) — "how many attempts did this take", not "what loop index did we stop at". Matches what Plan 04-04's ledger display and the review queue want.
- **Cover letter failures are non-fatal**. A validated tailored resume should not be thrown out because the cover letter JSON was malformed. We keep the resume, set `success=True`, set `cover_letter_paragraphs=None`, and append a warning for the review UI.
- **`validate_output` returns the LLMResponse** as a third tuple element so validator tokens roll into the same per-call ledger as tailoring tokens. BudgetGuard covers all Phase 4 traffic, not just rewrite calls.
- **`parse_tailoring_response` only checks `sections` is a list** — no strict schema. Resume structure varies too much (some have Skills top-level, some as a section; some have Projects, some don't). Strict validation caused churn during the research spike. The DOCX writer (04-04) does the final mapping and is free to ignore sections it doesn't recognize.
- **Violations from earlier retries are preserved** in `validation_warnings` even when a later retry passes. The review queue's whole value prop per CONTEXT.md is showing the user what the system caught — "Retry 1: removed invented skill X" is trust-building evidence.

## Deviations from Plan

None — plan executed as written.

- The plan's `validate_output` signature ambiguity (paragraph says "return `(bool, list[dict], LLMResponse)`") was implemented as stated.
- The plan mentioned a structlog event schema (`tailoring_start`, `tailoring_attempt`, `validation_result`, `retry`, `tailoring_complete`/`failed`) — implemented with those event names plus supporting events: `pii_strip_no_contact_section`, `tailoring_parse_failed`, `validator_parse_failed`, `tailoring_call_failed`, `validator_call_failed`, `cover_letter_generated`, `cover_letter_parse_failed`, `cover_letter_call_failed`.
- Wave 2 file scope was honoured: only `app/tailoring/prompts.py` and `app/tailoring/engine.py` were touched. `docx_writer.py` and `preview.py` (owned by 04-04) were not created or modified.

**Total deviations:** 0 auto-fixed
**Impact on plan:** Plan executed exactly as written.

## Issues Encountered

None. Both tasks' verify commands passed on first run, and the full test suite (175 tests) stayed green throughout.

## User Setup Required

None for this plan on its own. The engine will raise `ValueError("Anthropic API key not configured")` via `get_provider` (04-02) until the settings UI (plan 04-07) adds the encrypted key row — this is intentional, no tailoring runs yet.

## Next Phase Readiness

- **Ready for 04-04** (tailoring service / pipeline stage): Call `tailor_resume(provider, sections, job_description, intensity, company=..., title=...)` inside the pipeline. Walk `result.llm_calls` to write CostLedger rows. Persist `result.tailored_sections`, `result.cover_letter_paragraphs`, `result.validation_warnings`, and the four token totals into a `TailoringRecord`. Construct exactly one `BudgetGuard` at service startup and `debit` through it after every call type.
- **Ready for 04-04** (docx_writer): `result.tailored_sections` matches the schema in `TAILORING_OUTPUT_SCHEMA` — iterate `sections[*].heading` against the base DOCX heading paragraphs; use `subsections` for Work Experience; fall back to fuzzy matching if headings don't line up exactly.
- **Ready for 04-05** (cover letter artifact): `result.cover_letter_paragraphs` is a plain `list[str]` of 3-4 paragraphs — python-docx can create a cover-letter DOCX by appending each paragraph as a new `doc.add_paragraph`.
- **Ready for 04-06** (review queue): `result.validation_warnings` is a list of dicts stamped with `retry` index; the UI can group by retry to show "Retry 1 caught X, Retry 2 caught Y, final attempt passed". Non-passing results (`success=False`) go to the "failed tailoring" queue per CONTEXT.md.

### Blockers/Concerns

- **Prompt caching minimum tokens**: Claude Sonnet 4.5 requires 1024 tokens before the cache breakpoint. The system prompt (~850 tokens) plus a typical resume (~500-2000 tokens) easily exceeds this, but very short resumes (<200 tokens) might fail to cache silently. Plan 04-04 should log `cache_read_tokens` on the second call of a burst and warn if it stays 0.
- **Cover letter DOCX generation is owed by 04-05**, not this plan. The engine returns `cover_letter_paragraphs` as a list of strings — the caller is responsible for writing it to a `.docx` file (python-docx `add_paragraph` loop) and persisting the path on the TailoringRecord.
- **Section heading fuzzy matching**: the prompt instructs Claude to use the exact base-resume heading strings, but LLMs sometimes drift (`Work Experience` → `Experience`). Plan 04-04's DOCX writer should implement a case-insensitive fallback match (lowercase + keyword overlap) before giving up on a section. This plan's engine does not enforce exact-match on parse, so drift does not cause tailoring failure — it causes section mis-placement during DOCX write, which is the writer's problem.
- **Python 3.11 vs 3.12+ container**: unchanged from 04-02 — all new code uses stdlib + already-installed deps (anthropic via protocol, json, re, dataclasses, structlog), so 3.11 local and 3.12 container both work.

---
*Phase: 04-llm-tailoring-docx-generation*
*Completed: 2026-04-12*

## Self-Check: PASSED

- `app/tailoring/prompts.py` — FOUND
- `app/tailoring/engine.py` — FOUND
- commit `60a20b4` — FOUND
- commit `a3d7633` — FOUND
