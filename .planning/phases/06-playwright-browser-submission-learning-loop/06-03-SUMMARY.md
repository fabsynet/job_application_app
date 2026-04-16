---
phase: "06"
plan: "03"
subsystem: playwright-form-filling
tags: [playwright, form-filler, heuristics, ats, greenhouse, lever, ashby]
depends_on:
  requires: ["06-01"]
  provides: ["Form filler engine with label heuristics", "ATS-specific fillers for Greenhouse/Lever/Ashby", "Generic filler with progressive detection"]
  affects: ["06-04", "06-05", "06-06"]
tech-stack:
  added: []
  patterns: ["Label heuristic matching", "Strategy pattern for ATS fillers", "Progressive form detection"]
key-files:
  created:
    - app/playwright_submit/form_filler.py
    - app/playwright_submit/fillers/__init__.py
    - app/playwright_submit/fillers/base.py
    - app/playwright_submit/fillers/greenhouse.py
    - app/playwright_submit/fillers/lever.py
    - app/playwright_submit/fillers/ashby.py
    - app/playwright_submit/fillers/generic.py
    - tests/playwright_submit/test_form_filler.py
    - tests/playwright_submit/test_fillers.py
  modified: []
decisions:
  - id: "06-03-01"
    description: "Added BaseFiller ABC to define filler interface contract"
    rationale: "Clean abstraction for ATS-specific fillers with consistent navigate/scan/fill/submit/detect API"
metrics:
  duration: "~12 min"
  completed: "2026-04-15"
---

# Phase 6 Plan 03: Form Filler + ATS-Specific Fillers Summary

Label-based heuristic engine mapping 15+ form field patterns to profile data, with Greenhouse/Lever/Ashby-specific fillers and generic progressive detection fallback.

## What Was Built

### Task 1: Base Form Filler with Label Heuristic Engine
- **LABEL_HEURISTICS**: Priority-ordered list of (regex, profile_field, input_method) tuples covering first/last/full name, email, phone, LinkedIn, GitHub, portfolio, resume/CV upload, cover letter upload, work authorization (select_or_fill), salary, years of experience, and location fields
- **match_field_to_profile**: Case-insensitive regex matching, first-match-wins priority
- **get_profile_value**: Resolves profile fields with first_name/last_name splitting from full_name
- **KnownField/UnknownFieldInfo**: Dataclasses for classified fields with locator references
- **classify_fields**: Scans visible form elements, extracts labels (label-for, ancestor label, aria-label, placeholder, name), partitions into known/unknown
- **fill_known_fields**: Fills text, uploads files (auto-detect resume vs cover letter), handles select_or_fill with fallback
- **try_select_with_fallback**: Exact option match, then case-insensitive substring search
- 60 tests covering all heuristics, priority ordering, name splitting, classification, filling

### Task 2: ATS-Specific Fillers
- **select_filler**: Routes by job_source string (exact) or URL pattern to appropriate filler
- **GreenhouseFiller**: boards.greenhouse.io, iframe handling, GDPR consent auto-check, #app URL anchor
- **LeverFiller**: jobs.lever.co, /apply URL suffix, single-page form
- **AshbyFiller**: jobs.ashbyhq.com, /application URL suffix, multi-step form navigation (up to 10 steps)
- **GenericFiller**: Progressive detection — form with file input > aria-label match > largest form
- **BaseFiller ABC**: Abstract base with get_form_url, navigate_to_form, scan_all_pages, fill_and_submit, detect_success
- 31 tests covering routing, URL construction, iframe fallback, GDPR, progressive detection, multi-step scan

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Base form filler with label heuristic engine | f0f4cf4 | form_filler.py, test_form_filler.py |
| 2 | ATS-specific fillers | ad7019d | fillers/__init__.py, base.py, greenhouse.py, lever.py, ashby.py, generic.py, test_fillers.py |

## Deviations from Plan

### Auto-added

**1. [Rule 2 - Missing Critical] Added BaseFiller ABC**
- **Found during:** Task 2
- **Issue:** Plan didn't explicitly mention a base class, but all fillers share the same interface
- **Fix:** Created `fillers/base.py` with abstract methods defining the filler contract
- **Files:** app/playwright_submit/fillers/base.py

**2. [Rule 1 - Bug] Fixed work_authorization regex**
- **Found during:** Task 1 test run
- **Issue:** Regex `\bauthori[sz]ed?\b` didn't match "Authorization" (different suffix)
- **Fix:** Extended to `\bauthori[sz](?:ed?|ation)\b`
- **Files:** app/playwright_submit/form_filler.py

## Verification

- 91 new tests (60 + 31), all passing
- 127 total playwright_submit tests passing (including 36 from 06-02)
- All heuristics verified with explicit test cases
- Priority ordering verified (first_name before name, resume is upload not text)

## Next Phase Readiness

All form filling infrastructure ready for 06-04 (submission orchestrator) which will wire fillers into the pipeline, and 06-05/06-06 which will handle unknown field resolution and learning loop.

## Self-Check: PASSED
