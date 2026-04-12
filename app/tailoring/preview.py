"""DOCX-to-HTML preview and section diff for the tailoring review queue.

The review queue (Phase 4 plan 05+) shows each tailored resume
side-by-side with the user's base resume and highlights what changed.
Two pieces of infrastructure live here:

1. :func:`docx_to_html` converts a DOCX file to semantic HTML via
   `mammoth <https://pypi.org/project/mammoth/>`_.  Mammoth produces
   clean ``<h1>/<p>/<ul>`` markup that drops cleanly into a Pico.css
   card without extra styling.  Conversion warnings (unrecognised
   styles, unsupported content) are logged at debug level so they
   surface via structlog but never raise.

2. :func:`generate_section_diff` compares the base resume's extracted
   sections (the dict returned by
   :func:`app.resume.service.extract_resume_text`) with the structured
   JSON produced by the tailoring engine, emitting a per-section
   ``changed`` flag for the UI.

3. :func:`format_diff_html` renders the diff into a two-column HTML
   fragment suitable for Jinja2 ``{{ diff_html | safe }}`` embedding.
   Changed sections get a highlight background.  Removed lines are
   rendered with strikethrough, added lines with a light callout
   background — mirroring the unified-diff intuition without pulling
   in a JavaScript diff library.
"""

from __future__ import annotations

import difflib
import html
from pathlib import Path
from typing import Any

import mammoth
import structlog

log = structlog.get_logger(__name__)


# -- DOCX -> HTML ------------------------------------------------------------


def docx_to_html(docx_path: Path) -> str:
    """Convert a DOCX file to semantic HTML for in-browser preview.

    Mammoth maps paragraph styles to ``<h1>``/``<h2>``/``<p>`` and
    bullet lists to ``<ul><li>``.  The output is a raw HTML fragment
    (no ``<html>`` or ``<body>`` wrapper) so callers can inject it
    into a Jinja2 template with ``{{ html | safe }}``.

    Conversion warnings (e.g. "unrecognised paragraph style") are
    logged at debug level via structlog and do not raise.
    """
    docx_path = Path(docx_path)
    with open(docx_path, "rb") as fh:
        result = mammoth.convert_to_html(fh)

    for message in result.messages or []:
        # Each message has ``type`` ("warning" / "error") and
        # ``message`` attributes in mammoth's model.  Log at debug so
        # the signal is available without polluting INFO logs.
        log.debug(
            "preview.mammoth_message",
            path=str(docx_path),
            type=getattr(message, "type", "unknown"),
            message=str(message),
        )

    return result.value or ""


# -- Diff model --------------------------------------------------------------


def _tailored_section_text(section: dict) -> str:
    """Flatten a tailored JSON section into plain text for diffing.

    The diff is line-oriented, so the section text keeps one item per
    line.  Subsections (work-experience pattern) are flattened into
    "Company — Title (Dates)" headers followed by their bullets.
    """
    parts: list[str] = []

    content = section.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        parts.extend(str(c) for c in content)

    subsections = section.get("subsections") or []
    for sub in subsections:
        header_bits = [
            str(sub.get("company", "")).strip(),
            str(sub.get("title", "")).strip(),
            str(sub.get("dates", "")).strip(),
        ]
        header = " \u2014 ".join(b for b in header_bits if b)
        if header:
            parts.append(header)
        for bullet in sub.get("bullets", []) or []:
            parts.append(str(bullet))

    return "\n".join(p for p in parts if p)


def generate_section_diff(
    base_sections: list[dict],
    tailored_sections: dict,
) -> list[dict[str, Any]]:
    """Compare base resume sections with tailored JSON sections.

    Arguments:
        base_sections: The ``sections`` list returned by
            :func:`app.resume.service.extract_resume_text`.  Each item
            has ``heading`` and ``text``.
        tailored_sections: The structured JSON produced by the
            tailoring engine.  Expected to contain a ``sections`` key.

    Returns a list of diff rows, each shaped::

        {
            "heading": str,
            "base_text": str,
            "tailored_text": str,
            "changed": bool,
        }

    Rows appear in base-resume order.  Tailored sections that do not
    match any base heading are appended at the end with an empty
    ``base_text`` and ``changed=True``.
    """
    # Build a lookup of tailored sections by lowercase heading.
    tailored_by_heading: dict[str, dict] = {}
    for section in tailored_sections.get("sections", []) or []:
        heading = str(section.get("heading", "")).strip()
        if heading:
            tailored_by_heading[heading.lower()] = section

    diffs: list[dict[str, Any]] = []
    matched_keys: set[str] = set()

    for base in base_sections:
        heading = (base.get("heading") or "").strip()
        base_text = (base.get("text") or "").strip()
        if not heading and not base_text:
            continue

        key = heading.lower()
        tailored = tailored_by_heading.get(key)
        tailored_text = _tailored_section_text(tailored) if tailored else ""
        if tailored:
            matched_keys.add(key)

        # Only mark "changed" when there is an actual tailored payload
        # that differs from the base; otherwise the section is
        # untouched and we render it neutrally.
        changed = bool(tailored_text) and tailored_text.strip() != base_text.strip()

        diffs.append(
            {
                "heading": heading or "(untitled)",
                "base_text": base_text,
                "tailored_text": tailored_text or base_text,
                "changed": changed,
            }
        )

    # Append any tailored-only sections that didn't match a base
    # heading (e.g. Claude added "Projects" when the base has none).
    for key, section in tailored_by_heading.items():
        if key in matched_keys:
            continue
        diffs.append(
            {
                "heading": str(section.get("heading", "")).strip() or "(untitled)",
                "base_text": "",
                "tailored_text": _tailored_section_text(section),
                "changed": True,
            }
        )

    return diffs


