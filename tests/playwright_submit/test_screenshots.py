"""Unit tests for screenshot capture and cleanup utilities."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.playwright_submit.screenshots import (
    capture_error_screenshot,
    capture_step_screenshot,
    cleanup_old_screenshots,
    screenshot_dir,
)


# -- screenshot_dir ----------------------------------------------------------


def test_screenshot_dir_creates_directory(tmp_path: Path) -> None:
    d = screenshot_dir(tmp_path, job_id=42)
    assert d == tmp_path / "screenshots" / "42"
    assert d.is_dir()


def test_screenshot_dir_idempotent(tmp_path: Path) -> None:
    d1 = screenshot_dir(tmp_path, job_id=7)
    d2 = screenshot_dir(tmp_path, job_id=7)
    assert d1 == d2


# -- capture_step_screenshot -------------------------------------------------


@pytest.mark.asyncio
async def test_capture_step_screenshot(tmp_path: Path) -> None:
    page = AsyncMock()
    rel = await capture_step_screenshot(page, tmp_path, job_id=10, step=3)

    assert rel == str(Path("screenshots") / "10" / "step_3.png")
    expected_path = str(tmp_path / "screenshots" / "10" / "step_3.png")
    page.screenshot.assert_awaited_once_with(path=expected_path)


@pytest.mark.asyncio
async def test_capture_step_screenshot_creates_dir(tmp_path: Path) -> None:
    page = AsyncMock()
    await capture_step_screenshot(page, tmp_path, job_id=99, step=1)
    assert (tmp_path / "screenshots" / "99").is_dir()


# -- capture_error_screenshot ------------------------------------------------


@pytest.mark.asyncio
async def test_capture_error_screenshot(tmp_path: Path) -> None:
    page = AsyncMock()
    rel = await capture_error_screenshot(page, tmp_path, job_id=5)

    assert rel == str(Path("screenshots") / "5" / "error.png")
    expected_path = str(tmp_path / "screenshots" / "5" / "error.png")
    page.screenshot.assert_awaited_once_with(path=expected_path)


# -- cleanup_old_screenshots -------------------------------------------------


def test_cleanup_removes_old_dirs(tmp_path: Path) -> None:
    base = tmp_path / "screenshots"
    old_dir = base / "100"
    old_dir.mkdir(parents=True)
    (old_dir / "step_1.png").write_bytes(b"img")

    # Set mtime to 10 days ago
    old_time = time.time() - (10 * 86_400)
    os.utime(old_dir, (old_time, old_time))

    removed = cleanup_old_screenshots(tmp_path, retention_days=7)
    assert removed == 1
    assert not old_dir.exists()


def test_cleanup_preserves_recent_dirs(tmp_path: Path) -> None:
    base = tmp_path / "screenshots"
    recent_dir = base / "200"
    recent_dir.mkdir(parents=True)
    (recent_dir / "step_1.png").write_bytes(b"img")

    removed = cleanup_old_screenshots(tmp_path, retention_days=7)
    assert removed == 0
    assert recent_dir.exists()


def test_cleanup_preserves_exempt_jobs(tmp_path: Path) -> None:
    base = tmp_path / "screenshots"
    exempt_dir = base / "300"
    exempt_dir.mkdir(parents=True)
    (exempt_dir / "error.png").write_bytes(b"img")

    # Make it old
    old_time = time.time() - (30 * 86_400)
    os.utime(exempt_dir, (old_time, old_time))

    removed = cleanup_old_screenshots(tmp_path, retention_days=7, exempt_job_ids={300})
    assert removed == 0
    assert exempt_dir.exists()


def test_cleanup_no_screenshots_dir(tmp_path: Path) -> None:
    removed = cleanup_old_screenshots(tmp_path, retention_days=7)
    assert removed == 0


def test_cleanup_mixed(tmp_path: Path) -> None:
    """Old dirs removed, recent and exempt preserved."""
    base = tmp_path / "screenshots"

    old_dir = base / "10"
    old_dir.mkdir(parents=True)
    old_time = time.time() - (15 * 86_400)
    os.utime(old_dir, (old_time, old_time))

    recent_dir = base / "20"
    recent_dir.mkdir(parents=True)

    exempt_old_dir = base / "30"
    exempt_old_dir.mkdir(parents=True)
    os.utime(exempt_old_dir, (old_time, old_time))

    removed = cleanup_old_screenshots(tmp_path, retention_days=7, exempt_job_ids={30})
    assert removed == 1
    assert not old_dir.exists()
    assert recent_dir.exists()
    assert exempt_old_dir.exists()
