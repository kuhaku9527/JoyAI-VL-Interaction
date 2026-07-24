# SPDX-License-Identifier: Apache-2.0
"""Regression guard for the hermes_api recall-failure logging fix (audit §3 / P1).

Audit finding (code-health-audit-20260723.md):
  hermes_api/main.py:262  ``except Exception: return ""`` silently swallowed any
  recall error -- a downed memory-store or a network blip produced NO log signal,
  making the fail-open path invisible to operators.

Fix (commit 95c7c7a): the bare except now logs a WARNING before falling back:

    except Exception as exc:  # noqa: BLE001 - fail open
        logger.warning("local wiki recall failed, falling back to web search: %s", exc)
        return ""

These tests LOCK that behavior: a recall failure MUST be logged (not swallowed),
while the function still fails OPEN (returns "" so the solve is never blocked).

If the fix is ever reverted to a silent ``except Exception: return ""``, both
tests fail -- that is exactly the regression we want CI to catch.

Run:  python -m pytest services/background-agent/tests -o asyncio_mode=auto
"""

from __future__ import annotations

import logging

import httpx
from hermes_api import main as hapi

LOGGER_NAME = "hermes_api.main"


class _BoomPostClient:
    """Client whose POST raises -- simulates memory-store unreachable."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def __aenter__(self) -> _BoomPostClient:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> None:
        raise self._exc


class _BoomEnterClient:
    """Client whose async-enter raises -- simulates client construction failure."""

    async def __aenter__(self) -> _BoomEnterClient:
        raise httpx.ConnectError("cannot open httpx client")

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> None:
        raise AssertionError("post must not be reached when __aenter__ fails")


def _assert_warned_recall_failure(caplog) -> None:
    assert any(
        r.levelno == logging.WARNING
        and r.name == LOGGER_NAME
        and "local wiki recall failed" in r.getMessage()
        for r in caplog.records
    ), (
        "recall failure must be logged as WARNING on hermes_api.main "
        "(audit P1: must not be silently swallowed)"
    )


async def test_enrich_logs_warning_when_network_raises(monkeypatch, caplog):
    """A ConnectError during recall must be logged, while still failing open."""
    monkeypatch.setattr(
        hapi.httpx,
        "AsyncClient",
        lambda *a, **k: _BoomPostClient(httpx.ConnectError("memory-store down")),
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = await hapi._enrich_with_memory("any question")
    assert result == ""  # fail-open preserved
    _assert_warned_recall_failure(caplog)


async def test_enrich_logs_warning_when_client_entry_raises(monkeypatch, caplog):
    """An exception raised while opening the client must also be logged."""
    monkeypatch.setattr(
        hapi.httpx,
        "AsyncClient",
        lambda *a, **k: _BoomEnterClient(),
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = await hapi._enrich_with_memory("any question")
    assert result == ""
    _assert_warned_recall_failure(caplog)
