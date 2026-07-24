"""用 sherpa-onnx 1.13.4 验证 KWS 模型可加载 + 能识别 BT。

用法:
  python test_sherpa_load.py \
      --encoder /path/to/encoder.onnx \
      --decoder /path/to/decoder.onnx \
      --joiner  /path/to/joiner.onnx \
      --tokens  /path/to/tokens.txt \
      --keywords /path/to/keywords.txt \
      --test-wav /path/to/bt.wav
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import sherpa_onnx


def read_wav_16k(path: Path):
    """读 wav (或兜底 m4a/mp3/flac). 返回 (int16_list, sample_rate)."""
    suffix = path.suffix.lower()
    if suffix == ".wav":
        with wave.open(str(path), "rb") as w:
            assert w.getnchannels() == 1, f"期望单声道, 实际 {w.getnchannels()}"
            assert w.getsampwidth() == 2, f"期望 int16, 实际 sampwidth={w.getsampwidth()}"
            sr = w.getframerate()
            raw = w.readframes(w.getnframes())
            samples = [int.from_bytes(raw[i:i+2], "little", signed=True)
                       for i in range(0, len(raw), 2)]
            return samples, sr
    if suffix in (".m4a", ".mp3", ".flac"):
        import soundfile as sf
        audio, sr = sf.read(str(path), dtype="int16")
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype("int16")
        return audio.tolist(), sr
    raise ValueError(f"不支持的格式: {suffix}")


def evaluate_dir(spotter, wav_dir, keywords, max_files=None):
    """在 wav 目录上跑, 返回 (总数, 命中数, 每 wav 命中数 list)."""
    wavs = sorted(wav_dir.glob("*.wav"))
    if max_files is not None:
        wavs = wavs[:max_files]
    n_total = len(wavs)
    hits_per_wav = []
    n_hit = 0
    for w in wavs:
        try:
            samples, sr = read_wav_16k(w)
            stream = spotter.create_stream(keywords)
            stream.accept_waveform(sr, samples)
            tail = [0] * int(0.66 * sr)
            stream.accept_waveform(sr, tail)
            stream.input_finished()
            local_hits = 0
            while spotter.is_ready(stream):
                spotter.decode_stream(stream)
                r = spotter.get_result(stream)
                if r:
                    local_hits += 1
                    spotter.reset_stream(stream)
            hits_per_wav.append((w.name, local_hits))
            if local_hits > 0:
                n_hit += 1
        except Exception as e:
            hits_per_wav.append((w.name + " (err: " + str(e) + ")", 0))
    return n_total, n_hit, hits_per_wav


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--encoder",  type=Path, required=True)
    p.add_argument("--decoder",  type=Path, required=True)
    p.add_argument("--joiner",   type=Path, required=True)
    p.add_argument("--tokens",   type=Path, required=True)
    p.add_argument("--keywords", type=Path, required=True)
    p.add_argument("--test-wav", type=Path, required=False)
    p.add_argument("--num-threads", type=int, default=2)
    p.add_argument("--keywords-threshold", type=float, default=0.25)
    p.add_argument("--keywords-score", type=float, default=2.0)
    p.add_argument("--num-trailing-blanks", type=int, default=1)
    p.add_argument("--max-active-paths", type=int, default=10)
    p.add_argument("--eval-dir", type=Path, default=None,
                   help="批量评估模式: 扫这个目录下所有 wav, 报 (总数, 命中数, 每 wav 命中数)")
    p.add_argument("--max-files", type=int, default=None,
                   help="批量评估时最多跑几个 wav (调试用)")
    args = p.parse_args()

    print(f"=== 测试加载: {args.encoder.parent.name} ===")
    for k in ("encoder", "decoder", "joiner", "tokens", "keywords", "test_wav"):
        print(f"  {k:9s}: {getattr(args, k.replace('-', '_'))}")
    print()

    print("[1/3] 加载 KeywordSpotter ...")
    t0 = time.time()
    try:
        spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(args.tokens),
            encoder=str(args.encoder),
            decoder=str(args.decoder),
            joiner=str(args.joiner),
            keywords_file=str(args.keywords),
            num_threads=args.num_threads,
            provider="cpu",
            keywords_threshold=args.keywords_threshold,
            keywords_score=args.keywords_score,
            num_trailing_blanks=args.num_trailing_blanks,
            max_active_paths=args.max_active_paths,
        )
        print(f"  [OK] 加载成功 ({time.time()-t0:.2f}s)")
        # eval-dir 批量模式: 加载成功就跳去 batch_main
        if args.eval_dir is not None:
            return batch_main(args, spotter)
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("[2/3] 读 wav + 喂 stream ...")
    samples, sr = read_wav_16k(args.test_wav)
    if sr != 16000:
        print(f"  [warn] sr={sr}, 期望 16000 (sherpa-onnx 内部会重采)")
    print(f"  samples: {len(samples)} ({len(samples)/sr:.2f}s)")

    stream = spotter.create_stream()
    stream.accept_waveform(sr, samples)
    tail_paddings = [0] * int(0.66 * sr)
    stream.accept_waveform(sr, tail_paddings)
    stream.input_finished()

    print("[3/3] 解码 + 检测 ...")
    t0 = time.time()
    n_detected = 0
    while spotter.is_ready(stream):
        spotter.decode_stream(stream)
        r = spotter.get_result(stream)
        if r:
            n_detected += 1
            toks = spotter.tokens(stream)
            print(f"  [HIT {n_detected}] keyword='{r}' tokens={toks}")
            spotter.reset_stream(stream)
    print(f"  扫完 ({time.time()-t0:.2f}s)")

    if n_detected == 0:
        print("  [result] 没检测到 BT")
        return 2
    print(f"  [result] 共 {n_detected} 次命中")
    return 0


def batch_main(args, spotter):
    """批量评估: 跑 args.eval_dir 下所有 wav, 报 FAR / 命中分布."""
    print(f"[3/batch] 评估目录: {args.eval_dir}")
    # 内联 keyword: 让 sherpa-onnx 同时评估 keywords 文件 + 内联词表
    keywords_inline = None
    try:
        kw = Path(args.keywords).read_text(encoding="utf-8").strip()
        keywords_inline = kw if kw else None
    except Exception:  # noqa: S110
        pass
    n_total, n_hit, hits_per_wav = evaluate_dir(spotter, args.eval_dir, keywords_inline, args.max_files)
    far = n_hit / n_total if n_total else 0
    total_hits = sum(h for _, h in hits_per_wav)
    avg_hits = total_hits / n_total if n_total else 0
    print(f"  [batch] 总数={n_total}  触发 wav={n_hit}  FAR={far:.2%}")
    print(f"  [batch] 总命中={total_hits}  均值={avg_hits:.1f} 次/wav")
    # 命中分布直方图
    from collections import Counter
    cnt = Counter(h for _, h in hits_per_wav)
    print("  [batch] 命中数分布:")
    for k in sorted(cnt.keys()):
        print(f"     {k:3d} hits : {cnt[k]:3d} wavs")
    # 触发最多的前 5 个 wav
    top5 = sorted(hits_per_wav, key=lambda x: -x[1])[:5]
    print("  [batch] 触发 top5:")
    for name, h in top5:
        if h > 0:
            print(f"     {h:3d} hits : {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
