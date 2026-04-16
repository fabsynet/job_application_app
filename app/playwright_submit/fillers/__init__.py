"""ATS-specific form fillers with auto-detection (06-03).

``select_filler`` returns the appropriate filler class based on job source
or URL pattern.  Each filler knows how to navigate, scan, fill, and submit
forms for its target ATS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.playwright_submit.fillers.ashby import AshbyFiller
from app.playwright_submit.fillers.generic import GenericFiller
from app.playwright_submit.fillers.greenhouse import GreenhouseFiller
from app.playwright_submit.fillers.lever import LeverFiller

if TYPE_CHECKING:
    from app.playwright_submit.fillers.base import BaseFiller

# URL pattern → filler class mapping
_URL_PATTERNS: list[tuple[str, type]] = [
    ("boards.greenhouse.io", GreenhouseFiller),
    ("greenhouse.io", GreenhouseFiller),
    ("jobs.lever.co", LeverFiller),
    ("lever.co", LeverFiller),
    ("jobs.ashbyhq.com", AshbyFiller),
    ("ashbyhq.com", AshbyFiller),
]

# Source string → filler class mapping
_SOURCE_MAP: dict[str, type] = {
    "greenhouse": GreenhouseFiller,
    "lever": LeverFiller,
    "ashby": AshbyFiller,
}


def select_filler(
    job_source: str | None = None,
    job_url: str | None = None,
) -> "BaseFiller":
    """Return the appropriate filler instance for the given ATS.

    Checks ``job_source`` string first (exact match), then falls back to
    URL pattern matching.  Returns ``GenericFiller`` if no specific filler
    matches.
    """
    # 1. Check by source name
    if job_source:
        source_lower = job_source.lower().strip()
        filler_cls = _SOURCE_MAP.get(source_lower)
        if filler_cls:
            return filler_cls()

    # 2. Check by URL pattern
    if job_url:
        url_lower = job_url.lower()
        for pattern, filler_cls in _URL_PATTERNS:
            if pattern in url_lower:
                return filler_cls()

    # 3. Fallback to generic
    return GenericFiller()


__all__ = [
    "select_filler",
    "GreenhouseFiller",
    "LeverFiller",
    "AshbyFiller",
    "GenericFiller",
]
