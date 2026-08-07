"""F-3 P1a regression: text path must NOT await memory-store warmup inline.

The previous inline-warmup block held ``state.lock`` (the text handler holds
it across the whole ``_handle_text_payload`` call) and then
``await state._memory_warmed.wait()`` -- which starved the background
``_memory_warmup`` task (it needs the same lock) and deterministically stalled
5s with an empty ``_memory_block_cache`` on every session's first request.

Fix: the inline block is deleted; the cache is filled by the background
``_memory_warmup_task`` scheduled in ``get_session`` (identical mechanism to
the multimodal path). This test reproduces the production lock-held path and
proves the handler (a) returns promptly (no 5s starvation), (b) performs no
synchronous inline ``memory_store.warmup`` pull of its own, and (c) ends with a
populated ``_memory_block_cache`` filled by the background task.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from live_adapter import StreamingInferAdapter


class _CountingMemoryClient:
    def __init__(self, blocks=None):
        self._blocks = blocks or []
        self.warmup_calls = 0

    @property
    def is_enabled(self):
        return True

    async def ping(self):
        return True

    async def warmup(self, session_id, top_k=16, min_score=0.0):
        self.warmup_calls += 1
        return list(self._blocks)

    async def recall(self, query, session_id=None, top_k=6, min_score=0.0, namespaces=None):
        return list(self._blocks)

    async def push(self, session_id, blocks):
        return len(blocks)

    async def aclose(self):
        pass

    def health_snapshot(self):
        return {"enabled": True, "healthy": True, "url": "stub"}


class _StubMessage:
    def __init__(self, content):
        self.content = content


class _StubChoice:
    def __init__(self, content):
        self.message = _StubMessage(content)


class _StubChatCompletion:
    def __init__(self):
        self.choices = [_StubChoice("</response> hi")]
        self.usage = None


class _StubChatCompletionsAPI:
    async def create(self, **kwargs):
        return _StubChatCompletion()


class _StubChatNamespace:
    def __init__(self):
        self.completions = _StubChatCompletionsAPI()
        self.create = self.completions.create


class _StubAsyncOpenAI:
    def __init__(self):
        self.chat = _StubChatNamespace()


def _make_adapter(stub):
    cfg = StreamingInferAdapter.__init__.__globals__["AdapterConfig"]()
    a = StreamingInferAdapter.__new__(StreamingInferAdapter)
    a.config = cfg
    a.sessions = {}
    a._cleanup_task = None
    a._character_prompt_mtime = 0.0
    a._system_prompt_cache = {}
    a._invalidate_system_prompt_cache = lambda: None
    a._build_memory_prompt = lambda state, **kwargs: "COMPOSED-SYS"
    a.memory_store = stub
    a.main_client = _StubAsyncOpenAI()
    a.main_clients = {cfg.main_model: (a.main_client, cfg.main_model)}
    a.summarizer = None
    return a


@pytest.mark.asyncio
async def test_text_path_no_inline_warmup_no_deadlock():
    stub = _CountingMemoryClient(blocks=[{"block_id": "b1", "content": "X"}])
    a = _make_adapter(stub)
    # get_session schedules the background _memory_warmup_task (same mechanism
    # the multimodal path relies on).
    state = a.get_session("s1")
    payload = {"messages": [{"role": "user", "content": "hi"}]}

    # Reproduce the production path: the text handler holds state.lock across
    # the whole _handle_text_payload call. Wrap in wait_for so a regression
    # that starves the background warmup (and stalls 5s) fails fast instead of
    # "passing for the wrong reason".
    async def _run():
        async with state.lock:
            return await a._handle_text_payload(
                state,
                payload,
                client=a.main_client,
                model_name=a.config.main_model,
                interaction_mode="live",
            )

    result = await asyncio.wait_for(_run(), timeout=3.0)

    # Let the background warmup task finish, then assert the cache is filled
    # by that background task -- NOT by a synchronous inline pull in the handler.
    if state._memory_warmup_task is not None:
        await state._memory_warmup_task
    # Compare by value ignoring the in-place 'source' tag the wiki recall path
    # stamps onto the returned block dicts (same content, extra key only).
    assert [{k: v for k, v in b.items() if k != "source"} for b in state._memory_block_cache] == [
        {"block_id": "b1", "content": "X"}
    ]
    # Exactly one pull total: the handler no longer awaits memory_store.warmup
    # inline (the double-checked lock in _memory_warmup prevents a second pull
    # by the background task).
    assert stub.warmup_calls == 1, f"expected 1 warmup pull, got {stub.warmup_calls}"
    assert result["choices"][0]["message"]["content"] == "hi"
