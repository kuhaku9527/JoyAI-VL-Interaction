"""Regression: GET /api/services/status must not block the aiohttp event loop.

Before the fix, _services_status_handler called _probe_llm / _probe_tts /
_probe_summary / _probe_asr inline (each is a synchronous httpx call with
a 2-3s timeout). The worst-case wait was ~9s, freezing every other WS
message and HTTP request on the same event loop. The fix dispatches the
four probes to the default executor and gathers them with asyncio.gather,
so the handler returns in O(slowest probe) instead of O(sum of probes).

This test monkey-patches each probe to sleep 0.3s and asserts that the
handler returns in well under the serial 1.2s baseline.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _reset_services_config():
    from joy_interaction_webui import server

    snapshot = dict(server._services_config)
    yield
    server._services_config.clear()
    server._services_config.update(snapshot)


def test_services_status_runs_probes_in_parallel(monkeypatch):
    from joy_interaction_webui import server

    SLOW = 0.3

    def slow_llm(_url):
        time.sleep(SLOW)
        return {"status": "ok", "models": []}

    def slow_summary(_cfg):
        time.sleep(SLOW)
        return {"ok": True, "endpoint": "x", "code": 200}

    def slow_tts(_url):
        time.sleep(SLOW)
        return {"status": "ok", "endpoint": "x", "code": 200}

    def slow_asr(_cfg):
        time.sleep(SLOW)
        return {"ok": True, "model_dir": "x"}

    monkeypatch.setattr(server, "_probe_llm", slow_llm)
    monkeypatch.setattr(server, "_probe_summary", slow_summary)
    monkeypatch.setattr(server, "_probe_tts", slow_tts)
    monkeypatch.setattr(server, "_probe_asr", slow_asr)

    request = _FakeRequest()

    async def _run():
        start = time.perf_counter()
        resp = await server._services_status_handler(request)
        elapsed = time.perf_counter() - start
        return resp, elapsed

    resp, elapsed = asyncio.run(_run())
    # Serial execution would be ~1.2s. Parallel must be comfortably under
    # 2*SLOW with executor scheduling overhead.
    assert elapsed < SLOW * 2, f"handler blocked too long: {elapsed:.3f}s (expected < {SLOW * 2:.3f}s)"
    body = json.loads(resp.text)
    assert set(body.keys()) == {"llm", "summary", "tts", "asr"}
    for slot, item in body.items():
        assert item.get("ok") is True, f"{slot} not ok: {item}"


def test_services_status_surfaces_probe_errors(monkeypatch):
    from joy_interaction_webui import server

    def err_llm(_url):
        return {"status": "error", "reason": "llm down"}

    def ok_summary(_cfg):
        return {"ok": True, "endpoint": "x", "code": 200}

    def ok_tts(_url):
        return {"status": "ok", "endpoint": "x", "code": 200}

    def ok_asr(_cfg):
        return {"ok": True, "model_dir": "x"}

    monkeypatch.setattr(server, "_probe_llm", err_llm)
    monkeypatch.setattr(server, "_probe_summary", ok_summary)
    monkeypatch.setattr(server, "_probe_tts", ok_tts)
    monkeypatch.setattr(server, "_probe_asr", ok_asr)

    request = _FakeRequest()

    async def _run():
        resp = await server._services_status_handler(request)
        return resp

    resp = asyncio.run(_run())
    body = json.loads(resp.text)
    assert body["llm"]["ok"] is False
    assert body["llm"]["reason"] == "llm down"
    assert body["summary"]["ok"] is True
    assert body["tts"]["ok"] is True
    assert body["asr"]["ok"] is True


class _FakeRequest:
    """Minimal stand-in: _services_status_handler only inspects request.method,
    which it does not (the handler is GET-only by routing). Returning a
    trivial object is enough."""

    method = "GET"
    app = None
