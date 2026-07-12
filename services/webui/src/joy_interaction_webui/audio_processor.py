"""WebRTC audio tracks for the BT-7274 Jarvis mode.

Two tracks cooperate with ``JarvisSessionManager``:

* :class:`MicAudioTrack` consumes a remote audio track (the browser mic),
  decodes the AudioFrame to PCM16 bytes, optionally resamples to 16 kHz
  mono (the rate the sherpa-onnx ASR expects), and feeds the chunks to
  the session's state machine via :meth:`JarvisSession.feed_audio`.

* :class:`SpeakerAudioTrack` is a server-side outbound track. The Jarvis
  state machine pushes PCM16 bytes through ``audio_output(pcm, sr)``;
  :meth:`SpeakerAudioTrack.push_pcm` enqueues them and ``recv()`` packs
  them into 20 ms AudioFrames for the peer connection.

Both tracks run cooperatively — ``recv()`` is an async coroutine that
yields control between frames, so the event loop stays responsive even
while audio is flowing.
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import time
from typing import Optional

import numpy as np
from aiortc import AudioStreamTrack
from aiortc.mediastreams import AudioFrame, MediaStreamError
from av.audio.resampler import AudioResampler

logger = logging.getLogger("joyai.jarvis.audio")

# Frame size in milliseconds (matches WebRTC OPUS default packet time).
FRAME_DURATION_MS = 20


# ============================================================================
# Inbound — browser microphone -> jarvis session
# ============================================================================


class MicAudioTrack(AudioStreamTrack):
    """Consume a remote audio track and forward PCM to a Jarvis session.

    The remote track is normally an OPUS track from the browser at
    48 kHz stereo. We resample to 16 kHz mono before calling
    ``session.feed_audio`` because that is what the sherpa-onnx ASR
    expects (and ``_handle_kws`` / ``_handle_dialog`` assume that rate
    internally).
    """

    kind = "audio"

    def __init__(
        self,
        track: AudioStreamTrack,
        session,
        target_rate: int = 16000,
    ) -> None:
        super().__init__()
        self._track = track
        self._session = session
        self._target_rate = target_rate
        self._resampler: Optional[AudioResampler] = None
        self._frame_count = 0
        self._start = time.time()
        self._timestamp = 0

    async def recv(self) -> AudioFrame:
        """Receive next frame from upstream, resample, forward to session."""
        if self.readyState != "live":
            raise MediaStreamError

        frame = await self._track.recv()
        self._frame_count += 1

        # Lazy resampler (depends on inbound sample rate / layout).
        if self._resampler is None:
            self._resampler = AudioResampler(
                format="s16", layout="mono", rate=self._target_rate
            )
        resampled_frames = self._resampler.resample(frame)
        for rf in resampled_frames:
            pcm_bytes = bytes(rf.planes[0])
            if pcm_bytes:
                await self._session.feed_audio(pcm_bytes)

        # Return a no-op audio frame so the WebRTC track stays "live".
        # We do not echo mic audio back to the speaker.
        silence = AudioFrame(
            format="s16", layout="mono", samples=int(self._target_rate * FRAME_DURATION_MS / 1000)
        )
        for p in silence.planes:
            p.update(bytes(p.buffer_size))
        silence.pts = self._timestamp
        silence.sample_rate = self._target_rate
        silence.time_base = fractions.Fraction(1, self._target_rate)
        self._timestamp += silence.samples
        return silence

    def stop(self) -> None:
        logger.info("Mic track stopped after %d frames", self._frame_count)
        super().stop()


# ============================================================================
# Outbound — jarvis session -> browser speaker
# ============================================================================


class SpeakerAudioTrack(AudioStreamTrack):
    """Server-side audio track that plays PCM pushed by jarvis.

    The state machine calls ``audio_output(pcm, sample_rate)`` whenever
    it has audio to play (TTS responses, pre-recorded wake.wav /
    goodbye.wav). We treat every push as a contiguous chunk and feed it
    into a queue that ``recv()`` drains in 20 ms slices.

    Use :meth:`push_pcm` as the ``audio_output`` callback passed to
    :class:`JarvisSessionManager` or :class:`JarvisStateMachine`.
    """

    kind = "audio"

    def __init__(self, sample_rate: int = 24000, max_queue_chunks: int = 256) -> None:
        super().__init__()
        self._target_rate = sample_rate
        self._frame_samples = int(sample_rate * FRAME_DURATION_MS / 1000)
        # Queue holds raw PCM16 bytes. We split into 20 ms slices at recv time.
        self._pcm_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_queue_chunks)
        self._buffer = bytearray()
        self._timestamp = 0
        self._start = time.time()
        self._frame_count = 0
        self._closed = False

    async def push_pcm(self, pcm: bytes, sample_rate: int) -> None:
        """Callback compatible with ``audio_output`` signature.

        We resample if the source rate differs from our target rate.
        """
        if self._closed:
            return
        if not pcm:
            return
        if sample_rate != self._target_rate:
            pcm = _resample_pcm16(pcm, sample_rate, self._target_rate)
        try:
            self._pcm_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            logger.warning("Speaker queue full; dropping %d bytes", len(pcm))

    async def recv(self) -> AudioFrame:
        """Build a 20 ms AudioFrame from queued PCM, padding with silence if empty."""
        if self.readyState != "live":
            raise MediaStreamError

        # Pull next chunk if buffer is short.
        while len(self._buffer) < self._frame_samples * 2:
            try:
                chunk = self._pcm_queue.get_nowait()
                self._buffer.extend(chunk)
            except asyncio.QueueEmpty:
                # No audio right now — pad with silence.
                break

        frame_bytes = self._frame_samples * 2  # 2 bytes per sample (s16)
        if len(self._buffer) >= frame_bytes:
            frame_pcm = bytes(self._buffer[:frame_bytes])
            del self._buffer[:frame_bytes]
        else:
            # Pad short buffer with silence.
            frame_pcm = bytes(self._buffer) + b"\x00" * (frame_bytes - len(self._buffer))
            self._buffer.clear()

        frame = AudioFrame(format="s16", layout="mono", samples=self._frame_samples)
        for p in frame.planes:
            p.update(frame_pcm)
        frame.pts = self._timestamp
        frame.sample_rate = self._target_rate
        frame.time_base = fractions.Fraction(1, self._target_rate)
        self._timestamp += self._frame_samples
        self._frame_count += 1

        # Pacing: ~20 ms between frames.
        elapsed = time.time() - self._start
        expected = self._timestamp / self._target_rate
        wait = expected - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        return frame

    def stop(self) -> None:
        self._closed = True
        logger.info("Speaker track stopped after %d frames", self._frame_count)
        super().stop()


# ============================================================================
# Helpers
# ============================================================================


def _resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample PCM16 mono bytes using numpy (no extra deps).

    Cheap linear interpolation; fine for short TTS chunks where perfect
    quality is not required.
    """
    if src_rate == dst_rate or not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return pcm
    duration = samples.size / src_rate
    dst_len = max(1, int(round(duration * dst_rate)))
    x_old = np.linspace(0, samples.size - 1, samples.size)
    x_new = np.linspace(0, samples.size - 1, dst_len)
    resampled = np.interp(x_new, x_old, samples.astype(np.float32)).astype(np.int16)
    return resampled.tobytes()