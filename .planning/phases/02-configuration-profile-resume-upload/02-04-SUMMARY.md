---
phase: 02-configuration-profile-resume-upload
plan: 04
subsystem: credentials
tags: [fernet, anthropic, smtp, httpx, encryption, validation]

# Dependency graph
requires:
  - phase: 02-01
    provides: sidebar shell, Secret model, FernetVault, settings router
provides:
  - Anthropic API key validation via /v1/models endpoint
  - SMTP credential validation via smtplib login
  - Encrypted credential storage with Configured/Not set status display
  - Credentials settings section with inline validation feedback
affects: [04-llm-tailoring, 05-email-submission]

# Tech tracking
tech-stack:
  added: []
  patterns: [save-first-validate-second, async-thread-pool-smtp]

key-files:
  created:
    - app/credentials/__init__.py
    - app/credentials/validation.py
    - app/web/templates/partials/settings_credentials.html.j2
  modified:
    - app/web/routers/settings.py

key-decisions:
  - "Save-first-validate-second: credentials are Fernet-encrypted and persisted before validation runs, so network failures never prevent storage"
  - "Validation result shown as flash alongside save confirmation (e.g., 'Saved. API key is valid' or 'Saved. Connection failed: ...')"
  - "Credentials section never pre-fills inputs or shows masked values -- always empty fields with Configured/Not set status"
  - "SMTP validation runs synchronously via asyncio.to_thread to avoid blocking event loop"

patterns-established:
  - "save-first-validate-second: encrypt+persist credential, then validate, flash combined result"
  - "_upsert_secret helper: DRY pattern for Secret row upsert used by credential routes"
  - "_render_credentials helper: centralizes status computation for credentials partial"

# Metrics
duration: 3min
completed: 2026-04-12
---

# Phase 2 Plan 04: Credentials Section Summary

**Fernet-encrypted Anthropic API key + SMTP credential storage with async inline validation and Configured/Not set status indicators**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-12T04:16:37Z
- **Completed:** 2026-04-12T04:19:44Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Async validation for Anthropic API key (httpx GET /v1/models) and SMTP credentials (smtplib via thread pool)
- Credentials section in settings sidebar with Configured/Not set status, inline save+validation flash
- All credentials encrypted via FernetVault before persistence; never revealed after save

## Task Commits

Each task was committed atomically:

1. **Task 1: Credential validation service** - `8e2d2d9` (feat)
2. **Task 2: Credentials section UI + routes** - `3c0ded7` (feat)

## Files Created/Modified
- `app/credentials/__init__.py` - Package init
- `app/credentials/validation.py` - validate_anthropic_key + validate_smtp_credentials async functions
- `app/web/templates/partials/settings_credentials.html.j2` - Credentials form with status indicators
- `app/web/routers/settings.py` - Added credentials GET/POST routes + _upsert_secret/_render_credentials helpers

## Decisions Made
- Save-first-validate-second pattern: credentials persisted encrypted before async validation, so network failure never blocks storage
- Credentials inputs always empty (no pre-fill, no masking) -- status shown as "Configured" or "Not set"
- SMTP validation uses asyncio.to_thread for blocking smtplib calls
- Broad exception catch around validation returns "Saved but validation encountered an error" -- user sees save confirmation regardless

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Anthropic API key storage ready for Phase 4 LLM tailoring (decrypt via vault, use key)
- SMTP credential storage ready for Phase 5 email submission
- All 87 existing tests pass unchanged

## Self-Check: PASSED

---
*Phase: 02-configuration-profile-resume-upload*
*Completed: 2026-04-12*
