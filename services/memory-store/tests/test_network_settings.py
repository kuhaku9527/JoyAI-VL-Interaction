# SPDX-License-Identifier: Apache-2.0
"""Integration tests for provider health + network settings (ADR-0012 B3/B4).

Uses FastAPI's ASGI TestClient. The network config store is isolated to a temp
file per test via ``config.reset_store`` so the PUT /v1/settings/network
persistence does not leak across tests.

The proxy-routing test is fully offline: the embedder is disabled (``provider=
none``) and the live per-provider proxy path is exercised through an external
provider ping (``main_llm``) whose base URL points at a dead local port, so the
ping fails fast without reaching any real endpoint.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from memory_store import app as app_module
from memory_store import client_factory, config


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Client whose embedder is disabled ('none') so health never touches network."""
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "none")
    app_module._reset_backend_for_tests()
    transport = httpx.ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def proxy_client(tmp_path, monkeypatch):
    """Client that drives the live per-provider proxy path offline.

    ``main_llm`` is given a base URL (a dead local port) so its health ping
    calls ``client_factory.proxy_url_for`` through the app's import; we spy on
    that call. The embedder is disabled so no embedding network call happens.
    """
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("MEMORY_EXT_MAIN_LLM_URL", "http://127.0.0.1:9/v1/messages")
    monkeypatch.setenv("MEMORY_EXT_MAIN_LLM_KEY", "dummy")
    app_module._reset_backend_for_tests()

    spy = MagicMock(wraps=client_factory.proxy_url_for)
    monkeypatch.setattr(app_module, "proxy_url_for", spy)

    transport = httpx.ASGITransport(app=app_module.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield client, spy
    # The test's ``async with client`` block already closes the AsyncClient.


async def test_providers_health_structure(client, tmp_path):
    config.reset_store(str(tmp_path / "network_config.json"))
    async with client as c:
        r = await c.get("/v1/providers/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"memory_store", "embedding", "main_llm", "summarizer", "tts"}
    # Local backend is probed and reports latency.
    assert body["memory_store"]["ok"] is True
    assert isinstance(body["memory_store"]["latency_ms"], int)
    # Embedding slot present (disabled provider → not configured, not a 500).
    assert isinstance(body["embedding"], dict)
    # External providers are reported as not configured with a hint.
    for name in ("main_llm", "summarizer", "tts"):
        assert body[name]["configured"] is False
        assert "hint" in body[name]


async def test_put_network_settings_then_health_routes_proxy(proxy_client, tmp_path):
    client, spy = proxy_client
    config.reset_store(str(tmp_path / "network_config.json"))

    payload = {
        "proxy": {"enabled": True, "url": "http://127.0.0.1:7890"},
        "providers": {
            "main_llm": {"use_proxy": True},
            "siliconflow": {"use_proxy": True},
        },
    }
    async with client as c:
        r = await c.put("/v1/settings/network", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    # Returned body is a re-tested health snapshot with the same structure.
    assert set(body.keys()) == {"memory_store", "embedding", "main_llm", "summarizer", "tts"}
    assert body["memory_store"]["ok"] is True

    # The live health path resolved main_llm's proxy via the client factory.
    assert any(args.args == ("main_llm",) for args in spy.call_args_list), (
        "external provider health must resolve proxy via client_factory"
    )
    # Persisted config routes main_llm and siliconflow (embedding) through the proxy.
    assert client_factory.proxy_url_for("main_llm") == "http://127.0.0.1:7890"
    assert client_factory.proxy_url_for("siliconflow") == "http://127.0.0.1:7890"
    assert client_factory.proxy_url_for("minimax") is None
