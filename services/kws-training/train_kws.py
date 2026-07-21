"""
KWS 自训入口：CTC + Zipformer2 + 自定义 lhotse 数据。

数据：
  /mnt/d/AI/data/kws/bt-en/manifests/{positive,negative}_{train,test}.jsonl.gz
  /mnt/d/AI/data/kws/bt-en/manifests/tokens.txt

输出：
  /mnt/d/AI/data/kws/bt-en/exp/  (checkpoints)
  /mnt/d/AI/models/sherpa-onnx/models/kws/bt-en/  (ONNX, export 后)

用法（WSL2 内）：
  source ~/kws-train/bin/activate
  python /mnt/d/AI/workspace/JoyAI-VL-Interaction-main/services/kws-training/train_kws.py \\
      --manifests-dir /mnt/d/AI/data/kws/bt-en/manifests \\
      --exp-dir /mnt/d/AI/data/kws/bt-en/exp \\
      --num-epochs 30
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
import torchaudio
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).parent))
from kws_data_module import KwsAsrDataModule
from model import KwsModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kws-train")


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--manifests-dir", type=Path, required=True)
    p.add_argument("--exp-dir", type=Path, required=True)
    p.add_argument("--num-epochs", type=int, default=30)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--num-workers", type=int, default=0)
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--save-every", type=int, default=5)
    p.add_argument("--tokens-file", type=Path, default=None)
    return p.parse_args()


def load_tokens(tokens_file: Path) -> list[str]:
    tokens = []
    with tokens_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tokens.append(line.split()[0])
    return tokens


def compute_fbank(wav: torch.Tensor, sr: int = 16000, n_mels: int = 80) -> torch.Tensor:
    """wav: (T,) float32 → fbank: (T_frames, n_mels)"""
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    feat = torchaudio.compliance.kaldi.fbank(
        wav,
        htk_compat=True,
        sample_frequency=sr,
        use_energy=False,
        window_type="hanning",
        num_mel_bins=n_mels,
        dither=0.0,
        frame_shift=10,
        frame_length=25,
    )
    # CMN
    feat = feat - feat.mean(dim=0, keepdim=True)
    return feat


class FbankDataset(torch.utils.data.Dataset):
    """从 lhotse CutSet 读 wav → fbank。"""

    def __init__(self, cuts, token_table: list[str], n_mels: int = 80):
        self.cuts = list(cuts)
        self.token_table = token_table
        self.tok2id = {t: i for i, t in enumerate(token_table)}
        self.n_mels = n_mels

    def __len__(self):
        return len(self.cuts)

    def __getitem__(self, idx):
        cut = self.cuts[idx]
        audio = cut.load_audio()  # ndarray (channels, samples)
        sr = cut.sampling_rate
        if audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)
        wav = torch.from_numpy(audio).squeeze(0).float()
        fbank = compute_fbank(wav, sr, self.n_mels)  # (T, n_mels)
        sup = cut.supervisions[0]
        toks = sup.custom.get("tokens", [])
        target_ids = [self.tok2id.get(t, 2) for t in toks]  # 2=<unk>
        return fbank, torch.tensor(target_ids, dtype=torch.long), cut.id


def collate(batch):
    fbanks, targets, ids = zip(*batch)
    feat_lens = torch.tensor([f.shape[0] for f in fbanks], dtype=torch.long)
    max_t = max(f.shape[0] for f in fbanks)
    n_mels = fbanks[0].shape[1]
    feats = torch.zeros(len(fbanks), max_t, n_mels)
    for i, f in enumerate(fbanks):
        feats[i, : f.shape[0]] = f
    target_lens = torch.tensor([len(t) for t in targets], dtype=torch.long)
    flat_targets = torch.cat([t for t in targets if len(t) > 0]) if any(len(t) > 0 for t in targets) else torch.tensor([], dtype=torch.long)
    return feats, feat_lens, flat_targets, target_lens, ids


def evaluate(model, dl, device, loss_fn):
    model.eval()
    total_loss = 0.0
    n_batches = 0
    with torch.no_grad():
        for feats, feat_lens, targets, target_lens, _ in dl:
            feats = feats.to(device)
            targets = targets.to(device)
            out = model(feats, feat_lens, targets if targets.numel() > 0 else None,
                        target_lens)
            ctc_l = out['ctc_loss']
            join_l = out['joiner_loss']
            if ctc_l is None and join_l is None:
                loss = torch.tensor(0.0, device=device)
            elif ctc_l is None:
                loss = join_l
            elif join_l is None:
                loss = ctc_l
            else:
                loss = ctc_l + join_l
            total_loss += loss.item() if loss.requires_grad is False or True else 0.0
            n_batches += 1
    return total_loss / max(n_batches, 1)


def main():
    args = get_args()
    torch.manual_seed(args.seed)
    args.exp_dir.mkdir(parents=True, exist_ok=True)

    tokens_file = args.tokens_file or (args.manifests_dir / "tokens.txt")
    token_table = load_tokens(tokens_file)
    logger.info(f"Loaded {len(token_table)} tokens from {tokens_file}")
    vocab_size = len(token_table)

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    logger.info(f"Device: {device}")

    dm = KwsAsrDataModule(args)
    train_cuts = dm.train_cuts()
    valid_cuts = dm.valid_cuts()
    logger.info(f"train_cuts={len(train_cuts)}, valid_cuts={len(valid_cuts)}")

    train_ds = FbankDataset(train_cuts, token_table)
    valid_ds = FbankDataset(valid_cuts, token_table)
    train_dl = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
        collate_fn=collate, num_workers=args.num_workers,
    )
    valid_dl = DataLoader(
        valid_ds, batch_size=args.batch_size, shuffle=False,
        collate_fn=collate, num_workers=args.num_workers,
    )

    model = KwsModel(vocab_size=vocab_size).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    logger.info(f"Model params: {n_params:,} ({n_params / 1e6:.1f}M)")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.num_epochs)
    ctc_loss = nn.CTCLoss(blank=0, zero_infinity=True)

    best_valid_loss = float("inf")
    for epoch in range(1, args.num_epochs + 1):
        model.train()
        total_loss = 0.0
        n_batches = 0
        t0 = time.time()
        for feats, feat_lens, targets, target_lens, _ in train_dl:
            feats = feats.to(device)
            targets = targets.to(device)
            optimizer.zero_grad()
            out = model(feats, feat_lens, targets if targets.numel() > 0 else None,
                        target_lens)
            ctc_l = out['ctc_loss']
            join_l = out['joiner_loss']
            if ctc_l is None and join_l is None:
                # 全负样本 batch: skip (joiner loss 仍会算 blank 但没监督信号, 让 loss=0 跳过)
                optimizer.step()
                total_loss += 0.0
                n_batches += 1
                continue
            if ctc_l is None:
                loss = join_l
            elif join_l is None:
                loss = ctc_l
            else:
                loss = ctc_l + join_l
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            total_loss += loss.item()
            n_batches += 1
        scheduler.step()
        train_loss = total_loss / max(n_batches, 1)
        valid_loss = evaluate(model, valid_dl, device, ctc_loss)
        dt = time.time() - t0
        logger.info(
            f"[epoch {epoch:3d}/{args.num_epochs}] "
            f"train={train_loss:.4f} valid={valid_loss:.4f} "
            f"lr={scheduler.get_last_lr()[0]:.2e} "
            f"({dt:.1f}s)"
        )
        if valid_loss < best_valid_loss:
            best_valid_loss = valid_loss
            ckpt = args.exp_dir / "best.pt"
            torch.save({
                "epoch": epoch,
                "model_state": model.state_dict(),
                "vocab_size": vocab_size,
                "token_table": token_table,
                "valid_loss": valid_loss,
            }, ckpt)
            logger.info(f"  [save] best → {ckpt}")
        if epoch % args.save_every == 0:
            ckpt = args.exp_dir / f"epoch-{epoch}.pt"
            torch.save({
                "epoch": epoch,
                "model_state": model.state_dict(),
                "vocab_size": vocab_size,
                "token_table": token_table,
                "valid_loss": valid_loss,
            }, ckpt)

    logger.info(f"[done] best valid_loss = {best_valid_loss:.4f}")
    logger.info(f"  下一步：python export_kws_onnx.py --ckpt {args.exp_dir / 'best.pt'}")


if __name__ == "__main__":
    main()
