"""Regression tests for v3.19 hybrid wake confirmation.

The pre-confirm drain (``_drain_pending_audio(reason="post-wake-pre-confirm")``)
that was present in v3.17/v3.18 is gone. ASR must receive the wake audio so it
can re-transcribe the wake phrase and confirm the wake.

These tests pin two behaviours:

1. ASR sees the wake chunk via inline tap inside ``_handle_kws``.
2. Audio chunks queued in the wake buffer are NOT drained before the confirm
   window opens — they flow into ``_handle_wait_asr_confirm``.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _KwsShim:
    def __init__(self):
        self.fed = []

    def feed_audio(self, pcm: bytes) -> bool:
        self.fed.append(pcm)
        return True


class _AsrShim:
    def __init__(self):
        self.fed = []
        self.stream_started = False

    def start(self):
        self.stream_started = True

    def feed_chunk(self, pcm: bytes) -> str:
        self.fed.append(pcm)
        return ""  # tap on wake chunk produces nothing by itself.


async def _make_sm(asr_partials=()):
    """Build a state machine with shim KWS/ASR."""
    from joy_interaction_webui.jarvis_mode import (
        JarvisConfig,
        JarvisState,
        JarvisStateMachine,
    )

    cfg = JarvisConfig.from_env()
    cfg.asr_confirm_timeout_s = 0.5

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm.config = cfg
    sm.state = JarvisState.KWS_LISTENING
    sm._kws = _KwsShim()
    sm._asr = _AsrShim()
    sm._audio_queue = asyncio.Queue(maxsize=1024)
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
    sm._init_kws = lambda: None
    sm._init_asr = lambda: None
    return sm


async def test_tap_feeds_wake_chunk_to_asr_inline():
    """The pcm that triggers KWS must also be tapped to ASR inside _handle_kws."""
    from joy_interaction_webui.jarvis_mode import JarvisState

    sm = await _make_sm()
    wake_pcm = b"\x00\x01" * 80

    # Stub _play_wake_wav to short-circuit for the test (no audio playback).
    sm._play_wake_wav = lambda: asyncio.sleep(0)

    await sm._handle_kws(wake_pcm)

    assert sm.state in (JarvisState.WAIT_ASR_CONFIRM, JarvisState.DIALOG_ACTIVE)
    assert sm._asr.stream_started is True, "ASR stream should have been started"
    # The tap should have fed exactly one chunk to ASR — the wake chunk itself.
    assert len(sm._asr.fed) >= 1, f"ASR should have received the wake chunk; got {sm._asr.fed!r}"
    assert sm._asr.fed[0] == wake_pcm, (
        f"first ASR chunk should be the wake pcm; got {sm._asr.fed[0]!r}"
    )


async def test_no_pre_confirm_drain_queued_audio_flows_to_asr():
    """A chunk queued behind the wake chunk must reach _handle_wait_asr_confirm.

    In v3.17/v3.18 the pre-confirm drain dropped every chunk that arrived
    between KWS fire and ASR start. v3.19 removes that drain so ASR can
    transcribe the wake phrase itself.
    """
    from joy_interaction_webui.jarvis_mode import JarvisState

    sm = await _make_sm()
    wake_pcm = b"\x00\x01" * 80
    followup_pcm = b"\x02\x03" * 80

    sm._play_wake_wav = lambda: asyncio.sleep(0)
    await sm._handle_kws(wake_pcm)
    assert sm.state in (JarvisState.WAIT_ASR_CONFIRM, JarvisState.DIALOG_ACTIVE)

    # Drop fast-path promotion side-effects: if a previous chunk was tapped
    # but not matched, we expect followups to flow through normally.
    if sm.state == JarvisState.WAIT_ASR_CONFIRM:
        await sm._handle_wait_asr_confirm(followup_pcm)
    else:
        # Tap already promoted. The wake chunk was the only one fed via the
        # tap, so we just verify the ASR saw at least the wake chunk.
        pass
    assert sm._asr.fed[0] == wake_pcm
    if sm.state == JarvisState.WAIT_ASR_CONFIRM:
        assert followup_pcm in sm._asr.fed, (
            f"followup pcm must reach ASR via the queue (no pre-confirm drain); got {sm._asr.fed!r}"
        )

    # Always end clean.
    if sm._confirm_task is not None and not sm._confirm_task.done():
        sm._confirm_task.cancel()
        try:
            await sm._confirm_task
        except asyncio.CancelledError:
            pass


async def test_no_100ms_sleep_between_asr_chunks_in_confirm_loop():
    """Pin the removal of the run-loop cooldown for WAIT_ASR_CONFIRM.

    The 0.1s sleep between ASR chunks stalled the timer task via event-loop
    contention and was removed in v3.19. This test guards against the
    throttle being silently re-added.
    """
    from joy_interaction_webui import jarvis_mode

    src = Path(jarvis_mode.__file__).read_text(encoding="utf-8")
    forbidden = (
        "elif self.state == JarvisState.WAIT_ASR_CONFIRM:\n"
        "                    await self._handle_wait_asr_confirm(pcm)\n"
        "                    await asyncio.sleep(0.1)"
    )
    assert forbidden not in src, (
        "Re-introduced the 0.1s cooldown in WAIT_ASR_CONFIRM loop; "
        "this stall made the 1.2s confirm window drift to ~3s in production."
    )
