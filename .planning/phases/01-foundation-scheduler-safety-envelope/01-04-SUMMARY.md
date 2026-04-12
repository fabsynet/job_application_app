---
phase: 01-foundation-scheduler-safety-envelope
plan: 04
subsystem: web-ui
tags: [fastapi, htmx, jinja2, pico-css, starlette, dashboard, secrets, fernet, rate-limit]

# Dependency graph
requires:
  - phase: 01-03
    provides: "SchedulerService.run_pipeline / next_run_iso / pause / cancel_current_run, KillSwitch.engage/release/is_engaged, RateLimiter (live-mutable), app.state.{scheduler,killswitch,vault,rate_limiter}, Run/Settings/Secret models, FernetVault.encrypt auto-registering with scrubber"
provides:
  - "GET / live dashboard — colored status pill, humanised countdown, last run outcome, 50 most recent runs, one-click kill-switch and dry-run toggles"
  - "GET /fragments/status (HTMX 5s poll) and GET /fragments/next-run (HTMX 15s poll), both paused when document.hidden"
  - "POST /runs/trigger — fire-and-forget manual run via asyncio.create_task(svc.run_pipeline)"
  - "POST /toggles/kill-switch and POST /toggles/dry-run — HTMX partial-swap forms that hit KillSwitch.engage/release + Settings.dry_run"
  - "GET /runs (50 most recent) + GET /runs?offset=N rows-only partial for show-more + GET /runs/{id} detail with counts JSON"
  - "GET /settings + POST /settings/secrets (FernetVault.encrypt → upsert Secret) + DELETE /settings/secrets/{name} + POST /settings/limits (validates + live-mutates app.state.rate_limiter)"
  - "Jinja2 templates directory under app/web/templates, static assets under app/web/static (Pico.css v2 83KB bundled locally, app.css overrides)"
  - "app/web/deps.py — FastAPI dependency providers with lazy async_session import for test-reload safety"
affects: [01-05, Phase 2, Phase 5-manual-paste, all future UI work]

# Tech tracking
tech-stack:
  added:
    - "Jinja2 templates active under app/web/templates"
    - "HTMX 2.0.3 via unpkg CDN in base template"
    - "Pico.css v2.x (~83KB) bundled locally at app/web/static/pico.min.css"
    - "FastAPI StaticFiles mount at /static"
  patterns:
    - "HTMX fragments served from the same routers as full pages"
    - "Server-side humanize_seconds helper — no client-side JS timers"
    - "HTMX polling with [document.hidden === false] guard"
    - "HTMX show-more: offset>0 returns rows-only partial, tbody hx-swap=beforeend"

key-files:
  created:
    - "app/web/deps.py"
    - "app/web/routers/dashboard.py"
    - "app/web/routers/toggles.py"
    - "app/web/routers/runs.py"
    - "app/web/routers/settings.py"
    - "app/web/templates/base.html.j2"
    - "app/web/templates/dashboard.html.j2"
    - "app/web/templates/runs_list.html.j2"
    - "app/web/templates/run_detail.html.j2"
    - "app/web/templates/settings.html.j2"
    - "app/web/templates/partials/status_pill.html.j2"
    - "app/web/templates/partials/next_run.html.j2"
    - "app/web/templates/partials/toggles.html.j2"
    - "app/web/templates/partials/runs_rows.html.j2"
    - "app/web/templates/partials/secrets_list.html.j2"
    - "app/web/static/pico.min.css"
    - "app/web/static/app.css"
    - "tests/integration/test_dashboard_routes.py"
    - "tests/integration/test_toggles_routes.py"
    - "tests/integration/test_settings_routes.py"
  modified:
    - "app/main.py"

