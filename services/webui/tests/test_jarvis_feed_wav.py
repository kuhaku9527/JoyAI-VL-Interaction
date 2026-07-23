"""Tests for injecting a known wake wav into a Jarvis session."""

from __future__ import annotations

import asyncio
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _write_wav(path: Path, frames: bytes, sample_rate: int = 16000):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def test_feed_wav_to_session_feeds_pcm_chunks(tmp_path):
    from joy_interaction_webui.jarvis_routes import feed_wav_to_session

    frames = b"\x01\x00" * 1600  # 100ms at 16kHz int16
    wav_path = tmp_path / "bt.wav"
    _write_wav(wav_path, frames)

    class FakeSession:
        def __init__(self):
            self.chunks = []

        async def feed_audio(self, pcm):
            self.chunks.append(pcm)

    session = FakeSession()
    result = asyncio.run(feed_wav_to_session(session, wav_path, sleep_s=0))

    assert result["chunks"] == 1
    assert result["bytes"] == len(frames)
    assert session.chunks == [frames]


def test_feed_wav_to_session_rejects_wrong_format(tmp_path):
    from joy_interaction_webui.jarvis_routes import feed_wav_to_session

    wav_path = tmp_path / "bad.wav"
    _write_wav(wav_path, b"\x00\x00" * 100, sample_rate=8000)

    class FakeSession:
        async def feed_audio(self, pcm):
            raise AssertionError("should not feed invalid wav")

    try:
        asyncio.run(feed_wav_to_session(FakeSession(), wav_path, sleep_s=0))
    except ValueError as exc:
        assert "16kHz mono int16" in str(exc)
    else:
        raise AssertionError("expected ValueError")
