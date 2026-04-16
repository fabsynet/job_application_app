"""Greenhouse ATS form filler (06-03).

Handles boards.greenhouse.io application forms, including:
- iframe-embedded forms
- GDPR consent checkboxes
- Standard Greenhouse field layout
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

from app.playwright_submit.fillers.base import BaseFiller
from app.playwright_submit.form_filler import (
    KnownField,
    UnknownFieldInfo,
    classify_fields,
    fill_known_fields,
)

logger = logging.getLogger(__name__)

# Greenhouse success indicators
_SUCCESS_PATTERNS = [
    r"thank\s*you",
    r"application\s*(has\s*been\s*)?received",
    r"successfully\s*submitted",
    r"application\s*submitted",
]


class GreenhouseFiller(BaseFiller):
    """Filler for Greenhouse ATS (boards.greenhouse.io)."""

    ats_name = "greenhouse"

    def get_form_url(self, job_url: str) -> str:
        """Construct Greenhouse apply URL.

        Greenhouse jobs: https://boards.greenhouse.io/company/jobs/12345
        Apply page:      https://boards.greenhouse.io/company/jobs/12345
        (Same URL — the form is embedded or accessed via #app anchor)
        """
        # Normalise — strip trailing slash, add #app if not present
        url = job_url.rstrip("/")
        if "#app" not in url:
            url += "#app"
        return url

    async def navigate_to_form(self, page: Any, job_url: str) -> bool:
        """Navigate to Greenhouse application form.

        Greenhouse embeds forms in iframes on some pages. We try:
        1. Direct navigation to the form URL
        2. Looking for an iframe with the application form
        3. Clicking an "Apply" button if present
        """
        form_url = self.get_form_url(job_url)
        await page.goto(form_url, wait_until="domcontentloaded")

        # Check for iframe-embedded form
        iframe = page.frame_locator("#grnhse_app iframe")
        try:
            iframe_count = await page.locator("#grnhse_app iframe").count()
            if iframe_count > 0:
                logger.info("Found Greenhouse iframe, switching context")
                # Return the iframe's content frame for further operations
                return True
        except Exception:
            pass

        # Check for direct form
        form = page.locator("form#application-form, form[data-controller='application']")
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

        logger.warning("Could not find Greenhouse application form")
        return False

    async def _get_form_context(self, page: Any) -> Any:
        """Return the correct page/frame context for the form.

        Greenhouse may embed forms in iframes.
        """
        iframe_loc = page.locator("#grnhse_app iframe")
        if await iframe_loc.count() > 0:
            frame = page.frame_locator("#grnhse_app iframe")
            return frame
        return page

    async def _auto_check_gdpr(self, page: Any) -> None:
        """Auto-check GDPR/consent checkboxes if present."""
        gdpr_selectors = [
            "input[type='checkbox'][id*='consent']",
            "input[type='checkbox'][id*='gdpr']",
            "input[type='checkbox'][name*='consent']",
            "input[type='checkbox'][name*='gdpr']",
            "input[type='checkbox'][data-field='consent']",
        ]
        for selector in gdpr_selectors:
            checkboxes = page.locator(selector)
            count = await checkboxes.count()
            for i in range(count):
                cb = checkboxes.nth(i)
                if not await cb.is_checked():
                    await cb.check()
                    logger.info("Auto-checked GDPR/consent checkbox")

    async def scan_all_pages(
        self,
        page: Any,
        profile: Any,
    ) -> tuple[list[KnownField], list[UnknownFieldInfo]]:
        """Scan the Greenhouse form (typically single page)."""
        await self._auto_check_gdpr(page)
        return await classify_fields(page, profile, page_number=1)

    async def fill_and_submit(
        self,
        page: Any,
        known_fields: list[KnownField],
        resume_path: Optional[str] = None,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Fill and submit the Greenhouse form."""
        await fill_known_fields(page, known_fields, resume_path, cover_letter_path)

        if dry_run:
            logger.info("Dry run — skipping submit for Greenhouse")
            return True

        # Find and click submit button
        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Submit'), button:has-text('Apply')"
        )
        if await submit.count() > 0:
            await submit.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        logger.warning("Could not find Greenhouse submit button")
        return False

    async def detect_success(self, page: Any) -> bool:
        """Check for Greenhouse success indicators."""
        try:
            body_text = await page.locator("body").inner_text()
            for pattern in _SUCCESS_PATTERNS:
                if re.search(pattern, body_text, re.IGNORECASE):
                    return True
        except Exception:
            pass
        return False
