"""Regression: send_to_session must actually run ws.send_str (not just create_task it).

The old implementation used:

    asyncio.create_task(ws.send_str(message))

In a smoke test with no awaits inside FakeWS.send_str that worked (the coroutine
ran to completion synchronously). The real aiohttp ``send_str`` does await
internally (acquire WS lock, drain queue, write frame), so a fire-and-forget
``create_task`` schedules the coroutine but the event loop never actually gets to
run it before the surrounding coroutine returns. Symptom: the browser never sees
``llm_reply`` / ``vlm_response`` / ``background_result_ready`` WS messages.

These tests use a FakeWS whose ``send_str`` yields with ``asyncio.sleep(0)`` to
mimic aiohttp's real behaviour; under the old code they FAIL, under the fix
they PASS.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _isolate_session():
    from joy_interaction_webui import server

    server.websockets.clear()
    server.session_websockets.clear()
    server.ws_to_session.clear()
    yield
    server.websockets.clear()
    server.session_websockets.clear()
    server.ws_to_session.clear()


class AiohttpLikeWS:
    """Fake aiohttp WebSocketResponse.send_str that yields like the real one."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_str(self, s: str) -> None:
        # Yield once so the coroutine isn't synchronously runnable when
        # scheduled via bare asyncio.create_task(ws.send_str(...))
        await asyncio.sleep(0)
        self.sent.append(s)


def test_send_to_session_actually_delivers_to_yielding_ws():
    from joy_interaction_webui import server

    async def _run():
        ws = AiohttpLikeWS()
        server.session_websockets.setdefault("s1", set()).add(ws)
        server.send_to_session("s1", "hello")
        # Give the scheduler time to run the task we just scheduled
        for _ in range(5):
            await asyncio.sleep(0)
        return ws.sent

    sent = asyncio.run(_run())
    assert sent == ["hello"], f"send_to_session did not deliver: got {sent!r}"


def test_send_to_session_isolated_by_session_id():
    from joy_interaction_webui import server

    async def _run():
        a = AiohttpLikeWS()
        b = AiohttpLikeWS()
        server.session_websockets.setdefault("s1", set()).add(a)
        server.session_websockets.setdefault("s2", set()).add(b)
        server.send_to_session("s1", "to-a")
        for _ in range(5):
            await asyncio.sleep(0)
        return a.sent, b.sent

    a_sent, b_sent = asyncio.run(_run())
    assert a_sent == ["to-a"]
    assert b_sent == []


def test_send_to_session_swallows_broken_ws():
    from joy_interaction_webui import server

    class BrokenWS:
        async def send_str(self, s: str) -> None:
            raise RuntimeError("ws is closed")

    async def _run():
        good = AiohttpLikeWS()
        bad = BrokenWS()
        server.session_websockets.setdefault("s1", set()).add(good)
        server.session_websockets.setdefault("s1", set()).add(bad)
        server.send_to_session("s1", "hello")
        for _ in range(5):
            await asyncio.sleep(0)
        return good.sent

    sent = asyncio.run(_run())
    assert sent == ["hello"], f"send_to_session should not crash on bad WS: {sent!r}"
