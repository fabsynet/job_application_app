"""Fernet-based secrets vault (FOUND-06) with scrubber auto-registration.

Every plaintext that passes through this vault — during ``from_env`` (the
master key itself), ``encrypt`` (before the write path can log it), or
``decrypt`` (after the read path produces it) — is registered with the
log scrubber. Net effect: a secret loaded from DB at startup cannot later
appear in a log line even if a future handler accidentally logs it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from app.security.log_scrubber import REGISTRY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class InvalidFernetKey(Exception):
    """Raised for missing, malformed, or rotation-invalid Fernet keys."""


class FernetVault:
    """Thin wrapper around cryptography.fernet.Fernet with scrubber coupling.

    The vault is intentionally small: load-from-env, encrypt, decrypt, and
    a startup helper to pre-register every stored secret. All error paths
    collapse to :class:`InvalidFernetKey` so callers have a single exception
    to handle at boot.
    """

    def __init__(self, fernet: Fernet):
        self._fernet = fernet

    @classmethod
    def from_env(cls, key_str: str) -> "FernetVault":
        """Build a vault from a raw Fernet key string (typically ``$FERNET_KEY``).

        Raises :class:`InvalidFernetKey` if the value is empty or not a valid
        Fernet key. Also registers the master key string itself with the log
        scrubber — a belt-and-braces defense against accidental environment
        dumping in error paths.
        """
        if not key_str:
            raise InvalidFernetKey("FERNET_KEY env var is required")
        try:
            key_bytes = key_str.encode() if isinstance(key_str, str) else key_str
            fernet = Fernet(key_bytes)
        except (ValueError, TypeError) as e:
            raise InvalidFernetKey(f"FERNET_KEY is not a valid Fernet key: {e}") from e
        # Register the master key itself so it cannot appear in any log line.
        REGISTRY.add_literal(key_str)
        return cls(fernet)

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt ``plaintext`` and register it with the scrubber first.

        Registration happens BEFORE the call to ``Fernet.encrypt`` so any
        incidental logging on the write path (or during an exception) is
        already safe.
        """
        REGISTRY.add_literal(plaintext)
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt a stored Fernet token, registering the plaintext.

        A failed decryption is almost always caused by a rotated master key;
        we surface that specifically in the error message so operators see
        "may have changed" rather than a cryptography stack trace.
        """
        try:
            pt = self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as e:
            raise InvalidFernetKey(
                "stored secret cannot be decrypted — FERNET_KEY may have changed"
            ) from e
        REGISTRY.add_literal(pt)
        return pt

    async def register_all_secrets_with_scrubber(self, session: "AsyncSession") -> int:
        """Decrypt every ``Secret`` row so its plaintext is in the registry.

        Called once at startup after DB connectivity is up. Rows that fail
        to decrypt are left in place (preserve for forensic review) and
        logged via structlog using only the secret's ``name`` field, never
        its ciphertext.

        Returns the count of secrets successfully registered.
        """
        from sqlalchemy import select

        from app.db.models import Secret  # local import: db layer ships later

        result = await session.execute(select(Secret))
        rows = result.scalars().all()
        registered = 0
        for row in rows:
            try:
                self.decrypt(row.ciphertext)  # side effect: registers literal
                registered += 1
            except InvalidFernetKey:
                import structlog

                structlog.get_logger(__name__).error(
                    "secret_unreadable_on_boot",
                    secret_name=row.name,
                )
        return registered
