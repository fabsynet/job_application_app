"""Single-row Settings accessor.

The ``settings`` table is a singleton (primary key fixed at 1). This module
provides the three operations that every other subsystem needs:

* :func:`get_settings_row` — get-or-create; idempotent.
* :func:`set_setting` — mutate one field and bump ``updated_at``.
* :func:`get_setting` — read one field by name.

The Settings row holds operator-tunable values (kill_switch, dry_run,
daily_cap, delay bounds, timezone, wizard state, keywords). Every mutation
that is not a full row replacement goes through :func:`set_setting` so that
``updated_at`` stays truthful.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Settings


async def get_settings_row(session: AsyncSession) -> Settings:
    """Return the single Settings row, creating it on first access.

    The row is pinned at ``id=1``; concurrent creation is safe because the
    ``--workers 1`` uvicorn contract guarantees a single writer.
    """
    result = await session.execute(select(Settings).where(Settings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = Settings(id=1)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def set_setting(session: AsyncSession, field: str, value: Any) -> Settings:
    """Set a single field on the Settings row and persist ``updated_at``.

    Raises:
        AttributeError: If ``field`` is not a column on the Settings model.
            This is intentional — callers should not be able to typo a field
            and silently persist nothing.
    """
    row = await get_settings_row(session)
    if not hasattr(row, field):
        raise AttributeError(f"Settings has no field {field!r}")
    setattr(row, field, value)
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return row


async def get_setting(session: AsyncSession, field: str) -> Any:
    """Read a single field from the Settings row."""
    row = await get_settings_row(session)
    return getattr(row, field)


__all__ = ["get_settings_row", "set_setting", "get_setting"]
