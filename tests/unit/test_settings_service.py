"""Unit tests for ``app.settings.service``."""

from __future__ import annotations

import pytest

from app.settings.service import get_setting, get_settings_row, set_setting


async def test_get_or_create_is_idempotent(async_session) -> None:
    row1 = await get_settings_row(async_session)
    row2 = await get_settings_row(async_session)
    assert row1.id == 1
    assert row2.id == 1
    # Defaults from the SQLModel definition should hold on first insert.
    assert row1.kill_switch is False
    assert row1.dry_run is False
    assert row1.daily_cap == 20


async def test_set_setting_persists(async_session) -> None:
    await set_setting(async_session, "dry_run", True)
    value = await get_setting(async_session, "dry_run")
    assert value is True
    # Mutating a second field should not revert the first.
    await set_setting(async_session, "daily_cap", 5)
    assert await get_setting(async_session, "dry_run") is True
    assert await get_setting(async_session, "daily_cap") == 5


async def test_set_setting_rejects_unknown_field(async_session) -> None:
    with pytest.raises(AttributeError):
        await set_setting(async_session, "bogus_field", True)


async def test_set_setting_bumps_updated_at(async_session) -> None:
    row_before = await get_settings_row(async_session)
    ts_before = row_before.updated_at
    import asyncio

    await asyncio.sleep(0.01)
    await set_setting(async_session, "kill_switch", True)
    row_after = await get_settings_row(async_session)
    assert row_after.updated_at >= ts_before
