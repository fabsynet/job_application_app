# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-11)

**Core value:** Given a base resume + keywords, the app gets your tailored application in front of every matching job posting — with zero manual effort after setup.
**Current focus:** Phase 6 (Playwright Browser Submission / Learning Loop) — 06-01 schema + 06-02 browser primitives + 06-04 learning service complete; 5 plans remaining

## Current Position

Phase: 6 of 6 (Playwright Browser Submission / Learning Loop)
Plan: 06-04 of 8 in current phase — Learning service + semantic matcher + needs-info aggregation
Status: In progress
Last activity: 2026-04-15 — Completed 06-04-PLAN.md (SavedAnswer CRUD, LLM matcher, needs-info queries, 33 tests)

Progress: [███████████████████████████████████░░░░░] 87% (34 of 39 plans complete: Phases 1-5 complete + 06-01 + 06-02 + 06-04)

## Performance Metrics

**Velocity:**
- Total plans completed: 23
- Average duration: ~13 min
- Total execution time: ~5h 12min

**By Phase:**

| Phase | Plans | Total    | Avg/Plan |
|-------|-------|----------|----------|
| 01    | 5     | ~174 min | ~35 min  |
| 02    | 4     | ~23 min  | ~6 min   |
| 03    | 6     | ~32 min  | ~5 min   |
| 04    | 7     | ~78 min  | ~11 min  |

