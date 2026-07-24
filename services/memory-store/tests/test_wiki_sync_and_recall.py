# SPDX-License-Identifier: Apache-2.0
"""Wiki sync + vector recall + fail-open tests (fake embedder, no network)."""

from __future__ import annotations

import numpy as np
import pytest
from memory_store.backends.sqlite_backend import SqliteBackend
from memory_store.embedder import EmbedderError
from memory_store.models import RecallFilter
from memory_store.wiki_service import drop_wiki_namespace, sync_wiki_dir

_DIM = 1024


class FakeEmbedder:
    """Deterministic bag-of-chars embedder: similar texts land near each other.

    (Avoids Python's per-process randomized hash(); a query that is a subset
    of a chunk's text gets high cosine similarity with it.)
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
    def embed_texts(self, texts, *, is_query: bool = False):
        raise EmbedderError("API down (simulated)")


def _write_wiki(dir_path, pages: dict[str, str]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    for name, body in pages.items():
        (dir_path / name).write_text(body, encoding="utf-8")


@pytest.fixture
def backend(tmp_path):
    be = SqliteBackend(
        str(tmp_path / "memory.sqlite"),
        vec_dir=str(tmp_path / "vec"),
        embedder=FakeEmbedder(),
    )
    yield be
    be.close()


def test_sync_embeds_and_vector_recall(backend, tmp_path):
    wiki = tmp_path / "wiki" / "game-a"
    _write_wiki(
        wiki,
        {
            "boss.md": "# Boss\n\n火焰巨人弱打击属性武器，位于巨人山顶。\n\n![站位](assets/a.png)\n",
            "item.md": "# Item\n\n名刀月隐是智力流太刀，战技为隙间月影。\n",
        },
    )
    result = sync_wiki_dir(backend, backend.embedder, "wiki:game-a", str(wiki))
    assert result.chunks >= 2
    assert result.embedded == result.chunks - result.skipped_unchanged

    # Vector recall: identical query text hits the identical chunk (sim ≈ 1).
    import asyncio

    blocks = asyncio.run(
        backend.recall(
            "火焰巨人弱打击属性武器，位于巨人山顶。",
            top_k=5,
            min_score=0.0,
            flt=RecallFilter(namespaces=["wiki:game-a"]),
            min_similarity=0.5,
        )
    )
    assert blocks, "vector recall should hit"
    assert "火焰巨人" in blocks[0].content
    assert blocks[0].images == ["assets/a.png"]
    assert blocks[0].namespace == "wiki:game-a"


def test_sync_incremental_skips_unchanged_and_cleans_stale(backend, tmp_path):
    wiki = tmp_path / "wiki" / "game-b"
    _write_wiki(wiki, {"a.md": "# A\n\n第一段攻略内容。\n", "b.md": "# B\n\n第二段攻略内容。\n"})

    r1 = sync_wiki_dir(backend, backend.embedder, "wiki:game-b", str(wiki))
    assert r1.chunks >= 2
    calls_after_first = len(backend.embedder.calls)

    # Second sync with one file removed and one unchanged.
    (wiki / "b.md").unlink()
    r2 = sync_wiki_dir(backend, backend.embedder, "wiki:game-b", str(wiki))

    assert r2.skipped_unchanged == r2.chunks, "unchanged chunks must not re-embed"
    assert len(backend.embedder.calls) == calls_after_first, "no new embed calls expected"

    stats = {row["namespace"]: row for row in backend.namespace_stats()}
    assert stats["wiki:game-b"]["blocks"] == r2.chunks, "stale chunk from removed file must be gone"


def test_drop_namespace_wipes_rows_and_index(backend, tmp_path):
    wiki = tmp_path / "wiki" / "game-c"
    _write_wiki(wiki, {"a.md": "# A\n\n某游戏攻略内容。\n"})
    sync_wiki_dir(backend, backend.embedder, "wiki:game-c", str(wiki))
    assert backend.namespace_stats()[0]["indexed"] > 0

    deleted, index_removed = drop_wiki_namespace(backend, "wiki:game-c")
    assert deleted > 0
    assert index_removed is True
    assert backend.namespace_stats() == []


def test_recall_fails_open_to_fts_when_embedder_down(backend, tmp_path):
    wiki = tmp_path / "wiki" / "game-d"
    _write_wiki(wiki, {"a.md": "# A\n\n独特的攻略关键词 xyzzy 出现在这里。\n"})
    sync_wiki_dir(backend, backend.embedder, "wiki:game-d", str(wiki))

    # Embedder dies → recall must fall back to FTS5 BM25 instead of raising.
    backend._embedder = FailingEmbedder()
    import asyncio

    blocks = asyncio.run(
        backend.recall(
            "xyzzy",
            top_k=5,
            min_score=0.0,
            flt=RecallFilter(namespaces=["wiki:game-d"]),
        )
    )
    assert blocks, "fail-open FTS path should still return the block"
    assert "xyzzy" in blocks[0].content


def test_chat_memory_unaffected_by_wiki_namespace(backend):
    """Conversation memory (no namespace) must not leak into wiki recall."""
    import asyncio

    from memory_store.models import MemoryBlock

    asyncio.run(
        backend.push(
            "session-1",
            [MemoryBlock(content="火焰巨人是玩家昨晚讨论的话题", created_at=None)],
        )
    )
    blocks = asyncio.run(
        backend.recall(
            "火焰巨人",
            top_k=10,
            min_score=0.0,
            flt=RecallFilter(namespaces=["wiki:game-a"]),
        )
    )
    assert all(b.namespace == "wiki:game-a" for b in blocks), (
        "chat memory must stay out of wiki recall"
    )


def test_wildcard_namespace_expansion(backend, tmp_path):
    """`wiki:*` must expand to all existing wiki namespaces."""
    wiki = tmp_path / "wiki" / "game-e"
    _write_wiki(wiki, {"a.md": "# A\n\n通配展开测试关键词 zzz 攻略。\n"})
    sync_wiki_dir(backend, backend.embedder, "wiki:game-e", str(wiki))

    import asyncio

    blocks = asyncio.run(
        backend.recall(
            "zzz",
            top_k=5,
            min_score=0.0,
            flt=RecallFilter(namespaces=["wiki:*"]),
            min_similarity=0.0,
        )
    )
    assert blocks, "wiki:* should expand and hit"
    assert all(b.namespace and b.namespace.startswith("wiki:") for b in blocks)
