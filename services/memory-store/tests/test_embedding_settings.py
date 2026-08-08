# SPDX-License-Identifier: Apache-2.0
"""Integration tests for POST /v1/settings/embedding (issue #124).

Mirrors test_network_settings.py: the real BgeM3Embedder is replaced by a
sentinel so the endpoint's constructor + health() path never loads the local
model or hits the network. Covers: valid switch swaps both backend + app.state
mirror; invalid provider -> 400 with no swap; cloud provider without key -> 502
with no swap (no silent degrade, D-080).
"""

from __future__ import annotations

import os
from typing import ClassVar

import httpx
import pytest
from memory_store import app as app_module
from memory_store import config


class _FakeEmbedder:
    """Stand-in for BgeM3Embedder that validates + reports health offline."""

    ALLOWED: ClassVar[set[str]] = {"local", "siliconflow", "nvidia"}

    def __init__(self, provider=None, api_key=None, **_kwargs):
        self.provider = (provider or os.getenv("EMBEDDING_PROVIDER", "local")).lower()
        if self.provider not in self.ALLOWED:
            raise ValueError(
                f"unknown EMBEDDING_PROVIDER={self.provider!r}; "
                "expected one of: local, siliconflow, nvidia"
            )
        key_env = (
            "SILICONFLOW_API_KEY"
            if self.provider == "siliconflow"
            else "NVIDIA_API_KEY"
            if self.provider == "nvidia"
            else ""
        )
        self.api_key = api_key if api_key is not None else os.getenv(key_env, "")
        self._available = self.provider == "local" or bool(self.api_key)

    def available(self) -> bool:
        return self._available

    def health(self) -> dict:
        if not self._available:
            return {
                "ok": False,
                "provider": self.provider,
                "error": f"{self.provider} API key not set",
            }
        return {
            "ok": True,
            "provider": self.provider,
            "model": "BAAI/bge-m3",
            "dim": 1024,
            "latency_ms": 1,
        }


@pytest.fixture
def fake_embedder(monkeypatch):
    monkeypatch.setattr(app_module, "BgeM3Embedder", _FakeEmbedder)
    return _FakeEmbedder


@pytest.fixture
def client(tmp_path, monkeypatch, fake_embedder):
    monkeypatch.setenv("MEMORY_SQLITE_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    app_module._reset_backend_for_tests()
    transport = httpx.ASGITransport(app=app_module.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_post_embedding_settings_valid_local(client, tmp_path):
    config.reset_store(str(tmp_path / "network_config.json"))
    async with client as c:
        r = await c.post("/v1/settings/embedding", json={"provider": "local"})
    assert r.status_code == 200, r.text
    assert r.json()["embedding"]["provider"] == "local"
    # Swap actually re-pointed the live backend + app.state mirror.
    assert app_module.app.state.backend.embedder.provider == "local"
    assert app_module.app.state.embedder.provider == "local"


async def test_post_embedding_settings_invalid_provider(client, tmp_path):
    config.reset_store(str(tmp_path / "network_config.json"))
    async with client as c:
        r = await c.post("/v1/settings/embedding", json={"provider": "azure"})
    assert r.status_code == 400, r.text
    # No swap on invalid provider.
    assert app_module.app.state.backend.embedder.provider == "local"


async def test_post_embedding_settings_cloud_no_key_no_swap(client, tmp_path):
    config.reset_store(str(tmp_path / "network_config.json"))
    async with client as c:
        r = await c.post("/v1/settings/embedding", json={"provider": "siliconflow"})
    assert r.status_code == 502, r.text
    # Unhealthy provider must NOT swap the live embedder (no silent degrade).
    assert app_module.app.state.backend.embedder.provider == "local"
