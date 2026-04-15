"""Round-trip a tailored DOCX through user edits (no LLM, no validator).

Phase 5 plan 05-05 Task 1, Part A. The review queue lets the user inline-edit
each tailored section in a textarea before approving. On save we reconstruct
the ``{sections: [{heading, content}]}`` shape that
:func:`app.tailoring.docx_writer.build_tailored_docx` already accepts and
write a fresh versioned DOCX — no LLM call, no validator re-run.

Phase 4 does **not** persist the tailored JSON, only the rendered DOCX at
``TailoringRecord.tailored_resume_path``. To give the user something to edit
we walk that DOCX with python-docx, grouping non-heading paragraphs under
each heading paragraph (style name starting with ``Heading``).

The extractor flattens any work-experience subsections into the section's
``content`` list — Phase 4's writer treats a flat ``content`` list as
bullets inside the section regardless, so the round-trip stays stable
even when the original LLM output had nested ``subsections``.

The writer path (:func:`apply_user_edits`) MUST go through
``build_tailored_docx`` (which uses ``replace_paragraph_text_preserving_format``).
Direct ``paragraph.text = ...`` assignment is forbidden — it strips every
character format off the run (Phase 4 docx_writer Pitfall 1).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document


def extract_sections_from_docx(docx_path: Path | str) -> dict[str, Any]:
    """Walk headings in a DOCX and return a ``{sections: [...]}`` payload.

    Heuristic: every paragraph whose style name starts with ``"Heading"`` is
    a section boundary. Non-heading paragraphs accumulate into the current
    section's ``content`` list (one item per non-empty paragraph).

    Pre-heading paragraphs (a name / contact block at the top of the
    document) are bucketed into a leading section with ``heading == ""``
    so the user still sees a textarea for them. ``build_tailored_docx``
    will not match a section against an empty heading on write, so the
    pre-heading block round-trips through the DOCX unchanged.

    Returns:
        ``{"sections": [{"heading": str, "content": [str, ...]}, ...]}``
    """
    doc = Document(str(docx_path))
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for para in doc.paragraphs:
        style = (para.style.name or "") if para.style is not None else ""
        if style.lower().startswith("heading"):
            if current is not None:
                sections.append(current)
            current = {"heading": para.text.strip(), "content": []}
        else:
            if current is None:
                # Pre-heading paragraphs (name / contact block).
                current = {"heading": "", "content": []}
            text = para.text.strip()
            if text:
                current["content"].append(text)

    if current is not None:
        sections.append(current)

    return {"sections": sections}


def apply_user_edits(
    *,
    base_resume_path: Path,
    edited_sections: dict[str, Any],
    output_path: Path,
) -> Path:
    """Regenerate a tailored DOCX from user-edited sections.

    Pipes straight through :func:`app.tailoring.docx_writer.build_tailored_docx`,
    which is the only safe DOCX mutator in the codebase
    (``replace_paragraph_text_preserving_format``). NEVER call
    ``paragraph.text = ...`` here — see module docstring.
    """
    from app.tailoring.docx_writer import build_tailored_docx

    return build_tailored_docx(
        base_resume_path=base_resume_path,
        tailored_sections=edited_sections,
        output_path=output_path,
    )


__all__ = ["extract_sections_from_docx", "apply_user_edits"]
