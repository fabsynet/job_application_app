"""Playwright browser lifecycle manager with storageState persistence (SUBM-05).

Provides a single ``BrowserManager`` that lazily starts Playwright, launches
Chromium, and creates a browser context.  When ``storage_state_dir`` points to
an existing ``storageState.json`` the context reloads cookies/localStorage so
ATS sessions survive across pipeline runs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType

from playwright.async_api import (
    BrowserContext,
    async_playwright,
)

logger = logging.getLogger(__name__)

_DEFAULT_ACTION_TIMEOUT = 30_000   # 30 s
_DEFAULT_NAV_TIMEOUT = 60_000      # 60 s


class BrowserManager:
    """Manages a single Playwright browser instance per pipeline run."""

    def __init__(
        self,
        *,
        headless: bool = True,
        storage_state_dir: Path | None = None,
    ) -> None:
        self.headless = headless
        self._storage_state_dir = storage_state_dir or Path("data/browser")
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None

    # -- properties ----------------------------------------------------------

    @property
    def storage_state_path(self) -> Path:
        return self._storage_state_dir / "storageState.json"

    # -- public API ----------------------------------------------------------

    async def get_context(self) -> BrowserContext:
        """Lazily start Playwright and return a browser context."""
        if self._context is not None:
            return self._context

        pw = await async_playwright().start()
        self._playwright = pw

        browser = await pw.chromium.launch(headless=self.headless)
        self._browser = browser

        ctx_kwargs: dict = {}
        if self.storage_state_path.exists():
            ctx_kwargs["storage_state"] = str(self.storage_state_path)
            logger.info("Loading storageState from %s", self.storage_state_path)

        context = await browser.new_context(**ctx_kwargs)
        context.set_default_timeout(_DEFAULT_ACTION_TIMEOUT)
        context.set_default_navigation_timeout(_DEFAULT_NAV_TIMEOUT)
        self._context = context
        return context

    async def get_page(self):
        """Convenience: return a new page from the managed context."""
        ctx = await self.get_context()
        return await ctx.new_page()

    async def save_state(self) -> None:
        """Persist cookies / localStorage to disk."""
        if self._context is None:
            return
        self._storage_state_dir.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(self.storage_state_path))
        logger.info("Saved storageState to %s", self.storage_state_path)

    async def close(self) -> None:
        """Tear down context, browser, and Playwright. Idempotent."""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None

    # -- context manager -----------------------------------------------------

    async def __aenter__(self) -> "BrowserManager":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
