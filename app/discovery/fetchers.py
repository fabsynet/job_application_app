"""ATS source detection and validation.

STUB: This file is a minimal placeholder created by plan 03-03 so that
the sources router can import. Plan 03-02 will replace this with the
full implementation containing actual ATS API calls.
"""

from __future__ import annotations

import re


def detect_source(slug_or_url: str) -> tuple[str, str]:
    """Parse a URL or slug into (slug, source_type).

    Returns source_type as one of: greenhouse, lever, ashby, unknown.
    """
    slug_or_url = slug_or_url.strip().rstrip("/")

    # Greenhouse: https://boards.greenhouse.io/{slug} or https://job-boards.greenhouse.io/{slug}
    m = re.match(
        r"https?://(?:job-)?boards\.greenhouse\.io/([^/?#]+)", slug_or_url
    )
    if m:
        return m.group(1).lower(), "greenhouse"

    # Lever: https://jobs.lever.co/{slug}
    m = re.match(r"https?://jobs\.lever\.co/([^/?#]+)", slug_or_url)
    if m:
        return m.group(1).lower(), "lever"

    # Ashby: https://jobs.ashbyhq.com/{slug}
    m = re.match(r"https?://jobs\.ashbyhq\.com/([^/?#]+)", slug_or_url)
    if m:
        return m.group(1).lower(), "ashby"

    # Plain slug -- no URL detected
    slug = slug_or_url.lower().strip()
    return slug, "unknown"


async def validate_source(slug: str, source_type: str) -> tuple[bool, str]:
    """Validate that a source exists by hitting the real ATS API.

    STUB: Always returns (False, "stub -- 03-02 not yet deployed").
    Plan 03-02 will replace this with real httpx calls.
    """
    return False, f"Validation stub: {source_type} backend not yet implemented."


__all__ = ["detect_source", "validate_source"]
