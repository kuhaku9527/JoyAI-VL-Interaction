"""Slice 2 — ``POST /v1/text/chat`` composes system prompt + memory.

The voice path must use the **same** character profile + [Local Wiki]
injection as the multimodal ``/v1/chat/completions`` path. Otherwise
persona drift and missing memory defeat the whole consolidation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for _p in (str(ROOT), str(TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import helpers from the slice-1 test module; both live under tests/.
from test_text_chat_endpoint import (  # type: ignore[no-redef]  # noqa: E402
    _StreamProtocol,
    _StubAsyncOpenAI,
)


def _make_adapter(scripted, *, character_enabled=False, memory_blocks=None):
    """Build an adapter with character + memory hooks enabled.

    When ``memory_blocks`` is a non-empty list, the adapter's
    :class:`MemoryStoreClient` returns them from warmup/recall.
    """
    from live_adapter import AdapterConfig, StreamingInferAdapter

    cfg = AdapterConfig()
    cfg.enable_summarizer = False
    cfg.character_prompts_enabled = character_enabled
    cfg.memory_store_enabled = bool(memory_blocks)
    cfg.main_ctx_tokens = 16384

    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.config = cfg
    adapter.sessions = {}
    adapter._cleanup_task = None
    adapter._character_prompt_mtime = 0.0
    adapter._system_prompt_cache = {}
    adapter._invalidate_system_prompt_cache = lambda: None

    # In-memory MemoryStoreClient stub: warmup returns the blocks
    class _StubMemoryClient:
        def __init__(self, blocks):
            self._blocks = list(blocks)

        @property
        def is_enabled(self):
            return True

        async def ping(self):
            return True

        async def warmup(self, session_id, top_k=16, min_score=0.0):
            return list(self._blocks)

        async def recall(self, *a, **k):
            return list(self._blocks)

        async def push(self, session_id, blocks):
            return len(blocks)

        async def aclose(self):
            pass

        def health_snapshot(self):
            return {"enabled": True, "healthy": True}

    adapter.memory_store = _StubMemoryClient(memory_blocks or [])

    stub = _StubAsyncOpenAI(scripted=scripted)
    adapter.main_client = stub
    adapter.main_clients = {cfg.main_model: (stub, cfg.main_model)}
    adapter.summarizer = None
    return adapter, stub


def _post_json(adapter, body, session_id=None):
    from aiohttp import streams

    raw = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["x-streaming-session"] = session_id
    loop = asyncio.new_event_loop()
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


def _seed_character_file(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "char.txt"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_text_chat_includes_character_profile_in_system(tmp_path):
    """With a character prompt on disk, the main client sees it in messages[0]."""
    char_body = "You are BT-7274, Vanguard-class Titan AI assistant."
    char_path = _seed_character_file(tmp_path, char_body)
    adapter, stub = _make_adapter(
        scripted=["</response> hi"],
        character_enabled=True,
    )
    # Override the character_prompt_paths to point at our tmp file.
    adapter.config.character_prompt_paths = (str(char_path),)
    adapter._load_character_profiles = lambda: [char_body]
    adapter._build_memory_prompt = lambda state: (
        f"<character_profile>{char_body}</character_profile>\n\nbase decision prompt"
    )

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "hi"}],
        },
        session_id="char-1",
    )
    assert resp.status == 200
    forwarded = stub.last_kwargs["messages"]
    assert forwarded[0]["role"] == "system"
    assert "<character_profile>" in forwarded[0]["content"]
    assert "BT-7274" in forwarded[0]["content"]


@pytest.mark.asyncio
async def test_text_chat_includes_local_wiki_when_memory_warms():
    """When memory-store warms up blocks, the system prompt includes [Local Wiki]."""
    adapter, stub = _make_adapter(
        scripted=["</response> hi"],
        memory_blocks=[
            {
                "block_id": "b1",
                "content": "X-Wing pilot ace maneuver is reverse-thrust",
            },
        ],
    )
    adapter._build_memory_prompt = lambda state: (
        "[Local Wiki]\nb1: X-Wing pilot ace maneuver is reverse-thrust\nbase"
    )

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "hi"}],
        },
        session_id="wiki-1",
    )
    assert resp.status == 200
    forwarded = stub.last_kwargs["messages"]
    assert forwarded[0]["role"] == "system"
    assert "[Local Wiki]" in forwarded[0]["content"]
    assert "reverse-thrust" in forwarded[0]["content"]


@pytest.mark.asyncio
async def test_text_chat_replaces_caller_system_with_composed():
    """If the caller supplied a system message, the composed one wins.

    Avoids two-system-message drift between video and voice paths.
    """
    adapter, stub = _make_adapter(scripted=["</response> ok"])
    adapter._build_memory_prompt = lambda state: "COMPOSED-SYS"

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [
                {"role": "system", "content": "USER-SUPPLIED-SYS"},
                {"role": "user", "content": "hi"},
            ],
        },
        session_id="merge-1",
    )
    assert resp.status == 200
    forwarded = stub.last_kwargs["messages"]
    system_messages = [m for m in forwarded if m["role"] == "system"]
    # Exactly one system message (the composed one).
    assert len(system_messages) == 1
    assert system_messages[0]["content"] == "COMPOSED-SYS"


@pytest.mark.asyncio
async def test_text_chat_prepends_composed_when_no_caller_system():
    """No caller system -> composed goes in front, then user/assistant."""
    adapter, stub = _make_adapter(scripted=["</response> ok"])
    adapter._build_memory_prompt = lambda state: "COMPOSED-SYS"

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hey"},
                {"role": "user", "content": "how are you?"},
            ],
        },
        session_id="nosys-1",
    )
    assert resp.status == 200
    forwarded = stub.last_kwargs["messages"]
    assert forwarded[0] == {"role": "system", "content": "COMPOSED-SYS"}
    assert forwarded[1:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
        {"role": "user", "content": "how are you?"},
    ]


@pytest.mark.asyncio
async def test_text_chat_skips_compose_when_no_prompt_and_no_memory():
    """When both character and memory are empty, no system message is injected.

    Behaviour: text/chat is a thin orchestration surface. Empty compose
    means the caller's messages are forwarded verbatim (degenerate case).
    """
    adapter, stub = _make_adapter(scripted=["</response> ok"])
    adapter._build_memory_prompt = lambda state: ""

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "hi"}],
        },
        session_id="empty-1",
    )
    assert resp.status == 200
    forwarded = stub.last_kwargs["messages"]
    assert forwarded == [{"role": "user", "content": "hi"}]
