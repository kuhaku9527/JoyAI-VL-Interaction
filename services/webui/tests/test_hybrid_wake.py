"""Tests for hybrid KWS->ASR wake confirmation (v3.17)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class FakeKWS:
    def __init__(self, fires_on_call: int = 1):
        self.calls = 0
        self.fires_on_call = fires_on_call

    def start(self):
        pass

    def feed_audio(self, pcm: bytes) -> bool:
        self.calls += 1
        return self.calls == self.fires_on_call


class FakeASR:
    def __init__(self, partials, finals=()):
        self.partials = list(partials)
        self.finals = list(finals)
        self.started = False
        self.stopped = False
        self.chunks = 0
        self._i = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def feed_chunk(self, pcm: bytes) -> str:
        self.chunks += 1
        # cycle through partials, then finals once partials exhausted
        if self._i < len(self.partials):
            text = self.partials[self._i]
            self._i += 1
            return text
        if self.finals:
            return self.finals[-1]
        return ""


async def _make_sm(timeout_s: float = 0.2, kws_fires_on: int = 1, asr_partials=(), asr_finals=()):
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisStateMachine, JarvisState

    cfg = JarvisConfig.from_env()
    # Override hybrid knobs for the test
    cfg.asr_confirm_timeout_s = timeout_s
    cfg.asr_confirm_patterns = ["bt", "BT", "B T", "b t"]

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm.config = cfg
    sm.state = JarvisState.KWS_LISTENING
    sm._audio_queue = asyncio.Queue(maxsize=1024)
    sm._kws = FakeKWS(fires_on_call=kws_fires_on)
    sm._asr = FakeASR(asr_partials, finals=asr_finals)
    sm._asr_stream_active = False
    sm._current_asr_text = ""
    sm._last_speech_time = 0.0
    sm._tts_task = None
    sm._consume_task = None
    sm._tts_done = asyncio.Event()
    sm._tts_done.set()
    sm._confirm_task = None
    sm._last_asr_match = ""
    sm.audio_output = None
    sm.on_wake = None
    sm.on_asr_partial = None
    sm.on_user_utterance = None
    sm.on_llm_response = None
    sm.on_goodbye = None
    return sm


async def test_kws_fire_enters_wait_asr_confirm():
    from joy_interaction_webui.jarvis_mode import JarvisState

    sm = await _make_sm(timeout_s=0.3, kws_fires_on=1)
    await sm._handle_kws(b"\x00\x00" * 80)
    assert sm.state == JarvisState.WAIT_ASR_CONFIRM, f"expected WAIT_ASR_CONFIRM, got {sm.state}"
    assert sm._confirm_task is not None, "timeout task should be scheduled"
    assert sm._asr.started, "ASR should have started"
    sm._confirm_task.cancel()
    try:
        await sm._confirm_task
    except asyncio.CancelledError:
        pass


async def test_asr_match_promotes_to_dialog_active():
    from joy_interaction_webui.jarvis_mode import JarvisState

    sm = await _make_sm(
        timeout_s=0.5,
        kws_fires_on=1,
        asr_partials=["bt"],
    )
    # Stub _play_wake_wav to skip 4.6s playback for the test
    sm._play_wake_wav = lambda: asyncio.sleep(0)
    await sm._handle_kws(b"\x00\x00" * 80)
    # v3.19 fast-path: tap may already have promoted; allow either state.
    assert sm.state in (JarvisState.WAIT_ASR_CONFIRM, JarvisState.DIALOG_ACTIVE), (
        f"expected WAIT_ASR_CONFIRM or DIALOG_ACTIVE after tap, got {sm.state}"
    )
    if sm.state == JarvisState.WAIT_ASR_CONFIRM:
        # No tap match; let the queue path drive promotion.
        await sm._handle_wait_asr_confirm(b"\x00\x00" * 80)
        await asyncio.sleep(0.05)
    assert sm.state == JarvisState.DIALOG_ACTIVE, f"expected DIALOG_ACTIVE, got {sm.state}"
    assert sm._last_asr_match == "bt", f"expected match='bt', got {sm._last_asr_match!r}"


async def test_asr_no_match_timeout_returns_to_kws():
    from joy_interaction_webui.jarvis_mode import JarvisState

    sm = await _make_sm(
        timeout_s=0.1,
        kws_fires_on=1,
        asr_partials=["hello world"],
    )
    sm._play_wake_wav = lambda: asyncio.sleep(0)
    await sm._handle_kws(b"\x00\x00" * 80)
    assert sm.state == JarvisState.WAIT_ASR_CONFIRM
    # Feed one chunk that returns "hello world" (no bt)
    await sm._handle_wait_asr_confirm(b"\x00\x00" * 80)
    # Wait for the timeout to fire and reset
    await asyncio.sleep(0.25)
    assert sm.state == JarvisState.KWS_LISTENING, f"expected KWS_LISTENING after timeout, got {sm.state}"
    assert sm._asr_stream_active is False, "ASR should be stopped after rejection"


def test_asr_confirm_match_helper():
    from joy_interaction_webui.jarvis_mode import JarvisStateMachine

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    # Cases that should match
    for text in ["bt", "BT", "B T", "b t", "hey bt", "okay BT-7274", "  bt  "]:
        assert JarvisStateMachine._asr_confirm_match(sm, text) is True, f"should match: {text!r}"
    # Cases that should NOT match
    for text in ["", "hello world", "bet", "bot", "but", "battery"]:
        assert JarvisStateMachine._asr_confirm_match(sm, text) is False, f"should NOT match: {text!r}"