key-decisions:
  - "Pico.css classless served static — no Tailwind, no build step, single 83KB file"
  - "HTMX fragment routes share the same template/context builder as the full page for consistency"
  - "POST /settings/limits updates the live RateLimiter in-place so changes take effect without restart"
  - "humanize_seconds runs server-side; the client never computes time"
  - "get_session dependency imports async_session lazily so integration tests that reload app.db.base get the freshly bound engine"
  - "Starlette 1.0 TemplateResponse(request, name, ctx) positional signature used throughout — passing request inside ctx dict breaks Jinja's LRU cache (unhashable type: dict)"
  - "Secrets route calls vault.encrypt which auto-registers plaintext with SecretRegistry BEFORE DB commit — log scrubber is armed before the row is persisted"
  - "Known secret names exposed as a <select>; custom names still allowed and rendered in a separate section"
  - "/settings/limits validates the exact same ranges as RateLimiter.__init__ to keep DB state startable"
  - "runs show-more uses hx-swap='outerHTML' on the load-more row rather than beforeend on tbody so the button replaces itself"

patterns-established:
  - "Pattern: HTMX polling with document.hidden guard — hx-trigger='every 5s [document.hidden === false]'"
  - "Pattern: rows-only partial template returned for infinite-scroll offset>0, full page template otherwise"
  - "Pattern: fire-and-forget manual trigger via asyncio.create_task hand-off so HTTP response returns fast"
  - "Pattern: secret CRUD goes through FernetVault.encrypt so scrubber registration happens at the same point as write"
  - "Pattern: lazy-import DB session inside dependency generator to survive test-level module reloads"

# Metrics
duration: ~45 min
completed: 2026-04-11
---

# Phase 1 Plan 04: Dashboard, Toggles, Runs, Settings Summary

**Live HTMX status dashboard with one-click kill-switch and dry-run, /runs history with show-more, /settings form for Fernet-encrypted secrets and live rate-limit tuning — 18 new integration tests, 68/68 suite green**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-04-11 (post 01-03 completion)
- **Completed:** 2026-04-11
- **Tasks:** 3
- **Files created:** 20 (4 routers, 1 deps, 10 templates, 2 static, 3 tests)
- **Files modified:** 1 (app/main.py)

## Accomplishments

- Landing page at `/` shows colored status pill, countdown to next run, last run counts, recent runs table, and big Kill switch + Dry run + Force run now buttons — all CONTEXT.md "one click away from home" requirements met.
- HTMX polling refreshes the status pill every 5 seconds and the next-run countdown every 15 seconds, pausing automatically when the browser tab is hidden (`[document.hidden === false]` trigger filter).
- `POST /toggles/kill-switch` verified end-to-end to cancel an in-flight stub pipeline: test stubs `svc._execute_stub` with a long loop that checkpoints `ks.raise_if_engaged()`, fires a manual run, POSTs the toggle, and asserts the resulting Run row has `status='failed'` + `failure_reason='killed'`.
- `/runs` renders the 50 most recent runs; `/runs?offset=N` returns only `<tr>` rows for HTMX show-more; `/runs/{id}` shows JSON-pretty-printed counts.
- `/settings` form POSTs plaintext through `FernetVault.encrypt` which auto-registers the plaintext with the `SecretRegistry` log scrubber singleton; DB stores only ciphertext, a round-trip decrypt test confirms fidelity.
- `/settings/limits` validates the same bounds as `RateLimiter.__init__` and mutates `app.state.rate_limiter.{daily_cap,delay_min,delay_max,tz}` in-place so the next `run_pipeline` call picks up the new values without a restart.
- Prominent `FERNET_KEY` rotation warning banner on `/settings` per CONTEXT.md "no rotation tool — just re-enter" decision.

## Task Commits

1. **Task 1: Dashboard page + HTMX polling + Pico.css + force-run** — `45d0f10` (feat)
2. **Task 2: Toggle routes + runs list/detail + integration tests** — `67dbb0f` (feat)
3. **Task 3: Settings page with secrets CRUD and rate-limit config** — `a0171d2` (feat)

