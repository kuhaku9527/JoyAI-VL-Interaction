"""Unit tests for live_adapter memory-store hooks (v0.2)."""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

# These tests exercise the adapter methods directly with a stubbed
# MemoryStoreClient, so we do NOT need a real openai / aiohttp setup.
# We construct a tiny StreamingInferAdapter with minimal config.
from live_adapter import StreamingInferAdapter


class _StubMemoryClient:
    """Bare-bones stand-in for MemoryStoreClient used by the live adapter."""

    def __init__(self, blocks=None, push_log=None):
        self._blocks = blocks or []
        self._push_log = push_log if push_log is not None else []
        self._healthy = True

    @property
    def is_enabled(self):
        return True

    async def ping(self):
        return self._healthy

    async def warmup(self, session_id, top_k=16, min_score=0.0):
        return list(self._blocks)

    async def recall(self, query, session_id=None, top_k=6, min_score=0.0,
                     namespaces=None):
        return list(self._blocks)

    async def push(self, session_id, blocks):
        self._push_log.append({"session_id": session_id, "blocks": list(blocks)})
        return len(blocks)

    async def aclose(self):
        pass

    def health_snapshot(self):
        return {"enabled": True, "healthy": self._healthy, "url": "stub"}


def _make_adapter(memory_client):
    cfg = StreamingInferAdapter.__init__.__globals__["AdapterConfig"]()
    a = StreamingInferAdapter.__new__(StreamingInferAdapter)
    a.config = cfg
    a.sessions = {}
    a._cleanup_task = None
    a._character_prompt_mtime = 0.0
    a._system_prompt_cache = {}
    a._invalidate_system_prompt_cache = lambda: None
    a.memory_store = memory_client
    return a


def _make_state(session_id="s1"):
    Sess = StreamingInferAdapter.__init__.__globals__["SessionState"]
    state = Sess(session_id=session_id)
    state.mid_term_summaries = []
    state.long_term_history = []
    return state


@pytest.mark.asyncio
async def test_warmup_populates_cache():
    stub = _StubMemoryClient(blocks=[{"block_id": "x", "content": "hello"}])
    a = _make_adapter(stub)
    state = _make_state()
    await a._memory_warmup(state)
    assert state._memory_warmed.is_set()
    assert state._memory_block_cache == [{"block_id": "x", "content": "hello"}]


@pytest.mark.asyncio
async def test_warmup_idempotent():
    stub = _StubMemoryClient(blocks=[{"block_id": "x", "content": "hello"}])
    a = _make_adapter(stub)
    state = _make_state()
    await a._memory_warmup(state)
    # Mutate the stub; the second call must NOT re-pull.
    stub._blocks = [{"block_id": "y", "content": "world"}]
    await a._memory_warmup(state)
    assert state._memory_block_cache == [{"block_id": "x", "content": "hello"}]


@pytest.mark.asyncio
async def test_push_collects_mid_term_and_long_term():
    stub = _StubMemoryClient()
    a = _make_adapter(stub)
    state = _make_state()
    state.mid_term_summaries = [{"summary_text": "mid-term summary 1"}]
    state.long_term_history = [{"compressed_text": "long-term summary A"}]
    n = await a._memory_push(state)
    assert n == 2
    assert len(stub._push_log) == 1
    pushed = stub._push_log[0]
    assert pushed["session_id"] == "s1"
    contents = sorted(b["content"] for b in pushed["blocks"])
    assert contents == ["long-term summary A", "mid-term summary 1"]


@pytest.mark.asyncio
async def test_push_skips_when_disabled():
    class DisabledStub(_StubMemoryClient):
        @property
        def is_enabled(self):
            return False

    stub = DisabledStub()
    a = _make_adapter(stub)
    state = _make_state()
    state.mid_term_summaries = [{"summary_text": "x"}]
    n = await a._memory_push(state)
    assert n == 0
    assert stub._push_log == []


@pytest.mark.asyncio
async def test_push_idempotent():
    stub = _StubMemoryClient()
    a = _make_adapter(stub)
    state = _make_state()
    state.mid_term_summaries = [{"summary_text": "first"}]
    n1 = await a._memory_push(state)
    n2 = await a._memory_push(state)
    assert n1 == 1
    assert n2 == 0
    assert len(stub._push_log) == 1


@pytest.mark.asyncio
async def test_push_with_empty_data_is_zero():
    stub = _StubMemoryClient()
    a = _make_adapter(stub)
    state = _make_state()
    n = await a._memory_push(state)
    assert n == 0
    assert stub._push_log == []


@pytest.mark.asyncio
async def test_build_memory_prompt_fast_path():
    # No memory blocks -> should return the regular cached prompt.
    stub = _StubMemoryClient()
    a = _make_adapter(stub)
    state = _make_state()
    base = a._build_system_prompt(a.config.language)
    fast = a._build_memory_prompt(state)
    assert fast == base


@pytest.mark.asyncio
async def test_build_memory_prompt_slow_path():
    stub = _StubMemoryClient()
    a = _make_adapter(stub)
    state = _make_state()
    state._memory_block_cache = [{"block_id": "abc", "content": "remembered fact"}]
    out = a._build_memory_prompt(state)
    # PR #42 split the heading: chat memory is now under [Previous Memory];
    # the [Local Wiki] heading is reserved for the separate wiki section.
    assert "[Previous Memory]" in out
    assert "remembered fact" in out


