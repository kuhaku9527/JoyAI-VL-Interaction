"""Tests for the v3.37 ``POST /v1/text/chat`` endpoint.

This endpoint is the single LLM gateway for Jarvis voice dialog. It
takes a text-only OpenAI-style chat-completion request and returns:

* the model's reply with decision tokens stripped (``</silence>`` /
  ``</response> X`` / ``</delegation> Q`` resolved into a clean ``text``
  field), so the caller never has to re-parse them before TTS;
* a ``streamingharness.decision`` block telling the caller which
  action to take (silence / respond / delegate);
* the same character-profile + [Local Wiki] + prompt-token-guard
  treatment as the multi-modal ``/v1/chat/completions`` path, so both
  video and voice sessions converge on a single persona + memory.

The tests in this file exercise the **public HTTP seam** via
``aiohttp.test_utils.make_mocked_request`` against a
``StreamingInferAdapter`` whose ``AsyncOpenAI`` client is stubbed.

Slice 1 covers: basic acceptance, image rejection, role validation,
and decision-token parsing for ``</silence>`` / ``</response>``.
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


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubMessage:
    content: str


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
        content = "</silence>" if not self._scripted else self._scripted.pop(0)
        return _StubChatCompletion(
            choices=[_StubChoice(message=_StubMessage(content=content))],
            usage=_StubUsage(),
        )


class _StubChatNamespace:
    """client.chat -> _StubChatNamespace; .completions -> _StubChatCompletionsAPI."""

    def __init__(self, scripted: list[str]) -> None:
        self.completions = _StubChatCompletionsAPI(scripted=scripted)
        # backward-compat: some legacy code paths used .create(...) directly
        self.create = self.completions.create


class _StubAsyncOpenAI:
    def __init__(self, scripted: list[str]) -> None:
        self.chat = _StubChatNamespace(scripted=scripted)

    @property
    def last_kwargs(self) -> dict[str, Any]:
        # Live reference so callers always see the most recent call.
        return self.chat.completions.last_kwargs


def _make_adapter(scripted: list[str]) -> tuple[Any, _StubAsyncOpenAI]:
    """Construct a minimal StreamingInferAdapter with a stubbed main client.

    The summarizer + memory-store are disabled to keep construction cheap.
    """
    from live_adapter import (
        AdapterConfig,
        StreamingInferAdapter,
    )

    cfg = AdapterConfig()
    cfg.enable_summarizer = False
    cfg.character_prompts_enabled = False  # keep system prompt predictable
    cfg.memory_store_enabled = False
    cfg.main_ctx_tokens = 16384

    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.config = cfg
    adapter.sessions = {}
    adapter._cleanup_task = None
    adapter._character_prompt_mtime = 0.0
    adapter._system_prompt_cache = {}
    adapter._invalidate_system_prompt_cache = lambda: None
    # Disable memory-store client so warmup is a no-op.
    from memory_store_client import MemoryStoreClient

    adapter.memory_store = MemoryStoreClient(enabled=False)

    stub = _StubAsyncOpenAI(scripted=scripted)
    adapter.main_client = stub  # type: ignore[assignment]
    adapter.main_clients = {cfg.main_model: (stub, cfg.main_model)}  # type: ignore[assignment]
    adapter.summarizer = None
    return adapter, stub


class _StreamProtocol:
    """Minimal protocol stub aiohttp.streams.StreamReader needs to feed_data."""

    def resume_reading(self, *args, **kwargs):
        pass

    def pause_reading(self, *args, **kwargs):
        pass


def _post_json(adapter: Any, body: dict[str, Any], session_id=None) -> Any:
    """Build a mocked POST request and dispatch to handle_text_chat.

    Uses a real StreamReader so request.json() returns the bytes we
    feed it.
    """
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


# ---------------------------------------------------------------------------
# Slice 1 — basic acceptance / rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_chat_returns_clean_text_on_response_token():
    """``</response> hi`` -> 200, content="hi", decision="response"."""
    adapter, _stub = _make_adapter(scripted=["</response> hi"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "hello"}],
        },
        session_id="s1",
    )
    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["choices"][0]["message"]["content"] == "hi"
    harness = payload["streamingharness"]
    assert harness["decision"] == "response"
    # delegation_question must be present (None for non-delegation responses)
    # so the field shape is consistent for jarvis_mode consumers.
    assert "delegation_question" in harness
    assert harness["delegation_question"] is None
    # raw_content must preserve the unparsed model output for debugging.
    assert harness["raw_content"] == "</response> hi"


@pytest.mark.asyncio
async def test_text_chat_returns_empty_on_silence_token():
    """``</silence>`` -> 200, content="", decision="silence"."""
    adapter, _stub = _make_adapter(scripted=["</silence>"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "..."}],
        },
        session_id="s2",
    )
    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["choices"][0]["message"]["content"] == ""
    assert payload["streamingharness"]["decision"] == "silence"


@pytest.mark.asyncio
async def test_text_chat_returns_delegation_question_on_delegation_token():
    """``</delegation> Q`` -> decision="delegation", delegation_question="Q", content=""."""
    adapter, _stub = _make_adapter(scripted=["</delegation> 查 RTX 5060 Ti 价格"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "帮我查下 RTX 5060 Ti 价格"}],
        },
        session_id="s3",
    )
    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["choices"][0]["message"]["content"] == ""
    harness = payload["streamingharness"]
    assert harness["decision"] == "delegation"
    assert harness["delegation_question"] == "查 RTX 5060 Ti 价格"


@pytest.mark.asyncio
async def test_text_chat_rejects_image_url_content():
    """Any message with image_url content part -> 400."""
    adapter, _stub = _make_adapter(scripted=["</silence>"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64,..."},
                        },
                    ],
                }
            ],
        },
        session_id="s4",
    )
    assert resp.status == 400
    body = json.loads(resp.text)
    assert "image" in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_text_chat_rejects_data_url_in_text_content():
    """A string content that itself contains a data: image URL -> 400.

    Catches callers who try to sneak a base64 image through as text.
    """
    adapter, _stub = _make_adapter(scripted=["</silence>"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [
                {
                    "role": "user",
                    "content": "look at this image data:image/jpeg;base64,AAA",
                }
            ],
        },
        session_id="s5",
    )
    assert resp.status == 400
    body = json.loads(resp.text)
    assert "image" in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_text_chat_rejects_invalid_role():
    """role outside {system,user,assistant} -> 400."""
    adapter, _stub = _make_adapter(scripted=["</silence>"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "tool", "content": "x"}],
        },
        session_id="s6",
    )
    assert resp.status == 400
    body = json.loads(resp.text)
    assert "role" in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_text_chat_rejects_missing_messages():
    """No messages field -> 400."""
    adapter, _stub = _make_adapter(scripted=["</silence>"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
        },
        session_id="s7",
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_text_chat_forwards_messages_to_main_client():
    """The main_client receives the caller's messages, plus an injected system prompt.

    The composed system prompt may include the base decision-token prompt
    so we cannot pin an exact value here; this test only pins the
    non-system messages, which must be forwarded verbatim.
    """
    adapter, stub = _make_adapter(scripted=["</response> ok"])

    resp = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [
                {"role": "system", "content": "you are concise"},
                {"role": "user", "content": "hi"},
            ],
        },
        session_id="s8",
    )
    assert resp.status == 200
    forwarded = stub.last_kwargs["messages"]
    # User/assistant turns pass through verbatim. Caller-supplied system
    # is replaced by the composed one (see slice 2 test_text_chat_replaces_caller_system_with_composed).
    non_system = [m for m in forwarded if m["role"] != "system"]
    assert non_system == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_text_chat_uses_session_header_for_state_isolation():
    """Two sessions with different headers get independent SessionState."""
    adapter, _stub = _make_adapter(
        scripted=[
            "</response> A1",
            "</response> A2",
        ]
    )

    resp_a = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "u1"}],
        },
        session_id="session-A",
    )
    resp_b = await _post_json(
        adapter,
        {
            "model": "joyai-vl-interaction-preview",
            "messages": [{"role": "user", "content": "u2"}],
        },
        session_id="session-B",
    )
    assert resp_a.status == 200
    assert resp_b.status == 200
    # Each session created its own SessionState object.
    assert "session-A" in adapter.sessions
    assert "session-B" in adapter.sessions
    assert adapter.sessions["session-A"] is not adapter.sessions["session-B"]
