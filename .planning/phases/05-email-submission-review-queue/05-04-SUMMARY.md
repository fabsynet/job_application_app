---
phase: 05-email-submission-review-queue
plan: "05-04"
subsystem: submission
tags: [aiosmtplib, holdout, quiet-hours, rate-limit, idempotency, pipeline-stage, notifications, scheduler]

# Dependency graph
requires:
  - phase: 05-01
    provides: Submission + FailureSuppression tables, partial UNIQUE index ux_submissions_job_sent, CANONICAL_JOB_STATUSES + assert_valid_transition, Settings.submissions_paused + auto_holdout_margin_pct + base_url + notification_email
  - phase: 05-02
    provides: build_subject / build_attachment_filename / extract_cover_letter_plaintext / resolve_recipient_email / build_email_message / load_smtp_creds / send_via_smtp / SubmissionSendError
  - phase: 05-03
    provides: SubmitterStrategy Protocol + SubmissionContext + SubmissionOutcome + default_registry + select_strategy + EmailStrategy
  - phase: 05-07
    provides: send_success_notification + send_failure_notification + build_signature + should_notify + clear_suppressions_for_stage + notification templates
  - phase: 04 (tailoring)
    provides: TailoringRecord with retry_count + validation_passed + tailored_resume_path + cover_letter_path, compute_keyword_coverage
  - phase: 01 (scheduler envelope)
    provides: RateLimiter.await_precheck + record_submission + random_action_delay, KillSwitch.raise_if_engaged, SchedulerService._execute_pipeline composition

provides:
  - app/submission/holdout.py::should_auto_submit + HoldoutDecision (SC-2 low-confidence decision)
  - app/submission/service.py::insert_pending / mark_sent / mark_failed / list_tailored_jobs / list_approved_jobs / flip_job_status + IdempotentDuplicate (single DB-write surface for Phase 5)
  - app/submission/pipeline.py::run_submission — the drain loop (pause → auto-holdout → quiet-hours → cap → recipient → strategy → send → mark+notify)
  - app/submission/builder.py::extract_docx_plaintext — plain-text DOCX reader for holdout keyword coverage
  - SchedulerService._execute_pipeline wiring: discovery → tailoring → submission, all three stages merge counts into Run.counts
  - First live caller of RateLimiter.record_submission in the codebase
  - First enforcement site for Settings.quiet_hours_start / quiet_hours_end

affects: [06-manual-apply, 06-playwright-stage, dashboard-run-summary, notifications-ui]

# Tech tracking
tech-stack:
  added: []  # no new runtime deps, pure composition
  patterns:
    - "Drain-loop guards in strict order: pause → auto-holdout → quiet-hours → rate-limit precheck → recipient → strategy → send"
    - "Lazy per-function imports mirror run_tailoring pattern to survive live_app importlib.reload(app.config)"
    - "Flat counts dict with boolean halt markers (paused, rate_limited, quiet_hours_skipped) for dashboard render"
    - "Single DB-write surface for Job.status via flip_job_status(session, job_id, target, reason=) — every Phase 5 transition goes through assert_valid_transition"
    - "insert_pending → send → mark_sent/mark_failed is the canonical Phase 5 submit sequence; IdempotentDuplicate surfaces the partial UNIQUE index collision as a typed no-op"

key-files:
  created:
    - app/submission/holdout.py
    - app/submission/service.py
    - app/submission/pipeline.py
    - tests/submission/test_holdout.py
    - tests/submission/test_pipeline.py
  modified:
    - app/submission/builder.py (added extract_docx_plaintext helper)
    - app/scheduler/service.py (lazy-import run_submission inside _execute_pipeline; merged submission counts into _last_counts)

key-decisions:
  - "retry_count<=1 is first-try success per engine.py line 567 (retry+1 semantic); retry_count==0 is the catastrophic early-exit branch and is treated as first-try for the holdout because the validation_passed gate fires first in practice"
  - "Holdout required coverage clamped to [0,100] so threshold=95 + margin=50 does not demand an impossible 145% coverage"
  - "Quiet hours sampled ONCE before the drain loop, not re-sampled per job — matches Phase 1 precheck semantics; remainder stays approved for next run"
  - "Smtp creds + Profile loaded ONCE per drain loop (not per job) for correctness (stable attachment filename) and perf"
  - "Daily cap halt breaks out of the drain loop cleanly, leaving unsent jobs in status='approved' — matches SC-2 and the tailoring-stage budget-halt pattern"
  - "Pipeline flips Job.status only via flip_job_status (service helper) which validates every transition via assert_valid_transition; strategies remain stateless"
  - "Signature suppression is internal to send_failure_notification — pipeline does NOT call build_signature directly, so future signature schema changes touch exactly one module"
  - "IdempotentDuplicate surfaces partial UNIQUE index collision as a typed exception; pipeline counts as submitted, skips second notify — never raises"
  - "Missing SMTP creds at drain-loop start is a pipeline-level halt (not a per-job flip-failed storm) — one failure notification fires and the remaining jobs stay approved under a new submission_skipped count"
  - "Test suite uses a _FakeRateLimiter so per-job random delay (rate_limiter.random_action_delay) is 0.0 — real asyncio.sleep is injected via the sleep kwarg (unused in tests)"

