"""Unit tests for CAPTCHA / 2FA detection (mocked Playwright page)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from app.playwright_submit.captcha import detect_blocking_element


def _make_page(url: str = "https://jobs.example.com/apply", matches: dict | None = None):
    """Return a mock page that responds to locator().count().

    *matches* maps CSS selector strings to count values (default 0).
    """
    match_map = matches or {}

    page = MagicMock()
    page.url = url

    def _locator(sel: str):
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=match_map.get(sel, 0))
        return loc

    page.locator = _locator
    return page


# -- Individual CAPTCHA types ------------------------------------------------


@pytest.mark.asyncio
async def test_detects_recaptcha_iframe() -> None:
    page = _make_page(matches={'iframe[src*="recaptcha"]': 1})
    assert await detect_blocking_element(page) == "recaptcha"


@pytest.mark.asyncio
async def test_detects_recaptcha_div() -> None:
    page = _make_page(matches={"div.g-recaptcha": 1})
    assert await detect_blocking_element(page) == "recaptcha"


@pytest.mark.asyncio
async def test_detects_hcaptcha() -> None:
    page = _make_page(matches={'iframe[src*="hcaptcha"]': 1})
    assert await detect_blocking_element(page) == "hcaptcha"


@pytest.mark.asyncio
async def test_detects_hcaptcha_div() -> None:
    page = _make_page(matches={"div.h-captcha": 1})
    assert await detect_blocking_element(page) == "hcaptcha"


@pytest.mark.asyncio
async def test_detects_cloudflare() -> None:
    page = _make_page(matches={'iframe[src*="challenges.cloudflare.com"]': 1})
    assert await detect_blocking_element(page) == "cloudflare"


@pytest.mark.asyncio
async def test_detects_cloudflare_challenge_running() -> None:
    page = _make_page(matches={"#challenge-running": 1})
    assert await detect_blocking_element(page) == "cloudflare"


@pytest.mark.asyncio
async def test_detects_generic_captcha() -> None:
    page = _make_page(matches={'[class*="captcha" i]': 1})
    assert await detect_blocking_element(page) == "generic_captcha"


@pytest.mark.asyncio
async def test_detects_2fa_otp() -> None:
    page = _make_page(matches={'input[name*="otp"]': 1})
    assert await detect_blocking_element(page) == "2fa"


@pytest.mark.asyncio
async def test_detects_2fa_verification_code() -> None:
    page = _make_page(matches={'input[name*="verification_code"]': 1})
    assert await detect_blocking_element(page) == "2fa"


@pytest.mark.asyncio
async def test_detects_2fa_class() -> None:
    page = _make_page(matches={'[class*="two-factor"]': 1})
    assert await detect_blocking_element(page) == "2fa"


# -- Login redirect ----------------------------------------------------------


@pytest.mark.asyncio
async def test_detects_login_redirect() -> None:
    page = _make_page(url="https://greenhouse.io/login?next=/apply")
    assert await detect_blocking_element(page) == "login_required"


@pytest.mark.asyncio
async def test_detects_signin_redirect() -> None:
    page = _make_page(url="https://lever.co/signin")
    assert await detect_blocking_element(page) == "login_required"


@pytest.mark.asyncio
async def test_detects_sso_redirect() -> None:
    page = _make_page(url="https://myworkday.com/sso/saml")
    assert await detect_blocking_element(page) == "login_required"


# -- No blocking element -----------------------------------------------------


@pytest.mark.asyncio
async def test_no_blocking_element() -> None:
    page = _make_page()
    assert await detect_blocking_element(page) is None


# -- Priority order -----------------------------------------------------------


@pytest.mark.asyncio
async def test_recaptcha_takes_priority_over_generic() -> None:
    """When both reCAPTCHA and generic captcha selectors match, reCAPTCHA wins."""
    page = _make_page(matches={
        'iframe[src*="recaptcha"]': 1,
        '[class*="captcha" i]': 1,
    })
    assert await detect_blocking_element(page) == "recaptcha"
