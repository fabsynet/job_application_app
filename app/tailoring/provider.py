"""LLM provider abstraction for Phase 4 tailoring (TAIL-02, TAIL-07).

Every call into a hosted LLM goes through :class:`LLMProvider`. Phase 4
ships a single concrete backend — :class:`AnthropicProvider` wrapping
``AsyncAnthropic`` with prompt caching — but the protocol keeps the door
open for swapping in alternative backends (local models, another vendor,
or a test double) without touching the tailoring pipeline.

The factory :func:`get_provider` pulls the API key out of the encrypted
secrets vault (same Fernet-backed store that holds SMTP and ATS tokens).
Callers should not instantiate ``AnthropicProvider`` directly in
production code — go through the factory so rotation stays centralized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = structlog.get_logger(__name__)


DEFAULT_MODEL = "claude-sonnet-4-5"


@dataclass
class LLMResponse:
    """Normalised response shape returned by every ``LLMProvider``.

    Token counts are separated into four buckets so ``BudgetGuard`` can
    price prompt-cached calls correctly (cache reads cost 10% of input,
    cache writes cost 1.25x input — see ``budget.PRICING``).
    """

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every LLM backend must satisfy.

    ``system`` and ``messages`` follow the Anthropic Messages API shape:
    ``system`` is a list of content blocks (each ``{"type": "text",
    "text": ..., "cache_control": ...}``) and ``messages`` is the usual
    role/content list. A thin shim can translate to other vendor APIs.
    """

    async def complete(
        self,
        system: list[dict],
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.3,
    ) -> LLMResponse: ...


class AnthropicProvider:
    """``LLMProvider`` implementation backed by ``AsyncAnthropic``.

    The SDK is imported inside ``__init__`` so that tests (or modules
    that merely touch the protocol) can import this file without having
    the ``anthropic`` package installed. That same lazy import lets
    ``pip install`` run after the file exists without breaking bootstrap.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        from anthropic import AsyncAnthropic  # local import (see docstring)

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        logger.info("llm_provider_created", model=model)

    async def complete(
        self,
        system: list[dict],
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.3,
    ) -> LLMResponse:
        response = await self._client.messages.create(
            model=self._model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Concatenate text blocks in the response (Anthropic returns a list).
        parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        content = "".join(parts)

        usage: Any = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cache_creation_tokens = int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )
        cache_read_tokens = int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        )

        total_input = input_tokens + cache_creation_tokens + cache_read_tokens
        cache_hit_ratio = (
            cache_read_tokens / total_input if total_input > 0 else 0.0
        )

        logger.info(
            "llm_call_complete",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_hit_ratio=round(cache_hit_ratio, 3),
        )

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            model=self._model,
        )


async def get_provider(session: "AsyncSession") -> AnthropicProvider:
    """Build an :class:`AnthropicProvider` from the encrypted vault.

    Looks up the ``anthropic_api_key`` Secret row, decrypts it via the
    Fernet vault bound to the current ``FERNET_KEY``, and returns a
    fresh provider instance. Raises ``ValueError`` if the key is not
    configured — callers (settings UI / pipeline) translate that into a
    user-facing message.
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.security.fernet import FernetVault
    from app.tailoring.models import (  # noqa: F401  (ensures registration)
        TailoringRecord,
    )

    # Secret is defined in app.db.models.
    from app.db.models import Secret

    result = await session.execute(
        select(Secret).where(Secret.name == "anthropic_api_key")
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError("Anthropic API key not configured")

    vault = FernetVault.from_env(get_settings().fernet_key)
    api_key = vault.decrypt(row.ciphertext)
    logger.info("llm_provider_factory", source="vault")
    return AnthropicProvider(api_key=api_key)


__all__ = [
    "LLMResponse",
    "LLMProvider",
    "AnthropicProvider",
    "get_provider",
    "DEFAULT_MODEL",
]
