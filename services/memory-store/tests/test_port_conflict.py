# SPDX-License-Identifier: Apache-2.0
"""Port-conflict self-check (spec §D-1, ADR 0005 E)."""
from __future__ import annotations

import socket as _socket

import pytest

from memory_store import app as app_module


def test_main_returns_nonzero_on_port_conflict(monkeypatch, tmp_path):
    """Calling ``main()`` while the port is held should return non-zero.

    We bind the target port from this process before invoking ``main()``;
    the pre-bind probe inside ``main()`` must raise OSError and ``main()``
    must return 2 (per ADR 0005 E).
    """
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 8996))
    sock.listen(1)
    try:
        monkeypatch.setenv("MEMORY_PORT", "8996")
        monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite"))
        rc = app_module.main()
        assert rc == 2
    finally:
        sock.close()
