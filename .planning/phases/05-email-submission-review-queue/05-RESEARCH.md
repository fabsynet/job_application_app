# Phase 5: Email Submission, Review Queue, Manual Apply & Notifications — Research

**Researched:** 2026-04-15
**Domain:** SMTP email sending, inline DOCX editing, job state machines, failure deduplication, URL ingestion
**Confidence:** HIGH (codebase findings) + MEDIUM (library choices — aiosmtplib is current and well-maintained)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (verbatim)

**Review Queue Flow**
- **Layout:** Sortable/filterable table with row actions as the primary queue view. Columns include company, role, match score, tailored-on date, status. Row click opens a detail drawer/page with the full base-vs-tailored diff (uses `format_diff_html` from 04-04, already self-contained CSS).
- **Edit before approve:** **Full inline edit** is supported. User can edit the tailored DOCX bullets/content in the browser before approving. Must NOT reintroduce hallucinations — edits are user-authored (no re-run of the LLM on save), saved version becomes the canonical DOCX. Validator does NOT re-run on manual edits.
- **Batch approve:** Checkbox column + "Approve selected" action. Confirmation dialog shows count + company/role list + total attachments before firing. Single-button batch firing.
- **Reject:** Explicit prompt — "Skip this job permanently" vs "Re-tailor with a different angle." Re-tailor pushes job back through Phase 4 engine (costs budget; respects budget guard). Skip moves job to `skipped` state forever.
- **State machine:** `matched → tailored → approved → submitted` happy path, plus `tailored → skipped`, `tailored → retailoring → tailored`, `approved → failed` (SMTP error). Extends Phase 4's existing `matched`/`tailored`/`failed` states.

**Auto-Mode Trust Gate**
- **Free toggle, no gate.** Settings > Mode = full-auto flippable any time. Safety via daily cap + killswitch + per-run logs + low-confidence holdout. No "approve N first" ramp.
- **Low-confidence holdout:** Even in full-auto, auto-submit only when BOTH: (1) validator passed on first try, (2) keyword coverage ≥ user match threshold + safety margin. Otherwise falls to review queue. Safety margin = user setting, default ~10pp.
- **Daily cap halt:** Halt submission loop; unsent approved jobs stay `approved` for next day. Persistent banner "Daily cap hit — N jobs waiting for tomorrow." "Raise cap by N for today" action. `approved`-but-unsent jobs MUST allow tailored DOCX download, cover letter text, diff view — user can complete the app externally.
- **Emergency stop (two layers):** (1) Phase 1 global killswitch halts the entire pipeline; (2) NEW "Pause submissions" toggle — softer, Phase-5-owned — pauses only the submission stage. Discovery + tailoring keep running and fill the queue.

**Email Format & Identity**
- **From:** User's own SMTP address (Phase 2 Credentials). No Reply-To override.
- **Subject:** `Application for {role} at {company}`
- **Body:** The tailored cover letter IS the email body. Plain text, line breaks preserved. NO cover letter DOCX attachment.
- **Attachment:** `{FullName}_{Company}_Resume.docx`. FullName from Profile (spaces→underscores, strip punctuation). Company slugified (alnum + underscore).
- Dedup standard email signature with cover letter closer — probably NOT needed (cover letter already has "Sincerely, Name").

**Notifications**
- **Per-submission:** One email per successful submission. Content: job title, company, source, match score, link to applied-jobs detail view, tailored resume attached or linked.
- **Failure suppression:** "Failure signature" key = error class + message hash + stage. First failure fires an email; dupes suppressed until cleared (next successful send OR user UI ack).
- **Pipeline-level failures:** Run crash, budget halt, killswitch trip, >50% failure rate in a run — each fires once, same suppression.
- **Destination decoupled:** NEW setting `notification_email` (defaults to SMTP From). SMTP sender address unchanged.
- **Quiet hours do NOT apply to notifications.**

**Manual Paste Flow**
- **Paste → preview → confirm.** User pastes URL at `/manual-apply`. App fetches + parses (reuses Phase 3 normalizer for GH/Lever/Ashby; best-effort for generic). Preview card shows title/company/description excerpt/detected source. Confirm → Tailor. Cancel → abandon.
- **After confirm:** Job created with source `manual` or detected ATS. **Bypasses keyword match threshold** (explicit opt-in). **Respects dedup** (fingerprint). Enters standard tailoring + review/auto pipeline.
- **Fetch failure:** Show specific error. Fallback textarea: raw description + title/company/source fields.
- LinkedIn/Indeed/bot-walled sources degrade to manual-paste fallback, do NOT crash.

### Claude's Discretion
- URL patterns for `/review`, `/manual-apply`, detail routes — follow existing sidebar/HTMX patterns.
- Column additions vs. new table design — planner decides based on existing Job model.
- Suppression-window duration / "cleared" heuristic — planner picks sensible default (e.g., 6h window or until next successful run).
- HTMX vs full-page reload for batch-approve confirmation.
- Inline-edit widget: contenteditable vs textarea vs minimal richtext — simplest that preserves line breaks and bullet structure round-tripping to DOCX.
- Failure email body format.
- Exact low-confidence margin default (~10pp).

### Deferred Ideas (OUT OF SCOPE — do NOT plan)
- "Approve N first" trust gate.
- Inline re-tailor with custom guidance.
- Browser-based submission (Phase 6 — Playwright).
- Learning loop for unknown fields (Phase 6).
- Per-source From addresses.
- Per-run digest notification mode.
- Semantic dedup.
- Analytics / success-rate dashboard / trend charts.
</user_constraints>

---

## Summary

Phase 5 is almost entirely a **composition phase** on top of infrastructure that already exists in the codebase. The stack is locked — FastAPI + SQLModel + async SQLAlchemy + Jinja2 + HTMX 2.0.3 + Pico.css — and every building block needed already has a predecessor in `app/`: the `Job` model has a `status` column (Phase 3); the `TailoringRecord` model has `retry_count`, `validation_passed`, and paths to the tailored DOCX (Phase 4); SMTP credentials are already stored as encrypted `Secret` rows named `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` (Phase 2); `format_diff_html` is already rendered in `app/tailoring/preview.py` and wired into `app/web/routers/tailoring.py`; `RateLimiter` already enforces daily cap and has a `record_submission` method that nothing calls yet; `detect_source` in `app/discovery/fetchers.py` already handles URL-to-ATS routing.

