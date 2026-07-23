"""Regression: JarvisSession.start() must prewarm KWS+ASR.

If we skip the prewarm, the first KWS wake fires against a cold ASR
whose ~1.2s model load is consumed by the same-length confirm window
— every wake is rejected as a false alarm. Pin the behaviour here so
nothing can quietly drop the prewarm without a failing test.
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


async def test_session_start_prewarms_kws_and_asr():
    """start() must leave both engines ready before returning."""
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisState, JarvisStateMachine
    from joy_interaction_webui.jarvis_session import JarvisSession

    cfg = JarvisConfig.from_env()
    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm.config = cfg
    sm.state = JarvisState.KWS_LISTENING
    sm._kws = None
    sm._asr = None

    def fake_init_kws():
        if sm._kws is not None:
            return
        sm._kws = object()  # sentinel

    def fake_init_asr():
        if sm._asr is not None:
            return
        sm._asr = object()

    sm._init_kws = fake_init_kws  # type: ignore[assignment]
    sm._init_asr = fake_init_asr  # type: ignore[assignment]

    async def fake_run():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    sm.run = fake_run  # type: ignore[assignment]

    session = JarvisSession(session_id="test-prewarm", state_machine=sm)
    await session.start()

    try:
        assert sm._kws is not None, "KWS must be initialised by prewarm"
        assert sm._asr is not None, "ASR must be initialised by prewarm"
    finally:
        await session.stop()


async def test_prewarm_idempotent_on_second_start_attempt():
    """A no-op second prewarm must not reload the models."""
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisState, JarvisStateMachine

    cfg = JarvisConfig.from_env()
    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm.config = cfg
    sm.state = JarvisState.KWS_LISTENING
    sm._kws = None
    sm._asr = None

    init_calls = {"kws": 0, "asr": 0}

    def fake_init_kws():
        if sm._kws is not None:
            return
        init_calls["kws"] += 1
        sm._kws = object()

    def fake_init_asr():
        if sm._asr is not None:
            return
        init_calls["asr"] += 1
        sm._asr = object()

    sm._init_kws = fake_init_kws  # type: ignore[assignment]
    sm._init_asr = fake_init_asr  # type: ignore[assignment]

    await sm.prewarm_engines()
    assert init_calls["kws"] == 1
    assert init_calls["asr"] == 1

    await sm.prewarm_engines()
    assert init_calls["kws"] == 1, "second prewarm should not reload KWS"
    assert init_calls["asr"] == 1, "second prewarm should not reload ASR"


async def test_kws_confirm_window_no_longer_eaten_by_asr_init():
    """Regression: ASR must accept a chunk inside the confirm window.

    Before the prewarm fix, the first KWS wake triggered a 1.2s ASR
    model load inside the 1.2s confirm window, so ``feed_chunk`` was
    never reached. With prewarm, ASR is ready and a feed_chunk call
    inside the window succeeds.
    """
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisState, JarvisStateMachine

    cfg = JarvisConfig.from_env()
    cfg.asr_confirm_timeout_s = 0.2

    class _KwsShim:
        def feed_audio(self, _pcm):
            return True

    class _AsrShim:
        def __init__(self):
            self.feed_calls = 0
            self.start_called = False
            self.stop_called = False

        def start(self):
            self.start_called = True

        def stop(self):
            self.stop_called = True

        def feed_chunk(self, _pcm):
            self.feed_calls += 1
            return ""

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

    sm._init_kws = lambda: None  # type: ignore[assignment]
    sm._init_asr = lambda: None  # type: ignore[assignment]

    await sm._handle_kws(b"\x00\x00" * 80)
    assert sm.state == JarvisState.WAIT_ASR_CONFIRM, f"expected WAIT_ASR_CONFIRM, got {sm.state}"

    await sm._handle_wait_asr_confirm(b"\x00\x00" * 80)
    assert sm._asr.feed_calls >= 1, (
        "ASR should have processed at least one chunk in the confirm window"
    )

    if sm._confirm_task is not None and not sm._confirm_task.done():
        sm._confirm_task.cancel()
        try:
            await sm._confirm_task
        except asyncio.CancelledError:
            pass
