# SPDX-License-Identifier: Apache-2.0
"""verify_embedding_parity.py — space-consistency gate (ADR-0012).

The dual-mode design (local ingest + hosted-API recall) is only valid if the
local weights and the hosted ``BAAI/bge-m3`` produce the SAME vector space.
This script embeds identical texts through both paths and requires cosine
similarity > 0.999 per pair. Run before first production use:

    export SILICONFLOW_API_KEY=...
    python tools/verify_embedding_parity.py

Exit code 0 = parity confirmed (dual-mode safe); 1 = parity failed (pick ONE
side for both ingest and recall, never mix).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from memory_store.embedder import BgeM3Embedder, EmbedderError, cosine_similarity

_THRESHOLD = 0.999
_SAMPLES = [
    "火焰巨人是艾尔登法环中位于巨人山顶的 Boss，弱打击属性武器。",
    "The Fire Giant is a Legend Boss in Elden Ring, weak to strike damage.",
    "玛莲妮亚的水鸟乱舞需要连续翻滚四次躲避。",
]


def main() -> int:
    api = BgeM3Embedder(provider="siliconflow")
    local = BgeM3Embedder(provider="local")
    try:
        api_vecs = api.embed_texts(_SAMPLES)
    except EmbedderError as exc:
        print(f"API path failed: {exc}", file=sys.stderr)
        return 2
    try:
        local_vecs = local.embed_texts(_SAMPLES)
    except EmbedderError as exc:
        print(f"local path failed: {exc}", file=sys.stderr)
        return 2

    worst = 1.0
    for i, (a, b) in enumerate(zip(api_vecs, local_vecs)):
        sim = cosine_similarity(np.asarray(a), np.asarray(b))
        worst = min(worst, sim)
        status = "OK" if sim >= _THRESHOLD else "MISMATCH"
        print(f"[{status}] sample {i}: cosine={sim:.6f}")

    if worst >= _THRESHOLD:
        print(f"parity confirmed (worst={worst:.6f} >= {_THRESHOLD}); dual-mode is safe.")
        return 0
    print(
        f"parity FAILED (worst={worst:.6f} < {_THRESHOLD}). "
        "Use ONE side for both ingest and recall; do not mix.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