class _SlowMemoryClient(_StubMemoryClient):
    """Memory client whose warmup sleeps briefly so concurrent callers
    interleave, exercising the lock around _memory_block_cache writes."""

    def __init__(self, blocks=None, delay=0.05):
        super().__init__(blocks=blocks)
        self._warmup_calls = 0
        self._delay = delay

    async def warmup(self, session_id, top_k=16, min_score=0.0):
        self._warmup_calls += 1
        await asyncio.sleep(self._delay)
        return list(self._blocks)


@pytest.mark.asyncio
async def test_memory_warmup_concurrent_with_recall():
    """Concurrent warmup + recall on the same session must not tear the
    cache nor assign it more than once (lock-guarded critical sections)."""
    blocks = [{"block_id": "x", "content": "hello"}]
    stub = _SlowMemoryClient(blocks=blocks, delay=0.05)
    a = _make_adapter(stub)
    state = _make_state()

    # Fire several warmups and reads concurrently.
    tasks = [
        asyncio.ensure_future(a._memory_warmup(state)),
        asyncio.ensure_future(a._memory_warmup(state)),
        asyncio.ensure_future(a._memory_recall(state, "any question")),
        asyncio.ensure_future(a._memory_recall(state, "")),
        asyncio.ensure_future(a._memory_recall(state, "another question")),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert not any(isinstance(r, Exception) for r in results), results

    # Double-checked locking must collapse concurrent warmups into a
    # single memory-store pull.
    assert stub._warmup_calls == 1
    assert state._memory_warmed.is_set()
    # The cache must be a single, consistent assignment (no torn/duplicate
    # write from the interleaved coroutines).
    assert state._memory_block_cache == blocks



# ---------------------------------------------------------------------------
# Fire-and-forget wiki recall (v0.3, 2026-07-29) — see ADR-0013 / memory-client-resilience
# ---------------------------------------------------------------------------

class _SlowWikiClient(_StubMemoryClient):
    """Wiki recall sleeps long enough that we can observe ordering."""

    def __init__(self, blocks=None, wiki_delay=0.20):
        super().__init__(blocks=blocks)
        self._wiki_delay = wiki_delay

    async def recall(self, query, session_id=None, top_k=6, min_score=0.0,
                     namespaces=None):
        await asyncio.sleep(self._wiki_delay)
        return list(self._blocks)


@pytest.mark.asyncio
async def test_wiki_recall_is_fire_and_forget():
    """``_memory_recall`` returns BEFORE the wiki recall completes.

    Without fire-and-forget, the slow wiki recall would block the main path
    by 0.20s; with it, the call returns in <50ms and the wiki cache fills in
    asynchronously.
    """
    blocks = [{"block_id": "w1", "content": "wiki fact"}]
    stub = _SlowWikiClient(blocks=blocks, wiki_delay=0.20)
    a = _make_adapter(stub)
    state = _make_state()
    state._memory_warmed.set()  # skip warmup so timing isolates wiki

    t0 = asyncio.get_event_loop().time()
    chat_blocks = await a._memory_recall(state, "what is the wiki fact?")
    elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000

    # Chat path returns quickly even though wiki recall is in flight.
    assert chat_blocks == []
    assert elapsed_ms < 80, f"_memory_recall took {elapsed_ms:.0f}ms; should be <80ms"

    # The wiki recall task is still scheduled — let it finish, then verify cache.
    # Drain pending tasks on the running loop.
    await asyncio.sleep(0.30)
    assert state._memory_wiki_cache == blocks, (
        "wiki cache should have been populated by the background task"
    )


@pytest.mark.asyncio
async def test_wiki_recall_updates_cache_async():
    """The background wiki task writes to ``state._memory_wiki_cache``."""
    blocks = [{"block_id": "w2", "content": "wiki fact 2"}]
    stub = _StubMemoryClient(blocks=blocks)
    a = _make_adapter(stub)
    state = _make_state()
    state._memory_warmed.set()

    # Initial cache empty.
    assert state._memory_wiki_cache == []

    await a._memory_recall(state, "trigger wiki recall")

    # Yield control so the scheduled task can run.
    await asyncio.sleep(0)

    assert state._memory_wiki_cache == blocks


@pytest.mark.asyncio
async def test_wiki_recall_failure_does_not_propagate():
    """A stub recall that raises must NOT raise from ``_memory_recall``."""
    class BoomWikiClient(_StubMemoryClient):
        async def recall(self, query, session_id=None, top_k=6, min_score=0.0,
                         namespaces=None):
            raise RuntimeError("simulated upstream explosion")

    a = _make_adapter(BoomWikiClient())
    state = _make_state()
    state._memory_warmed.set()

    # Should not raise even though the wiki client explodes.
    chat_blocks = await a._memory_recall(state, "boom query")
    assert chat_blocks == []

    # Drain pending tasks.
    await asyncio.sleep(0)
    # Cache untouched because recall raised before any blocks were returned.
    assert state._memory_wiki_cache == []
