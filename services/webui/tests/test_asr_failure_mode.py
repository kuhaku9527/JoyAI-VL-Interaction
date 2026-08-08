"""Regression: ASR connect-failure handling follows D-2026-08-08-080.

``asr._resolve_asr_failure_mode`` must return:
  * LOCAL_PRIMARY when no external url is configured (local in-process sherpa
    is the intended primary path, NOT a silent fallback),
  * ERROR_NO_FALLBACK when an external url IS configured but unreachable / auth
    failed and the operator has NOT opted into local failover,
  * DEGRADED_FAILOVER when external is down but ASR_ALLOW_LOCAL_FAILOVER=1.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui import asr  # noqa: E402


def test_not_configured_returns_local_primary():
    mode = asr._resolve_asr_failure_mode(
        RuntimeError("ASR url is not configured"), url_configured=False
    )
    assert mode is asr.AsrFailureMode.LOCAL_PRIMARY


def test_configured_unreachable_no_failover_returns_error():
    mode = asr._resolve_asr_failure_mode(ConnectionError("connection refused"), url_configured=True)
    assert mode is asr.AsrFailureMode.ERROR_NO_FALLBACK


def test_configured_unreachable_failover_off_by_default(monkeypatch):
    monkeypatch.delenv("ASR_ALLOW_LOCAL_FAILOVER", raising=False)
    mode = asr._resolve_asr_failure_mode(ConnectionError("connection refused"), url_configured=True)
    assert mode is asr.AsrFailureMode.ERROR_NO_FALLBACK


def test_configured_unreachable_with_failover_optin_returns_degraded(monkeypatch):
    monkeypatch.setenv("ASR_ALLOW_LOCAL_FAILOVER", "1")
    mode = asr._resolve_asr_failure_mode(ConnectionError("connection refused"), url_configured=True)
    assert mode is asr.AsrFailureMode.DEGRADED_FAILOVER
