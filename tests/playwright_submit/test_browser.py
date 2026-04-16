"""Unit tests for BrowserManager (mocked Playwright — no real browser)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.playwright_submit.browser import BrowserManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_playwright_stack():
    """Return (pw_instance, browser, context) mocks wired together."""
    context = AsyncMock()
    context.close = AsyncMock()
    context.storage_state = AsyncMock()
    context.new_page = AsyncMock(return_value=AsyncMock())
    # These are sync methods on real BrowserContext — use MagicMock to avoid
    # "coroutine never awaited" warnings.
    context.set_default_timeout = MagicMock()
    context.set_default_navigation_timeout = MagicMock()

    browser = AsyncMock()
    browser.close = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    pw = AsyncMock()
    pw.chromium = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()

    # async_playwright() returns an object whose .start() returns pw
    ap_cm = MagicMock()
    ap_cm.start = AsyncMock(return_value=pw)

    return ap_cm, pw, browser, context


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_context_creates_stack(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(headless=True, storage_state_dir=tmp_path)
        ctx = await mgr.get_context()

    assert ctx is context
    pw.chromium.launch.assert_awaited_once_with(headless=True)
    browser.new_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_context_headless_false(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(headless=False, storage_state_dir=tmp_path)
        await mgr.get_context()

    pw.chromium.launch.assert_awaited_once_with(headless=False)


@pytest.mark.asyncio
async def test_get_context_loads_storage_state(tmp_path: Path) -> None:
    state_file = tmp_path / "storageState.json"
    state_file.write_text("{}")

    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=tmp_path)
        await mgr.get_context()

    call_kwargs = browser.new_context.call_args.kwargs
    assert call_kwargs["storage_state"] == str(state_file)


@pytest.mark.asyncio
async def test_get_context_skips_storage_state_when_missing(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=tmp_path)
        await mgr.get_context()

    call_kwargs = browser.new_context.call_args.kwargs
    assert "storage_state" not in call_kwargs


@pytest.mark.asyncio
async def test_save_state_writes_file(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=tmp_path)
        await mgr.get_context()
        await mgr.save_state()

    context.storage_state.assert_awaited_once_with(
        path=str(tmp_path / "storageState.json")
    )


@pytest.mark.asyncio
async def test_save_state_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "dir"
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=nested)
        await mgr.get_context()
        await mgr.save_state()

    assert nested.exists()


@pytest.mark.asyncio
async def test_close_is_idempotent(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=tmp_path)
        await mgr.get_context()
        await mgr.close()
        await mgr.close()  # second call must not raise

    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    pw.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_without_start(tmp_path: Path) -> None:
    """close() on a never-started manager must not raise."""
    mgr = BrowserManager(storage_state_dir=tmp_path)
    await mgr.close()  # no error


@pytest.mark.asyncio
async def test_context_manager(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        async with BrowserManager(storage_state_dir=tmp_path) as mgr:
            ctx = await mgr.get_context()
            assert ctx is context

    # __aexit__ should have called close
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_page_returns_new_page(tmp_path: Path) -> None:
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=tmp_path)
        page = await mgr.get_page()

    context.new_page.assert_awaited_once()
    assert page is context.new_page.return_value


@pytest.mark.asyncio
async def test_get_context_returns_same_context(tmp_path: Path) -> None:
    """Calling get_context twice returns the same cached context."""
    ap_cm, pw, browser, context = _mock_playwright_stack()

    with patch("app.playwright_submit.browser.async_playwright", return_value=ap_cm):
        mgr = BrowserManager(storage_state_dir=tmp_path)
        ctx1 = await mgr.get_context()
        ctx2 = await mgr.get_context()

    assert ctx1 is ctx2
    # Playwright should only be started once
    ap_cm.start.assert_awaited_once()
