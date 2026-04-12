"""FastAPI dependency providers for the web layer.

The dashboard, toggles, runs and settings routers all share the same handful
of collaborators (DB session, scheduler service, kill-switch, Fernet vault,
rate limiter). Centralising the lookup here keeps the routers free of
``request.app.state.*`` attribute strings and makes them trivial to override
in tests.
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a scoped ``AsyncSession`` and commit-less close on exit."""
    async with async_session() as session:
        yield session


def get_scheduler(request: Request):
    """Return the ``SchedulerService`` hung off the FastAPI lifespan."""
    return request.app.state.scheduler


def get_killswitch(request: Request):
    """Return the process-wide ``KillSwitch``."""
    return request.app.state.killswitch


def get_vault(request: Request):
    """Return the Fernet vault built at lifespan startup."""
    return request.app.state.vault


def get_rate_limiter(request: Request):
    """Return the live ``RateLimiter`` (mutable at runtime via /settings/limits)."""
    return request.app.state.rate_limiter


__all__ = [
    "get_session",
    "get_scheduler",
    "get_killswitch",
    "get_vault",
    "get_rate_limiter",
]
