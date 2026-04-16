---
phase: 06-playwright-browser-submission-learning-loop
plan: 02
subsystem: playwright-browser-primitives
tags: [playwright, browser, captcha, screenshots, async]
requires:
  - "Phase 1 foundation (data_dir convention)"
provides:
  - "BrowserManager with storageState persistence"
  - "CAPTCHA/2FA detection (6 types)"
  - "Screenshot capture and cleanup utilities"
affects:
  - "06-03 (PlaywrightStrategy depends on BrowserManager)"
  - "06-04 through 06-06 (ATS fillers use browser + captcha + screenshots)"
  - "06-07 (learning loop reads screenshot paths)"
tech-stack:
  added: []
  patterns:
    - "Async context manager for browser lifecycle"
    - "Lazy initialization with cached internal state"
    - "Selector-based blocking element detection with priority ordering"
key-files:
  created:
    - app/playwright_submit/__init__.py
    - app/playwright_submit/browser.py
    - app/playwright_submit/captcha.py
    - app/playwright_submit/screenshots.py
    - tests/playwright_submit/__init__.py
    - tests/playwright_submit/test_browser.py
    - tests/playwright_submit/test_captcha.py
    - tests/playwright_submit/test_screenshots.py
  modified: []
key-decisions:
  - id: "browser-lazy-init"
    decision: "BrowserManager lazily starts Playwright on first get_context() call"
    rationale: "Avoids browser startup cost when manager is constructed but not used"
  - id: "captcha-priority-order"
    decision: "CAPTCHA detection checks specific providers before generic selectors"
    rationale: "Prevents generic [class*=captcha] from masking specific reCAPTCHA/hCaptcha detection"
  - id: "screenshot-relative-paths"
    decision: "Screenshot functions return paths relative to data_dir"
    rationale: "Portable across environments; stored in DB without absolute path coupling"
duration: "~3 min"
completed: "2026-04-15"
---

# Phase 6 Plan 02: Browser Primitives Summary

**Playwright browser lifecycle, CAPTCHA detection, and screenshot utilities for all ATS form fillers.**

## What Was Built

### BrowserManager (`app/playwright_submit/browser.py`)
- Lazily starts Playwright + Chromium with configurable `headless` mode
- Loads `storageState.json` on context creation if file exists (session persistence)
- `save_state()` persists cookies/localStorage after submissions
- Default timeouts: 30s action, 60s navigation
- Async context manager support (`async with BrowserManager() as mgr`)
- Idempotent `close()` with error swallowing for clean teardown

### CAPTCHA Detection (`app/playwright_submit/captcha.py`)
- `detect_blocking_element(page)` checks 6 blocking types in priority order:
  1. reCAPTCHA (iframe + div selectors)
  2. hCaptcha (iframe + div selectors)
  3. Cloudflare challenge (iframe + #challenge-running)
  4. Generic CAPTCHA (class/id containing "captcha")
  5. 2FA (OTP input, verification code, two-factor class)
  6. Login redirect (URL contains /login, /signin, /sso)

### Screenshot Utilities (`app/playwright_submit/screenshots.py`)
- `screenshot_dir(data_dir, job_id)` creates and returns `screenshots/{job_id}/`
- `capture_step_screenshot(page, data_dir, job_id, step)` saves `step_{N}.png`
- `capture_error_screenshot(page, data_dir, job_id)` saves `error.png`
- `cleanup_old_screenshots(data_dir, retention_days, exempt_job_ids)` removes old dirs by mtime

## Task Commits

| Task | Name | Commit | Tests |
|------|------|--------|-------|
| 1 | BrowserManager with storageState persistence | 97c0c34 | 11 |
| 2 | CAPTCHA detection + screenshot utilities | 151f991 | 25 |

**Total: 36 tests, all passing**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed playwright package locally**
- **Found during:** Task 1
- **Issue:** `playwright` not installed in local dev environment (only in Docker image)
- **Fix:** `pip install playwright`
- **No commit needed** (runtime dependency, already in requirements.txt)

## Decisions Made

1. **Lazy browser initialization** - BrowserManager only starts Playwright on first `get_context()` call, avoiding unnecessary browser startup
2. **Priority-ordered CAPTCHA detection** - Specific providers (reCAPTCHA, hCaptcha) checked before generic `[class*=captcha]` to avoid false masking
3. **Relative screenshot paths** - All capture functions return paths relative to `data_dir` for portability

## Next Phase Readiness

All Wave 1 browser primitives are ready. Wave 2 plans (06-03 PlaywrightStrategy, 06-04+ ATS fillers) can now import:
- `BrowserManager` for browser lifecycle
- `detect_blocking_element` for CAPTCHA/2FA pause logic
- `capture_step_screenshot` / `capture_error_screenshot` for debugging artifacts

## Self-Check: PASSED
