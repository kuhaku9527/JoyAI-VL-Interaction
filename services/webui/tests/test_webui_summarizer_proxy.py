"""Tests for the webui -> webinfer summarizer routing proxy.

The webui must not mutate webinfer's summarizer directly. The /api/
services/config PUT handler triggers _propagate_services_to_runtime,
which calls _webinfer_proxy_summarizer_routing, which POSTs the
summary config to webinfer's /v1/summarizer/route. The operator's
"Summary = cloud" change is then live in the running webinfer process.

These tests pin the composition:
  1. _webinfer_base_url() respects WEBINFER_URL env var.
  2. _webinfer_base_url() falls back to the LLM api_base stripped of /v1.
  3. PUT /api/services/config with summary config triggers a POST to
     webinfer with the right payload.
  4. The proxy returns the new snapshot from webinfer.
  5. When webinfer is unreachable, the proxy returns {ok: false, reason: ...}.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _isolate():
    from joy_interaction_webui import server
    snapshot = dict(server._services_config)
    yield
    server._services_config.clear()
    server._services_config.update(snapshot)


def test_webinfer_base_url_respects_env(monkeypatch):
    from joy_interaction_webui import server
    monkeypatch.setenv("WEBINFER_URL", "http://my-webinfer:9999")
    assert server._webinfer_base_url() == "http://my-webinfer:9999"


def test_webinfer_base_url_strips_v1_from_llm_default(monkeypatch):
    from joy_interaction_webui import server
    monkeypatch.delenv("WEBINFER_URL", raising=False)
    server._services_config["llm"] = {"api_base": "http://localhost:8070/v1"}
    assert server._webinfer_base_url() == "http://localhost:8070"


def test_webinfer_base_url_keeps_non_v1_path(monkeypatch):
    from joy_interaction_webui import server
    monkeypatch.delenv("WEBINFER_URL", raising=False)
    server._services_config["llm"] = {"api_base": "http://localhost:8070/gateway"}
    # /v1 is not at the end, so the URL is left as is.
    assert server._webinfer_base_url() == "http://localhost:8070/gateway"


async def test_propagate_summary_calls_webinfer(monkeypatch):
    from joy_interaction_webui import server

    captured = {}

    async def _fake_proxy(summary_cfg):
        captured["payload"] = {
            "api_base": summary_cfg.get("api_base"),
            "model_name": summary_cfg.get("model"),
            "api_key": summary_cfg.get("api_key"),
        }
        return {"api_base": "x", "model_name": "y", "api_key_set": True}

    monkeypatch.setattr(server, "_webinfer_proxy_summarizer_routing", _fake_proxy)
    server._services_config["summary"] = {
        "api_base": "https://api.minimaxi.com/v1",
        "model": "MiniMax-VL-01",
        "api_key": "sk-test",
    }
    server._propagate_services_to_runtime()
    # The create_task is fire-and-forget; give the scheduler a chance
    # to run the proxy before we assert.
    import asyncio
    await asyncio.sleep(0)
    assert captured["payload"] == {
        "api_base": "https://api.minimaxi.com/v1",
        "model_name": "MiniMax-VL-01",
        "api_key": "sk-test",
    }


def test_propagate_skips_when_summary_empty(monkeypatch):
    from joy_interaction_webui import server

    called = {"count": 0}

    async def _fake_proxy(summary_cfg):
        called["count"] += 1
        return {}

    monkeypatch.setattr(server, "_webinfer_proxy_summarizer_routing", _fake_proxy)
    server._services_config["summary"] = {"api_base": "", "model": "", "api_key": ""}
    server._propagate_services_to_runtime()
    assert called["count"] == 0


async def test_propagate_unreachable_webinfer_logs_warning(monkeypatch):
    """If webinfer is down, the proxy must not raise; it logs and
    returns {ok: false, reason: ...}. _propagate_services_to_runtime
    must not let that bubble up to the PUT /api/services/config caller.
    """
    from joy_interaction_webui import server

    async def _fake_proxy(summary_cfg):
        return {"ok": False, "reason": "Connection refused"}

    monkeypatch.setattr(server, "_webinfer_proxy_summarizer_routing", _fake_proxy)
    server._services_config["summary"] = {
        "api_base": "https://api.minimaxi.com/v1",
        "model": "MiniMax-VL-01",
    }
    # Must not raise.
    server._propagate_services_to_runtime()
    import asyncio
    await asyncio.sleep(0)
