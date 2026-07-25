# SPDX-License-Identifier: Apache-2.0
"""Standalone real-machine verification for NVIDIA NIM ``baai/bge-m3`` recall.

Run with a real key:

    NVIDIA_API_KEY=nvapi-xxx python tools/verify_nvidia_recall.py

Prints a human-readable report and exits non-zero if the Chinese recall
acceptance criterion fails. Mirrors ``tests/test_nvidia_real_recall.py`` but
formatted for manual runs / demos.
"""

from __future__ import annotations

import os
import sys

import numpy as np
from memory_store.embedder import BgeM3Embedder, cosine_similarity

CHINESE_DOCS = {
    "malenia": "玛莲妮亚是化圣雪原的圣树boss，使用水鸟乱舞，弱火属性与出血。",
    "radahn": "拉塔恩是盖利德红狮子城的boss，使用重力魔法与陨石攻击。",
    "moonveil": "名刀月隐是智力流派太刀，战技为隙间月影，适合法师使用。",
    "erdtree": "黄金树是交界地的中心，是玛莉卡女王的神祇居所。",
}
CHINESE_QUERIES = {
    "玛莲妮亚怎么打": "malenia",
    "法师应该拿什么武器": "moonveil",
    "红狮子城的boss是谁": "radahn",
    "交界地的中心是什么": "erdtree",
}


def main() -> int:
    """Run the real-machine NVIDIA bge-m3 Chinese recall check; non-zero on failure."""
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        print("[FAIL] NVIDIA_API_KEY is not set. Cannot run real-machine verification.")
        return 2

    print("=" * 64)
    print(" NVIDIA NIM baai/bge-m3 — real-machine vector recall check")
    print("=" * 64)

    emb = BgeM3Embedder(provider="nvidia", timeout=60.0)
    print(f" provider : {emb.provider}")
    print(f" api_base : {emb.api_base}")
    print(f" model    : {emb.model}")
    print(f" dim      : {emb.dim}")

    health = emb.health()
    print(f" health   : {health}")
    if not health.get("ok"):
        print("[FAIL] NVIDIA health check failed.")
        return 1

    vec = emb.embed_query("测试中文向量维度与归一化")
    norm = float(np.linalg.norm(vec))
    print(f" vec shape: {vec.shape} dtype={vec.dtype} norm={norm:.4f}")
    if vec.shape != (1024,) or not (0.99 <= norm <= 1.01):
        print("[FAIL] vector shape/dtype/norm unexpected.")
        return 1

    doc_keys = list(CHINESE_DOCS.keys())
    doc_vecs = emb.embed_texts([CHINESE_DOCS[k] for k in doc_keys], is_query=False)

    print("\n--- Chinese semantic recall@1 ---")
    ok = True
    for query, expected in CHINESE_QUERIES.items():
        q_vec = emb.embed_query(query)
        ranked = sorted(
            zip(doc_keys, [cosine_similarity(q_vec, d) for d in doc_vecs]),
            key=lambda x: x[1],
            reverse=True,
        )
        top_key, top_sim = ranked[0]
        flag = "OK " if top_key == expected else "XX "
        if top_key != expected:
            ok = False
        print(f"  [{flag}] q={query!r}")
        print(f"        top-1={top_key} (sim={top_sim:.3f})  expected={expected}")
        print(f"        ranking={[(k, round(s, 3)) for k, s in ranked]}")

    if not ok:
        print("\n[FAIL] One or more Chinese queries did not recall the correct passage.")
        return 1

    print("\n[PASS] NVIDIA bge-m3 real-machine vector recall verified (Chinese samples).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
