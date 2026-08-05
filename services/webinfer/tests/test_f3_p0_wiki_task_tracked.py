"""F-3 P0 regression: Local-Wiki recall tasks are tracked on SessionState.

Before the fix, ``SessionState`` had no ``_memory_wiki_tasks`` attribute, so
``MemoryIOMixin._schedule_wiki_recall``'s ``getattr(state, "_memory_wiki_tasks", None)``
always returned ``None`` and the fire-and-forget wiki task was never retained on
``state`` -- only its local variable reference kept it alive, making it
GC-eligible mid-flight and causing ``_memory_wiki_cache`` to intermittently
never populate.

This test asserts the task is tracked in ``state._memory_wiki_tasks`` and that
the cache is populated after the background recall completes.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from live_adapter import StreamingInferAdapter  # noqa: E402


class _StubMemoryClient:
    def __init__(self, blocks=None):
        self._blocks = blocks or []

    @property
    def is_enabled(self):
        return True

    async def ping(self):
        return True

    async def warmup(self, session_id, top_k=16, min_score=0.0):
        return []

    async def recall(self, query, session_id=None, top_k=6, min_score=0.0, namespaces=None):
        return list(self._blocks)

    async def push(self, session_id, blocks):
        return len(blocks)

    async def aclose(self):
        pass

    def health_snapshot(self):
        return {"enabled": True, "healthy": True, "url": "stub"}


def _make_adapter(stub):
    cfg = StreamingInferAdapter.__init__.__globals__["AdapterConfig"]()
    a = StreamingInferAdapter.__new__(StreamingInferAdapter)
    a.config = cfg
    a.sessions = {}
    a._cleanup_task = None
    a._character_prompt_mtime = 0.0
    a._system_prompt_cache = {}
    a._invalidate_system_prompt_cache = lambda: None
    a.memory_store = stub
    return a


def _make_state(session_id="s1"):
    Sess = StreamingInferAdapter.__init__.__globals__["SessionState"]
    return Sess(session_id=session_id)


@pytest.mark.asyncio
async def test_wiki_recall_task_is_tracked_and_cache_populates():
    blocks = [{"block_id": "w1", "content": "wiki fact"}]
    a = _make_adapter(_StubMemoryClient(blocks=blocks))
    state = _make_state()
    state._memory_warmed.set()

    await a._memory_recall(state, "trigger wiki recall")
    # The fire-and-forget task must be tracked on state (P0 fix).
    assert len(state._memory_wiki_tasks) == 1, "wiki recall task was not tracked on state"

    # Let the background task complete.
    await asyncio.sleep(0)
    assert state._memory_wiki_cache == blocks
