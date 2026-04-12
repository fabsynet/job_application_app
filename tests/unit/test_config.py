"""Config fail-fast contract tests.

These tests pin the three guarantees ``app.config`` owes the rest of the
system:

1. Missing ``FERNET_KEY`` raises a validation error at construction time.
2. A syntactically-wrong ``FERNET_KEY`` also raises.
3. A valid key produces a ``Settings`` instance with the expected defaults.

Each test isolates the settings cache via ``get_settings.cache_clear()`` so
ordering is irrelevant.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings, get_settings


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("FERNET_KEY", "TZ", "BIND_ADDRESS", "DATA_DIR", "LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()


def test_missing_fernet_key_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    # Point pydantic-settings at an empty .env inside tmp_path so we do not
    # accidentally pick up a real .env file from the repo root.
    (tmp_path / ".env").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_malformed_fernet_key_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("FERNET_KEY", "not-a-real-fernet-key")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        Settings()  # type: ignore[call-arg]

    # The error message should identify the offending field, not leak the bad value.
    assert "FERNET_KEY" in str(exc_info.value) or "fernet_key" in str(exc_info.value)


def test_valid_fernet_key_loads(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.fernet_key == key
    assert settings.tz == "UTC"
    assert settings.bind_address == "0.0.0.0"
    assert settings.log_level == "INFO"


def test_get_settings_is_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.chdir(tmp_path)

    first = get_settings()
    second = get_settings()
    assert first is second  # same cached instance
