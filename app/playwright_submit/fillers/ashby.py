"""Ashby ATS form filler (06-03).

Handles jobs.ashbyhq.com application forms:
- URL pattern: jobs.ashbyhq.com/{company}/{job-id}
- Multi-step form handling (next/continue buttons)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.playwright_submit.fillers.base import BaseFiller
from app.playwright_submit.form_filler import (
    KnownField,
    UnknownFieldInfo,
    classify_fields,
    fill_known_fields,
)

logger = logging.getLogger(__name__)

_SUCCESS_PATTERNS = [
    r"thank\s*you",
    r"application\s*(has\s*been\s*)?received",
    r"successfully\s*submitted",
    r"application\s*submitted",
]

# Max form steps to prevent infinite loops
_MAX_STEPS = 10


class AshbyFiller(BaseFiller):
    """Filler for Ashby ATS (jobs.ashbyhq.com)."""

    ats_name = "ashby"

    def get_form_url(self, job_url: str) -> str:
        """Construct Ashby apply URL.

        Ashby jobs: https://jobs.ashbyhq.com/company/job-uuid
        Apply page: https://jobs.ashbyhq.com/company/job-uuid/application
        """
        url = job_url.rstrip("/")
        if not url.endswith("/application"):
            url += "/application"
        return url

    async def navigate_to_form(self, page: Any, job_url: str) -> bool:
        """Navigate to Ashby application form."""
        form_url = self.get_form_url(job_url)
        await page.goto(form_url, wait_until="domcontentloaded")

        form = page.locator("form, [data-testid='application-form']")
        if await form.count() > 0:
            return True

        # Try clicking Apply button
        apply_btn = page.locator(
            "a:has-text('Apply'), button:has-text('Apply')"
        )
        if await apply_btn.count() > 0:
            await apply_btn.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        logger.warning("Could not find Ashby application form")
        return False

    async def _has_next_button(self, page: Any) -> bool:
        """Check if there's a next/continue button (multi-step form)."""
        next_btn = page.locator(
            "button:has-text('Next'), button:has-text('Continue'), "
            "button[data-testid='next-button']"
        )
        return await next_btn.count() > 0

    async def _click_next(self, page: Any) -> bool:
        """Click the next/continue button to advance form steps."""
        next_btn = page.locator(
            "button:has-text('Next'), button:has-text('Continue'), "
            "button[data-testid='next-button']"
        )
        if await next_btn.count() > 0:
            await next_btn.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True
        return False

    async def scan_all_pages(
        self,
        page: Any,
        profile: Any,
    ) -> tuple[list[KnownField], list[UnknownFieldInfo]]:
        """Scan all steps of an Ashby multi-step form.

        Navigates through form pages using Next/Continue buttons,
        collecting all fields before returning.
        """
        all_known: list[KnownField] = []
        all_unknown: list[UnknownFieldInfo] = []

        for step in range(1, _MAX_STEPS + 1):
            known, unknown = await classify_fields(page, profile, page_number=step)
            all_known.extend(known)
            all_unknown.extend(unknown)

            if not await self._has_next_button(page):
                break

            # Don't click next during scan — just record the page count
            # We'll navigate back through during fill_and_submit
            await self._click_next(page)

        return all_known, all_unknown

    async def fill_and_submit(
        self,
        page: Any,
        known_fields: list[KnownField],
        resume_path: Optional[str] = None,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Fill and submit the Ashby form."""
        await fill_known_fields(page, known_fields, resume_path, cover_letter_path)

        if dry_run:
            logger.info("Dry run — skipping submit for Ashby")
            return True

        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Submit'), button:has-text('Apply')"
        )
        if await submit.count() > 0:
            await submit.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        logger.warning("Could not find Ashby submit button")
        return False

    async def detect_success(self, page: Any) -> bool:
        """Check for Ashby success indicators."""
        try:
            body_text = await page.locator("body").inner_text()
            for pattern in _SUCCESS_PATTERNS:
                if re.search(pattern, body_text, re.IGNORECASE):
                    return True
        except Exception:
            pass
        return False
