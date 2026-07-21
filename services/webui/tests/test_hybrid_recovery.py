"""Regression test for v3.23: WAIT_ASR_CONFIRM timeout falls back to fresh-window
KWS probe (recovers wake when live KWS fired but ASR model never spells bt).

The streaming-paraformer ASR model often returns only "b" instead of "bt" for the
two-syllable wake phrase (verified empirically against positive_0002.wav and the
real flow), which makes the standard WAIT_ASR_CONFIRM pattern match fail. We
recover by running the captured PCM through a fresh-stream KWS probe before
giving up.
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

from joy_interaction_webui.jarvis_mode import JarvisState, JarvisStateMachine


class FakeKWS:
    def __init__(self, fire_count=1, fresh_probe_hit=True):
        self._live_calls = 0
        self._fresh_calls = 0
        self.fire_count = fire_count
        self.fresh_probe_hit = fresh_probe_hit
        self.capture_chunks = []

    def start(self):
        pass

    def feed_audio(self, pcm: bytes) -> bool:
        self._live_calls += 1
        # Always remember last 1.0s of PCM for diagnostics capture.
        self.capture_chunks.append(bytes(pcm))
        return self._live_calls == self.fire_count

    def detect_in_pcm(self, pcm: bytes) -> bool:
        self._fresh_calls += 1
        return self.fresh_probe_hit


class FakeASR:
    def __init__(self, partials=()):
        self.partials = list(partials)
        self._i = 0
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def feed_chunk(self, pcm: bytes) -> str:
        if self._i < len(self.partials):
            text = self.partials[self._i]
            self._i += 1
            return text
        return ""


def _build_machine(kws, asr, capture_window_s=3.0, capture_min_interval_s=60.0):
    """Construct a JarvisStateMachine with minimal real config + injected fakes."""
    from joy_interaction_webui.jarvis_mode import JarvisConfig

    cfg = JarvisConfig(
        wake_word="bt",
        kws_model_dir="ignored",
        asr_model_dir="ignored",
        sample_rate=16000,
        kws_capture_window_s=capture_window_s,
        kws_capture_min_interval_s=capture_min_interval_s,
        asr_confirm_timeout_s=0.2,  # fast for the test
        kws_fresh_window_min_s=1.0,
        kws_fresh_window_probe_enabled=True,
        kws_fresh_window_direct_wake=True,
    )
    sm = JarvisStateMachine(
        config=cfg,
        on_wake=None,
        on_goodbye=None,
        on_asr_partial=None,
        on_user_utterance=None,
        on_llm_response=None,
    )
    sm._kws = kws
    sm._asr = asr
    sm._ensure_kws_diagnostic_state()
    return sm


def test_fresh_window_recovery_promotes_wake_when_asr_fails_to_confirm():
    """Live KWS fires once, ASR returns "b" only, fresh-window probe hits -> wake."""
    kws = FakeKWS(fire_count=1, fresh_probe_hit=True)
    asr = FakeASR(partials=["b", "b", "b"])
    sm = _build_machine(kws, asr)
    pcm = b"\x00\x01" * 3200  # 0.2s of audio

    async def scenario():
        # Drive _handle_kws enough to fire live KWS
        for _ in range(3):
            await sm._handle_kws(pcm)
        assert sm.state == JarvisState.WAIT_ASR_CONFIRM, f"unexpected {sm.state}"
        # Wait for confirm timeout to fire + recovery probe to run.
        # The recovery path goes WAIT_ASR_CONFIRM -> WAKE_DETECTED -> DIALOG_ACTIVE
        # but wake.wav playback is async; accept WAKE_DETECTED as the recovery
        # end-state we care about here.
        for _ in range(40):
            await asyncio.sleep(0.05)
            if sm.state in (JarvisState.WAKE_DETECTED, JarvisState.DIALOG_ACTIVE):
                break
        return sm.state

    final = asyncio.run(scenario())
    assert final in (JarvisState.WAKE_DETECTED, JarvisState.DIALOG_ACTIVE), (
        f"expected WAKE_DETECTED/DIALOG_ACTIVE after fresh-window recovery, got {final}"
    )


def test_no_recovery_resets_to_kws_when_probe_also_misses():
    """Live KWS fires, ASR fails, fresh-window probe also misses -> back to KWS."""
    kws = FakeKWS(fire_count=1, fresh_probe_hit=False)
    asr = FakeASR(partials=["", "", ""])
    sm = _build_machine(kws, asr)
    pcm = b"\x00\x01" * 3200

    async def scenario():
        for _ in range(3):
            await sm._handle_kws(pcm)
        assert sm.state == JarvisState.WAIT_ASR_CONFIRM
        for _ in range(20):
            await asyncio.sleep(0.05)
            if sm.state == JarvisState.KWS_LISTENING:
                break
        return sm.state

    final = asyncio.run(scenario())
    assert final == JarvisState.KWS_LISTENING, (
        f"expected KWS_LISTENING after both confirms fail, got {final}"
    )
