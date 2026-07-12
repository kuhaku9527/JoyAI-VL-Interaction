"""Regression test for v3.24: conversation history is appended to LLM context.

Uses monkeypatching of httpx.AsyncClient to capture messages without actually
hitting the network.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisStateMachine


class FakeResponse:
    def __init__(self, text):
        self._text = text
    def raise_for_status(self):
        pass
    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


def _build_sm():
    cfg = JarvisConfig(
        wake_word="bt",
        sample_rate=16000,
        kws_model_dir="ignored",
        asr_model_dir="ignored",
        llm_api_url="http://stub",
        llm_model="stub",
        llm_system_prompt="be brief",
    )
    return JarvisStateMachine(config=cfg)


def _make_client(captured):
    client = AsyncMock()
    captured_holder = captured

    def make_post(*a, **kw):
        async def post(url, json):
            captured_holder.append(json)
            return FakeResponse("Confirmed.")
        return post
    client.post = make_post()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def test_first_turn_has_no_history():
    captured = []
    client = _make_client(captured)

    async def go():
        sm = _build_sm()
        with patch("httpx.AsyncClient", return_value=client):
            await sm._send_to_llm("hello")
        return sm, captured

    sm, captured = asyncio.run(go())
    assert len(captured) == 1
    msgs = captured[0]["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "hello"}


def test_second_turn_has_first_turn_in_history():
    captured = []
    client = _make_client(captured)

    async def go():
        sm = _build_sm()
        with patch("httpx.AsyncClient", return_value=client):
            await sm._send_to_llm("hello")
            await sm._send_to_llm("who are you")
        return captured

    captured = asyncio.run(go())
    assert len(captured) == 2
    msgs = captured[1]["messages"]
    # system + 2 history (turn1 user + assistant) + new user = 4
    assert len(msgs) == 4, f"got {len(msgs)}: {msgs}"
    assert msgs[1] == {"role": "user", "content": "hello"}
    assert msgs[2] == {"role": "assistant", "content": "Confirmed."}
    assert msgs[3] == {"role": "user", "content": "who are you"}


def test_history_bounded_by_max_turns():
    captured = []
    client = _make_client(captured)

    async def go():
        sm = _build_sm()
        with patch("httpx.AsyncClient", return_value=client):
            for i in range(25):
                await sm._send_to_llm(f"turn-{i}")
        return captured, sm

    captured, sm = asyncio.run(go())
    assert len(captured) == 25
    msgs_last = captured[-1]["messages"]
    # system + max_history_turns * 2 history + new user = 1 + 20 + 1 = 22
    assert len(msgs_last) == 22, (
        f"history not bounded: {len(msgs_last)} messages"
    )
    # Latest user message is at the end
    assert msgs_last[-1]["content"] == "turn-24"
    # Oldest retained is turn-(25-10-1) = turn-14
    user_msgs = [m["content"] for m in msgs_last if m["role"] == "user"]
    assert user_msgs[0] == "turn-14", user_msgs
    assert user_msgs[-1] == "turn-24", user_msgs