# -- Diff -> HTML ------------------------------------------------------------


def _line_diff_html(base_text: str, tailored_text: str) -> tuple[str, str]:
    """Return a pair ``(base_html, tailored_html)`` with line-level markup.

    Uses :class:`difflib.SequenceMatcher` at the line level so removed
    lines are wrapped in ``<del>`` on the base side and added lines are
    wrapped in ``<ins>`` on the tailored side.  Unchanged lines render
    plainly on both sides.
    """
    base_lines = base_text.splitlines()
    tailored_lines = tailored_text.splitlines()
    matcher = difflib.SequenceMatcher(a=base_lines, b=tailored_lines)

    base_out: list[str] = []
    tailored_out: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for line in base_lines[i1:i2]:
                base_out.append(html.escape(line))
            for line in tailored_lines[j1:j2]:
                tailored_out.append(html.escape(line))
        elif tag == "delete":
            for line in base_lines[i1:i2]:
                base_out.append(f"<del>{html.escape(line)}</del>")
        elif tag == "insert":
            for line in tailored_lines[j1:j2]:
                tailored_out.append(f"<ins>{html.escape(line)}</ins>")
        elif tag == "replace":
            for line in base_lines[i1:i2]:
                base_out.append(f"<del>{html.escape(line)}</del>")
            for line in tailored_lines[j1:j2]:
                tailored_out.append(f"<ins>{html.escape(line)}</ins>")

    return "<br>".join(base_out), "<br>".join(tailored_out)


_DIFF_WRAPPER_STYLES = (
    "display:grid;grid-template-columns:1fr 1fr;gap:1rem;"
    "margin-block:0.5rem;"
)
_SECTION_BASE_STYLES = (
    "border:1px solid var(--pico-muted-border-color,#ccc);"
    "border-radius:var(--pico-border-radius,0.25rem);"
    "padding:0.75rem;"
)
_SECTION_CHANGED_STYLES = "background:var(--pico-mark-background-color,#fff3cd);"
_HEADING_STYLES = "margin:0 0 0.5rem 0;font-size:0.9rem;opacity:0.75;"
_INS_STYLES = "background:#d4edda;text-decoration:none;"
_DEL_STYLES = "color:#721c24;"


def format_diff_html(diffs: list[dict[str, Any]]) -> str:
    """Render a diff list as a side-by-side HTML fragment.

    Output structure per section::

        <section class="tailoring-diff-section">
          <header>Heading</header>
          <div class="tailoring-diff-grid">
            <div class="tailoring-diff-base">...</div>
            <div class="tailoring-diff-tailored">...</div>
          </div>
        </section>

    Changed sections get a highlight background.  Base and tailored
    columns show line-level ``<del>`` / ``<ins>`` markup so reviewers
    can see exactly which bullets changed.  Inline styles are used so
    the fragment works without a matching CSS bundle; the class names
    are still emitted so a future stylesheet can override them.
    """
    if not diffs:
        return '<p class="tailoring-diff-empty">No sections to compare.</p>'

    pieces: list[str] = []
    for d in diffs:
        heading = html.escape(str(d.get("heading", "(untitled)")))
        base_text = str(d.get("base_text", ""))
        tailored_text = str(d.get("tailored_text", ""))
        changed = bool(d.get("changed"))

        if changed:
            base_html, tailored_html = _line_diff_html(base_text, tailored_text)
            section_style = _SECTION_BASE_STYLES + _SECTION_CHANGED_STYLES
            marker = '<small>changed</small>'
        else:
            base_html = html.escape(base_text).replace("\n", "<br>")
            tailored_html = html.escape(tailored_text).replace("\n", "<br>")
            section_style = _SECTION_BASE_STYLES
            marker = '<small>unchanged</small>'

        pieces.append(
            f'<section class="tailoring-diff-section" style="{section_style}">'
            f'<header style="{_HEADING_STYLES}">'
            f'<strong>{heading}</strong> {marker}'
            f'</header>'
            f'<div class="tailoring-diff-grid" style="{_DIFF_WRAPPER_STYLES}">'
            f'<div class="tailoring-diff-base">{base_html or "&nbsp;"}</div>'
            f'<div class="tailoring-diff-tailored">{tailored_html or "&nbsp;"}</div>'
            f'</div>'
            f'</section>'
        )

    # Scoped styling for <ins>/<del> inside the diff blocks so the
    # markup is self-contained.
    scoped_css = (
        "<style>"
        ".tailoring-diff-section ins{" + _INS_STYLES + "}"
        ".tailoring-diff-section del{" + _DEL_STYLES + "}"
        "</style>"
    )

    return scoped_css + "".join(pieces)


__all__ = [
    "docx_to_html",
    "generate_section_diff",
    "format_diff_html",
]
