"""Tests for app.learning.service — SavedAnswer CRUD + UnknownField persistence."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.models import SavedAnswer, UnknownField
from app.learning.service import (
    create_unknown_fields,
    delete_saved_answer,
    get_all_saved_answers,
    get_saved_answer,
    get_unknown_fields_for_job,
    increment_reuse_count,
    resolve_all_for_job,
    resolve_unknown_field,
    save_answer,
    update_saved_answer,
)


# =========================================================================
# Helper to seed a Job row (UnknownField has FK → jobs.id)
# =========================================================================

async def _create_job(session: AsyncSession, job_id: int = 1) -> int:
    """Insert a minimal Job row and return its id."""
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


# =========================================================================
# SavedAnswer CRUD
# =========================================================================


class TestSaveAnswer:
    """save_answer creates or upserts by normalised label."""

    @pytest.mark.asyncio
    async def test_create_new_answer(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "First Name", "Alice")
        assert sa.id is not None
        assert sa.field_label == "First Name"
        assert sa.field_label_normalized == "first name"
        assert sa.answer_text == "Alice"
        assert sa.answer_type == "text"
        assert sa.times_reused == 0

    @pytest.mark.asyncio
    async def test_upsert_existing_answer(self, async_session: AsyncSession):
        sa1 = await save_answer(async_session, "First Name", "Alice")
        sa2 = await save_answer(async_session, "first  name", "Bob")
        assert sa1.id == sa2.id
        assert sa2.answer_text == "Bob"

    @pytest.mark.asyncio
    async def test_create_with_type_and_source(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        sa = await save_answer(
            async_session,
            "Gender",
            "Male",
            answer_type="select",
            source_job_id=job_id,
        )
        assert sa.answer_type == "select"
        assert sa.source_job_id == job_id


class TestGetAllSavedAnswers:
    """get_all_saved_answers returns answers ordered by reuse then recency."""

    @pytest.mark.asyncio
    async def test_ordering(self, async_session: AsyncSession):
        sa1 = await save_answer(async_session, "A", "val-a")
        sa2 = await save_answer(async_session, "B", "val-b")
        # Bump reuse on sa2 so it sorts first
        await increment_reuse_count(async_session, sa2.id)
        answers = await get_all_saved_answers(async_session)
        assert len(answers) == 2
        assert answers[0].id == sa2.id

    @pytest.mark.asyncio
    async def test_empty(self, async_session: AsyncSession):
        answers = await get_all_saved_answers(async_session)
        assert answers == []


class TestDeleteSavedAnswer:
    @pytest.mark.asyncio
    async def test_delete_existing(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "X", "val")
        assert await delete_saved_answer(async_session, sa.id) is True
        assert await get_saved_answer(async_session, sa.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, async_session: AsyncSession):
        assert await delete_saved_answer(async_session, 999) is False


class TestUpdateSavedAnswer:
    @pytest.mark.asyncio
    async def test_update_text(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "City", "NYC")
        updated = await update_saved_answer(async_session, sa.id, "LA")
        assert updated is not None
        assert updated.answer_text == "LA"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, async_session: AsyncSession):
        assert await update_saved_answer(async_session, 999, "x") is None


class TestIncrementReuseCount:
    @pytest.mark.asyncio
    async def test_increment(self, async_session: AsyncSession):
        sa = await save_answer(async_session, "Zip", "10001")
        assert sa.times_reused == 0
        await increment_reuse_count(async_session, sa.id)
        refreshed = await get_saved_answer(async_session, sa.id)
        assert refreshed.times_reused == 1


# =========================================================================
# UnknownField persistence
# =========================================================================


class TestCreateUnknownFields:
    @pytest.mark.asyncio
    async def test_bulk_create(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        fields = [
            {"field_label": "Visa Status", "field_type": "select", "is_required": True},
            {"field_label": "Start Date", "field_type": "text"},
        ]
        created = await create_unknown_fields(async_session, job_id, fields)
        assert len(created) == 2
        assert created[0].job_id == job_id
        assert created[0].field_label == "Visa Status"
        assert created[0].is_required is True

    @pytest.mark.asyncio
    async def test_dedup_by_label(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        fields = [{"field_label": "X"}, {"field_label": "X"}]
        created = await create_unknown_fields(async_session, job_id, fields)
        assert len(created) == 1

    @pytest.mark.asyncio
    async def test_dedup_across_calls(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        await create_unknown_fields(async_session, job_id, [{"field_label": "X"}])
        second = await create_unknown_fields(async_session, job_id, [{"field_label": "X"}])
        assert len(second) == 0


class TestGetUnknownFieldsForJob:
    @pytest.mark.asyncio
    async def test_returns_unresolved_only(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        fields = [
            {"field_label": "A", "page_number": 2},
            {"field_label": "B", "page_number": 1},
        ]
        created = await create_unknown_fields(async_session, job_id, fields)
        # Resolve one
        sa = await save_answer(async_session, "A", "answer-a")
        await resolve_unknown_field(async_session, created[0].id, sa.id)

        remaining = await get_unknown_fields_for_job(async_session, job_id)
        assert len(remaining) == 1
        assert remaining[0].field_label == "B"

    @pytest.mark.asyncio
    async def test_ordered_by_page_number(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        fields = [
            {"field_label": "P3", "page_number": 3},
            {"field_label": "P1", "page_number": 1},
            {"field_label": "P2", "page_number": 2},
        ]
        await create_unknown_fields(async_session, job_id, fields)
        result = await get_unknown_fields_for_job(async_session, job_id)
        pages = [f.page_number for f in result]
        assert pages == [1, 2, 3]


class TestResolveAllForJob:
    @pytest.mark.asyncio
    async def test_resolves_multiple(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        created = await create_unknown_fields(
            async_session, job_id,
            [{"field_label": "Q1"}, {"field_label": "Q2"}],
        )
        answers_map = {created[0].id: "A1", created[1].id: "A2"}
        saved = await resolve_all_for_job(async_session, job_id, answers_map)

        assert len(saved) == 2
        # All fields should now be resolved
        remaining = await get_unknown_fields_for_job(async_session, job_id)
        assert len(remaining) == 0
        # Saved answers should be retrievable
        all_answers = await get_all_saved_answers(async_session)
        assert len(all_answers) == 2

    @pytest.mark.asyncio
    async def test_skips_nonexistent_field(self, async_session: AsyncSession):
        job_id = await _create_job(async_session)
        saved = await resolve_all_for_job(async_session, job_id, {999: "nope"})
        assert saved == []
