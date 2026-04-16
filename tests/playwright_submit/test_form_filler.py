"""Tests for form_filler label heuristics and field classification (06-03)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.playwright_submit.form_filler import (
    KnownField,
    LABEL_HEURISTICS,
    UnknownFieldInfo,
    classify_fields,
    fill_known_fields,
    get_profile_value,
    match_field_to_profile,
    try_select_with_fallback,
)


# ---------------------------------------------------------------------------
# match_field_to_profile
# ---------------------------------------------------------------------------


class TestMatchFieldToProfile:
    def test_first_name(self):
        result = match_field_to_profile("First Name")
        assert result == ("first_name", "text")

    def test_last_name(self):
        result = match_field_to_profile("Last Name")
        assert result == ("last_name", "text")

    def test_full_name(self):
        result = match_field_to_profile("Full Name")
        assert result == ("full_name", "text")

    def test_generic_name_fallback(self):
        result = match_field_to_profile("Name")
        assert result == ("full_name", "text")

    def test_email(self):
        result = match_field_to_profile("Email Address")
        assert result == ("email", "text")

    def test_email_hyphenated(self):
        result = match_field_to_profile("E-mail")
        assert result == ("email", "text")

    def test_phone(self):
        result = match_field_to_profile("Phone Number")
        assert result == ("phone", "text")

    def test_mobile(self):
        result = match_field_to_profile("Mobile")
        assert result == ("phone", "text")

    def test_linkedin(self):
        result = match_field_to_profile("LinkedIn URL")
        assert result == ("linkedin_url", "text")

    def test_github(self):
        result = match_field_to_profile("GitHub Profile")
        assert result == ("github_url", "text")

    def test_portfolio(self):
        result = match_field_to_profile("Portfolio")
        assert result == ("portfolio_url", "text")

    def test_personal_site(self):
        result = match_field_to_profile("Personal Site")
        assert result == ("portfolio_url", "text")

    def test_website(self):
        result = match_field_to_profile("Website")
        assert result == ("portfolio_url", "text")

    def test_resume_upload(self):
        result = match_field_to_profile("Resume")
        assert result == ("resume", "upload")

    def test_cv_upload(self):
        result = match_field_to_profile("Upload your CV")
        assert result == ("resume", "upload")

    def test_cover_letter_upload(self):
        result = match_field_to_profile("Cover Letter")
        assert result == ("cover_letter", "upload")

    def test_work_authorization(self):
        result = match_field_to_profile("Work Authorization")
        assert result == ("work_authorization", "select_or_fill")

    def test_legally_authorized(self):
        result = match_field_to_profile("Are you legally authorized to work?")
        assert result == ("work_authorization", "select_or_fill")

    def test_sponsorship(self):
        result = match_field_to_profile("Sponsorship required?")
        assert result == ("work_authorization", "select_or_fill")

    def test_salary(self):
        result = match_field_to_profile("Salary Expectations")
        assert result == ("salary_expectation", "text")

    def test_compensation(self):
        result = match_field_to_profile("Desired compensation")
        assert result == ("salary_expectation", "text")

    def test_years_experience(self):
        result = match_field_to_profile("Years of Experience")
        assert result == ("years_experience", "text")

    def test_experience_alone(self):
        result = match_field_to_profile("Experience level")
        assert result == ("years_experience", "text")

    def test_location(self):
        result = match_field_to_profile("Location")
        assert result == ("address", "text")

    def test_city(self):
        result = match_field_to_profile("City")
        assert result == ("address", "text")

    def test_address(self):
        result = match_field_to_profile("Street Address")
        assert result == ("address", "text")

    def test_no_match(self):
        result = match_field_to_profile("How did you hear about us?")
        assert result is None

    def test_empty_label(self):
        assert match_field_to_profile("") is None

    def test_none_label(self):
        assert match_field_to_profile(None) is None

    def test_case_insensitive(self):
        result = match_field_to_profile("FIRST NAME")
        assert result == ("first_name", "text")


class TestPriorityOrdering:
    """First Name should match before generic Name."""

    def test_first_name_before_name(self):
        result = match_field_to_profile("First Name")
        assert result[0] == "first_name"

    def test_last_name_before_name(self):
        result = match_field_to_profile("Last Name")
        assert result[0] == "last_name"

    def test_full_name_before_name(self):
        result = match_field_to_profile("Full Name")
        assert result[0] == "full_name"

    def test_resume_matches_upload_not_text(self):
        result = match_field_to_profile("Resume/CV")
        assert result[1] == "upload"


# ---------------------------------------------------------------------------
# get_profile_value
# ---------------------------------------------------------------------------


class TestGetProfileValue:
    def _profile(self, **kw):
        return SimpleNamespace(**kw)

    def test_direct_field(self):
        p = self._profile(email="test@example.com")
        assert get_profile_value(p, "email") == "test@example.com"

    def test_first_name_from_full(self):
        p = self._profile(full_name="John Doe")
        assert get_profile_value(p, "first_name") == "John"

    def test_last_name_from_full(self):
        p = self._profile(full_name="John Doe")
        assert get_profile_value(p, "last_name") == "Doe"

    def test_last_name_multi_part(self):
        p = self._profile(full_name="Mary Jane Watson")
        assert get_profile_value(p, "last_name") == "Jane Watson"

    def test_first_name_single_word(self):
        p = self._profile(full_name="Madonna")
        assert get_profile_value(p, "first_name") == "Madonna"

    def test_last_name_single_word_none(self):
        p = self._profile(full_name="Madonna")
        assert get_profile_value(p, "last_name") is None

    def test_missing_field_none(self):
        p = self._profile()
        assert get_profile_value(p, "phone") is None

    def test_empty_string_none(self):
        p = self._profile(phone="")
        assert get_profile_value(p, "phone") is None

    def test_int_to_string(self):
        p = self._profile(years_experience=5)
        assert get_profile_value(p, "years_experience") == "5"

    def test_full_name_empty_string(self):
        p = self._profile(full_name="")
        assert get_profile_value(p, "first_name") is None

    def test_full_name_none(self):
        p = self._profile(full_name=None)
        assert get_profile_value(p, "first_name") is None


# ---------------------------------------------------------------------------
# classify_fields — mocked Playwright page
# ---------------------------------------------------------------------------


def _make_mock_element(
    *,
    tag="INPUT",
    input_type="text",
    elem_id="",
    name="",
    label_text="",
    aria_label=None,
    placeholder=None,
    required=False,
    options=None,
):
    """Create a mock Playwright element locator."""
    el = AsyncMock()
    el.get_attribute = AsyncMock(
        side_effect=lambda attr: {
            "id": elem_id or None,
            "name": name or None,
            "type": input_type,
            "aria-label": aria_label,
            "placeholder": placeholder,
            "required": "" if required else None,
            "aria-required": None,
        }.get(attr)
    )
    el.evaluate = AsyncMock(
        side_effect=lambda expr: {
            "el => el.tagName": tag,
        }.get(expr, "")
    )
    return el, label_text, elem_id, name


def _make_mock_page(elements: list):
    """Build a mock page with locator() returning mock elements.

    Each element is a tuple from _make_mock_element.
    """
    page = AsyncMock()

    # We need to track which elements are input, select, textarea
    input_elements = []
    select_elements = []
    textarea_elements = []

    for el, label_text, elem_id, name_attr in elements:
        tag = None
        # Peek at what tag this is by calling evaluate synchronously
        # Actually, let's use a different approach — tag stored on element
        # We'll just put all non-select/textarea in input
        input_elements.append((el, label_text, elem_id, name_attr))

    def make_locator_mock(elems):
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=len(elems))

        def nth_fn(i):
            return elems[i][0] if i < len(elems) else AsyncMock()

        loc.nth = nth_fn
        return loc

    # For the label lookup
    def locator_side_effect(selector):
        # Handle label[for="..."]
        if selector.startswith("label[for="):
            label_loc = AsyncMock()
            # Find matching element
            for el, label_text, elem_id, _ in elements:
                target_id = selector.split('"')[1]
                if elem_id == target_id and label_text:
                    label_loc.count = AsyncMock(return_value=1)
                    first = AsyncMock()
                    first.inner_text = AsyncMock(return_value=label_text)
                    label_loc.first = first
                    return label_loc
            label_loc.count = AsyncMock(return_value=0)
            return label_loc

        # Handle ancestor::label xpath
        if "ancestor::label" in selector:
            anc = AsyncMock()
            anc.count = AsyncMock(return_value=0)
            return anc

        # Handle input:visible, select:visible, textarea:visible
        if selector == "input:visible":
            return make_locator_mock(input_elements)
        elif selector == "select:visible":
            return make_locator_mock([])
        elif selector == "textarea:visible":
            return make_locator_mock([])

        return make_locator_mock([])

    page.locator = MagicMock(side_effect=locator_side_effect)

    # Also need element.locator for ancestor xpath
    for el, _, _, _ in elements:
        anc_loc = AsyncMock()
        anc_loc.count = AsyncMock(return_value=0)
        el.locator = MagicMock(return_value=anc_loc)

    return page


class TestClassifyFields:
    @pytest.mark.asyncio
    async def test_known_field_classified(self):
        el, *rest = _make_mock_element(
            elem_id="email_field",
            label_text="Email",
            input_type="text",
        )
        page = _make_mock_page([(el, *rest)])
        profile = SimpleNamespace(email="test@example.com")

        known, unknown = await classify_fields(page, profile)

        assert len(known) == 1
        assert known[0].profile_field == "email"
        assert known[0].value == "test@example.com"

    @pytest.mark.asyncio
    async def test_unknown_field_classified(self):
        el, *rest = _make_mock_element(
            elem_id="custom_q",
            label_text="How did you hear about us?",
            input_type="text",
        )
        page = _make_mock_page([(el, *rest)])
        profile = SimpleNamespace()

        known, unknown = await classify_fields(page, profile)

        assert len(known) == 0
        assert len(unknown) == 1
        assert unknown[0].label == "How did you hear about us?"

    @pytest.mark.asyncio
    async def test_hidden_fields_skipped(self):
        el, *rest = _make_mock_element(
            elem_id="token",
            label_text="",
            input_type="hidden",
        )
        page = _make_mock_page([(el, *rest)])
        profile = SimpleNamespace()

        known, unknown = await classify_fields(page, profile)

        assert len(known) == 0
        assert len(unknown) == 0

    @pytest.mark.asyncio
    async def test_upload_field_no_profile_value_needed(self):
        el, *rest = _make_mock_element(
            elem_id="resume_upload",
            label_text="Resume",
            input_type="file",
        )
        page = _make_mock_page([(el, *rest)])
        profile = SimpleNamespace()

        known, unknown = await classify_fields(page, profile)

        assert len(known) == 1
        assert known[0].input_method == "upload"
        assert known[0].profile_field == "resume"

    @pytest.mark.asyncio
    async def test_required_field_detected(self):
        el, *rest = _make_mock_element(
            elem_id="misc",
            label_text="Preferred pronouns",
            input_type="text",
            required=True,
        )
        page = _make_mock_page([(el, *rest)])
        profile = SimpleNamespace()

        known, unknown = await classify_fields(page, profile)

        assert len(unknown) == 1
        assert unknown[0].is_required is True

    @pytest.mark.asyncio
    async def test_page_number_propagated(self):
        el, *rest = _make_mock_element(
            elem_id="q1",
            label_text="Custom question",
            input_type="text",
        )
        page = _make_mock_page([(el, *rest)])
        profile = SimpleNamespace()

        known, unknown = await classify_fields(page, profile, page_number=3)

        assert unknown[0].page_number == 3


# ---------------------------------------------------------------------------
# fill_known_fields
# ---------------------------------------------------------------------------


class TestFillKnownFields:
    @pytest.mark.asyncio
    async def test_text_fill(self):
        locator = AsyncMock()
        kf = KnownField(
            label="Email",
            profile_field="email",
            value="test@example.com",
            input_method="text",
            locator=locator,
        )
        await fill_known_fields(AsyncMock(), [kf])
        locator.fill.assert_awaited_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_upload_resume(self):
        locator = AsyncMock()
        kf = KnownField(
            label="Resume",
            profile_field="resume",
            value="",
            input_method="upload",
            locator=locator,
        )
        await fill_known_fields(
            AsyncMock(), [kf], resume_path="/tmp/resume.pdf"
        )
        locator.set_input_files.assert_awaited_once_with("/tmp/resume.pdf")

    @pytest.mark.asyncio
    async def test_upload_cover_letter(self):
        locator = AsyncMock()
        kf = KnownField(
            label="Cover Letter",
            profile_field="cover_letter",
            value="",
            input_method="upload",
            locator=locator,
        )
        await fill_known_fields(
            AsyncMock(), [kf], cover_letter_path="/tmp/cover.pdf"
        )
        locator.set_input_files.assert_awaited_once_with("/tmp/cover.pdf")

    @pytest.mark.asyncio
    async def test_upload_no_file_path_warns(self):
        locator = AsyncMock()
        kf = KnownField(
            label="Resume",
            profile_field="resume",
            value="",
            input_method="upload",
            locator=locator,
        )
        await fill_known_fields(AsyncMock(), [kf])
        locator.set_input_files.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_select_or_fill_select(self):
        locator = AsyncMock()
        locator.evaluate = AsyncMock(return_value="SELECT")
        locator.select_option = AsyncMock()
        kf = KnownField(
            label="Work Auth",
            profile_field="work_authorization",
            value="Yes",
            input_method="select_or_fill",
            locator=locator,
        )
        await fill_known_fields(AsyncMock(), [kf])
        locator.select_option.assert_awaited()

    @pytest.mark.asyncio
    async def test_select_or_fill_fallback_to_text(self):
        locator = AsyncMock()
        locator.evaluate = AsyncMock(return_value="INPUT")
        kf = KnownField(
            label="Work Auth",
            profile_field="work_authorization",
            value="Yes",
            input_method="select_or_fill",
            locator=locator,
        )
        await fill_known_fields(AsyncMock(), [kf])
        locator.fill.assert_awaited_once_with("Yes")


# ---------------------------------------------------------------------------
# try_select_with_fallback
# ---------------------------------------------------------------------------


class TestTrySelectWithFallback:
    @pytest.mark.asyncio
    async def test_exact_match(self):
        locator = AsyncMock()
        locator.select_option = AsyncMock()
        result = await try_select_with_fallback(locator, "Yes")
        assert result is True
        locator.select_option.assert_awaited_once_with(label="Yes")

    @pytest.mark.asyncio
    async def test_fallback_substring(self):
        locator = AsyncMock()
        # First call (exact match) raises, second call (fallback) succeeds
        locator.select_option = AsyncMock(
            side_effect=[Exception("no exact"), None]
        )
        locator.evaluate = AsyncMock(
            return_value=["Select...", "Yes, I am authorized", "No"]
        )

        result = await try_select_with_fallback(locator, "yes")
        assert result is True

    @pytest.mark.asyncio
    async def test_no_match(self):
        locator = AsyncMock()
        locator.select_option = AsyncMock(side_effect=Exception("no match"))
        locator.evaluate = AsyncMock(return_value=["Option A", "Option B"])

        result = await try_select_with_fallback(locator, "xyz")
        assert result is False