Plan metadata commit follows this summary.

## Files Created/Modified

### Routers (app/web/routers/)
- `dashboard.py` — GET /, /fragments/status, /fragments/next-run, POST /runs/trigger; `_humanize_seconds` helper; shared `_common_ctx` builder.
- `toggles.py` — POST /toggles/kill-switch (engage/release via KillSwitch primitive), POST /toggles/dry-run.
- `runs.py` — GET /runs (full or rows-partial), GET /runs/{id} with JSON-pretty counts.
- `settings.py` — GET /settings, POST/DELETE /settings/secrets, POST /settings/limits with live rate-limiter mutation.

### Dependencies
- `app/web/deps.py` — `get_session`, `get_scheduler`, `get_killswitch`, `get_vault`, `get_rate_limiter`. Lazy `async_session` import for test isolation.

### Templates (app/web/templates/)
- `base.html.j2` — HTML skeleton with nav, Pico.css + app.css + HTMX 2.0.3 script tag.
- `dashboard.html.j2` — full status card; polls fragments via hx-trigger; extends base.
- `runs_list.html.j2` — 50 most recent runs table, includes rows partial.
- `run_detail.html.j2` — single-run page with counts JSON in `<pre>`.
- `settings.html.j2` — rate-limit form + secrets form + rotation warning banner.
- `partials/status_pill.html.j2` — colored pill with killswitch/dry-run/running states.
- `partials/next_run.html.j2` — `Next run in Xm Ys` or `No scheduled run`.
- `partials/toggles.html.j2` — kill/dry/force-run buttons.
- `partials/runs_rows.html.j2` — rows-only for show-more; includes load-more row.
- `partials/secrets_list.html.j2` — checklist of known secrets + custom entries.

### Static (app/web/static/)
- `pico.min.css` — Pico.css v2 bundled (~83KB, downloaded from unpkg).
- `app.css` — small overrides for status pill colors, kill-switch button, dry-run badge, warning banner.

### Tests (tests/integration/)
- `test_dashboard_routes.py` — 7 tests: render, status/next-run fragments, empty runs, 404 detail, force-run creates Run row, run detail renders counts + DRY badge.
- `test_toggles_routes.py` — 3 tests: kill-switch engage/release round-trip with DB check, dry-run toggle, kill-switch cancels in-flight run (end-to-end HTTP → killswitch → Run row).
- `test_settings_routes.py` — 8 tests: render + rotation warning, encrypt+scrub round-trip, upsert replaces value, delete, save_limits live-updates RateLimiter + persists, invalid range rejection, invalid cap rejection, bad timezone rejection.

### Modified
- `app/main.py` — added StaticFiles mount at `/static`, imports for dashboard/toggles/runs/settings routers, registration in `create_app()`.

## Decisions Made

1. **Pico.css classless, bundled local.** No Tailwind, no build step. Single 83KB file committed to `app/web/static/pico.min.css`. `app.css` adds only colored pill styles and a warning banner — everything else is classless defaults.

2. **Shared context builder for fragments and full pages.** `_common_ctx` in dashboard router produces the same dict for `/` and `/fragments/*` so the polled fragment can never drift from the initial page render.

3. **Server-side humanize_seconds.** No client-side JS timer — HTMX pulls a pre-formatted `Next run in 47m 12s` string every 15 seconds. Keeps the browser deterministic and avoids a second source of truth.

4. **Live RateLimiter mutation on `/settings/limits`.** After persisting to the Settings row, the route writes the new values directly to `app.state.rate_limiter.{daily_cap,delay_min,delay_max,tz}`. No restart required, no APScheduler reconfiguration needed — the next `run_pipeline` call reads the new bounds. Validated in `test_save_limits_updates_live_rate_limiter`.

