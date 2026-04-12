"""Shared pytest fixtures for the Phase 1 test suite.

Only small, opt-in fixtures live here. Nothing is auto-used — tests must
request fixtures explicitly so each case remains legible.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def tmp_fernet_key() -> str:
    """Yield a freshly generated Fernet key (string form)."""
    return Fernet.generate_key().decode()


@pytest.fixture
def env_with_fernet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_fernet_key: str,
    tmp_path: Path,
) -> Iterator[str]:
    """Set the minimum env vars required to construct ``Settings`` cleanly.

    Yields the Fernet key so tests can assert on it or reuse it. Ensures the
    settings cache is cleared on entry and exit so neighbouring tests do not
    see a stale ``Settings`` instance from a previous case.
    """
    from app.config import get_settings

    monkeypatch.setenv("FERNET_KEY", tmp_fernet_key)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("BIND_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield tmp_fernet_key
    finally:
        get_settings.cache_clear()
