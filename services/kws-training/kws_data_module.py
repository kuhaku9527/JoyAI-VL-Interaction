"""
KWS 自定义 lhotse 数据模块（替代 icefall 的 WenetSpeechAsrDataModule）。

读：
  /mnt/d/AI/data/kws/bt-en/manifests/positive_{train,test}.jsonl.gz
  /mnt/d/AI/data/kws/bt-en/manifests/negative_{train,test}.jsonl.gz
  /mnt/d/AI/data/kws/bt-en/manifests/tokens.txt

输出 lhotse CutSet，喂给 icefall 的 Zipformer2 训练。
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
from functools import cached_property
from pathlib import Path
from typing import List

from lhotse import CutSet, Recording
from lhotse.cut import MonoCut
from lhotse.supervision import SupervisionSegment

logger = logging.getLogger(__name__)


def _jsonl_gz_to_cuts(path: Path) -> CutSet:
    """把 Windows 侧录的 JSONL 转成 lhotse CutSet。

    输入 JSONL 格式（record_kws_corpus.py 写的）：
        {"id": "positive_0001", "audio": "/abs/path.wav",
         "duration": 1.2, "sampling_rate": 16000, "channels": 1,
         "text": "bt 在吗", "tokens": "B T z ai m a", "keyword": "bt_zai_ma"}
    """
    cuts: List[MonoCut] = []
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            audio_path = Path(e["audio"])
            rec = Recording.from_file(audio_path, recording_id=e["id"])
            # 用 rec.duration（实际 wav 时长）而不是 manifest 里的 e["duration"]
            # 避免 manifest 与 wav 时长不一致导致 DurationMismatchError
            cut = MonoCut(
                id=e["id"],
                start=0.0,
                duration=rec.duration,
                channel=0,
                recording=rec,
                supervisions=[
                    SupervisionSegment(
                        id=e["id"],
                        recording_id=e["id"],
                        start=0.0,
                        duration=e["duration"],
                        text=e.get("text", ""),
                        language="Chinese",
                        custom={"tokens": e.get("tokens", "").split(),
                                "keyword": e.get("keyword", "")},
                    )
                ],
            )
            cuts.append(cut)
    return CutSet.from_cuts(cuts)


class KwsAsrDataModule:
    """自定义 KWS 数据模块（替代 icefall 的 WenetSpeechAsrDataModule）。"""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.manifests_dir = Path(args.manifests_dir)
        if not self.manifests_dir.exists():
            raise FileNotFoundError(f"manifests_dir 不存在: {self.manifests_dir}")

    @cached_property
    def train_cuts(self) -> CutSet:
        logger.info("About to get train cuts (positive + negative)")
        pos = _jsonl_gz_to_cuts(self.manifests_dir / "positive_train.jsonl.gz")
        neg = _jsonl_gz_to_cuts(self.manifests_dir / "negative_train.jsonl.gz")
        combined = CutSet.from_cuts(list(pos) + list(neg))
        logger.info(f"  pos_train={len(pos)}, neg_train={len(neg)}, total={len(combined)}")
        return combined

    @cached_property
    def valid_cuts(self) -> CutSet:
        logger.info("About to get valid cuts (positive test)")
        return _jsonl_gz_to_cuts(self.manifests_dir / "positive_test.jsonl.gz")

    @cached_property
    def test_cuts(self) -> CutSet:
        logger.info("About to get test cuts (positive + negative test)")
        pos = _jsonl_gz_to_cuts(self.manifests_dir / "positive_test.jsonl.gz")
        neg = _jsonl_gz_to_cuts(self.manifests_dir / "negative_test.jsonl.gz")
        return CutSet.from_cuts(list(pos) + list(neg))

    def train_dataloaders(
        self,
        cuts: CutSet,
        sampler_state_dict=None,
    ):
        from lhotse.dataset import K2SpeechRecognitionDataset
        from lhotse.dataset.sampling import SimpleCutSampler
        from torch.utils.data import DataLoader
        sampler = SimpleCutSampler(
            cuts,
            max_duration=self.args.max_duration,
            shuffle=True,
        )
        if sampler_state_dict is not None:
            sampler.load_state_dict(sampler_state_dict)
        return DataLoader(
            K2SpeechRecognitionDataset(),
            sampler=sampler,
            batch_size=None,
            num_workers=self.args.num_workers,
        )

    def valid_dataloaders(self, cuts_valid: CutSet):
        from lhotse.dataset import K2SpeechRecognitionDataset
        from lhotse.dataset.sampling import SimpleCutSampler
        from torch.utils.data import DataLoader
        sampler = SimpleCutSampler(
            cuts_valid, max_duration=self.args.max_duration, shuffle=False,
        )
        return DataLoader(
            K2SpeechRecognitionDataset(),
            sampler=sampler,
            batch_size=None,
            num_workers=self.args.num_workers,
        )
