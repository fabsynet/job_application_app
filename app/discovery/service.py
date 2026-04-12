"""Discovery service: CRUD operations for Source rows.

STUB: This file is a minimal placeholder created by plan 03-03 so that
the sources router can import. Plan 03-02 will replace this with the
full implementation.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Source


async def get_all_sources(session: AsyncSession) -> list[Source]:
    """Return all Source rows ordered by creation date."""
    result = await session.execute(
        select(Source).order_by(Source.created_at.desc())
    )
    return list(result.scalars().all())


async def create_source(
    session: AsyncSession,
    slug: str,
    source_type: str,
    display_name: str,
) -> Source:
    """Create and persist a new Source row."""
    source = Source(
        slug=slug,
        source_type=source_type,
        display_name=display_name,
        enabled=True,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def toggle_source(
    session: AsyncSession,
    source_id: int,
    enabled: bool,
) -> None:
    """Toggle the enabled flag on a Source row."""
    result = await session.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        source.enabled = enabled
        await session.commit()


async def delete_source(
    session: AsyncSession,
    source_id: int,
) -> None:
    """Delete a Source row by ID."""
    result = await session.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        await session.delete(source)
        await session.commit()


__all__ = ["get_all_sources", "create_source", "toggle_source", "delete_source"]
