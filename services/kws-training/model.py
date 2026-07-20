"""
KWS 模型：Zipformer2 (icefall) + 输入投影 + CTC head + Joiner head。

训练 = CTC loss + Joiner (per-frame CE) loss:
  - CTC: encoder_out → ctc_head → CTC loss (audio-level supervision)
  - Joiner: encoder_out + decoder_emb → joiner → per-frame CE (frame-level supervision,
    让 joiner 学会在 BT 帧输出 B/T token, 其他帧输出 <blk>)

导出时包成 sherpa-onnx Transducer 三件套 (decoder 和 joiner 复用训练权重):
  - encoder.onnx: Zipformer2 流式 (cached states + embed_states + processed_lens)
  - decoder.onnx: nn.Embedding lookup (训练后的 joiner_decoder)
  - joiner.onnx: nn.Linear (训练后的 joiner) rank-2 单帧接口

约定：
  - fbank 输入: (B, T, 80) → 投影 → (T, B, encoder_dim[0]) → Zipformer → (T', B, max(encoder_dim))
  - CTC head: linear(max_dim → vocab) → (B, T', V)
  - Joiner: concat(encoder_out, decoder_emb) → linear → (B, T', V)
  - decoder_dim = max(ENCODER_DIMS) = 512 (与 sherpa-onnx 参考 joiner_dim 风格一致)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent / "icefall_src"))
from zipformer import Zipformer2

logger = logging.getLogger(__name__)


# 小一圈配置（适合 50+200 小数据集；过大反而过拟合）
# 首维 128 是 sherpa-onnx KWS 硬要求（GetEncoderInitStates 写死 embed_states shape=(1,128,3,19)）
# Joiner per-frame cross-entropy 的类别权重 (vocab order: <blk>=0 <sos/eos>=1 <unk>=2 B=3 T=4 _=5).
# 关键: B/T 是正样本仅有的非空信号, blank 是负样本主导的 98% 帧.
# 不加权重 -> joiner 把所有 token 都压成 blank (FAR 0% / recall 0%).
# 加权策略: blank 0.01x (几乎忽略), B/T 50x (强监督), 其他 1x.
# 这样 43 段正样本 x 2 帧 = 86 个非空信号不会被 160x50 帧的 blank 淹没.
JOINER_CLASS_WEIGHT = (0.01, 1.0, 1.0, 50.0, 50.0, 1.0)

ENCODER_DIMS = (128, 256, 384, 512, 384, 256)
NUM_LAYERS = (1, 1, 1, 1, 1, 1)  # sherpa-onnx 1.13.4 KWS + icefall Zipformer2 multi-layer trace bug (PR #2086 修但未合 stable), 暂用单层
DOWNSAMPLING = (1, 2, 4, 8, 4, 2)
FEEDFORWARD = (256, 384, 512, 768, 512, 384)
NUM_HEADS = (4, 4, 4, 8, 4, 4)


class KwsModel(nn.Module):
    """Zipformer2 + CTC head，专用于 KWS。"""

    def __init__(
        self,
        num_features: int = 80,
        vocab_size: int = 200,
        causal: bool = True,
    ):
        super().__init__()
        # 输入投影: 80-mel fbank → encoder_dim[0]
        self.input_proj = nn.Linear(num_features, ENCODER_DIMS[0])
        # Zipformer2 主体
        self.encoder = Zipformer2(
            output_downsampling_factor=2,
            downsampling_factor=DOWNSAMPLING,
            encoder_dim=ENCODER_DIMS,
            num_encoder_layers=NUM_LAYERS,
            encoder_unmasked_dim=tuple(d // 2 for d in ENCODER_DIMS),
            query_head_dim=32,
            value_head_dim=12,
            pos_head_dim=4,
            pos_dim=48,
            num_heads=NUM_HEADS,
            feedforward_dim=FEEDFORWARD,
            cnn_module_kernel=(15, 15, 7, 7, 7, 15),
            causal=causal,
            chunk_size=[-1],
            left_context_frames=[-1],
        )
        encoder_out_dim = max(ENCODER_DIMS)  # 512
        # CTC head（audio-level supervision）
        self.ctc_head = nn.Linear(encoder_out_dim, vocab_size)
        # Joiner head: decoder_emb + joiner linear
        # decoder_dim = encoder_out_dim (与 sherpa-onnx 参考 joiner_dim 风格一致, 避免 ONNX 导出 dim 不一致)
        self.decoder_dim = encoder_out_dim  # 512
        # 单 token BOS embedding, 推理时 y=[0,0] sum 后输出 2 * emb(0)
        self.joiner_decoder = nn.Embedding(1, self.decoder_dim)
        # joiner linear: concat(encoder_out, decoder_out) → vocab
        self.joiner = nn.Linear(encoder_out_dim + self.decoder_dim, vocab_size)

    def forward(
        self,
        features: torch.Tensor,      # (B, T, 80)
        features_lens: torch.Tensor, # (B,)
        targets: torch.Tensor | None = None,  # flat (sum(target_lens),) or empty
        target_lens: torch.Tensor | None = None,  # (B,)
    ):
        """返回 dict: ctc_loss / joiner_loss / ctc_logits / joiner_logits / out_lens.

        targets=None 时 (推理模式) 只返回 logits, 无 loss.
        """
        # fbank (B, T, F) → (T, B, F) → 投影 → (T, B, encoder_dim[0])
        x = features.transpose(0, 1)
        x = self.input_proj(x)
        # Zipformer
        encoder_out, encoder_out_lens = self.encoder(x, features_lens)
        # encoder_out: (T', B, max_dim) → (B, T', max_dim)
        e = encoder_out.transpose(0, 1)
        B, T_prime = e.size(0), e.size(1)

        # ===== CTC head =====
        ctc_logits = self.ctc_head(e)  # (B, T', V)
        ctc_loss = None
        if targets is not None and target_lens is not None and targets.numel() > 0:
            log_probs = F.log_softmax(ctc_logits, dim=-1).transpose(0, 1)  # (T', B, V)
            ctc_loss = F.ctc_loss(
                log_probs, targets, encoder_out_lens, target_lens,
                blank=0, zero_infinity=True,
            )

        # ===== Joiner head (per-frame) =====
        # decoder_emb 是常量 (BOS), 对所有帧广播
        decoder_emb = self.joiner_decoder.weight  # (1, decoder_dim=512)
        decoder_out = decoder_emb.unsqueeze(0).expand(B, T_prime, -1)  # (B, T', 512)
        combined = torch.cat([e, decoder_out], dim=-1)  # (B, T', 1024)
        joiner_logits = self.joiner(combined)  # (B, T', V)

        joiner_loss = None
        if targets is not None and target_lens is not None:
            frame_targets = _make_frame_targets(
                targets, target_lens, encoder_out_lens, T_prime, B, blank_id=0,
            )  # (B, T_prime), ignore_index=-100
            # 类别权重: blank 0.01x, B/T 50x (JOINER_CLASS_WEIGHT 注释见文件顶部)
            # reduction="sum" 而非 "mean", 让每个 B/T 帧全力贡献, 不被空帧平均稀释
            weight = torch.tensor(JOINER_CLASS_WEIGHT, dtype=joiner_logits.dtype,
                                  device=joiner_logits.device)
            joiner_loss = F.cross_entropy(
                joiner_logits.permute(0, 2, 1),  # (B, V, T_prime) for F.cross_entropy
                frame_targets,
                weight=weight,
                ignore_index=-100,
                reduction="sum",
            )
            # 归一化: 除以 batch 中正样本数 (防止 sum 比 ctc_loss 大几个数量级)
            n_pos = max(1, int((target_lens > 0).sum().item()))
            joiner_loss = joiner_loss / n_pos

        return {
            'ctc_loss': ctc_loss,
            'joiner_loss': joiner_loss,
            'ctc_logits': ctc_logits,
            'joiner_logits': joiner_logits,
            'out_lens': encoder_out_lens,
        }

    def forward_joiner(
        self,
        encoder_out: torch.Tensor,  # (B, T, max_dim)
        decoder_out: torch.Tensor,  # (B, T, decoder_dim) 或 (B, 1, decoder_dim)
    ) -> torch.Tensor:
        """导出时用：模拟 joiner。decoder_out 广播到 encoder_out 的 T。"""
        if decoder_out.dim() == 2:
            decoder_out = decoder_out.unsqueeze(1)  # (B, 1, D)
        T = encoder_out.size(1)
        if decoder_out.size(1) == 1:
            decoder_out = decoder_out.expand(-1, T, -1)
        combined = torch.cat([encoder_out, decoder_out], dim=-1)
        return self.joiner(combined)

def _make_frame_targets(
    targets: torch.Tensor,       # (sum(target_lens),)
    target_lens: torch.Tensor,    # (B,)
    out_lens: torch.Tensor,       # (B,) 实际 encoder 输出帧数
    T_max: int,
    B: int,
    blank_id: int = 0,
) -> torch.Tensor:
    """为每个样本生成每帧目标 token id.

    正样本 (target_len >= 2, 比如 [B, T]):
      B 放在 1/3 位置, T 放在 2/3 位置, 其余帧 <blk>
    负样本 (target_len == 0):
      所有帧 <blk>

    Returns: (B, T_max) int64, ignore_index=-100 (用于 cross_entropy 跳过).
    """
    frame_targets = torch.full((B, T_max), -100, dtype=torch.long, device=targets.device)
    blank = torch.tensor(blank_id, dtype=torch.long, device=targets.device)

    offset = 0
    for b in range(B):
        L = int(target_lens[b].item())
        T_b = int(out_lens[b].item()) if out_lens is not None else T_max
        T_b = min(T_b, T_max)
        if T_b <= 0:
            continue

        if L == 0:
            # 负样本: 全部 blank
            frame_targets[b, :T_b] = blank
        else:
            sample_targets = targets[offset:offset + L]
            offset += L
            # L 个 token 分布在 T_b 帧内, 取 T_b//3, 2*T_b//3 两个位置
            if L >= 1 and T_b >= 2:
                # 第一个 token 放在 ~1/3
                t1 = max(0, min(T_b - L, T_b // 3))
                frame_targets[b, t1] = sample_targets[0]
            if L >= 2 and T_b >= 4:
                t2 = max(t1 + 1 if L >= 1 else 0, min(T_b - 1, 2 * T_b // 3))
                frame_targets[b, t2] = sample_targets[1]
            # 剩余帧 blank
            for t in range(T_b):
                if frame_targets[b, t].item() == -100:
                    frame_targets[b, t] = blank
    return frame_targets