patterns-established:
  - "Pattern: Drain-loop guard order — pause first (no queue walk), auto-holdout branch next (transforms tailored → approved), quiet-hours sample once, rate-limit precheck per-job, then recipient/strategy/send. Future Phase 6 Playwright stage should reuse this exact sequence."
  - "Pattern: flip_job_status is the *only* Phase 5 Job.status writer — every transition is validated via assert_valid_transition; service tests cover forbidden transitions at the helper layer"
  - "Pattern: failure suppression stays out of the pipeline — the sender owns signature build + should_notify; callers see bool-returning never-raising notification helpers"

# Metrics
duration: ~30min
completed: 2026-04-15
---

# Phase 5 Plan 04: Submission Pipeline Stage Summary

**The drain loop comes alive: pause → auto-holdout → quiet-hours → cap → recipient → strategy → send, with idempotent CRUD, rate-limiter accounting, and suppression-gated success/failure notifications composed over the Wave 1+2 primitives.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 (both auto-type, no checkpoints)
- **Files created:** 5
- **Files modified:** 2
- **Test count delta:** +21 (10 holdout + 11 pipeline)
- **Full suite:** 321/321 green in ~49s

## Accomplishments

- **SC-1 fail-closed** — missing recipient OR no applicable strategy → `needs_info` + failure notification (never a silent drop)
- **SC-2 holdout + cap halt** — `retry_count<=1 AND coverage >= threshold+margin` guards auto-submission; daily-cap halt breaks the drain loop cleanly, remainder stays `approved` for next run
- **SC-4 per-submission cadence** — every successful send fires one success notification + clears matching failure-suppression rows; every failure fires one notification subject to signature suppression
- **SC-7 idempotency** — partial UNIQUE index `ux_submissions_job_sent` enforced in-code via `IdempotentDuplicate` sentinel; second pipeline pass on the same job is a clean no-op because the job has already transitioned out of `approved`
- **First live consumer of RateLimiter.record_submission** (research surprise finding #2)
- **First enforcement site for Settings.quiet_hours_start/end** (research surprise finding #1)
- **Scheduler composition** — `_execute_pipeline` now runs discovery → tailoring → submission; `_last_counts` merges all three stage dicts into a unified `Run.counts` JSON blob for the dashboard

## Task Commits

1. **Task 1: Holdout decision + submission service (CRUD + idempotency)** — `788b392` (feat)
2. **Task 2: run_submission pipeline stage + scheduler integration** — `31090b6` (feat)

**Plan metadata:** pending — `docs(05-04): complete submission pipeline plan`

## Files Created/Modified

- **app/submission/holdout.py** (NEW) — `should_auto_submit` + `HoldoutDecision`. Locks `retry_count<=1 AND validation_passed is True AND coverage >= threshold+margin`. Required coverage clamped to [0,100].
- **app/submission/service.py** (NEW) — `insert_pending` / `mark_sent` / `mark_failed` / `list_tailored_jobs` / `list_approved_jobs` / `flip_job_status` + `IdempotentDuplicate`. Single DB-write surface for every `Submission` row and every `Job.status` transition in Phase 5. `mark_sent` wraps `IntegrityError` → `IdempotentDuplicate` so partial-unique-index collisions surface as typed no-ops.
- **app/submission/pipeline.py** (NEW) — `run_submission(ctx, session_factory, *, rate_limiter, killswitch_check=None, registry=None, clock=None, sleep=None)`. Returns `{submitted, submission_failed, needs_info, held_out, paused, rate_limited, quiet_hours_skipped, submission_skipped}`. Lazy per-function imports match the tailoring-stage reload-safety pattern.
- **app/submission/builder.py** (MODIFIED) — added `extract_docx_plaintext` helper. Single-newline join (distinct from `extract_cover_letter_plaintext`'s blank-line join) used only by the holdout keyword-coverage check.
- **app/scheduler/service.py** (MODIFIED) — `_execute_pipeline` now lazy-imports `run_submission` and merges submission counts. Top-level import graph unchanged to preserve the Phase 4 `live_app` reload contract.
- **tests/submission/test_holdout.py** (NEW) — 10 tests covering retry_count semantics, validation gates, coverage thresholds, and an engine-anchor guard that re-reads `app/tailoring/engine.py` source at runtime.
- **tests/submission/test_pipeline.py** (NEW) — 11 integration tests: happy path, idempotency, low-confidence holdout, review/auto branches, daily cap halt, pause toggle, quiet hours, missing recipient, SMTP auth error, signature suppression. Uses in-memory session factory + monkeypatched `aiosmtplib.send` + `_FakeRateLimiter`.

## Decisions Made

- **`retry_count` semantics locked via runtime engine-anchor guard.** `should_auto_submit` accepts `retry_count <= 1` as first-try success. A dedicated test re-reads `app/tailoring/engine.py` source and asserts the `retry_count=retry + 1` pattern still exists — if a future refactor drops this, the guard test flies a red flag before the holdout silently starts holding out every job.

- **Holdout required percentage clamped to [0, 100].** Pathological Settings config (e.g. `match_threshold=95 + auto_holdout_margin_pct=50`) is coerced to a 100% requirement rather than an impossible 145%. Tests cover both the clamp and the exact-at-required eligibility edge.

- **Drain loop guard order is strict and documented in the module docstring.** Pause first (never walk the queue if paused), auto-holdout branch next (transforms `tailored → approved` in bulk), then per-drain: killswitch, rate-limit precheck, recipient resolution, strategy selection, insert_pending, submit, mark+notify, delay.

- **Quiet hours sampled once before the drain loop.** Matches Phase 1 rate-limit precheck semantics — if we're in quiet hours, the whole stage exits; we don't wake up halfway through a batch to halt. Remainder stays `approved` for the next pipeline tick.

- **Smtp creds + Profile cached per drain loop, not per job.** Two rationale: (1) stable attachment filename across a batch, (2) no redundant Fernet decryption per job. If creds are missing at load time the pipeline fires one `SmtpCredsMissing`-stage failure notification, sets `submission_skipped = len(approved_pairs)`, and returns without a per-job flip-failed storm.

- **`IdempotentDuplicate` is a typed no-op, not an error.** When the partial UNIQUE index fires on `mark_sent`, the pipeline logs at WARN, counts the job as `submitted`, and `continue`s — no double notification. The sentinel lives in `app/submission/service.py` alongside `mark_sent` so any future code path that calls `mark_sent` directly inherits the same contract.

- **Pipeline never calls `build_signature` directly.** Suppression logic is internal to `send_failure_notification` — caller passes `stage`, `error_class`, `error_message`, `job`, and the sender builds the signature + consults `should_notify`. This keeps the suppression schema owned by one module (05-07).

- **`mark_failed` records `failure_signature=None`** for now. The pipeline already hands `error_class` + `error_message` to `send_failure_notification` which does its own canonicalization + hashing; wiring a second signature build just for the Submission row would mean two sources of truth. Future cleanup: expose a `get_signature_from_last_notify` helper from 05-07 and populate the Submission row for audit.

- **`_FakeRateLimiter` in tests makes `random_action_delay` return 0.0** so tests don't accidentally sleep. The pipeline also accepts a `sleep=` kwarg for test injection — currently unused by tests because the zero-delay path is enough, but the hook is in place for future timing-sensitive tests.

- **Test DOCX bodies deliberately contain keyword-overlap text** (`"Python FastAPI Postgres Docker Kubernetes async services"`) so the holdout coverage check passes with the Phase 5 default `match_threshold=10 + margin=10 = 20%`. The `test_low_confidence_holdout_leaves_job_in_tailored` test uses `retry_count=3` rather than low coverage so the test clearly exercises the retry gate independently of the coverage branch.

## Deviations from Plan

None - plan executed exactly as written. Two minor shape refinements below are not deviations but clarifications of the plan's "done" contract.

**Refinement A — `extract_docx_plaintext` added as a new builder helper rather than inlined in the pipeline.** The plan said "plant a helper in `app/submission/builder.py` called `extract_docx_plaintext(path) -> str` if not already present" — I added it explicitly and exported it so the pipeline's import stays clean and a future Plan 06 can reuse it for the Playwright transcript check.

**Refinement B — `submission_skipped` counter added for the "creds missing at drain-loop start" branch.** The plan enumerated `submitted/failed/needs_info/skipped/paused/rate_limited/held_out` as count keys; I surfaced `submission_skipped` as a distinct integer (not a bool) so the dashboard can show "N jobs queued, skipped because SMTP creds missing." This is additive — the plan's required keys are all present.

## Issues Encountered

**1. Initial test descriptions had no keyword overlap with the tailored DOCX.**

The first pipeline-test seed used `"Contact us at hr@acme.example.com to apply"` which has near-zero token overlap with `"Python FastAPI Postgres Docker Kubernetes"`, so the holdout coverage check returned 0% and the tailored job got held out of the auto branch. Fixed by adding a `_DEFAULT_DESCRIPTION` constant that leads with `"Python FastAPI Postgres Docker Kubernetes async services"` before the contact email. This is a test-scaffolding quirk, not a pipeline bug — the holdout is doing exactly what SC-2 says it should do for low-coverage content.

**Fix time:** ~2 minutes. Full suite went from 2 failed → 321/321 green.

## User Setup Required

None. No new runtime dependencies. No new environment variables. No new database columns (Plan 05-01 already shipped `submissions_paused`, `auto_holdout_margin_pct`, `base_url`, `notification_email`).

Operator-visible behavior change: once the container is rebuilt with this plan's code, a scheduled pipeline run will actually send email to recruiters when:
  1. `Settings.submissions_paused = False` (default)
  2. Current hour is outside the quiet window (default 22..7 UTC)
  3. At least one job is in `status='approved'` (or `status='tailored'` + auto-mode + holdout pass)
  4. A non-noreply recipient email is extractable from `Job.description`
  5. SMTP creds are configured (`smtp_host/port/user/password` Secret rows)

For a dry-run smoke test: seed one `approved` job, monkeypatch `aiosmtplib.send`, hit `POST /runs/run-now`, inspect logs for `submission_sent` and `Run.counts['submitted']: 1`.

## Next Phase Readiness

- **05-04 pipeline stage:** stable. Composes 05-01 schema + 05-02 primitives + 05-03 registry + 05-07 notifications. SchedulerService wiring done.
- **05-06 manual-apply:** unblocked. Can paste a URL, run the standard tailoring path, and `run_submission` will drain the resulting approved job through the email strategy.
- **Phase 6 Playwright stage:** unblocked for ATS-form jobs. `select_strategy(job, description, registry)` already returns `None` when `EmailStrategy.is_applicable` rejects a noreply-only / empty description — prepending `PlaywrightStrategy` to the registry lets it take the job without touching `run_submission`.
- **Phase 5 phase-end visual sweep:** still pending from 05-05's Task 3 deferral (8 UX scenarios documented in 05-05-SUMMARY.md Deviation #1). Does not block 05-06.

### Concerns carried forward

- **`rate_limiter.record_submission` is called inside a session scoped to the same "success" block as `mark_sent` + `flip_job_status` + `send_success_notification` + `clear_suppressions_for_stage`.** All four operations commit through that one session. If the success notification's SMTP call fails after `record_submission` has incremented the counter, the counter still sticks — the notification failure does not roll back the count. This matches the SC-4 contract ("one send attempt = one counter tick") but should be documented in the dashboard ("Rate limit counter reflects attempted sends, not successfully notified sends").

- **`mark_failed` records `failure_signature=None`** for Submission rows today. The Submission audit trail has `error_class` + `error_message` so it is fully actionable, but a future UI that wants to group failed submissions by signature will need to either backfill (sha256 pass on historical rows) or accept the NULL. Filed as a cleanup — low priority.

- **Cover-letter-missing path is non-fatal.** If `TailoringRecord.cover_letter_path` is None or unreadable, the pipeline logs a warning and sends an empty email body. The plan explicitly permits this ("cover letter write failures are non-fatal" from 04-05 decision) but operators with auto-mode on may want a stricter "require cover letter or hold out" setting. Deferred.

- **`submission_skipped` counter is only set when SMTP creds are missing at drain-loop start.** If creds disappear mid-loop (unlikely but possible during a Settings mutation race), subsequent jobs will flip to `failed` via the per-job failure branch rather than `submission_skipped`. The race is mitigated by the load-once-per-loop pattern.

- **No retry/backoff at the send level.** One-shot per run per job, matching the research plan's locked "v1 = no send-level retry" decision. If a transient SMTPServerDisconnected happens, the job flips to `failed`; it re-enters the queue only if the user clicks "Retry" in the review UI. Phase 5 explicitly accepts this.

---
*Phase: 05-email-submission-review-queue*
*Completed: 2026-04-15*

## Self-Check: PASSED

- app/submission/holdout.py — FOUND
- app/submission/service.py — FOUND
- app/submission/pipeline.py — FOUND
- app/submission/builder.py — FOUND (modified: extract_docx_plaintext)
- app/scheduler/service.py — FOUND (modified: lazy-import run_submission inside _execute_pipeline)
- tests/submission/test_holdout.py — FOUND
- tests/submission/test_pipeline.py — FOUND
- commit 788b392 — FOUND (feat 05-04 Task 1)
- commit 31090b6 — FOUND (feat 05-04 Task 2)
- Full suite: 321/321 green
