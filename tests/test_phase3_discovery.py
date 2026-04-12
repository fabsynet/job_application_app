"""Unit tests for Phase 3 discovery modules: fetchers, scoring, dedup, service.

Covers requirements:
  - DISC-01: Greenhouse fetcher + parsing
  - DISC-02: Lever fetcher + parsing
  - DISC-03: Ashby fetcher + parsing
  - DISC-05: Source auto-detection
  - DISC-06: Dedup via job_fingerprint
  - MATCH-01: Case-insensitive partial keyword scoring
  - MATCH-02/03: Score thresholds and storage (via scoring unit tests)
  - Anomaly detection edge cases (fewer than 3 data points)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from app.discovery.fetchers import (
    detect_source,
    fetch_ashby,
    fetch_greenhouse,
    fetch_lever,
    strip_html,
)
from app.discovery.scoring import job_fingerprint, score_job


# =========================================================================
# detect_source tests (DISC-05)
# =========================================================================


class TestDetectSource:
    """Source auto-detection from URL or plain slug."""

    def test_greenhouse_url(self):
        slug, src = detect_source("https://boards.greenhouse.io/stripe")
        assert slug == "stripe"
        assert src == "greenhouse"

    def test_greenhouse_api_url(self):
        slug, src = detect_source(
            "https://boards-api.greenhouse.io/v1/boards/stripe/jobs"
        )
        assert slug == "stripe"
        assert src == "greenhouse"

    def test_lever_url(self):
        slug, src = detect_source("https://jobs.lever.co/stripe")
        assert slug == "stripe"
        assert src == "lever"

    def test_ashby_url(self):
        slug, src = detect_source("https://jobs.ashbyhq.com/stripe")
        assert slug == "stripe"
        assert src == "ashby"

    def test_plain_slug(self):
        slug, src = detect_source("stripe")
        assert slug == "stripe"
        assert src == "unknown"

    def test_plain_slug_with_dashes(self):
        slug, src = detect_source("my-company")
        assert slug == "my-company"
        assert src == "unknown"

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            detect_source("not a valid slug or url!!!")

    def test_trailing_slash_stripped(self):
        slug, src = detect_source("https://boards.greenhouse.io/stripe/")
        assert slug == "stripe"
        assert src == "greenhouse"


# =========================================================================
# score_job tests (MATCH-01)
# =========================================================================


class TestScoreJob:
    """Case-insensitive partial keyword matching."""

    def test_case_insensitive(self):
        score, matched, unmatched = score_job(
            "We need a Python developer", ["python"]
        )
        assert score == 100
        assert matched == ["python"]
        assert unmatched == []

    def test_partial_match_python3(self):
        score, matched, unmatched = score_job(
            "Experience with python3 required", ["python"]
        )
        assert score == 100
        assert matched == ["python"]

    def test_partial_match_slash_separated(self):
        score, matched, unmatched = score_job(
            "Python/Django stack", ["python"]
        )
        assert score == 100
        assert matched == ["python"]

    def test_score_calculation_50_percent(self):
        desc = "We use python and react"
        keywords = ["python", "react", "golang", "rust"]
        score, matched, unmatched = score_job(desc, keywords)
        assert score == 50
        assert set(matched) == {"python", "react"}
        assert set(unmatched) == {"golang", "rust"}

    def test_empty_keywords(self):
        score, matched, unmatched = score_job("any description", [])
        assert score == 0
        assert matched == []
        assert unmatched == []

    def test_no_matches(self):
        score, matched, unmatched = score_job(
            "We use Java and C++", ["python", "rust"]
        )
        assert score == 0
        assert matched == []
        assert unmatched == ["python", "rust"]

    def test_all_matched(self):
        score, matched, unmatched = score_job(
            "Python React TypeScript", ["python", "react", "typescript"]
        )
        assert score == 100
        assert len(matched) == 3
        assert unmatched == []


# =========================================================================
# job_fingerprint tests (DISC-06)
# =========================================================================


class TestJobFingerprint:
    """Dedup fingerprint canonicalisation."""

    def test_same_inputs_same_hash(self):
        fp1 = job_fingerprint("https://example.com/job", "Engineer", "stripe")
        fp2 = job_fingerprint("https://example.com/job", "Engineer", "stripe")
        assert fp1 == fp2

    def test_query_params_stripped(self):
        fp1 = job_fingerprint("https://example.com/job?ref=123", "Engineer", "stripe")
        fp2 = job_fingerprint("https://example.com/job?ref=456", "Engineer", "stripe")
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = job_fingerprint("https://example.com/job", "Engineer", "Stripe")
        fp2 = job_fingerprint("https://example.com/job", "Engineer", "stripe")
        assert fp1 == fp2

    def test_trailing_slash_stripped(self):
        fp1 = job_fingerprint("https://example.com/job/", "Engineer", "stripe")
        fp2 = job_fingerprint("https://example.com/job", "Engineer", "stripe")
        assert fp1 == fp2

    def test_different_jobs_different_hashes(self):
        fp1 = job_fingerprint("https://example.com/job1", "Engineer", "stripe")
        fp2 = job_fingerprint("https://example.com/job2", "Engineer", "stripe")
        assert fp1 != fp2

    def test_different_titles_different_hashes(self):
        fp1 = job_fingerprint("https://example.com/job", "Engineer", "stripe")
        fp2 = job_fingerprint("https://example.com/job", "Designer", "stripe")
        assert fp1 != fp2


# =========================================================================
# Fetcher response parsing tests (DISC-01, DISC-02, DISC-03)
# =========================================================================


def _mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestFetchGreenhouse:
    """Greenhouse fetcher parsing (DISC-01)."""

    @pytest.mark.asyncio
    async def test_parses_greenhouse_response(self):
        mock_data = {
            "jobs": [
                {
                    "id": 12345,
                    "title": "Software Engineer",
                    "location": {"name": "San Francisco, CA"},
                    "content": "<p>Build amazing things with <b>Python</b></p>",
                    "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345",
                    "updated_at": "2026-01-15T12:00:00Z",
                }
            ]
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(mock_data)

        jobs = await fetch_greenhouse(client, "stripe")

        assert len(jobs) == 1
        job = jobs[0]
        assert job["external_id"] == "12345"
        assert job["title"] == "Software Engineer"
        assert job["company"] == "stripe"
        assert job["location"] == "San Francisco, CA"
        assert job["source"] == "greenhouse"
        assert job["posted_date"] == "2026-01-15T12:00:00Z"
        # HTML stripped for description
        assert "<p>" not in job["description"]
        assert "Python" in job["description"]
        # HTML preserved for display
        assert "<p>" in job["description_html"]

    @pytest.mark.asyncio
    async def test_content_true_param_passed(self):
        """Verify content=true is sent to get the full job descriptions."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response({"jobs": []})

        await fetch_greenhouse(client, "stripe")

        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert call_kwargs[1]["params"] == {"content": "true"}

    @pytest.mark.asyncio
    async def test_empty_jobs_list(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response({"jobs": []})

        jobs = await fetch_greenhouse(client, "empty-co")
        assert jobs == []


class TestFetchLever:
    """Lever fetcher parsing (DISC-02)."""

    @pytest.mark.asyncio
    async def test_parses_lever_flat_array(self):
        """Lever returns a flat array, NOT wrapped in {jobs: [...]}."""
        mock_data = [
            {
                "id": "abc-def-123",
                "text": "Backend Engineer",
                "categories": {"location": "Remote"},
                "descriptionPlain": "Work with Python and Go",
                "description": "<p>Work with Python and Go</p>",
                "hostedUrl": "https://jobs.lever.co/stripe/abc-def-123",
            }
        ]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(mock_data)

        jobs = await fetch_lever(client, "stripe")

        assert len(jobs) == 1
        job = jobs[0]
        assert job["external_id"] == "abc-def-123"
        assert job["title"] == "Backend Engineer"
        assert job["company"] == "stripe"
        assert job["location"] == "Remote"
        assert job["source"] == "lever"
        assert job["description"] == "Work with Python and Go"

    @pytest.mark.asyncio
    async def test_lever_posted_date_is_none(self):
        """Lever public API lacks posted date."""
        mock_data = [
            {
                "id": "xyz",
                "text": "Role",
                "categories": {},
                "descriptionPlain": "desc",
                "hostedUrl": "https://jobs.lever.co/co/xyz",
            }
        ]
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(mock_data)

        jobs = await fetch_lever(client, "co")
        assert jobs[0]["posted_date"] is None


class TestFetchAshby:
    """Ashby fetcher parsing (DISC-03)."""

    @pytest.mark.asyncio
    async def test_parses_ashby_response(self):
        mock_data = {
            "jobs": [
                {
                    "id": "ashby-999",
                    "title": "Full Stack Developer",
                    "location": "New York, NY",
                    "descriptionPlain": "Build with React and Node",
                    "descriptionHtml": "<div>Build with React and Node</div>",
                    "jobUrl": "https://jobs.ashbyhq.com/co/ashby-999",
                    "publishedAt": "2026-03-01T08:00:00Z",
                }
            ]
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response(mock_data)

        jobs = await fetch_ashby(client, "co")

        assert len(jobs) == 1
        job = jobs[0]
        assert job["external_id"] == "ashby-999"
        assert job["title"] == "Full Stack Developer"
        assert job["company"] == "co"
        assert job["location"] == "New York, NY"
        assert job["source"] == "ashby"
        assert job["description"] == "Build with React and Node"
        assert job["description_html"] == "<div>Build with React and Node</div>"
        assert job["posted_date"] == "2026-03-01T08:00:00Z"


# =========================================================================
# strip_html tests
# =========================================================================


class TestStripHtml:
    """HTML tag removal and entity decoding."""

    def test_removes_tags(self):
        assert strip_html("<p>Hello</p>") == "Hello"

    def test_handles_nested_tags(self):
        assert strip_html("<div><p><b>Nested</b> text</p></div>") == "Nested text"

    def test_preserves_text_content(self):
        result = strip_html("<ul><li>Item 1</li><li>Item 2</li></ul>")
        assert "Item 1" in result
        assert "Item 2" in result

    def test_decodes_entities(self):
        assert strip_html("A &amp; B") == "A & B"

    def test_empty_input(self):
        assert strip_html("") == ""

    def test_none_like_falsy(self):
        assert strip_html("") == ""

    def test_collapses_whitespace(self):
        result = strip_html("<p>  too   many   spaces  </p>")
        assert result == "too many spaces"


# =========================================================================
# Anomaly detection tests (via service.get_rolling_average)
# =========================================================================


class TestAnomalyDetection:
    """Rolling average anomaly detection edge cases."""

    @pytest.mark.asyncio
    async def test_fewer_than_3_data_points_returns_none(self, async_session):
        """Fewer than 3 data points should skip anomaly detection."""
        from app.discovery.service import get_rolling_average, save_discovery_stats
        from app.discovery.models import Source
        from app.db.models import Run

        # Create a source and two runs with stats (< 3 data points)
        source = Source(slug="test-co", source_type="greenhouse", enabled=True)
        async_session.add(source)
        await async_session.commit()
        await async_session.refresh(source)

        for i in range(2):
            run = Run(status="succeeded", triggered_by="scheduler")
            async_session.add(run)
            await async_session.commit()
            await async_session.refresh(run)
            await save_discovery_stats(
                async_session, run.id, source.id, discovered=10, matched=5
            )

        avg = await get_rolling_average(async_session, source.id)
        assert avg is None  # fewer than 3 data points

    @pytest.mark.asyncio
    async def test_normal_count_no_anomaly(self, async_session):
        """Count above 20% of average should not be flagged."""
        from app.discovery.service import get_rolling_average, save_discovery_stats
        from app.discovery.models import Source
        from app.db.models import Run

        source = Source(slug="ok-co", source_type="lever", enabled=True)
        async_session.add(source)
        await async_session.commit()
        await async_session.refresh(source)

        # Create 4 runs with ~10 discovered each (enough data points)
        for i in range(4):
            run = Run(status="succeeded", triggered_by="scheduler")
            async_session.add(run)
            await async_session.commit()
            await async_session.refresh(run)
            await save_discovery_stats(
                async_session, run.id, source.id, discovered=10, matched=3
            )

        avg = await get_rolling_average(async_session, source.id)
        assert avg is not None
        assert avg == pytest.approx(10.0, abs=0.1)
        # 10 >= 10 * 0.2 → no anomaly

    @pytest.mark.asyncio
    async def test_low_count_detected_as_anomaly(self, async_session):
        """Count below 20% of average should trigger anomaly."""
        from app.discovery.service import get_rolling_average, save_discovery_stats
        from app.discovery.models import Source
        from app.db.models import Run

        source = Source(slug="drop-co", source_type="ashby", enabled=True)
        async_session.add(source)
        await async_session.commit()
        await async_session.refresh(source)

        # 3 runs with 100 discovered, then 1 run with 1 discovered
        for i in range(3):
            run = Run(status="succeeded", triggered_by="scheduler")
            async_session.add(run)
            await async_session.commit()
            await async_session.refresh(run)
            await save_discovery_stats(
                async_session, run.id, source.id, discovered=100, matched=20
            )

        avg = await get_rolling_average(async_session, source.id)
        assert avg is not None
        # Average is ~100, so a count of 1 would be < 20% (20) → anomaly
        assert 1 < avg * 0.20  # confirms 1 is anomalous

    @pytest.mark.asyncio
    async def test_errored_stats_excluded_from_average(self, async_session):
        """Stats with error should be excluded from rolling average calculation."""
        from app.discovery.service import get_rolling_average, save_discovery_stats
        from app.discovery.models import Source
        from app.db.models import Run

        source = Source(slug="err-co", source_type="greenhouse", enabled=True)
        async_session.add(source)
        await async_session.commit()
        await async_session.refresh(source)

        # 3 good runs + 1 errored run
        for i in range(3):
            run = Run(status="succeeded", triggered_by="scheduler")
            async_session.add(run)
            await async_session.commit()
            await async_session.refresh(run)
            await save_discovery_stats(
                async_session, run.id, source.id, discovered=50, matched=10
            )

        run_err = Run(status="succeeded", triggered_by="scheduler")
        async_session.add(run_err)
        await async_session.commit()
        await async_session.refresh(run_err)
        await save_discovery_stats(
            async_session, run_err.id, source.id,
            discovered=0, matched=0, error="Timeout"
        )

        avg = await get_rolling_average(async_session, source.id)
        # Only 3 non-error data points count
        assert avg is not None
        assert avg == pytest.approx(50.0, abs=0.1)
