"""Unit tests for app.submission.builder pure helpers (Phase 5, Plan 05-02)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from docx import Document

from app.submission.builder import (
    build_attachment_filename,
    build_email_message,
    build_subject,
    extract_cover_letter_plaintext,
    resolve_recipient_email,
)


# --- build_subject --------------------------------------------------------


def test_build_subject_formats_locked_template() -> None:
    assert (
        build_subject(role="Senior Backend Engineer", company="Stripe")
        == "Application for Senior Backend Engineer at Stripe"
    )


def test_build_subject_defaults_on_empty_inputs() -> None:
    assert build_subject(role="", company="") == "Application for Application at Unknown"


# --- build_attachment_filename --------------------------------------------


def test_build_attachment_filename_ascii_only() -> None:
    assert (
        build_attachment_filename(full_name="Omobolaji Abubakre", company="Stripe")
        == "Omobolaji_Abubakre_Stripe_Resume.docx"
    )


def test_build_attachment_filename_strips_unicode() -> None:
    name = build_attachment_filename(full_name="Café", company="Nestlé")
    # Strip .docx suffix and assert the remainder is strict ASCII slug charset.
    stem = name[: -len("_Resume.docx")]
    assert re.fullmatch(r"[A-Za-z0-9_]+", stem), stem
    # Every non-ASCII letter was stripped, so the only remaining chars are "Caf" and "Nestl".
    assert stem == "Caf_Nestl"


def test_build_attachment_filename_handles_empty() -> None:
    assert (
        build_attachment_filename(full_name="", company="")
        == "Unknown_Unknown_Resume.docx"
    )


def test_build_attachment_filename_strips_punctuation() -> None:
    assert (
        build_attachment_filename(full_name="Jane O'Neill", company="A&B Inc.")
        == "Jane_ONeill_AB_Inc_Resume.docx"
    )


# --- resolve_recipient_email ----------------------------------------------


def test_resolve_recipient_skips_noreply() -> None:
    desc = "Please do not reply to noreply@foo.com — send your application to hr@foo.com."
    assert resolve_recipient_email(desc) == "hr@foo.com"


def test_resolve_recipient_returns_none_when_absent() -> None:
    assert resolve_recipient_email("No contact info here.") is None


def test_resolve_recipient_returns_none_on_empty() -> None:
    assert resolve_recipient_email("") is None
    assert resolve_recipient_email(None) is None  # type: ignore[arg-type]


def test_resolve_recipient_skips_all_noreply_variants() -> None:
    desc = (
        "Send to noreply@x.com or no-reply@y.com or donotreply@z.com "
        "or do-not-reply@w.com or notifications@v.com."
    )
    assert resolve_recipient_email(desc) is None


def test_resolve_recipient_first_match_wins() -> None:
    desc = "Contact careers@acme.io or jobs@acme.io."
    assert resolve_recipient_email(desc) == "careers@acme.io"


# --- extract_cover_letter_plaintext ---------------------------------------


def _make_cover_letter_docx(tmp_path: Path, paragraphs: list[str]) -> Path:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    out = tmp_path / "cover.docx"
    doc.save(str(out))
    return out


def test_extract_cover_letter_plaintext_joins_with_blank_lines(tmp_path: Path) -> None:
    path = _make_cover_letter_docx(
        tmp_path,
        [
            "Dear Hiring Manager,",
            "",  # empty — should be dropped
            "I am excited to apply for the Senior Backend Engineer role.",
            "   ",  # whitespace only — should be dropped
            "Sincerely,",
            "Omobolaji Abubakre",
        ],
    )
    text = extract_cover_letter_plaintext(path)
    assert text == (
        "Dear Hiring Manager,\n\n"
        "I am excited to apply for the Senior Backend Engineer role.\n\n"
        "Sincerely,\n\n"
        "Omobolaji Abubakre"
    )


def test_extract_cover_letter_plaintext_accepts_string_path(tmp_path: Path) -> None:
    path = _make_cover_letter_docx(tmp_path, ["Hello", "World"])
    assert extract_cover_letter_plaintext(str(path)) == "Hello\n\nWorld"


# --- build_email_message --------------------------------------------------


def test_build_email_message_has_docx_attachment(tmp_path: Path) -> None:
    # Use a tiny real DOCX as the attachment so read_bytes returns a zip.
    attachment = _make_cover_letter_docx(tmp_path, ["resume body"])
    msg = build_email_message(
        from_addr="me@example.com",
        to_addr="hr@stripe.com",
        subject="Application for Engineer at Stripe",
        body_text="Dear Hiring Manager,\n\nPlease find my resume attached.",
        attachment_path=attachment,
        attachment_filename="Jane_Stripe_Resume.docx",
    )

    # Top-level must be multipart after add_attachment.
    assert msg.get_content_maintype() == "multipart"
    assert msg["Subject"] == "Application for Engineer at Stripe"
    assert msg["From"] == "me@example.com"
    assert msg["To"] == "hr@stripe.com"

    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    part = attachments[0]
    assert part.get_filename() == "Jane_Stripe_Resume.docx"
    assert part.get_content_type() == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    # The payload bytes should equal the original file.
    assert part.get_payload(decode=True) == attachment.read_bytes()


def test_build_email_message_preserves_body_newlines(tmp_path: Path) -> None:
    attachment = _make_cover_letter_docx(tmp_path, ["resume"])
    body = "Line one.\n\nLine two.\n\nLine three."
    msg = build_email_message(
        from_addr="me@example.com",
        to_addr="hr@example.com",
        subject="x",
        body_text=body,
        attachment_path=attachment,
        attachment_filename="x_Resume.docx",
    )
    # First non-attachment part is the body.
    body_part = next(
        p for p in msg.walk() if p.get_content_type() == "text/plain"
    )
    assert body in body_part.get_content()


@pytest.mark.parametrize("port_input", [587, 465])
def test_builder_module_exports(port_input: int) -> None:
    # Sanity: all advertised names are importable.
    from app.submission import builder

    for name in (
        "build_subject",
        "build_attachment_filename",
        "extract_cover_letter_plaintext",
        "resolve_recipient_email",
        "build_email_message",
    ):
        assert hasattr(builder, name), name
