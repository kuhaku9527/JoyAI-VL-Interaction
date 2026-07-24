# SPDX-License-Identifier: Apache-2.0
"""Regression tests for audit section 3 / B007: shutdown cleanup errors must be logged.

Guards the fix in ``services/webinfer/session.py`` where
``SessionMixin.stop_background_tasks()`` now logs a WARNING when the background
cleanup task raises a non-CancelledError instead of silently passing
(``except (asyncio.CancelledError, Exception): pass``).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from session import SessionMixin  # noqa: E402

LOGGER_NAME = "streaming_infer_adapter"


async def _raise_on_cancel():
    # Simulate a cleanup task that fails rather than cleanly cancelling:
    # the CancelledError from stop_background_tasks() is converted into a real
    # exception, which is exactly the branch the fix now logs.
    try:
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        raise RuntimeError("cleanup exploded during shutdown") from None


@pytest.mark.asyncio
async def test_stop_background_tasks_logs_warning_when_cleanup_raises(caplog):
    mixin = SessionMixin()
    mixin.sessions = {}
    mixin.memory_store = MagicMock()
    mixin.memory_store.aclose = AsyncMock()

    mixin._cleanup_task = asyncio.ensure_future(_raise_on_cancel())
    await asyncio.sleep(0.05)  # let the task enter its sleep()

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        await mixin.stop_background_tasks()

    assert mixin._cleanup_task is None
    assert any(
        r.levelno == logging.WARNING and "cleanup task raised during shutdown" in r.getMessage()
        for r in caplog.records
    ), "cleanup-task shutdown exception must be logged (audit B007: must not silently swallow)"
