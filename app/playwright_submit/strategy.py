"""PlaywrightStrategy — browser-based form submission for known ATS platforms.

Implements the :class:`~app.submission.registry.SubmitterStrategy` protocol
for Greenhouse, Lever, and Ashby application forms.  Orchestrates
BrowserManager, ATS-specific fillers, CAPTCHA detection, screenshots,
and the learning loop (saved-answer matching via LLM).

Unlike EmailStrategy (which is stateless), PlaywrightStrategy needs DB
access to load the user profile, retrieve saved answers, and persist
unknown fields.  It accepts an optional ``session_factory`` or falls
back to ``async_session`` from ``app.db.base``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Callable

from app.playwright_submit.browser import BrowserManager
from app.playwright_submit.captcha import detect_blocking_element
from app.playwright_submit.fillers import select_filler
from app.playwright_submit.screenshots import (
    capture_error_screenshot,
    capture_step_screenshot,
)
from app.submission.registry import (
    SubmissionContext,
    SubmissionOutcome,
)

if TYPE_CHECKING:
    from app.discovery.models import Job

logger = logging.getLogger(__name__)

_KNOWN_ATS_DOMAINS = ("greenhouse.io", "lever.co", "ashbyhq.com")


def _is_known_ats_url(url: str) -> bool:
    """Return True if *url* contains a known ATS domain."""
    if not url:
        return False
    url_lower = url.lower()
    return any(domain in url_lower for domain in _KNOWN_ATS_DOMAINS)


class PlaywrightStrategy:
    """SUBM-03/04/05: browser-based form submission via Playwright.

    Applicable for jobs whose ``source`` is a known ATS (greenhouse, lever,
    ashby) or whose URL matches a known ATS domain.  Falls through to
    EmailStrategy for all other jobs.
    """

    name: str = "playwright"

    def __init__(
        self,
        browser_manager: BrowserManager | None = None,
        session_factory: Callable | None = None,
    ) -> None:
        self._browser_manager = browser_manager
        self._owns_browser = browser_manager is None
        self._session_factory = session_factory
        self._reused_answers: list[tuple[str, Any]] = []

    # -- SubmitterStrategy protocol ------------------------------------------

    def is_applicable(self, job: "Job", description: str) -> bool:
        """True for known ATS sources or URLs."""
        if job.source and job.source.lower() in ("greenhouse", "lever", "ashby"):
            return True
        return _is_known_ats_url(job.url or "")

    async def submit(self, ctx: SubmissionContext) -> SubmissionOutcome:
        """Orchestrate the full browser form-fill + submit flow.

        Never raises -- always returns a SubmissionOutcome.
        """
        self._reused_answers = []
        page = None

        try:
            # 1. Get/create BrowserManager and read settings.
            bm = await self._get_browser_manager()
            session_factory = self._get_session_factory()

            async with session_factory() as session:
                settings = await self._load_settings(session)

            headless = settings.playwright_headless
            pause_if_unsure = settings.pause_if_unsure
            data_dir = self._get_data_dir()

            # Update headless if we created the manager.
            if self._owns_browser and bm.headless != headless:
                bm.headless = headless

            # 2. Get a new page.
            page = await bm.get_page()

            # 3. Select filler.
            filler = select_filler(ctx.job.source, ctx.job.url)

            # 4. Navigate to form.
            nav_ok = await filler.navigate_to_form(page, ctx.job.url)
            if not nav_ok:
                await capture_error_screenshot(page, data_dir, ctx.job.id)
                return SubmissionOutcome(
                    success=False,
                    submitter=self.name,
                    error_class="navigation_failed",
                    error_message="Could not navigate to application form",
                )

            # 5. Check CAPTCHA / blocking element.
            blocking = await detect_blocking_element(page)
            if blocking is not None:
                await capture_error_screenshot(page, data_dir, ctx.job.id)
                return SubmissionOutcome(
                    success=False,
                    submitter=self.name,
                    error_class="captcha",
                    error_message=blocking,
                )

            # 6-7. Load Profile and SavedAnswers from DB.
            async with session_factory() as session:
                from app.learning.service import get_all_saved_answers
                from app.settings.service import get_profile_row

                profile = await get_profile_row(session)
                saved_answers = await get_all_saved_answers(session)

            # 8. Scan all form pages.
            step = 1
            await capture_step_screenshot(page, data_dir, ctx.job.id, step)
            known_fields, unknown_fields = await filler.scan_all_pages(
                page, profile
            )
            step += 1
            await capture_step_screenshot(page, data_dir, ctx.job.id, step)

            # 9. For unknown fields: try LLM matching against saved answers.
            matched = []
            truly_unknown = []

            if unknown_fields and saved_answers:
                unknown_infos = [
                    {
                        "field_id": 0,  # no DB ID yet
                        "field_label": uf.label,
                        "field_type": uf.field_type,
                        "field_options": json.dumps(uf.options) if uf.options else None,
                        "is_required": uf.is_required,
                        "page_number": uf.page_number,
                    }
                    for uf in unknown_fields
                ]

                from app.learning.matcher import try_match_and_fill
                from app.tailoring.provider import get_provider

                async with session_factory() as session:
                    provider = await get_provider(session)
                    matched, truly_unknown = await try_match_and_fill(
                        session, unknown_infos, saved_answers, provider
                    )
                    await session.commit()

                # Record reused answers for reporting.
                for m in matched:
                    sa = m.get("matched_answer")
                    if sa is not None:
                        self._reused_answers.append((m["field_label"], sa))
            else:
                truly_unknown = [
                    {
                        "field_label": uf.label,
                        "field_type": uf.field_type,
                        "field_options": json.dumps(uf.options) if uf.options else None,
                        "is_required": uf.is_required,
                        "page_number": uf.page_number,
                    }
                    for uf in unknown_fields
                ]

            # 10. If truly-unknown AND pause_if_unsure -> needs_info.
            if truly_unknown and pause_if_unsure:
                async with session_factory() as session:
                    from app.learning.service import create_unknown_fields

                    await create_unknown_fields(
                        session, ctx.job.id, truly_unknown
                    )
                    await session.commit()

                return SubmissionOutcome(
                    success=False,
                    submitter=self.name,
                    error_class="needs_info",
                    error_message=f"{len(truly_unknown)} unknown fields",
                )

            # 11. If pause_if_unsure=False: skip unknowns, proceed.

            # 12. Fill known + matched fields and submit.
            # Build extra KnownFields from matched answers.
            from app.playwright_submit.form_filler import KnownField

            extra_known = []
            for m in matched:
                sa = m.get("matched_answer")
                if sa is not None:
                    extra_known.append(
                        KnownField(
                            label=m["field_label"],
                            profile_field="saved_answer",
                            value=sa.answer_text,
                            input_method="text",
                            locator=None,
                        )
                    )

            all_known = list(known_fields) + extra_known

            submitted = await filler.fill_and_submit(
                page,
                all_known,
                resume_path=str(ctx.tailored_resume_path),
                cover_letter_path=str(ctx.cover_letter_path),
            )

            if not submitted:
                await capture_error_screenshot(page, data_dir, ctx.job.id)
                return SubmissionOutcome(
                    success=False,
                    submitter=self.name,
                    error_class="submit_failed",
                    error_message="fill_and_submit returned False",
                )

            # 13. Detect success.
            success = await filler.detect_success(page)

            # 14. Save storageState.
            await bm.save_state()

            # 15. Final screenshot.
            step += 1
            await capture_step_screenshot(page, data_dir, ctx.job.id, step)

            if not success:
                return SubmissionOutcome(
                    success=False,
                    submitter=self.name,
                    error_class="success_detection_failed",
                    error_message="Could not confirm submission success",
                )

            # 16. Return success.
            return SubmissionOutcome(success=True, submitter=self.name)

        except Exception as exc:
            logger.exception(
                "playwright_strategy_error",
                extra={"job_id": ctx.job.id, "error": str(exc)},
            )
            # Take error screenshot if page is available.
            if page is not None:
                try:
                    data_dir = self._get_data_dir()
                    await capture_error_screenshot(page, data_dir, ctx.job.id)
                except Exception:
                    pass
            return SubmissionOutcome(
                success=False,
                submitter=self.name,
                error_class=type(exc).__name__,
                error_message=str(exc),
            )

    # -- helpers -------------------------------------------------------------

    async def _get_browser_manager(self) -> BrowserManager:
        if self._browser_manager is None:
            self._browser_manager = BrowserManager()
            self._owns_browser = True
        return self._browser_manager

    def _get_session_factory(self) -> Callable:
        if self._session_factory is not None:
            return self._session_factory
        from app.db.base import async_session
        return async_session

    def _get_data_dir(self):
        from app.config import get_settings
        return get_settings().data_dir

    async def _load_settings(self, session):
        from app.settings.service import get_settings_row
        return await get_settings_row(session)

    async def close(self) -> None:
        """Close the BrowserManager if it was created internally."""
        if self._owns_browser and self._browser_manager is not None:
            await self._browser_manager.close()
            self._browser_manager = None

    @property
    def reused_answers(self) -> list[tuple[str, Any]]:
        """Return (field_label, SavedAnswer) pairs auto-filled via matcher."""
        return list(self._reused_answers)


__all__ = ["PlaywrightStrategy", "_is_known_ats_url"]
