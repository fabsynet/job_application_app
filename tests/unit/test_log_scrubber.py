"""The mandated "zero PII in logs" assertion suite (CONTEXT.md, SAFE-03).

Per CONTEXT.md Specific Ideas: "Zero PII in logs is a testable property,
not a vibe. The planner should write an explicit assertion for it."

This file is the explicit assertion. It exercises both layers (stdlib
filter and structlog processor), verifies static regex fallback for
unregistered-but-shaped secrets, and — critically — the integration
test reads the real ``app.log`` file off disk and asserts no sentinel
ever reaches it.
"""

from __future__ import annotations

import logging

import pytest
import structlog

from app.logging_setup import configure_logging
from app.security.log_scrubber import (
    REGISTRY,
    RedactingFilter,
    structlog_scrub_processor,
)

SENTINELS = [
    "sk-ant-api03-DEADBEEFDEADBEEFDEADBEEFDEADBEEF",
    "gAAAAABmMYSECRETFERNETTOKENPAYLOAD==",
    "super-secret-smtp-password-123",
]


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Clear literals before/after each test. Static patterns are preserved."""
    REGISTRY.clear_literals()
    yield
    REGISTRY.clear_literals()


def test_clear_literals_preserves_static_patterns():
    """Sanity: clear_literals() nukes literals but static patterns survive."""
    REGISTRY.clear_literals()
    unregistered = "sk-ant-api03-NEVERREGISTEREDDEADBEEFDEADBEEF"
    scrubbed = REGISTRY.scrub(f"leak {unregistered} here")
    assert unregistered not in scrubbed
    assert "***REDACTED***" in scrubbed


def test_stdlib_logger_scrubs_registered_secrets(caplog):
    for s in SENTINELS:
        REGISTRY.add_literal(s)

    logger = logging.getLogger("scrubber.stdlib.test")
    logger.handlers = []
    logger.addFilter(RedactingFilter())
    logger.setLevel(logging.DEBUG)
    logger.propagate = True

    with caplog.at_level(logging.DEBUG, logger="scrubber.stdlib.test"):
        # %s formatting path
        logger.info("api key is %s", SENTINELS[0])
        # f-string path
        logger.info(f"fernet token {SENTINELS[1]} was seen")
        # password-shaped
        logger.info("smtp pw: %s", SENTINELS[2])

    combined = " ".join(r.getMessage() for r in caplog.records)
    for s in SENTINELS:
        assert s not in combined, f"sentinel leaked: {s!r}"
    assert "REDACTED" in combined


def test_structlog_processor_scrubs_event_dict():
    captured: list[dict] = []

    def capture_processor(logger, name, event_dict):
        captured.append(dict(event_dict))
        # Drop so the terminal logger doesn't also try to render.
        raise structlog.DropEvent

    for s in SENTINELS:
        REGISTRY.add_literal(s)

    structlog.configure(
        processors=[structlog_scrub_processor, capture_processor],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        cache_logger_on_first_use=False,
    )
    log = structlog.get_logger("scrubber.structlog.test")
    log.info("event", api_key=SENTINELS[0], smtp_pwd=SENTINELS[2], nested={"token": SENTINELS[1]})

    assert captured, "capture_processor never ran"
    ev = captured[0]
    for s in SENTINELS:
        for v in ev.values():
            assert s not in str(v), f"sentinel {s!r} leaked into event_dict"
    # Spot check the REDACTED marker is present.
    assert any("REDACTED" in str(v) for v in ev.values())


def test_static_patterns_catch_unregistered_anthropic_keys(caplog):
    unregistered = "sk-ant-api03-THISKEYWASNEVERREGISTEREDDEADBEEF"

    logger = logging.getLogger("scrubber.static.test")
    logger.handlers = []
    logger.addFilter(RedactingFilter())
    logger.setLevel(logging.DEBUG)
    logger.propagate = True

    with caplog.at_level(logging.DEBUG, logger="scrubber.static.test"):
        logger.info("config loaded: %s", unregistered)

    assert unregistered not in caplog.text
    assert "REDACTED" in caplog.text


def test_scrubber_does_not_mutate_short_words(caplog):
    """4-char minimum: 'a' must not be treated as a redactable literal."""
    REGISTRY.add_literal("a")  # expected no-op

    logger = logging.getLogger("scrubber.shortword.test")
    logger.handlers = []
    logger.addFilter(RedactingFilter())
    logger.setLevel(logging.DEBUG)
    logger.propagate = True

    with caplog.at_level(logging.DEBUG, logger="scrubber.shortword.test"):
        logger.info("an apple a day")

    assert "an apple a day" in caplog.text
    assert "REDACTED" not in caplog.text


def test_integration_configure_logging_then_log(tmp_path):
    """End-to-end: sentinel logged via stdlib must not reach app.log on disk."""
    configure_logging("INFO", tmp_path)

    sentinel = "integration-sentinel-abcdef123456"
    REGISTRY.add_literal(sentinel)

    log = logging.getLogger("scrubber.integration.test")
    log.info("user-provided token is %s right here", sentinel)

    # Flush all handlers attached to root so the FileHandler writes to disk.
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "app.log"
    assert log_file.exists(), "app.log was not created by configure_logging"
    contents = log_file.read_text(encoding="utf-8")
    assert sentinel not in contents, f"sentinel leaked to disk: {log_file}"
    assert "REDACTED" in contents
