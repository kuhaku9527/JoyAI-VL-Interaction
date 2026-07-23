"""Tests for diagnostic feed task lifecycle."""

from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _make_wav(path: Path, seconds: int = 6, rate: int = 16000) -> None:
    import struct

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        silence = struct.pack("<h", 0) * rate
        for _ in range(seconds):
            wf.writeframes(silence)


async def test_attach_feed_task_cancels_previous():
    from joy_interaction_webui.jarvis_session import JarvisSession

    s = JarvisSession.__new__(JarvisSession)
    s._feed_task = None

    cancelled = {"first": False, "second": False}

    async def runner_first():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled["first"] = True
            raise

    async def runner_second():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled["second"] = True
            raise

    first = asyncio.create_task(runner_first())
    # Yield so the task actually starts and enters its sleep
    await asyncio.sleep(0)
    s.attach_feed_task(first)
    second = asyncio.create_task(runner_second())
    await asyncio.sleep(0)
    s.attach_feed_task(second)
    # Give the cancel+await chain time to propagate
    await asyncio.sleep(0.05)
    assert cancelled["first"] is True, "previous task should have been cancelled"
    assert cancelled["second"] is False
    second.cancel()
    try:
        await second
    except asyncio.CancelledError:
        pass


async def test_session_stop_cancels_feed_task():
    from joy_interaction_webui.jarvis_session import JarvisSession

    s = JarvisSession.__new__(JarvisSession)
    s._bg_task = None

    flag = {"cancelled": False}

    async def runner():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            flag["cancelled"] = True
            raise

    task = asyncio.create_task(runner())
    await asyncio.sleep(0)
    s._feed_task = task
    await s.stop()
    assert flag["cancelled"] is True, "stop() must cancel _feed_task"


async def test_feed_wav_max_duration_caps_runtime(tmp_path):
    from joy_interaction_webui.jarvis_routes import feed_wav_to_session

    wav = tmp_path / "long.wav"
    _make_wav(wav, seconds=10)

    received = {"chunks": 0}

    class FakeSession:
        async def feed_audio(self, pcm: bytes):
            received["chunks"] += 1

    t0 = time.time()
    result = await feed_wav_to_session(
        FakeSession(),
        wav,
        chunk_frames=1600,
        sleep_s=0.05,
        max_duration_s=0.5,
    )
    elapsed = time.time() - t0
    assert result["chunks"] < 30, f"expected early stop, got {result['chunks']} chunks"
    assert elapsed < 3.0, f"expected fast stop, got {elapsed:.2f}s"
    assert received["chunks"] == result["chunks"]
