"""Unit tests for :mod:`app.manual_apply.fetcher`.

Network-free: every HTTP response is served by ``httpx.MockTransport``
so the suite honours the Phase 5 "no network calls" rule.
"""

from __future__ import annotations

import httpx
import pytest

from app.manual_apply import fetcher as fetcher_module
from app.manual_apply.fetcher import (
    FetchError,
    ParsedJob,
    _best_effort_parse,
    fetch_and_parse,
)


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Swap ``httpx.AsyncClient`` for one that routes through a MockTransport.

    The fetcher instantiates its own AsyncClient inside the function
    body so we replace the constructor with a wrapper that forces the
    ``transport=`` kwarg to a ``MockTransport`` driven by ``handler``.
    """
    real_cls = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(fetcher_module.httpx, "AsyncClient", _factory)


# ---------------------------------------------------------------------------
# HTTP error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_404_raises_not_found(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    _install_mock(monkeypatch, handler)

    with pytest.raises(FetchError) as exc_info:
        await fetch_and_parse("https://example.com/missing")
    assert exc_info.value.reason == "not_found"
    assert exc_info.value.status == 404


@pytest.mark.asyncio
async def test_fetch_403_raises_auth_wall(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    _install_mock(monkeypatch, handler)

    with pytest.raises(FetchError) as exc_info:
        await fetch_and_parse("https://www.linkedin.com/jobs/view/123")
    assert exc_info.value.reason == "auth_wall"
    assert exc_info.value.status == 403


@pytest.mark.asyncio
async def test_fetch_timeout_raises_timeout(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    _install_mock(monkeypatch, handler)

    with pytest.raises(FetchError) as exc_info:
        await fetch_and_parse("https://slow.example.com/job")
    assert exc_info.value.reason == "timeout"


@pytest.mark.asyncio
async def test_fetch_empty_body_raises_empty_body(
    monkeypatch: pytest.MonkeyPatch,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="tiny")

    _install_mock(monkeypatch, handler)

    with pytest.raises(FetchError) as exc_info:
        await fetch_and_parse("https://example.com/empty")
    assert exc_info.value.reason == "empty_body"
    assert exc_info.value.status == 200


@pytest.mark.asyncio
async def test_fetch_500_raises_http_error(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="a" * 500)

    _install_mock(monkeypatch, handler)

    with pytest.raises(FetchError) as exc_info:
        await fetch_and_parse("https://example.com/broken")
    assert exc_info.value.reason == "http_500"
    assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# Best-effort parse
# ---------------------------------------------------------------------------


def test_best_effort_parse_extracts_title():
    body = (
        "<html><head><title>Senior Backend Engineer at Stripe</title>"
        "</head><body>" + ("This is the description. " * 20) + "</body></html>"
    )
    parsed = _best_effort_parse("https://example.com/jobs/42", body, "manual")
    assert parsed.title == "Senior Backend Engineer"
    assert parsed.source == "manual"
    assert "description" in parsed.description
    assert parsed.url == "https://example.com/jobs/42"
    assert parsed.external_id == "/jobs/42"


def test_best_effort_parse_falls_back_to_hostname_for_company():
    body = "<html><head><title>Job</title></head><body>" + ("x " * 200) + "</body></html>"
    parsed = _best_effort_parse("https://careers.acme.com/r/42", body, "manual")
    assert parsed.company == "careers.acme.com"


def test_best_effort_parse_uses_og_site_name_when_present():
    body = (
        '<html><head><title>Cool Job</title>'
        '<meta property="og:site_name" content="Stripe"></head>'
        "<body>" + ("x " * 200) + "</body></html>"
    )
    parsed = _best_effort_parse("https://boards.example.com/r/1", body, "manual")
    assert parsed.company == "Stripe"


def test_best_effort_parse_caps_description_length():
    body = "<html><head><title>T</title></head><body>" + ("x" * 100000) + "</body></html>"
    parsed = _best_effort_parse("https://example.com/j", body, "manual")
    assert len(parsed.description) <= 20000


def test_best_effort_parse_missing_title_falls_back():
    body = "<html><body>" + ("word " * 500) + "</body></html>"
    parsed = _best_effort_parse("https://example.com/j", body, "manual")
    assert parsed.title == "Unknown Role"


# ---------------------------------------------------------------------------
# ATS source detection preserves the source tag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_greenhouse_url_stamps_source_greenhouse(
    monkeypatch: pytest.MonkeyPatch,
):
    html = (
        "<html><head><title>Senior Engineer at Stripe</title></head>"
        "<body>" + ("Build great things. " * 50) + "</body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    _install_mock(monkeypatch, handler)

    parsed = await fetch_and_parse(
        "https://boards.greenhouse.io/stripe/jobs/123456"
    )
    assert isinstance(parsed, ParsedJob)
    assert parsed.source == "greenhouse"
    assert "Senior Engineer" in parsed.title


@pytest.mark.asyncio
async def test_fetch_lever_url_stamps_source_lever(
    monkeypatch: pytest.MonkeyPatch,
):
    html = "<html><head><title>Staff SRE</title></head><body>" + ("x " * 300) + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    _install_mock(monkeypatch, handler)

    parsed = await fetch_and_parse("https://jobs.lever.co/figma/abc-def")
    assert parsed.source == "lever"


@pytest.mark.asyncio
async def test_fetch_unknown_url_stamps_source_manual(
    monkeypatch: pytest.MonkeyPatch,
):
    html = "<html><head><title>Job</title></head><body>" + ("word " * 300) + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    _install_mock(monkeypatch, handler)

    parsed = await fetch_and_parse("https://careers.bigcorp.com/roles/42")
    assert parsed.source == "manual"