5. **Starlette 1.0 TemplateResponse signature.** `TemplateResponse(request, name, ctx)` positional form used throughout — the legacy `TemplateResponse(name, {"request": request, ...})` kwarg form triggers `TypeError: unhashable type: 'dict'` in Jinja's LRU cache on Starlette 1.0 because the whole context dict becomes part of the cache key. Discovered on first test run of Task 2.

6. **Lazy async_session import in `get_session` dependency.** Integration tests reload `app.db.base` to rebind the engine to a `tmp_path` DATA_DIR. The dependency now imports `async_session` at call time (inside the generator body) rather than at module load time — otherwise the router holds a stale session factory from whichever test ran first, and HTTP writes land in a different SQLite file than the test's read session.

7. **Secret upsert path goes through vault.encrypt.** The encrypt call auto-registers the plaintext with the scrubber BEFORE producing the ciphertext. Order matters: any accidental log line between here and the DB commit is already safe by the time we emit it.

8. **Known secret names exposed as `<select>`.** `KNOWN_SECRET_NAMES = [anthropic_api_key, smtp_host, smtp_port, smtp_user, smtp_password]`. Custom names still accepted and rendered in a separate "custom" section of the checklist.

9. **Runs show-more uses outerHTML swap on a load-more row.** The last row of `runs_rows.html.j2` is a `<tr id="runs-load-more">` containing a Show more button. `hx-swap="outerHTML"` replaces this row with the next 50 rows (including a new load-more at the bottom) — cleaner than `hx-swap="beforeend"` on the tbody because the button self-manages its own lifecycle.

10. **`/settings/limits` validation mirrors `RateLimiter.__init__`.** Same ranges (daily_cap ≥ 0, delay_min > 0, delay_max > delay_min, delay_max ≤ 600, valid IANA tz). Keeps the DB state startable — a value that the form accepts is guaranteed to construct a RateLimiter on next boot.

## Deviations from Plan

Only one meaningful deviation, all others were forward-compatible tightening:

### Auto-fixed Issues

**1. [Rule 1 - Bug] Starlette 1.0 TemplateResponse signature mismatch**
- **Found during:** Task 2 (first `pytest` of dashboard routes)
- **Issue:** Plan-prescribed `templates.TemplateResponse("name.html.j2", {"request": request, ...})` raised `TypeError: unhashable type: 'dict'` from Jinja's LRU cache because Starlette 1.0 made `request` a positional argument and uses `(loader_weakref, name, context)` as the cache key — a context that contains a dict fails to hash.
- **Fix:** Changed all router calls to `TemplateResponse(request, "name.html.j2", {...})` and removed `"request": request` entries from every context dict.
- **Files modified:** app/web/routers/dashboard.py, toggles.py, runs.py, settings.py
- **Verification:** 10/10 dashboard+toggles tests pass; 8/8 settings tests pass.
- **Committed in:** 67dbb0f (Task 2) — signature fix landed with the rest of Task 2 because the tests that exposed it were in Task 2.

**2. [Rule 3 - Blocking] `get_session` dependency captured stale async_session after test reload**
- **Found during:** Task 2 (test_kill_switch_toggle_engage_release failed initially — HTTP write invisible to test read)
- **Issue:** `app/web/deps.py` imported `async_session` at module load time. Integration test fixtures reload `app.db.base` to rebind the engine to a `tmp_path` DATA_DIR, but the `deps` module's captured reference still pointed at the previous test's engine. Result: HTTP handler wrote to engine A, test read from engine B, assertion failed.
- **Fix:** Moved `from app.db.base import async_session` inside the `get_session` async generator body so each request resolves the name from the currently-loaded module.
- **Files modified:** app/web/deps.py
- **Verification:** All 18 new integration tests pass; full 68-test suite green.
- **Committed in:** 67dbb0f (Task 2)

