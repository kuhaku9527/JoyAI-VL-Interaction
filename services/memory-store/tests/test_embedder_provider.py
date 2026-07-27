# SPDX-License-Identifier: Apache-2.0
"""BgeM3Embedder provider-switch tests (nvidia vs siliconflow), mocked HTTP.

No network: the per-provider client is replaced with a recording fake so we
can assert on the request payload (model, base URL, and the NVIDIA-only
``input_type`` discriminator) without ever hitting NVIDIA or SiliconFlow.
Secrets are never hard-coded — ``NVIDIA_API_KEY`` / ``SILICONFLOW_API_KEY``
are injected via monkeypatch only.
"""

from __future__ import annotations

import pytest
from memory_store import client_factory
from memory_store.embedder import BgeM3Embedder


class _FakeResp:
    """Minimal stand-in for httpx.Response (raise_for_status + json)."""

    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


class _FakeClient:
    """httpx.Client substitute that records the last POST request."""

    def __init__(self):
        self.last: dict | None = None

    def post(self, url, *, headers=None, json=None, timeout=None):
        self.last = {
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        }
        # Emit one 1024-dim vector per input text so _embed_api's shape check
        # passes for batches of any size.
        texts = (json or {}).get("input", ["x"])
        data = {"data": [{"index": i, "embedding": [0.0] * 1024} for i in range(len(texts))]}
        return _FakeResp(data)

    def close(self) -> None:
        return None


@pytest.fixture
def fake_client(monkeypatch):
    """Patch client_factory.get_sync_client to return recording fakes."""
    clients: list[_FakeClient] = []

    def _make(provider, **kwargs):
        client = _FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr(client_factory, "get_sync_client", _make)
    return clients


# -- provider selection -----------------------------------------------------


def test_nvidia_is_default_and_uses_nvidia_constants(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    emb = BgeM3Embedder()  # no env, no provider arg
    assert emb.provider == "nvidia"
    assert emb.api_base == "https://integrate.api.nvidia.com/v1"
    assert emb.model == "baai/bge-m3"


def test_nvidia_default_overridden_by_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "siliconflow")
    emb = BgeM3Embedder()
    assert emb.provider == "siliconflow"
    assert emb.api_base == "https://api.siliconflow.cn/v1"
    assert emb.model == "BAAI/bge-m3"


def test_nvidia_explicit_selects_nvidia_constants(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    emb = BgeM3Embedder(provider="nvidia")
    assert emb.api_base == "https://integrate.api.nvidia.com/v1"
    assert emb.model == "baai/bge-m3"


def test_siliconflow_regression_uses_legacy_constants(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    emb = BgeM3Embedder(provider="siliconflow")
    assert emb.api_base == "https://api.siliconflow.cn/v1"
    assert emb.model == "BAAI/bge-m3"


# -- available() ------------------------------------------------------------


def test_nvidia_available_requires_nvidia_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert BgeM3Embedder(provider="nvidia").available() is False
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-key")
    assert BgeM3Embedder(provider="nvidia").available() is True


def test_siliconflow_available_requires_siliconflow_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert BgeM3Embedder(provider="siliconflow").available() is False
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    assert BgeM3Embedder(provider="siliconflow").available() is True


# -- request payload (input_type discriminator) -----------------------------


def test_nvidia_embed_query_sends_input_type_query(fake_client):
    emb = BgeM3Embedder(provider="nvidia", api_key="nv-key")
    emb.embed_query("hello")
    payload = fake_client[-1].last["json"]
    assert payload["input_type"] == "query"
    assert payload["truncate"] == "NONE"
    assert payload["model"] == "baai/bge-m3"
    assert payload["encoding_format"] == "float"


def test_nvidia_embed_texts_sends_input_type_passage(fake_client):
    emb = BgeM3Embedder(provider="nvidia", api_key="nv-key")
    emb.embed_texts(["doc one", "doc two"], is_query=False)
    payload = fake_client[-1].last["json"]
    assert payload["input_type"] == "passage"
    assert payload["truncate"] == "NONE"


def test_siliconflow_payload_has_no_input_type(fake_client):
    emb = BgeM3Embedder(provider="siliconflow", api_key="sf-key")
    emb.embed_query("hello")
    payload = fake_client[-1].last["json"]
    assert "input_type" not in payload
    assert payload["model"] == "BAAI/bge-m3"


def test_nvidia_missing_key_raises_generic_error(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    emb = BgeM3Embedder(provider="nvidia")
    with pytest.raises(Exception) as exc:  # EmbedderError
        emb.embed_texts(["x"])
    assert "nvidia" in str(exc.value)


# -- health() ---------------------------------------------------------------


def test_nvidia_health_returns_structure(fake_client):
    emb = BgeM3Embedder(provider="nvidia", api_key="nv-key")
    result = emb.health()
    assert result["ok"] is True
    assert result["provider"] == "nvidia"
    assert result["model"] == "baai/bge-m3"
    assert result["dim"] == 1024
    assert "latency_ms" in result


def test_siliconflow_health_returns_structure(fake_client):
    emb = BgeM3Embedder(provider="siliconflow", api_key="sf-key")
    result = emb.health()
    assert result["ok"] is True
    assert result["provider"] == "siliconflow"
    assert result["dim"] == 1024