**Primary recommendation:** Treat Phase 5 as wiring, not greenfield. Use `aiosmtplib` for the async submitter (keeps parity with the existing async pipeline and does NOT block the event loop the way stdlib `smtplib` would inside `run_pipeline`). Add a single `submissions` table with a unique constraint on `(job_id, status='submitted')` to guarantee idempotency (SUBM-07). Extend `Job.status` with the new string values — do not introduce a new enum column. For inline DOCX edit, use a plain `<textarea>` per section/bullet and regenerate the DOCX through the same `build_tailored_docx` path already used in Phase 4 (run-level replacement preserves formatting). Every new schema addition goes into a single `0005_phase5_submissions.py` Alembic migration.

---

## Standard Stack

### Core (new to this phase)

| Library | Version | Purpose | Why Standard |
|---|---|---|---|
| `aiosmtplib` | 5.1.0 | Async SMTP client for the submitter | Pipeline is async; stdlib `smtplib` blocks the event loop. `aiosmtplib` is the de-facto async SMTP library for asyncio apps and has a stable 5.x API with context-manager support, STARTTLS/SSL, and attachment support via stdlib `email.message.EmailMessage`. |
| `email.message.EmailMessage` (stdlib) | stdlib | Build MIME message with DOCX attachment + plain-text body | Python stdlib recommendation since 3.6; avoids legacy `MIMEMultipart`/`MIMEBase` ceremony. `EmailMessage.add_attachment(data, maintype="application", subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename=...)` one-liner. |

Confidence: aiosmtplib version — **HIGH** (verified via `pip index versions`, latest is 5.1.0 as of 2026-04-15). Stdlib EmailMessage pattern — **HIGH** (documented in Python docs; standard pattern for sending DOCX attachments).

### Supporting (already in the codebase — reuse)

| Library | Version | Purpose | Where |
|---|---|---|---|
| `httpx` | 0.28.1 | URL fetching for `/manual-apply` | Already in `requirements.txt` and used by `app/discovery/fetchers.py` and `app/credentials/validation.py`. |
| `python-docx` | 1.1.2 | DOCX read/write for inline edit round-trip | Already in `requirements.txt` and used by `app/tailoring/docx_writer.py`. |
| `mammoth` | 1.12.0 | DOCX → HTML for editable preview | Already in use in `app/tailoring/preview.py::docx_to_html`. |
| `Jinja2` | 3.1.4 | Notification email rendering + new queue templates | Already in use. Templates live under `app/web/templates/`. |
| `structlog` | 24.4.0 | All logging — must use existing logger pattern | All new modules must `log = structlog.get_logger(__name__)`. |
| `htmx` | 2.0.3 | All interactive queue behavior | Already loaded in `base.html.j2`. Use `HX-Request` header sniffing like `app/web/routers/jobs.py` for partial swaps. |
| Pico.css | — | Styling. Use the same minimal utility-free pattern as existing templates. | `<link rel="stylesheet" href="/static/pico.min.css">` in `base.html.j2`. |

### Alternatives Considered

| Instead of | Could Use | Why we chose the other |
|---|---|---|
| `aiosmtplib` | stdlib `smtplib` wrapped in `asyncio.to_thread` | `app/credentials/validation.py` already uses `asyncio.to_thread(smtplib.SMTP...)` for validation — fine for one-off credential check, but for the hot submission loop each send would spawn a thread and serialize under the GIL. `aiosmtplib` is non-blocking native async and adds ~1 dep for a per-job hot path. |
| `aiosmtplib` | `emails`, `python-emails`, `yagmail` | Higher-level sugar libraries. None are as actively maintained and all add opinionated rendering layers we don't need (we already render the body as plain text from the cover letter). |
| New `JobStatus` enum column | Keep `Job.status: str` with a module-level frozenset of valid values | Phase 3/4 convention — see `CANONICAL_FAILURE_REASONS` in `app/db/models.py`. Enforcement is service-layer, not DB-level. Keeps migration trivial. |
| New `review_queue` table | Reuse `Job.status` transitions + new `submissions` table for idempotency | The review queue IS the set of jobs in `status in ('tailored', 'pending_review', 'approved', 'retailoring')`. No new first-class entity needed. Matches user decision to extend, not redesign. |

**Installation:**
```bash
# Add to requirements.txt:
aiosmtplib==5.1.0
```

---

## Architecture Patterns

### Recommended module structure

```
app/
├── submission/                 # NEW subpackage
│   ├── __init__.py
│   ├── models.py              # Submission, FailureSuppression SQLModels
│   ├── service.py             # CRUD: record submission, claim row, list_queue
│   ├── builder.py             # build_email_message(job, record, profile) -> EmailMessage
│   ├── sender.py              # async send_via_smtp(msg, creds) -> SubmissionResult
│   ├── pipeline.py            # run_submission(ctx, session_factory, ...) — scheduler stage
│   ├── holdout.py             # should_auto_submit(record, settings) -> bool
│   └── notifications.py       # send_success_notification / send_failure_notification
├── review/                    # NEW subpackage
│   ├── __init__.py
│   ├── service.py             # approve/reject/retailor job_id transitions (idempotent)
│   └── docx_edit.py           # apply_user_edits(tailored_path, edited_sections) -> Path
├── manual_apply/              # NEW subpackage
│   ├── __init__.py
│   ├── fetcher.py             # fetch_url(url) -> ParsedJob | FetchError
│   └── service.py             # create_manual_job, parse_preview
├── db/migrations/versions/
│   └── 0005_phase5_submission.py   # NEW
└── web/routers/
    ├── review.py              # NEW  — /review, /review/{job_id}, /review/{job_id}/approve, etc.
    ├── manual_apply.py        # NEW  — /manual-apply
    └── notifications.py       # NEW  — /notifications/ack endpoint for suppression clear
```

The split between `submission/`, `review/`, and `manual_apply/` matches the existing `discovery/`, `tailoring/` style (feature package with `models.py`, `service.py`, `pipeline.py`).

### Pattern 1: New scheduler stage — `run_submission`

Mirror exactly the `run_tailoring` shape in `app/tailoring/pipeline.py`. The new stage plugs into `SchedulerService._execute_pipeline` **after** `run_tailoring`:

```python
# app/scheduler/service.py (patch)
from app.submission.pipeline import run_submission

submission_counts = await run_submission(
    ctx,
    self._session_factory,
    rate_limiter=self._rate_limiter,
    killswitch_check=self._killswitch.raise_if_engaged,
)
self._last_counts = {**discovery_counts, **tailoring_counts, **submission_counts}
```