**3. [Rule 2 - Missing Critical] Timezone validation on `/settings/limits`**
- **Found during:** Task 3 implementation
- **Issue:** Plan said "validates daily_cap and delay range"; it did not explicitly require timezone validation. But saving an invalid tz string would crash `RateLimiter` construction at next boot, bricking the app.
- **Fix:** Added `ZoneInfo(timezone)` construction inside a try/except that converts `ZoneInfoNotFoundError` into HTTP 400. Also added a test case (`test_save_limits_rejects_bad_timezone`).
- **Files modified:** app/web/routers/settings.py, tests/integration/test_settings_routes.py
- **Verification:** `test_save_limits_rejects_bad_timezone` passes; valid IANA tz still accepted.
- **Committed in:** a0171d2 (Task 3)

---

**Total deviations:** 3 auto-fixed (1 bug, 1 blocking, 1 missing critical)
**Impact on plan:** All three necessary for correctness. No scope creep. The Starlette signature fix and the `get_session` lazy import are test-infra robustness items that will pay dividends in every future plan that touches routers.

## Issues Encountered

- **Starlette 1.0 changed TemplateResponse signature** (see deviation 1). Not documented in the plan — first time we've touched Jinja in this project.
- **Test isolation: `async_session` captured at import time** (see deviation 2). Added to Blockers/Concerns for 01-03 is now fully addressed by the lazy-import fix: future router tests that reload `app.db.base` won't hit this again.
- **LF→CRLF warnings on Windows.** Harmless; Git's autocrlf translating line endings on write. All commits succeeded.

## User Setup Required

None — all static assets bundled, HTMX from unpkg CDN (LAN-bound deployment still works because the dashboard is the only thing that needs HTMX, and the `<script src>` resolves at browser load time from whatever WAN the operator has). Fernet key and Settings row already provisioned by earlier plans.

## Next Phase Readiness

**Ready for plan 01-05 (remaining Wave 2/Wave 3 items):**
- Plan 01-05 can now assume `/settings` exists as the remediation surface for any `FERNET_KEY` rotation banner it wants to add.
- The `_common_ctx` dashboard builder has a TODO-comment hook (`# Guard: if wizard not complete, plan 01-05 installs a redirect middleware`) for the wizard redirect.
- All Phase 1 routers are wired; any additional endpoints (wizard, import/export, health details) slot in alongside existing ones.

**Ready for Phase 2+:**
- Phase 2 (Discovery) can add stage counters to `Run.counts` and they will render automatically on `/` and `/runs/{id}` with zero template changes — the dashboard reads whatever keys exist in the dict.
- Phase 5 (manual-paste) has a working `/runs` history page to graft onto.

**Blockers/concerns for STATE.md:**
- HTMX is loaded from `unpkg.com/htmx.org@2.0.3` via CDN. CONTEXT.md prefers LAN-bound deployment; if the operator is fully offline, HTMX will fail to load and the dashboard will render but not poll. Consider bundling htmx.min.js locally in a later cleanup plan (trivial: 47 KB file, same pattern as pico.min.css). Non-blocking because the pages still render server-side.
- Pico.css warning banner lives in the template, but there is no "boot-time decrypt-failed" detection yet. Plan 01-05 should add a middleware or lifespan check that flips a banner flag when `register_all_secrets_with_scrubber` returns fewer secrets than the DB has rows.
- `/runs/trigger` is POST without CSRF protection. LAN-bound deployment per CONTEXT.md ("no auth in v1") makes this acceptable; revisit if the app ever gets pushed to a wider network.

## Self-Check: PASSED
- All 20 created files verified present on disk.
- All 3 task commits verified in git log (`45d0f10`, `67dbb0f`, `a0171d2`).
- Full test suite: 68 passed in 9.17s (50 prior + 18 new).
- Success criteria all met: dashboard renders + polls, kill-switch hits `KillSwitch.engage`, dry-run updates `Settings.dry_run`, /runs shows 50 most recent, /settings saves via FernetVault + registers plaintext.

---
*Phase: 01-foundation-scheduler-safety-envelope*
*Completed: 2026-04-11*
