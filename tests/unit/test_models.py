"""Unit tests for the SQLModel Phase 1 tables.

These tests do not touch an actual database — they only assert on class
construction, defaults, and metadata registration. Integration coverage
(migrate → insert → query) arrives with later plans once the scheduler has
something to write.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Ensure app.config can import without a real .env on disk."""
    from app.config import get_settings

    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_models_import_cleanly() -> None:
    from sqlmodel import SQLModel

    from app.db import models  # noqa: F401  - registers tables on metadata

    table_names = set(SQLModel.metadata.tables.keys())
    assert {"settings", "secrets", "runs", "rate_limit_counters"} <= table_names


def test_settings_defaults() -> None:
    from app.db.models import Settings

    row = Settings()
    assert row.id == 1
    assert row.kill_switch is False
    assert row.dry_run is False
    assert row.daily_cap == 20
    assert row.delay_min_seconds == 30
    assert row.delay_max_seconds == 120
    assert row.timezone == "UTC"
    assert row.wizard_complete is False
    assert row.keywords_csv == ""


def test_run_counts_is_empty_dict_by_default() -> None:
    from app.db.models import Run

    run = Run()
    assert run.counts == {}
    assert run.status == "running"
    assert run.dry_run is False
    assert run.triggered_by == "scheduler"
    assert run.failure_reason is None


def test_rate_limit_counter_defaults() -> None:
    from app.db.models import RateLimitCounter

    counter = RateLimitCounter(day="2026-04-11")
    assert counter.day == "2026-04-11"
    assert counter.submitted_count == 0


def test_canonical_failure_reasons_set() -> None:
    from app.db.models import CANONICAL_FAILURE_REASONS

    expected = {"killed", "rate_limit", "error", "dry_run_skip", "crashed"}
    assert set(CANONICAL_FAILURE_REASONS) == expected
