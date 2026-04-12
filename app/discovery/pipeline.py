"""Discovery pipeline: fetch, dedup, score, persist.

``run_discovery`` is the main pipeline stage called by
``SchedulerService._execute_pipeline``.  It orchestrates:

1. Load enabled sources and user keywords from Settings
2. Fetch from all sources in parallel via ``asyncio.gather``
3. Dedup each job by fingerprint (skip if already in DB)
4. Score against keywords and assign status (matched/discovered)
5. Persist new jobs and per-source run stats
6. Check for anomalies (today < 20% of 7-day rolling average)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import structlog

from app.discovery.fetchers import fetch_source
from app.discovery.scoring import job_fingerprint, score_job
from app.discovery.service import (
    get_enabled_sources,
    get_job_by_fingerprint,
    get_rolling_average,
    save_discovery_stats,
    update_source_fetch_status,
)
from app.discovery.models import Job
from app.runs.context import RunContext
from app.settings.service import get_settings_row

log = structlog.get_logger(__name__)


def _parse_posted_date(raw: Any) -> datetime | None:
    """Parse a posted-date string into a datetime, or return None."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        # Handle ISO-8601 strings from ATS APIs (e.g. "2026-03-15T12:00:00Z")
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def _fetch_one_source(
    client: httpx.AsyncClient,
    source_type: str,
    slug: str,
) -> list[dict]:
    """Fetch jobs from one source.  Wrapper for gather error isolation."""
    return await fetch_source(client, source_type, slug)


async def run_discovery(ctx: RunContext, session_factory: Any) -> dict:
    """Execute the discovery pipeline stage.

    Returns a counts dict:
    ``{"discovered": N, "new": K, "matched": M, "anomalies": [...]}``
    """
    # ── 1. Load sources and keywords ────────────────────────────────
    async with session_factory() as session:
        sources = await get_enabled_sources(session)
        settings = await get_settings_row(session)
        keywords = [k.strip() for k in (settings.keywords_csv or "").split("|") if k.strip()]
        threshold = settings.match_threshold

    if not sources:
        log.info("discovery_skipped", reason="no enabled sources", run_id=ctx.run_id)
        return {"discovered": 0, "new": 0, "matched": 0, "anomalies": []}

    # ── 2. Fetch from all sources in parallel ───────────────────────
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            _fetch_one_source(client, s.source_type, s.slug)
            for s in sources
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results per source
    source_jobs: dict[int, list[dict]] = {}  # source.id -> jobs
    source_errors: dict[int, str] = {}       # source.id -> error msg

    for source, result in zip(sources, results):
        if isinstance(result, BaseException):
            error_msg = f"{type(result).__name__}: {result}"
            source_errors[source.id] = error_msg
            log.warning(
                "source_fetch_failed",
                source_id=source.id,
                slug=source.slug,
                source_type=source.source_type,
                error=error_msg,
                run_id=ctx.run_id,
            )
        else:
            # Tag each job dict with source_id
            for j in result:
                j["source_id"] = source.id
            source_jobs[source.id] = result
            log.info(
                "source_fetched",
                source_id=source.id,
                slug=source.slug,
                count=len(result),
                run_id=ctx.run_id,
            )

    # Update source fetch statuses
    async with session_factory() as session:
        for source in sources:
            if source.id in source_errors:
                await update_source_fetch_status(
                    session, source.id, "error", source_errors[source.id],
                )
            elif source.id in source_jobs:
                await update_source_fetch_status(session, source.id, "ok")

    # ── 3. Dedup + score + persist ──────────────────────────────────
    total_discovered = 0
    total_new = 0
    total_matched = 0
    per_source_discovered: dict[int, int] = {}
    per_source_matched: dict[int, int] = {}

    async with session_factory() as session:
        for source_id, jobs_data in source_jobs.items():
            src_discovered = 0
            src_matched = 0

            for job_data in jobs_data:
                total_discovered += 1
                src_discovered += 1

                # Compute fingerprint
                company = job_data.get("company", "")
                fp = job_fingerprint(
                    job_data.get("url", ""),
                    job_data.get("title", ""),
                    company,
                )

                # Dedup check
                existing = await get_job_by_fingerprint(session, fp)
                if existing is not None:
                    continue

                # Score against keywords
                description = job_data.get("description", "")
                score, matched_kw, _unmatched_kw = score_job(description, keywords)

                # Determine status
                status = "matched" if score >= threshold else "discovered"
                if status == "matched":
                    total_matched += 1
                    src_matched += 1

                # Persist job
                job = Job(
                    fingerprint=fp,
                    external_id=job_data.get("external_id", ""),
                    title=job_data.get("title", ""),
                    company=company,
                    location=job_data.get("location", ""),
                    description=description,
                    description_html=job_data.get("description_html", ""),
                    url=job_data.get("url", ""),
                    source=job_data.get("source", ""),
                    source_id=source_id,
                    posted_date=_parse_posted_date(job_data.get("posted_date")),
                    score=score,
                    matched_keywords="|".join(matched_kw),
                    status=status,
                    run_id=ctx.run_id,
                )
                session.add(job)
                total_new += 1

            per_source_discovered[source_id] = src_discovered
            per_source_matched[source_id] = src_matched

        await session.commit()

    # ── 4. Save per-source stats ────────────────────────────────────
    async with session_factory() as session:
        for source in sources:
            sid = source.id
            error = source_errors.get(sid)
            await save_discovery_stats(
                session,
                run_id=ctx.run_id,
                source_id=sid,
                discovered=per_source_discovered.get(sid, 0),
                matched=per_source_matched.get(sid, 0),
                error=error,
            )

    # ── 5. Anomaly detection ────────────────────────────────────────
    anomalies: list[dict] = []
    async with session_factory() as session:
        for source in sources:
            sid = source.id
            if sid in source_errors:
                continue  # Don't flag anomaly on errored source
            today_count = per_source_discovered.get(sid, 0)
            rolling_avg = await get_rolling_average(session, sid)
            if rolling_avg is not None and today_count < rolling_avg * 0.20:
                anomalies.append({
                    "source_id": sid,
                    "slug": source.slug,
                    "today_count": today_count,
                    "rolling_avg": round(rolling_avg, 1),
                })
                log.warning(
                    "anomaly_detected",
                    source_id=sid,
                    slug=source.slug,
                    today_count=today_count,
                    rolling_avg=round(rolling_avg, 1),
                    run_id=ctx.run_id,
                )

    counts = {
        "discovered": total_discovered,
        "new": total_new,
        "matched": total_matched,
        "anomalies": anomalies,
    }

    log.info("discovery_complete", run_id=ctx.run_id, **{
        k: v for k, v in counts.items() if k != "anomalies"
    }, anomaly_count=len(anomalies))

    return counts


__all__ = ["run_discovery"]
