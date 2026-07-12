"""Regression test for bug #1: wake.wav (stereo 48kHz) plays garbled.

Root cause: ``_play_event_wav`` treated WAV frames as mono, even when the
file has 2 channels. The downstream ``SpeakerAudioTrack._resample_pcm16``
then interprets interleaved L/R samples as consecutive mono samples, which
produces pitch-shifted garbled audio and the wrong duration.

Fix contract:
  * Downmix multi-channel PCM to mono before pushing to audio_output.
  * Use ``nframes / sample_rate`` for duration, not
    ``len(pcm) / (sample_rate * 2)``.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _write_stereo_wav(path: Path, sample_rate: int = 48000, duration_s: float = 0.05) -> None:
    """Synthesize a stereo 48kHz WAV with distinct L/R sine tones for verification."""
    n = int(sample_rate * duration_s)
    t = np.arange(n) / sample_rate
    left = (np.sin(2 * np.pi * 440.0 * t) * 16000).astype(np.int16)
    right = (np.sin(2 * np.pi * 660.0 * t) * 16000).astype(np.int16)
    interleaved = np.empty(n * 2, dtype=np.int16)
    interleaved[0::2] = left
    interleaved[1::2] = right
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(interleaved.tobytes())


def test_play_event_wav_downmixes_stereo_to_mono():
    """Stereo input must become mono PCM at the file's native sample rate."""
    from joy_interaction_webui.jarvis_mode import JarvisStateMachine

    sm = JarvisStateMachine.__new__(JarvisStateMachine)

    captured = {}

    async def fake_audio_output(pcm: bytes, sample_rate: int):
        captured["pcm"] = pcm
        captured["sample_rate"] = sample_rate

    sm.audio_output = fake_audio_output

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "stereo_event.wav"
        _write_stereo_wav(wav_path, sample_rate=48000, duration_s=0.05)
        sm.config = type("Cfg", (), {"events_dir": str(tmp)})()

        asyncio.run(sm._play_event_wav("stereo_event.wav"))

    pcm = captured.get("pcm")
    sr = captured.get("sample_rate")
    assert pcm is not None, "audio_output was never called"
    assert sr == 48000, f"expected 48000Hz, got {sr}"

    samples = np.frombuffer(pcm, dtype=np.int16)
    # Mono downmix: sample count equals number of frames (not frames * channels)
    expected_frames = int(48000 * 0.05)
    assert samples.size == expected_frames, (
        f"mono downmix should yield {expected_frames} samples, got {samples.size}"
    )

    # Mean of L+R sines is non-trivial (energy present)
    assert np.abs(samples.astype(np.int32)).sum() > 0, "downmixed signal is silent"


def test_play_event_wav_reports_correct_duration_for_stereo():
    """Duration log should reflect real wall-clock length, not double-count stereo."""
    from joy_interaction_webui.jarvis_mode import JarvisStateMachine
    import logging

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    sm.audio_output = None  # take the silent-fallback path

    duration_holder = {}

    async def fake_sleep(s):
        duration_holder["s"] = s

    # Patch asyncio.sleep inside the function scope is hard; instead inject
    # via the captured log line: read INFO log.
    logger = logging.getLogger("joyai.jarvis")
    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = CaptureHandler(level=logging.INFO)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "stereo.wav"
            _write_stereo_wav(wav_path, sample_rate=48000, duration_s=1.0)
            sm.config = type("Cfg", (), {"events_dir": str(tmp)})()
            asyncio.run(sm._play_event_wav("stereo.wav"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)

    play_lines = [m for m in records if "Playing event" in m]
    assert play_lines, f"no Playing event log line. records: {records}"
    # Expect "Playing event: stereo.wav (1.0s, 48000Hz, ...)"
    msg = play_lines[-1]
    assert "(1.0s," in msg, f"duration should be 1.0s for 1.0s stereo file, got: {msg}"
    assert "48000Hz" in msg


def test_play_event_wav_mono_unchanged():
    """Mono input must pass through unchanged (no spurious downmix)."""
    from joy_interaction_webui.jarvis_mode import JarvisStateMachine

    sm = JarvisStateMachine.__new__(JarvisStateMachine)
    captured = {}

    async def fake_audio_output(pcm: bytes, sample_rate: int):
        captured["pcm"] = pcm
        captured["sample_rate"] = sample_rate

    sm.audio_output = fake_audio_output

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "mono.wav"
        n = 800  # 50ms @ 16kHz mono
        samples = (np.arange(n) % 1000).astype(np.int16)
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(samples.tobytes())
        sm.config = type("Cfg", (), {"events_dir": str(tmp)})()
        asyncio.run(sm._play_event_wav("mono.wav"))

    assert captured["sample_rate"] == 16000
    assert np.array_equal(
        np.frombuffer(captured["pcm"], dtype=np.int16), samples
    ), "mono file bytes must be unchanged"