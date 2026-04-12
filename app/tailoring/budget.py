"""Budget enforcement for LLM spend (TAIL-08).

``BudgetGuard`` is the single gate every tailoring call must pass
through before it hits the Anthropic API, and the single recorder
every completed call must debit afterwards. It combines three
responsibilities that are easy to get wrong if they live in separate
modules:

1. **Month rollover.** Spend accumulates on the singleton ``Settings``
   row keyed to ``budget_month`` (YYYY-MM, UTC). On first call of a
   new month the counter is reset to zero and ``budget_month`` is
   stamped. No cron job required.

2. **Threshold evaluation.** Two thresholds are exposed:
   - 80% soft limit → ``is_warning=True`` so the UI can show a banner.
   - 100% hard halt → ``can_proceed=False`` so the pipeline stops.
   A zero cap (``budget_cap_dollars == 0``) means unlimited.

3. **Atomic debit + ledger.** ``debit`` acquires a per-process
   ``asyncio.Lock`` so two concurrent tailoring tasks cannot race the
   spend counter, then writes both the incremented Settings total and
   a ``CostLedger`` row in the same transaction. Research Pitfall 6
   called this out explicitly.

Pricing is a class-level dict so tests can monkeypatch it without
touching the DB.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from app.settings.service import get_settings_row

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = structlog.get_logger(__name__)


class BudgetGuard:
    """Serialized budget checker/debiter for Anthropic LLM calls."""

    # 80% soft limit → warning banner; 100% hard halt.
    WARN_THRESHOLD: float = 0.80

    # Per-MTok pricing in USD. Extend as new models come online.
    # Keys are Anthropic model names; values are dollars per million tokens.
    PRICING: dict[str, dict[str, float]] = {
        "claude-sonnet-4-5": {
            "input": 3.0,
            "output": 15.0,
            "cache_read": 0.30,
            "cache_write": 3.75,
        },
    }

    def __init__(self) -> None:
        # Serializes check+debit across concurrent tailoring coroutines.
        # Per-process is sufficient — the uvicorn contract is --workers 1.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Pure helpers
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_cost(
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        model: str = "claude-sonnet-4-5",
    ) -> float:
        """Return the dollar cost for a single call, rounded to 6dp.

        Unknown models fall back to ``claude-sonnet-4-5`` pricing so a
        newly-released model never causes a KeyError in production —
        the mis-estimation will surface in the ledger, not as a crash.
        """
        rates = BudgetGuard.PRICING.get(
            model, BudgetGuard.PRICING["claude-sonnet-4-5"]
        )
        cost = (
            (input_tokens / 1_000_000) * rates["input"]
            + (output_tokens / 1_000_000) * rates["output"]
            + (cache_read_tokens / 1_000_000) * rates["cache_read"]
            + (cache_write_tokens / 1_000_000) * rates["cache_write"]
        )
        return round(cost, 6)

    @staticmethod
    def _current_month() -> str:
        """YYYY-MM in UTC, matching ``Settings.budget_month`` format."""
        return datetime.utcnow().strftime("%Y-%m")

    # ------------------------------------------------------------------
    # DB-bound operations
    # ------------------------------------------------------------------

    async def check_budget(
        self, session: "AsyncSession"
    ) -> tuple[bool, float, float, bool]:
        """Return ``(can_proceed, spent, cap, is_warning)``.

        Also performs the month-rollover reset inline: if the stored
        ``budget_month`` does not match the current UTC month, the
        spend counter is zeroed and the month stamp is updated before
        the thresholds are evaluated.
        """
        row = await get_settings_row(session)
        current_month = self._current_month()

        if row.budget_month != current_month:
            logger.info(
                "budget_month_rollover",
                previous_month=row.budget_month or "(unset)",
                new_month=current_month,
                previous_spent=row.budget_spent_dollars,
            )
            row.budget_spent_dollars = 0.0
            row.budget_month = current_month
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)

        spent = float(row.budget_spent_dollars)
        cap = float(row.budget_cap_dollars)

        # cap <= 0 means "no cap" — unlimited spend.
        if cap <= 0:
            logger.info(
                "budget_check",
                spent=spent,
                cap=cap,
                can_proceed=True,
                is_warning=False,
                uncapped=True,
            )
            return (True, spent, 0.0, False)

        is_warning = spent >= cap * self.WARN_THRESHOLD
        can_proceed = spent < cap

        logger.info(
            "budget_check",
            spent=spent,
            cap=cap,
            can_proceed=can_proceed,
            is_warning=is_warning,
        )

        return (can_proceed, spent, cap, is_warning)

    async def debit(
        self,
        session: "AsyncSession",
        cost_dollars: float,
        record_id: int,
        call_type: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
    ) -> None:
        """Increment spend and append a ``CostLedger`` row atomically.

        Takes the instance lock so two tailoring coroutines cannot
        both read "spent=$9.99" and both decide to proceed when the
        cap is $10. Research Pitfall 6.
        """
        # Local import so this module can load before 04-01's models
        # are present at bootstrap (the two plans run in parallel).
        from app.tailoring.models import CostLedger

        async with self._lock:
            row = await get_settings_row(session)
            row.budget_spent_dollars = float(row.budget_spent_dollars) + float(
                cost_dollars
            )
            row.updated_at = datetime.utcnow()

            ledger = CostLedger(
                tailoring_record_id=record_id,
                call_type=call_type,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                cost_dollars=float(cost_dollars),
                month=self._current_month(),
            )
            session.add(ledger)

            await session.commit()

        logger.info(
            "budget_debit",
            record_id=record_id,
            call_type=call_type,
            model=model,
            cost_dollars=round(float(cost_dollars), 6),
            new_spent=row.budget_spent_dollars,
        )


__all__ = ["BudgetGuard"]