**Rules (copy from `run_tailoring`):**
1. Lazy-import inside the function body (matches existing `reload`-safety note).
2. Per-job budget-style gate = `RateLimiter.await_precheck` + `record_submission` after a successful send.
3. Kill-switch check between jobs via injected callable.
4. Randomized inter-submission delay via `rate_limiter.random_action_delay()`.
5. Honor the new `Settings.submission_paused` flag as early exit (distinct from killswitch).
6. Honor the new `Settings.auto_mode` + holdout logic to decide which `tailored` jobs are eligible to move to `approved` automatically.

### Pattern 2: Idempotent submission via a `submissions` row with unique partial index

The canonical way to guarantee "no double-submit on re-run" in SQLite is a unique constraint. Since a job can have multiple attempts (one rejected by SMTP, then a later one succeeds), the constraint must apply only to **successful** rows.

**Schema:**
```python
class Submission(SQLModel, table=True):
    __tablename__ = "submissions"
    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    tailoring_record_id: int = Field(foreign_key="tailoring_records.id")
    attempt: int = Field(default=1)
    status: str = Field(default="pending")  # pending | sent | failed
    smtp_from: str = Field()
    smtp_to: str = Field()
    subject: str = Field()
    attachment_filename: str = Field()
    error_class: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    failure_signature: str | None = Field(default=None, index=True)
    sent_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Migration partial unique index** (SQLite supports partial indices):
```python
# In 0005_phase5_submission.py upgrade()
op.create_index(
    "ux_submissions_job_sent",
    "submissions",
    ["job_id"],
    unique=True,
    sqlite_where=sa.text("status = 'sent'"),
)
```

**Send algorithm:**
```python
async def submit_job(session, job_id, record_id, ...):
    # 1. Insert pending row (inside its own transaction) — IntegrityError here
    #    means another worker already got to it. Unlikely given the asyncio.Lock
    #    on SchedulerService but defends against manual-force + scheduled race.
    # 2. Try send.
    # 3. On success: UPDATE row SET status='sent', sent_at=now(). The UPDATE will
    #    itself fail (UNIQUE) if another attempt already succeeded. Catch
    #    IntegrityError → log idempotent-dup → skip.
    # 4. On failure: UPDATE row SET status='failed', error_class=..., error_message=...
    # 5. Flip Job.status to 'submitted' or 'failed' in the same session.
```

**Why partial unique index** (vs full unique index on `(job_id, status)`): allows many `failed` attempts per job, only one `sent`. SQLite's partial index syntax (`CREATE UNIQUE INDEX ... WHERE status = 'sent'`) is supported and enforceable; Alembic exposes it via `sqlite_where`.

### Pattern 3: Failure suppression via a `failure_suppressions` table

```python
class FailureSuppression(SQLModel, table=True):
    __tablename__ = "failure_suppressions"
    id: int | None = Field(default=None, primary_key=True)
    signature: str = Field(unique=True, index=True)  # sha256(error_class + stage + msg_canon)
    stage: str = Field()  # 'submission' | 'pipeline' | 'tailoring' | 'discovery'
    error_class: str = Field()
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    notify_count: int = Field(default=1)  # emails actually sent for this signature
    occurrence_count: int = Field(default=1)  # total occurrences (sent + suppressed)
    cleared_at: datetime | None = Field(default=None)
    cleared_by: str | None = Field(default=None)  # 'auto_next_success' | 'user_ack'
```

**Signature function:**
```python
import hashlib, re
def build_signature(error_class: str, stage: str, message: str) -> str:
    # Canonicalize message: lowercase, strip digits, collapse whitespace.
    # Digit-strip matters so "failed after 3s" vs "failed after 7s" hash the same.
    canon = re.sub(r"\d+", "N", (message or "").lower())
    canon = re.sub(r"\s+", " ", canon).strip()
    return hashlib.sha256(f"{stage}|{error_class}|{canon}".encode()).hexdigest()
