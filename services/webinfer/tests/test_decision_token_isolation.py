"""Tests for decision-token isolation (issues #44 / #45).

Tier 1 (#44): ``strip_decision_tokens`` removes every decision-token variant
from the end-user ``content`` while ``parse_model_decision`` still powers the
``streamingharness.decision`` field (jarvis depends on it).

Tier 2 (#45): ``interaction_mode`` isolates the decision-token framework:
  * ``call``  -> forced silence OFF + NO_DECISION_SYSTEM_PROMPT (no tokens).
  * ``jarvis`` -> forced silence OFF + decision tokens KEPT (jarvis reads
    ``harness.decision``).
  * ``live``  (default) -> original behaviour (forced silence + tokens).

The test doubles mirror ``tests/test_video_chat_endpoint.py`` (a minimal
``StreamingInferAdapter`` with a stubbed ``AsyncOpenAI`` client, summarizer and
memory-store disabled) so this file stays self-contained.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prompt_constants import NO_DECISION_SYSTEM_PROMPT  # noqa: E402
from response_format import parse_model_decision, strip_decision_tokens  # noqa: E402

# ---------------------------------------------------------------------------
# Test doubles (mirror test_video_chat_endpoint.py)
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
    """Construct a minimal StreamingInferAdapter with a stubbed main client."""
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
    adapter.memory_store = MemoryStoreClient(base_url="http://127.0.0.1:8997", enabled=False)

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
# Tier 1: strip_decision_tokens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("</response> hello there", "hello there"),
        ("</silence>", ""),
        ("</delegation> 查 RTX 5060 Ti 价格", "查 RTX 5060 Ti 价格"),
        ("<silence>", ""),
        ("<response> plain_reply", "plain_reply"),
        ("<delegation> ask the agent", "ask the agent"),
        ("</RESPONSE>  Mixed Case", "Mixed Case"),
        ("  </silence>  ", ""),
        ("</response> note </delegation> actual question", "note actual question"),
        ("just plain text", "just plain text"),
        ("", ""),
    ],
)
def test_strip_decision_tokens_variants(raw: str, expected: str) -> None:
    """Every decision-token variant (case-insensitive) is stripped; body kept."""
    assert strip_decision_tokens(raw) == expected


def test_strip_decision_tokens_keeps_placeholder_text() -> None:
    """``<the question>``-style placeholder text is NOT a token; it is kept."""
    assert strip_decision_tokens("</response> <the question>") == "<the question>"


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Internal-whitespace variants that the first regex leaked (reviewer gap).
        ("</Silence >", ""),
        ("</RESPONSE >", ""),
        ("< silence >", ""),
        ("<delegation > ask the agent", "ask the agent"),
        # Mixed body text around the internally-spaced token must collapse cleanly.
        ("see < response > hi", "see hi"),
        ("before </ Delegation > the question", "before the question"),
    ],
)
def test_strip_decision_tokens_internal_whitespace(raw: str, expected: str) -> None:
    """Tokens with whitespace after '<'/'</' or before '>' are fully stripped (#44 regression).

    The backend reviewer flagged that ``</Silence >`` and ``</RESPONSE >`` still
    leaked to the UI because the original regex required the tag brackets to be
    adjacent to the tag name. The tightened regex allows optional internal
    whitespace so these variants are matched and removed.
    """
    assert strip_decision_tokens(raw) == expected


def test_strip_decision_tokens_preserves_decision_parsing_inputs() -> None:
    """Stripping content does not alter what parse_model_decision sees.

    Callers must pass the RAW text to parse_model_decision; the stripped
    content is purely for display. This guards against the two drifting.
    """
    raw = "</response> 你好"
    decision, clean_text, _ = parse_model_decision(raw)
    assert decision == "response"
    assert clean_text == "你好"
    assert strip_decision_tokens(raw) == "你好"


# ---------------------------------------------------------------------------
# Tier 2: interaction_mode isolation (prompt + forced silence)
# ---------------------------------------------------------------------------


def test_call_mode_build_main_http_messages_uses_no_decision_prompt() -> None:
    """call mode -> uses NO_DECISION_SYSTEM_PROMPT (no silence/speak/delegate framework).

    The no-decision prompt mentions the token names only as examples of what
    NOT to emit, so the meaningful assertion is the absence of the decision
    *framework* ("## Action Format" / "MUST choose exactly one of the three
    actions"), not the literal token strings.
    """
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    msgs = adapter._build_main_http_messages(
        [{"role": "user", "content": "hi"}],
        session_state=state,
        include_decision_tokens=False,
    )
    sys_msgs = [m for m in msgs if m.get("role") == "system"]
    assert sys_msgs, "expected a system message to be composed"
    content = sys_msgs[0]["content"]
    assert content == NO_DECISION_SYSTEM_PROMPT
    assert "## Action Format" not in content
    assert "MUST choose exactly one of the following three actions" not in content


def test_live_mode_build_main_http_messages_keeps_decision_prompt() -> None:
    """live mode (default) -> decision-token framework is preserved."""
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    msgs = adapter._build_main_http_messages(
        [{"role": "user", "content": "hi"}],
        session_state=state,
        include_decision_tokens=True,
    )
    sys_msgs = [m for m in msgs if m.get("role") == "system"]
    assert sys_msgs
    assert "## Action Format" in sys_msgs[0]["content"]
    assert "MUST choose exactly one of the following three actions" in sys_msgs[0]["content"]


def test_is_forced_silence_isolated_by_mode() -> None:
    """Forced silence only fires for live mode with no pending query (#45)."""
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()  # current_query_text defaults to None

    # live + no query -> forced silence (original behaviour)
    assert adapter._is_forced_silence(state, "live") is True
    # live + query pending -> not forced
    state.current_query_text = "hi"
    assert adapter._is_forced_silence(state, "live") is False
    # call / jarvis -> never forced, regardless of query state
    state.current_query_text = None
    assert adapter._is_forced_silence(state, "call") is False
    assert adapter._is_forced_silence(state, "jarvis") is False
    state.current_query_text = "hi"
    assert adapter._is_forced_silence(state, "call") is False
    assert adapter._is_forced_silence(state, "jarvis") is False


def test_normalize_interaction_mode() -> None:
    """Unknown / missing modes fall back to 'live'; known modes pass through."""
    from infer_loop import _normalize_interaction_mode

    assert _normalize_interaction_mode(None) == "live"
    assert _normalize_interaction_mode("") == "live"
    assert _normalize_interaction_mode("CALL") == "call"
    assert _normalize_interaction_mode("jarvis") == "jarvis"
    assert _normalize_interaction_mode("bogus") == "live"


# ---------------------------------------------------------------------------
# Integration: finalize strips content but preserves jarvis decision field
# ---------------------------------------------------------------------------


def test_finalize_strips_token_keeps_response_decision() -> None:
    """content is stripped; decision field (jarvis) preserved."""
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    ctx = _make_finalize_ctx(generated_text="</response> 你好")
    result = adapter._chat_payload_finalize(state, adapter.config.main_model, ctx)
    assert result["choices"][0]["message"]["content"] == "你好"
    assert result["streamingharness"]["decision"] == "response"


def test_finalize_strips_silence_token_keeps_silence_decision() -> None:
    """</silence> -> empty content, but decision='silence' still emitted."""
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    ctx = _make_finalize_ctx(generated_text="</silence>")
    result = adapter._chat_payload_finalize(state, adapter.config.main_model, ctx)
    assert result["choices"][0]["message"]["content"] == ""
    assert result["streamingharness"]["decision"] == "silence"


def test_finalize_strips_delegation_token_keeps_decision_and_question() -> None:
    """Delegation: content stripped, decision + delegation_question preserved."""
    adapter, _ = _make_adapter(scripted=[])
    state = _make_state()
    ctx = _make_finalize_ctx(generated_text="</delegation> 查 RTX 5060 Ti 价格")
    result = adapter._chat_payload_finalize(state, adapter.config.main_model, ctx)
    assert result["choices"][0]["message"]["content"] == "查 RTX 5060 Ti 价格"
    assert result["streamingharness"]["decision"] == "delegation"
    assert result["streamingharness"]["delegation_question"] == "查 RTX 5060 Ti 价格"
