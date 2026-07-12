# SPDX-License-Identifier: Apache-2.0
"""SqliteBackend tests (spec §D-7, ~6 tests)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from memory_store.backends import get_backend
from memory_store.models import MemoryBlock, RecallFilter


def _block(content: str, session_id: str = "s1", score: float = 1.0,
           created_at: datetime | None = None) -> MemoryBlock:
    return MemoryBlock(
        block_id="",
        session_id=session_id,
        content=content,
        score=score,
        created_at=created_at or datetime.now(),
    )


async def test_push_and_recall_roundtrip():
    backend = get_backend()
    b1 = _block("Pilot 问了 BT-7274 的武器系统配置")
    b2 = _block("Pilot 询问地图布局")
    pushed = await backend.push("sess-A", [b1, b2])
    assert pushed == 2

    blocks = await backend.recall("BT-7274 武器", top_k=5, min_score=0.0, flt=None)
    contents = [b.content for b in blocks]
    assert any("武器系统" in c for c in contents)


async def test_recall_filters_by_min_score():
    backend = get_backend()
    await backend.push("sess-A", [
        _block("highly relevant payload", score=0.95),
        _block("borderline payload", score=0.5),
        _block("low relevance payload", score=0.1),
    ])
    blocks = await backend.recall("payload", top_k=10, min_score=0.4, flt=None)
    assert all(b.score >= 0.4 for b in blocks)
    contents = [b.content for b in blocks]
    assert "highly relevant payload" in contents
    assert "low relevance payload" not in contents


async def test_recall_filters_by_session_ids():
    backend = get_backend()
    await backend.push("sess-A", [_block("alpha charlie delta")])
    await backend.push("sess-B", [_block("alpha bravo delta")])
    flt = RecallFilter(session_ids=["sess-B"])
    blocks = await backend.recall("alpha", top_k=10, min_score=0.0, flt=flt)
    assert {b.session_id for b in blocks} == {"sess-B"}


async def test_recall_warmup_returns_recent_blocks():
    backend = get_backend()
    old = datetime.now() - timedelta(hours=2)
    new = datetime.now()
    await backend.push("sess-A", [
        _block("old block", created_at=old),
        _block("new block", created_at=new),
        _block("newest block", created_at=new + timedelta(seconds=1)),
    ])
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
    await backend.push("sess-A", [
        _block("old", created_at=cutoff - timedelta(days=1)),
        _block("new", created_at=cutoff + timedelta(seconds=1)),
    ])
    flt = RecallFilter(created_after=cutoff)
    blocks = await backend.recall("__warmup__", top_k=10, min_score=0.0, flt=flt)
    assert {b.content for b in blocks} == {"new"}


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
