"""Integration tests for Phase 6 requirements (SUBM-03/04/05, LEARN-01/03/04).

End-to-end tests that exercise the full PlaywrightStrategy pipeline with
real DB fixtures (in-memory SQLite via the async_session conftest fixture)
and mocked Playwright interactions (no real browser).

Every test creates real DB rows (Job, Profile, Settings, TailoringRecord,
SavedAnswer, UnknownField) and patches only the Playwright/browser layer.
"""

from __future__ import annotations

import json
from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.db.models import Profile, Settings
from app.learning.models import SavedAnswer, UnknownField
from app.playwright_submit.form_filler import KnownField, UnknownFieldInfo
from app.playwright_submit.strategy import PlaywrightStrategy
from app.submission.registry import (
    SubmissionContext,
    SubmissionOutcome,
    default_registry,
    select_strategy,
)
from app.tailoring.models import TailoringRecord
from app.tailoring.provider import LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_factory(session: AsyncSession):
    """Wrap a real AsyncSession in an async context manager factory."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def _seed_settings(session: AsyncSession, **overrides) -> Settings:
    defaults = dict(
        id=1,
        kill_switch=False,
        dry_run=False,
        daily_cap=20,
        delay_min_seconds=30,
        delay_max_seconds=120,
        timezone="UTC",
        wizard_complete=True,
        keywords_csv="python|backend",
        playwright_headless=True,
        pause_if_unsure=True,
        screenshot_retention_days=30,
    )
    defaults.update(overrides)
    s = Settings(**defaults)
    session.add(s)
    await session.flush()
    return s


async def _seed_profile(session: AsyncSession, **overrides) -> Profile:
    defaults = dict(
        id=1,
        full_name="Jane Doe",
        email="jane@example.com",
        phone="555-0100",
        linkedin_url="https://linkedin.com/in/janedoe",
    )
    defaults.update(overrides)
    p = Profile(**defaults)
    session.add(p)
    await session.flush()
    return p


async def _seed_job(session: AsyncSession, **overrides) -> Job:
    defaults = dict(
        fingerprint="abc123",
        external_id="ext-1",
        title="Software Engineer",
        company="Acme Corp",
        location="Remote",
        description="Great Python role",
        url="https://boards.greenhouse.io/acme/jobs/123",
        source="greenhouse",
        score=85,
        matched_keywords="python",
        status="queued",
    )
    defaults.update(overrides)
    j = Job(**defaults)
    session.add(j)
    await session.flush()
    return j


async def _seed_tailoring(session: AsyncSession, job_id: int) -> TailoringRecord:
    tr = TailoringRecord(
        job_id=job_id,
        version=1,
        intensity="balanced",
        status="completed",
        base_resume_path="/data/resumes/base.docx",
        tailored_resume_path="/data/resumes/tailored.docx",
        cover_letter_path="/data/letters/cover.pdf",
    )
    session.add(tr)
    await session.flush()
    return tr


async def _seed_saved_answer(
    session: AsyncSession,
    field_label: str,
    answer_text: str,
    answer_type: str = "text",
    **overrides,
) -> SavedAnswer:
    defaults = dict(
        field_label=field_label,
        field_label_normalized=" ".join(field_label.lower().split()),
        answer_text=answer_text,
        answer_type=answer_type,
        times_reused=0,
    )
    defaults.update(overrides)
    sa = SavedAnswer(**defaults)
    session.add(sa)
    await session.flush()
    return sa


def _make_ctx(job: Job, **overrides) -> SubmissionContext:
    defaults = dict(
        job=job,
        tailored_resume_path=Path("/data/resumes/tailored.docx"),
        cover_letter_path=Path("/data/letters/cover.pdf"),
        recipient_email="hr@acme.com",
        subject="Application for Software Engineer",
        body_text="Please consider my application.",
        attachment_filename="resume.pdf",
        smtp_creds=SimpleNamespace(
            host="smtp.test", port=587, username="u", password="p"
        ),
    )
    defaults.update(overrides)
    return SubmissionContext(**defaults)


def _mock_browser_manager():
    """Return a mock BrowserManager with page."""
    bm = AsyncMock()
    page = AsyncMock()
    bm.get_page = AsyncMock(return_value=page)
    bm.save_state = AsyncMock()
    bm.headless = True
    return bm, page


def _mock_filler(
    nav_ok: bool = True,
    known: list | None = None,
    unknown: list | None = None,
    submit_ok: bool = True,
    success_detected: bool = True,
):
    """Return a mock filler with configurable behavior."""
    filler = AsyncMock()
    filler.navigate_to_form = AsyncMock(return_value=nav_ok)
    filler.scan_all_pages = AsyncMock(return_value=(
        known if known is not None else [
            KnownField(
                label="Full Name",
                profile_field="full_name",
                value="Jane Doe",
                input_method="text",
                locator=None,
            ),
        ],
        unknown if unknown is not None else [],
    ))
    filler.fill_and_submit = AsyncMock(return_value=submit_ok)
    filler.detect_success = AsyncMock(return_value=success_detected)
    return filler


class FakeLLMProvider:
    """Scriptable mock provider returning canned LLMResponse objects.

    Same pattern as tests/learning/test_matcher.py.
    """

    def __init__(self, responses: list):
        self._responses = responses
        self._index = 0
        self.calls: list[dict] = []

    async def complete(self, system, messages, max_tokens, temperature=0.3):
        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if self._index >= len(self._responses):
            raise AssertionError(
                f"FakeLLMProvider ran out of responses at call {self._index}"
            )
        item = self._responses[self._index]
        self._index += 1
        if isinstance(item, LLMResponse):
            return item
        if isinstance(item, Exception):
            raise item
        return LLMResponse(
            content=str(item),
            input_tokens=50,
            output_tokens=30,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            model="fake",
        )


@asynccontextmanager
async def _standard_patches(bm, filler, session, data_dir=Path("/data"), extra_patches=None):
    """Enter all standard patches for a happy-path submission test."""
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.playwright_submit.strategy.detect_blocking_element",
            return_value=None,
        ))
        stack.enter_context(patch(
            "app.playwright_submit.strategy.select_filler",
            return_value=filler,
        ))
        stack.enter_context(patch(
            "app.playwright_submit.strategy.capture_step_screenshot",
            new_callable=AsyncMock,
            return_value="screenshots/step.png",
        ))
        stack.enter_context(patch(
            "app.playwright_submit.strategy.capture_error_screenshot",
            new_callable=AsyncMock,
            return_value="screenshots/error.png",
        ))
        stack.enter_context(patch(
            "app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir",
            return_value=data_dir,
        ))
        if extra_patches:
            for p in extra_patches:
                stack.enter_context(p)
        yield stack


# ===========================================================================
# SUBM-03 (SC-1): Playwright submits to Greenhouse/Lever/Ashby
# ===========================================================================


class TestSC1GreenhouseEndToEnd:
    """test_sc1_greenhouse_end_to_end: greenhouse job + profile + tailoring -> success."""

    @pytest.mark.asyncio
    async def test_sc1_greenhouse_end_to_end(self, async_session: AsyncSession):
        settings = await _seed_settings(async_session)
        profile = await _seed_profile(async_session)
        job = await _seed_job(
            async_session,
            source="greenhouse",
            url="https://boards.greenhouse.io/acme/jobs/123",
        )
        tr = await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler()
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert outcome.submitter == "playwright"
        filler.fill_and_submit.assert_awaited_once()
        filler.detect_success.assert_awaited_once()


class TestSC1LeverEndToEnd:
    """test_sc1_lever_end_to_end: lever job + profile + tailoring -> success."""

    @pytest.mark.asyncio
    async def test_sc1_lever_end_to_end(self, async_session: AsyncSession):
        settings = await _seed_settings(async_session)
        profile = await _seed_profile(async_session)
        job = await _seed_job(
            async_session,
            fingerprint="lever-fp",
            source="lever",
            url="https://jobs.lever.co/acme/abc-123",
        )
        tr = await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler()
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert outcome.submitter == "playwright"
        filler.fill_and_submit.assert_awaited_once()


class TestSC1AshbyEndToEnd:
    """test_sc1_ashby_end_to_end: ashby job + profile + tailoring -> success."""

    @pytest.mark.asyncio
    async def test_sc1_ashby_end_to_end(self, async_session: AsyncSession):
        settings = await _seed_settings(async_session)
        profile = await _seed_profile(async_session)
        job = await _seed_job(
            async_session,
            fingerprint="ashby-fp",
            source="ashby",
            url="https://jobs.ashbyhq.com/acme/job-456",
        )
        tr = await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler()
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert outcome.submitter == "playwright"
        filler.fill_and_submit.assert_awaited_once()


class TestSC1StorageStatePersisted:
    """test_sc1_storage_state_persisted: save_state() called after success."""

    @pytest.mark.asyncio
    async def test_sc1_storage_state_persisted(self, async_session: AsyncSession):
        await _seed_settings(async_session)
        await _seed_profile(async_session)
        job = await _seed_job(async_session)
        await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler()
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        bm.save_state.assert_awaited_once()


# ===========================================================================
# SUBM-04 (SC-5): Generic ATS forms
# ===========================================================================


class TestSC5GenericAtsSubmission:
    """test_sc5_generic_ats_submission: unknown source -> GenericFiller, screenshots captured."""

    @pytest.mark.asyncio
    async def test_sc5_generic_ats_submission(self, async_session: AsyncSession):
        await _seed_settings(async_session, pause_if_unsure=False)
        await _seed_profile(async_session)
        job = await _seed_job(
            async_session,
            fingerprint="generic-fp",
            source="workday",
            url="https://careers.workday.com/apply/123",
        )
        await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler(
            unknown=[
                UnknownFieldInfo(label="How did you hear about us?", field_type="text"),
            ],
        )
        factory = _session_factory(async_session)

        # GenericFiller is selected for non-ATS URLs -- but we're testing
        # the full pipeline, so we mock select_filler to return our filler.
        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        capture_step = AsyncMock(return_value="screenshots/step.png")

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value=None),
            patch("app.playwright_submit.strategy.select_filler", return_value=filler),
            patch("app.playwright_submit.strategy.capture_step_screenshot", capture_step),
            patch("app.playwright_submit.strategy.capture_error_screenshot", new_callable=AsyncMock, return_value="err.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        # Screenshots are captured at multiple steps
        assert capture_step.await_count >= 2


class TestSC5GenericFormDetection:
    """test_sc5_generic_form_detection: select_filler returns GenericFiller for unknown source."""

    def test_sc5_generic_form_detection(self):
        from app.playwright_submit.fillers import select_filler, GenericFiller

        filler = select_filler(job_source="workday", job_url="https://careers.workday.com/apply")
        assert isinstance(filler, GenericFiller)

        filler2 = select_filler(job_source=None, job_url="https://example.com/careers")
        assert isinstance(filler2, GenericFiller)


# ===========================================================================
# SUBM-05: Persistent session (storageState)
# ===========================================================================


class TestSubm05StorageState:
    """test_subm05_storage_state: loads when exists, saves after submit."""

    @pytest.mark.asyncio
    async def test_subm05_storage_state(self, async_session: AsyncSession, tmp_path: Path):
        """BrowserManager loads storageState.json when it exists and saves after success."""
        from app.playwright_submit.browser import BrowserManager

        storage_dir = tmp_path / "browser"
        storage_dir.mkdir()
        state_file = storage_dir / "storageState.json"
        state_file.write_text(json.dumps({"cookies": [{"name": "session", "value": "abc"}]}))

        bm = BrowserManager(headless=True, storage_state_dir=storage_dir)
        assert bm.storage_state_path.exists()
        assert bm.storage_state_path == state_file

        # Verify path is correct; actual browser calls are mocked at strategy level.
        # The save_state method is tested via the happy-path E2E tests above
        # (bm.save_state.assert_awaited_once).

    @pytest.mark.asyncio
    async def test_subm05_save_state_called_on_success(self, async_session: AsyncSession):
        """After a successful submission, save_state is called."""
        await _seed_settings(async_session)
        await _seed_profile(async_session)
        job = await _seed_job(async_session, fingerprint="ss-fp")
        await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler()
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        bm.save_state.assert_awaited_once()


# ===========================================================================
# LEARN-01 (SC-2): Unknown field logging
# ===========================================================================


class TestSC2UnknownFieldsHalt:
    """test_sc2_unknown_fields_halt: unknown fields + pause_if_unsure=True -> needs_info + DB rows."""

    @pytest.mark.asyncio
    async def test_sc2_unknown_fields_halt(self, async_session: AsyncSession):
        await _seed_settings(async_session, pause_if_unsure=True)
        await _seed_profile(async_session)
        job = await _seed_job(async_session, fingerprint="uf-fp")
        await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        unknowns = [
            UnknownFieldInfo(label="Preferred pronouns", field_type="text", is_required=True),
            UnknownFieldInfo(label="Visa status", field_type="select", options=["Yes", "No"]),
        ]
        filler = _mock_filler(unknown=unknowns)
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome = await strategy.submit(ctx)

        assert outcome.success is False
        assert outcome.error_class == "needs_info"
        assert "2 unknown fields" in outcome.error_message

        # Verify UnknownField rows were created in the DB.
        from sqlalchemy import select as sa_select
        result = await async_session.execute(
            sa_select(UnknownField).where(UnknownField.job_id == job.id)
        )
        uf_rows = list(result.scalars().all())
        assert len(uf_rows) == 2
        labels = {uf.field_label for uf in uf_rows}
        assert "Preferred pronouns" in labels
        assert "Visa status" in labels


# ===========================================================================
# LEARN-03 (SC-3): Answers persisted and reused
# ===========================================================================


class TestSC3AnswerAndRetry:
    """test_sc3_answer_and_retry: answer unknowns via learning service, retry succeeds."""

    @pytest.mark.asyncio
    async def test_sc3_answer_and_retry(self, async_session: AsyncSession):
        await _seed_settings(async_session, pause_if_unsure=True)
        await _seed_profile(async_session)
        job = await _seed_job(async_session, fingerprint="retry-fp")
        await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        # Step 1: First attempt halts on unknown fields.
        bm, page = _mock_browser_manager()
        unknowns = [
            UnknownFieldInfo(label="Work authorization", field_type="text", is_required=True),
        ]
        filler = _mock_filler(unknown=unknowns)
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(bm, filler, async_session):
            outcome1 = await strategy.submit(ctx)

        assert outcome1.success is False
        assert outcome1.error_class == "needs_info"

        # Step 2: User answers the unknown field via the learning service.
        from app.learning.service import resolve_all_for_job

        from sqlalchemy import select as sa_select
        result = await async_session.execute(
            sa_select(UnknownField).where(UnknownField.job_id == job.id)
        )
        uf_rows = list(result.scalars().all())
        assert len(uf_rows) == 1

        answers = {uf_rows[0].id: "Yes, authorized to work in US"}
        saved_answers = await resolve_all_for_job(async_session, job.id, answers)
        await async_session.commit()

        assert len(saved_answers) == 1
        assert saved_answers[0].answer_text == "Yes, authorized to work in US"

        # Step 3: Retry -- this time the saved answer matches via LLM.
        bm2, page2 = _mock_browser_manager()
        filler2 = _mock_filler(
            unknown=[
                UnknownFieldInfo(label="Work authorization", field_type="text", is_required=True),
            ],
        )

        # The LLM matcher returns the saved answer as a match.
        llm_response = json.dumps({
            "matches": {"Work authorization": saved_answers[0].id}
        })
        fake_provider = FakeLLMProvider([llm_response])

        strategy2 = PlaywrightStrategy(browser_manager=bm2, session_factory=factory)
        ctx2 = _make_ctx(job)

        async with _standard_patches(
            bm2, filler2, async_session,
            extra_patches=[
                patch(
                    "app.tailoring.provider.get_provider",
                    new_callable=AsyncMock,
                    return_value=fake_provider,
                ),
            ],
        ):
            outcome2 = await strategy2.submit(ctx2)

        assert outcome2.success is True
        assert outcome2.submitter == "playwright"
        filler2.fill_and_submit.assert_awaited_once()


# ===========================================================================
# LEARN-04 (SC-4): Semantic matching
# ===========================================================================


class TestSC4SemanticMatch:
    """test_sc4_semantic_match: SavedAnswer for 'work auth' matches 'Work Authorization' via LLM."""

    @pytest.mark.asyncio
    async def test_sc4_semantic_match(self, async_session: AsyncSession):
        await _seed_settings(async_session, pause_if_unsure=True)
        await _seed_profile(async_session)
        job = await _seed_job(async_session, fingerprint="sem-fp")
        await _seed_tailoring(async_session, job.id)

        # Create a saved answer with a slightly different label.
        sa = await _seed_saved_answer(
            async_session,
            field_label="work auth",
            answer_text="Yes, authorized",
        )
        await async_session.commit()

        # The form has "Work Authorization" -- different wording.
        bm, page = _mock_browser_manager()
        filler = _mock_filler(
            unknown=[
                UnknownFieldInfo(label="Work Authorization", field_type="text", is_required=True),
            ],
        )
        factory = _session_factory(async_session)

        # LLM says the two labels match.
        llm_response = json.dumps({
            "matches": {"Work Authorization": sa.id}
        })
        fake_provider = FakeLLMProvider([llm_response])

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        async with _standard_patches(
            bm, filler, async_session,
            extra_patches=[
                patch(
                    "app.tailoring.provider.get_provider",
                    new_callable=AsyncMock,
                    return_value=fake_provider,
                ),
            ],
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is True
        assert len(strategy.reused_answers) == 1
        assert strategy.reused_answers[0][0] == "Work Authorization"
        assert strategy.reused_answers[0][1].field_label == "work auth"

        # Verify the LLM was actually called for matching.
        assert len(fake_provider.calls) == 1


# ===========================================================================
# Cross-cutting: Registry order
# ===========================================================================


class TestRegistryOrder:
    """test_registry_order: [PlaywrightStrategy, EmailStrategy]."""

    def test_registry_order(self):
        from app.playwright_submit.strategy import PlaywrightStrategy
        from app.submission.strategies.email import EmailStrategy

        registry = default_registry()
        assert len(registry) == 2
        assert isinstance(registry[0], PlaywrightStrategy)
        assert isinstance(registry[1], EmailStrategy)


# ===========================================================================
# Cross-cutting: Playwright falls through to email
# ===========================================================================


class TestPlaywrightFallsThroughToEmail:
    """test_playwright_falls_through_to_email: non-ATS job -> EmailStrategy."""

    def test_playwright_falls_through_to_email(self):
        from app.submission.strategies.email import EmailStrategy

        job = Job(
            fingerprint="email-fp",
            external_id="ext-99",
            title="Designer",
            company="Widget Co",
            url="https://example.com/careers",
            source="indeed",
            status="queued",
            description="Contact us at hiring@widget.co to apply.",
        )

        strategy = select_strategy(job, job.description)
        assert strategy is not None
        assert isinstance(strategy, EmailStrategy)


# ===========================================================================
# Cross-cutting: CAPTCHA halts
# ===========================================================================


class TestCaptchaHalts:
    """test_captcha_halts: CAPTCHA detected -> error_class='captcha'."""

    @pytest.mark.asyncio
    async def test_captcha_halts(self, async_session: AsyncSession):
        await _seed_settings(async_session)
        await _seed_profile(async_session)
        job = await _seed_job(async_session, fingerprint="captcha-fp")
        await _seed_tailoring(async_session, job.id)
        await async_session.commit()

        bm, page = _mock_browser_manager()
        filler = _mock_filler()
        factory = _session_factory(async_session)

        strategy = PlaywrightStrategy(browser_manager=bm, session_factory=factory)
        ctx = _make_ctx(job)

        with (
            patch("app.playwright_submit.strategy.detect_blocking_element", return_value="recaptcha"),
            patch("app.playwright_submit.strategy.select_filler", return_value=filler),
            patch("app.playwright_submit.strategy.capture_error_screenshot", new_callable=AsyncMock, return_value="err.png"),
            patch("app.playwright_submit.strategy.capture_step_screenshot", new_callable=AsyncMock, return_value="step.png"),
            patch("app.playwright_submit.strategy.PlaywrightStrategy._get_data_dir", return_value=Path("/data")),
        ):
            outcome = await strategy.submit(ctx)

        assert outcome.success is False
        assert outcome.error_class == "captcha"
        assert outcome.error_message == "recaptcha"
        # fill_and_submit should NOT be called when CAPTCHA detected
        filler.fill_and_submit.assert_not_awaited()
