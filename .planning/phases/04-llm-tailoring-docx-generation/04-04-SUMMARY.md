---
phase: 04-llm-tailoring-docx-generation
plan: 04
subsystem: docx-generation
tags: [python-docx, mammoth, format-preservation, ats, diff, preview]

# Dependency graph
requires:
  - phase: 02-core-config-credentials
    provides: base resume storage (app/resume/service.py), extract_resume_text section extraction
  - phase: 04-llm-tailoring-docx-generation
    provides: TailoringRecord schema consumer of tailored artifact paths (from 04-01)
provides:
  - app.tailoring.docx_writer.build_tailored_docx (format-preserving resume render)
  - app.tailoring.docx_writer.build_cover_letter_docx (business-letter DOCX)
  - app.tailoring.docx_writer.check_ats_friendly (tables/font audit)
  - app.tailoring.docx_writer.compute_keyword_coverage (jd overlap ratio)
  - app.tailoring.preview.docx_to_html (mammoth-backed preview)
  - app.tailoring.preview.generate_section_diff (base vs tailored model)
  - app.tailoring.preview.format_diff_html (side-by-side HTML fragment)
affects:
  - 04-05 tailoring pipeline (will call build_tailored_docx + build_cover_letter_docx)
  - 04-06 review queue UI (will embed format_diff_html and docx_to_html output)
  - 04-07 end-to-end wiring (ATS checks consumed by review queue warnings)

# Tech tracking
tech-stack:
  added:
    - mammoth==1.12.0 (installed into local .venv; already pinned in requirements.txt by 04-02)
  patterns:
    - "Run-level DOCX replacement via replace_paragraph_text_preserving_format — never paragraph.text setter when runs exist (research Pitfall 1)"
    - "Heading matching = case-insensitive exact + keyword fuzzy fallback (experience/education/skills/summary/objective/projects) to absorb 'Work Experience' vs 'Professional Experience' drift (Pitfall 5)"
    - "Work-experience subsections matched by locked company name; title/dates/company paragraphs never mutated (CONTEXT.md locked-fields rule)"
    - "Diff HTML uses inline styles on Pico.css CSS variables so the fragment renders without a matching stylesheet but still supports theming"

key-files:
  created:
    - app/tailoring/docx_writer.py
    - app/tailoring/preview.py
  modified: []

key-decisions:
  - "Overflow policy for simple sections: when Claude returns more bullets than the base resume slot, extras are DROPPED with a warning log rather than cloning paragraph XML. Adding paragraphs at arbitrary positions breaks bullet-list continuation and inter-paragraph spacing; better to under-render than to corrupt the layout."
  - "Underflow policy: fewer tailored bullets than base paragraphs clears the excess base paragraphs (empty string via run replacement) rather than deleting them. Deletion would re-flow the entire document; clearing keeps spacing stable."
  - "Cover letter font detection reads runs[0].font.name from the FIRST run it finds on the base resume. Falls back to Calibri on any exception. Good enough — mismatch between resume and cover letter only happens when the base resume itself has mixed fonts, which the ATS checker will flag anyway."
  - "check_ats_friendly returns keyword_coverage=None because coverage depends on the job description. Callers merge in compute_keyword_coverage(tailored_text, jd) separately. Keeps the ATS function callable from anywhere without dragging the JD into the signature."
  - "compute_keyword_coverage uses a naive >3-char word-token extraction with no stopword list. Stopwords would be dropped from both sides symmetrically and tailored resumes organically cover common words, so the added complexity buys nothing. Regex allows +, -, / so 'C++', 'CI/CD', 'front-end' count as single tokens."
  - "generate_section_diff appends tailored-only sections at the END (not interleaved) with empty base_text and changed=True. Interleaving would require base-heading position tracking that isn't available; appending is visually clear in the review queue."
  - "format_diff_html emits a <style> prelude scoped to .tailoring-diff-section so <ins>/<del> color themselves without requiring the review-queue template to ship matching CSS. Fragment is fully self-contained."
  - "_replace_experience_subsections uses a fixed 2-line skip after the company header (title + dates) before collecting bullets. Heuristic rather than parsed because python-docx has no semantic notion of 'bullet vs. title'; style-name checking would be too brittle across different resume templates."

patterns-established:
  - "Every public function in app.tailoring.docx_writer logs via structlog at .info on success and .warning on fallback/overflow. The caller never has to wrap in try/except to get traceability."
  - "Mammoth warnings are swallowed into structlog.debug rather than raising or being returned — keeps the preview endpoint totally non-fatal in the HTMX render path."

# Metrics
duration: ~7 min
completed: 2026-04-12
---

# Phase 4 Plan 04: DOCX Writer and Preview Summary

