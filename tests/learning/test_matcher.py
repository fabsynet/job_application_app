"""Tests for app.learning.matcher — LLM semantic matching for answer reuse."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.matcher import find_matching_answers, try_match_and_fill
from app.learning.models import SavedAnswer, UnknownField
from app.learning.service import (
    create_unknown_fields,
    get_saved_answer,
    save_answer,
)
from app.tailoring.provider import LLMResponse


# =========================================================================
# FakeLLMProvider — local test double (04-07 pattern, NOT shared fixture)
# =========================================================================


class FakeLLMProvider:
    """Scriptable mock that returns canned LLMResponse objects."""

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
            model="fake",
        )


# =========================================================================
# Helper
# =========================================================================

async def _create_job(session: AsyncSession, job_id: int = 1) -> int:
    from app.discovery.models import Job

    job = Job(
        id=job_id,
        fingerprint=f"fp-{job_id}",
        external_id=f"ext-{job_id}",
        source="test",
        company="TestCo",
        title="Test Engineer",
        url=f"https://example.com/jobs/{job_id}",
        status="needs_info",
    )
    session.add(job)
    await session.flush()
    return job.id


def _match_response(matches: dict) -> str:
    return json.dumps({"matches": matches})


# =========================================================================
# find_matching_answers
# =========================================================================


class TestFindMatchingAnswers:
    @pytest.mark.asyncio
    async def test_matched_labels(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "First Name", "Alice")
        provider = FakeLLMProvider([
            _match_response({"Full Name": sa.id})
        ])
        result = await find_matching_answers(
            ["Full Name"], [sa], provider
        )
        assert result["Full Name"] is not None
        assert result["Full Name"].id == sa.id

    @pytest.mark.asyncio
    async def test_unmatched_labels(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "First Name", "Alice")
        provider = FakeLLMProvider([
            _match_response({"Visa Status": None})
        ])
        result = await find_matching_answers(
            ["Visa Status"], [sa], provider
        )
        assert result["Visa Status"] is None

    @pytest.mark.asyncio
    async def test_empty_labels(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "X", "Y")
        provider = FakeLLMProvider([])
        result = await find_matching_answers([], [sa], provider)
        assert result == {}
        assert len(provider.calls) == 0  # No LLM call for empty input

    @pytest.mark.asyncio
    async def test_empty_saved_answers(self, async_session: AsyncSession):
        provider = FakeLLMProvider([])
        result = await find_matching_answers(["Name"], [], provider)
        assert result["Name"] is None
        assert len(provider.calls) == 0

    @pytest.mark.asyncio
    async def test_llm_failure_returns_all_none(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "First Name", "Alice")
        provider = FakeLLMProvider([RuntimeError("LLM down")])
        result = await find_matching_answers(
            ["Full Name"], [sa], provider
        )
        assert result["Full Name"] is None

    @pytest.mark.asyncio
    async def test_single_llm_call_for_batch(self, async_session: AsyncSession):
        sa1 = await save_answer(async_session, "First Name", "Alice")
        sa2 = await save_answer(async_session, "Email", "a@b.com")
        provider = FakeLLMProvider([
            _match_response({"Your Name": sa1.id, "Email Address": sa2.id})
        ])
        result = await find_matching_answers(
            ["Your Name", "Email Address"], [sa1, sa2], provider
        )
        assert len(provider.calls) == 1  # Single batched call
        assert result["Your Name"].id == sa1.id
        assert result["Email Address"].id == sa2.id

    @pytest.mark.asyncio
    async def test_handles_markdown_fenced_json(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "First Name", "Alice")
        fenced = f'```json\n{_match_response({"Name": sa.id})}\n```'
        provider = FakeLLMProvider([fenced])
        result = await find_matching_answers(
            ["Name"], [sa], provider
        )
        assert result["Name"].id == sa.id


# =========================================================================
# try_match_and_fill
# =========================================================================


class TestTryMatchAndFill:
    @pytest.mark.asyncio
    async def test_matched_fields_resolved(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        sa = await save_answer(async_session, "First Name", "Alice")
        created = await create_unknown_fields(
            async_session, job_id, [{"field_label": "Your Name"}]
        )
        infos = [{"field_id": created[0].id, "field_label": "Your Name"}]
        provider = FakeLLMProvider([
            _match_response({"Your Name": sa.id})
        ])

        matched, still_unknown = await try_match_and_fill(
            async_session, infos, [sa], provider
        )
        assert len(matched) == 1
        assert len(still_unknown) == 0
        assert matched[0]["matched_answer"].id == sa.id
        # Reuse count should be incremented
        refreshed = await get_saved_answer(async_session, sa.id)
        assert refreshed.times_reused == 1

    @pytest.mark.asyncio
    async def test_unmatched_stay_unknown(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        sa = await save_answer(async_session, "First Name", "Alice")
        created = await create_unknown_fields(
            async_session, job_id, [{"field_label": "Visa Status"}]
        )
        infos = [{"field_id": created[0].id, "field_label": "Visa Status"}]
        provider = FakeLLMProvider([
            _match_response({"Visa Status": None})
        ])

        matched, still_unknown = await try_match_and_fill(
            async_session, infos, [sa], provider
        )
        assert len(matched) == 0
        assert len(still_unknown) == 1

    @pytest.mark.asyncio
    async def test_empty_inputs(self, async_session: AsyncSession):
        provider = FakeLLMProvider([])
        matched, still_unknown = await try_match_and_fill(
            async_session, [], [], provider
        )
        assert matched == []
        assert still_unknown == []
