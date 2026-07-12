"""Sherpa-onnx KWS engine for Jarvis mode.

Detects wake word (default "bt"; sherpa-onnx KWS reads actual keyword
3: from keywords.txt at model_dir/keywords.txt — must be BPE-style "B T @bt").
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import sherpa_onnx

logger = logging.getLogger("joyai.jarvis.kws")


class JarvisKWS:
    """Wake-word detection via sherpa-onnx KWS.

    CPU-only, ~56MB self-trained v4 encoder + ~50KB decoder+joiner, <0.5% CPU usage.
    Uses a single persistent stream (fixed 2026-07-09: was creating
    a new stream per chunk, which prevented wake word detection).
    """

    def __init__(
        self,
        model_dir: str = "D:/AI/models/sherpa-onnx/models/kws/bt-zai-ma",
        wake_word: str = "bt",
        num_threads: int = 1,
        keywords_score: float = 10.0,
        keywords_threshold: float = 0.25,
        num_trailing_blanks: int = 1,
        max_active_paths: int = 10,
    ):
        """Init KWS.

        Args:
            model_dir: sherpa-onnx KWS model dir.
            wake_word: 唤醒词 (display only, 实际从 keywords_file 读).
            num_threads: ONNX Runtime 线程数.
            keywords_score: keyword boost score (sherpa-onnx KeywordSpotter 调优).
                社区默认 1.0 对自训 2-token joiner 不够; v4 训练后用 10.0
                (FAR 15.5% / recall 75.5% 甜蜜点, 详见 test_sherpa_load.py 扫表).
            keywords_threshold: acoustic probability threshold to fire.
            num_trailing_blanks: trailing blank frames required after keyword.
            max_active_paths: beam search width (community default 4 不够, 用 10).
        """
        model_path = Path(model_dir)
        if not model_path.exists():
            raise FileNotFoundError(
                f"KWS model dir not found: {model_dir}\n"
                f"Download sherpa-onnx prebuilt: "
                f"https://github.com/k2-fsa/sherpa-onnx/releases"
            )

        keywords_file = model_path / "keywords.txt"
        if not keywords_file.exists():
            keywords_file.write_text(wake_word, encoding="utf-8")
            logger.info(f"Created {keywords_file} with wake word: {wake_word}")

        # sherpa-onnx prebuilt ships encoder/decoder/joiner with epoch+chunk suffix.
        # Pick the smaller chunk (chunk-8) for lower latency on short wake words.
        encoder = next(model_path.glob("encoder*chunk-8*.onnx"), model_path / "encoder.onnx")
        decoder = next(model_path.glob("decoder*chunk-8*.onnx"), model_path / "decoder.onnx")
        joiner = next(model_path.glob("joiner*chunk-8*.onnx"), model_path / "joiner.onnx")
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_path / "tokens.txt"),
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            keywords_file=str(keywords_file),
            num_threads=num_threads,
            sample_rate=16000,
            keywords_score=keywords_score,
            keywords_threshold=keywords_threshold,
            num_trailing_blanks=num_trailing_blanks,
            max_active_paths=max_active_paths,
        )
        self.wake_word = wake_word
        self.keywords_score = keywords_score
        self.keywords_threshold = keywords_threshold
        logger.info(
            f"KWS config: score={keywords_score} th={keywords_threshold} "
            f"trailing_blanks={num_trailing_blanks} max_paths={max_active_paths}"
        )
        self.stream: Optional[sherpa_onnx.KeywordSpotter.Stream] = None
        logger.info(f"KWS loaded: model={model_dir}, wake_word={wake_word!r}")

    def start(self):
        """Start/reset the KWS stream (creates fresh persistent stream)."""
        self.stream = self.spotter.create_stream()
        logger.debug("KWS stream started/reset")

    def feed_audio(self, pcm: bytes) -> bool:
        """Feed a PCM chunk (16kHz int16 mono), return True if wake word detected.

        Uses a persistent stream created by start() — each chunk feeds
        into the same stream so the transducer can accumulate cross-chunk
        context.  After detection the stream is _reset_ to avoid re-triggering
        on the same audio buffer.

        Args:
            pcm: raw int16 little-endian PCM bytes

        Returns:
            True if wake word detected in this chunk, False otherwise.
        """
        if self.stream is None:
            self.start()

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.stream.accept_waveform(16000, samples)

        if not self.spotter.is_ready(self.stream):
            return False

        self.spotter.decode_stream(self.stream)
        # get_result returns the detected keyword as a string (empty = no hit)
        result_str = self.spotter.get_result(self.stream)
        if not result_str:
            return False

        # any non-empty detection is a hit (model only fires on registered keywords)
        detected = True
        logger.info("Wake word detected: %r", result_str)
        # reset to avoid re-triggering on the same audio buffer
        self.stream = self.spotter.create_stream()
        return detected

    def detect_in_pcm(self, pcm: bytes, chunk_samples: int = 1600) -> bool:
        """Run a fresh one-shot KWS stream over a PCM window.

        This is used as a live fallback when the long-running stream misses a
        phrase that a clean rolling window can detect. It does not mutate the
        persistent ``self.stream`` used by ``feed_audio``.
        """
        if not pcm:
            return False
        stream = self.spotter.create_stream()
        chunk_bytes = max(1, chunk_samples) * 2
        for offset in range(0, len(pcm), chunk_bytes):
            chunk = pcm[offset: offset + chunk_bytes]
            if len(chunk) < 2:
                continue
            if len(chunk) % 2:
                chunk = chunk[:-1]
            samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            if samples.size == 0:
                continue
            stream.accept_waveform(16000, samples)
            if not self.spotter.is_ready(stream):
                continue
            self.spotter.decode_stream(stream)
            result_str = self.spotter.get_result(stream)
            if result_str:
                logger.info("Wake word detected in fresh PCM window: %r", result_str)
                return True
        return False

    def stop(self):
        """Release the KWS stream."""
        self.stream = None


if __name__ == "__main__":
    import sys
    import wave
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m services.asr.jarvis.kws <wav_path>")
        sys.exit(1)

    wav_path = Path(sys.argv[1])
    if not wav_path.exists():
        print(f"File not found: {wav_path}")
        sys.exit(1)

    kws = JarvisKWS()
    kws.start()

    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1, "mono only"
        assert wf.getsampwidth() == 2, "int16 only"
        assert wf.getframerate() == 16000, "16kHz only"

        chunk_size = 1600  # 100ms @ 16kHz int16
        while True:
            data = wf.readframes(chunk_size // 2)
            if not data:
                break
            if kws.feed_audio(data):
                print("Wake word detected!")
                sys.exit(0)

    print("Wake word not detected")
    sys.exit(1)

