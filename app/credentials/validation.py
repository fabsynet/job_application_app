"""Credential validation helpers for Anthropic API key and SMTP credentials.

Each validator returns a ``(bool, str)`` tuple: success flag and a
human-readable message suitable for display in the settings flash area.
Both functions save-first-validate-second: the caller encrypts and persists
the credential before invoking validation, so network failures do NOT
prevent storage.
"""

from __future__ import annotations

import asyncio
import smtplib
import socket

import httpx


async def validate_anthropic_key(api_key: str) -> tuple[bool, str]:
    """Validate an Anthropic API key by hitting the /v1/models endpoint.

    Returns (True, message) on success, (False, message) on any failure.
    Network errors are soft failures -- the key is already saved.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        if resp.status_code == 200:
            return (True, "API key is valid")
        if resp.status_code == 401:
            return (False, "Invalid API key")
        return (False, f"Unexpected response: {resp.status_code}")
    except httpx.TimeoutException:
        return (False, "Validation timed out -- key saved but not verified")
    except httpx.ConnectError:
        return (False, "Could not reach Anthropic API -- key saved but not verified")
    except Exception as exc:
        return (False, f"Validation error -- key saved but not verified: {exc}")


def _smtp_check(host: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Synchronous SMTP validation (runs in a thread pool)."""
    try:
        with smtplib.SMTP(host, port, timeout=5) as server:
            server.ehlo()
            if port == 587:
                server.starttls()
                server.ehlo()
            server.login(username, password)
        return (True, "SMTP credentials valid")
    except smtplib.SMTPAuthenticationError:
        return (False, "Authentication failed")
    except (socket.timeout, TimeoutError):
        return (False, "Connection timed out -- credentials saved but not verified")
    except (ConnectionRefusedError, OSError) as exc:
        return (False, f"Connection failed: {exc}")
    except Exception as exc:
        return (False, f"Validation error -- credentials saved but not verified: {exc}")


async def validate_smtp_credentials(
    host: str, port: int, username: str, password: str
) -> tuple[bool, str]:
    """Validate SMTP credentials by attempting a real login.

    Runs the blocking ``smtplib`` call in a thread pool via
    ``asyncio.to_thread`` so the event loop is not blocked.
    """
    return await asyncio.to_thread(_smtp_check, host, int(port), username, password)


__all__ = ["validate_anthropic_key", "validate_smtp_credentials"]
