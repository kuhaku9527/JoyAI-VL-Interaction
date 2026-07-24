"""Analyze live KWS diagnostic captures.

Reads 16 kHz mono PCM16 WAV files, runs the current Jarvis KWS config and
streaming ASR, then prints one TSV row per file:

    file    kws_hit    asr_text    duration_s

Use this after a live Listen test to decide which captures are positives,
hard negatives, or input-device failures.
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "webui" / "src"))

from joy_interaction_webui.jarvis_mode import JarvisConfig

from services.asr.jarvis.asr import JarvisASR
from services.asr.jarvis.kws import JarvisKWS

DEFAULT_CAPTURE_DIR = Path("D:/AI/data/kws/mic_captures")


def _iter_wavs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("*.wav"))


def _read_chunks(wav_path: Path, chunk_frames: int = 1600):
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise ValueError(f"{wav_path} must be 16kHz mono PCM16")
        nframes = wf.getnframes()
        while True:
            pcm = wf.readframes(chunk_frames)
            if not pcm:
                break
            yield pcm, nframes / 16000.0


def analyze_one(wav_path: Path, cfg: JarvisConfig) -> dict:
    kws = JarvisKWS(
        model_dir=cfg.kws_model_dir,
        wake_word=cfg.wake_word,
        num_threads=cfg.kws_num_threads,
        keywords_score=cfg.kws_keywords_score,
        keywords_threshold=cfg.kws_keywords_threshold,
        num_trailing_blanks=cfg.kws_num_trailing_blanks,
        max_active_paths=cfg.kws_max_active_paths,
    )
    asr = JarvisASR(model_dir=cfg.asr_model_dir, num_threads=cfg.asr_num_threads)
    kws.start()
    asr.start()
    hit = False
    text = ""
    duration = 0.0
    for pcm, chunk_dur in _read_chunks(wav_path):
        duration = chunk_dur
        if kws.feed_audio(pcm):
            hit = True
        next_text = asr.feed_chunk(pcm) or ""
        if next_text:
            text = next_text
    kws.stop()
    asr.stop()
    return {
        "file": str(wav_path),
        "kws_hit": hit,
        "asr_text": text,
        "duration_s": duration,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze KWS live capture WAVs")
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_CAPTURE_DIR)
    args = parser.parse_args()

    cfg = JarvisConfig.from_env()
    wavs = _iter_wavs(args.path)
    if not wavs:
        print(f"No wav files found: {args.path}", file=sys.stderr)
        return 1

    print("file\tkws_hit\tasr_text\tduration_s")
    for wav_path in wavs:
        try:
            row = analyze_one(wav_path, cfg)
        except Exception as exc:
            print(f"{wav_path}\tERROR\t{exc}\t0")
            continue
        print(
            f"{row['file']}\t{int(row['kws_hit'])}\t"
            f"{row['asr_text']}\t{row['duration_s']:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
