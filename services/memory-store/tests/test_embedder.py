# SPDX-License-Identifier: Apache-2.0
"""BgeM3Embedder unit tests (mocked HTTP, no network)."""

from __future__ import annotations

import numpy as np
import pytest
from memory_store.embedder import BgeM3Embedder, EmbedderError, _prepare, content_hash


def test_prepare_is_deterministic_and_shared():
    assert _prepare("  hello\n\nworld  ", is_query=True) == "hello world"
    assert _prepare("  hello\n\nworld  ", is_query=False) == "hello world"


def test_content_hash_stable():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


def test_available_requires_key_for_api(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert BgeM3Embedder(provider="siliconflow").available() is False
    assert BgeM3Embedder(provider="siliconflow", api_key="k").available() is True
    # ``provider=`` here is a string by design — the embedder rejects unknown
    # providers at construction time. The "available is False" semantics for
    # a disabled embedder is now expressed by *not* wiring one up (the
    # SqliteBackend treats ``embedder=None`` as the disable path; the health
    # endpoint reports `provider: none` only when the operator opts in
    # explicitly via env). The literal ``provider="none"`` is therefore no
    # longer a public knob.
    assert BgeM3Embedder(provider="local").available() is True


def test_api_success(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.2] * 1024},
                    {"index": 0, "embedding": [0.1] * 1024},
                ]
            }

    # Embeddings now go through httpx.Client.post (via client_factory), not the
    # module-level httpx.post, so patch the client method to stay offline.
    monkeypatch.setattr("httpx.Client.post", lambda self, *a, **k: _Resp())
    emb = BgeM3Embedder(provider="siliconflow", api_key="k")
    vecs = emb.embed_texts(["a", "b"])
    assert vecs.shape == (2, 1024)
    assert np.isclose(vecs[0][0], 0.1), "results must be re-sorted by index"


def test_api_failure_raises_embedder_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("httpx.post", _boom)
    emb = BgeM3Embedder(provider="siliconflow", api_key="k")
    with pytest.raises(EmbedderError):
        emb.embed_texts(["x"])


def test_missing_key_raises_embedder_error(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    emb = BgeM3Embedder(provider="siliconflow")
    with pytest.raises(EmbedderError):
        emb.embed_texts(["x"])


def test_health_uses_same_path(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    h = BgeM3Embedder(provider="siliconflow").health()
    assert h["ok"] is False and "error" in h
