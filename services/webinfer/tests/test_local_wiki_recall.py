"""Local Wiki live-recall wiring (ADR-0012 §6, 2026-07-28)."""

from __future__ import annotations

import os

import pytest

# webinfer tests run with PYTHONPATH = services/webinfer; we rely on the
# adjacent sys.path entries so the absolute imports below resolve.
from adapter_types import SessionState
from memory_io import MemoryIOMixin


class _StubMemoryClient:
    """Async stub over MemoryStoreClient with recording + failure injection."""

    def __init__(self, blocks=None, enabled: bool = True, raise_exc: Exception | None = None):
        self._blocks = blocks or []
        self.enabled = enabled
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def recall(self, query, *, session_id=None, top_k=6, min_score=0.0, namespaces=None):
        self.calls.append(
            {
                "query": query,
                "session_id": session_id,
                "top_k": int(top_k),
                "min_score": float(min_score),
                "namespaces": namespaces,
            }
        )
        if self._raise is not None:
            raise self._raise
        return list(self._blocks)


class _StubAdapter(MemoryIOMixin):
    """Bare mixin host so we can call ``_memory_recall`` without the full
    StreamingInferAdapter. Only the attributes the memory mixin touches are
    wired."""

    def __init__(self, memory_store, *, namespaces=None, top_k=5, min_score=0.0, enabled=True):
        self.memory_store = memory_store
        # Config shim used by ``_wiki_settings`` to read env overrides.
        self.config = type(
            "Cfg",
            (),
            {
                "wiki_recall_namespaces": namespaces,
                "wiki_recall_top_k": top_k,
                "wiki_recall_min_score": min_score,
                "wiki_recall_enabled": enabled,
            },
        )()


def _make_state(*, warmed: bool = True, chat_blocks=None) -> SessionState:
    st = SessionState(session_id="s1")
    st._memory_warmed.set() if warmed else None
    st._memory_block_cache = list(chat_blocks or [])
    st._memory_wiki_cache = []
    return st


# -- happy path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_recall_fired_with_namespaces_and_populates_cache():
    blocks = [
        {
            "block_id": "w1",
            "content": "玛莲妮亚的水鸟乱舞需要连续翻滚四次。",
            "namespace": "wiki:elden-ring",
            "source_url": "https://example/Malenia",
        }
    ]
    stub = _StubMemoryClient(blocks=blocks)
    a = _StubAdapter(stub, namespaces=["wiki:elden-ring", "wiki:hl2"])
    # Make sure no stale env from another test leaks into this one.
    for k in (
        "WIKI_RECALL_NAMESPACES",
        "WIKI_RECALL_TOP_K",
        "WIKI_RECALL_MIN_SCORE",
        "WIKI_RECALL_ENABLED",
    ):
        os.environ.pop(k, None)
    state = _make_state(chat_blocks=[{"block_id": "c1", "content": "昨天聊到火焰巨人"}])

    chat = await a._memory_recall(state, "玛莲妮亚怎么打")

    # Chat memory is still the canonical return value of the hook.
    assert chat == [{"block_id": "c1", "content": "昨天聊到火焰巨人"}]
    # The wiki section is stashed on its own slot for the prompt builder.
    assert state._memory_wiki_cache[0]["block_id"] == "w1"
    assert state._memory_wiki_cache[0]["source"] == "wiki"
    # The HTTP call must carry the namespace filter (per ADR-0012 L1).
    assert stub.calls[0]["namespaces"] == ["wiki:elden-ring", "wiki:hl2"]
    assert stub.calls[0]["top_k"] == 5
    assert stub.calls[0]["query"] == "玛莲妮亚怎么打"
    # Sanity: the captured call is the raw env-shaped list, not a stringified
    # rep — guard the schema we promised to the backend in this PR.
    assert isinstance(stub.calls[0]["namespaces"], list)


# -- failure is fail-open ----------------------------------------------------


@pytest.mark.asyncio
async def test_wiki_recall_failure_does_not_break_chat():
    stub = _StubMemoryClient(raise_exc=RuntimeError("connection refused"))
    a = _StubAdapter(stub)
    state = _make_state(chat_blocks=[{"block_id": "c1", "content": "x"}])

    chat = await a._memory_recall(state, "怎么打")

    assert chat == [{"block_id": "c1", "content": "x"}]
    # The wiki cache must NOT be touched when the call failed.
    assert state._memory_wiki_cache == []


