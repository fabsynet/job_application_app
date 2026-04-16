"""Generic ATS form filler (06-03).

Handles unknown ATS forms using progressive form detection:
1. Form with file input (most likely application form)
2. Form with aria-label containing "apply" or "application"
3. Largest form on the page (most fields)
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
    r"you('ve|\s*have)\s*applied",
]


class GenericFiller(BaseFiller):
    """Filler for unknown/generic ATS forms."""

    ats_name = "generic"

    def get_form_url(self, job_url: str) -> str:
        """For generic forms, the job URL is the form URL."""
        return job_url.rstrip("/")

    async def _find_application_form(self, page: Any) -> Any | None:
        """Progressive form detection.

        Strategy (in priority order):
        1. Form containing a file input (resume upload = application form)
        2. Form with aria-label matching "apply" or "application"
        3. Largest form on the page (most input fields)
        """
        forms = page.locator("form:visible")
        form_count = await forms.count()

        if form_count == 0:
            return None

        if form_count == 1:
            return forms.first

        # Strategy 1: Form with file input
        for i in range(form_count):
            form = forms.nth(i)
            file_inputs = form.locator("input[type='file']")
            if await file_inputs.count() > 0:
                logger.info("Generic: found form with file input (strategy 1)")
                return form

        # Strategy 2: Form with application-related aria-label
        for i in range(form_count):
            form = forms.nth(i)
            aria = await form.get_attribute("aria-label") or ""
            if re.search(r"appl(y|ication)", aria, re.IGNORECASE):
                logger.info("Generic: found form by aria-label (strategy 2)")
                return form

        # Strategy 3: Largest form (most inputs)
        max_inputs = 0
        best_form = forms.first
        for i in range(form_count):
            form = forms.nth(i)
            inputs = form.locator("input, select, textarea")
            count = await inputs.count()
            if count > max_inputs:
                max_inputs = count
                best_form = form

        logger.info("Generic: using largest form with %d inputs (strategy 3)", max_inputs)
        return best_form

    async def navigate_to_form(self, page: Any, job_url: str) -> bool:
        """Navigate to the job page and find the application form."""
        form_url = self.get_form_url(job_url)
        await page.goto(form_url, wait_until="domcontentloaded")

        # Try to find the form directly
        form = await self._find_application_form(page)
        if form:
            return True

        # Try clicking Apply button
        apply_btn = page.locator(
            "a:has-text('Apply'), button:has-text('Apply')"
        )
        if await apply_btn.count() > 0:
            await apply_btn.first.click()
            await page.wait_for_load_state("domcontentloaded")

            form = await self._find_application_form(page)
            if form:
                return True

        logger.warning("Could not find application form on generic page")
        return False

    async def scan_all_pages(
        self,
        page: Any,
        profile: Any,
    ) -> tuple[list[KnownField], list[UnknownFieldInfo]]:
        """Scan the generic form (assumes single page)."""
        return await classify_fields(page, profile, page_number=1)

    async def fill_and_submit(
        self,
        page: Any,
        known_fields: list[KnownField],
        resume_path: Optional[str] = None,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Fill and submit the generic form."""
        await fill_known_fields(page, known_fields, resume_path, cover_letter_path)

        if dry_run:
            logger.info("Dry run — skipping submit for generic form")
            return True

        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Submit'), button:has-text('Apply')"
        )
        if await submit.count() > 0:
            await submit.first.click()
            await page.wait_for_load_state("domcontentloaded")
            return True

        logger.warning("Could not find submit button on generic form")
        return False

    async def detect_success(self, page: Any) -> bool:
        """Check for generic success indicators."""
        try:
            body_text = await page.locator("body").inner_text()
            for pattern in _SUCCESS_PATTERNS:
                if re.search(pattern, body_text, re.IGNORECASE):
                    return True
        except Exception:
            pass

        # Check for URL change to a thank-you page
        try:
            url = page.url.lower()
            if "thank" in url or "success" in url or "confirmation" in url:
                return True
        except Exception:
            pass

        return False
