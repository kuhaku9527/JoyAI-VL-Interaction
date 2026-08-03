"""Regression test: text-chat path must not self-deadlock on state.lock.

Background
----------
``handle_text_chat`` (infer_loop.py) holds ``state.lock`` across the entire
``_handle_text_payload`` call. That call invokes
``MemoryIOMixin._memory_recall`` (memory_io.py), which acquires ``state.lock``
*internally* -- and ``asyncio.Lock`` is not reentrant, so the same coroutine
deadlocked forever. Because ``_memory_recall`` is reached on every text-chat
turn (not just when the memory-store is enabled), the request loop hung
indefinitely and ``pytest (webinfer)`` on CI stalled for >= 55 min.

This test drives the real ``handle_text_chat`` surface with a stub memory
client and asserts the call returns within ``asyncio.wait_for(..., 5s)``.
A deadlock makes ``wait_for`` raise ``TimeoutError`` and the test fails --
exactly reproducing the CI hang as a fast, local signal.

It covers every branch that previously deadlocked:

* memory enabled  -> direct warmup sets ``_memory_warmed``; recall then hits
  the ``async with state.lock`` at ``memory_io._memory_recall`` (~line 182);
* memory disabled -> recall falls through to ``_memory_warmup`` (~line 141),
  which also re-acquires ``state.lock``;
* empty user text -> recall takes the ``if not question`` early-return branch
  (~line 173), which *also* re-acquires ``state.lock``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Self-contained HTTP-seam test doubles (mirrors test_text_chat_endpoint).
# Defined locally rather than imported from a sibling test module so the
# file collects cleanly whether pytest is invoked with an explicit file list
# or with the whole ``tests/`` directory.


class _StreamProtocol:
    """Minimal protocol stub aiohttp.streams.StreamReader needs to feed_data."""

    def resume_reading(self, *args, **kwargs):
        pass

    def pause_reading(self, *args, **kwargs):
        pass


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def model_dump(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class _StubChatCompletion:
    choices: list[_StubChoice]
    usage: _StubUsage | None = None


class _StubChatCompletionsAPI:
    """Mirrors the openai SDK layout: client.chat.completions.create(...)."""

    def __init__(self, scripted: list[str]) -> None:
        self._scripted = list(scripted)
        self.last_kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> _StubChatCompletion:
        self.last_kwargs = kwargs
        content = self._scripted.pop(0) if self._scripted else "</silence>"
        return _StubChatCompletion(
            choices=[_StubChoice(message=_StubMessage(content=content))],
            usage=_StubUsage(),
        )


class _StubChatNamespace:
    """client.chat -> _StubChatNamespace; .completions -> _StubChatCompletionsAPI."""

    def __init__(self, scripted: list[str]) -> None:
        self.completions = _StubChatCompletionsAPI(scripted=scripted)
        self.create = self.completions.create


class _StubAsyncOpenAI:
    def __init__(self, scripted: list[str]) -> None:
        self.chat = _StubChatNamespace(scripted=scripted)

    @property
    def last_kwargs(self) -> dict[str, Any]:
        return self.chat.completions.last_kwargs


class _StubMemoryClient:
    """In-memory memory-store stub returning fixed blocks.

    ``is_enabled`` is configurable so we can exercise both deadlock
    branches (direct-warmup vs recall-triggered warmup).
    """

    def __init__(self, blocks: list[dict], *, enabled: bool) -> None:
        self._blocks = list(blocks)
        self._enabled = enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def ping(self) -> bool:
        return True

    async def warmup(self, session_id: str, top_k: int = 16, min_score: float = 0.0) -> list[dict]:
        return list(self._blocks)

    async def recall(self, *args: object, **kwargs: object) -> list[dict]:
        return list(self._blocks)

    async def push(self, session_id: str, blocks: list[dict]) -> int:
        return len(blocks)

    async def aclose(self) -> None:
        pass

    def health_snapshot(self) -> dict:
        return {"enabled": self._enabled, "healthy": True}


def _make_adapter(*, memory_blocks: list[dict], memory_enabled: bool):
    """Build a minimal StreamingInferAdapter with a stubbed main + memory client.

    Mirrors ``test_text_chat_endpoint._make_adapter`` but wires a memory
    client so the recall path is exercised on every turn.
    """
    from live_adapter import AdapterConfig, StreamingInferAdapter

    cfg = AdapterConfig()
    cfg.enable_summarizer = False
    cfg.character_prompts_enabled = False
    cfg.memory_store_enabled = memory_enabled
    cfg.main_ctx_tokens = 16384

    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.config = cfg
    adapter.sessions = {}
    adapter._cleanup_task = None
    adapter._character_prompt_mtime = 0.0
    adapter._system_prompt_cache = {}
    adapter._invalidate_system_prompt_cache = lambda: None
    adapter._build_memory_prompt = lambda state, **kwargs: "COMPOSED-SYS"
    adapter.memory_store = _StubMemoryClient(memory_blocks, enabled=memory_enabled)

    stub = _StubAsyncOpenAI(scripted=["</response> hi"])
    adapter.main_client = stub  # type: ignore[assignment]
    adapter.main_clients = {cfg.main_model: (stub, cfg.main_model)}  # type: ignore[assignment]
    adapter.summarizer = None
    return adapter


def _post_json(adapter, body: dict, session_id: str | None = None):
    """Build a mocked POST request and dispatch to handle_text_chat."""
    from aiohttp import streams

    raw = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["x-streaming-session"] = session_id
    loop = asyncio.get_running_loop()
    stream = streams.StreamReader(
        protocol=_StreamProtocol(),
        limit=2**16,
        loop=loop,
    )
    stream.feed_data(raw)
    stream.feed_eof()
    request = make_mocked_request("POST", "/v1/text/chat", headers=headers, payload=stream)

    async def _run():
        return await adapter.handle_text_chat(request)

    return _run()


@pytest.mark.asyncio
async def test_text_chat_memory_enabled_no_deadlock():
    """Enabled memory-store (production JOYAI_ENABLE_MEMORY_STORE=1 path)."""
    adapter = _make_adapter(
        memory_blocks=[{"block_id": "b1", "content": "X-Wing reverse-thrust"}],
        memory_enabled=True,
    )
    body = {
        "model": "joyai-vl-interaction-preview",
        "messages": [{"role": "user", "content": "hi"}],
    }
    # Without the re-entrant lock fix this suspends forever on state.lock and
    # wait_for raises TimeoutError (the >=55 min CI hang, reproduced locally).
    resp = await asyncio.wait_for(_post_json(adapter, body, session_id="mem-on-1"), timeout=5)
    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["choices"][0]["message"]["content"] == "hi"


@pytest.mark.asyncio
async def test_text_chat_memory_disabled_no_deadlock():
    """Disabled memory-store still routes through _memory_recall -> deadlock historically."""
    adapter = _make_adapter(memory_blocks=[], memory_enabled=False)
    body = {
        "model": "joyai-vl-interaction-preview",
        "messages": [{"role": "user", "content": "hello"}],
    }
    resp = await asyncio.wait_for(_post_json(adapter, body, session_id="mem-off-1"), timeout=5)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_text_chat_empty_user_text_no_deadlock():
    """Empty user text takes the `if not question` early-return branch in _memory_recall."""
    adapter = _make_adapter(
        memory_blocks=[{"block_id": "b2", "content": "wiki fact"}],
        memory_enabled=True,
    )
    body = {
        "model": "joyai-vl-interaction-preview",
        "messages": [{"role": "system", "content": "x"}],
    }
    resp = await asyncio.wait_for(_post_json(adapter, body, session_id="empty-q-1"), timeout=5)
    assert resp.status == 200
