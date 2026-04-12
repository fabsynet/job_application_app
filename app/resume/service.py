"""Resume file storage and DOCX text extraction.

Handles saving uploaded DOCX files to the data directory and extracting
structured text content using python-docx for preview display.

The resume is stored as a single file (``base_resume.docx``) in the
``{DATA_DIR}/resumes/`` directory.  This directory maps to the host-mounted
``./data`` volume so the file survives container restarts.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from docx import Document
from fastapi import UploadFile

from app.config import get_settings


def _resume_dir() -> Path:
    """Return the resume storage directory, creating it if needed."""
    d = Path(get_settings().data_dir) / "resumes"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_resume(file: UploadFile) -> Path:
    """Save an uploaded DOCX file as the base resume.

    Overwrites any existing file so "replace" is just another upload.
    Uses ``shutil.copyfileobj`` for memory-efficient streaming.

    Returns the path to the saved file.
    """
    dest = _resume_dir() / "base_resume.docx"
    with open(dest, "wb") as out:
        shutil.copyfileobj(file.file, out)
    return dest


def extract_resume_text(file_path: Path) -> dict:
    """Extract text from a DOCX file, grouped by heading sections.

    Returns::

        {
            "full_text": str,       # all paragraphs joined by newlines
            "sections": [           # grouped by Heading styles
                {"heading": str | None, "text": str},
                ...
            ]
        }

    ``full_text`` is capped at 500 lines to prevent enormous previews.
    """
    doc = Document(str(file_path))

    all_lines: list[str] = []
    sections: list[dict[str, Optional[str]]] = []
    current_heading: Optional[str] = None
    current_text: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = para.style.name if para.style else ""

        if style_name.startswith("Heading"):
            # Flush the current section
            if current_text or current_heading is not None:
                sections.append({
                    "heading": current_heading,
                    "text": "\n".join(current_text),
                })
            current_heading = text
            current_text = []
        else:
            current_text.append(text)

        all_lines.append(text)

    # Flush final section
    if current_text or current_heading is not None:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_text),
        })

    # If no sections were created (no headings found), put everything in one
    if not sections and all_lines:
        sections.append({"heading": None, "text": "\n".join(all_lines[:500])})

    full_text = "\n".join(all_lines[:500])

    return {"full_text": full_text, "sections": sections}


def get_resume_path() -> Optional[Path]:
    """Return the path to the base resume if it exists, else None."""
    p = _resume_dir() / "base_resume.docx"
    return p if p.exists() else None


__all__ = ["save_resume", "extract_resume_text", "get_resume_path"]