**Format-preserving tailored-resume DOCX writer, cover letter generator, ATS checks, mammoth-backed HTML preview, and side-by-side section diff — the full artifact layer for the tailoring review queue.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-04-12T21:18:43Z
- **Completed:** 2026-04-12T21:25:53Z
- **Tasks:** 2
- **Files modified:** 2 (both created)

## Accomplishments

- `app/tailoring/docx_writer.py` (574 LOC) — `build_tailored_docx`, `build_cover_letter_docx`, `check_ats_friendly`, `compute_keyword_coverage`, plus the `replace_paragraph_text_preserving_format` primitive and private heading/subsection matchers
- `app/tailoring/preview.py` (307 LOC) — `docx_to_html`, `generate_section_diff`, `format_diff_html`
- Run-level formatting preservation verified end-to-end with a synthetic DOCX smoke test: bold/font are intact after replacement, section content gets rewritten, work-experience bullets are swapped while company/title/dates paragraphs stay untouched
- Mammoth conversion and line-level diff rendering verified against the same synthetic doc — `<ins>`/`<del>` markup emits correctly for changed sections, unchanged sections render neutrally
- Full test suite: **175/175 passing** (unchanged from Wave 1)

## Task Commits

Each task was committed atomically:

1. **Task 1: Format-preserving DOCX writer + cover letter + ATS checks** — `73f2fc6` (feat)
2. **Task 2: DOCX-to-HTML preview + section diff** — `09b526c` (feat)

_Plan metadata commit follows this SUMMARY._

## Files Created/Modified

- `app/tailoring/docx_writer.py` — New. 574 lines. Format-preserving DOCX render pipeline, cover letter generator, ATS audit, keyword coverage.
- `app/tailoring/preview.py` — New. 307 lines. Mammoth preview, section diff model, side-by-side HTML fragment formatter.

## Decisions Made

See the `key-decisions` block in the frontmatter — the substantive ones are overflow/underflow semantics for simple sections, the decision to leave `keyword_coverage` decoupled from `check_ats_friendly`, the fixed 2-line skip heuristic for work-experience subsection headers, and the scoped `<style>` prelude in the diff HTML fragment.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed mammoth==1.12.0 into local .venv**

- **Found during:** Task 2 verification (`from app.tailoring.preview import ...`)
- **Issue:** `mammoth` was pinned in `requirements.txt` by 04-02 but never installed into the local test venv. Import failed immediately.
- **Fix:** `pip install mammoth==1.12.0` — installs `mammoth` and its `cobble` dependency.
- **Files modified:** None (requirements.txt already had the pin from 04-02)
- **Commit:** N/A (no source change, environment-only fix)

No other deviations. No files outside the plan's `files_modified` list were touched. `prompts.py` and `engine.py` remain untouched per Wave-2 parallelism rules.

**Total deviations:** 1 auto-fixed (Rule 3 environment blocker)
**Impact on plan:** None — plan executed as written. Task 1's full end-to-end DOCX round-trip and Task 2's mammoth/diff smoke test both produced the expected output on a synthetic resume.

## Issues Encountered

- Mammoth was in `requirements.txt` but not in the venv; handled as Rule 3 blocker and installed inline. Non-blocking for CI (requirements.txt is authoritative) — just a local venv drift from 04-02.

## User Setup Required

None. The DOCX writer and preview are pure-Python library code with no external service configuration.

## Next Phase Readiness

- `build_tailored_docx` is the only entry point 04-05 (pipeline stage) needs to persist tailored resumes to `data/resumes/{job_id}/v{N}.docx`. Signature: `(base_resume_path, tailored_sections_dict, output_path) -> Path`.
- `build_cover_letter_docx` is ready for the cover-letter generation branch of the pipeline. Signature: `(paragraphs_list, output_path, base_resume_path=None) -> Path`.
- `check_ats_friendly` + `compute_keyword_coverage` are ready to be called post-generation by the pipeline and attached to the `TailoringRecord.validation_warnings` JSON blob (schema from 04-01).
- `docx_to_html` and `format_diff_html` are ready for 04-06 (review queue UI) — both return HTML fragments ready for `{{ x | safe }}` embedding.
- **Wave 2 coordination:** 04-03 (prompts + engine) is the parallel sibling. This plan deliberately did NOT touch `prompts.py` or `engine.py`, so a clean merge is expected. The contract between them is the `tailored_sections` dict shape, which both sides pull from the `04-RESEARCH.md` schema section.

---
*Phase: 04-llm-tailoring-docx-generation*
*Completed: 2026-04-12*

## Self-Check: PASSED

- `app/tailoring/docx_writer.py` exists
- `app/tailoring/preview.py` exists
- Commit `73f2fc6` present in git log
- Commit `09b526c` present in git log
