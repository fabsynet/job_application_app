"""Tests for PlaywrightStrategy (06-05)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.playwright_submit.form_filler import KnownField, UnknownFieldInfo
from app.playwright_submit.strategy import PlaywrightStrategy, _is_known_ats_url
from app.submission.registry import SubmissionContext, SubmissionOutcome


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_job(source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/123", job_id=42):
    """Create a minimal Job-like object."""
    job = SimpleNamespace(
        id=job_id,
        source=source,
        url=url,
        title="Software Engineer",
        company="Acme",
        description="Great job",
    )
    return job


def _make_ctx(job=None, **overrides):
    """Create a SubmissionContext with sensible defaults."""
    if job is None:
        job = _make_job()
    defaults = dict(
        job=job,
        tailored_resume_path=Path("/tmp/resume.pdf"),
        cover_letter_path=Path("/tmp/cover.pdf"),
        recipient_email="hr@acme.com",
        subject="Application",
        body_text="Please consider me.",
        attachment_filename="resume.pdf",
        smtp_creds=SimpleNamespace(
            host="smtp.test", port=587, username="u", password="p"
        ),
    )
    defaults.update(overrides)
    return SubmissionContext(**defaults)


def _make_settings(headless=True, pause_if_unsure=True):
    """Create a mock Settings row."""
    return SimpleNamespace(
        playwright_headless=headless,
        pause_if_unsure=pause_if_unsure,
        screenshot_retention_days=30,
    )


def _make_profile():
    return SimpleNamespace(
        full_name="John Doe",
        email="john@example.com",
        phone="555-0100",
    )


def _mock_session_factory(settings=None, profile=None, saved_answers=None):
    """Return a session factory that yields a mock session.

    The mock session supports async context manager usage and patches
    the service calls that PlaywrightStrategy makes.
    """
    _settings = settings or _make_settings()
    _profile = profile or _make_profile()
    _saved_answers = saved_answers if saved_answers is not None else []

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory, mock_session, _settings, _profile, _saved_answers


# ---------------------------------------------------------------------------
# _is_known_ats_url
# ---------------------------------------------------------------------------


class TestIsKnownAtsUrl:
    def test_greenhouse(self):
        assert _is_known_ats_url("https://boards.greenhouse.io/acme") is True

    def test_lever(self):
        assert _is_known_ats_url("https://jobs.lever.co/acme") is True

    def test_ashby(self):
        assert _is_known_ats_url("https://jobs.ashbyhq.com/acme") is True

    def test_unknown(self):
        assert _is_known_ats_url("https://example.com/careers") is False

    def test_empty(self):
        assert _is_known_ats_url("") is False

    def test_none_like(self):
        assert _is_known_ats_url("") is False


# ---------------------------------------------------------------------------
# is_applicable
# ---------------------------------------------------------------------------


class TestIsApplicable:
    def test_greenhouse_source(self):
        job = _make_job(source="greenhouse", url="https://example.com")
        strategy = PlaywrightStrategy()
        assert strategy.is_applicable(job, "some description") is True

    def test_lever_source(self):
        job = _make_job(source="lever", url="https://example.com")
        strategy = PlaywrightStrategy()
        assert strategy.is_applicable(job, "some description") is True

    def test_ashby_source(self):
        job = _make_job(source="ashby", url="https://example.com")
        strategy = PlaywrightStrategy()
        assert strategy.is_applicable(job, "some description") is True

    def test_lever_url_unknown_source(self):
        job = _make_job(source="indeed", url="https://jobs.lever.co/acme/123")
        strategy = PlaywrightStrategy()
        assert strategy.is_applicable(job, "") is True

    def test_unknown_source_and_url(self):
        job = _make_job(source="indeed", url="https://indeed.com/jobs/123")
        strategy = PlaywrightStrategy()
        assert strategy.is_applicable(job, "") is False

    def test_no_source_no_url(self):
        job = _make_job(source="", url="")
        strategy = PlaywrightStrategy()
        assert strategy.is_applicable(job, "") is False


# ---------------------------------------------------------------------------
# submit — happy path
# ---------------------------------------------------------------------------


class TestSubmitSuccess:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Full success: navigate -> scan -> fill -> submit -> detect -> save."""
        factory, mock_session, settings, profile, saved = _mock_session_factory()

        mock_bm = AsyncMock()
        mock_page = AsyncMock()
        mock_bm.get_page = AsyncMock(return_value=mock_page)
        mock_bm.save_state = AsyncMock()
        mock_bm.headless = True

        mock_filler = AsyncMock()
        mock_filler.navigate_to_form = AsyncMock(return_value=True)
        mock_filler.scan_all_pages = AsyncMock(return_value=(
            [KnownField(label="Name", profile_field="full_name", value="John Doe", input_method="text", locator=None)],
            [],  # no unknown fields
        ))
        mock_filler.fill_and_submit = AsyncMock(return_value=True)
        mock_filler.detect_success = AsyncMock(return_value=True)

        strategy = PlaywrightStrategy(
            browser_manager=mock_bm,
            session_factory=factory,
        )

        ctx = _make_ctx()

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value=None),
            patch("app.playwright_submit.strategy.select_filler", return_value=mock_filler),
            patch("app.playwright_submit.strategy.capture_step_screenshot", new_callable=AsyncMock, return_value="screenshots/42/step_1.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._load_settings", return_value=settings),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
            patch("app.settings.service.get_profile_row", return_value=profile),
            patch("app.learning.service.get_all_saved_answers", return_value=saved),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert outcome.submitter == "playwright"
        mock_bm.save_state.assert_awaited_once()
        mock_filler.fill_and_submit.assert_awaited_once()
        mock_filler.detect_success.assert_awaited_once()


