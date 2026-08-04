# SPDX-License-Identifier: Apache-2.0
"""SqliteBackend tests (spec §D-7, ~6 tests).

Recall now uses the vector semantic path only (D-2026-08-05-003): the FTS5
BM25 fallback is gone, so semantic recall requires a namespace scope and a
working embedder. These semantic tests use a deterministic ``FakeEmbedder``
and index blocks via ``insert_block_with_vector`` (the same path wiki sync
uses) so they run fully offline. The pure-SQL ``__warmup__`` path needs no
embedder and is exercised separately.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest
from memory_store.backends import get_backend
from memory_store.backends.sqlite_backend import SqliteBackend
from memory_store.embedder import EmbedderError
from memory_store.models import MemoryBlock, RecallFilter

_DIM = 1024


class FakeEmbedder:
    """Deterministic bag-of-chars embedder: similar texts land near each other.

    Avoids Python's per-process randomized hash(); a query that is a subset of
    a chunk's text gets high cosine similarity with it. Used so semantic recall
    is testable without the real bge-m3 weights.
    """

    provider = "fake"

    def __init__(self):
        self.calls: list[list[str]] = []

    def available(self) -> bool:
        return True

    def _vec_for(self, text: str) -> np.ndarray:
        v = np.zeros(_DIM, dtype=np.float32)
        for ch in text:
            v[ord(ch) % _DIM] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_texts(self, texts, *, is_query: bool = False):
        self.calls.append(list(texts))
        return np.stack([self._vec_for(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec_for(text)


class FailingEmbedder(FakeEmbedder):
    """Embedder whose embedding call always raises (simulates API down)."""

    def embed_query(self, text: str) -> np.ndarray:
        raise EmbedderError("API down (simulated)")

    def embed_texts(self, texts, *, is_query: bool = False):
        raise EmbedderError("API down (simulated)")


@pytest.fixture
def vector_backend(tmp_path):
    """Isolated backend with a fake embedder for vector recall tests."""
    be = SqliteBackend(
        str(tmp_path / "memory.sqlite"),
        vec_dir=str(tmp_path / "vec"),
        embedder=FakeEmbedder(),
    )
    yield be
    be.close()


def _block(
    content: str,
    session_id: str = "s1",
    score: float = 1.0,
    created_at: datetime | None = None,
    namespace: str | None = None,
) -> MemoryBlock:
    return MemoryBlock(
        block_id="",
        session_id=session_id,
        content=content,
        score=score,
        created_at=created_at or datetime.now(),
        namespace=namespace,
    )


def _index(backend, session_id: str, content: str, namespace: str, **kw) -> MemoryBlock:
    """Build, embed and vector-index a block (mirrors wiki sync's write path)."""
    block = _block(content, session_id=session_id, namespace=namespace, **kw)
    vec = backend.embedder.embed_query(content)
    backend.insert_block_with_vector(session_id, block, vec)
    return block


# -- semantic recall (vector path only) ---------------------------------------


async def test_push_and_recall_roundtrip(vector_backend):
    ns = "wiki:test"
    _index(vector_backend, "sess-A", "Pilot 问了 BT-7274 的武器系统配置", ns)
    _index(vector_backend, "sess-A", "Pilot 询问地图布局", ns)
    blocks = await vector_backend.recall(
        "BT-7274 武器",
        top_k=5,
        min_score=0.0,
        flt=RecallFilter(namespaces=[ns]),
        min_similarity=0.0,
    )
    contents = [b.content for b in blocks]
    assert any("武器系统" in c for c in contents)


async def test_recall_filters_by_min_score(vector_backend):
    ns = "wiki:test"
    _index(vector_backend, "sess-A", "highly relevant payload", ns, score=0.95)
    _index(vector_backend, "sess-A", "borderline payload", ns, score=0.5)
    _index(vector_backend, "sess-A", "low relevance payload", ns, score=0.1)
    blocks = await vector_backend.recall(
        "payload",
        top_k=10,
        min_score=0.4,
        flt=RecallFilter(namespaces=[ns]),
        min_similarity=0.0,
    )
    assert all(b.score >= 0.4 for b in blocks)
    contents = [b.content for b in blocks]
    assert "highly relevant payload" in contents
    assert "low relevance payload" not in contents


async def test_recall_filters_by_session_ids(vector_backend):
    ns = "wiki:test"
    _index(vector_backend, "sess-A", "alpha charlie delta", ns)
    _index(vector_backend, "sess-B", "alpha bravo delta", ns)
    flt = RecallFilter(session_ids=["sess-B"], namespaces=[ns])
    blocks = await vector_backend.recall(
        "alpha", top_k=10, min_score=0.0, flt=flt, min_similarity=0.0
    )
    assert {b.session_id for b in blocks} == {"sess-B"}


# -- decision-locking: no silent degrade, explicit errors ---------------------


async def test_recall_requires_namespaces(vector_backend):
    """Bare recall (no filter.namespaces) must raise, not silently empty."""
    _index(vector_backend, "sess-A", "some content here", "wiki:test")
    with pytest.raises(ValueError):
        await vector_backend.recall("some", top_k=5, min_score=0.0, flt=None)


async def test_recall_embedder_unavailable_raises(vector_backend):
    """Embedder down must raise EmbedderError, never fall back to BM25."""
    _index(vector_backend, "sess-A", "unique keyword xyzzy here", "wiki:test")
    vector_backend._embedder = FailingEmbedder()
    with pytest.raises(EmbedderError):
        await vector_backend.recall(
            "xyzzy", top_k=5, min_score=0.0, flt=RecallFilter(namespaces=["wiki:test"])
        )


async def test_recall_namespaces_wildcard_expands(vector_backend):
    """RecallFilter(namespaces=['wiki:*']) expands to all existing namespaces."""
    _index(vector_backend, "sess-A", "margit the fell omen boss", "wiki:elden-ring")
    _index(vector_backend, "sess-A", "ganon the calamity boss", "wiki:zelda")
    blocks = await vector_backend.recall(
        "boss",
        top_k=10,
        min_score=0.0,
        flt=RecallFilter(namespaces=["wiki:*"]),
        min_similarity=0.0,
    )
    ns = {b.namespace for b in blocks}
    assert {"wiki:elden-ring", "wiki:zelda"} <= ns


# -- warmup path (pure SQL, no embedder needed) -------------------------------


async def test_recall_warmup_returns_recent_blocks():
    backend = get_backend()
    old = datetime.now() - timedelta(hours=2)
    new = datetime.now()
    await backend.push(
        "sess-A",
        [
            _block("old block", created_at=old),
            _block("new block", created_at=new),
            _block("newest block", created_at=new + timedelta(seconds=1)),
        ],
    )
    flt = RecallFilter(session_ids=["sess-A"])
    blocks = await backend.recall("__warmup__", top_k=2, min_score=0.0, flt=flt)
    assert len(blocks) == 2
    # Most recent first
    assert blocks[0].content == "newest block"
    assert blocks[1].content == "new block"


async def test_recall_warmup_respects_top_k():
    backend = get_backend()
    await backend.push("sess-A", [_block(f"block-{i}") for i in range(5)])
    blocks = await backend.recall("__warmup__", top_k=3, min_score=0.0, flt=None)
    assert len(blocks) == 3


async def test_recall_filters_by_created_after():
    backend = get_backend()
    cutoff = datetime.now()
    await backend.push(
        "sess-A",
        [
            _block("old", created_at=cutoff - timedelta(days=1)),
            _block("new", created_at=cutoff + timedelta(seconds=1)),
        ],
    )
    flt = RecallFilter(created_after=cutoff)
    blocks = await backend.recall("__warmup__", top_k=10, min_score=0.0, flt=flt)
    assert {b.content for b in blocks} == {"new"}


# -- backend contract / health ------------------------------------------------


async def test_health_reports_path_and_block_count():
    backend = get_backend()
    await backend.push("sess-A", [_block("alpha"), _block("bravo")])
    h = await backend.health()
    assert h["ok"] is True
    assert h["backend"] == "sqlite"
    assert h["blocks"] == 2
    assert h["path"].endswith("memory.sqlite")


async def test_backend_protocol_methods_exist():
    backend = get_backend()
    assert callable(getattr(backend, "push", None))
    assert callable(getattr(backend, "recall", None))
    assert callable(getattr(backend, "health", None))
    assert callable(getattr(backend, "name", None))
    assert backend.name() == "sqlite"


async def test_push_empty_blocks_returns_zero():
    backend = get_backend()
    pushed = await backend.push("sess-A", [])
    assert pushed == 0
    h = await backend.health()
    assert h["blocks"] == 0
