"""Phase 5 SMTP credential loader — reads Secret rows, decrypts via Fernet.

Mirrors the ``get_provider`` pattern in :mod:`app.tailoring.provider`:
the decryption is centralised so consumers never hand-roll Secret lookups
and every plaintext passes through the :class:`FernetVault` scrubber so
credentials cannot leak into structlog output.

Research pitfall 7: ``smtp_port`` is persisted as a string ciphertext
(``_upsert_secret(..., str(smtp_port))`` in ``settings.py``). It MUST be
coerced to ``int`` before being handed to :mod:`aiosmtplib`, which
type-checks the ``port`` argument at connect time.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Secret
from app.security.fernet import FernetVault


class SmtpCredsMissing(Exception):
    """Raised when a required ``smtp_*`` :class:`Secret` row is absent.

    The missing field name is attached as :attr:`name` so the pipeline
    (Plan 05-04) can stamp the Job record with a precise ``needs_info``
    reason without re-parsing the exception message.
    """

    def __init__(self, name: str):
        super().__init__(f"SMTP credential missing: {name}")
        self.name = name


@dataclass(frozen=True)
class SmtpCreds:
    """Decrypted SMTP credentials ready for :func:`send_via_smtp`."""

    host: str
    port: int
    username: str
    password: str


_REQUIRED = ("smtp_host", "smtp_port", "smtp_user", "smtp_password")


async def load_smtp_creds(session: AsyncSession) -> SmtpCreds:
    """Decrypt the four ``smtp_*`` Secret rows into an :class:`SmtpCreds`.

    Raises :class:`SmtpCredsMissing` on the first missing row — callers
    should catch and flip the job to a ``needs_info`` state rather than
    retry (a missing credential will not be fixed by a retry loop).

    ``get_settings`` is imported lazily so that integration tests which
    ``importlib.reload(app.config)`` under a ``live_app`` fixture do not
    pin this module to a stale LRU cache (Phase 4 pitfall, see STATE.md
    04-05 blocker note on ``app.resume.service``).
    """
    from app.config import get_settings as _get_settings

    vault = FernetVault.from_env(_get_settings().fernet_key)
    raw: dict[str, str] = {}
    for name in _REQUIRED:
        result = await session.execute(select(Secret).where(Secret.name == name))
        row = result.scalar_one_or_none()
        if row is None:
            raise SmtpCredsMissing(name)
        raw[name] = vault.decrypt(row.ciphertext)
    # Research pitfall 7: smtp_port round-trips as a string, coerce here.
    return SmtpCreds(
        host=raw["smtp_host"],
        port=int(raw["smtp_port"]),
        username=raw["smtp_user"],
        password=raw["smtp_password"],
    )


__all__ = ["SmtpCreds", "SmtpCredsMissing", "load_smtp_creds"]
