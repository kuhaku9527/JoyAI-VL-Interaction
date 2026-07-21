"""Slice 3 — jarvis_mode routes LLM calls through webinfer.

Voice path no longer talks to llama-server directly. Two endpoints:

* ``/v1/text/chat``         — text-only (default)
* ``/v1/chat/completions``  — multimodal (when image_b64 is provided)

Both URLs share the same base (``llm_api_url``); only the suffix differs.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisStateMachine


class _FakeResponse:
    def __init__(self, body):
        self._body = body
    def raise_for_status(self):
        pass
    def json(self):
        return self._body


def _build_sm(llm_api_url="http://stub/v1"):
    """Build a JarvisStateMachine that talks to a stub URL."""
    cfg = JarvisConfig(
        wake_word="bt",
        sample_rate=16000,
        kws_model_dir="ignored",
        asr_model_dir="ignored",
        llm_api_url=llm_api_url,
        llm_model="stub",
        llm_system_prompt="be brief",
    )
    return JarvisStateMachine(config=cfg)


def _capturing_client(requests, response_body):
    """Patch httpx.AsyncClient so we capture the URL + JSON of every POST.

    Returns a context-manager-like object whose ``post(url, json=...)`` is
    an awaitable returning ``_FakeResponse(response_body)``.
    """
    client = AsyncMock()

    async def post(url, json=None, **kwargs):
        requests.append({"url": url, "json": json})
        return _FakeResponse(response_body)

    client.post = post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _chat_completion_response(content: str, decision: str = "response",
                              delegation_question=None) -> dict:
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "stub",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "streamingharness": {
            "main_model": "stub",
            "raw_content": content,
            "decision": decision,
            "delegation_question": delegation_question,
            "memory_chars": 0,
            "qa_history_len": 0,
            "prompt_chars": 0,
            "trimmed_turns": 0,
        },
    }
    return body


def test_jarvis_default_url_routes_through_webinfer_text_chat():
    """Default llm_api_url must be webinfer + /v1/text/chat suffix."""
    cfg = JarvisConfig(
        wake_word="bt",
        kws_model_dir="ignored",
        asr_model_dir="ignored",
        llm_model="stub",
        llm_system_prompt="be brief",
    )
    # Default base must be the webinfer OpenAI-compatible gateway, not 7060.
    assert cfg.llm_api_url.startswith("http://127.0.0.1:8070"), (
        f"voice path bypasses webinfer; got llm_api_url={cfg.llm_api_url!r}"
    )
    # The text-only sub-path must be /v1/text/chat (single LLM gateway).
    assert cfg.llm_text_path == "/text/chat"


def test_jarvis_text_only_posts_to_webinfer_text_chat():
    """_send_to_llm(text) hits /v1/text/chat on the configured base URL."""
    requests: list = []

    async def run():
        sm = _build_sm(llm_api_url="http://webinfer:8070/v1")
        captured = _capturing_client(
            requests, _chat_completion_response("hi", decision="response")
        )
        with patch("httpx.AsyncClient", return_value=captured):
            await sm._send_to_llm("hello", stream_tts=False)
        return sm

    sm = asyncio.run(run())
    assert len(requests) == 1
    assert requests[0]["url"] == "http://webinfer:8070/v1/text/chat"


def test_jarvis_image_b64_posts_to_webinfer_chat_completions():
    """_send_to_llm(text, image_b64=...) hits /v1/chat/completions for multimodal."""
    requests: list = []

    async def run():
        sm = _build_sm(llm_api_url="http://webinfer:8070/v1")
        captured = _capturing_client(
            requests, _chat_completion_response("ok", decision="response")
        )
        with patch("httpx.AsyncClient", return_value=captured):
            await sm._send_to_llm(
                "what is in this image?",
                stream_tts=False,
                image_b64="AAAA",
            )
        return sm

    sm = asyncio.run(run())
    assert len(requests) == 1
    assert requests[0]["url"] == "http://webinfer:8070/v1/chat/completions"


def test_jarvis_text_only_payload_is_text_only():
    """Voice text-only payload must not carry image_url content parts."""
    requests: list = []

    async def run():
        sm = _build_sm(llm_api_url="http://webinfer:8070/v1")
        captured = _capturing_client(
            requests, _chat_completion_response("ok", decision="response")
        )
        with patch("httpx.AsyncClient", return_value=captured):
            await sm._send_to_llm("hello", stream_tts=False)

    asyncio.run(run())
    sent = requests[0]["json"]
    for message in sent["messages"]:
        if isinstance(message.get("content"), list):
            for part in message["content"]:
                assert part.get("type") != "image_url", (
                    "text-only path leaked image_url content"
                )


def test_jarvis_strips_decision_tokens_before_broadcast():
    """webinfer returns decision='response' + clean content; jarvis broadcasts clean."""
    broadcast: list = []

    async def run():
        sm = _build_sm(llm_api_url="http://webinfer:8070/v1")
        sm.on_llm_response = lambda text, source: broadcast.append(text)
        captured = _capturing_client(
            requests=[],
            response_body=_chat_completion_response(
                "Confirmed.",
                decision="response",
            ),
        )
        with patch("httpx.AsyncClient", return_value=captured):
            await sm._send_to_llm("hi", stream_tts=False)

    asyncio.run(run())
    # Broadcast must be the clean assistant text, never include
    # </response> / </silence> / </delegation> tokens.
    assert broadcast == ["Confirmed."]


def test_jarvis_skips_tts_on_silence():
    """When webinfer returns decision='silence', _stream_tts must NOT be invoked."""
    async def run():
        sm = _build_sm(llm_api_url="http://webinfer:8070/v1")
        captured = _capturing_client(
            requests=[],
            response_body=_chat_completion_response("", decision="silence"),
        )
        with patch("httpx.AsyncClient", return_value=captured):
            await sm._send_to_llm("hi", stream_tts=True)
        return sm

    sm = asyncio.run(run())
    # No TTS task was scheduled.
    assert sm._tts_task is None


def test_jarvis_triggers_delegation_on_delegation_decision():
    """webinfer returns decision='delegation' + question -> BackgroundModelService fires."""
    captured_payloads: list = []

    class _StubBackgroundService:
        def __init__(self):
            self.enabled = True
            self._closed = False
        def handle_foreground_response(self, text, metrics=None):
            captured_payloads.append({"text": text, "metrics": metrics})

    sm = _build_sm(llm_api_url="http://webinfer:8070/v1")
    sm._background_service = _StubBackgroundService()  # type: ignore[attr-defined]

    async def run():
        captured = _capturing_client(
            requests=[],
            response_body=_chat_completion_response(
                "",
                decision="delegation",
                delegation_question="查 RTX 5060 Ti 价格",
            ),
        )
        with patch("httpx.AsyncClient", return_value=captured):
            await sm._send_to_llm("帮我查 RTX 5060 Ti 价格", stream_tts=False)

    asyncio.run(run())
    assert len(captured_payloads) == 1
    # The delegation payload must include the delegated question so the
    # background sub-agent has the same context as the user's original ask.
    assert "查 RTX 5060 Ti 价格" in captured_payloads[0]["text"]
