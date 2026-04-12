---
phase: 02-configuration-profile-resume-upload
plan: 02
subsystem: configuration
tags: [profile, resume, docx, upload, drag-and-drop, htmx, crud]

dependency_graph:
  requires: [02-01]
  provides: [profile-crud, resume-upload, docx-extraction, resume-preview]
  affects: [02-05, 03-xx, 04-xx]

tech_stack:
  added: []
  patterns: [singleton-get-or-create, file-upload-multipart, docx-text-extraction, drag-and-drop-js]

file_tracking:
  key_files:
    created:
      - app/resume/__init__.py
      - app/resume/service.py
      - app/web/templates/partials/settings_profile.html.j2
      - app/web/templates/partials/settings_resume.html.j2
    modified:
      - app/settings/service.py
      - app/web/routers/settings.py

decisions:
  - id: D-0202-01
    summary: "Profile fields normalise empty strings to None; phone strips non-digits"
  - id: D-0202-02
    summary: "Resume stored as single file base_resume.docx, replaced on re-upload"
  - id: D-0202-03
    summary: "DOCX sections split on Heading styles; full_text capped at 500 lines"
  - id: D-0202-04
    summary: "Dedicated GET routes for profile/resume declared before generic catch-all for correct FastAPI routing"

metrics:
  duration: "~8 min"
  completed: "2026-04-12"
---

# Phase 2 Plan 2: Profile & Resume Upload Summary

**One-liner:** Profile form with 10 fields across 3 collapsible groups + DOCX resume upload with drag-and-drop and structured text preview

## What Was Built

### Profile Section
- Three collapsible `<details>` groups: Contact (name, email, phone, address), Work Details (authorization dropdown, salary, experience), Links (LinkedIn, GitHub, portfolio)
- All fields optional per user decision -- saving blank form succeeds
- Light validation: email must contain "@" if provided; phone digits stripped
- Profile singleton (id=1) with get-or-create pattern matching Settings
- HTMX POST returns updated partial with success flash

### Resume Upload Section
- File picker with `.docx` accept filter and drag-and-drop zone
- Vanilla JS (~15 lines) handles dragover/dragleave/drop events
- `hx-encoding="multipart/form-data"` on form (HTMX pitfall from research)
- File saved to `{DATA_DIR}/resumes/base_resume.docx` (host volume mount)
- Settings row updated with `resume_filename` and `resume_uploaded_at`
- python-docx extraction groups paragraphs by Heading styles into sections
- Scrollable preview div (max-height 400px) renders headings as bold labels
- Non-.docx uploads rejected with error flash
- Re-upload replaces existing file (no versioning)

## Task Commits

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 | Profile section -- form + CRUD | aced31e | app/settings/service.py, settings_profile.html.j2 |
| 2 | Resume upload -- file storage + DOCX extraction + preview | da204d3 | app/resume/service.py, settings_resume.html.j2, app/resume/__init__.py |

## Decisions Made

1. **D-0202-01:** Profile fields normalise empty strings to None for clean DB storage; phone field has non-digit characters stripped automatically
2. **D-0202-02:** Resume stored as single file `base_resume.docx` -- re-upload overwrites (no versioning needed for v1)
3. **D-0202-03:** DOCX text extraction splits on Heading styles for structured preview; full_text capped at 500 lines to prevent enormous previews
4. **D-0202-04:** Dedicated GET routes for profile and resume sections declared before the generic `{section_name}` catch-all to ensure correct FastAPI route matching

## Deviations from Plan

None -- plan executed exactly as written.

## Verification

- [x] Profile form renders with three collapsible groups
- [x] Profile saves all fields, persists across reloads
- [x] All profile fields optional -- blank save succeeds
- [x] Resume upload via file picker works
- [x] Drag-and-drop JS snippet included in template
- [x] DOCX text extracted and shown as structured preview
- [x] Resume file stored at data/resumes/base_resume.docx
- [x] Settings row updated with resume_filename and resume_uploaded_at
- [x] Non-DOCX rejected with error flash
- [x] All 87 existing tests pass

## Next Phase Readiness

- Profile data and resume file are ready for the submission pipeline (Phase 3+)
- Resume text extraction provides raw material for LLM tailoring (Phase 4)
- No blockers for remaining Phase 2 plans

## Self-Check: PASSED
