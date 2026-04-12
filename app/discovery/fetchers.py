"""ATS fetcher functions and source auto-detection.

Each public ATS API has a dedicated async fetcher that returns a list of
normalised job dicts matching the ``Job`` model schema.  The ``detect_source``
function parses user input (URL or plain slug) to determine the ATS type
and extract the company slug.

Supported ATS providers:
  - Greenhouse (boards-api.greenhouse.io)
  - Lever (api.lever.co)
  - Ashby (api.ashbyhq.com)
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

import httpx
import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# HTML-to-text helper
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_MAP = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
    "&nbsp;": " ",
}


def strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities for scoring purposes."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    for entity, char in _ENTITY_MAP.items():
        text = text.replace(entity, char)
    # Collapse whitespace
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# ATS fetchers -- each returns list[dict] with normalised keys
# ---------------------------------------------------------------------------

async def fetch_greenhouse(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Fetch all jobs from Greenhouse public API.

    Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    Response shape: ``{"jobs": [...]}``
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    resp = await client.get(url, params={"content": "true"})
    resp.raise_for_status()
    data = resp.json()

    jobs: list[dict] = []
    for j in data.get("jobs", []):
        content_html = j.get("content", "")
        jobs.append({
            "external_id": str(j["id"]),
            "title": j.get("title", ""),
            "company": slug,
            "location": (j.get("location") or {}).get("name", ""),
            "description": strip_html(content_html),
            "description_html": content_html,
            "url": j.get("absolute_url", ""),
            "source": "greenhouse",
            "posted_date": j.get("updated_at"),
        })
    return jobs


async def fetch_lever(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Fetch all jobs from Lever public API.

    Endpoint: GET https://api.lever.co/v0/postings/{slug}?mode=json
    Response shape: flat JSON array ``[{...}, ...]`` (NOT wrapped in object).
    Lever does not expose a posted date in the public API.
    """
    url = f"https://api.lever.co/v0/postings/{slug}"
    resp = await client.get(url, params={"mode": "json"})
    resp.raise_for_status()
    data = resp.json()

    # Lever returns a flat list, not {"jobs": [...]}
    if not isinstance(data, list):
        data = []

    jobs: list[dict] = []
    for j in data:
        desc_plain = j.get("descriptionPlain", j.get("description", ""))
        jobs.append({
            "external_id": str(j.get("id", "")),
            "title": j.get("text", ""),
            "company": slug,
            "location": (j.get("categories") or {}).get("location", ""),
            "description": desc_plain,
            "description_html": j.get("description", ""),
            "url": j.get("hostedUrl", ""),
            "source": "lever",
            "posted_date": None,  # Lever public API lacks posted date
        })
    return jobs


