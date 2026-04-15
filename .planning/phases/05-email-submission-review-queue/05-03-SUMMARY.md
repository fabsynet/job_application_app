---
phase: 05-email-submission-review-queue
plan: "05-03"
subsystem: submission
tags: [protocol, registry, strategy-pattern, dispatch, plug-in, dataclass]

# Dependency graph
requires:
  - phase: 05-email-submission-review-queue
    plan: "05-01"
    provides: "Submission model + submitter column (email | playwright) so SubmissionOutcome.submitter maps directly to the row column"
  - phase: 05-email-submission-review-queue
    plan: "05-02"
    provides: "build_email_message, resolve_recipient_email, send_via_smtp, SubmissionSendError, SmtpCreds, SmtpConfig — every primitive EmailStrategy composes"
provides:
  - "app.submission.registry: SubmitterStrategy Protocol, SubmissionContext + SubmissionOutcome dataclasses, default_registry() factory, select_strategy() dispatcher"
  - "app.submission.strategies.email.EmailStrategy: the only Phase 5 concrete strategy, stateless (zero DB writes)"
  - "Single dispatch entry point select_strategy(job, description, registry) for the Plan 05-04 pipeline"
  - "Phase 6 plug-in seam: PlaywrightStrategy will satisfy the same Protocol with no caller changes"
affects: [submission, 05-04 submission-pipeline, 05-06 review-queue, 06-playwright-submission]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "runtime_checkable Protocol + dataclass payloads — registry callers depend on the Protocol, not concrete classes, so Phase 6 plugs in without touching select_strategy or the pipeline"
    - "Stateless strategies: Phase 5 strategies have ZERO DB writes (no session in SubmissionContext); the pipeline owns persistence so the registry is unit-testable without a database fixture"
    - "Lazy import inside default_registry() — strategies/email.py imports SubmissionContext from registry.py, so registry.py defers `from app.submission.strategies.email import EmailStrategy` to call time to break the circular"
    - "first-applicable dispatch: select_strategy returns the first strategy whose is_applicable() returns True, mirroring middleware-chain dispatch — Phase 6 will simply prepend PlaywrightStrategy to the registry list"

key-files:
  created:
    - app/submission/registry.py
    - app/submission/strategies/__init__.py
    - app/submission/strategies/email.py
    - tests/submission/test_registry.py
    - .planning/phases/05-email-submission-review-queue/05-03-SUMMARY.md

key-decisions:
  - "SubmissionContext is a dataclass owned by registry.py (not strategies/email.py) so future strategies can extend it via a Phase 6 subclass or optional fields without circular imports"
  - "is_applicable takes `description` as an explicit second argument rather than reading job.description so the pipeline can pass a cleaned / best-effort description for manual-paste jobs without shadowing the Job row"
  - "EmailStrategy.submit does NOT re-resolve the recipient via resolve_recipient_email — the pipeline pre-populates ctx.recipient_email so manual-paste jobs can override the auto-detected address before send"
  - "SubmissionOutcome.submitter is a free-form string (defaults to the strategy.name attribute) that maps 1:1 onto the Submission.submitter column from Plan 05-01 — no enum, no central registry of names"
  - "default_registry() returns a fresh list on every call (not a module-level singleton) so tests cannot mutate global state by passing it without a copy; the cost is a sub-microsecond list construction"
  - "Strategies do not import SQLAlchemy session types — verified by a grep gate in the plan verify step (no `await session`, `session.execute`, `session.add` anywhere in registry.py or strategies/email.py)"
  - "Tests live under tests/submission/test_registry.py (pyproject testpaths root), inheriting the 05-02 directory convention; the plan's app/tests/submission/ path was preemptively corrected to avoid a re-run of the 05-02 fixture-discovery deviation"

patterns-established:
  - "Pattern: registry pattern with Protocol + dispatch function — first-applicable iteration over a list, returning Optional[Strategy]; pipeline treats None as 'no submitter applies' = needs_info"
  - "Pattern: stateless submitter strategies — context dataclass in, outcome dataclass out, no session, no DB; pipeline interprets the outcome and writes the row"
  - "Pattern: name-as-attribute on Protocol — the Protocol declares `name: str` so registry consumers can read it without isinstance() narrowing"

# Metrics
duration: ~12 min
completed: 2026-04-15
---

# Phase 5 Plan 05-03: Submission Strategy Registry Summary

**SubmitterStrategy Protocol + EmailStrategy concrete implementation behind a single `select_strategy(...)` dispatch point, fully unit-tested without a database fixture and Playwright-ready for Phase 6.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-04-15
- **Tasks:** 2/2 executed
- **Files created:** 4 (3 app modules + 1 test file)
- **Files modified:** 0
- **New tests:** 8 (all green)
- **Project test suite:** 253 passed (245 from 05-02 + 8 from 05-03), 1 pre-existing failure in `tests/submission/test_suppression.py` belonging to a parallel plan (05-05/05-07) — unrelated to 05-03 and confirmed present before any 05-03 commit landed.

