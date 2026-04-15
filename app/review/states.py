"""Phase 5 job state machine — extends Phase 1-4 string values.

REVW-01: discovered -> matched -> tailored -> pending_review ->
         approved -> submitted -> confirmed | failed | needs_info

Enforcement is service-layer only; `Job.status` remains a plain str.
"""
from __future__ import annotations

CANONICAL_JOB_STATUSES: frozenset[str] = frozenset({
    "discovered",       # Phase 3
    "matched",          # Phase 3
    "queued",           # Phase 3 manual queue
    "tailored",         # Phase 4
    "failed",           # Phase 4
    "pending_review",   # Phase 5 (alias for tailored in review-only mode)
    "approved",         # Phase 5
    "retailoring",      # Phase 5 (re-tailor in flight)
    "skipped",          # Phase 5 (user explicit skip)
    "submitted",        # Phase 5
    "confirmed",        # Phase 5 terminal (future confirm-by-recruiter)
    "needs_info",       # Phase 5 (e.g. missing contact email)
    "applied",          # Phase 3 legacy alias — keep for back-compat
})

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "discovered":     frozenset({"matched", "skipped"}),
    "matched":        frozenset({"tailored", "failed", "skipped"}),
    "queued":         frozenset({"tailored", "failed", "skipped"}),
    "tailored":       frozenset({"pending_review", "approved", "skipped", "retailoring", "failed", "needs_info"}),
    "pending_review": frozenset({"approved", "skipped", "retailoring", "needs_info"}),
    "approved":       frozenset({"submitted", "failed", "needs_info", "skipped"}),
    "retailoring":    frozenset({"tailored", "failed"}),
    "submitted":      frozenset({"confirmed", "failed"}),  # post-submit corrections
    "failed":         frozenset({"retailoring", "skipped", "approved"}),  # user retry
    "skipped":        frozenset(),  # terminal
    "confirmed":      frozenset(),  # terminal
    "needs_info":     frozenset({"approved", "skipped", "retailoring"}),
    "applied":        frozenset(),  # legacy terminal
}


def assert_valid_transition(current: str, target: str) -> None:
    """Raise ValueError if `current -> target` is not an allowed transition.

    Call this at the service layer before writing `Job.status`.
    """
    if target not in CANONICAL_JOB_STATUSES:
        raise ValueError(f"unknown job status: {target!r}")
    if current not in CANONICAL_JOB_STATUSES:
        raise ValueError(f"unknown current status: {current!r}")
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(
            f"illegal transition {current!r} -> {target!r}; "
            f"allowed: {sorted(allowed)}"
        )


__all__ = ["CANONICAL_JOB_STATUSES", "assert_valid_transition"]
