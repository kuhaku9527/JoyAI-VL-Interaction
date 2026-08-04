# SPDX-License-Identifier: Apache-2.0
"""FastAPI endpoint contract tests (spec §D-7)."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from memory_store import app as app_module
from memory_store.embedder import EmbedderError


class _FailingEmbedder:
    """Embedder that is 'available' but raises on embed_query (simulates down)."""

    provider = "fail"

    def available(self) -> bool:
        return True

    def embed_query(self, text: str):
        raise EmbedderError("simulated embedder down")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite"))
    app_module._reset_backend_for_tests()
    transport = httpx.ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint(client):
    async with client as c:
        r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["backend"] == "sqlite"


async def test_backends_endpoint_lists_active(client):
    async with client as c:
        r = await c.get("/v1/backends")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "sqlite"
    assert set(body["available"]) == {"sqlite", "psql", "obsidian"}


async def test_push_and_recall_endpoints(client):
    payload = {
        "session_id": "sess-X",
        "blocks": [
            {
                "block_id": "",
                "session_id": "sess-X",
                "content": "Pilot 询问 BT-7274 的 VLM 输出",
                "score": 1.0,
                "created_at": datetime.now().isoformat(),
                "last_hit_at": None,
                "hit_count": 0,
            }
        ],
    }
    async with client as c:
        r1 = await c.post("/v1/blocks/push", json=payload)
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["pushed"] == 1
        assert body1["session_id"] == "sess-X"

        # Recall now uses the vector semantic path only (FTS5 BM25 removed);
        # the embedder-free "__warmup__" path verifies push→recall retrieval
        # without needing the real bge-m3 weights.
        r2 = await c.post(
            "/v1/blocks/recall",
            json={"query": "__warmup__", "top_k": 5, "min_score": 0.0, "filter": None},
        )
        assert r2.status_code == 200
        body2 = r2.json()
        assert len(body2["blocks"]) >= 1
        assert "VLM" in body2["blocks"][0]["content"]


async def test_recall_filter_session_ids(client):
    payload = {
        "session_id": "sess-A",
        "blocks": [
            {
                "block_id": "",
                "session_id": "sess-A",
                "content": "alpha charlie delta",
                "score": 1.0,
                "created_at": datetime.now().isoformat(),
                "last_hit_at": None,
                "hit_count": 0,
            }
        ],
    }
    async with client as c:
        await c.post("/v1/blocks/push", json=payload)
        payload["session_id"] = "sess-B"
        payload["blocks"][0]["content"] = "alpha bravo delta"
        await c.post("/v1/blocks/push", json=payload)

        # Warmup path (no embedder) keeps the session_ids filter contract
        # intact without relying on the removed FTS5 fallback.
        r = await c.post(
            "/v1/blocks/recall",
            json={
                "query": "__warmup__",
                "top_k": 10,
                "min_score": 0.0,
                "filter": {"session_ids": ["sess-B"]},
            },
        )
        assert r.status_code == 200
        blocks = r.json()["blocks"]
        assert all(b["session_id"] == "sess-B" for b in blocks)


async def test_recall_missing_query_returns_422(client):
    async with client as c:
        r = await c.post("/v1/blocks/recall", json={"top_k": 5, "min_score": 0.0})
    assert r.status_code == 422


async def test_recall_bare_requires_namespaces_returns_400(client):
    # No filter.namespaces -> vector path rejected before any embedder use.
    async with client as c:
        r = await c.post(
            "/v1/blocks/recall",
            json={"query": "not a warmup", "top_k": 5, "min_score": 0.0, "filter": None},
        )
    assert r.status_code == 400


async def test_recall_embedder_down_returns_503(client):
    # Swap in a failing embedder; a namespaced recall must surface 503, not 200.
    app_module.app.state.backend._embedder = _FailingEmbedder()
    async with client as c:
        r = await c.post(
            "/v1/blocks/recall",
            json={
                "query": "q",
                "top_k": 5,
                "min_score": 0.0,
                "filter": {"namespaces": ["wiki:test"]},
            },
        )
    assert r.status_code == 503


async def test_push_block_with_uuid_generated_on_blank(client):
    payload = {
        "session_id": "sess-X",
        "blocks": [
            {
                "block_id": "",
                "session_id": "sess-X",
                "content": "auto id",
                "score": 1.0,
                "created_at": datetime.now().isoformat(),
                "last_hit_at": None,
                "hit_count": 0,
            }
        ],
    }
    async with client as c:
        r = await c.post("/v1/blocks/push", json=payload)
        assert r.status_code == 200
        r2 = await c.post(
            "/v1/blocks/recall",
            json={"query": "__warmup__", "top_k": 5, "min_score": 0.0, "filter": None},
        )
        body = r2.json()
        assert any(b["block_id"] for b in body["blocks"])
        assert all(len(b["block_id"]) > 0 for b in body["blocks"])