## Accomplishments

- `app/submission/registry.py` ships the SUBM-06 surface: `SubmitterStrategy` Protocol (runtime_checkable), `SubmissionContext` dataclass carrying everything a strategy needs (job, paths, recipient, subject, body, attachment filename, smtp_creds), `SubmissionOutcome` dataclass returning success + submitter + error_class + error_message, `default_registry()` factory, and `select_strategy(job, description, registry=None)` dispatcher.
- `app/submission/strategies/email.py` implements the only Phase 5 strategy: `EmailStrategy` composes `build_email_message` + `send_via_smtp` + `resolve_recipient_email` from Plan 05-02, catches `SubmissionSendError` and converts it to a failed `SubmissionOutcome` carrying the stable `error_class` / `error_message` payload that the Plan 05-05 failure-suppression table will hash on.
- 8 unit tests covering: `is_applicable` for parseable / noreply-only / empty descriptions, `select_strategy` routing + None fallback, `default_registry` length + name + Protocol conformance via `isinstance`, `submit` success path with monkeypatched `send_via_smtp` (asserts forwarded From/To/Subject and faithful SmtpConfig population), and `submit` failure path wrapping `SMTPAuthenticationError`.
- Strategies are stateless (verified by grep gate against `session.execute`, `session.add`, `await session`, `session.commit`, `session.flush` — zero hits in either registry.py or strategies/email.py). The Plan 05-04 pipeline owns persistence.

## Task Commits

Each task committed atomically:

1. **Task 1: SubmitterStrategy protocol + SubmissionContext + registry** — `88e9fc4` (feat)
2. **Task 2: EmailStrategy implementation + registry unit tests** — `2bb784a` (feat)

## Files Created

- `app/submission/registry.py` — Protocol + dataclasses + dispatcher (135 lines)
- `app/submission/strategies/__init__.py` — package marker with module docstring
- `app/submission/strategies/email.py` — EmailStrategy (89 lines)
- `tests/submission/test_registry.py` — 8 unit tests (174 lines)

## Decisions Made

- **SubmissionContext lives in registry.py.** Strategies import the dataclass from registry.py (not the other way around), which means future strategies can subclass or extend the context without dragging registry.py into a circular import. The cost is one lazy import inside `default_registry()` to construct EmailStrategy on demand.
- **`is_applicable(job, description)` takes description explicitly.** The pipeline (05-04) can pass a cleaned / best-effort description for manual-paste jobs without mutating `job.description`. This decouples strategy applicability from the Job row's stored description so MANL-01..06 can flow through the same dispatch.
- **`submit` does not re-resolve the recipient.** The pipeline pre-populates `ctx.recipient_email`, which means manual-paste flows can override the auto-detected address before send. EmailStrategy.is_applicable still uses `resolve_recipient_email` so the dispatcher knows to pick it; submit just trusts the context.
- **`SubmissionOutcome.submitter` mirrors the strategy `name` attribute** and maps 1:1 onto the `Submission.submitter` column from Plan 05-01. No enum, no central name registry — strategies declare their own name and the column accepts whatever string they return.
- **`default_registry()` returns a fresh list on every call.** Avoids a module-level mutable singleton and makes tests harder to pollute. Construction cost is sub-microsecond.
- **Tests preemptively placed under `tests/submission/`** (pyproject testpaths root) rather than the plan's `app/tests/submission/` path — the Plan 05-02 deviation already established this convention and reapplying it here saves an unnecessary deviation roundtrip.
- **Zero-DB invariant enforced by grep gate.** The plan verify step greps strategies/email.py and registry.py for any `session.*` access pattern. Both files return clean — strategies are pure send wrappers; the pipeline owns row writes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking convention] Test directory placed at `tests/submission/test_registry.py`, not `app/tests/submission/test_registry.py` as written in the plan**
- **Found during:** Task 2 file creation (preemptive — known from Plan 05-02 STATE.md note)
- **Issue:** The plan specifies `app/tests/submission/test_registry.py`, but `pyproject.toml` sets `testpaths = ["tests"]` and the shared async_session / env_with_fernet fixtures live only in `tests/conftest.py`. Test files placed under `app/tests/` are neither discovered by pytest nor fixture-reachable. Plan 05-02 hit and fixed this exact issue (commit 6c38d70 / 12064fa).
- **Fix:** Created `tests/submission/test_registry.py` directly. Did not create the doomed `app/tests/submission/` path at all.
- **Files affected:** `tests/submission/test_registry.py`
- **Verification:** `pytest tests/submission/test_registry.py -v` → 8 passed; full suite (excluding pre-existing failing suppression test) 253 passed.
- **Committed in:** `2bb784a` (Task 2)

