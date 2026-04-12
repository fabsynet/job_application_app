"""Unit tests for ``app.scheduler.killswitch``."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.scheduler.killswitch import KillSwitch
from app.settings.service import get_settings_row, set_setting


def _fake_scheduler_service() -> MagicMock:
    svc = MagicMock(name="SchedulerService")
    svc.pause_scheduler = MagicMock()
    svc.resume_scheduler = MagicMock()
    svc.cancel_current_run = MagicMock()
    return svc


async def test_engage_sets_event(async_session) -> None:
    ks = KillSwitch()
    svc = _fake_scheduler_service()

    await ks.engage(svc, async_session)

    assert ks.is_engaged() is True
    svc.pause_scheduler.assert_called_once()
    svc.cancel_current_run.assert_called_once()
    row = await get_settings_row(async_session)
    assert row.kill_switch is True


async def test_release_clears_event(async_session) -> None:
    ks = KillSwitch()
    svc = _fake_scheduler_service()

    await ks.engage(svc, async_session)
    await ks.release(svc, async_session)

    assert ks.is_engaged() is False
    svc.resume_scheduler.assert_called_once()
    row = await get_settings_row(async_session)
    assert row.kill_switch is False


async def test_raise_if_engaged_raises_cancelled_error(async_session) -> None:
    ks = KillSwitch()
    svc = _fake_scheduler_service()
    await ks.engage(svc, async_session)
    with pytest.raises(asyncio.CancelledError):
        await ks.raise_if_engaged()


async def test_raise_if_engaged_noop_when_clear() -> None:
    ks = KillSwitch()
    # Should not raise.
    await ks.raise_if_engaged()


async def test_hydrate_from_settings_preserves_state(async_session) -> None:
    await set_setting(async_session, "kill_switch", True)
    ks = await KillSwitch.hydrate_from_settings(async_session)
    assert ks.is_engaged() is True

    await set_setting(async_session, "kill_switch", False)
    ks2 = await KillSwitch.hydrate_from_settings(async_session)
    assert ks2.is_engaged() is False