# ---------------------------------------------------------------------------
# submit — CAPTCHA detected
# ---------------------------------------------------------------------------


class TestSubmitCaptcha:
    @pytest.mark.asyncio
    async def test_captcha_returns_failure(self):
        factory, mock_session, settings, profile, saved = _mock_session_factory()

        mock_bm = AsyncMock()
        mock_page = AsyncMock()
        mock_bm.get_page = AsyncMock(return_value=mock_page)
        mock_bm.headless = True

        mock_filler = AsyncMock()
        mock_filler.navigate_to_form = AsyncMock(return_value=True)

        strategy = PlaywrightStrategy(browser_manager=mock_bm, session_factory=factory)
        ctx = _make_ctx()

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value="recaptcha"),
            patch("app.playwright_submit.strategy.select_filler", return_value=mock_filler),
            patch("app.playwright_submit.strategy.capture_error_screenshot", new_callable=AsyncMock, return_value="error.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._load_settings", return_value=settings),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is False
        assert outcome.error_class == "captcha"
        assert outcome.error_message == "recaptcha"


# ---------------------------------------------------------------------------
# submit — unknown fields with pause_if_unsure
# ---------------------------------------------------------------------------


class TestSubmitUnknownFields:
    @pytest.mark.asyncio
    async def test_pause_if_unsure_true_returns_needs_info(self):
        """Unknown fields + pause_if_unsure -> needs_info outcome."""
        factory, mock_session, settings, profile, saved = _mock_session_factory(
            settings=_make_settings(pause_if_unsure=True),
            saved_answers=[],
        )

        mock_bm = AsyncMock()
        mock_page = AsyncMock()
        mock_bm.get_page = AsyncMock(return_value=mock_page)
        mock_bm.headless = True

        unknowns = [
            UnknownFieldInfo(label="Preferred pronouns", field_type="text", is_required=True),
            UnknownFieldInfo(label="Visa status", field_type="select", options=["Yes", "No"]),
        ]

        mock_filler = AsyncMock()
        mock_filler.navigate_to_form = AsyncMock(return_value=True)
        mock_filler.scan_all_pages = AsyncMock(return_value=([], unknowns))

        strategy = PlaywrightStrategy(browser_manager=mock_bm, session_factory=factory)
        ctx = _make_ctx()

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value=None),
            patch("app.playwright_submit.strategy.select_filler", return_value=mock_filler),
            patch("app.playwright_submit.strategy.capture_step_screenshot", new_callable=AsyncMock, return_value="step.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._load_settings", return_value=settings),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
            patch("app.settings.service.get_profile_row", return_value=profile),
            patch("app.learning.service.get_all_saved_answers", return_value=[]),
            patch("app.learning.service.create_unknown_fields", new_callable=AsyncMock, return_value=[]),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is False
        assert outcome.error_class == "needs_info"
        assert "2 unknown fields" in outcome.error_message

    @pytest.mark.asyncio
    async def test_pause_if_unsure_false_proceeds(self):
        """Unknown fields + pause_if_unsure=False -> proceeds to submit."""
        factory, mock_session, settings, profile, saved = _mock_session_factory(
            settings=_make_settings(pause_if_unsure=False),
            saved_answers=[],
        )

        mock_bm = AsyncMock()
        mock_page = AsyncMock()
        mock_bm.get_page = AsyncMock(return_value=mock_page)
        mock_bm.headless = True

        unknowns = [
            UnknownFieldInfo(label="Preferred pronouns", field_type="text"),
        ]

        mock_filler = AsyncMock()
        mock_filler.navigate_to_form = AsyncMock(return_value=True)
        mock_filler.scan_all_pages = AsyncMock(return_value=(
            [KnownField(label="Name", profile_field="full_name", value="John Doe", input_method="text", locator=None)],
            unknowns,
        ))
        mock_filler.fill_and_submit = AsyncMock(return_value=True)
        mock_filler.detect_success = AsyncMock(return_value=True)

        strategy = PlaywrightStrategy(browser_manager=mock_bm, session_factory=factory)
        ctx = _make_ctx()

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value=None),
            patch("app.playwright_submit.strategy.select_filler", return_value=mock_filler),
            patch("app.playwright_submit.strategy.capture_step_screenshot", new_callable=AsyncMock, return_value="step.png"),
            patch("app.playwright_submit.strategy.capture_error_screenshot", new_callable=AsyncMock, return_value="error.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._load_settings", return_value=settings),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
            patch("app.settings.service.get_profile_row", return_value=profile),
            patch("app.learning.service.get_all_saved_answers", return_value=[]),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert outcome.submitter == "playwright"
        mock_filler.fill_and_submit.assert_awaited_once()


