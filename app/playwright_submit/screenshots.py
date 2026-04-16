"""Screenshot capture and cleanup utilities for Playwright submissions.

Screenshots are organised under ``{data_dir}/screenshots/{job_id}/`` with
per-step images (``step_{N}.png``) and a dedicated error snapshot
(``error.png``).  Old directories are cleaned up based on mtime.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def screenshot_dir(data_dir: Path, job_id: int) -> Path:
    """Return ``{data_dir}/screenshots/{job_id}/``, creating it if needed."""
    d = data_dir / "screenshots" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def capture_step_screenshot(
    page,
    data_dir: Path,
    job_id: int,
    step: int,
) -> str:
    """Save a step screenshot and return its path relative to *data_dir*."""
    d = screenshot_dir(data_dir, job_id)
    filename = f"step_{step}.png"
    full_path = d / filename
    await page.screenshot(path=str(full_path))
    rel = full_path.relative_to(data_dir)
    logger.debug("Screenshot saved: %s", rel)
    return str(rel)


async def capture_error_screenshot(
    page,
    data_dir: Path,
    job_id: int,
) -> str:
    """Save an error screenshot and return its path relative to *data_dir*."""
    d = screenshot_dir(data_dir, job_id)
    full_path = d / "error.png"
    await page.screenshot(path=str(full_path))
    rel = full_path.relative_to(data_dir)
    logger.info("Error screenshot saved: %s", rel)
    return str(rel)


def cleanup_old_screenshots(
    data_dir: Path,
    retention_days: int,
    exempt_job_ids: set[int] | None = None,
) -> int:
    """Delete screenshot dirs older than *retention_days*.

    Directories whose name (job_id) is in *exempt_job_ids* are preserved
    regardless of age.  Returns the number of directories removed.
    """
    base = data_dir / "screenshots"
    if not base.exists():
        return 0

    exempt = exempt_job_ids or set()
    cutoff = time.time() - (retention_days * 86_400)
    removed = 0

    for child in base.iterdir():
        if not child.is_dir():
            continue
        # Parse job_id from directory name
        try:
            jid = int(child.name)
        except ValueError:
            continue
        if jid in exempt:
            continue
        if child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            logger.info("Removed old screenshot dir: %s", child)
            removed += 1

    return removed
