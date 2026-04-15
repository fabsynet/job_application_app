"""Phase 5 low-confidence holdout decision (SC-2).

Locked: auto-submit only when BOTH conditions hold:

1. Validator passed on first try: ``TailoringRecord.validation_passed is
   True`` **and** ``TailoringRecord.retry_count <= 1``. Per
   :mod:`app.tailoring.engine` line 567, ``retry_count`` is written as
   ``retry + 1`` on success, so ``retry_count == 1`` means the retry
   loop's index-0 pass produced a valid output (i.e. first-try success).
   ``retry_count == 0`` only surfaces on the catastrophic "resume empty
   after PII strip" branch (line 379). ``retry_count >= 2`` means the
   validator rejected at least once. Research pitfall 8 warns about
   this off-by-one; see ``tests/submission/test_holdout.py`` for the
   engine-anchor guard that prevents the semantic from drifting out
   from under this module without a red-flag failure.

2. Keyword coverage is at or above ``user_threshold +
   holdout_margin_pct``. Coverage is the same
   :func:`app.tailoring.docx_writer.compute_keyword_coverage` metric
   used by the Phase 4 dashboard; it re-tokenises the job description
   and counts substring hits in the tailored text.

Everything else falls back to the review queue — in auto mode, a
held-out job stays in ``status='tailored'`` so the user sees it in
the review UI with the :attr:`HoldoutDecision.reason` badge explaining
why it was routed for manual approval.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.discovery.models import Job
from app.tailoring.docx_writer import compute_keyword_coverage
from app.tailoring.models import TailoringRecord


@dataclass(frozen=True)
class HoldoutDecision:
    """Result of :func:`should_auto_submit`.

    :attr:`auto_eligible` is the single yes/no the pipeline acts on;
    :attr:`reason` is a stable string code suitable for structured
    logging and for the queue UI to render as a badge
    ("coverage_below_holdout", "validation_needed_retries", ...).
    :attr:`coverage_pct` and :attr:`required_pct` are zero on the
    early-exit branches (no coverage was computed) and populated on
    the coverage-check branches so callers can surface the exact
    miss to the operator.
    """

    auto_eligible: bool
    reason: str
    coverage_pct: int
    required_pct: int


def should_auto_submit(
    *,
    record: TailoringRecord,
    job: Job,
    tailored_text: str,
    user_threshold: int,
    holdout_margin_pct: int,
) -> HoldoutDecision:
    """Return whether ``record`` may be auto-submitted without review.

    Keyword-only so the pipeline cannot silently swap ``user_threshold``
    and ``holdout_margin_pct``. Both integers are expected in the
    ``0..100`` range; :func:`max` / :func:`min` clamp the computed
    required percentage so a pathological operator config (e.g.
    threshold=95 + margin=50) cannot demand a coverage above 100.
    """
    if record.validation_passed is not True:
        return HoldoutDecision(
            auto_eligible=False,
            reason="validation_not_passed",
            coverage_pct=0,
            required_pct=0,
        )
    # retry_count <= 1 is first-try success (see module docstring).
    if (record.retry_count or 0) > 1:
        return HoldoutDecision(
            auto_eligible=False,
            reason="validation_needed_retries",
            coverage_pct=0,
            required_pct=0,
        )
    coverage = int(
        compute_keyword_coverage(tailored_text, job.description or "") * 100
    )
    required = max(0, min(100, int(user_threshold) + int(holdout_margin_pct)))
    if coverage < required:
        return HoldoutDecision(
            auto_eligible=False,
            reason="coverage_below_holdout",
            coverage_pct=coverage,
            required_pct=required,
        )
    return HoldoutDecision(
        auto_eligible=True,
        reason="auto_eligible",
        coverage_pct=coverage,
        required_pct=required,
    )


__all__ = ["should_auto_submit", "HoldoutDecision"]
