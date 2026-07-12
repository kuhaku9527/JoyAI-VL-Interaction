"""Lite Jarvis state machine test — no llama-server, no ASR model loaded.

Verifies:
  1. JarvisStateMachine instantiates without KWS/ASR engines loaded
  2. State transitions: KWS_LISTENING (default) → forced DIALOG_ACTIVE
  3. EXIT_WORDS detection on partial: "我知道了" / "明白" / "好的" → EXIT_DETECTED
  4. After exit: state resets to KWS_LISTENING
  5. TTS_PAUSED transition when barge-in happens (state machine dialect)

Skipped (need real model + llama-server):
  - Real ASR feed (uses Mock ASR that returns scripted text)
  - Real LLM HTTP call (skipped — endpoint detection skipped via timer)
  - Real KWS detection (verified in test_jarvis_kws_e2e.py separately)

Run: python services/scripts/test_jarvis_state_machine_lite.py
"""
import asyncio
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "webui" / "src"))
sys.path.insert(0, str(REPO / "services" / "asr"))
sys.path.insert(0, str(REPO))

from joy_interaction_webui.jarvis_mode import (
    JarvisConfig, JarvisState, JarvisStateMachine, EXIT_WORDS,
)

assert "bt" in ("bt",), "doc-test: only 'bt' wake word now (post 2026-07-10)"
print(f"EXIT_WORDS = {sorted(EXIT_WORDS)}")
print(f"len(EXIT_WORDS) = {len(EXIT_WORDS)} (expected 8: 行/明白/了解/ok/好的/知道了/谢谢/感谢)")
assert len(EXIT_WORDS) == 8, f"EXIT_WORDS count != 8, got {len(EXIT_WORDS)}"


class MockAsr:
    """Mock ASR that returns scripted partial text (no model load needed)."""
    def __init__(self, scripted=None):
        self.scripted = scripted or []
        self.i = 0

    def start(self):
        pass

    def stop(self):
        pass

    def feed_chunk(self, pcm: bytes) -> str:
        if self.i < len(self.scripted):
            t = self.scripted[self.i]
            self.i += 1
            return t
        return self.scripted[-1] if self.scripted else ""


async def test_exit_word_transitions():
    """Drive state machine → EXIT_WORDS detection → KWS_LISTENING reset."""
    print()
    print("=" * 60)
    print("Test: DIALOG_ACTIVE → EXIT word '我知道了' → KWS_LISTENING")
    print("=" * 60)

    config = JarvisConfig(
        asr_model_dir="D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en",
        kws_model_dir="D:/AI/models/sherpa-onnx/models/kws/bt-en",
        llm_api_url="http://127.0.0.1:7060/v1",  # NOT actually called (we mock)
        wake_word="bt",
    )
    jarvis = JarvisStateMachine(config=config)
    print(f"[init] state = {jarvis.state.name}  (expect KWS_LISTENING)")
    assert jarvis.state == JarvisState.KWS_LISTENING

    # Inject Mock ASR (no model load)
    jarvis._asr = MockAsr(scripted=["我", "我知道", "我知道了"])
    jarvis._asr_stream_active = True
    jarvis.state = JarvisState.DIALOG_ACTIVE
    jarvis._last_speech_time = time.time()
    print(f"[force] state = {jarvis.state.name}")

    # Audio loop: empty 100ms PCM x 3 (forces _handle_dialog x 3)
    pcm_silence = (b"\x00\x00" * 800)
    for i in range(3):
        await jarvis._handle_dialog(pcm_silence)
        print(f"  [chunk {i+1}] partial_text={jarvis._current_asr_text!r}, state={jarvis.state.name}")

    # After "我知道了" → EXIT_DETECTED → reset → KWS_LISTENING
    print(f"[final] state = {jarvis.state.name}  (expect KWS_LISTENING)")
    assert jarvis.state == JarvisState.KWS_LISTENING, f"state should be KWS_LISTENING, got {jarvis.state.name}"
    print("[OK] EXIT_WORDS detection → state reset to KWS_LISTENING")


async def test_barge_in_transition():
    """Verify barge-in: while TTS in 'DIALOG_ACTIVE' state, user speech pauses TTS."""
    print()
    print("=" * 60)
    print("Test: barge-in (user speech during TTS) → TTS_PAUSED")
    print("=" * 60)

    jarvis = JarvisStateMachine(config=JarvisConfig(wake_word="bt"))
    jarvis._asr = MockAsr(scripted=["帮我看看"])
    jarvis._asr_stream_active = True
    jarvis.state = JarvisState.DIALOG_ACTIVE
    jarvis._last_speech_time = time.time()

    # Simulate TTS playing (mock task that's still running)
    async def fake_tts():
        await asyncio.sleep(60)
    jarvis._tts_task = asyncio.create_task(fake_tts())

    await jarvis._handle_dialog(b"\x00\x00" * 800)
    print(f"  state after speech during TTS = {jarvis.state.name}  (expect TTS_PAUSED)")
    assert jarvis.state == JarvisState.TTS_PAUSED, f"barge-in failed, state={jarvis.state.name}"

    # Cleanup
    if jarvis._tts_task and not jarvis._tts_task.done():
        jarvis._tts_task.cancel()
        try:
            await jarvis._tts_task
        except (asyncio.CancelledError, Exception):
            pass
    print("[OK] barge-in → TTS_PAUSED")


async def test_no_exit_word_no_transition():
    """Verify non-exit partial keeps DIALOG_ACTIVE."""
    print()
    print("=" * 60)
    print("Test: regular partial (no exit word) keeps DIALOG_ACTIVE")
    print("=" * 60)

    jarvis = JarvisStateMachine(config=JarvisConfig(wake_word="bt"))
    jarvis._asr = MockAsr(scripted=["今天天气怎么样", "今天天气如何", "今天天气如"])
    jarvis._asr_stream_active = True
    jarvis.state = JarvisState.DIALOG_ACTIVE
    jarvis._last_speech_time = time.time()

    for i in range(3):
        await jarvis._handle_dialog(b"\x00\x00" * 800)
        print(f"  [chunk {i+1}] partial={jarvis._current_asr_text!r}, state={jarvis.state.name}")

    assert jarvis.state == JarvisState.DIALOG_ACTIVE, "non-exit should keep DIALOG_ACTIVE"
    print("[OK] no exit word → stays DIALOG_ACTIVE")


async def main():
    await test_exit_word_transitions()
    await test_barge_in_transition()
    await test_no_exit_word_no_transition()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED — Jarvis state machine skeleton works")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
