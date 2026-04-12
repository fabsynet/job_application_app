"""Keyword scoring and dedup fingerprinting for discovered jobs.

``job_fingerprint`` produces a SHA-256 hash from the canonical form of
(url, title, company) used as a unique index to prevent duplicates across
runs and sources.

``score_job`` computes a case-insensitive partial-match score of user
keywords against a job description, returning the score (0-100) and the
matched / unmatched keyword lists.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse, urlunparse


def job_fingerprint(url: str, title: str, company: str) -> str:
    """Canonical fingerprint for dedup.

    Normalisation:
      - URL: lowercase, strip query params / fragment / trailing slash
      - Title: lowercase, strip whitespace, collapse internal whitespace
      - Company: lowercase, strip whitespace

    Returns a hex-encoded SHA-256 hash.
    """
    # URL: strip query/fragment, lowercase, strip trailing slash
    parsed = urlparse(url.lower().strip())
    clean_url = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )

    clean_title = " ".join(title.lower().split())
    clean_company = company.lower().strip()

    raw = f"{clean_url}|{clean_title}|{clean_company}"
    return hashlib.sha256(raw.encode()).hexdigest()


def score_job(
    description: str, keywords: list[str],
) -> tuple[int, list[str], list[str]]:
    """Score a job description against user keywords.

    Returns ``(score_0_to_100, matched_keywords, unmatched_keywords)``.

    Matching is case-insensitive and partial (substring):
      - ``"python"`` matches ``"Python"``, ``"python3"``, ``"Python/Django"``

    An empty keywords list yields ``(0, [], [])``.
    """
    if not keywords:
        return (0, [], [])

    desc_lower = description.lower()
    matched: list[str] = []
    unmatched: list[str] = []

    for kw in keywords:
        if kw.lower() in desc_lower:
            matched.append(kw)
        else:
            unmatched.append(kw)

    score = round(len(matched) / len(keywords) * 100)
    return (score, matched, unmatched)


__all__ = ["job_fingerprint", "score_job"]
