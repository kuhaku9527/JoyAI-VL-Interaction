"""Sherpa-onnx streaming ASR engine for Jarvis mode.

Streaming recognition with first-token latency 200-400ms.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import sherpa_onnx

logger = logging.getLogger("joyai.jarvis.asr")


class JarvisASR:
    """Streaming ASR via sherpa-onnx Paraformer.

    First-token latency 200-400ms, CPU-only, ~200MB RAM, ~100MB disk.
    """

    def __init__(
        self,
        model_dir: str = "D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en",
        num_threads: int = 2,
    ):
        model_path = Path(model_dir)
        if not model_path.exists():
            raise FileNotFoundError(
                f"ASR model dir not found: {model_dir}\n"
                f"Download sherpa-onnx streaming-paraformer: "
                f"https://github.com/k2-fsa/sherpa-onnx/releases"
            )

        # Streaming-paraformer (not transducer) — encoder + decoder only
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=str(model_path / "tokens.txt"),
            encoder=str(model_path / "encoder.int8.onnx"),
            decoder=str(model_path / "decoder.int8.onnx"),
            num_threads=num_threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.0,
            rule2_min_trailing_silence=0.8,
            rule3_min_utterance_length=8.0,
        )
        self.stream = None
        self.last_text = ""
        logger.info(f"Streaming ASR loaded: {model_dir}")

    def start(self):
        """Start a new streaming session."""
        self.stream = self.recognizer.create_stream()
        self.last_text = ""
        logger.debug("ASR session started")

    def feed_chunk(self, pcm: bytes) -> str:
        """Feed a PCM chunk, return latest partial text.

        Args:
            pcm: raw int16 little-endian PCM bytes (16kHz mono)

        Returns
        -------
            Latest partial transcription (may be empty string).
        """
        if self.stream is None:
            self.start()
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.stream.accept_waveform(16000, samples)
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_streams([self.stream])
        text = self.recognizer.get_result(self.stream)  # Paraformer returns str
        if text != self.last_text:
            self.last_text = text
        return text

    def stop(self):
        """Stop streaming session."""
        self.stream = None
        self.last_text = ""
        logger.debug("ASR session stopped")


if __name__ == "__main__":
    import sys
    import wave
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m services.asr.jarvis.asr <wav_path>")
        sys.exit(1)

    wav_path = Path(sys.argv[1])
    asr = JarvisASR()
    asr.start()

    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError("input wav must be mono (1 channel)")
        if wf.getsampwidth() != 2:
            raise ValueError("input wav must be 16-bit PCM (int16)")
        if wf.getframerate() != 16000:
            raise ValueError("input wav must be sampled at 16000 Hz")
        chunk_size = 1600  # 100ms chunks
        while True:
            data = wf.readframes(chunk_size // 2)
            if not data:
                break
            text = asr.feed_chunk(data)
            if text:
                print(f"[partial] {text}")
    print(f"[final] {asr.last_text}")
