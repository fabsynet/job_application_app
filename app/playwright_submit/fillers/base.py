"""Abstract base filler defining the ATS filler interface (06-03).

All ATS-specific fillers inherit from ``BaseFiller`` and implement:
- get_form_url: construct the apply URL from a job URL
- navigate_to_form: navigate to the application form
- scan_all_pages: scan all form pages, collecting known/unknown fields
- fill_and_submit: fill known fields and submit the form
- detect_success: check whether submission succeeded
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Optional

from app.playwright_submit.form_filler import (
    KnownField,
    UnknownFieldInfo,
    classify_fields,
    fill_known_fields,
)

logger = logging.getLogger(__name__)


class BaseFiller(abc.ABC):
    """Abstract base class for ATS-specific form fillers."""

    ats_name: str = "unknown"

    @abc.abstractmethod
    def get_form_url(self, job_url: str) -> str:
        """Construct the application form URL from the job listing URL."""
        ...

    @abc.abstractmethod
    async def navigate_to_form(self, page: Any, job_url: str) -> bool:
        """Navigate to the application form.

        Returns True if the form was found, False otherwise.
        """
        ...

    @abc.abstractmethod
    async def scan_all_pages(
        self,
        page: Any,
        profile: Any,
    ) -> tuple[list[KnownField], list[UnknownFieldInfo]]:
        """Scan all form pages, returning aggregated known/unknown fields.

        For multi-step forms, navigates through all pages collecting fields
        before returning.
        """
        ...

    @abc.abstractmethod
    async def fill_and_submit(
        self,
        page: Any,
        known_fields: list[KnownField],
        resume_path: Optional[str] = None,
        cover_letter_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Fill all known fields and submit the form.

        If ``dry_run`` is True, fills fields but does NOT click submit.
        Returns True if submission succeeded (or would have in dry_run).
        """
        ...

    @abc.abstractmethod
    async def detect_success(self, page: Any) -> bool:
        """Check whether the form submission succeeded.

        Looks for success indicators (thank-you page, confirmation text, etc.).
        """
        ...
