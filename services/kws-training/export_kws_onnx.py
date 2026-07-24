"""
KWS 模型导出：PyTorch → sherpa-onnx KWS 流式三件套。

输出 4 个文件（替换 zh-en-3M）：
  encoder.onnx  decoder.onnx  joiner.onnx  tokens.txt  keywords.txt

关键约束（已通过读 sherpa-onnx 源码确认）：
- sherpa-onnx OnlineZipformer2TransducerModel 不解析 input name，只按 list 顺序调用
- 输入顺序：x, cached_*(m*6 个), embed_states, processed_lens
  其中 m = sum(NUM_LAYERS) = 13
- x 形状: (N, T, 80) - batch 在 dim 0
- cached 顺序（按 sherpa-onnx GetEncoderInitStates 逻辑）：
  for module in 6:
    for layer in NUM_LAYERS[module]:
      cached_key, cached_nonlin_attn, cached_val1, cached_val2, cached_conv1, cached_conv2
- cached_* 形状（来自 sherpa-onnx）:
  - cached_key/val1/val2:    (left_context, N, dim)  -> batch dim 1
  - cached_nonlin_attn:      (1, N, left_context, 3*embed_dim/4)  -> batch dim 1
  - cached_conv1/conv2:      (N, embed_dim, kernel/2)  -> batch dim 0
  - embed_states:            (N, first_encoder_dim, 3, 19)  -> batch dim 0
  - processed_lens:          (N,) int64  -> batch dim 0
- encoder 输出：(N, T', max_encoder_dim)
- 首维必须 128（sherpa-onnx 硬编码 embed_states 第二维）

用法（WSL2）:
  source ~/kws-train/bin/activate
  python export_kws_onnx.py \\\
      --ckpt /mnt/d/AI/data/kws/bt-en/exp/best.pt \\\
      --out-dir /mnt/d/AI/models/sherpa-onnx/models/kws/bt-en
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import List

import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).parent))
from model import DOWNSAMPLING, ENCODER_DIMS, NUM_HEADS, NUM_LAYERS, KwsModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("kws-export")


# sherpa-onnx 期望的 embed_states 形状
EMBED_STATES_FIXED_DIM2 = 128  # 必须是 first encoder_dim


def get_args():
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--chunk-size", type=int, default=16,
                   help="Zipformer2 streaming chunk size (frames). sherpa-onnx 1.13.4 KWS "
                        "only ships chunk=16 / chunk=8 pretrained models; 16 is the standard. "
                        "T at runtime = chunk_size*2 + 13 (ConvNeXt right-pad 13).")
    p.add_argument("--left-context", type=int, default=64)
    return p.parse_args()


class OnnxEncoder(nn.Module):
    """icefall 风格的 OnnxEncoder：包装 KwsModel.encoder 成 sherpa-onnx 兼容流式 ONNX。
    
    forward 输入: x, x_lens, *states
    forward 输出: encoder_out, x_lens (回传, sherpa-onnx 不用), *new_states
    """

    def __init__(self, model: KwsModel, chunk_size: int, left_context: int):
        super().__init__()
        self.input_proj = model.input_proj
        self.encoder = model.encoder
        # 配置 streaming
        self.encoder.chunk_size = [chunk_size]
        self.encoder.left_context_frames = [left_context]
        self.chunk_size = chunk_size
        self.left_context = left_context
        # joiner_dim: max(ENCODER_DIMS) - encoder 直接输出 max_dim
        self.joiner_dim = max(ENCODER_DIMS)

    def forward(self, x: torch.Tensor, *states: torch.Tensor):
        # x: (N, T, 80) -> 转为 icefall 期望的 (T, N, 80)
        x = x.transpose(0, 1).contiguous()
        # input_proj
        x = self.input_proj(x)  # (T, N, ENCODER_DIMS[0])
        T_in, B = x.size(0), x.size(1)
        # icefall KWS 约定: 实际 input T = chunk_size * 2 + 13 (ConvNeXt right-pad 13)
        #   chunk_size=16 -> T=45 (sherpa-onnx 1.13.4 KWS 默认)
        #   chunk_size=8  -> T=29
        T = T_in  # 严格等于外部传入的 T (用 main 里 dummy_x 算的)
        x_lens = torch.full((B,), T, dtype=torch.long, device=x.device)
        # mask shape (B, max_left + T) per icefall module 期望
        max_left = self.left_context  # = 64
        mask = torch.zeros(B, max_left + T, dtype=torch.bool, device=x.device)
        # streaming forward: 取前 78 个 cached states 喂给它
        # 后两位是 sherpa-onnx 特殊的 embed_states + processed_lens, 不在 icefall 流程里
        n_cached = sum(NUM_LAYERS) * 6  # = 78
        cached_states = list(states[:n_cached])
        out, out_lens, new_cached = self.encoder.streaming_forward(
            x, x_lens, cached_states, src_key_padding_mask=mask
        )
        # encoder 输出 T' = (T + 1) // 2 (icefall downsample_output 2x)
        #   chunk_size=16, T=45 -> T'=23
        #   chunk_size=32, T=77 -> T'=39
        # sherpa-onnx 不强校验 T', 它会逐帧 consume
        # out: (T', N, max_dim) -> (N, T', max_dim)
        out = out.transpose(0, 1).contiguous()
        # embed_states / processed_lens: sherpa-onnx 期望 80 个新 states
        # new_embed_states = embed_states (passthrough)
        # new_processed_lens = processed_lens + (T // 2)  因为 output 是 2x downsample
        embed_states_in = states[n_cached]      # (N, 128, 3, 19)
        processed_lens_in = states[n_cached + 1] # (N,) int64
        new_embed_states = embed_states_in
        # 增量 = output 长度 = (T + 1) // 2 (icefall downsample_output 2x)
        # 实际 icefall: lengths = (x_lens + 1) // 2
        new_processed_lens = processed_lens_in + (T + 1) // 2
        # output 顺序: encoder_out, new_cached_*(78), new_embed_states, new_processed_lens
        return (out,) + tuple(new_cached) + (new_embed_states, new_processed_lens)


class OnnxDecoder(nn.Module):
    """标准 transducer decoder: y (N, context_size) int64 -> decoder_out (N, decoder_dim).

    复用训练后的 KwsModel.joiner_decoder (1 x decoder_dim 单 BOS embedding).
    推理时 y 永远是 [0, 0] (BOS), 输出是 2 * embed(0).

    维度约定:
      - decoder_dim = max(ENCODER_DIMS) = 512 (= encoder_out_dim), 跟 KwsModel.decoder_dim 对齐
      - 与 sherpa-onnx 参考 decoder_out 维度匹配 (rank-2 单帧接口)
    """

    def __init__(self, model: KwsModel):
        super().__init__()
        self.decoder_dim = model.decoder_dim
        self.vocab_size = model.ctc_head.out_features
        # ONNX 导出需要 vocab_size 行 (sherpa-onnx 会传任意 token id)
        # 把训练后的 1 行 BOS emb 复制 vocab_size 次 (KWS 推理永远走 BOS 路径)
        self.embed = nn.Embedding(self.vocab_size, self.decoder_dim)
        with torch.no_grad():
            bos = model.joiner_decoder.weight  # (1, decoder_dim)
            self.embed.weight.copy_(bos.expand(self.vocab_size, -1))

    def forward(self, y: torch.Tensor):
        # y: (N, 2) int64
        emb = self.embed(y)  # (N, 2, decoder_dim)
        return emb.sum(dim=1)  # (N, decoder_dim)


class OnnxJoiner(nn.Module):
    """标准 transducer joiner: encoder_out + decoder_out -> vocab logits.

    复用训练后的 KwsModel.joiner (Linear(encoder_dim + decoder_dim, vocab)).

    sherpa-onnx KWS 按 T 拆单帧调用 (transducer-keyword-decoder.cc:59-82):
        for t in 0..T: RunJoiner(GetEncoderOutFrame(t), decoder_out)
    所以 encoder_out 是单帧 (N, encoder_dim) rank 2, 不是 (N, T, encoder_dim).

    维度约定:
      - 输入: encoder_out (N, encoder_dim) + decoder_out (N, decoder_dim)
      - 输出: logit (N, vocab)
      - encoder_dim == decoder_dim == max(ENCODER_DIMS) == 512
      - 与 sherpa-onnx 参考 joiner 输入维度匹配 (rank-2 单帧接口)
    """

    def __init__(self, model: KwsModel):
        super().__init__()
        self.encoder_dim = max(ENCODER_DIMS)
        self.decoder_dim = model.decoder_dim
        self.vocab_size = model.ctc_head.out_features
        if model.joiner.in_features != self.encoder_dim + self.decoder_dim:
            raise ValueError(
                f"model.joiner.in_features={model.joiner.in_features} != "
                f"encoder_dim({self.encoder_dim}) + decoder_dim({self.decoder_dim})"
            )
        # 直接复用训练后的 joiner Linear (ONNX export 时 torch 会自动拷贝权重)
        self.linear = model.joiner

    def forward(self, encoder_out: torch.Tensor, decoder_out: torch.Tensor):
        if encoder_out.dim() == 3:
            encoder_out = encoder_out.squeeze(1)
        if decoder_out.dim() == 3:
            decoder_out = decoder_out.squeeze(1)
        combined = torch.cat([encoder_out, decoder_out], dim=-1)  # (N, encoder_dim+decoder_dim)
        return self.linear(combined)  # (N, vocab)


def add_metadata(onnx_path: Path, meta: dict) -> None:
    import onnx
    from onnx import StringStringEntryProto
    m = onnx.load(str(onnx_path))
    existing = {p.key: p.value for p in m.metadata_props}
    existing.update(meta)
    del m.metadata_props[:]
    for k, v in existing.items():
        m.metadata_props.append(StringStringEntryProto(key=k, value=str(v)))
    onnx.save(m, str(onnx_path))


def compute_state_shapes(model: KwsModel, chunk_size: int, left_context: int):
    """按 sherpa-onnx GetEncoderInitStates 顺序，返回 (names, shapes, init_values)."""
    enc = model.encoder
    names: List[str] = []
    shapes: List[List[int]] = []
    inits: List[torch.Tensor] = []

    init_states = enc.get_init_states(batch_size=1)
    for i, s in enumerate(init_states):
        names.append(f"state_{i}")
        shapes.append(list(s.shape))
        inits.append(s.detach().clone())

    # embed_states: (1, 128, 3, 19) - sherpa-onnx 硬编码
    embed_shape = [1, EMBED_STATES_FIXED_DIM2, 3, 19]
    names.append("embed_states")
    shapes.append(embed_shape)
    inits.append(torch.zeros(embed_shape))

    # processed_lens: (1,) int64
    names.append("processed_lens")
    shapes.append([1])
    inits.append(torch.zeros([1], dtype=torch.long))

    return names, shapes, inits


def main():
    args = get_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"加载 checkpoint: {args.ckpt}")
    ckpt = torch.load(args.ckpt, map_location="cpu", weights_only=False)
    vocab_size = ckpt["vocab_size"]
    logger.info(f"  epoch={ckpt.get('epoch', '?')}  vocab_size={vocab_size}  valid_loss={ckpt.get('valid_loss', '?')}")

    model = KwsModel(vocab_size=vocab_size)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    logger.info("模型加载完成")

    # ===== 用 icefall 标准流程: convert_scaled_to_non_scaled =====
    # 这一步把 Balancer/Dropout3/ChunkCausalDepthwiseConv1d 等替换成 ONNX-friendly 版
    # icefall multi-layer 2,2,3,4,3,2 (=16层) 兼容的关键
    from icefall_src.scaling_converter import convert_scaled_to_non_scaled
    convert_scaled_to_non_scaled(model, inplace=True)
    logger.info("  [scaling_converter] convert_scaled_to_non_scaled done")

    # ===== Monkey-patch: 强制 SimpleDownsample 走 padding 分支 =====
    # 原因: causal=True + torch.jit.is_tracing() 时跳过 padding, 导致 reshape 失败
    # 这是 icefall 已知 KWS 导出坑
    # 用 model 的 import chain 触发 sys.path, 然后从 zipformer 模块拿 SimpleDownsample
    import importlib
    sd_module = importlib.import_module("zipformer")  # 已被 model.py 加载过
    SimpleDownsample = sd_module.SimpleDownsample
    def _patched_simple_downsample_forward(self, src):
        # 强制走 padding 分支 (不依赖 causal/is_tracing)
        (seq_len, batch_size, in_channels) = src.shape
        ds = self.downsample
        d_seq_len = (seq_len + ds - 1) // ds
        pad = d_seq_len * ds - seq_len
        if pad > 0:
            src_extra = src[src.shape[0] - 1 :].expand(pad, src.shape[1], src.shape[2])
            src = torch.cat((src, src_extra), dim=0)
        src = src.reshape(d_seq_len, ds, batch_size, in_channels)
        weights = self.bias.softmax(dim=0).unsqueeze(-1).unsqueeze(-1)
        return (src * weights).sum(dim=1)
    SimpleDownsample.forward = _patched_simple_downsample_forward
    logger.info("  [monkey-patch] SimpleDownsample.forward 强制 padding")

    joiner_dim = max(ENCODER_DIMS)
    decoder_dim = model.decoder_dim
    logger.info(f"  joiner_dim={joiner_dim}  decoder_dim={decoder_dim}")
    logger.info(f"  ENCODER_DIMS={ENCODER_DIMS}  NUM_LAYERS={NUM_LAYERS}")
    total_cached = sum(NUM_LAYERS) * 6
    logger.info(f"  total cached states = {total_cached} ({sum(NUM_LAYERS)} layers x 6)")

    # ===== 1) encoder (流式) =====
    logger.info("[1/3] 导出 encoder (流式)...")
    enc_wrapper = OnnxEncoder(model, args.chunk_size, args.left_context)

    # 状态名/形状
    state_names, state_shapes, state_inits = compute_state_shapes(model, args.chunk_size, args.left_context)
    logger.info(f"  状态数 = {len(state_names)} (cached={total_cached} + embed_states + processed_lens)")

    # dummy 输入: icefall KWS 约定 T = chunk_size*2 + 13
    #   chunk_size=16 (default) -> T=45 (sherpa-onnx KWS 唯一官方支持的 chunk)
    PAD_LENGTH = 7 + 2 * 3  # 13
    T = args.chunk_size * 2 + PAD_LENGTH
    B = 1
    n_mels = 80
    dummy_x = torch.randn(B, T, n_mels)  # (N, T, 80) = (1, 77, 80)

    encoder_inputs = [dummy_x] + state_inits
    encoder_input_names = ["x"] + state_names
    # 81 outputs: encoder_out + 78 new_state + new_embed_states + new_processed_lens
    encoder_output_names = ["encoder_out"] + [f"new_state_{i}" for i in range(len(state_names))]
    # 最后两个 output 必须用具体名字, sherpa-onnx 第二次跑时按 output order 喂 input order,
    # input[79]=processed_lens input[80]=embed_states 实际顺序按 ONNX graph.input
    # 所以我们 output 末尾两个名字也要对应, 但 sherpa-onnx 不看名字只按 index 取, 所以这里
    # 名字写什么都行, 关键是数量对
    # total outputs = 1 (encoder_out) + 1 (encoder_out) + n_cached (new_state_X) + 2 (new_embed_states, new_processed_lens)
    n_cached = sum(NUM_LAYERS) * 6
    expected_outputs = 1 + n_cached + 2  # encoder_out + new_states + 2 passthrough
    if len(encoder_output_names) != expected_outputs:
        raise ValueError(f"output_names should be {expected_outputs}, got {len(encoder_output_names)}")
    # 最后两个 output 是 new_embed_states 和 new_processed_lens (在 forward 里 return)
    encoder_output_names[-2] = "new_embed_states"
    encoder_output_names[-1] = "new_processed_lens"

    # dynamic axes: 按 sherpa-onnx 喂入的实际 shape 标记 batch dim
    # 参考 sherpa-onnx GetEncoderInitStates 创建的 shape:
    #   cached_key/val1/val2:      (left, 1, dim)        -> dim 1 = N
    #   cached_nonlin_attn:        (1, 1, left, 3*dim/4) -> dim 1 = N
    #   cached_conv1/conv2:        (1, dim, kernel/2)     -> dim 0 = N
    #   embed_states:              (1, 128, 3, 19)        -> dim 0 = N
    #   processed_lens:            (1,)                   -> dim 0 = N
    dynamic_axes = {
        "x": {0: "N", 1: "T"},
        "encoder_out": {0: "N", 1: "T"},
    }
    for i, shape in enumerate(state_shapes):
        sn = state_names[i]
        if "embed_states" in sn or "processed_lens" in sn:
            # (1, 128, 3, 19) 或 (1,) -> dim 0 是 batch
            dynamic_axes[sn] = {0: "N"}
            dynamic_axes[f"new_state_{i}"] = {0: "N"}
        elif len(shape) == 3 and shape[0] == 1 and shape[2] != 1:
            # (1, dim, kernel/2): cached_conv1/conv2
            # dim[0]=1 是 batch=1 的 init, dim[1]=embed_dim, dim[2]=kernel/2
            # 实际上 sherpa-onnx 喂入 (N, dim, kernel/2), batch 在 dim 0
            dynamic_axes[sn] = {0: "N"}
            dynamic_axes[f"new_state_{i}"] = {0: "N"}
        elif len(shape) == 3:
            # (left, 1, dim): cached_key/val1/val2
            # dim[0]=left (固定), dim[1]=batch, dim[2]=dim
            dynamic_axes[sn] = {1: "N"}
            dynamic_axes[f"new_state_{i}"] = {1: "N"}
        elif len(shape) == 4:
            # (1, 1, left, 3*dim/4): cached_nonlin_attn
            # dim[1]=batch, 其他固定
            dynamic_axes[sn] = {1: "N"}
            dynamic_axes[f"new_state_{i}"] = {1: "N"}
        else:
            dynamic_axes[sn] = {0: "N"}
            dynamic_axes[f"new_state_{i}"] = {0: "N"}

    encoder_path = args.out_dir / "encoder.onnx"
    logger.info(f"  → {encoder_path.name}")
    torch.onnx.export(
        enc_wrapper,
        tuple(encoder_inputs),
        str(encoder_path),
        input_names=encoder_input_names,
        output_names=encoder_output_names,
        dynamic_axes=dynamic_axes,
        opset_version=14,
        do_constant_folding=True,
        dynamo=False,
    )
    # 删除 x_lens_out（sherpa-onnx 不期望这 output）
    # 实际 sherpa-onnx 期望 output[0] = encoder_out, 其余是 states
    # 我们把 x_lens_out 放在 position 1 错了 - 应该不输出 x_lens_out
    # 但 ONNX 已导出，先 check 一遍；先打 metadata

    # encoder metadata (与 zh-en-3M 对齐)
    left_context_len_per_module = [args.left_context // k for k in DOWNSAMPLING]
    enc_meta = {
        "model_type": "zipformer2",
        "version": "1",
        "model_author": "joyai-kws-training",
        "comment": "streaming zipformer2 (custom trained, BT wake word)",
        "decode_chunk_len": str(args.chunk_size * 2),  # = 2 * chunk_size
        "T": str(args.chunk_size * 2 + PAD_LENGTH),      # = 2*chunk_size + 13, 跟 trace 一致
        "num_encoder_layers": ",".join(map(str, NUM_LAYERS)),
        "encoder_dims": ",".join(map(str, ENCODER_DIMS)),
        "cnn_module_kernels": ",".join(map(str, (15, 15, 7, 7, 7, 15))),
        "left_context_len": ",".join(map(str, left_context_len_per_module)),
        "query_head_dims": ",".join(map(str, (32,) * 6)),
        "value_head_dims": ",".join(map(str, (12,) * 6)),
        "num_heads": ",".join(map(str, NUM_HEADS)),
        "joiner_dim": str(joiner_dim),
    }
    add_metadata(encoder_path, enc_meta)
    logger.info(f"  metadata: model_type=zipformer2, encoder_dims={enc_meta['encoder_dims']}")

    # ===== 2) decoder (no-op) =====
    logger.info("[2/3] 导出 decoder (no-op)...")
    dummy_y = torch.zeros(B, 2, dtype=torch.long)
    dec_wrapper = OnnxDecoder(model)
    decoder_path = args.out_dir / "decoder.onnx"
    logger.info(f"  → {decoder_path.name}")
    torch.onnx.export(
        dec_wrapper,
        (dummy_y,),
        str(decoder_path),
        input_names=["y"],
        output_names=["decoder_out"],
        dynamic_axes={"y": {0: "N"}, "decoder_out": {0: "N"}},
        opset_version=14,
        do_constant_folding=True,
        dynamo=False,
    )
    add_metadata(decoder_path, {
        "context_size": "2",
        "vocab_size": str(vocab_size),
    })

    # ===== 3) joiner =====
    # sherpa-onnx KWS 按 T 拆单帧调用 (transducer-keyword-decoder.cc:59-82),
    # joiner 的 encoder_out 期望 rank 2 (N, joiner_dim), 不是 (N, T, joiner_dim)
    logger.info("[3/3] 导出 joiner (rank-2 单帧)...")
    dummy_e = torch.randn(B, joiner_dim)          # (N, D)
    dummy_d = torch.randn(B, joiner_dim)          # (N, D)
    join_wrapper = OnnxJoiner(model)
    joiner_path = args.out_dir / "joiner.onnx"
    logger.info(f"  → {joiner_path.name}")
    torch.onnx.export(
        join_wrapper,
        (dummy_e, dummy_d),
        str(joiner_path),
        input_names=["encoder_out", "decoder_out"],
        output_names=["logit"],
        # encoder_out 只有 batch dim; decoder_out 只有 batch dim; logit 只有 batch dim
        dynamic_axes={"encoder_out": {0: "N"}, "decoder_out": {0: "N"}, "logit": {0: "N"}},
        opset_version=14,
        do_constant_folding=True,
        dynamo=False,
    )
    add_metadata(joiner_path, {
        "joiner_dim": str(joiner_dim),
    })

    # ===== 4) 复制 tokens + keywords =====
    src_tokens = args.ckpt.parent.parent / "manifests" / "tokens.txt"
    src_keywords = args.ckpt.parent.parent / "manifests" / "keywords.txt"
    if src_tokens.exists():
        shutil.copy(src_tokens, args.out_dir / "tokens.txt")
        logger.info("  → tokens.txt")
    if src_keywords.exists():
        shutil.copy(src_keywords, args.out_dir / "keywords.txt")
        logger.info("  → keywords.txt")

    # ===== 5) 验证 ONNX =====
    try:
        import onnx
        for name in ["encoder.onnx", "decoder.onnx", "joiner.onnx"]:
            m = onnx.load(str(args.out_dir / name))
            onnx.checker.check_model(m)
            logger.info(f"  [verify] {name} OK")
    except Exception as e:
        logger.warning(f"  [verify] ONNX check 失败: {e}")

    logger.info(f"[done] 导出完成: {args.out_dir}")
    logger.info("  下一步：用 sherpa-onnx KeywordSpotter 试加载")


if __name__ == "__main__":
    main()
