"""Regression tests for KWS miss observability.

The production wake contract remains KWS-first.  The diagnostic ASR shadow is
there to explain misses and collect retraining samples; it must not promote a
wake by itself.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import wave
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _NoHitKws:
    def __init__(self, *, rolling_hit: bool = False):
        self.fed = []
        self.rolling_hit = rolling_hit
        self.probed = []

    def feed_audio(self, pcm: bytes) -> bool:
        self.fed.append(pcm)
        return False

    def detect_in_pcm(self, pcm: bytes) -> bool:
        self.probed.append(pcm)
        return self.rolling_hit

    def start(self):
        pass


class _ShadowAsr:
    def __init__(self, text: str = "bt"):
        self.text = text
        self.fed = []
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def feed_chunk(self, pcm: bytes) -> str:
        self.fed.append(pcm)
        return self.text

    def stop(self):
        self.stopped += 1


def _loud_pcm(samples: int = 1600) -> bytes:
    # 10000 / 32768 ~= 0.305 peak: definitely speech-like for diagnostics.
    return (10000).to_bytes(2, byteorder="little", signed=True) * samples


async def test_kws_miss_logs_shadow_asr_but_does_not_wake(tmp_path, caplog):
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisState, JarvisStateMachine

    cfg = JarvisConfig(
        kws_capture_dir=str(tmp_path),
        kws_capture_min_interval_s=0.0,
        kws_capture_peak_threshold=0.001,
    )
    sm = JarvisStateMachine(config=cfg)
    sm._kws = _NoHitKws()
    sm._asr = _ShadowAsr("bt")
    sm._init_kws = lambda: None
    sm._init_asr = lambda: None

    with caplog.at_level(logging.INFO):
        await sm._handle_kws(_loud_pcm())

    assert sm.state == JarvisState.KWS_LISTENING
    assert sm._kws.fed, "KWS still owns the wake decision"
    assert sm._asr.fed, "shadow ASR should receive speech-like KWS misses"
    assert any("KWS MISS: shadow ASR saw wake pattern" in rec.message for rec in caplog.records)
    assert not any("ASR confirmed wake" in rec.message for rec in caplog.records)


async def test_kws_diagnostic_capture_writes_real_pcm_window(tmp_path):
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisStateMachine

    cfg = JarvisConfig(
        kws_shadow_asr_enabled=False,
        kws_capture_dir=str(tmp_path),
        kws_capture_window_s=0.2,
        kws_capture_min_interval_s=0.0,
        kws_capture_peak_threshold=0.001,
    )
    sm = JarvisStateMachine(config=cfg)
    sm._kws = _NoHitKws()
    sm._init_kws = lambda: None

    await sm._handle_kws(_loud_pcm())

    captures = list(tmp_path.glob("kws_live_*.wav"))
    assert len(captures) == 1
    with wave.open(str(captures[0]), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() > 0


async def test_rolling_kws_probe_can_wake_when_live_stream_misses(tmp_path):
    """A fresh rolling-window probe catches stream-boundary misses.

    This pins the live failure observed on 2026-07-12: a saved 3s capture
    woke KWS offline, but the long-running live KWS stream did not fire.
    """
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisState, JarvisStateMachine

    cfg = JarvisConfig(
        kws_shadow_asr_enabled=False,
        kws_capture_dir=str(tmp_path),
        kws_capture_min_interval_s=999.0,
        kws_fresh_window_probe_enabled=True,
        kws_fresh_window_probe_interval_s=0.0,
        kws_fresh_window_min_s=0.01,
        kws_fresh_window_direct_wake=True,
    )
    sm = JarvisStateMachine(config=cfg)
    sm._kws = _NoHitKws(rolling_hit=True)
    sm._asr = _ShadowAsr("")
    sm._init_kws = lambda: None
    sm._init_asr = lambda: None
    sm._play_wake_wav = lambda: asyncio.sleep(0)

    await sm._handle_kws(_loud_pcm())

    assert sm._kws.fed, "live stream KWS was tried first"
    assert sm._kws.probed, "fresh rolling-window KWS probe should run on stream miss"
    assert sm.state == JarvisState.DIALOG_ACTIVE
    assert sm._asr.started >= 1
