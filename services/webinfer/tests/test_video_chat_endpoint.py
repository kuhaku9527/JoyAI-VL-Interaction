"""Regression tests for the video (/v1/chat/completions) decision path (#2).

P0 fix #2 routed the *video* paths (``_chat_payload_finalize`` and
``_forward_text_only``) through ``parse_model_decision`` and forwarded
``decision`` / ``delegation_question`` into ``_chat_completion_response``,
so the video response now always carries ``streamingharness.decision``
(silence / response / delegation) and ``delegation_question`` -- consistent
with the text path.

Before #2 the video path called ``normalize_model_output`` and never passed
``decision`` / ``delegation_question``, so those fields were missing or None
(see ADR 0008 §9, PRD P1-b). These tests lock the fix in; without them a
silent revert of the video wiring would go undetected (no prior video-path
decision assertion existed).

The harness mirrors ``tests/test_text_chat_endpoint.py``: a minimal
``StreamingInferAdapter`` with a stubbed ``AsyncOpenAI`` client, summarizer
and memory-store disabled for determinism.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Test doubles (mirror test_text_chat_endpoint.py)
# ---------------------------------------------------------------------------


@dataclass
class _StubChoice:
    message: "_StubMessage"


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
    usage: Optional[_StubUsage] = None


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
    def __init__(self, scripted: list[str]) -> None:
        self.completions = _StubChatCompletionsAPI(scripted=scripted)
        # backward-compat: some legacy code paths used .create(...) directly
        self.create = self.completions.create


class _StubAsyncOpenAI:
    def __init__(self, scripted: list[str]) -> None:
        self.chat = _StubChatNamespace(scripted=scripted)

    @property
    def last_kwargs(self) -> dict[str, Any]:
        return self.chat.completions.last_kwargs


def _make_adapter(scripted: list[str]):
    """Construct a minimal StreamingInferAdapter with a stubbed main client.

    Summarizer + memory-store are disabled to keep construction cheap and
    deterministic (same approach as test_text_chat_endpoint.py::_make_adapter).
    """
    from live_adapter import AdapterConfig, StreamingInferAdapter
    from memory_store_client import MemoryStoreClient

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
    adapter.memory_store = MemoryStoreClient(enabled=False)

    stub = _StubAsyncOpenAI(scripted=scripted)
    adapter.main_client = stub  # type: ignore[assignment]
    adapter.main_clients = {cfg.main_model: (stub, cfg.main_model)}  # type: ignore[assignment]
    adapter.summarizer = None
    return adapter, stub


def _make_state(session_id: str = "v1"):
    from live_adapter import StreamingInferAdapter

    Sess = StreamingInferAdapter.__init__.__globals__["SessionState"]
    state = Sess(session_id=session_id)
    # Minimal current_chunk shape finalize appends to.
    state.current_chunk = {"messages": [], "response_records": []}
    return state


def _make_finalize_ctx(*, generated_text: str) -> SimpleNamespace:
    now = time.perf_counter()
    return SimpleNamespace(
        generated_text=generated_text,
        raw_text=generated_text,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        time_range="0.0 seconds",
        query_text="hi",
        turn_count=1,
        turn_input_record={},
        is_forced_silence=False,
        t_start=now,
        t_prompt_build_start=now,
        t_prompt_build_end=now,
        t_inference_end=now,
        inference_time=0.1,
        model_input_record=None,
        chunk_start_model_input_path=None,
    )


# ---------------------------------------------------------------------------
# _forward_text_only -- video text-only forward path (handle_chat_completions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_forward_response_token_emits_decision_response():
    """``</response> hi`` -> decision="response", content="hi", no delegation."""
    adapter, stub = _make_adapter(scripted=["</response> hi"])
    resp = await adapter._forward_text_only(
        {"messages": [{"role": "user", "content": "hi"}]},
        client=stub,
        model_name=adapter.config.main_model,
    )
    # Video path keeps the RAW model output as content by design (ADR 0008 §9:
    # text path strips the token to "hi", video path does NOT), so content
    # still carries the </response> token here.
    harness = resp["streamingharness"]
    assert harness["decision"] == "response"
    assert harness["delegation_question"] is None
    assert resp["choices"][0]["message"]["content"] == "</response> hi"


@pytest.mark.asyncio
async def test_video_forward_silence_token_emits_decision_silence():
    """``</silence>`` -> decision="silence", content="", no delegation."""
    adapter, stub = _make_adapter(scripted=["</silence>"])
    resp = await adapter._forward_text_only(
        {"messages": [{"role": "user", "content": "..."}]},
        client=stub,
        model_name=adapter.config.main_model,
    )
    # Video path keeps the RAW model output (token included) as content.
    harness = resp["streamingharness"]
    assert harness["decision"] == "silence"
    assert harness["delegation_question"] is None
    assert resp["choices"][0]["message"]["content"] == "</silence>"


@pytest.mark.asyncio
async def test_video_forward_delegation_token_emits_decision_and_question():
    """``</delegation> Q`` -> decision="delegation", delegation_question="Q"."""
    adapter, stub = _make_adapter(scripted=["</delegation> 查 RTX 5060 Ti 价格"])
    resp = await adapter._forward_text_only(
        {"messages": [{"role": "user", "content": "帮我查下价格"}]},
        client=stub,
        model_name=adapter.config.main_model,
    )
    # Video path keeps the RAW model output (token included) as content.
    harness = resp["streamingharness"]
    assert harness["decision"] == "delegation"
    assert harness["delegation_question"] == "查 RTX 5060 Ti 价格"
    assert resp["choices"][0]["message"]["content"] == "</delegation> 查 RTX 5060 Ti 价格"


# ---------------------------------------------------------------------------
# _chat_payload_finalize -- primary video finalize path (ADR 0008 §9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_finalize_response_token_emits_decision_response():
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    ctx = _make_finalize_ctx(generated_text="</response> hi")
    result = adapter._chat_payload_finalize(state, adapter.config.main_model, ctx)
    harness = result["streamingharness"]
    assert harness["decision"] == "response"
    assert harness["delegation_question"] is None


@pytest.mark.asyncio
async def test_video_finalize_delegation_token_emits_decision_and_question():
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    ctx = _make_finalize_ctx(generated_text="</delegation> 查 RTX 5060 Ti 价格")
    result = adapter._chat_payload_finalize(state, adapter.config.main_model, ctx)
    harness = result["streamingharness"]
    assert harness["decision"] == "delegation"
    assert harness["delegation_question"] == "查 RTX 5060 Ti 价格"
