"""Integration regression: external ASR unreachable must NOT silently degrade.

Per D-2026-08-08-080, when an external ASR url is configured but
``connect_asr`` fails, ``asr_websocket_handler`` must surface an explicit
error frame to the browser and must NOT send a fake ``connected`` status.
The handler is exercised end-to-end through a self-contained aiohttp server
(no pytest plugin needed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import aiohttp

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui import asr  # noqa: E402


class _FakeEngine:
    """Minimal stand-in for the in-process sherpa engine in tests."""

    def __init__(self):
        self.last_text = ""
        self.start_count = 0

    def start(self):
        self.start_count += 1

    def feed_chunk(self, chunk):
        pass


async def _start_server(handler):
    app = aiohttp.web.Application()
    app.router.add_get("/ws/asr", handler)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}/ws/asr"


async def test_handler_external_unreachable_sends_error_not_connected(monkeypatch):
    async def _raise_connect(session_id):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(asr, "connect_asr", _raise_connect)
    monkeypatch.setattr(asr, "get_asr_url", lambda: "ws://127.0.0.1:9999/ws/asr")
    monkeypatch.delenv("ASR_ALLOW_LOCAL_FAILOVER", raising=False)

    runner, url = await _start_server(asr.asr_websocket_handler)
    try:
        async with aiohttp.ClientSession() as session, session.ws_connect(url) as ws:
            msg = await ws.receive()
            assert msg.type == aiohttp.WSMsgType.TEXT
            payload = json.loads(msg.data)
            assert payload["type"] == "error"
            assert "external ASR unreachable" in payload["message"]
            assert payload["type"] != "status"
    finally:
        await runner.cleanup()


async def test_handler_not_configured_connects_local_primary(monkeypatch):
    """No external url configured -> local in-proc sherpa is the primary path
    and the browser receives a normal ``connected`` status (no error, no
    ``degraded`` tag).
    """

    async def _raise_not_configured(session_id):
        raise RuntimeError("ASR url is not configured")

    monkeypatch.setattr(asr, "connect_asr", _raise_not_configured)
    monkeypatch.setattr(asr, "get_asr_url", lambda: "")
    monkeypatch.setattr(asr, "_get_inproc_asr", _FakeEngine)

    runner, url = await _start_server(asr.asr_websocket_handler)
    try:
        async with aiohttp.ClientSession() as session, session.ws_connect(url) as ws:
            msg = await ws.receive()
            assert msg.type == aiohttp.WSMsgType.TEXT
            payload = json.loads(msg.data)
            assert payload.get("type") == "status"
            assert payload.get("message") == "connected"
            assert payload.get("degraded") is not True
    finally:
        await runner.cleanup()
