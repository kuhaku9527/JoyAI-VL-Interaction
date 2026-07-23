"""Slice 4 — JarvisSessionManager wires BackgroundModelService into the state machine.

When ``create_session`` runs, it must look up the BackgroundModelService
that server.py registered in ``sessions[session_id]`` and assign it to
``sm._background_service``. That way the delegation routing in
``_send_to_llm`` fires for voice requests, just like it does for video.

Conversely, the per-turn ``_make_llm_callback`` no longer needs to do
its own delegation routing (that is now centralized in ``_send_to_llm``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui.jarvis_mode import JarvisConfig  # noqa: E402
from joy_interaction_webui.jarvis_session import JarvisSessionManager  # noqa: E402


def _build_manager():
    cfg = JarvisConfig(
        wake_word="bt",
        kws_model_dir="ignored",
        asr_model_dir="ignored",
        llm_model="stub",
        llm_system_prompt="be brief",
    )
    return JarvisSessionManager(config=cfg)


def test_create_session_attaches_background_service_from_server_sessions(monkeypatch):
    """The BackgroundModelService stored in ``sessions[session_id]`` is set on the state machine."""
    from joy_interaction_webui import jarvis_mode as _jm
    from joy_interaction_webui import server

    bg = SimpleNamespace(
        enabled=True,
        _closed=False,
        handle_foreground_response=AsyncMock(),
    )
    server.sessions["sess-bg-1"] = {
        "background_service": bg,
        "vlm_service": SimpleNamespace(),
    }
    # Bypass KWS/ASR model load (test uses a fake "ignored" path).
    monkeypatch.setattr(_jm.JarvisStateMachine, "prewarm_engines", AsyncMock(return_value=None))
    monkeypatch.setattr(_jm.JarvisStateMachine, "run", AsyncMock(return_value=None))
    try:

        async def run():
            manager = _build_manager()
            session = await manager.create_session("sess-bg-1")
            return session.state_machine._background_service

        sm_bg = asyncio.run(run())
        assert sm_bg is bg, "BackgroundModelService was not propagated to JarvisStateMachine"
    finally:
        server.sessions.pop("sess-bg-1", None)


def test_create_session_without_background_service_keeps_none(monkeypatch):
    """No BackgroundModelService registered -> sm._background_service stays None (graceful)."""
    from joy_interaction_webui import jarvis_mode as _jm
    from joy_interaction_webui import server

    server.sessions.pop("sess-bg-2", None)
    monkeypatch.setattr(_jm.JarvisStateMachine, "prewarm_engines", AsyncMock(return_value=None))
    monkeypatch.setattr(_jm.JarvisStateMachine, "run", AsyncMock(return_value=None))

    async def run():
        manager = _build_manager()
        session = await manager.create_session("sess-bg-2")
        return session.state_machine._background_service

    sm_bg = asyncio.run(run())
    assert sm_bg is None


def test_llm_callback_does_not_double_route_delegation():
    """_make_llm_callback broadcasts the LLM reply only; delegation is handled in _send_to_llm."""
    from joy_interaction_webui import server

    bg = SimpleNamespace(
        enabled=True,
        _closed=False,
        handle_foreground_response=AsyncMock(),
    )
    server.sessions["sess-bg-3"] = {
        "background_service": bg,
        "vlm_service": SimpleNamespace(),
    }

    # notify_session_llm_reply is sync in server.py (send_to_session creates
    # an asyncio task internally). Make the fake sync too.
    broadcast: list = []

    def fake_notify_session_llm_reply(session_id, text, source="jarvis"):
        broadcast.append({"session_id": session_id, "text": text, "source": source})

    try:
        # Patch BOTH names: server.notify_session_llm_reply (the canonical
        # attribute) and let the cb's local import pick it up via ``from .server import``.
        with patch.object(
            server, "notify_session_llm_reply", side_effect=fake_notify_session_llm_reply
        ):
            manager = _build_manager()
            cb = manager._make_llm_callback("sess-bg-3")
            cb("Confirmed.", source="jarvis_voice")

        assert broadcast == [
            {"session_id": "sess-bg-3", "text": "Confirmed.", "source": "jarvis_voice"}
        ]
        # Crucially: the callback must NOT trigger background delegation
        # anymore — that path is owned by _send_to_llm via _background_service.
        assert not bg.handle_foreground_response.called, (
            "_make_llm_callback re-triggered delegation; double-routing risk"
        )
    finally:
        server.sessions.pop("sess-bg-3", None)