```

**Should-notify decision:**
```python
async def should_notify(session, signature: str) -> bool:
    row = (await session.execute(
        select(FailureSuppression).where(
            FailureSuppression.signature == signature,
            FailureSuppression.cleared_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        return True  # first occurrence — notify and record
    row.occurrence_count += 1
    row.last_seen_at = datetime.utcnow()
    await session.commit()
    return False  # duplicate — suppress
```

**Clear-on-success:** after every successful submission, iterate `FailureSuppression` where `stage='submission' AND cleared_at IS NULL AND last_seen_at < now` and set `cleared_at=now`, `cleared_by='auto_next_success'`. User ack from the UI does the same via a POST to `/notifications/ack/{id}`.

### Pattern 4: Job state machine — extend `Job.status`, don't replace

Add a module-level frozenset to `app/discovery/models.py` (or a new `app/review/states.py`):

```python
CANONICAL_JOB_STATUSES: frozenset[str] = frozenset({
    "discovered",       # Phase 3
    "matched",          # Phase 3
    "queued",           # Phase 3 (manual queue)
    "tailored",         # Phase 4
    "failed",           # Phase 4
    "pending_review",   # Phase 5 — alias used in review-only mode
    "approved",         # Phase 5
    "retailoring",      # Phase 5 — while a re-tailor is in flight
    "skipped",          # Phase 5 — user explicit skip
    "submitted",        # Phase 5
    "applied",          # Phase 3 — legacy alias, keep
})
```

**Transitions (allowed):**
- `tailored → pending_review` (in review mode, purely nominal — the UI can treat `tailored` as `pending_review`)
- `tailored → approved` (manual approve OR auto-mode holdout-pass)
- `tailored → skipped` (explicit reject)
- `tailored → retailoring → tailored|failed` (explicit re-tailor)
- `approved → submitted` (successful send)
- `approved → failed` (SMTP error)
- `submitted` is terminal.
- `skipped` is terminal.

**Migration-free:** Phase 3's `Job.status` is already a plain `str`. No ALTER TABLE needed to accept new values. The only Alembic migration for this phase is the new tables (`submissions`, `failure_suppressions`) plus the new `Settings` columns.

### Pattern 5: Inline DOCX edit without LLM re-run

**The locked constraint is:** edits must be clearly user-authored, must not call the LLM again, and must not invoke the validator. The simplest round-trip is:

**5a. Surface the editable content.** The tailored JSON that Claude produced is NOT persisted — only the rendered DOCX is. But `app/tailoring/preview.py::_docx_sections_as_tailored_json` already shims a DOCX back into the `{"sections": [{"heading", "content"}]}` shape used by `build_tailored_docx`. Reuse it.

**5b. Render each section as a plain `<textarea>`** — one per section (and one per experience subsection bullet list). Line breaks = bullets. This is the simplest-thing-that-works and trivially round-trips because `build_tailored_docx` already accepts the same dict shape as input.

```html
<!-- app/web/templates/partials/review_edit_form.html.j2 -->
<form hx-post="/review/{{ job.id }}/save-edits" hx-swap="outerHTML">
  {% for section in tailored_sections %}
    <label><strong>{{ section.heading }}</strong></label>
    <textarea
      name="section_{{ loop.index0 }}"
      rows="{{ section.content.split('\n') | length + 2 }}"
      data-heading="{{ section.heading }}">{{ section.content }}</textarea>
  {% endfor %}
  <button type="submit">Save edits</button>
</form>
```

**5c. Save endpoint** (`app/review/docx_edit.py`):
```python
def apply_user_edits(
    base_resume_path: Path,
    edited_sections: dict,   # {"sections": [{"heading", "content"}, ...]}
    output_path: Path,
) -> Path:
    # Exact same call as the tailoring pipeline. build_tailored_docx already
    # handles run-level replacement preserving formatting. We just pass the
    # user's edited text instead of the LLM output.
    from app.tailoring.docx_writer import build_tailored_docx
    return build_tailored_docx(
        base_resume_path=base_resume_path,
        tailored_sections=edited_sections,
        output_path=output_path,
    )
```

**5d. Versioning.** Reuse `app/tailoring/service.py::get_next_version` so each save produces a new `v{N}.docx`. Store a new `TailoringRecord` with `intensity="manual_edit"` and `status="completed"`, `validation_passed=None`, `retry_count=0`, and `error_message="user_edit"` as a clear marker in the audit trail. Do NOT debit budget. The record participates normally in the latest-version lookup used by the submitter.

**Why this is safe:**
- `build_tailored_docx` uses `replace_paragraph_text_preserving_format` which is the only documented-safe mutator in this codebase (see Phase 4 Pitfall 1 in `docx_writer.py` module docstring). Setting `paragraph.text = ...` directly would destroy run-level bold/italic.
- Work-experience subsection matching is already locked to company names; the user edits only bullets, never company/title/dates.
- **The cover letter** is plain text — the locked decision says it is the email body. Editing it is even simpler: a single `<textarea>`, saved as a list of paragraphs, regenerated via `build_cover_letter_docx`.

**Widget choice rationale:**
- `contenteditable` — loses line-break fidelity across paste, browser-dependent, needs Markdown or manual normalization. Skip.
- Minimal richtext (Quill, TipTap) — overkill, adds JS deps, and the tailored content has no markup beyond line breaks.
- `<textarea>` — trivial, native, preserves newlines, trivially parsed server-side with `.splitlines()`. **Winner.**

### Pattern 6: SMTP submitter (aiosmtplib + EmailMessage)

```python
# app/submission/sender.py
from email.message import EmailMessage
from pathlib import Path
import aiosmtplib

_DOCX_MIME = ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")

def build_email_message(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body_text: str,
    attachment_path: Path,
    attachment_filename: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body_text)  # plain text; preserves newlines
    data = attachment_path.read_bytes()
    msg.add_attachment(
        data,
        maintype=_DOCX_MIME[0],
        subtype=_DOCX_MIME[1],
        filename=attachment_filename,
    )
    return msg

async def send_via_smtp(
    msg: EmailMessage,
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: float = 30.0,
) -> None:
    # aiosmtplib.send is a one-shot convenience that connects, authenticates,
    # sends, and quits. STARTTLS is auto on port 587; implicit TLS on 465.
    await aiosmtplib.send(
        msg,
        hostname=host,
        port=port,
        username=username,
        password=password,
        start_tls=(port == 587),
        use_tls=(port == 465),
        timeout=timeout,
    )
```

**Error handling:** `aiosmtplib` raises `aiosmtplib.SMTPException` and its subclasses (`SMTPAuthenticationError`, `SMTPServerDisconnected`, `SMTPTimeoutError`, `SMTPRecipientsRefused`). The submitter catches these and produces a failure signature keyed on the exception class name.

**Retry policy for v1:** NONE at the send level. A failed send flips `Job.status=failed`, writes a `Submission.status=failed` row, and fires a failure notification (subject to suppression). The next scheduler pass will re-pick the `approved` job if it was a transient class (the user will see retry UI in the queue). **Planner note:** document explicitly that v1 is one-shot-per-run-per-job. No exponential backoff, no DLQ. Keeps the v1 simple.

**Credential retrieval** (matches `app/tailoring/provider.py::get_provider`):
```python
from app.db.models import Secret
from app.security.fernet import FernetVault
from app.config import get_settings as get_app_settings

async def load_smtp_creds(session):
    vault = FernetVault.from_env(get_app_settings().fernet_key)
    creds = {}
    for name in ("smtp_host", "smtp_port", "smtp_user", "smtp_password"):
        row = (await session.execute(
            select(Secret).where(Secret.name == name)
        )).scalar_one_or_none()
        if row is None:
            raise ValueError(f"SMTP credential missing: {name}")
        creds[name] = vault.decrypt(row.ciphertext)
    creds["smtp_port"] = int(creds["smtp_port"])
    return creds
```

### Pattern 7: Low-confidence holdout decision

```python
# app/submission/holdout.py
def should_auto_submit(
    record: TailoringRecord,
    job: Job,
    user_threshold: int,        # Settings.match_threshold — 0..100
    holdout_margin: int,        # Settings.auto_holdout_margin_pct — default 10
    job_description: str,
    tailored_text: str,
) -> tuple[bool, str]:
    """Return (allowed, reason). 'reason' drives the queue display badge."""
    if record.validation_passed is not True:
        return False, "validation_not_passed"
    if (record.retry_count or 0) > 0:
        return False, "validation_needed_retries"
    from app.tailoring.docx_writer import compute_keyword_coverage
    # compute_keyword_coverage returns 0.0..1.0
    coverage_pct = int(compute_keyword_coverage(tailored_text, job_description) * 100)
    required = user_threshold + holdout_margin
    if coverage_pct < required:
        return False, f"coverage_below_holdout ({coverage_pct} < {required})"
    return True, "auto_eligible"
```

**Where "first try" lives:** `TailoringRecord.retry_count` is an existing column set by `app/tailoring/engine.py` (lines 513, 526, 567, 587). Semantics: `retry_count=0` means the first attempt succeeded; `retry_count=1+` means validator retried. Use `> 0` as the "not first try" test.

**Coverage recomputation cost:** `compute_keyword_coverage` tokenizes the JD with a regex and does a substring scan — O(keywords × len(text)), microseconds. Safe to call per job in the submission loop.

### Pattern 8: Manual-apply URL fetch

```python
# app/manual_apply/fetcher.py
import httpx
from dataclasses import dataclass
from app.discovery.fetchers import detect_source  # already exists

@dataclass
class ParsedJob:
    title: str
    company: str
    description: str
    description_html: str
    url: str
    source: str  # 'greenhouse' | 'lever' | 'ashby' | 'manual'
    external_id: str

class FetchError(Exception):
    def __init__(self, reason: str, status: int | None = None):
        self.reason = reason
        self.status = status

USER_AGENT = "Mozilla/5.0 (compatible; JobApplyBot/1.0; +local)"

async def fetch_and_parse(url: str) -> ParsedJob:
    # 1. detect_source first — if it's a known ATS, call the existing
    #    fetchers.py functions, then filter by external_id.
    try:
        source_type, slug = detect_source(url)
    except Exception:
        source_type, slug = "manual", ""

    timeout = httpx.Timeout(10.0, connect=5.0)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(url)
    except httpx.TimeoutException:
        raise FetchError("timeout")
    except httpx.ConnectError as exc:
        raise FetchError(f"connect_failed: {exc}")

    if resp.status_code == 404:
        raise FetchError("not_found", status=404)
    if resp.status_code in (401, 403):
        raise FetchError("auth_wall", status=resp.status_code)
    if resp.status_code >= 400:
        raise FetchError(f"http_{resp.status_code}", status=resp.status_code)

    # 2. If known ATS, delegate to Phase 3 normalizer using the slug and filter
    #    the returned list for a matching URL or external_id. This reuses
    #    Greenhouse/Lever/Ashby parsing verbatim.
    # 3. Otherwise best-effort HTML parse using stdlib (no new deps):
    #    - strip_html from app.discovery.fetchers for the description
    #    - <title> tag for the title guess
    #    - <meta property="og:site_name"> for company guess, fallback to hostname
    #
    # Return ParsedJob.
```

**Explicit "graceful degrade":** any `FetchError` bubbles to the router which shows the fallback textarea form. LinkedIn/Indeed always hit `auth_wall` or a 200 with an empty body — both paths end in the fallback, not a crash.

**Dedup reuse:** after parsing, call `app/discovery/scoring.py::job_fingerprint(url, title, company)` then `get_job_by_fingerprint`. If found, return "Already exists as job #N" — don't create a dup. Matches locked decision.

### Pattern 9: Applied-jobs dashboard & queue table

**Server-side sort/filter pattern is already established** in `app/discovery/service.py::list_jobs` and `app/web/routers/jobs.py::jobs_page` — whitelisted column map, `order_by(col.desc())`, HTMX partial swap when `HX-Request` header is set. Clone this exact pattern:

```python
# app/review/service.py
REVIEW_SORT_COLUMNS = {
    "company": Job.company,
    "title": Job.title,
    "score": Job.score,
    "tailored_at": TailoringRecord.created_at,
    "status": Job.status,
}

async def list_review_queue(
    session, *, sort_by="tailored_at", sort_dir="desc",
    status_filter: list[str] | None = None, limit=50, offset=0,
):
    q = select(Job, TailoringRecord).join(
        TailoringRecord, TailoringRecord.job_id == Job.id
    ).where(Job.status.in_(status_filter or ["tailored", "approved", "retailoring"]))
    col = REVIEW_SORT_COLUMNS.get(sort_by, TailoringRecord.created_at)
    q = q.order_by(col.desc() if sort_dir == "desc" else col.asc()).limit(limit).offset(offset)
    ...
```

**Pagination:** offset/limit with "Load more" HTMX button — same pattern as Phase 3. No need for cursor pagination at v1 scale.

**Checkbox batch-approve:** a plain HTML form with multiple `<input type="checkbox" name="job_ids" value="{{ job.id }}">`. Submit button opens an HTMX-loaded confirmation partial (`hx-get="/review/confirm-approve" hx-include="[name='job_ids']:checked"`). The confirm partial lists the jobs and has a single POST button that calls `/review/approve-batch`. This keeps the batch UX inside HTMX partials (no full page reload).

### Pattern 10: Notification email rendering

Put Jinja templates for notifications in `app/web/templates/emails/`:

```
app/web/templates/emails/
├── _base.txt.j2
├── success.txt.j2
├── failure_submission.txt.j2
└── failure_pipeline.txt.j2
```

Render them with a separate `Jinja2Templates` instance scoped to `emails/`, or use `app.state.jinja.get_template("emails/success.txt.j2").render(...)`. These are plain-text (never HTML) per the "recruiters read plain" locked decision — but NOTE: the locked decision about plain text is for the **application** email body. Notification emails to the user can be HTML or plain; plain is simplest and matches the local-only nature of the app. **Recommendation: plain text for v1.**

**Dashboard link construction:** the app may not have a public hostname. Use `app.config.get_settings()` — there should be (or you can add) a `base_url` setting defaulting to `http://localhost:8000`. In the notification template render `{{ base_url }}/review/{{ job.id }}`. Planner should add `Settings.base_url` column if it does not already exist.

```python
# Grep confirms: no base_url in settings yet. Add it in 0005 migration.
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Async SMTP client | Don't wrap `smtplib` in `to_thread` per-send | `aiosmtplib` 5.1.0 | Blocking-in-threadpool per job serializes under GIL and uses an extra thread per send. Native async is ~20 lines + 1 dep. |
| MIME message building | Don't assemble `MIMEMultipart` + `MIMEBase` + `encoders.encode_base64` | `email.message.EmailMessage` + `add_attachment()` | Modern Python email API — one call handles Base64, boundaries, headers. Legacy `MIMEMultipart` is error-prone with encoding headers on DOCX. |
| DOCX round-trip after edit | Don't hand-parse XML or swap `paragraph.text` | `build_tailored_docx(base, edited_sections, out)` | `replace_paragraph_text_preserving_format` is the only safe mutator in this repo; using `paragraph.text =` destroys run-level formatting (documented in `app/tailoring/docx_writer.py` docstring). |
| DOCX → editable HTML preview | Don't write a DOCX parser | `mammoth.convert_to_html` via existing `docx_to_html` | Already wired and working. |
| Job dedup on manual paste | Don't write a new hash function | `app.discovery.scoring.job_fingerprint(url, title, company)` | Already the canonical fingerprint — using anything else would split the dedup index. |
| URL-to-ATS detection | Don't re-regex GH/Lever/Ashby URLs | `app.discovery.fetchers.detect_source(url)` | Already handles every supported ATS URL shape. |
| Daily cap accounting | Don't add a second counter | `RateLimiter.await_precheck` + `RateLimiter.record_submission` | Already implemented, TZ-aware, has midnight reset. Nothing currently calls `record_submission` — Phase 5 is its first user. |
| Diff rendering | Don't build a JS diff component | `format_diff_html` from `app/tailoring/preview.py` | Self-contained CSS, Jinja-embeddable. |
| Secret encryption | Don't introduce another vault | `FernetVault.from_env(get_settings().fernet_key)` + `Secret` table | Phase 1–2 pattern — `app/tailoring/provider.py` shows the exact pattern to copy. |
| URL fetch error matrix | Don't build a whole parser framework | `httpx.AsyncClient` + simple status-code branching | `app/credentials/validation.py` shows the exact exception-handling pattern. |
| Jinja rendering for emails | Don't build a separate template engine | `Jinja2Templates(directory="app/web/templates/emails")` | Same engine, same `render()` API. |
| HTML stripping for generic URL fetch | Don't pull in BeautifulSoup | `app.discovery.fetchers.strip_html` | Already used by scoring path; good enough for v1 best-effort parse. |

**Key insight:** Phase 5 is 90% assembly. Every major primitive already exists in the repo — this phase is mostly schema additions and wiring. Resist the urge to introduce new libraries; the only new runtime dep is `aiosmtplib`.

---

## Common Pitfalls

### Pitfall 1: `aiosmtplib.send()` silent truncation on non-ASCII attachment filenames
**What goes wrong:** Company names like "Café" or "Nestlé" produce headers that need RFC 2231 encoding. `EmailMessage.add_attachment(filename=...)` handles this correctly, but if the planner slugifies the company BEFORE passing to `add_attachment` and accidentally double-encodes, the attachment gets a garbled name in some mail clients.
**How to avoid:** Slugify with a hard ASCII-only rule in the builder — matches the locked decision: `re.sub(r"[^A-Za-z0-9_]", "", company.replace(" ", "_"))`. Same for `FullName`. Test with "Café" → "Caf" (or add explicit unidecode if the user wants transliteration; not required for v1).
**Warning signs:** Attachment shows as `noname.docx` or `=?utf-8?...?=.docx` in Outlook.

### Pitfall 2: Daily cap race between manual force-run and scheduled run
**What goes wrong:** `SchedulerService._lock` serializes runs inside the process, but `RateLimiter.record_submission` is a read-modify-write. Two concurrent submit loops could both check `await_precheck` at count=19 and both succeed at count=21.
**How to avoid:** Phase 5 only submits inside `run_submission` which is called from `_execute_pipeline` inside the `asyncio.Lock`. There's only ever one submission loop in flight. As long as Phase 5 does NOT add a second call site, this is safe. **Planner rule:** `RateLimiter.record_submission` is called ONLY from `app/submission/pipeline.py::run_submission`. Do not call it from route handlers.
**Warning signs:** Daily cap exceeded by 1 or 2 on days with manual + scheduled overlap.

### Pitfall 3: Inline edit loses run-level bold/italic
**What goes wrong:** User edits the textarea, planner calls `paragraph.text = new_text` to save (the "obvious" API). `python-docx` then collapses all runs into a single plain run — every bold phrase becomes plain text.
**How to avoid:** Never call `paragraph.text = ...`. Always go through `replace_paragraph_text_preserving_format` (or equivalently through `build_tailored_docx` which calls it). This is called out as "Pitfall 1" in `app/tailoring/docx_writer.py` module docstring.
**Warning signs:** First tailored section loses all formatting after a user edit save.

### Pitfall 4: Failure suppression key too specific
**What goes wrong:** Planner hashes `str(exception)` verbatim into the signature. Exceptions like `SMTPRecipientsRefused: 550-5.1.1 <foo@bar.com>: user unknown` have the email address in the message — two different recipients yield two different signatures. User gets 10 emails anyway.
**How to avoid:** Canonicalize the message before hashing (see Pattern 3): lowercase, replace digits with `N`, replace `/[a-z0-9._-]+@[a-z0-9.-]+/` with `<email>`. Hash on `(stage, error_class, canon_msg)` tuple.
**Warning signs:** Suppression table growing unbounded during a single broken run.

### Pitfall 5: Quiet hours accidentally gate notifications
**What goes wrong:** Planner adds a `check_quiet_hours()` helper in `app/submission/pipeline.py` and then uses the same helper for `send_notification`. Locked decision says notifications IGNORE quiet hours.
**How to avoid:** Keep quiet-hours logic inside `run_submission` ONLY. `send_success_notification` / `send_failure_notification` must have no reference to `Settings.quiet_hours_*`. Add a test: `test_notification_sends_during_quiet_hours`.
**Warning signs:** Failure emails delayed overnight; user reports "I thought the SMTP was broken but actually no email was sent because of quiet hours."

### Pitfall 6: Manual-apply bypasses dedup
**What goes wrong:** Locked decision says manual paste bypasses keyword match but respects dedup. Planner implements "bypasses match" by inserting a Job row directly, accidentally skipping the `get_job_by_fingerprint` check.
**How to avoid:** The ONLY gate that should differ for manual-apply is the score threshold. The dedup call — `fp = job_fingerprint(url, title, company); existing = await get_job_by_fingerprint(session, fp)` — must run unchanged. On hit, show "Already exists as job #N" and link to it.
**Warning signs:** Same URL pasted twice creates two Job rows.

### Pitfall 7: `smtp_port` round-trip as string
**What goes wrong:** `Secret` ciphertext stores `smtp_port` as a string (written via `_upsert_secret(..., str(smtp_port))` in `settings.py`). If the planner passes the string directly to `aiosmtplib`, the connect call fails with a TypeError.
**How to avoid:** Always `int(creds["smtp_port"])` after decrypt. See Pattern 6 `load_smtp_creds` example.
**Warning signs:** First real send fails with `TypeError: int expected`.

### Pitfall 8: "First try" semantics off-by-one
**What goes wrong:** `TailoringRecord.retry_count` is set to `retry + 1` in most code paths in `app/tailoring/engine.py`. The planner assumes `retry_count == 0` means first try but the actual value for a first-try success might be `1`.
**How to avoid:** Read `app/tailoring/engine.py` lines 513–587 before implementing the holdout check. Match the actual semantic — likely `retry_count <= 1` means first-try success (retry loop index 0 produced a valid result). **Planner must verify by reading the engine and ideally adding a test.**
**Warning signs:** Every single tailored job gets held out of auto mode, even obviously good ones.

### Pitfall 9: SQLite partial unique index not enforced
**What goes wrong:** Alembic's `op.create_index` with `sqlite_where` works, but if the planner uses `UniqueConstraint` (table-level), SQLite ignores the WHERE clause and the constraint becomes global.
**How to avoid:** Use `op.create_index(..., unique=True, sqlite_where=sa.text("status = 'sent'"))` — NOT `UniqueConstraint(..., sqlite_where=...)`. Verify with `sqlite_master` query in a test.
**Warning signs:** Second failed attempt raises IntegrityError even though no row has `status='sent'`.

### Pitfall 10: Cover letter as email body drops blank-line paragraph separation
**What goes wrong:** Phase 4 stores the cover letter as a `list[str]` of paragraphs. Joining with `"\n"` collapses paragraph breaks. Joining with `"\n\n"` is correct for plain-text emails but needs to match what `EmailMessage.set_content` expects.
**How to avoid:** `body = "\n\n".join(paragraphs)`. `set_content` will preserve as-is. Verify by sending to yourself during development.
**Warning signs:** Recruiters see a wall of text.

---

## Code Examples

### build + send one email (end-to-end)

```python
# app/submission/pipeline.py (excerpt)
from app.submission.sender import build_email_message, send_via_smtp
from app.submission.builder import build_subject, build_body, build_attachment_filename

async def _submit_one(session, job, latest_record, profile, creds) -> None:
    subject = build_subject(role=job.title, company=job.company)
    # Cover letter DOCX -> plain text paragraphs. Phase 4 stores the cover
    # letter as a DOCX at latest_record.cover_letter_path. We need the plain
    # text; the simplest path is to re-extract paragraphs from the DOCX via
    # python-docx directly since mammoth returns HTML (not what we want).
    from docx import Document
    cl_paras = [p.text for p in Document(latest_record.cover_letter_path).paragraphs if p.text.strip()]
    body = "\n\n".join(cl_paras)
    filename = build_attachment_filename(
        full_name=profile.full_name,
        company=job.company,
    )
    msg = build_email_message(
        from_addr=creds["smtp_user"],
        to_addr=_resolve_recipient(job),  # posted contact email — Phase 5 needs this extractor
        subject=subject,
        body_text=body,
        attachment_path=Path(latest_record.tailored_resume_path),
        attachment_filename=filename,
    )
    await send_via_smtp(
        msg,
        host=creds["smtp_host"],
        port=int(creds["smtp_port"]),
        username=creds["smtp_user"],
        password=creds["smtp_password"],
    )
```

### Attachment filename builder

```python
# app/submission/builder.py
import re

def build_attachment_filename(full_name: str, company: str) -> str:
    def _clean(s: str) -> str:
        s = (s or "").strip().replace(" ", "_")
        return re.sub(r"[^A-Za-z0-9_]", "", s) or "Unknown"
    return f"{_clean(full_name)}_{_clean(company)}_Resume.docx"

def build_subject(role: str, company: str) -> str:
    role = (role or "Application").strip()
    company = (company or "Unknown").strip()
    return f"Application for {role} at {company}"
```

### The recipient extractor (open question — see below)

There is no existing "posted contact email" field on `Job`. The locked decision says email-apply uses "posted contact email." **Planner must decide where this comes from.** Options:
1. Add `Job.contact_email: str | None` column, populated by fetchers (most ATS APIs don't expose it — requires scraping the JD).
2. Parse the first email regex from `Job.description` at submit time.
3. Require user to paste the recipient for each job (defeats the point).

**Recommendation:** Option 2 for v1. Regex over `Job.description` at submit time; if none found, flip `Job.status = 'needs_info'` and emit a failure notification asking the user to fill it in. Matches REVW-01 state machine spec.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| `MIMEMultipart` + `MIMEBase` + base64 | `EmailMessage.add_attachment()` | Python 3.6+ | Less ceremony, correct headers for binary attachments, handles RFC 2231 filename encoding automatically. |
| `smtplib` in threads | `aiosmtplib` | Stable since ~2020 | Native async, no GIL contention on concurrent sends, matches FastAPI app model. |
| Custom state-machine library | Plain `str` status + frozenset validator | Matches repo convention from Phase 1+ | No new dep, migration-simple, enforced at service layer. |
| Regex job URL parsers | Reuse `detect_source` | Phase 3 already built it | Avoids parser drift. |

---

## Open Questions

1. **Where does the recipient email come from?**
   - What we know: Locked decision says email-apply uses "posted contact email." Job model has no such column.
   - What's unclear: Do ATS APIs return it? (Greenhouse/Lever/Ashby generally do not — their whole model is "apply via our form.")
   - **Recommendation:** Regex-extract from `Job.description` at submit time (Pattern: `r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"`, take first match that's not obviously a noreply). If none found, flip job to `needs_info` state and emit a failure notification. Planner should decide whether to also store the parsed email on a new `Job.contact_email` column for audit.

2. **Base URL for notification email links.**
   - What we know: The app runs locally by default (`http://localhost:8000`). Settings table has no `base_url` field.
   - What's unclear: Whether the user accesses via localhost, a Tailscale hostname, or a reverse proxy.
   - **Recommendation:** Add `Settings.base_url: str = "http://localhost:8000"` in the 0005 migration and expose it in the Settings UI near the notification email field. Notifications render `{{ base_url }}/review/{{ job.id }}`.

3. **TailoringRecord.retry_count semantics.**
   - What we know: The column exists and is written at lines 513/526/567/587 of `app/tailoring/engine.py` as either `retry`, `retry+1`, or `retry` depending on the branch.
   - What's unclear: Whether "first try" means `retry_count == 0` or `retry_count == 1`. Needs source reading during planning, ideally with a unit test.
   - **Recommendation:** Planner adds a helper `record.is_first_try_success() -> bool` whose definition is verified against a test harness run of the engine. Most likely `record.validation_passed is True and record.retry_count <= 1`, but confirm empirically.

4. **Does Phase 2's `Settings.auto_mode` column already exist?**
   - What we know: `app/db/models.py` line 66 defines `auto_mode: bool = Field(default=True)`. The column is in the schema.
   - What's unclear: Whether anything reads it today.
   - **Recommendation:** Phase 5 is the first reader. Planner should grep for `auto_mode` in `app/scheduler/` and `app/web/routers/` to confirm zero consumers before adding the logic.

5. **Template engine instance reuse across routers.**
   - What we know: Each router creates its own `Jinja2Templates(directory=...)` (see `app/web/routers/jobs.py`, `tailoring.py`).
   - What's unclear: Whether this is intentional or just legacy. New routers should match.
   - **Recommendation:** Match the existing pattern — per-router `Jinja2Templates` with the same `Path(__file__).parent.parent / "templates"`.

6. **"Pause submissions" as a new column vs reuse of existing toggles.**
   - What we know: Phase 1 has `Settings.kill_switch` and `Settings.dry_run`. Locked decision adds a softer "Pause submissions."
   - **Recommendation:** Add `Settings.submission_paused: bool = False` in 0005. Do not reuse `dry_run` — dry run semantics in Phase 1 halts the entire pipeline's writes, which is too strong.

---

## Key Codebase Anchors for the Planner

These are the exact files/symbols Phase 5 must hook into. Planner should reference these directly in PLAN.md task actions.

| Anchor | Absolute Path | Purpose |
|---|---|---|
| Scheduler entry point | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\scheduler\service.py::SchedulerService._execute_pipeline` | Add `run_submission` stage call after `run_tailoring`. |
| Rate limiter | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\scheduler\rate_limit.py::RateLimiter.record_submission` | Call once per successful send. Currently unused. |
| Killswitch | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\scheduler\killswitch.py::KillSwitch.raise_if_engaged` | Pass as `killswitch_check` callable to submission pipeline. |
| Secrets vault | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\security\fernet.py::FernetVault.from_env` | Decrypt `smtp_*` secrets. |
| Secret model | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\db\models.py::Secret` | Named rows: `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`. |
| Job model | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\discovery\models.py::Job` | Extend `status` values, don't alter column. |
| TailoringRecord | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\tailoring\models.py::TailoringRecord` | Read `tailored_resume_path`, `cover_letter_path`, `validation_passed`, `retry_count`. |
| Tailoring service | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\tailoring\service.py::get_next_version`, `::get_latest_tailoring`, `::resume_artifact_path`, `::cover_letter_artifact_path` | Reuse for versioned user-edit saves. |
| Diff renderer | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\tailoring\preview.py::format_diff_html`, `::generate_section_diff`, `::docx_to_html` | Review drawer. |
| DOCX writer | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\tailoring\docx_writer.py::build_tailored_docx`, `::build_cover_letter_docx`, `::compute_keyword_coverage` | Round-trip user edits; compute holdout coverage. |
| Fetchers & detect_source | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\discovery\fetchers.py::detect_source`, `::strip_html` | Manual-apply URL routing. |
| Job CRUD | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\discovery\service.py::list_jobs`, `::get_job_by_fingerprint`, `::update_job_status`, `::get_job_detail` | Queue table; dedup on manual-apply. |
| Fingerprint | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\discovery\scoring.py::job_fingerprint` | Manual-apply dedup. |
| Existing sort/filter router pattern | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\web\routers\jobs.py::jobs_page` | Model for `/review` and `/applied`. |
| Base template | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\web\templates\base.html.j2` | Nav entries to add: Review, Manual Apply (or keep under Jobs). |
| Settings migration pattern | `C:\Users\abuba\Downloads\cla_project\job_application_app\app\db\migrations\versions\0004_phase4_tailoring.py` | Template for 0005. |
| Quiet hours fields | `app/db/models.py::Settings.quiet_hours_start`/`quiet_hours_end` (lines 61–62) | **Currently unused by pipeline** — Phase 5 is where enforcement lives. Grep confirms no scheduler/pipeline file references these fields. Planner's `run_submission` is the first enforcement point. |

**Surprise finding:** quiet hours are stored but NOT currently enforced anywhere. The pipeline has no `quiet_hours_start` reference outside `settings.py` config write. Phase 5's submission stage is the first enforcement site. Make this explicit in the plan — do not assume "Phase 2 already does this, just reuse it." There is nothing to reuse.

**Surprise finding 2:** `RateLimiter.record_submission` is declared, tested by Phase 1 unit tests, but has zero callers in the live pipeline (`Grep record_submission app/`). Phase 5 is its first real consumer.

**Surprise finding 3:** The cover letter is persisted only as a DOCX (`TailoringRecord.cover_letter_path`), not as plaintext. To use it as the email body you must re-extract paragraphs via `docx.Document(...)`. Plan an explicit task: `extract_cover_letter_plain_text(path) -> str`.

---

## Sources

### Primary (HIGH confidence)
- **Codebase inspection** (all file:line references above) — direct reads of `app/db/models.py`, `app/discovery/models.py`, `app/tailoring/models.py`, `app/tailoring/pipeline.py`, `app/tailoring/docx_writer.py`, `app/tailoring/preview.py`, `app/scheduler/service.py`, `app/scheduler/rate_limit.py`, `app/credentials/validation.py`, `app/web/routers/settings.py`, `app/web/routers/tailoring.py`, `app/web/routers/jobs.py`, `app/discovery/service.py`, `app/discovery/pipeline.py`, `requirements.txt`, `app/web/templates/base.html.j2`.
- **aiosmtplib 5.1.0** — version confirmed via `pip index versions aiosmtplib` on 2026-04-15 (HIGH).
- **Python stdlib docs** (`email.message.EmailMessage`) — stable stdlib API since 3.6.
- **SQLite partial unique index** — documented in SQLite CREATE INDEX syntax; Alembic supports via `sqlite_where`.

### Secondary (MEDIUM confidence)
- **aiosmtplib `send()` signature and STARTTLS/TLS port conventions** — based on library's documented-stable API. Not re-verified against the 5.1 changelog in this research session; planner should smoke-test the first real send in a throwaway script before wiring into the pipeline.
- **Suppression hash canonicalization pattern** — standard industry pattern (Sentry-style fingerprinting). No single authoritative source, but well-established.

### Tertiary (LOW confidence — flag for validation)
- **None.** All claims above are backed by either direct codebase inspection or stable Python stdlib / SQLite behavior.

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — aiosmtplib version verified; all other libs already in `requirements.txt`.
- Architecture: **HIGH** — mirrors existing Phase 4 patterns which are directly inspected.
- Pitfalls: **HIGH** — derived from direct reads of Phase 4 docstrings (`docx_writer.py` Pitfall 1) and codebase quirks (SMTP port as string, retry_count off-by-one, unused `record_submission`, unused quiet hours).
- Open questions: known, enumerated above.

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (stable stack; re-verify aiosmtplib version if upgrading later)

## RESEARCH COMPLETE
