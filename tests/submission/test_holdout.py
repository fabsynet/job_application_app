"""Unit tests for app.submission.holdout (Plan 05-04 Task 1).

Locks the retry_count semantics: ``retry_count == 1`` means first-try
success per ``app/tailoring/engine.py`` line 567 (written as
``retry + 1``). Plus an engine-anchor guard that re-reads the engine
source at runtime so a future refactor that changes this pattern flies
a red flag before the holdout silently starts held-out every job.
"""
from __future__ import annotations

import pathlib

from app.discovery.models import Job
from app.submission.holdout import HoldoutDecision, should_auto_submit
from app.tailoring.models import TailoringRecord


def _make_job(description: str = "python fastapi postgres docker") -> Job:
    """Build a Job instance (not persisted) with enough fields for the holdout."""
    return Job(
        fingerprint="holdout-test-fp",
        external_id="ext-holdout",
        title="Backend Engineer",
        company="Acme",
        url="https://example.com/acme/job",
        source="greenhouse",
        description=description,
    )


def _make_record(
    *,
    validation_passed: bool | None = True,
    retry_count: int = 1,
) -> TailoringRecord:
    return TailoringRecord(
        job_id=1,
        base_resume_path="/tmp/base.docx",
        validation_passed=validation_passed,
        retry_count=retry_count,
    )


# ---------------------------------------------------------------------------
# Core holdout semantics
# ---------------------------------------------------------------------------


def test_retry_count_1_is_first_try_success() -> None:
    """GUARD: retry_count=1 must be treated as first-try success.

    If ``app/tailoring/engine.py`` ever changes to set ``retry_count=0``
    on success, the other-side engine-anchor test below will also fire.
    Both tests must be updated together in lockstep.
    """
    record = _make_record(validation_passed=True, retry_count=1)
    job = _make_job("python fastapi postgres docker")
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi postgres docker kubernetes",
        user_threshold=50,
        holdout_margin_pct=10,
    )
    assert isinstance(decision, HoldoutDecision)
    assert decision.auto_eligible is True
    assert decision.reason == "auto_eligible"


def test_retry_count_2_held_out_as_validation_needed_retries() -> None:
    """Second-try success (retry_count=2) must still be held out."""
    record = _make_record(validation_passed=True, retry_count=2)
    job = _make_job()
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi postgres docker",
        user_threshold=50,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is False
    assert decision.reason == "validation_needed_retries"


def test_retry_count_0_treated_as_first_try() -> None:
    """retry_count=0 is the catastrophic branch (engine.py line 379).

    Per the module docstring, ``retry_count == 0`` only happens when
    the engine aborted before running a retry at all. In practice
    those records have ``validation_passed=False`` and the validation
    gate fires first, but if one ever sneaks through with
    ``validation_passed=True`` we treat it the same as first-try
    success because ``retry_count <= 1``.
    """
    record = _make_record(validation_passed=True, retry_count=0)
    job = _make_job()
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi postgres docker",
        user_threshold=50,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is True


def test_validation_not_passed_held_out() -> None:
    record = _make_record(validation_passed=False, retry_count=1)
    job = _make_job()
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi postgres docker",
        user_threshold=50,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is False
    assert decision.reason == "validation_not_passed"


def test_validation_none_held_out() -> None:
    """validation_passed=None (never ran) must also be held out."""
    record = _make_record(validation_passed=None, retry_count=1)
    job = _make_job()
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi",
        user_threshold=50,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is False
    assert decision.reason == "validation_not_passed"


def test_coverage_below_threshold_held_out() -> None:
    """user_threshold=60 + margin=10 -> required=70; coverage below held out.

    Job description has 4 long tokens: python, fastapi, postgres, docker.
    Tailored text matches 2 of them -> 50% coverage (below 70%).
    """
    record = _make_record()
    job = _make_job("python fastapi postgres docker")
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi cobol",
        user_threshold=60,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is False
    assert decision.reason == "coverage_below_holdout"
    assert decision.coverage_pct == 50
    assert decision.required_pct == 70


def test_coverage_exactly_at_required_is_eligible() -> None:
    """Coverage == required -> eligible (>= semantics, not strict >)."""
    record = _make_record()
    # 4 keywords, 3 matches -> 75% coverage.
    job = _make_job("python fastapi postgres docker")
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi postgres rails",
        user_threshold=65,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is True
    assert decision.coverage_pct == 75
    assert decision.required_pct == 75


def test_coverage_required_clamped_to_100() -> None:
    """Pathological config threshold=95 + margin=50 clamps to 100 not 145."""
    record = _make_record()
    job = _make_job("python fastapi postgres docker")
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi postgres docker",
        user_threshold=95,
        holdout_margin_pct=50,
    )
    # Required was clamped to 100; coverage 100 -> eligible.
    assert decision.required_pct == 100
    assert decision.coverage_pct == 100
    assert decision.auto_eligible is True


def test_empty_description_holds_out_when_required_nonzero() -> None:
    """No usable JD tokens -> coverage 0; any nonzero required holds out."""
    record = _make_record()
    job = _make_job("")
    decision = should_auto_submit(
        record=record,
        job=job,
        tailored_text="python fastapi",
        user_threshold=50,
        holdout_margin_pct=10,
    )
    assert decision.auto_eligible is False
    assert decision.reason == "coverage_below_holdout"


# ---------------------------------------------------------------------------
# Engine-anchor guard
# ---------------------------------------------------------------------------


def test_engine_still_uses_retry_plus_one() -> None:
    """Lock the ``retry_count = retry + 1`` pattern in engine.py.

    If this test ever fires, either the engine changed its retry_count
    semantics (in which case update ``should_auto_submit``) or the
    file was moved (in which case update the assertion path). Do NOT
    just delete the test.
    """
    src = pathlib.Path("app/tailoring/engine.py").read_text(encoding="utf-8")
    assert "retry_count=retry + 1" in src, (
        "retry_count semantics changed in engine.py — update "
        "app/submission/holdout.py in lockstep"
    )
