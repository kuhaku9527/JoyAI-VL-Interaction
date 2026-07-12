"""
KWS 自训语料采集脚本（Windows 侧，唤醒词 "BT"）。

设计要点：
- 录 N 句 "BT"（正样本）+ 200 段背景/其他语音（负样本）
- 16kHz mono int16 WAV
- 能量 VAD 自动裁剪静音
- 写 lhotse 兼容 JSONL manifest（切到 WSL2 后可直接喂 icefall）
- 用法：
    python record_kws_corpus.py --label positive --count 50
    python record_kws_corpus.py --label negative --count 200
    python record_kws_corpus.py --label positive --count 3 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

# ============== 常量 ==============

TARGET_SR = 16000
TARGET_CHANNELS = 1
DTYPE = "int16"
DEFAULT_DATA_ROOT = Path("D:/AI/data/kws/bt-en")

# 能量 VAD 参数
VAD_FRAME_MS = 30
VAD_ENERGY_THRESHOLD = 0.01
VAD_PAD_SAMPLES = int(0.15 * TARGET_SR)

MAX_RECORD_SEC = 3.0
MIN_RECORD_SEC = 0.3


# ============== 工具函数 ==============

def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float32) ** 2) + 1e-12))


def trim_silence(audio: np.ndarray, sr: int = TARGET_SR) -> np.ndarray:
    if len(audio) < sr * MIN_RECORD_SEC:
        return audio
    frame_size = int(sr * VAD_FRAME_MS / 1000)
    n_frames = len(audio) // frame_size
    voiced_frames = []
    for i in range(n_frames):
        seg = audio[i * frame_size : (i + 1) * frame_size]
        if rms(seg) >= VAD_ENERGY_THRESHOLD:
            voiced_frames.append(i)
    if not voiced_frames:
        return audio
    first = max(0, voiced_frames[0] * frame_size - VAD_PAD_SAMPLES)
    last = min(len(audio), (voiced_frames[-1] + 1) * frame_size + VAD_PAD_SAMPLES)
    return audio[first:last]


def record_one(duration_sec: float, sr: int, device: int | None) -> np.ndarray:
    frames = int(duration_sec * sr)
    rec = sd.rec(
        frames, samplerate=sr, channels=TARGET_CHANNELS, dtype=DTYPE, device=device,
    )
    sd.wait()
    return rec.flatten()


def write_wav(path: Path, audio: np.ndarray, sr: int = TARGET_SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, sr, subtype="PCM_16")


# ============== 主流程 ==============

def main() -> int:
    parser = argparse.ArgumentParser(
        description="KWS 训练语料采集（BT / 背景）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--label", choices=["positive", "negative"], required=True)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--device", type=int, default=None)
    parser.add_argument("--max-sec", type=float, default=MAX_RECORD_SEC)
    parser.add_argument("--sr", type=int, default=TARGET_SR)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sub = "positive" if args.label == "positive" else "negative"
    wav_dir = args.data_root / sub
    manifest_path = args.data_root / f"{sub}.jsonl"
    wav_dir.mkdir(parents=True, exist_ok=True)

    if args.device is None:
        info = sd.query_devices(kind="input")
        print(f"  [info] 默认输入设备: {info['name']} (idx={info['index']})")
        args.device = info["index"]
    else:
        info = sd.query_devices(args.device)
        print(f"  [info] 指定输入设备: {info['name']} (idx={args.device})")
    print(f"  [info] 采样率: {args.sr} Hz, 通道: {TARGET_CHANNELS}, dtype: {DTYPE}")
    print(f"  [info] 数据目录: {wav_dir}")
    print(f"  [info] 目标条数: {args.count}")
    print()

    print("=" * 60)
    if args.label == "positive":
        print('  正样本采集：说 "BT"（按 Enter 开始 / 自动结束）')
        print("  多样性建议：30cm/1m/2m × 正常/大/小声 × 正常/稍快/稍慢")
    else:
        print("  负样本采集：自由说话 / 沉默 / 风扇 / 键盘 / 电视声")
    print("=" * 60)
    print()

    existing_files = {p.name for p in wav_dir.glob("*.wav")} if args.skip_existing else set()
    n_done = len(existing_files)
    n_target = args.count
    if n_done >= n_target:
        print(f"  [done] 已录 {n_done} 条 >= 目标 {n_target}")
        return 0
    print(f"  [start] 已存在 {n_done} 条，还需 {n_target - n_done} 条")
    print()

    n_skipped = 0
    try:
        for i in range(n_done, n_target):
            wav_name = f"{sub}_{i + 1:04d}.wav"
            wav_path = wav_dir / wav_name
            print(f"--- [{i + 1}/{n_target}] {wav_name} ---")
            if args.dry_run:
                audio = np.zeros(int(args.sr * 1.0), dtype=np.int16)
                write_wav(wav_path, audio, args.sr)
                print(f"  [dry-run] 写了 1s 静音")
                continue

            input("  按 Enter 开始录音 > ")
            t0 = time.time()
            audio = record_one(args.max_sec, args.sr, args.device)
            dt = time.time() - t0

            audio_trim = trim_silence(audio, args.sr)
            dur = len(audio_trim) / args.sr

            if dur < MIN_RECORD_SEC:
                print(f"  [skip] 裁剪后 {dur:.2f}s < {MIN_RECORD_SEC}s（疑似静音）")
                n_skipped += 1
                if n_skipped >= 3:
                    print("  [warn] 连续 3 次空录音，检查麦克风/电平")
                    n_skipped = 0
                continue

            write_wav(wav_path, audio_trim, args.sr)
            rms_db = 20 * np.log10(rms(audio_trim) + 1e-9)
            print(f"  [ok] {dur:.2f}s, RMS={rms_db:.1f} dB → {wav_path.name}")
            n_done += 1
            print()
    except KeyboardInterrupt:
        print("\n  [interrupt] 用户中断")

    print()
    print(f"  [manifest] 写 {manifest_path}")
    with manifest_path.open("w", encoding="utf-8") as f:
        for wav in sorted(wav_dir.glob("*.wav")):
            info = sf.info(str(wav))
            entry = {
                "id": wav.stem,
                "audio": str(wav.resolve()),
                "duration": info.duration,
                "sampling_rate": info.samplerate,
                "channels": info.channels,
            }
            if args.label == "positive":
                entry["text"] = "BT"
                entry["tokens"] = "B T"
                entry["keyword"] = "bt"
            else:
                entry["text"] = ""
                entry["tokens"] = ""
                entry["keyword"] = "negative"
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"  [done] 共 {n_done} 条 / 目标 {n_target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())