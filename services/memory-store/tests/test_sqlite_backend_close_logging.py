# SPDX-License-Identifier: Apache-2.0
"""Regression tests for audit section 3 / B007: sqlite close must log, not swallow.

Guards the fix in
``services/memory-store/src/memory_store/backends/sqlite_backend.py`` where
``SqliteBackend.close()`` now logs a WARNING when ``conn.close()`` raises
instead of silently passing (``except Exception: pass``).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from memory_store.backends.sqlite_backend import SqliteBackend

LOGGER_NAME = "memory_store.backends.sqlite_backend"


def test_close_logs_warning_when_conn_close_raises(tmp_path, caplog):
    backend = SqliteBackend(str(tmp_path / "mem.sqlite"))
    boom = RuntimeError("disk vanished mid-close")
    backend._conn = MagicMock()
    backend._conn.close.side_effect = boom

    # best-effort cleanup: the exception must NOT propagate out of close().
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        backend.close()

    assert any(
        r.levelno == logging.WARNING and "sqlite connection close failed" in r.getMessage()
        for r in caplog.records
    ), "sqlite close failure must be logged (audit B007: must not silently swallow)"


def test_close_is_quiet_when_conn_ok(tmp_path, caplog):
    backend = SqliteBackend(str(tmp_path / "mem.sqlite"))
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        backend.close()  # real close of a freshly opened db; should be silent
    assert not any(r.levelno == logging.WARNING for r in caplog.records), (
        "a clean sqlite close should not emit WARNING logs"
    )
