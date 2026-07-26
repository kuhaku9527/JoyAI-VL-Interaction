"""Tests for the [Local Wiki] F1-F4 webui gateway routes (ADR-0012).

The webui is the single SPA gateway. Provider health (B3) and network
settings (B4) are OWNED by the backend (memory-store, #36); the gateway
only FORWARDS them. The knowledge-base surface (F4) is also proxied, except
the pasted-markdown entry which the gateway stages as a temp file and forwards
to the memory-store sync endpoint (browsers cannot write files).

These tests pin the contract without requiring the real backends:
  * Route-registration checks assert the proxy wiring exists in server.py.
  * A fake in-process memory-store (TestServer) serves the real JSON shapes
    so we can assert the gateway forwards/transforms correctly.
  * Dead-port cases assert graceful 502 when memory-store is unreachable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

WEBUI_SRC = Path(__file__).resolve().parents[1] / "src"
if str(WEBUI_SRC) not in sys.path:
    sys.path.insert(0, str(WEBUI_SRC))

from joy_interaction_webui import server  # noqa: E402  (needs sys.path above)

SERVER_SRC = WEBUI_SRC / "joy_interaction_webui" / "server.py"


def _server_source() -> str:
    return SERVER_SRC.read_text(encoding="utf-8")


# -- fake in-process memory-store ----------------------------------------------


@pytest.fixture
async def fake_ms():
    """Stand-in for the memory-store service; serves the real JSON contract."""

    async def health(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "memory_store": {"ok": True, "latency_ms": 3},
                "embedding": {"ok": False, "provider": "siliconflow", "error": "no balance"},
                "main_llm": {"ok": False, "configured": False, "error": "not configured"},
                "summarizer": {"ok": False, "configured": False, "error": "not configured"},
                "tts": {"ok": False, "configured": False, "error": "not configured"},
            }
        )

    async def get_settings(_: web.Request) -> web.Response:
        return web.json_response(
            {
                "proxy": {"enabled": False, "url": "http://127.0.0.1:7890"},
                "providers": {"siliconflow": {"use_proxy": False}, "gemini": {"use_proxy": True}},
            }
        )

    async def put_settings(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response({"received": body, "health": {"memory_store": {"ok": True}}})

    async def get_namespaces(_: web.Request) -> web.Response:
        return web.json_response(
            {"namespaces": [{"namespace": "wiki:zelda", "blocks": 12, "indexed": 8}]}
        )

    async def delete_namespace(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "namespace": request.match_info["namespace"],
                "deleted_rows": 5,
                "index_file_removed": True,
            }
        )

    async def sync(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        return web.json_response(
            {
                "namespace": body.get("namespace"),
                "files": 1,
                "chunks": 3,
                "embedded": 3,
                "skipped_unchanged": 0,
                "dropped": 0,
                "errors": [],
            }
        )

    app = web.Application()
    app.router.add_get("/v1/providers/health", health)
    app.router.add_get("/v1/settings/network", get_settings)
    app.router.add_put("/v1/settings/network", put_settings)
    app.router.add_get("/v1/namespaces", get_namespaces)
    app.router.add_delete("/v1/namespaces/{namespace}", delete_namespace)
    app.router.add_post("/v1/external/sync", sync)
    async with TestServer(app) as srv:
        yield srv


# -- gateway app fixture -------------------------------------------------------


@pytest.fixture
async def app(fake_ms):
    application = web.Application()
    application.router.add_get("/v1/providers/health", server._proxy_to_memory_store)
    application.router.add_get("/v1/settings/network", server._proxy_to_memory_store)
    application.router.add_put("/v1/settings/network", server._proxy_to_memory_store)
    application.router.add_get("/v1/namespaces", server._proxy_to_memory_store)
    application.router.add_post("/v1/external/sync", server._proxy_to_memory_store)
    application.router.add_post("/v1/external/ingest-text", server._ingest_text_handler)
    application.router.add_delete("/v1/namespaces/{namespace}", server._proxy_to_memory_store)
    server.MEMORY_STORE_URL = f"http://{fake_ms.host}:{fake_ms.port}"
    yield application


@pytest.fixture
async def client(app):
    async with TestServer(app) as srv, TestClient(srv) as c:
        yield c


# -- route-registration static checks -----------------------------------------


def test_health_proxy_route_registered():
    assert 'add_get("/v1/providers/health", _proxy_to_memory_store)' in _server_source()


def test_network_settings_routes_registered():
    src = _server_source()
    assert 'add_get("/v1/settings/network", _proxy_to_memory_store)' in src
    assert 'add_put("/v1/settings/network", _proxy_to_memory_store)' in src


def test_memory_store_proxy_routes_registered():
    src = _server_source()
    assert 'add_get("/v1/namespaces", _proxy_to_memory_store)' in src
    assert 'add_post("/v1/external/sync", _proxy_to_memory_store)' in src
    assert 'add_post("/v1/external/ingest-text", _ingest_text_handler)' in src
    assert 'add_delete("/v1/namespaces/{namespace}", _proxy_to_memory_store)' in src


# -- B3: provider health proxy ------------------------------------------------


async def test_providers_health_proxy_forwards(client):
    resp = await client.get("/v1/providers/health")
    assert resp.status == 200
    data = await resp.json()
    for slot in ("main_llm", "summarizer", "embedding", "memory_store", "tts"):
        assert slot in data, f"missing health slot: {slot}"
    assert data["memory_store"]["ok"] is True
    assert data["embedding"]["provider"] == "siliconflow"


async def test_providers_health_proxy_unreachable_502(client, monkeypatch):
    monkeypatch.setattr(server, "MEMORY_STORE_URL", "http://127.0.0.1:1")
    resp = await client.get("/v1/providers/health")
    assert resp.status == 502
    body = await resp.json()
    assert body.get("error") == "memory-store unreachable"


# -- B4: network settings proxy ----------------------------------------------


async def test_settings_get_proxy_forwards(client):
    resp = await client.get("/v1/settings/network")
    assert resp.status == 200
    data = await resp.json()
    assert "proxy" in data and "providers" in data
    assert data["proxy"]["url"] == "http://127.0.0.1:7890"
    assert data["providers"]["gemini"]["use_proxy"] is True


async def test_settings_put_proxy_forwards(client):
    resp = await client.put(
        "/v1/settings/network",
        json={
            "proxy": {"enabled": True, "url": "http://127.0.0.1:7890"},
            "providers": {"siliconflow": {"use_proxy": True}},
        },
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["received"]["proxy"]["enabled"] is True
    assert data["health"]["memory_store"]["ok"] is True


async def test_settings_get_proxy_unreachable_502(client, monkeypatch):
    monkeypatch.setattr(server, "MEMORY_STORE_URL", "http://127.0.0.1:1")
    resp = await client.get("/v1/settings/network")
    assert resp.status == 502


# -- F4: knowledge-base proxy -------------------------------------------------


async def test_namespaces_proxy_forwards(client):
    resp = await client.get("/v1/namespaces")
    assert resp.status == 200
    data = await resp.json()
    assert data["namespaces"][0]["namespace"] == "wiki:zelda"
    assert data["namespaces"][0]["blocks"] == 12


async def test_namespaces_delete_proxy_forwards(client):
    resp = await client.delete("/v1/namespaces/" + "wiki%3Azelda")
    assert resp.status == 200
    data = await resp.json()
    assert data["deleted_rows"] == 5
    assert data["index_file_removed"] is True


async def test_sync_proxy_forwards(client):
    resp = await client.post(
        "/v1/external/sync",
        json={"namespace": "wiki:zelda", "dir": "/data/wiki/zelda", "drop_first": False},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["chunks"] == 3


# -- F4: pasted-markdown ingest (gateway stages a temp .md) -------------------


async def test_ingest_text_success(client):
    resp = await client.post(
        "/v1/external/ingest-text",
        json={"namespace": "wiki:zelda", "text": "# Hello\n\nSome lore."},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["namespace"] == "wiki:zelda"
    assert data["chunks"] == 3


async def test_ingest_text_missing_field(client):
    resp = await client.post("/v1/external/ingest-text", json={"text": "no ns"})
    assert resp.status == 422
    resp2 = await client.post("/v1/external/ingest-text", json={"namespace": "x"})
    assert resp2.status == 422


async def test_ingest_text_backend_unreachable_502(client, monkeypatch):
    monkeypatch.setattr(server, "MEMORY_STORE_URL", "http://127.0.0.1:1")
    resp = await client.post(
        "/v1/external/ingest-text",
        json={"namespace": "wiki:zelda", "text": "lore"},
    )
    assert resp.status == 502
