"""
KWS 数据准备（WSL2 侧）：把 Windows 录好的 positive/negative 转成 lhotse cuts + train/test split。

唤醒词：**BT**（2 字符，纯英文字母，简化训练）
- 词表：~30 token（B/T/A/I + 必要静音 + 兜底 <unk>）
- keywords.txt: `B T @bt`

输入：
  /mnt/d/AI/data/kws/bt-en/positive/   （N wav，positive.jsonl）
  /mnt/d/AI/data/kws/bt-en/negative/   （M wav，negative.jsonl）

输出：
  /mnt/d/AI/data/kws/bt-en/manifests/
    ├── positive_train.jsonl.gz
    ├── positive_test.jsonl.gz
    ├── negative_train.jsonl.gz
    ├── negative_test.jsonl.gz
    ├── tokens.txt         # 简化词表
    └── keywords.txt       # "B T @bt"

用法（WSL2）：
  /home/ku/kws-train/bin/python /mnt/d/AI/workspace/JoyAI-VL-Interaction-main/services/scripts/prep_kws_data.py \\
      --data-root /mnt/d/AI/data/kws/bt-en \\
      --test-ratio 0.2
"""
from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
from pathlib import Path

# BT 唤醒词词表（最小化：只保留训练需要的 token）
PINYIN_VOCAB = [
    "<blk>", "<sos/eos>", "<unk>",
    # 唤醒词核心 token
    "B", "T",
    # 兜底噪声 / 静音
    "_",
]


def write_tokens(out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for idx, tok in enumerate(PINYIN_VOCAB):
            f.write(f"{tok} {idx}\n")
    print(f"  [tokens] {len(PINYIN_VOCAB)} tokens → {out_path}")


def write_keywords(out_path: Path) -> None:
    # sherpa-onnx keywords 格式: <phonemes> @<alias>
    out_path.write_text("B T @bt\n", encoding="utf-8")
    print(f"  [keywords] → {out_path}: B T @bt")


def load_manifest(jsonl_path: Path) -> list[dict]:
    entries = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def split_train_test(entries: list[dict], test_ratio: float, seed: int = 42) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    indices = list(range(len(entries)))
    rng.shuffle(indices)
    n_test = max(1, int(len(entries) * test_ratio))
    test_idx = set(indices[:n_test])
    train = [e for i, e in enumerate(entries) if i not in test_idx]
    test = [e for i, e in enumerate(entries) if i in test_idx]
    return train, test


def write_jsonl_gz(entries: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"  [manifest] {len(entries):3d} → {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="KWS 数据准备：lhotse manifest + tokens + keywords")
    parser.add_argument(
        "--data-root", type=Path,
        default=Path("/mnt/d/AI/data/kws/bt-en"),
        help="数据根（Windows: D:/AI/data/kws/bt-en）",
    )
    parser.add_argument(
        "--test-ratio", type=float, default=0.2,
        help="测试集比例（默认 0.2）",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="随机种子",
    )
    args = parser.parse_args()

    data_root: Path = args.data_root
    if not data_root.exists():
        print(f"ERROR: 数据根不存在: {data_root}", file=sys.stderr)
        return 1

    pos_jsonl = data_root / "positive.jsonl"
    neg_jsonl = data_root / "negative.jsonl"
    if not pos_jsonl.exists() or not neg_jsonl.exists():
        print(f"ERROR: 缺 manifest（{pos_jsonl} 或 {neg_jsonl}）", file=sys.stderr)
        print("  先在 Windows 侧跑 record_kws_corpus.py", file=sys.stderr)
        return 1

    pos = load_manifest(pos_jsonl)
    neg = load_manifest(neg_jsonl)
    print(f"  [load] positive={len(pos)}, negative={len(neg)}")
    if len(pos) < 10 or len(neg) < 30:
        print(f"WARN: 数据偏少（pos={len(pos)}, neg={len(neg)}），建议正样本≥30, 负样本≥100")

    pos_train, pos_test = split_train_test(pos, args.test_ratio, args.seed)
    neg_train, neg_test = split_train_test(neg, args.test_ratio, args.seed)
    print(f"  [split] pos train={len(pos_train)} test={len(pos_test)}")
    print(f"  [split] neg train={len(neg_train)} test={len(neg_test)}")

    manifests_dir = data_root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl_gz(pos_train, manifests_dir / "positive_train.jsonl.gz")
    write_jsonl_gz(pos_test, manifests_dir / "positive_test.jsonl.gz")
    write_jsonl_gz(neg_train, manifests_dir / "negative_train.jsonl.gz")
    write_jsonl_gz(neg_test, manifests_dir / "negative_test.jsonl.gz")

    write_tokens(manifests_dir / "tokens.txt")
    write_keywords(manifests_dir / "keywords.txt")

    print()
    print("  [done] 下一步：跑 train_kws.py")
    print(f"    /home/ku/kws-train/bin/python /mnt/d/AI/workspace/JoyAI-VL-Interaction-main/services/kws-training/train_kws.py \\")
    print(f"        --manifests-dir {manifests_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())