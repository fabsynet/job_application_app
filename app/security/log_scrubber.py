"""Two-layer log scrubber enforcing SAFE-03 "PII/resume never in logs".

Layer 1: stdlib logging.Filter (catches uvicorn/SQLAlchemy/APScheduler/stdlib).
Layer 2: structlog processor (catches typed values in structured events, placed
BEFORE JSONRenderer so we scrub values, not rendered JSON strings).

Both layers pull from a single module-level SecretRegistry singleton. The registry
supports runtime registration (users add API keys via UI at runtime, and those keys
must be added to the registry at that moment — see CONTEXT.md locked decisions).

Belt-and-braces static regex patterns catch unregistered leaks for common secret
shapes (Anthropic sk-ant-*, OpenAI sk-*, Fernet gAAAAA* tokens, password=value).
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

REDACTED = "***REDACTED***"

# Static fallback patterns — belt-and-braces for unregistered leaks.
# Ordered from most-specific to least-specific.
_STATIC_PATTERN_SOURCES: list[str] = [
    r"sk-ant-[A-Za-z0-9\-_]{20,}",                        # Anthropic
    r"sk-[A-Za-z0-9]{32,}",                               # OpenAI-shape
    r"gAAAAA[A-Za-z0-9\-_=]{20,}",                        # Fernet token prefix
    r"(?i)password[\"'=:\s]+[^\s\"']{4,}",                # password=value leak
]

# Minimum length for a literal to be registered — avoids nuking everyday words
# like "a", "the", "and" which would turn every log line into redaction soup.
_MIN_LITERAL_LEN = 4


class SecretRegistry:
    """Thread-safe registry of literals + static patterns to redact from logs.

    This is a singleton (see module-level ``REGISTRY``). Runtime registration
    is supported so that secrets entered via the UI at runtime get their
    plaintexts added before they have any chance to appear in a log line.
    """

    def __init__(self) -> None:
        self._literals: set[str] = set()
        self._patterns: list[re.Pattern[str]] = [
            re.compile(src) for src in _STATIC_PATTERN_SOURCES
        ]
        self._lock = threading.Lock()

    def add_literal(self, value: str) -> None:
        """Register an exact literal string to redact.

        Values shorter than ``_MIN_LITERAL_LEN`` are silently ignored to avoid
        accidentally redacting common short words. Non-strings are ignored.
        """
        if not isinstance(value, str):
            return
        if len(value) < _MIN_LITERAL_LEN:
            return
        with self._lock:
            self._literals.add(value)

    def clear_literals(self) -> None:
        """Clear the literals set. TEST-ONLY — do not use in production code.

        Static patterns are NOT cleared; they live on ``_patterns`` and
        continue to provide fallback redaction after this call.
        """
        with self._lock:
            self._literals.clear()

    def scrub(self, text: Any) -> Any:
        """Replace all registered literals and static patterns with REDACTED.

        Non-string input is returned unchanged. Literals are replaced first
        (longest-first to prevent a short literal eating a longer one), then
        static regex patterns are applied.
        """
        if not isinstance(text, str):
            return text
        with self._lock:
            literals = sorted(self._literals, key=len, reverse=True)
            patterns = list(self._patterns)
        out = text
        for lit in literals:
            if lit and lit in out:
                out = out.replace(lit, REDACTED)
        for pat in patterns:
            out = pat.sub(REDACTED, out)
        return out


# Module-level singleton. Both RedactingFilter and structlog_scrub_processor
# pull from this one instance so runtime-registered secrets are visible to both.
REGISTRY = SecretRegistry()


class RedactingFilter(logging.Filter):
    """stdlib logging filter that mutates record.msg/args in place.

    Why mutate instead of re-emit: ``record.getMessage()`` formats ``msg % args``
    lazily at handler time. If we scrub only the post-format string (e.g. by
    replacing ``record.msg`` after formatting), args still contain the raw
    secret. Mutating msg+args before handler emission is the correct hook.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        if isinstance(record.msg, str):
            record.msg = REGISTRY.scrub(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    REGISTRY.scrub(a) if isinstance(a, str) else a for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (REGISTRY.scrub(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
        return True


def structlog_scrub_processor(
    logger: Any, name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor that scrubs string values in the event_dict.

    MUST be placed BEFORE ``JSONRenderer`` in the processor chain so we scrub
    typed values, not a rendered JSON string where literal/regex boundaries
    may have been altered by escaping. See RESEARCH.md pitfall
    "Structlog vs stdlib redaction ordering".

    Performs shallow recursion one level into nested dicts and lists — logs
    very rarely go deeper, and unbounded recursion in a hot path is a footgun.
    """

    def _scrub_value(v: Any) -> Any:
        if isinstance(v, str):
            return REGISTRY.scrub(v)
        if isinstance(v, dict):
            return {k: (REGISTRY.scrub(x) if isinstance(x, str) else x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            scrubbed = [REGISTRY.scrub(x) if isinstance(x, str) else x for x in v]
            return type(v)(scrubbed) if isinstance(v, tuple) else scrubbed
        return v

    for key in list(event_dict.keys()):
        event_dict[key] = _scrub_value(event_dict[key])
    return event_dict