# ---------------------------------------------------------------------------
# submit — error -> screenshot + failure
# ---------------------------------------------------------------------------


class TestSubmitError:
    @pytest.mark.asyncio
    async def test_exception_returns_failure_with_screenshot(self):
        """Any exception -> error screenshot + failure outcome."""
        factory, mock_session, settings, profile, saved = _mock_session_factory()

        mock_bm = AsyncMock()
        mock_page = AsyncMock()
        mock_bm.get_page = AsyncMock(return_value=mock_page)
        mock_bm.headless = True

        mock_filler = AsyncMock()
        mock_filler.navigate_to_form = AsyncMock(
            side_effect=RuntimeError("Playwright crashed")
        )

        strategy = PlaywrightStrategy(browser_manager=mock_bm, session_factory=factory)
        ctx = _make_ctx()

        with (
            patch("app.playwright_submit.strategy.select_filler", return_value=mock_filler),
            patch("app.playwright_submit.strategy.capture_error_screenshot", new_callable=AsyncMock, return_value="error.png") as mock_err_ss,
            patch("app.playwright_submit.strategy.PlaywrightStrategy._load_settings", return_value=settings),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is False
        assert outcome.error_class == "RuntimeError"
        assert "Playwright crashed" in outcome.error_message
        mock_err_ss.assert_awaited_once()


# ---------------------------------------------------------------------------
# submit — auto-match from saved answers
# ---------------------------------------------------------------------------


class TestSubmitAutoMatch:
    @pytest.mark.asyncio
    async def test_unknown_field_matched_via_llm(self):
        """Unknown field matched by LLM -> auto-filled, not halted."""
        mock_saved_answer = SimpleNamespace(
            id=10, field_label="Pronouns", answer_text="he/him", answer_type="text",
            times_reused=3,
        )
        factory, mock_session, settings, profile, saved = _mock_session_factory(
            settings=_make_settings(pause_if_unsure=True),
            saved_answers=[mock_saved_answer],
        )

        mock_bm = AsyncMock()
        mock_page = AsyncMock()
        mock_bm.get_page = AsyncMock(return_value=mock_page)
        mock_bm.save_state = AsyncMock()
        mock_bm.headless = True

        unknowns = [
            UnknownFieldInfo(label="Preferred pronouns", field_type="text"),
        ]

        mock_filler = AsyncMock()
        mock_filler.navigate_to_form = AsyncMock(return_value=True)
        mock_filler.scan_all_pages = AsyncMock(return_value=(
            [KnownField(label="Name", profile_field="full_name", value="John Doe", input_method="text", locator=None)],
            unknowns,
        ))
        mock_filler.fill_and_submit = AsyncMock(return_value=True)
        mock_filler.detect_success = AsyncMock(return_value=True)

        # try_match_and_fill returns all matched, none truly unknown
        async def mock_try_match(session, infos, answers, provider):
            for info in infos:
                info["matched_answer"] = mock_saved_answer
            return infos, []

        strategy = PlaywrightStrategy(browser_manager=mock_bm, session_factory=factory)
        ctx = _make_ctx()

        mock_provider = MagicMock()

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value=None),
            patch("app.playwright_submit.strategy.select_filler", return_value=mock_filler),
            patch("app.playwright_submit.strategy.capture_step_screenshot", new_callable=AsyncMock, return_value="step.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._load_settings", return_value=settings),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
            patch("app.settings.service.get_profile_row", return_value=profile),
            patch("app.learning.service.get_all_saved_answers", return_value=[mock_saved_answer]),
            patch("app.learning.matcher.try_match_and_fill", side_effect=mock_try_match),
            patch("app.tailoring.provider.get_provider", new_callable=AsyncMock, return_value=mock_provider),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert len(strategy.reused_answers) == 1
        assert strategy.reused_answers[0][0] == "Preferred pronouns"
        assert strategy.reused_answers[0][1] == mock_saved_answer
        mock_filler.fill_and_submit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_satisfies_submitter_strategy(self):
        from app.submission.registry import SubmitterStrategy
        strategy = PlaywrightStrategy()
        assert isinstance(strategy, SubmitterStrategy)

    def test_name_attribute(self):
        strategy = PlaywrightStrategy()
        assert strategy.name == "playwright"