---

**Total deviations:** 1 auto-fixed (preemptive convention alignment with 05-02)
**Impact on plan:** Zero — surface and exports match the plan exactly; only the test path differs from the literal text in the `<files>` element.

## Issues Encountered

- **Pre-existing failing test in `tests/submission/test_suppression.py::test_fresh_signature_after_clear_treated_as_new`** — confirmed unrelated to 05-03 by stashing all 05-03 changes, re-running, and reproducing the failure on the plain `master` baseline. The test belongs to a parallel plan (05-05 notifications or 05-07 manual-apply) that landed `test_suppression.py` while 05-03 was in flight. Out of scope; flagged for the owning plan.

## Verification Evidence

- `python -c "from app.submission.registry import SubmitterStrategy, SubmissionContext, SubmissionOutcome, default_registry, select_strategy; print('ok')"` → `ok`
- `python -c "from app.submission.strategies.email import EmailStrategy; s = EmailStrategy(); print(s.name)"` → `email`
- `python -c "from app.submission.registry import default_registry; r = default_registry(); assert len(r) == 1 and r[0].name == 'email'; print('ok')"` → `ok`
- `pytest tests/submission/test_registry.py -v` → 8 passed in 0.54s
- `pytest --ignore=tests/submission/test_suppression.py -q` → 253 passed in 108.55s
- Grep against `app/submission/registry.py` and `app/submission/strategies/email.py` for `session.execute|session.add|session.commit|session.flush|await session` → zero hits (strategies confirmed stateless)
- `isinstance(default_registry()[0], SubmitterStrategy)` returns True (Protocol conformance verified at runtime)

## Next Phase Readiness

**Ready to be consumed by:**
- Plan 05-04 (submission pipeline) — calls `select_strategy(job, job.description)` once per approved job, treats `None` as `needs_info`, builds a `SubmissionContext` from the tailoring record + loaded SmtpCreds, awaits `strategy.submit(ctx)`, and persists the `Submission` row + Job.status transition based on `SubmissionOutcome`.
- Plan 05-05 (failure notifications) — receives `outcome.error_class` + `outcome.error_message` from the pipeline; the existing stable identifiers from `SubmissionSendError` flow through unchanged.
- Phase 6 (Playwright submission) — adds `PlaywrightStrategy` to `app.submission.strategies.playwright`, satisfies the same Protocol, and either prepends to the default_registry list (preferred for a known ATS) or appends after EmailStrategy (fallback). `SubmissionContext` may grow optional Playwright-only fields (browser context, ATS form schema, learning loop selectors) without affecting EmailStrategy.

**Blockers/concerns for next plans:**
- `SubmissionContext` does not yet carry a `from_addr` field — EmailStrategy currently uses `ctx.smtp_creds.username` as the From address. If Plan 05-04 needs to use `profile.email` instead (per the Plan 05-02 blocker note about user identity vs SMTP auth user), `SubmissionContext` will need a new `from_addr: str` field and EmailStrategy.submit will need to read it. Cheap one-line change; flagged here so 05-04 catches it.
- `EmailStrategy.submit` has no retry/backoff — it bubbles `SubmissionSendError` (after wrapping it) on the first failure. Plan 05-04 must decide whether transient errors (`SMTPServerDisconnected`, `SMTPTimeoutError`) get retried at the pipeline layer or just go straight into the failure suppression table. Plan 05-02 already flagged this same concern.
- Phase 6 PlaywrightStrategy will need a different applicability signal (source = known ATS slug + has form schema). The Protocol's `is_applicable(job, description)` signature does not currently expose source or schema directly, but the strategy can read `job.source` from the passed Job instance. No Protocol change required — just a docstring update when Phase 6 lands.

## Self-Check: PASSED

All declared `key-files.created` exist on disk:
- `app/submission/registry.py` — FOUND
- `app/submission/strategies/__init__.py` — FOUND
- `app/submission/strategies/email.py` — FOUND
- `tests/submission/test_registry.py` — FOUND
- `.planning/phases/05-email-submission-review-queue/05-03-SUMMARY.md` — FOUND (this file)

All Task commit hashes resolve in `git log`:
- `88e9fc4` — FOUND (Task 1: feat(05-03): add SubmitterStrategy protocol and registry selector)
- `2bb784a` — FOUND (Task 2: feat(05-03): add EmailStrategy and registry unit tests)

---
*Phase: 05-email-submission-review-queue*
*Completed: 2026-04-15*
