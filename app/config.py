"""Typed application settings loaded from environment / .env.

The module exposes a single ``get_settings()`` entry point that returns a
cached ``Settings`` instance. Using a cached function (instead of a top-level
``settings = Settings()`` attribute) keeps the module importable under pytest
even when ``FERNET_KEY`` is manipulated by fixtures — callers that need the
live value call ``get_settings.cache_clear()`` between tests.

Fail-fast contract: ``Settings`` raises ``pydantic.ValidationError`` at
construction time if ``FERNET_KEY`` is missing or not a valid Fernet key.
This guarantees the lifespan event in ``app.main`` surfaces bad configuration
before the HTTP port is bound, matching the contract in
``.planning/phases/01-foundation-scheduler-safety-envelope/01-RESEARCH.md``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings.

    Fields use uppercase aliases so ``FERNET_KEY=...`` in the environment
    maps to the lowercase attribute ``fernet_key``. ``extra="ignore"`` allows
    the process to carry unrelated env vars (e.g. ``PATH``) without error.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    fernet_key: str = Field(..., alias="FERNET_KEY")
    tz: str = Field("UTC", alias="TZ")
    bind_address: str = Field("0.0.0.0", alias="BIND_ADDRESS")
    data_dir: Path = Field(Path("/data"), alias="DATA_DIR")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("fernet_key")
    @classmethod
    def _validate_fernet(cls, v: str) -> str:
        """Fail fast on empty or malformed Fernet keys.

        ``Fernet(...)`` itself performs length + base64 validation, so we
        simply attempt construction and translate any error to a ``ValueError``
        (which pydantic wraps into a ``ValidationError``).
        """
        if not v:
            raise ValueError("FERNET_KEY is required")
        try:
            Fernet(v.encode())
        except Exception as exc:  # noqa: BLE001 - pydantic wraps to ValidationError
            raise ValueError(f"FERNET_KEY is not a valid Fernet key: {exc}") from exc
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` instance (cached).

    Tests should call ``get_settings.cache_clear()`` after mutating the
    environment to force re-instantiation.
    """
    return Settings()  # type: ignore[call-arg]