async def fetch_ashby(client: httpx.AsyncClient, slug: str) -> list[dict]:
    """Fetch all jobs from Ashby public API.

    Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}
    Response shape: ``{"jobs": [...]}``
    Uses ``descriptionPlain`` for scoring and ``descriptionHtml`` for display.
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()

    jobs: list[dict] = []
    for j in data.get("jobs", []):
        jobs.append({
            "external_id": str(j.get("id", "")),
            "title": j.get("title", ""),
            "company": slug,
            "location": j.get("location", ""),
            "description": j.get("descriptionPlain", ""),
            "description_html": j.get("descriptionHtml", ""),
            "url": j.get("jobUrl", ""),
            "source": "ashby",
            "posted_date": j.get("publishedAt"),
        })
    return jobs


# ---------------------------------------------------------------------------
# Fetcher dispatcher
# ---------------------------------------------------------------------------

_FETCHER_BY_TYPE = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


async def fetch_source(
    client: httpx.AsyncClient, source_type: str, slug: str,
) -> list[dict]:
    """Dispatch to the correct ATS fetcher based on source type."""
    fetcher = _FETCHER_BY_TYPE.get(source_type)
    if fetcher is None:
        raise ValueError(f"Unknown source type: {source_type}")
    return await fetcher(client, slug)


# ---------------------------------------------------------------------------
# Source auto-detection from URL or plain slug
# ---------------------------------------------------------------------------

def detect_source(input_str: str) -> tuple[str, str]:
    """Return ``(slug, source_type)`` from user input.

    Supports:
      - Greenhouse URL: boards.greenhouse.io/stripe or boards-api.greenhouse.io/...
      - Lever URL: jobs.lever.co/stripe or api.lever.co/...
      - Ashby URL: jobs.ashbyhq.com/stripe or api.ashbyhq.com/...
      - Plain slug (alphanumeric + dash + underscore): returns (slug, "unknown")

    Raises ``ValueError`` for unrecognisable input.
    """
    input_str = input_str.strip().rstrip("/")

    # URL patterns
    if "greenhouse.io" in input_str:
        parsed = urlparse(input_str if "://" in input_str else f"https://{input_str}")
        parts = [
            p for p in parsed.path.split("/")
            if p and p not in ("v1", "boards", "jobs")
        ]
        if parts:
            return (parts[0], "greenhouse")

    if "lever.co" in input_str:
        parsed = urlparse(input_str if "://" in input_str else f"https://{input_str}")
        parts = [
            p for p in parsed.path.split("/")
            if p and p not in ("v0", "postings")
        ]
        if parts:
            return (parts[0], "lever")

    if "ashbyhq.com" in input_str:
        parsed = urlparse(input_str if "://" in input_str else f"https://{input_str}")
        parts = [
            p for p in parsed.path.split("/")
            if p and p not in ("posting-api", "job-board")
        ]
        if parts:
            return (parts[0], "ashby")

    # Plain slug -- no URL pattern matched
    if re.match(r"^[a-zA-Z0-9_-]+$", input_str):
        return (input_str, "unknown")

    raise ValueError(f"Cannot parse source from: {input_str}")


# ---------------------------------------------------------------------------
# Source validation -- hit the real API to check if slug is valid
# ---------------------------------------------------------------------------

_VALIDATE_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

# Order for probing unknown slugs (Greenhouse most common)
_PROBE_ORDER = ["greenhouse", "lever", "ashby"]


async def validate_source(slug: str, source_type: str) -> tuple[bool, str]:
    """Validate a source slug against the real ATS API.

    Returns ``(True, "")`` on success or ``(False, error_message)`` on failure.

    For ``source_type="unknown"``, probes Greenhouse -> Lever -> Ashby and
    returns ``(True, detected_type)`` on first success.

    Uses ``timeout=10.0`` for validation requests.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        if source_type != "unknown":
            url_template = _VALIDATE_URLS.get(source_type)
            if not url_template:
                return (False, f"Unknown source type: {source_type}")
            try:
                resp = await client.get(url_template.format(slug=slug))
                if source_type == "lever":
                    # Lever returns empty array [] for invalid slugs, not 404
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        return (True, "")
                    return (False, f"No postings found for '{slug}' on Lever.")
                if resp.status_code == 200:
                    return (True, "")
                return (False, f"API returned {resp.status_code} for '{slug}' on {source_type}.")
            except httpx.TimeoutException:
                return (False, f"Timeout validating '{slug}' on {source_type}.")
            except Exception as e:
                return (False, f"Error validating '{slug}': {e}")

        # Unknown source type -- probe all three
        for st in _PROBE_ORDER:
            url_template = _VALIDATE_URLS[st]
            try:
                resp = await client.get(url_template.format(slug=slug))
                if st == "lever":
                    data = resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        return (True, st)
                elif resp.status_code == 200:
                    return (True, st)
            except Exception:
                continue

        return (False, f"Could not find '{slug}' on Greenhouse, Lever, or Ashby.")


__all__ = [
    "fetch_greenhouse",
    "fetch_lever",
    "fetch_ashby",
    "fetch_source",
    "detect_source",
    "validate_source",
    "strip_html",
]