@pytest.mark.asyncio
async def test_wiki_recall_disabled_via_config():
    stub = _StubMemoryClient(blocks=[{"block_id": "w1", "content": "x"}])
    a = _StubAdapter(stub, enabled=False)
    state = _make_state()

    await a._memory_recall(state, "q")

    assert stub.calls == []  # no HTTP call at all
    assert state._memory_wiki_cache == []


@pytest.mark.asyncio
async def test_wiki_recall_skipped_when_memory_store_disabled():
    stub = _StubMemoryClient(blocks=[{"block_id": "w1", "content": "x"}], enabled=False)
    a = _StubAdapter(stub)
    state = _make_state()

    await a._memory_recall(state, "q")

    assert stub.calls == []
    assert state._memory_wiki_cache == []


@pytest.mark.asyncio
async def test_wiki_recall_empty_query_is_noop():
    """A player chat without a question must not trigger any wiki call."""
    stub = _StubMemoryClient(blocks=[{"block_id": "w1", "content": "x"}])
    a = _StubAdapter(stub)
    state = _make_state()

    chat = await a._memory_recall(state, "")

    assert chat == []
    assert stub.calls == []
    assert state._memory_wiki_cache == []


# -- prompt assembly glue -----------------------------------------------------


def test_build_memory_prompt_renders_both_sections():
    """Smoke: when both caches are populated, the renderer emits two
    distinct sections in the correct order."""
    from prompt_assembly import PromptAssemblyMixin

    class _Cfg:
        language = "zh-CN"
        system_prompt = "BASE"
        keep_qa_history = False
        qa_history_window = 0

    class _Host(PromptAssemblyMixin):
        def __init__(self):
            self.config = _Cfg()

        def _load_character_profiles(self):
            return []

        def _build_system_prompt(self, language):
            return "BASE"

    host = _Host()
    state = _make_state()
    state._memory_block_cache = [{"block_id": "c1", "content": "chat fact"}]
    state._memory_wiki_cache = [
        {
            "block_id": "w1",
            "content": "wiki fact",
            "namespace": "wiki:g",
            "source_url": "https://e",
        }
    ]
    out = host._build_memory_prompt(state)
    assert "[Previous Memory]" in out
    assert "[Local Wiki]" in out
    assert out.index("[Previous Memory]") < out.index("[Local Wiki]")
    assert "chat fact" in out
    assert "wiki fact" in out
    assert "ns=wiki:g" in out


# -- env override -------------------------------------------------------------


def test_env_overrides_config(monkeypatch):
    """Operators can shrink the wiki recall set from the env without
    touching the adapter config."""
    monkeypatch.setenv("WIKI_RECALL_NAMESPACES", "wiki:elden-ring,wiki:hl2")
    monkeypatch.setenv("WIKI_RECALL_TOP_K", "3")
    monkeypatch.setenv("WIKI_RECALL_MIN_SCORE", "0.5")
    monkeypatch.setenv("WIKI_RECALL_ENABLED", "true")

    from memory_io import _wiki_settings

    cfg = type("Cfg", (), {})()  # empty config: every value comes from env
    s = _wiki_settings(cfg)
    assert s["enabled"] is True
    assert s["namespaces"] == ["wiki:elden-ring", "wiki:hl2"]
    assert s["top_k"] == 3
    assert s["min_score"] == 0.5


def test_env_disable_overrides_config(monkeypatch):
    monkeypatch.setenv("WIKI_RECALL_ENABLED", "false")
    from memory_io import _wiki_settings

    cfg = type("Cfg", (), {"wiki_recall_enabled": True})()
    # Config-side ``True`` is overridden by env ``false``.
    assert _wiki_settings(cfg)["enabled"] is False
    # And inverted: env ``true`` overrides config ``False``.
    monkeypatch.setenv("WIKI_RECALL_ENABLED", "true")
    cfg = type("Cfg", (), {"wiki_recall_enabled": False})()
    assert _wiki_settings(cfg)["enabled"] is True
