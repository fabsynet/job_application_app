"""Tests for ATS-specific fillers and select_filler routing (06-03)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.playwright_submit.fillers import (
    AshbyFiller,
    GenericFiller,
    GreenhouseFiller,
    LeverFiller,
    select_filler,
)


# ---------------------------------------------------------------------------
# select_filler routing
# ---------------------------------------------------------------------------


class TestSelectFiller:
    def test_greenhouse_by_source(self):
        filler = select_filler(job_source="greenhouse")
        assert isinstance(filler, GreenhouseFiller)

    def test_lever_by_source(self):
        filler = select_filler(job_source="lever")
        assert isinstance(filler, LeverFiller)

    def test_ashby_by_source(self):
        filler = select_filler(job_source="ashby")
        assert isinstance(filler, AshbyFiller)

    def test_source_case_insensitive(self):
        filler = select_filler(job_source="Greenhouse")
        assert isinstance(filler, GreenhouseFiller)

    def test_greenhouse_by_url(self):
        filler = select_filler(
            job_url="https://boards.greenhouse.io/acme/jobs/12345"
        )
        assert isinstance(filler, GreenhouseFiller)

    def test_lever_by_url(self):
        filler = select_filler(
            job_url="https://jobs.lever.co/acme/abc-123-def"
        )
        assert isinstance(filler, LeverFiller)

    def test_ashby_by_url(self):
        filler = select_filler(
            job_url="https://jobs.ashbyhq.com/acme/abc-123"
        )
        assert isinstance(filler, AshbyFiller)

    def test_unknown_url_returns_generic(self):
        filler = select_filler(
            job_url="https://careers.example.com/jobs/123"
        )
        assert isinstance(filler, GenericFiller)

    def test_no_args_returns_generic(self):
        filler = select_filler()
        assert isinstance(filler, GenericFiller)

    def test_source_takes_priority_over_url(self):
        filler = select_filler(
            job_source="lever",
            job_url="https://boards.greenhouse.io/acme/jobs/12345",
        )
        assert isinstance(filler, LeverFiller)

    def test_unknown_source_falls_to_url(self):
        filler = select_filler(
            job_source="workday",
            job_url="https://boards.greenhouse.io/acme/jobs/12345",
        )
        assert isinstance(filler, GreenhouseFiller)


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


class TestURLConstruction:
    def test_greenhouse_adds_anchor(self):
        filler = GreenhouseFiller()
        url = filler.get_form_url("https://boards.greenhouse.io/acme/jobs/12345")
        assert url.endswith("#app")

    def test_greenhouse_no_double_anchor(self):
        filler = GreenhouseFiller()
        url = filler.get_form_url(
            "https://boards.greenhouse.io/acme/jobs/12345#app"
        )
        assert url.count("#app") == 1

    def test_lever_adds_apply(self):
        filler = LeverFiller()
        url = filler.get_form_url("https://jobs.lever.co/acme/abc-123")
        assert url.endswith("/apply")

    def test_lever_no_double_apply(self):
        filler = LeverFiller()
        url = filler.get_form_url(
            "https://jobs.lever.co/acme/abc-123/apply"
        )
        assert url.count("/apply") == 1

    def test_ashby_adds_application(self):
        filler = AshbyFiller()
        url = filler.get_form_url("https://jobs.ashbyhq.com/acme/abc-123")
        assert url.endswith("/application")

    def test_ashby_no_double_application(self):
        filler = AshbyFiller()
        url = filler.get_form_url(
            "https://jobs.ashbyhq.com/acme/abc-123/application"
        )
        assert url.count("/application") == 1

    def test_generic_passthrough(self):
        filler = GenericFiller()
        url = filler.get_form_url("https://example.com/jobs/123/")
        assert url == "https://example.com/jobs/123"

    def test_trailing_slash_stripped(self):
        filler = LeverFiller()
        url = filler.get_form_url("https://jobs.lever.co/acme/abc-123/")
        assert url.endswith("/apply")
        assert "//" not in url.replace("https://", "")


# ---------------------------------------------------------------------------
# Greenhouse iframe fallback
# ---------------------------------------------------------------------------


class TestGreenhouseIframe:
    @pytest.mark.asyncio
    async def test_iframe_detected(self):
        filler = GreenhouseFiller()
        page = AsyncMock()
        page.goto = AsyncMock()

        # Simulate iframe present
        iframe_locator = AsyncMock()
        iframe_locator.count = AsyncMock(return_value=1)

        form_locator = AsyncMock()
        form_locator.count = AsyncMock(return_value=0)

        def locator_side_effect(selector):
            if "iframe" in selector:
                return iframe_locator
            return form_locator

        page.locator = MagicMock(side_effect=locator_side_effect)
        page.frame_locator = MagicMock(return_value=AsyncMock())

        result = await filler.navigate_to_form(
            page, "https://boards.greenhouse.io/acme/jobs/12345"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_direct_form_detected(self):
        filler = GreenhouseFiller()
        page = AsyncMock()
        page.goto = AsyncMock()

        iframe_locator = AsyncMock()
        iframe_locator.count = AsyncMock(return_value=0)

        form_locator = AsyncMock()
        form_locator.count = AsyncMock(return_value=1)

        def locator_side_effect(selector):
            if "iframe" in selector:
                return iframe_locator
            if "form" in selector.lower():
                return form_locator
            return AsyncMock(count=AsyncMock(return_value=0))

        page.locator = MagicMock(side_effect=locator_side_effect)
        page.frame_locator = MagicMock(return_value=AsyncMock())

        result = await filler.navigate_to_form(
            page, "https://boards.greenhouse.io/acme/jobs/12345"
        )
        assert result is True


# ---------------------------------------------------------------------------
# GDPR checkbox
# ---------------------------------------------------------------------------


class TestGDPRCheckbox:
    @pytest.mark.asyncio
    async def test_gdpr_auto_checked(self):
        filler = GreenhouseFiller()
        page = AsyncMock()

        checkbox = AsyncMock()
        checkbox.is_checked = AsyncMock(return_value=False)
        checkbox.check = AsyncMock()

        checkbox_locator = AsyncMock()
        checkbox_locator.count = AsyncMock(return_value=1)
        checkbox_locator.nth = MagicMock(return_value=checkbox)

        no_match_locator = AsyncMock()
        no_match_locator.count = AsyncMock(return_value=0)

        call_count = 0

        def locator_side_effect(selector):
            nonlocal call_count
            if "consent" in selector or "gdpr" in selector:
                call_count += 1
                if call_count == 1:
                    return checkbox_locator
                return no_match_locator
            return no_match_locator

        page.locator = MagicMock(side_effect=locator_side_effect)

        await filler._auto_check_gdpr(page)
        checkbox.check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_checked_skipped(self):
        filler = GreenhouseFiller()
        page = AsyncMock()

        checkbox = AsyncMock()
        checkbox.is_checked = AsyncMock(return_value=True)
        checkbox.check = AsyncMock()

        checkbox_locator = AsyncMock()
        checkbox_locator.count = AsyncMock(return_value=1)
        checkbox_locator.nth = MagicMock(return_value=checkbox)

        no_match_locator = AsyncMock()
        no_match_locator.count = AsyncMock(return_value=0)

        call_count = 0

        def locator_side_effect(selector):
            nonlocal call_count
            if "consent" in selector or "gdpr" in selector:
                call_count += 1
                if call_count == 1:
                    return checkbox_locator
                return no_match_locator
            return no_match_locator

        page.locator = MagicMock(side_effect=locator_side_effect)

        await filler._auto_check_gdpr(page)
        checkbox.check.assert_not_awaited()


# ---------------------------------------------------------------------------
# Generic progressive detection
# ---------------------------------------------------------------------------


class TestGenericDetection:
    @pytest.mark.asyncio
    async def test_single_form_returned(self):
        filler = GenericFiller()
        page = AsyncMock()

        form = AsyncMock()
        forms_locator = AsyncMock()
        forms_locator.count = AsyncMock(return_value=1)
        forms_locator.first = form

        page.locator = MagicMock(return_value=forms_locator)

        result = await filler._find_application_form(page)
        assert result is form

    @pytest.mark.asyncio
    async def test_no_forms_returns_none(self):
        filler = GenericFiller()
        page = AsyncMock()

        forms_locator = AsyncMock()
        forms_locator.count = AsyncMock(return_value=0)

        page.locator = MagicMock(return_value=forms_locator)

        result = await filler._find_application_form(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_form_with_file_input_preferred(self):
        filler = GenericFiller()
        page = AsyncMock()

        # Form 0: no file input
        form0 = AsyncMock()
        form0_files = AsyncMock()
        form0_files.count = AsyncMock(return_value=0)
        form0.locator = MagicMock(return_value=form0_files)

        # Form 1: has file input
        form1 = AsyncMock()
        form1_files = AsyncMock()
        form1_files.count = AsyncMock(return_value=1)
        form1.locator = MagicMock(return_value=form1_files)

        forms_locator = AsyncMock()
        forms_locator.count = AsyncMock(return_value=2)
        forms_locator.first = form0
        forms_locator.nth = MagicMock(
            side_effect=lambda i: [form0, form1][i]
        )

        page.locator = MagicMock(return_value=forms_locator)

        result = await filler._find_application_form(page)
        assert result is form1


# ---------------------------------------------------------------------------
# Ashby multi-step scan
# ---------------------------------------------------------------------------


class TestAshbyMultiStep:
    @pytest.mark.asyncio
    async def test_multi_step_collects_all_pages(self):
        filler = AshbyFiller()
        page = AsyncMock()
        profile = SimpleNamespace()

        step_count = 0

        async def mock_has_next(p):
            nonlocal step_count
            step_count += 1
            return step_count < 3  # 3 steps total

        # Mock classify_fields to return one unknown per page
        async def mock_classify(p, prof, page_number=1):
            from app.playwright_submit.form_filler import UnknownFieldInfo
            return [], [
                UnknownFieldInfo(
                    label=f"Question {page_number}",
                    field_type="text",
                    page_number=page_number,
                )
            ]

        with patch.object(filler, "_has_next_button", side_effect=mock_has_next), \
             patch.object(filler, "_click_next", return_value=True), \
             patch("app.playwright_submit.fillers.ashby.classify_fields", side_effect=mock_classify):
            known, unknown = await filler.scan_all_pages(page, profile)

        assert len(unknown) == 3
        assert [u.page_number for u in unknown] == [1, 2, 3]


# ---------------------------------------------------------------------------
# detect_success
# ---------------------------------------------------------------------------


class TestDetectSuccess:
    @pytest.mark.asyncio
    async def test_thank_you_detected(self):
        for FillerCls in [GreenhouseFiller, LeverFiller, AshbyFiller, GenericFiller]:
            filler = FillerCls()
            page = AsyncMock()
            body = AsyncMock()
            body.inner_text = AsyncMock(return_value="Thank you for applying!")
            page.locator = MagicMock(return_value=body)

            result = await filler.detect_success(page)
            assert result is True, f"{FillerCls.ats_name} failed to detect success"

    @pytest.mark.asyncio
    async def test_no_success_indicator(self):
        for FillerCls in [GreenhouseFiller, LeverFiller, AshbyFiller]:
            filler = FillerCls()
            page = AsyncMock()
            body = AsyncMock()
            body.inner_text = AsyncMock(return_value="Please fill in all fields.")
            page.locator = MagicMock(return_value=body)

            result = await filler.detect_success(page)
            assert result is False

    @pytest.mark.asyncio
    async def test_generic_url_success(self):
        filler = GenericFiller()
        page = AsyncMock()
        body = AsyncMock()
        body.inner_text = AsyncMock(return_value="Some page content")
        page.locator = MagicMock(return_value=body)
        page.url = "https://example.com/thank-you"

        result = await filler.detect_success(page)
        assert result is True


# ---------------------------------------------------------------------------
# ATS names
# ---------------------------------------------------------------------------


class TestATSNames:
    def test_ats_names(self):
        assert GreenhouseFiller.ats_name == "greenhouse"
        assert LeverFiller.ats_name == "lever"
        assert AshbyFiller.ats_name == "ashby"
        assert GenericFiller.ats_name == "generic"
