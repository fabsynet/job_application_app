"""Manual-apply URL fetcher + best-effort HTML parser.

Entry point is :func:`fetch_and_parse`, an async helper that takes a
user-pasted job URL and returns a :class:`ParsedJob` dataclass suitable
for feeding into :func:`app.manual_apply.service.create_manual_job`.

Routing:
  1. ``detect_source`` (reused from Phase 3) tags the URL with a known
     ATS source (greenhouse / lever / ashby) or ``"unknown"``.
  2. The URL is fetched via :mod:`httpx` with a short timeout, a browser
     User-Agent header, and redirects enabled.
  3. HTTP 4xx/5xx + transport errors raise :class:`FetchError` with a
     stable ``reason`` string the UI layer can render directly.
  4. On success the HTML body is parsed best-effort (``<title>`` +
     ``og:site_name`` + :func:`strip_html` for description). Known ATS
     URLs preserve the detected source tag even though the v1 parser
     does not round-trip through the ATS API — this keeps the
     ``source`` column accurate for downstream dedup / rate limiting.

Design notes:
  - No HTML parsing dependency is added; regex + the Phase 3
    ``strip_html`` helper is enough for an excerpt-quality description.
    A user who wants higher fidelity can always paste the description
    directly into the fallback form.
  - The LinkedIn / Indeed "auth wall" edge case is detected two ways:
    (a) HTTP 401/403, and (b) a 200 with an empty / obviously-login
    body. Both degrade into :class:`FetchError` so the router can swap
    the paste form for the fallback textarea.
  - The 20k-char description cap protects downstream tailoring from
    pathological pages (a raw HTML dump of LinkedIn's SPA shell is
    ~300k of markup). 20k is comfortably above any real job posting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import structlog

from app.discovery.fetchers import detect_source, strip_html

log = structlog.get_logger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; JobApplyBot/1.0; +local)"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_SITE_NAME_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)


@dataclass
class ParsedJob:
    """A best-effort parse of a pasted job URL.

    ``source`` is one of ``greenhouse``, ``lever``, ``ashby``, or
    ``manual`` (unknown generic pages). ``external_id`` is derived from
    the URL path component so two pastes of the same URL collide inside
    the canonical fingerprint even when the fingerprint is recomputed.
    """

    title: str
    company: str
    description: str
    description_html: str
    url: str
    source: str
    external_id: str


class FetchError(Exception):
    """Raised by :func:`fetch_and_parse` on any network / parse failure.

    ``reason`` is a short, stable identifier the router layer renders to
    the user (``"not_found"``, ``"auth_wall"``, ``"timeout"``, ...).
    ``status`` is the HTTP status code when the error is HTTP-specific,
    ``None`` for transport-level failures.
    """

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status


async def fetch_and_parse(url: str) -> ParsedJob:
    """Fetch a pasted job URL and return a :class:`ParsedJob`.

    Raises :class:`FetchError` with a stable ``reason`` on any failure.
    """
    source_type = "manual"
    try:
        _slug, detected = detect_source(url)
        if detected in ("greenhouse", "lever", "ashby"):
            source_type = detected
    except Exception:
        source_type = "manual"

    timeout = httpx.Timeout(10.0, connect=5.0)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json",
    }

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers=headers
    ) as client:
        try:
            resp = await client.get(url)
        except httpx.TimeoutException as exc:
            log.warning("manual_apply.fetch_timeout", url=url)
            raise FetchError("timeout") from exc
        except httpx.ConnectError as exc:
            log.warning("manual_apply.fetch_connect_error", url=url, error=str(exc))
            raise FetchError(f"connect_failed: {exc}") from exc
        except httpx.RequestError as exc:
            log.warning("manual_apply.fetch_request_error", url=url, error=str(exc))
            raise FetchError(f"request_error: {exc}") from exc

    if resp.status_code == 404:
        raise FetchError("not_found", status=404)
    if resp.status_code in (401, 403):
        raise FetchError("auth_wall", status=resp.status_code)
    if resp.status_code >= 400:
        raise FetchError(f"http_{resp.status_code}", status=resp.status_code)

    body = resp.text or ""

    # Bot-wall edge cases: LinkedIn / Indeed often 200 with an SPA shell
    # that contains barely any markup. Treat anything below 200 chars as
    # an effective auth wall and punt to the fallback form.
    if len(body.strip()) < 200:
        raise FetchError("empty_body", status=resp.status_code)

    return _best_effort_parse(url, body, source_type)


def _best_effort_parse(url: str, body: str, source: str) -> ParsedJob:
    """Extract title / company / description from a generic HTML body.

    - Title comes from ``<title>`` with any ``" at Company"`` suffix
      stripped so badges render cleanly.
    - Company prefers ``og:site_name`` and falls back to the URL
      hostname.
    - Description is a best-effort text rendering via the Phase 3
      ``strip_html`` helper, capped at 20k chars.
    """
    m = _TITLE_RE.search(body)
    raw_title = m.group(1).strip() if m else ""
    # Collapse whitespace inside the title
    raw_title = " ".join(raw_title.split())
    title = raw_title.split(" at ")[0].strip() or "Unknown Role"

    company_match = _OG_SITE_NAME_RE.search(body)
    if company_match:
        company = company_match.group(1).strip()
    else:
        company = urlparse(url).hostname or "Unknown"

    description = strip_html(body)[:20000]

    external_id = urlparse(url).path or url

    return ParsedJob(
        title=title,
        company=company,
        description=description,
        description_html=body,
        url=url,
        source=source,
        external_id=external_id,
    )


__all__ = ["fetch_and_parse", "ParsedJob", "FetchError", "USER_AGENT"]
