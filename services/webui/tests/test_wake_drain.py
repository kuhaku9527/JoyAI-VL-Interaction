"""Tests for wake audio-queue drain."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_drain_pending_audio_empties_queue():
    from joy_interaction_webui.jarvis_mode import JarvisStateMachine

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm._audio_queue = asyncio.Queue(maxsize=1024)
    for i in range(7):
        sm._audio_queue.put_nowait(b"\x00\x01" * 80)
    assert sm._audio_queue.qsize() == 7
    dropped = asyncio.run(sm._drain_pending_audio(reason="test"))
    assert dropped == 7
    assert sm._audio_queue.empty() is True


def test_drain_pending_audio_is_idle_safe():
    from joy_interaction_webui.jarvis_mode import JarvisStateMachine

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm._audio_queue = asyncio.Queue(maxsize=1024)
    dropped = asyncio.run(sm._drain_pending_audio(reason="empty"))
    assert dropped == 0
