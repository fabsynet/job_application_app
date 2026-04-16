"""Lever ATS form filler (06-03).

Handles jobs.lever.co application forms:
- URL pattern: jobs.lever.co/{company}/{job-id}/apply
- Single-page form layout
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

_SUCCESS_PATTERNS = [
    r"thank\s*you",
    r"application\s*(has\s*been\s*)?received",
    r"successfully\s*submitted",
    r"application\s*submitted",
]


class LeverFiller(BaseFiller):
    """Filler for Lever ATS (jobs.lever.co)."""

    ats_name = "lever"

    def get_form_url(self, job_url: str) -> str:
        """Construct Lever apply URL.

        Lever jobs: https://jobs.lever.co/company/job-uuid
        Apply page: https://jobs.lever.co/company/job-uuid/apply
        """
        url = job_url.rstrip("/")
        if not url.endswith("/apply"):
            url += "/apply"
        return url

    async def navigate_to_form(self, page: Any, job_url: str) -> bool:
        """Navigate to Lever application form."""
        form_url = self.get_form_url(job_url)
        await page.goto(form_url, wait_until="domcontentloaded")

        # Lever forms are typically in a div.application-form or form tag
        form = page.locator(
            "form, .application-form, [data-qa='application-form']"
        )
        if await form.count() > 0:
            return True

        # Try clicking Apply button if on job description page
        apply_btn = page.locator(
            "a:has-text('Apply'), button:has-text('Apply')"
        )
        if await apply_btn.count() > 0:
            await apply_btn.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        logger.warning("Could not find Lever application form")
        return False

    async def scan_all_pages(
        self,
        page: Any,
        profile: Any,
    ) -> tuple[list[KnownField], list[UnknownFieldInfo]]:
        """Scan the Lever form (single page)."""
        return await classify_fields(page, profile, page_number=1)

    async def fill_and_submit(
        self,
        page: Any,
        known_fields: list[KnownField],
        resume_path: Optional[str] = None,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Fill and submit the Lever form."""
        await fill_known_fields(page, known_fields, resume_path, cover_letter_path)

        if dry_run:
            logger.info("Dry run — skipping submit for Lever")
            return True

        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Submit application'), button:has-text('Submit')"
        )
        if await submit.count() > 0:
            await submit.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        logger.warning("Could not find Lever submit button")
        return False

    async def detect_success(self, page: Any) -> bool:
        """Check for Lever success indicators."""
        try:
            body_text = await page.locator("body").inner_text()
            for pattern in _SUCCESS_PATTERNS:
                if re.search(pattern, body_text, re.IGNORECASE):
                    return True
        except Exception:
            pass
        return False
