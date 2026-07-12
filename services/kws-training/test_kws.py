"""
KWS 评估：0/1 命中 + FP 率。

输入：
  /mnt/d/AI/models/sherpa-onnx/models/kws/bt-en/  (ONNX 模型)
  /mnt/d/AI/data/kws/bt-en/manifests/positive_test.jsonl.gz
  /mnt/d/AI/data/kws/bt-en/manifests/negative_test.jsonl.gz

输出：
  hit_rate（应接近 1.0）
  false_positive_rate（应接近 0.0）
  per-file 详情

用法（WSL2）：
  python test_kws.py --model-dir /mnt/d/AI/models/sherpa-onnx/models/kws/bt-en

依赖：sherpa-onnx（pip install sherpa-onnx 即可）
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
import wave
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kws-test")


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--manifests-dir", type=Path,
                   default=Path("/mnt/d/AI/data/kws/bt-en/manifests"))
    p.add_argument("--num-threads", type=int, default=1)
    return p.parse_args()


def load_manifest_jsonl_gz(path: Path) -> list[dict]:
    entries = []
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def test_one_sherpa(kws, wav_path: Path) -> bool:
    """用 sherpa-onnx KeywordSpotter 测一个 wav，返回是否命中。"""
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getsampwidth() == 2
        samples = np.frombuffer(
            wf.readframes(wf.getnframes()), dtype=np.int16
        ).astype(np.float32) / 32768.0

    stream = kws.create_stream()
    chunk = 1600  # 100ms
    for i in range(0, len(samples), chunk):
        stream.accept_waveform(16000, samples[i: i + chunk])
        # 关键：调用 decode_stream 才能触发 KWS 判定
        if kws.is_ready(stream):
            kws.decode_stream(stream)
            result = kws.get_result(stream)
            if result:
                return True
    # 末尾也得跑一遍（音频播完后）
    if kws.is_ready(stream):
        kws.decode_stream(stream)
        result = kws.get_result(stream)
        if result:
            return True
    return False


def main():
    args = get_args()
    if not args.model_dir.exists():
        logger.error(f"模型目录不存在: {args.model_dir}")
        sys.exit(1)
    if not (args.model_dir / "encoder.onnx").exists():
        logger.error(f"缺 encoder.onnx: {args.model_dir}")
        sys.exit(1)

    # 加载 sherpa-onnx
    try:
        import sherpa_onnx
    except ImportError:
        logger.error("缺 sherpa-onnx（在 WSL2 跑：~/kws-train/bin/pip install sherpa-onnx）")
        sys.exit(1)
    logger.info(f"sherpa-onnx: {sherpa_onnx.__version__}")

    # chunk-8 优先（小延迟）
    encoder = next(args.model_dir.glob("encoder*chunk-8*.onnx"),
                   args.model_dir / "encoder.onnx")
    decoder = next(args.model_dir.glob("decoder*chunk-8*.onnx"),
                   args.model_dir / "decoder.onnx")
    joiner = next(args.model_dir.glob("joiner*chunk-8*.onnx"),
                  args.model_dir / "joiner.onnx")
    logger.info(f"  encoder: {encoder.name}")
    logger.info(f"  decoder: {decoder.name}")
    logger.info(f"  joiner: {joiner.name}")

    kws = sherpa_onnx.KeywordSpotter(
        tokens=str(args.model_dir / "tokens.txt"),
        encoder=str(encoder),
        decoder=str(decoder),
        joiner=str(joiner),
        keywords_file=str(args.model_dir / "keywords.txt"),
        num_threads=args.num_threads,
        sample_rate=16000,
    )

    # 加载测试集
    pos = load_manifest_jsonl_gz(args.manifests_dir / "positive_test.jsonl.gz")
    neg = load_manifest_jsonl_gz(args.manifests_dir / "negative_test.jsonl.gz")
    logger.info(f"Test set: positive={len(pos)}, negative={len(neg)}")

    # 评估
    pos_hits = 0
    pos_details = []
    for e in pos:
        hit = test_one_sherpa(kws, Path(e["audio"]))
        pos_hits += hit
        pos_details.append((e["id"], hit, e["duration"]))

    neg_hits = 0
    neg_details = []
    for e in neg:
        hit = test_one_sherpa(kws, Path(e["audio"]))
        neg_hits += hit
        neg_details.append((e["id"], hit, e["duration"]))

    # 报告
    print()
    print("=" * 60)
    print("  KWS 评估结果")
    print("=" * 60)
    print(f"  正样本: {pos_hits}/{len(pos)} = {pos_hits/max(len(pos),1)*100:.1f}% (应接近 100%)")
    print(f"  负样本: {neg_hits}/{len(neg)} = {neg_hits/max(len(neg),1)*100:.1f}% (应接近 0%)")
    print()

    if pos_hits < len(pos) * 0.8:
        print("  ⚠️  唤醒词检出率 <80%，考虑：")
        print("    - 增训正样本（再录 30 句）")
        print("    - 调 keywords_score 阈值")
        print("    - 检查负样本是否含 'bt 在吗' 误标")
    if neg_hits > len(neg) * 0.1:
        print("  ⚠️  误报率 >10%，考虑：")
        print("    - 增训负样本（再录 100 段噪声/对话）")
        print("    - 调 keywords_threshold 阈值")
        print("    - 检查训练 token 顺序是否对齐 keywords.txt")

    # 详情
    print()
    print("  正样本详情（id / 命中 / 时长）:")
    for id_, hit, dur in pos_details:
        mark = "✓" if hit else "✗"
        print(f"    {mark} {id_}  {dur:.2f}s")
    print()
    print("  负样本详情（前 20 个）:")
    for id_, hit, dur in neg_details[:20]:
        mark = "✓误报" if hit else "✗正确"
        print(f"    {mark}  {id_}  {dur:.2f}s")
    if len(neg_details) > 20:
        print(f"    ... 剩 {len(neg_details) - 20} 个省略")


if __name__ == "__main__":
    main()