# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for memory-store v0.1."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PKG_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@pytest.fixture
def sqlite_path(tmp_path) -> str:
    p = tmp_path / "memory.sqlite"
    yield str(p)
    # cleanup is implicit (tmp_path auto-removed)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Each test runs with a fresh MEMORY_BACKEND=sqlite + tmp sqlite path."""
    monkeypatch.setenv("MEMORY_BACKEND", "sqlite")
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite"))

    # Reimport the backends module so get_backend() reads fresh env, then
    # rebind app.state.backend to the freshly constructed backend.
    import importlib

    from memory_store import app as app_module
    from memory_store import backends

    importlib.reload(backends)
    app_module._reset_backend_for_tests()
    yield
