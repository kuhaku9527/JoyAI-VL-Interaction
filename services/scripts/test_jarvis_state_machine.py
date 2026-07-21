"""State machine end-to-end test (skip KWS).

Manually drive JarvisStateMachine:
1. Force state = DIALOG_ACTIVE
2. Feed real ASR wav (chinese question)
3. Verify LLM gets called (real llama-server 7060) and returns chinese reply
4. Inject exit word "明白"
5. Verify state transitions to KWS_LISTENING

Run: python services/scripts/test_jarvis_state_machine.py
"""
import asyncio
import logging
import sys
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "webui" / "src"))
sys.path.insert(0, str(REPO / "services" / "asr"))
sys.path.insert(0, str(REPO))  # for services.asr.jarvis.asr import

from joy_interaction_webui.jarvis_mode import (
    JarvisConfig,
    JarvisState,
    JarvisStateMachine,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test")


# Real llama-server (started in last session)
LLM_URL = "http://127.0.0.1:7060/v1"


async def test_state_machine_basic():
    """Drive state machine with real ASR wav + real LLM endpoint."""
    print("=" * 60)
    print("Test: state machine end-to-end (skip KWS, use real LLM)")
    print("=" * 60)

    config = JarvisConfig(
        asr_model_dir="D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en",
        kws_model_dir="D:/AI/models/sherpa-onnx/models/kws/zh-en-3M",
        llm_api_url=LLM_URL,
        llm_model="joyai-vl-interaction-preview-iq4_nl-imat.gguf",
        llm_system_prompt="你是铁御，钢铁侠的AI助手，简洁回答。",
    )
    jarvis = JarvisStateMachine(config=config)

    state_log = []
    def on_wake():
        state_log.append(("wake", jarvis.state))
    def on_goodbye():
        state_log.append(("goodbye", jarvis.state))
    jarvis.on_wake = on_wake
    jarvis.on_goodbye = on_goodbye

    llm_responses = []
    def on_llm(resp):
        llm_responses.append(resp)
    jarvis.on_llm_response = on_llm

    async def audio_out(pcm, sr):
        logger.info("audio_output: %d bytes @ %dHz", len(pcm), sr)
    jarvis.audio_output = audio_out

    bg = asyncio.create_task(jarvis.run())
    await asyncio.sleep(0.5)

    jarvis._init_asr()
    jarvis._asr.start()
    jarvis._asr_stream_active = True
    jarvis.state = JarvisState.DIALOG_ACTIVE
    jarvis._last_speech_time = time.time()
    print(f"[init] state forced to: {jarvis.state.name}")
    # Step 1: Feed ASR wav DIRECTLY to _handle_dialog (bypass queue)
    test_wav = "D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en/test_wavs/1.wav"
    print(f"[step 1] feeding {test_wav} via _handle_dialog")
    with wave.open(test_wav, "rb") as wf:
        chunk = 1600
        while True:
            data = wf.readframes(chunk // 2)
            if not data: break
            await jarvis._handle_dialog(data)
    print(f"[step 1] ASR partial: {jarvis._current_asr_text[:80]!r}")

    # Force endpoint trigger (simulate 2s of silence after speech)
    jarvis._last_speech_time = time.time() - 3.0
    await jarvis._handle_dialog(b"\x00\x00" * 800)  # triggers endpoint → LLM
    await asyncio.sleep(3.0)  # let LLM HTTP call complete
    print(f"[step 1] LLM responses so far: {len(llm_responses)} items")
    for r in llm_responses:
        print(f"  - {r[:150]!r}")
    assert len(llm_responses) >= 1, "LLM should have been called"
    print(f"[step 1] state after LLM: {jarvis.state.name}")

    # Step 2: Mock ASR.feed_chunk to return exit word (simulate ASR producing it)
    print("[step 2] mocking ASR to return exit word")
    original_feed = jarvis._asr.feed_chunk
    jarvis._asr.feed_chunk = lambda pcm: "知道了"
    try:
        jarvis._current_asr_text = ""
        jarvis._last_speech_time = time.time() - 3.0
        await jarvis._handle_dialog(b"\x00\x00" * 800)
    finally:
        jarvis._asr.feed_chunk = original_feed
    print(f"[step 2] state after exit: {jarvis.state.name}")
    assert jarvis.state == JarvisState.KWS_LISTENING, f"state should be KWS_LISTENING, got {jarvis.state}"
    print("[step 2] PASS — state back to KWS_LISTENING")
    print(f"[step 2] state_log: {state_log}")

    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass
    print(f"\nState log: {state_log}")
    print(f"LLM responses ({len(llm_responses)}):")
    for r in llm_responses:
        print(f"  - {r[:200] if isinstance(r, str) else r}")


if __name__ == "__main__":
    asyncio.run(test_state_machine_basic())