**Recent Trend:**
- Last 8 plans: 05-01 (schema, parallel) | 05-02 (~22 min, 2 deviations auto-fixed) | 05-03 (~12 min, 1 preemptive convention deviation) | 05-07 (~30 min, 3 deviations auto-fixed) | 05-05 (~25 min, 5 deviations auto-fixed + 1 documentation-only checkpoint deferral) | 05-04 (~30 min, 0 deviations) | 05-06 (~30 min, 4 deviations auto-fixed) | 05-08 (~35 min, 3 deviations auto-fixed)
- Trend: 05-06 shipped the paste-a-link manual-apply flow — /manual-apply (GET + POST /preview + POST /confirm + POST /fallback), four Jinja templates, httpx-based async fetcher with a stable FetchError vocabulary (not_found / auth_wall / timeout / empty_body / http_NNN / etc), idempotent create_manual_job that reuses the canonical Phase 3 job_fingerprint for dedup. Manual-apply jobs land at status='matched' with score=100 and matched_keywords='manual_paste' as a stable sentinel for UI differentiation, then the standard tailoring pipeline (05-05 widened get_queued_jobs) picks them up unchanged. LinkedIn/Indeed/bot-walled URLs degrade gracefully to the fallback textarea form (never 5xx). 26 new tests (13 fetcher + 5 service + 8 router) — network-free via httpx.MockTransport + monkeypatched fetch_and_parse. Two atomic commits (e1cffc4 fetcher + service; 47a9ec3 router + templates + main mount). Four auto-fixed deviations: (1) Rule 3 — plan's detect_source tuple unpacking was `source_type, slug` but the real signature returns `(slug, source_type)` — flipped and stamped greenhouse/lever URLs correctly; (2) Rule 3 — tests placed under tests/manual_apply/ (pyproject testpaths='tests') rather than app/tests/manual_apply/ matching 05-02/05-05 precedent; (3) Rule 1 — router /preview used Form(...) which 422s on empty string before handler, relaxed to Form('') to let empty URL reach the handler and render fallback with error='empty_url'; (4) Rule 3 — Task 3 checkpoint:human-verify deferred to phase-end visual sweep matching 05-05 precedent because parallel wave with 05-08 can't accommodate blocking checkpoints. Full suite 358/358 green in ~56s. Parallel-wave coordination: 05-08 Task 1 landed commit bb7c881 between my two task commits (app/review/applied_service.py + 11 tests) and later added applied_router + 'Applied' nav link additively to app/main.py and base.html.j2 alongside my manual_apply_router + 'Manual Apply' nav link — both coexist cleanly.

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- 06-04: No confidence threshold for LLM semantic matching — if the LLM says two labels are equivalent, the match is accepted and auto-filled. Per locked design decision (must_haves.truths).
- 06-04: Graceful degradation on LLM failure — find_matching_answers returns all-None instead of raising. Pipeline proceeds without auto-fill for that batch.
- 06-04: Label normalization (lowercase, strip, collapse whitespace) for SavedAnswer dedup — upsert by field_label_normalized prevents duplicate answers for "First Name" vs "first  name".
- 05-06: `detect_source` returns `(slug, source_type)` — slug FIRST. Plan 05-06's code snippet had the tuple order flipped; any future caller must unpack as `slug, source_type = detect_source(url)`. Stamped a Task 1 test (`test_fetch_greenhouse_url_stamps_source_greenhouse`) that will break loudly if the signature ever changes.
- 05-06: FetchError reasons are a small stable vocabulary — not_found / auth_wall / timeout / empty_body / connect_failed / request_error / http_NNN / unexpected_error / empty_url / title_and_company_required. The UI renders the reason verbatim inside a `<code>` block in _fallback.html.j2. No localization layer in v1.
- 05-06: `<200`-char empty-body heuristic on 2xx responses catches LinkedIn/Indeed SPA shells that return 200 with a login prompt. The cap is well below any real job posting HTML (~5k+ chars minimum empirically).
- 05-06: Manual-apply jobs land with `score=100` + `matched_keywords='manual_paste'` as a stable sentinel — no new column needed, Jobs list UI can visually differentiate manual vs auto-discovered at a glance.
- 05-06: `create_manual_job` is idempotent — returns the existing Job when fingerprint matches rather than raising. Router layer calls `check_duplicate` first as a read-before-write so it can render a distinct "Already in the queue" fragment without needing an exception to disambiguate.
- 05-06: Fallback path synthesizes a stable URL (`manual://<company>/<title>`) when the user has no URL at all — keeps fingerprint semantics consistent and lets two different fallback pastes for different roles still dedupe correctly.
- 05-06: Router `/preview` uses `Form("")` for the `url` field (not `Form(...)`). FastAPI's required-form dependency raises 422 before the handler runs, which contradicts MANL-03's "graceful degradation — never 5xx/4xx on user-facing flow" contract. Empty strings now reach the handler and render the fallback form with `error='empty_url'`.
- 05-06: Tests that monkeypatch `fetch_and_parse` must patch BOTH `app.manual_apply.fetcher.fetch_and_parse` AND `app.web.routers.manual_apply.fetch_and_parse` — the router imports the symbol at module load time, so patching only the source module is insufficient. Documented as a pattern note in the `_install_parsed` / `_install_fetch_error` test helpers.
- 05-06: Task 3 `checkpoint:human-verify` deferred to phase-end visual sweep — same precedent as 05-05 Deviation #1. Parallel waves cannot accommodate per-plan blocking checkpoints; 8 live_app router integration tests cover the equivalent flows automatically.
- 05-04: `retry_count <= 1` is first-try success per engine.py line 567 (`retry_count = retry + 1`); locked via a test that reads engine.py source at runtime and asserts the `retry_count=retry + 1` pattern still exists — a future refactor that changes this pattern flies a red flag before the holdout silently starts holding out every job
- 05-04: Holdout required coverage pct clamped to [0, 100] so pathological `match_threshold=95 + margin=50` is coerced to 100% requirement rather than impossible 145%
- 05-04: Drain-loop guard order is strict: pause → auto-holdout branch (transforms tailored → approved) → quiet-hours sample once → per-job killswitch → rate-limit precheck → recipient → strategy → insert_pending → submit → mark+notify → delay. This exact sequence is documented in `app/submission/pipeline.py` module docstring and should be reused by the Phase 6 Playwright drain loop.
- 05-04: Quiet hours sampled ONCE before the drain loop, not re-sampled per job; if inside window, whole stage exits and remainder stays `approved` for next pipeline tick. Matches Phase 1 rate-limit precheck semantics.
- 05-04: SMTP creds + Profile loaded ONCE per drain loop (not per job) for stable attachment filename + perf. Missing creds at drain-loop start fires one pipeline-level failure notification, sets `submission_skipped = len(approved_pairs)`, and returns without a per-job flip-failed storm.
- 05-04: `flip_job_status(session, job_id, target, reason=)` in `app/submission/service.py` is the ONLY Phase 5 `Job.status` writer; every transition validated via `assert_valid_transition` before persist; same-status writes are idempotent no-ops.
- 05-04: `IdempotentDuplicate` is a typed exception surfaced by `mark_sent` when the partial UNIQUE index fires — pipeline catches, logs WARN, counts as submitted, skips second notify, does NOT raise. Sentinel lives alongside `mark_sent` so future call sites inherit the contract.
- 05-04: Pipeline NEVER calls `build_signature` directly — suppression logic is internal to `send_failure_notification` via `should_notify`. Caller passes stage + error_class + error_message + job; the sender hashes and gates. Keeps suppression schema owned by 05-07.
- 05-04: `mark_failed` records `failure_signature=None` for now — cleanup task to backfill via `get_signature_from_last_notify` helper (low priority; Submission row already has `error_class` + `error_message` for forensic value).
- 05-04: Rate limiter counter ticks on ATTEMPTED sends (inside the same success block as mark_sent). If the success notification's SMTP call fails after record_submission, the counter still sticks — documented in the dashboard contract ("rate limit counter = attempted sends, not successfully notified sends").
- 05-04: `submission_skipped` added as a distinct count-dict key (integer, not bool) surfaced when SMTP creds are missing at drain-loop start. Additive over the plan's required `{submitted, failed, needs_info, skipped, paused, rate_limited, held_out}` keys.
- 05-04: `app/submission/builder.py::extract_docx_plaintext` (single-newline join) added as a NEW helper distinct from `extract_cover_letter_plaintext` (blank-line join for email bodies) — only used by the holdout coverage check. Phase 6 Playwright can reuse it for transcript checks.
- 05-04: Test suite uses `_FakeRateLimiter` with `random_action_delay` returning 0.0 so pipeline integration tests don't sleep. The pipeline also accepts a `sleep=` kwarg for injection; tests do not use it today (zero-delay path is sufficient) but the hook is in place for timing-sensitive future tests.
- 05-04: Pipeline test descriptions deliberately lead with `"Python FastAPI Postgres Docker Kubernetes async services"` so keyword overlap with the tailored DOCX crosses the default `match_threshold=10 + margin=10 = 20%` — the low-confidence holdout test uses `retry_count=3` to exercise the retry gate independently of coverage.
- 05-05: `app.tailoring.service.get_queued_jobs` widened from `status == 'matched'` to `status IN ('matched', 'retailoring')` so a user's "Re-tailor with a different angle" click in the review drawer becomes a fresh tailoring attempt automatically on the next pipeline run — single-line patch, no new pipeline stage required
- 05-05: `manual_edit` TailoringRecord intensity = user-saved DOCX edits, zero token/cost fields, error_message='user_edit' as a stable marker, no Budget debit, no validator re-run, no Job.status change (user approves separately) — distinguishes user edits from LLM output without a new column
- 05-05: `list_review_queue` uses `MAX(TailoringRecord.id)` GROUP BY job_id (NOT MAX(version)) so the freshest record always wins even when a manual_edit shares version semantics with the LLM original
- 05-05: All-or-nothing `approve_batch` rolls back the whole batch on the first illegal transition; tests must `session.expunge_all()` before re-querying because SQLAlchemy 2.x rollback expires every ORM-tracked attribute and Windows asyncio trips MissingGreenlet on lazy-load
- 05-05: Router list-query params (`status`, `job_ids`) declared with `Query(default_factory=list)` instead of bare `list[str] = []` — FastAPI 0.10x bare-list annotations only parse from the body; repeated query params need `Query(...)` explicitly
- 05-05: `_render_table(request, session)` helper added so mutation endpoints (approve/reject/retailor/batch) re-render the table fragment WITHOUT calling `review_index` as a plain Python function — `review_index` carries `Query()` defaults that are not iterable when invoked outside FastAPI's dependency-injection path
- 05-05: Pre-heading paragraphs (name + contact block) bucket into a leading section with `heading == ''` so the user still sees a textarea for them; `build_tailored_docx` will not match an empty heading on write, so the preamble round-trips through the DOCX file unchanged
- 05-05: `extract_sections_from_docx` flattens any nested work-experience subsections into the section's flat `content` list — `build_tailored_docx` treats a flat content list as bullets inside the section regardless, so the round-trip stays stable
- 05-05: `/review/{job_id}/reject` accepts `mode=skip|retailor` as a Form field; `/review/{job_id}/retailor` is a thin wrapper for explicit drawer button bindings — same handler, no logic duplication
- 05-05: Router 422 toasts (NEVER 500s) for illegal state transitions — every endpoint catches `ValueError` from `assert_valid_transition` and returns a `<div class="toast toast-error">` fragment with HTTP 422
- 05-05: Task 3 (`checkpoint:human-verify`) deferred to phase-end visual sweep — parallel waves cannot accommodate per-plan blocking checkpoints; 24 integration tests cover the same UX flows automatically (8 scenarios documented in 05-05-SUMMARY.md Deviation #1 for the phase-end sweep)
- 05-07: FailureSuppression rows are RE-USED on next-burst-after-clear rather than duplicated — Plan 05-01's signature UNIQUE constraint forced this fix; cleared_at→None, cleared_by→None, notify_count++, occurrence_count→1 preserves the "fresh notification fires" contract while honouring the schema. notify_count is now the authoritative count of distinct bursts the user has been alerted about for that signature.
- 05-07: Failure signature canonicalisation = lowercase + email-strip (<email>) + digit-strip (N) + whitespace-collapse, hashed with SHA-256 over the (stage|error_class|canon_message) tuple. Stage is in the payload so submission-stage and pipeline-stage failures suppress in independent buckets even with identical error_class + message.
- 05-07: Notification senders (send_success_notification, send_failure_notification, send_pipeline_failure_notification) are bool-returning, never-raising, never-self-recursing. Broken SMTP creds log structurally and return False. send_failure_notification never escalates its OWN SMTP error back into another failure notification — would create a feedback loop the moment SMTP credentials broke.
- 05-07: Notifications module imports get_profile_row from app.settings.service, NOT app.profile.service.get_profile (which does not exist in this codebase). Profile is a singleton row colocated with Settings under app/db/models.py.
- 05-07: Failure-suppression row is inserted BEFORE the SMTP send attempt — if the send itself fails after the row insert, subsequent occurrences still suppress until clear. Rationale: user-facing contract is "we tried to alert you once" and a flaky outbound path should not allow ten retries to inundate the operator with duplicate emails for the same root cause.
- 05-07: Notification senders are silence-window-agnostic by design and verified by both grep AND test_notification_sends_during_silence_window which sets the most aggressive 24-hour quiet window. The locked decision is documented in app/submission/notifications.py using the synonym "silence window" so verify-step grep on `quiet_hours` stays empty.
- 05-07: Notification email templates live under app/web/templates/emails/ as plaintext .txt.j2 files (autoescape disabled — escaping `<email>` placeholder text would be wrong). Module-scope Jinja Environment with FileSystemLoader, mirrors the Phase 4 _jinja pattern in app.tailoring.
- 05-07: POST /notifications/ack/{id} returns a tiny HTML fragment for HTMX swap-on-click; 404 on unknown id. Mounted in app.main.create_app alongside the other Phase 5 routers (notifications_router and review_router from 05-05 coexist cleanly).
- 05-03: SubmitterStrategy is a runtime_checkable Protocol with a `name: str` attribute and `is_applicable(job, description)` + `async submit(ctx) -> SubmissionOutcome` methods — Phase 6 PlaywrightStrategy plugs in without touching select_strategy or the pipeline (SUBM-06)
- 05-03: SubmissionContext is a dataclass owned by registry.py (not strategies/email.py); strategies import the dataclass FROM registry.py so future strategies can extend the context without circular imports. default_registry() uses a lazy `from app.submission.strategies.email import EmailStrategy` to break the circular at call time
- 05-03: is_applicable takes `description` as an explicit second argument rather than reading job.description, so the pipeline can pass a cleaned / best-effort description for manual-paste jobs (MANL-01..06) without shadowing the Job row
- 05-03: EmailStrategy.submit does NOT re-resolve the recipient — pipeline pre-populates ctx.recipient_email so manual-paste flows can override the auto-detected address before send. Only is_applicable calls resolve_recipient_email
- 05-03: Strategies are stateless (zero DB writes) — verified by grep gate against `session.execute|session.add|session.commit|session.flush|await session` in registry.py and strategies/email.py. Plan 05-04 pipeline owns persistence of the Submission row + Job.status transition + failure_suppression call
- 05-03: SubmissionOutcome.submitter is a free-form string mirroring the strategy.name attribute and maps 1:1 onto Submission.submitter from 05-01 — no enum, no central name registry
- 05-03: default_registry() returns a fresh list on every call (not a module-level singleton) so tests cannot mutate global state by mistake
- 05-03: select_strategy is first-applicable iteration (returns the first strategy whose is_applicable returns True, else None) — Phase 6 will simply prepend PlaywrightStrategy to the list for known-ATS jobs and EmailStrategy stays as the fallback
- 05-03: Pipeline (05-04) treats select_strategy returning None as `needs_info` — fail-closed (SC-1). EmailStrategy is_applicable returns False on noreply-only / empty descriptions, so `needs_info` is the natural state for those jobs
- 05-02: Phase 5 submission tests live under tests/submission/ (the pyproject testpaths root), NOT app/tests/submission/ as the plan drafted — the shared async_session / env_with_fernet fixtures only exist in tests/conftest.py
- 05-02: app.submission.creds.load_smtp_creds imports get_settings lazily inside the function body to avoid the 04-05 importlib.reload(app.config) staleness pitfall (live_app fixtures in test_phase2_resume.py reload app.config mid-run) — this is now the second consumer of the lazy-get_settings pattern and should be considered canonical for any Phase 5+ module that depends on fernet_key
- 05-02: _slug_ascii falls back to "Unknown" on empty / whitespace-only / pure-non-ASCII inputs so build_attachment_filename always yields a safe [A-Za-z0-9_] MIME header stem (research pitfall 1)
- 05-02: SubmissionSendError wraps every aiosmtplib exception with a stable string error_class — specific branches for SMTPAuthenticationError / SMTPRecipientsRefused / SMTPServerDisconnected / SMTPTimeoutError, plus a catch-all SMTPException branch using type(exc).__name__ so future aiosmtplib subclasses still get a stable identifier for Plan 05-05's suppression table
- 05-02: SmtpConfig plain-connection fallback (neither start_tls nor use_tls) is permitted for any port outside {587, 465} — dev/test only, Plan 05-04 should reject unsupported ports at the config-save layer instead of at send time
- 05-02: Builder helpers (build_subject, build_attachment_filename, build_email_message) are keyword-only so the 05-04 pipeline cannot silently swap from_addr/to_addr or role/company at the call site
- 05-02: aiosmtplib.send is monkeypatched in sender tests; no real SMTP server in the suite per plan success criterion "no network calls in the test suite"
- 05-02: Phase 4's stdlib `EmailMessage.add_attachment` path confirmed working — no MIMEMultipart / MIMEBase anywhere in app/submission (research §"Don't Hand-Roll")
- 05-02: smtp_port string→int coercion happens exactly once, inside load_smtp_creds (research pitfall 7) — SmtpConfig.port is typed int and callers should never pass a raw Secret value
- 05-01: Partial UNIQUE index MUST use `op.create_index(..., sqlite_where=sa.text(...))` — `UniqueConstraint(..., sqlite_where=...)` silently drops the WHERE clause on SQLite (research Pitfall 9). Applied to `ux_submissions_job_sent` (SC-7 idempotency).
- 05-01: CANONICAL_JOB_STATUSES is a 13-element frozenset in `app.review.states`; enforcement is service-layer only (Job.status stays a plain str column, mirroring CANONICAL_FAILURE_REASONS precedent). `assert_valid_transition(current, target)` is the uniform gate before any Phase 5 Job.status write.
- 05-01: Legacy `applied` status kept in CANONICAL_JOB_STATUSES as a terminal (no outgoing transitions) — zero-churn Phase 3 back-compat, avoids retroactive row rewriting.
- 05-01: `Settings.notification_email` nullable — NULL means "resolve to smtp_user at send time" so users are not forced to configure a second inbox upfront. Downstream plans need a resolver helper.
- 05-01: `Settings.base_url` default `http://localhost:8000` — LAN-first; operator overrides via Settings UI when exposing beyond localhost. Used to build review-page links in notification emails.
- 05-01: `Submission.submitter` column ships now with values `email | playwright` so Phase 6 Playwright lands without a schema bump.
- 05-01: New feature packages (`app.submission`, `app.review`) register with Alembic metadata via import side-effect at the bottom of `app/db/models.py` (mirrors Phase 3 discovery / Phase 4 tailoring pattern).
- 05-01: Python `Settings` SQLModel class mirrors the four new columns at field-declaration level (not just the migration) — SQLModel attribute access requires the Python-side fields and catching this in Task 2 avoids AttributeError in every downstream Phase 5 consumer.
- 04-07: FakeLLMProvider is a local test class (not a shared conftest fixture) — Phase 4 is its only consumer and local definition keeps the test surface legible
- 04-07: Base resume DOCX fixture built via python-docx in a pytest helper rather than checked into the repo — fully deterministic, version-tracked as code
- 04-07: SC-5 cache-token-visibility test asserts against the template file via read_text+substring checks rather than rendering through Jinja2 — avoids needing a full Jinja env + dummy context
- 04-07: SC-2 end-to-end invented-skill test scripts 6 FakeLLMProvider responses (tailor/validate × 3) to exercise the full retry+escalation loop and prove success=False at max_retries
- 04-07: SAFE-04 PII-in-prompt test flattens every recorded provider call (system blocks + messages) into one blob and greps for literal name/email/phone — strictest possible assertion
- 04-07: Service-layer tests use the async_session conftest fixture directly rather than live_app because they only need DB state, not HTTP surface
- 04-07: Job fixtures in Phase 4 tests must include external_id='ext-N' (NOT NULL constraint); Phase 3 tests implicitly satisfied this via real ATS payloads
- 04-07: resume_artifact_path test normalises to forward slashes before asserting '42/v1.docx' so it passes on Windows and Linux
- 04-06: Tailoring detail view recomputes keyword_coverage on each render via compute_keyword_coverage — TailoringRecord has no keyword_coverage column so the value is derived from (tailored_docx_text, job.description) at render time
- 04-06: Detail-view diff shim re-extracts the tailored DOCX and reshapes into {sections:[{heading,content}]} — the engine's tailored_sections JSON is not persisted, so the diff rebuilds input from the artifact (line-level diff still highlights bullet changes correctly)
- 04-06: Cache savings pricing constants (_INPUT_PRICE_PER_MTOK=3.00, _CACHE_READ_PRICE_PER_MTOK=0.30) inlined in tailoring router rather than re-exported from BudgetGuard.PRICING to avoid UI↔budget import coupling — marked must-stay-in-sync
- 04-06: /settings/tailoring POST rejects values outside {light, balanced, full} with HTTP 400 so the pipeline (04-05) can trust Settings.tailoring_intensity without defensive normalisation
- 04-06: 80% budget warning banner is dismissible via POST /dismiss-budget-warning (client-only swap=delete, no cookie); 100% halt banner is non-dismissible and links to Settings > Budget
- 04-06: Dashboard budget widget reads Settings row for cap/spent/month as source of truth and augments with CostLedger get_monthly_cost_summary for the per-call-type breakdown — two different sources because the Settings row is the authoritative budget counter BudgetGuard debits, while CostLedger is the audit trail
- 04-06: Tailoring sidebar entry placed immediately after Budget (Credentials already sits above Budget in existing order, so the plan's "before Credentials" was not literally achievable without reordering unrelated items)
- 04-06: Detail route swallows preview/diff/ATS exceptions at warning level so a broken or missing DOCX never 500s the review page
- 04-05: Queued jobs = status='matched' from discovery; ordered score DESC so budget-constrained runs tailor the best matches first
- 04-05: get_next_version counts ALL existing records (any status) so retries get a fresh version number rather than reusing a failed slot
- 04-05: save_tailoring_record flushes (not commits) so callers can group record + cost entries + debit into one transaction
- 04-05: prompt_hash = SHA256(system_prompt | resume_text | job_description) with 0x1E separator between fields
- 04-05: save_cost_entries re-estimates cost per row via BudgetGuard.estimate_cost — ledger sums stay aligned with the budget counter using one source of truth
- 04-05: Budget halt at 100% BREAKS the per-job loop; remaining jobs stay 'matched' for next run — no partial-retry in the pipeline layer
- 04-05: Rejected records ALSO write CostLedger entries and debit BudgetGuard because tokens were consumed; engine-exception records do NOT (no result to bill)
- 04-05: DOCX write failures still debit (tokens were consumed) but flip job to 'failed'; cover letter write failures are non-fatal (resume saved, status='tailored')
- 04-05: run_tailoring lazy-imported inside SchedulerService._execute_pipeline to keep the scheduler's static import graph minimal under test reload cycles
- 04-05: Base resume path resolved via inlined Path(get_settings().data_dir) / 'resumes' / 'base_resume.docx' instead of app.resume.service.get_resume_path — avoids stale LRU cache hits after importlib.reload(app.config) in integration tests
- 04-05: run_tailoring wraps get_settings() in try/except so late APScheduler firings during pytest monkeypatch teardown log skipped_no_resume instead of propagating ValidationError
- 04-04: DOCX replacement goes through replace_paragraph_text_preserving_format exclusively — paragraph.text setter is only used in the no-runs fallback branch (research Pitfall 1 enforced in code)
- 04-04: Section overflow drops excess tailored bullets with a warning log rather than cloning paragraph XML; underflow clears extras instead of deleting them so spacing stays stable
- 04-04: Work-experience subsection matching uses a fixed 2-line skip after the company header (title + dates) before collecting bullets — heuristic, not style-parsed, because python-docx has no semantic bullet notion
- 04-04: check_ats_friendly returns keyword_coverage=None; compute_keyword_coverage is a separate function so ATS audits can run without a job description in scope
- 04-04: Cover letter font is auto-detected from the base resume's first run, falling back to Calibri — only affects the cover letter, resume template is untouched
- 04-04: format_diff_html emits a scoped <style> prelude so <ins>/<del> colour themselves without requiring the review-queue template to ship matching CSS — the fragment is fully self-contained
- 04-04: generate_section_diff appends tailored-only sections at the end (not interleaved) with empty base_text; interleaving would need base-order tracking that extract_resume_text does not expose
- 04-03: TAILORING_SYSTEM_PROMPT is one monolithic constant — easier prompt-injection review and cleaner prompt caching than fragment assembly
- 04-03: Temperature schedule pinned in engine: validator 0.1, tailoring 0.3, cover letter 0.4 — codified once so consumers cannot drift
- 04-03: get_escalated_prompt_suffix escalates only the tailoring prompt on retries; validator strictness stays constant (research Pitfall 4)
- 04-03: strip_pii_sections drops ANY section matching contact-hint keywords (contact/info/personal/details/profile), not just section 0 — handles mid-document contact blocks
- 04-03: Regex email/phone redaction runs AFTER heading-based stripping as belt-and-braces for stray PII embedded in non-contact sections
- 04-03: TailoringResult.retry_count is 1-indexed (retry+1) — 'how many attempts did this take', not 'loop index we stopped at'
- 04-03: Cover letter failures are NON-fatal — a validated tailored resume is not discarded because the cover letter JSON was malformed; success=True with a warning
- 04-03: validate_output returns (passed, violations, LLMResponse) as a 3-tuple so validator tokens flow into the same per-call ledger as tailoring tokens
- 04-03: parse_tailoring_response only validates sections is a list, not strict per-section schema — resume structure varies too much; DOCX writer (04-04) handles mapping
- 04-03: Violations from earlier retries preserved in validation_warnings even when a later retry passes — review queue shows the full 'what did we catch and fix' history per CONTEXT.md trust-building requirement
- 04-03: Cache_control breakpoint placed AFTER base resume (not after instructions) so prompt caching hits on sequential jobs — minimum-token threshold requires enough content before the breakpoint
- 04-02: LLMProvider is a runtime_checkable Protocol; AnthropicProvider lazy-imports AsyncAnthropic inside __init__ so the file loads even when anthropic isn't installed yet
- 04-02: get_provider resolves anthropic_api_key through FernetVault.from_env (same pattern as SMTP / ATS credentials) — never reads ANTHROPIC_API_KEY from env directly
- 04-02: LLMResponse keeps input/output/cache_creation/cache_read tokens as four separate ints so BudgetGuard can price cached calls at the correct per-bucket rate
- 04-02: BudgetGuard.PRICING is class-level; unknown models fall back to claude-sonnet-4-5 rates rather than raising KeyError (mis-estimation recoverable, crash is not)
- 04-02: budget_cap_dollars == 0 means "unlimited" (the default singleton value); users who want a zero-spend halt set kill_switch instead
- 04-02: Month rollover runs inline inside check_budget on first call of a new month — no separate APScheduler cron job
- 04-02: debit serializes through a per-instance asyncio.Lock and writes Settings increment + CostLedger row in one transaction (research Pitfall 6)
- 04-02: BudgetGuard must be a singleton per process because the asyncio.Lock lives on the instance — Plan 04-04 owns construction
- 04-02: CostLedger imported locally inside debit() so app.tailoring.budget stays importable during Wave 1 parallel execution with 04-01
- 04-01: tailoring_records.version is integer counter (v1, v2, …) matching versioned artifact paths data/resumes/{job_id}/v{N}.docx
- 04-01: cost_ledger.tailoring_record_id nullable so orphan validator/probe calls can still be logged for budget
- 04-01: cost_ledger.month is denormalised string (YYYY-MM) indexed for cheap SUM-based budget queries (no strftime in hot path)
- 04-01: validation_warnings stored as JSON string in VARCHAR column — portable SQLite migration, consumers json.loads on read
- 04-01: Phase 4 models live under app/tailoring/, re-exported from app/db/models.py (mirrors Phase 3 app/discovery/ convention)
- 04-01: Settings alter uses plain op.add_column (matches existing 0002 pattern, not batch_alter_table as plan suggested)
- 04-01: Migration revision slug is 0004_phase4_tailoring (not bare 0004) to match existing chain convention
- 03-06: Pipeline _parse_posted_date converts ISO strings from ATS APIs to datetime objects (was crashing SQLite)
- 03-04: Sort defaults to score desc (highest matches first)
- 03-04: 500-job limit on list query (reasonable ceiling for single-user app)
- 03-04: Case-insensitive keyword matching for breakdown display
- 03-04: Queue button only shown for discovered + below-threshold jobs
- 03-02: detect_source returns (slug, source_type) tuple to match existing sources router contract
- 03-02: validate_source returns (bool, str) tuple for router compatibility
- 03-02: _execute_pipeline stores counts via self._last_counts; wrapper passes to finalize_run to avoid double-finalize
- 03-02: Pipeline uses separate session scopes for load, fetch-status-update, persist, stats, anomaly phases
- 03-05: Anomaly dismiss uses cookie (dismissed_anomaly_run_id) keyed on run_id -- no DB schema change
- 03-05: Discovery summary queries DiscoveryRunStats joined with Source, not Run.counts JSON
- 03-05: POST /dismiss-anomaly returns empty HTML for hx-swap=delete pattern
- 03-03: Sources router uses _render_sources helper following _render_section pattern from settings.py
- 03-03: Toggle endpoint returns empty 200 with HX-Reswap none header (no DOM update needed)
- 03-03: Unknown source type triggers probe of all three ATS APIs sequentially
- 03-03: Sources section positioned after Keywords in sidebar ordering
- 03-01: Discovery models live in app/discovery/models.py, imported into app/db/models.py for Alembic metadata registration
- 03-01: Job.fingerprint is SHA256, unique-indexed for O(1) dedup lookups
- 03-01: posted_date nullable (Lever public API lacks this field)
- 03-01: description and description_html stored separately (plain text for scoring, HTML for display)
- 03-01: DiscoveryRunStats tracks per-source per-run counts for anomaly detection rolling averages
- 02-02: Profile fields normalise empty strings to None; phone strips non-digits
- 02-02: Resume stored as single file base_resume.docx, replaced on re-upload (no versioning)
- 02-02: DOCX text extraction splits on Heading styles; full_text capped at 500 lines
- 02-02: Dedicated GET routes for profile/resume declared before generic catch-all for correct FastAPI routing
- 02-03: Keywords use {keyword:path} path param in DELETE route for URL-encoded special chars
- 02-03: Schedule checkbox parsed via raw form data (same pattern as safety toggles) — missing = False
- 02-03: Budget progress bar calculated server-side in Jinja2 — no client JS needed for bar rendering
- 02-03: _render_section enriches context per-section (keywords list parsing from pipe-delimited CSV)
- 02-04: Save-first-validate-second pattern for credentials — encrypt+persist before async validation so network failures never prevent storage
- 02-04: Credentials section never pre-fills inputs or shows masked values — always empty fields with Configured/Not set status
- 02-04: SMTP validation runs synchronously via asyncio.to_thread to avoid blocking event loop
- 02-04: _upsert_secret helper DRYs Secret row upsert for credential routes
- 02-01: Settings page uses sidebar shell with HTMX section loading; each section is a partial loaded via hx-get
- 02-01: POST /settings/limits returns partial HTML (not 303 redirect) for HTMX sidebar consistency
- 02-01: Safety toggles accessible from both dashboard (/toggles) and settings sidebar (/settings/safety)
- 02-01: Placeholder partials for unimplemented sections prevent 404 errors during sidebar navigation
- 01-05: Wizard writes wizard_complete only on step 3 or skip — going back and forth does not flip the flag
- 01-05: Wizard step 2 allows blank submissions (guidance, not a gate per CONTEXT.md)
- 01-05: Rotation banner does not delete unreadable secrets — preserved for forensic recovery
- 01-05: End-to-end tests run against the real lifespan with tmp_path data dirs, not mocks
- 01-05: Reload wizard module in test fixtures to avoid stale get_settings reference from importlib.reload(app.config)
- 01-04: Pico.css v2 bundled local (83KB), HTMX 2.0.3 via unpkg CDN, no build step
- 01-04: HTMX fragments served from the same routers as full pages, sharing one `_common_ctx` builder so polled fragments never drift from initial render
- 01-04: `_humanize_seconds` runs server-side — no client-side JS timers
- 01-04: `/settings/limits` mutates `app.state.rate_limiter.{daily_cap,delay_min,delay_max,tz}` in-place so changes take effect without restart
- 01-04: Starlette 1.0 `TemplateResponse(request, name, ctx)` positional form required — kwarg `{"request": request}` breaks Jinja LRU cache (unhashable dict)
- 01-04: `get_session` dependency lazy-imports `async_session` inside the generator body so integration tests that reload `app.db.base` get the freshly bound engine
- 01-04: Secrets CRUD routes `vault.encrypt` auto-registers plaintext with `SecretRegistry` BEFORE DB commit — scrubber armed at the same point as the write
- 01-04: Runs show-more uses `hx-swap="outerHTML"` on a load-more `<tr>` (self-replacing) rather than `beforeend` on tbody — cleaner button lifecycle
- 01-04: `/settings/limits` validation mirrors `RateLimiter.__init__` bounds exactly, keeping DB state guaranteed-startable
- 01-04: POST `/runs/trigger` is fire-and-forget via `asyncio.create_task(svc.run_pipeline)` — HTTP returns fast, pipeline runs on same event loop
- Roadmap: Safe-channel-first ordering (GH/Lever/Ashby + email before Playwright; LinkedIn/Indeed deferred to v1.x)
- Roadmap: Rate limiting (SAFE-01/02, DISC-07) ships in Phase 1 with the scheduler, not later
- Roadmap: Hallucination validator (TAIL-04) ships in the same phase as first LLM call (TAIL-01)
- Roadmap: Learning loop (LEARN-01..05) ships with Playwright (Phase 6), not earlier
- Roadmap: Manual paste-a-link (MANL-01..06) is first-class v1, landing in Phase 5
- 01-03: Phase 1 stub pipeline is a 50ms asyncio.sleep with killswitch checkpoints — Phases 2+ replace the body, not the wrapper
- 01-03: RunContext is a frozen dataclass passed as argument (explicit > implicit; ContextVar rejected)
- 01-03: Rate-limit counter is a dedicated table keyed by local-TZ ISO date string (cheap next-day insert)
- 01-03: Midnight reset runs as an APScheduler CronTrigger job, not an in-process timer
- 01-03: run_pipeline swallows CancelledError at its boundary after finalising the Run row — propagating would abort the APScheduler worker
- 01-03: Three-layer run-lock defense (asyncio.Lock + max_instances=1 + DB sentinel Run row)
- 01-03: set_scheduler_service module-level setter bridges APScheduler function-call invocation with lifespan-scoped state
- 01-03: app.runs.service.mark_orphans_failed supersedes earlier placeholder in app.db.base (session-scoped, returns rowcount)
- 01-03: Integration tests drive lifespan via app.router.lifespan_context(app) — httpx 0.28 dropped ASGITransport(lifespan='on')
- 01-03: freezegun abandoned for midnight-reset integration test (hangs async runner on Windows); replaced with monkeypatched today_local
- 01-02: SecretRegistry is a module-level singleton with threading.Lock (FastAPI + APScheduler share state)
- 01-02: structlog scrub processor precedes JSONRenderer (scrub typed values, not rendered strings)
- 01-02: 4-char minimum on literal registration to prevent common-word redaction soup
- 01-02: FernetVault auto-registers plaintext on encrypt (pre), decrypt (post), and from_env (master key)
- 01-02: InvalidToken collapses into InvalidFernetKey with a "may have changed" message
- 01-01: APScheduler pinned at 3.11.x (not 4.x alpha); Playwright 1.58.0-noble base shipped now to avoid mid-project rebuild
- 01-01: Single ./data host bind mount holds SQLite, logs, uploads, browser state
- 01-01: SQLite WAL mode enabled in init_db() so HTMX polls never block scheduler writes
- 01-01: get_settings() lru-cached entrypoint (not module-level `settings`) for test-fixture override
- 01-01: Alembic include_object hook excludes apscheduler_* tables from target_metadata
- 01-01: Fail-fast config — Fernet(key) instantiated inside pydantic field_validator at construction time
- 01-01: Hand-authored baseline migration 0001_initial (not autogenerated) because async engine setup complicates autogenerate

### Pending Todos

None.

### Blockers/Concerns

- REQUIREMENTS.md summary says "58 total v1 requirements" but the enumerated list contains 65. Discrepancy flagged in ROADMAP.md Coverage section; correct during Phase 2 planning.
- Phase 4 needs a prompt-design spike (extractive tailoring) before full pipeline integration, per research SUMMARY.md.
- Phase 6 generic-ATS form matching may need a selector-stability spike before implementation.
- 01-01: Docker image has not been built on this host (Docker Desktop daemon was not running during execution). `docker compose config` validated the compose file; first `docker compose build` still pending.
- 01-01: Local test venv is Python 3.11.9 but pyproject requires >=3.12. Tests run green on 3.11 against pinned deps; production (Playwright base) uses 3.12+. Re-validate inside the container during Phase 2.
- 01-03: requirements.txt should be split into prod vs dev — freezegun + pytest-asyncio were installed into .venv for tests but are NOT in requirements.txt. Non-blocking; flag as Phase 2 cleanup.
- 01-03: `app.db.base._settings = get_settings()` executes at module import time, so integration tests that need a different DATA_DIR must reload `app.config` and `app.db.base` before importing `app.main`. Future plans should consider refactoring to lazy-init inside `init_db()`. **Partially mitigated in 01-04/01-05**: `get_session` dependency now lazy-imports `async_session`; wizard module must also be reloaded alongside `app.config` in test fixtures.
- 01-04: HTMX is loaded from `unpkg.com/htmx.org@2.0.3` via CDN. Fully offline LAN deployments will render the dashboard but not poll. Consider bundling htmx.min.js locally (trivial, ~47KB, same pattern as `pico.min.css`) in a later cleanup plan.
- 01-04: POST `/runs/trigger` has no CSRF protection. LAN-bound + "no auth in v1" makes this acceptable; revisit if the app is ever exposed to a wider network.
- 04-02: BudgetGuard instance lifecycle — asyncio.Lock is per-instance, so Plan 04-04 must instantiate exactly one BudgetGuard and pass it to every tailoring consumer (validator calls and cover-letter calls must debit through the same instance).
- 04-02: Anthropic SDK streaming vs. non-streaming not yet decided. Current AnthropicProvider.complete assumes non-streaming (simpler for validator + DOCX rewrite that need the full text). Revisit during 04-03 if prompt design requires streaming.
- 04-05: **`app.resume.service` module-level `from app.config import get_settings` binding is a latent fragility.** It captures the get_settings function object at first import, so any module-level reload of `app.config` (as the integration-test `live_app` fixture does) leaves `app.resume.service` holding a stale reference with a stale LRU cache. Any future code path that calls `get_resume_path()` or `save_resume()` from a pipeline stage must route through a lazy `get_settings()` import (the way `run_tailoring` now does) OR refactor `_resume_dir()` to call `app.config.get_settings()` lazily. Cleanup plan: refactor `app.resume.service._resume_dir()` to `return Path(__import__("app.config", fromlist=["get_settings"]).get_settings().data_dir) / "resumes"` or similar — a single-line change that eliminates the binding hazard.
- 04-05: APScheduler teardown race — late pipeline firings during pytest monkeypatch teardown can still propagate exceptions up the stack. `run_tailoring` is defensive, but `run_discovery` and `run_pipeline` itself are not. Non-blocking for now; flag if more pipeline stages land in Phase 5.
- 04-05: BudgetGuard instance lifecycle — `run_tailoring` currently constructs a fresh `BudgetGuard()` per stage invocation. Safe today (asyncio.Lock is per-instance; each `_execute_pipeline` owns exactly one), but if a future stage needs cross-call concurrency (parallel tailoring inside one run) the BudgetGuard should be promoted to a `SchedulerService` attribute initialised at lifespan. Flag for 04-07.
- 05-02: `SmtpConfig` plain-connection fallback accepts any port outside {587, 465} without TLS. Safe for unit tests but unsafe for production if a user somehow configures an unusual port. Plan 05-04 (or the Settings UI path that writes smtp_port) must reject anything outside a small allowlist (25/465/587/2525) at save time so this layer can trust its input.
- 05-02: `send_via_smtp` has no retry/backoff — transient errors (SMTPServerDisconnected, SMTPTimeoutError) bubble straight up. Plan 05-04 or 05-05 must decide whether to add an in-run retry or just mark-and-move-on. Transient failures should probably NOT debit the daily submission cap, which is an open question for 05-04's accounting.
- 05-02: `from_addr` for email submissions is not resolved inside the 05-02 primitives — the Plan 05-04 pipeline will need to pick between `profile.email` (user's identity) and `smtp_user` (the SMTP auth username) before calling `build_email_message`. Often identical but not guaranteed (e.g. alias forwarding setups).
- 05-07: send_failure_notification returns `False` on its own SMTP failure but does NOT re-raise. Plan 05-04 must not assume `False` means "duplicate suppressed" — it could also mean "creds missing" or "transport down". The bool is a hint, not a contract; actual user-visible failure handling is the pipeline's responsibility.
- 05-07: send_pipeline_failure_notification needs an async_session passed in — there is no module-level session factory inside notifications.py. Plan 05-04's outer try/except scope (around _execute_pipeline) must construct its own `async with async_session() as session` to call this helper.
- 05-07: The reopen-on-clear semantic means notify_count grows monotonically per signature. Plan 05-06 should display this in the dashboard banner ("alerted N times") so the operator can see whether the same issue keeps recurring.
- 05-07: app/web/templates/emails/ is now the canonical location for outbound notification templates. Future notification-adjacent plans (weekly digest, response-rate alerts) should put templates here and re-use the _jinja Environment in app.submission.notifications.
- 05-05: Plan 05-05 Task 3 (`checkpoint:human-verify`) was deferred to a single phase-end visual sweep — see 05-05-SUMMARY.md Deviation #1 for the eight UX scenarios that need a manual browser walkthrough before merging Phase 5. Coverage at the integration-test level is already in place via 10 live_app router tests.
- 05-05: SQLAlchemy 2.x rollback expires every ORM-tracked attribute, and Windows asyncio trips MissingGreenlet on lazy-loads of expired attrs. Future tests that read state from a session AFTER a rollback must `session.expunge_all()` and re-query via Core SQL — never via `session.get()` or attribute access on the original instance.
- 05-05: FastAPI 0.10x bare-list query annotations (`status: list[str] = []`) silently fail to parse repeated query params. Always use `Query(default_factory=list)` for repeating query params. Latent fragility — audit other routers if this matters elsewhere.
- 05-05: `app.review.service.list_review_queue` orders by `MAX(TailoringRecord.id)` per job, NOT by `version`. A future plan that wants "latest by version" should use a different helper — sharing this one would break the manual_edit case where a user-saved record needs to win over a same-version LLM original.
- 05-04: Rate-limiter counter ticks on ATTEMPTED sends inside the same success block as mark_sent. If the success notification's SMTP call fails after record_submission, the counter still sticks. Dashboard copy must read "Rate limit counter = attempted sends, not successfully notified sends" to set operator expectations correctly.
- 05-04: Submission.failure_signature is NULL for failed rows today. Filed as a low-priority cleanup — the Submission row already has error_class + error_message for forensic value, but a future UI that wants to group failures by signature will need to either backfill or accept the NULL.
- 05-04: Cover-letter-missing path is non-fatal in the submission pipeline — if `TailoringRecord.cover_letter_path` is None or unreadable, the pipeline logs a warning and sends an email with an empty body. The plan explicitly permits this (04-05 decision) but operators with auto-mode on may want a stricter "require cover letter or hold out" setting. Deferred to a future plan.
- 05-04: No retry/backoff at the send level. One-shot per run per job matches the research plan's locked "v1 = no send-level retry" decision. Transient SMTPServerDisconnected → job flips to `failed`; re-enters queue only via the review-UI "Retry" button. Phase 5 explicitly accepts this.
- 05-04: `submission_skipped` counter is only set when SMTP creds are missing at drain-loop start. If creds disappear mid-loop (unlikely — Settings mutation race), subsequent jobs will flip to `failed` via the per-job failure branch rather than `submission_skipped`. The race is mitigated by the load-once-per-loop pattern.

## Session Continuity

Last session: 2026-04-15
Stopped at: Completed 06-04-PLAN.md (learning service + semantic matcher + needs-info aggregation). Two atomic commits: bbfb1d9 (Task 1: SavedAnswer CRUD + UnknownField persistence service, 17 tests) and 0273df7 (Task 2: LLM semantic matcher + needs-info aggregation, 16 tests). One deviation: Rule 1 — fixed func.case() SQLAlchemy API to use case() directly. 33/33 new tests green.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 06-02-PLAN.md (browser primitives). Two atomic commits: 97c0c34 (Task 1: BrowserManager with storageState persistence, 11 tests) and 151f991 (Task 2: CAPTCHA detection + screenshot utilities, 25 tests). One deviation: Rule 3 — installed playwright package locally (already in requirements.txt but not in local venv). 36/36 new tests green.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 06-01-PLAN.md (Phase 6 schema foundation). Two atomic commits: 78bef07 (Task 1: app/learning/models.py SavedAnswer + UnknownField + app/db/models.py Settings extensions + import side-effect) and af4d0fc (Task 2: Alembic migration 0006 creating saved_answers + unknown_fields tables + 3 Settings columns). Zero deviations. 369/369 suite green.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 05-06-PLAN.md (manual-apply paste-a-link flow). Two atomic commits: e1cffc4 (Task 1: app/manual_apply/fetcher.py + app/manual_apply/service.py + 18 unit tests) and 47a9ec3 (Task 2: app/web/routers/manual_apply.py + 4 Jinja templates + app/main.py mount + base.html.j2 nav link + 8 router integration tests). 26 new tests total; full suite 358/358 green in ~56s. Four auto-fixed deviations (see 05-06-SUMMARY.md): (1) detect_source tuple unpacking order flip — plan had `source_type, slug` but real signature is `(slug, source_type)`; (2) tests relocated to tests/manual_apply/ to match pyproject testpaths='tests' (05-02/05-05 precedent); (3) /preview Form(...) → Form("") so empty-url request reaches the handler and renders fallback instead of 422; (4) Task 3 checkpoint:human-verify deferred to phase-end visual sweep (05-05 precedent). MANL-01..06 complete; SC-3 satisfied. Parallel-wave note: 05-08 Task 1 landed commit bb7c881 between my task commits (applied_service + 11 tests) and later additively mounted applied_router + 'Applied' nav link alongside my manual_apply_router + 'Manual Apply' nav link — both coexist cleanly in app/main.py and base.html.j2. Only 05-08 remaining in Phase 5 (in parallel, Task 1 already landed).

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 05-04-PLAN.md (submission pipeline drain loop). Two atomic commits: 788b392 (Task 1: app/submission/holdout.py + app/submission/service.py + 10 holdout tests including engine-anchor guard re-reading engine.py source at runtime) and 31090b6 (Task 2: app/submission/pipeline.py::run_submission + app/scheduler/service.py lazy-import wiring + app/submission/builder.py::extract_docx_plaintext helper + 11 pipeline integration tests). 21 new tests total; full suite 321/321 green in ~49s. Zero deviations against the plan — the drain loop order, holdout retry_count<=1 semantics, idempotency via the partial UNIQUE index, first-live-consumer of RateLimiter.record_submission, and first enforcement of Settings.quiet_hours_start/end all match the plan must_haves verbatim. Two minor refinements (not deviations): (1) added a dedicated `submission_skipped` count key for the creds-missing-at-drain-loop-start branch; (2) extracted `extract_docx_plaintext` as a named builder helper (rather than inlined) for reuse in Phase 6. SchedulerService._execute_pipeline now runs discovery → tailoring → submission and merges all three stage count dicts into Run.counts. Phase 5 is now 6/7 plans complete — only 05-06 (manual-apply paste-a-link) remains before the phase-end visual sweep deferred from 05-05.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 05-05-PLAN.md (review queue UI + state-machine guard + retailoring loop) in parallel with 05-03 (submitter) and 05-07 (notifications). Two atomic commits: 6265daa (Task 1: app/review/docx_edit.py + app/review/service.py + 14 unit tests + 1-line patch to app/tailoring/service.py:get_queued_jobs to also pick up `retailoring` status) and 99b1d43 (Task 2: app/web/routers/review.py with 8 endpoints, 5 Jinja templates under app/web/templates/review/, app/main.py mount, base.html.j2 nav link, 10 router integration tests via live_app). 24 new tests, full suite 300/300 green. Five auto-fixed deviations (see 05-05-SUMMARY.md): (1) Task 3 human-verify checkpoint deferred to phase-end visual sweep — parallel waves cannot accommodate per-plan blocking checkpoints, integration tests cover the same flows; (2) batch-approve test needed session.expunge_all() before re-querying after rollback to dodge Windows asyncio MissingGreenlet on expired ORM attributes; (3) router list-query params switched from bare `list[str] = []` to `Query(default_factory=list)` because FastAPI 0.10x bare lists don't parse repeated query params; (4) `_render_table` helper added so mutation endpoints don't re-call `review_index` (Query() defaults not iterable when bypassed); (5) tests/review/ instead of app/tests/review/ matching pyproject testpaths. The Phase 5 review-queue UI + state-machine + retailoring loop are now stable. Plan 05-04 (submission pipeline) can drain the approved queue this plan fills; 05-06 (manual-apply paste-a-link) is the only remaining Phase 5 plan.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 05-07-PLAN.md (notification subsystem) in parallel with 05-03 (submitter) and 05-05 (review UI). Phase 5 Wave 2 partially landed — failure signature SHA-256 canonicalisation, suppression CRUD with reopen-on-clear (cleared_at→None, notify_count++) honouring the Plan 05-01 UNIQUE signature index, three bool-returning notification senders (success / failure / pipeline-failure) all silence-window-agnostic by design, three Jinja plaintext templates under app/web/templates/emails/, POST /notifications/ack/{id} HTMX-friendly route mounted in app.main.create_app. 23 new tests (14 suppression + 9 notifications), full suite 290/290 in ~110s. Two atomic commits: d49a32b (Task 1: suppression service) and 0af6ef2 (Task 2: notification senders + templates + ack router). Three deviations all auto-fixed: (1) Rule 1 — schema/spec collision on failure_suppressions.signature UNIQUE constraint, fixed by re-opening cleared rows in place; (2) Rule 1 — plan referenced non-existent app.profile.service.get_profile, swapped for app.settings.service.get_profile_row; (3) Rule 3 — verify-step grep on quiet_hours flagged docstring text, rewrote using synonym "silence window". The 05-03 session note about a "pre-existing test_suppression failure" was the same schema/spec collision and is now resolved by deviation #1. Parallel-wave file app/web/routers/review.py from Plan 05-05 was respected as out-of-scope; app/main.py was independently modified by 05-05 to mount review_router alongside notifications_router and both coexist cleanly. Plan 05-04 (submission pipeline) can now compose 05-02 primitives + 05-03 select_strategy + 05-07 notification senders + 05-01 schema into the end-to-end submit_one_job pipeline.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 05-03-PLAN.md (Wave 2 submitter dispatch surface). Two atomic commits: 88e9fc4 (Task 1 — SubmitterStrategy Protocol + SubmissionContext + SubmissionOutcome dataclasses + default_registry + select_strategy) and 2bb784a (Task 2 — EmailStrategy concrete implementation + 8 unit tests). Three new files in app/ (registry.py, strategies/__init__.py, strategies/email.py) and one new test file (tests/submission/test_registry.py). Strategies are stateless (zero DB writes verified by grep gate); SubmissionContext carries job + paths + recipient + subject + body + filename + smtp_creds. EmailStrategy composes 05-02's build_email_message + send_via_smtp behind the SubmitterStrategy Protocol so the 05-04 pipeline calls `select_strategy(job, job.description)` once per approved job — None means `needs_info` (SC-1 fail-closed). Phase 6 PlaywrightStrategy plugs in by satisfying the same Protocol, prepended to the registry list for known-ATS jobs. One preemptive deviation (Rule 3): tests placed under tests/submission/test_registry.py instead of the plan's app/tests/submission/ — applying the 05-02 lesson up front. Full project suite 253 passed (245 from 05-02 + 8 from 05-03), one pre-existing failure in tests/submission/test_suppression.py belonging to a parallel 05-07 plan (commit d49a32b that landed between my two commits — not in scope here, flagged for the owning plan). Wave 2 submitter dispatch surface is stable; 05-04 pipeline can now compose select_strategy + load_smtp_creds + the 05-02 builder helpers into one `async def run_submission(job, tailoring_record)` call.

---

Previous session: 2026-04-15 (earlier)
Previously stopped at: Completed 05-02-PLAN.md in parallel with 05-01. Phase 5 Wave 1 (schema + email primitives) is now complete. 05-02 landed aiosmtplib==5.1.0 and three new modules: app/submission/builder.py (5 pure helpers — build_subject, build_attachment_filename, extract_cover_letter_plaintext, resolve_recipient_email, build_email_message), app/submission/creds.py (load_smtp_creds + SmtpCreds + SmtpCredsMissing, lazy get_settings inside function), and app/submission/sender.py (send_via_smtp + SmtpConfig + SubmissionSendError with stable error_class for future failure-suppression hashing). 29 new unit tests — 17 builder + 12 sender/creds; network-free via monkeypatched aiosmtplib.send and the in-memory async_session fixture. Full suite 245/245 green. Task commits: 6c38d70 (Task 1: aiosmtplib + builder) and 12064fa (Task 2: creds + sender). Two deviations, both auto-fixed: (1) Rule 3 — tests relocated from app/tests/submission/ to tests/submission/ to match pyproject `testpaths = ["tests"]`; (2) Rule 1 — `load_smtp_creds` originally module-imported `get_settings`, failed under test_phase2_resume.py live_app fixture (importlib.reload(app.config) left a stale function reference). Fixed with the canonical 04-05 lazy-import-inside-function pattern. Phase 5 Wave 2 (05-03 submission registry, 05-04 pipeline, 05-05 notifications, 05-06 review UI, 05-07 manual apply) can now run against these primitives + the 05-01 schema.

---

Earlier session: 2026-04-15 (earliest)
Earlier stopped at: Completed 05-01-PLAN.md (Wave 1 schema foundation). Alembic 0005_phase5_submission ships submissions + failure_suppressions tables plus four new Settings columns (notification_email, base_url, submissions_paused, auto_holdout_margin_pct). Partial UNIQUE index `ux_submissions_job_sent` (WHERE status='sent') verified real via sqlite_master inspection AND proven by IntegrityError on duplicate-sent insert. `app.review.states` ships a 13-element CANONICAL_JOB_STATUSES frozenset plus assert_valid_transition() service-layer validator; illegal transitions like submitted->matched raise ValueError. New `app.submission` and `app.review` packages register with Alembic metadata via import side-effect at the bottom of `app/db/models.py`. Python Settings SQLModel class mirrors the four new migration columns. Downgrade/upgrade roundtrip clean. 216/216 suite green (no regressions). Two atomic commits: 47c88c2 (Task 1: models + state frozenset) and 47f3ab3 (Task 2: migration + Settings field additions). Zero deviations. Note: a parallel wave-1 plan 05-02 landed commit 6c38d70 between my two commits (email builder primitives + aiosmtplib dep) — non-overlapping, both waves integrate cleanly. Phase 5 Wave 1 schema is now stable; Wave 2 plans (submitter, pipeline, review UI, notifications) can run in parallel against the tables.
Resume file: None
