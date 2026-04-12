"""Kill-switch: asyncio.Event + DB persistence + scheduler hard-stop.

RESEARCH.md Pattern 3. Per CONTEXT.md, the kill-switch is a *hard stop*:

1. The in-flight asyncio task (held by :class:`SchedulerService`) is cancelled
   via :meth:`asyncio.Task.cancel`; the stub pipeline checkpoints
   :meth:`raise_if_engaged` so long-running stages bail out at the first yield.
2. The APScheduler job is paused so future cron ticks do not start new runs.
3. ``Settings.kill_switch`` is persisted to ``True`` so a container restart
   hydrates into an already-engaged state (per :meth:`hydrate_from_settings`).

Release reverses all three.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.scheduler.service import SchedulerService


class KillSwitch:
    """Process-wide kill switch backed by ``asyncio.Event``.

    Use :meth:`hydrate_from_settings` to construct one from the persisted
    Settings row at lifespan startup.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def is_engaged(self) -> bool:
        return self._event.is_set()

    def _set(self) -> None:
        self._event.set()

    def _clear(self) -> None:
        self._event.clear()

    async def engage(
        self,
        scheduler_service: "SchedulerService",
        session: AsyncSession,
    ) -> None:
        """Engage the kill-switch: persist, pause, cancel."""
        self._set()
        from app.settings.service import set_setting

        await set_setting(session, "kill_switch", True)
        scheduler_service.pause_scheduler()
        scheduler_service.cancel_current_run()

    async def release(
        self,
        scheduler_service: "SchedulerService",
        session: AsyncSession,
    ) -> None:
        """Release the kill-switch: clear, resume the scheduler, persist."""
        self._clear()
        from app.settings.service import set_setting

        await set_setting(session, "kill_switch", False)
        scheduler_service.resume_scheduler()

    async def raise_if_engaged(self) -> None:
        """Raise ``asyncio.CancelledError`` if engaged.

        Every pipeline checkpoint calls this. Raising CancelledError (rather
        than a custom exception) propagates through asyncio's task
        cancellation machinery naturally — the outer ``run_pipeline`` sees
        the same exception whether the task was externally cancelled or the
        inner code called this method.
        """
        if self._event.is_set():
            raise asyncio.CancelledError("kill_switch_engaged")

    @classmethod
    async def hydrate_from_settings(cls, session: AsyncSession) -> "KillSwitch":
        """Build a KillSwitch preloaded from ``Settings.kill_switch``.

        Called once at lifespan startup. If the persisted flag is ``True``,
        the returned switch is already engaged; the lifespan then pauses the
        APScheduler job before yielding to the application.
        """
        from app.settings.service import get_settings_row

        row = await get_settings_row(session)
        ks = cls()
        if row.kill_switch:
            ks._set()
        return ks


__all__ = ["KillSwitch"]
