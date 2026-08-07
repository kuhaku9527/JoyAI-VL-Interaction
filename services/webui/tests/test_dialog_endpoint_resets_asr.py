"""Regression test for bug #3: ASR mojibake loop.

After ``_send_to_llm`` fires on a stale partial, the underlying
``self._asr`` stream still holds the same text. On the next mic chunk
the ASR returns the identical stale text, which then trips the 2-second
endpoint timer again, and again, and again — looping the same junk
text into the LLM and the browser dialog.

Fix contract:
  * After endpoint send, ``_asr.start()`` resets the streaming session.
  * Pure-noise / single-character / punctuation-only text is dropped.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _RecordingASR:
    """ASR fake that records start() calls and returns the same stale text."""

    def __init__(self, stale_text: str):
        self.stale_text = stale_text
        self.start_count = 0

    def start(self):
        self.start_count += 1

    def stop(self):
        pass

    def feed_chunk(self, pcm: bytes) -> str:
        # Simulate Paraformer holding the last partial on silence.
        return self.stale_text


class _RejectingLLM:
    """Stub for the LLM HTTP call: just record what was sent."""

    def __init__(self):
        self.calls = []

    async def __call__(self, sm, text):
        self.calls.append(text)


async def _make_sm(asr: _RecordingASR, llm_capture: list):
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisState, JarvisStateMachine

    cfg = JarvisConfig.from_env()

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm.config = cfg
    sm.state = JarvisState.DIALOG_ACTIVE
    sm._asr = asr
    sm._asr_stream_active = True
    sm._current_asr_text = ""
    sm._last_speech_time = 0.0
    sm._tts_task = None
    sm._audio_queue = asyncio.Queue(maxsize=4)
    sm.on_user_utterance = lambda t: llm_capture.append(("pilot", t))
    sm.on_asr_partial = None
    sm.on_llm_response = None
    sm.on_wake = None
    sm.on_goodbye = None
    sm.audio_output = None
    sm._tts_done = asyncio.Event()
    sm._tts_done.set()

    # Stub _send_to_llm to capture text without making HTTP calls.
    # Signature mirrors JarvisStateMachine._send_to_llm (jarvis_mode.py),
    # which gained the `interaction_mode` kwarg in the Smart Turn feature.
    async def fake_send(text, *, stream_tts=True, interaction_mode="jarvis"):
        llm_capture.append(("llm", text))

    sm._send_to_llm = fake_send
    sm._play_goodbye_wav = lambda: asyncio.sleep(0)
    sm._transition_to = lambda *a, **k: asyncio.sleep(0)
    sm._pause_tts = lambda: asyncio.sleep(0)
    return sm


def test_dialog_endpoint_resets_asr_stream():
    """Each endpoint must call _asr.start() to clear the stale partial."""
    asr = _RecordingASR(stale_text="上一轮识别")
    capture = []
    sm = asyncio.run(_make_sm(asr, capture))

    sm._current_asr_text = "上一轮识别"
    sm._last_speech_time = time.time() - 5.0  # well past 2s window

    asyncio.run(sm._handle_dialog(b"\x00\x00" * 80))

    assert asr.start_count >= 1, (
        f"ASR stream must be reset after endpoint; start_count={asr.start_count}"
    )
    assert sm._current_asr_text == "", "current_asr_text must be cleared after send"


def test_dialog_endpoint_drops_garbage_text():
    """Single-char / mojibake / punctuation-only text must NOT be sent to LLM."""
    cases = [
        "��",  # mojibake (replacement char)
        "嗯",  # filler only
        ".",  # punctuation
        "?",  # punctuation
        " ",  # whitespace
    ]
    for stale in cases:
        asr = _RecordingASR(stale_text=stale)
        capture = []
        sm = asyncio.run(_make_sm(asr, capture))

        sm._current_asr_text = stale
        sm._last_speech_time = time.time() - 5.0

        asyncio.run(sm._handle_dialog(b"\x00\x00" * 80))

        llm_sent = [c for c in capture if c[0] == "llm"]
        assert llm_sent == [], f"garbage text {stale!r} must not reach LLM; got {llm_sent}"


def test_dialog_endpoint_sends_real_utterance():
    """Multi-char Chinese / English with letters must reach the LLM once."""
    asr = _RecordingASR(stale_text="BT 在吗")
    capture = []
    sm = asyncio.run(_make_sm(asr, capture))

    sm._current_asr_text = "BT 在吗"
    sm._last_speech_time = time.time() - 5.0

    asyncio.run(sm._handle_dialog(b"\x00\x00" * 80))

    llm_sent = [c for c in capture if c[0] == "llm"]
    assert len(llm_sent) == 1, f"expected exactly 1 LLM call, got {len(llm_sent)}"
    assert llm_sent[0][1] == "BT 在吗"
    # And ASR was reset so the next chunk won't loop the same text
    assert asr.start_count >= 1
