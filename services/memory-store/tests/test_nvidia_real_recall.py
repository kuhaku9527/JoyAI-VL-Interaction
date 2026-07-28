# SPDX-License-Identifier: Apache-2.0
"""Real-machine verification of NVIDIA NIM ``baai/bge-m3`` vector recall (ADR-0012).

This is the *real-API* counterpart to ``test_embedder_provider.py`` (which is
fully mocked). It exercises the actual NVIDIA NIM endpoint with a genuine
``NVIDIA_API_KEY`` and asserts that:

* the explicit ``nvidia`` provider points at the NVIDIA NIM base URL /
  ``baai/bge-m3`` model (the **default** is now ``local`` — see ADR-0012 §6
  and test_local_real_recall.py for the local-machine counterpart);
* ``health()`` returns a live OK with dim == 1024;
* embeddings are 1024-d, float32, L2-normalized (norm ≈ 1);
* a **Chinese** query semantically retrieves the correct Chinese passage
  (recall@1) — the core "向量召回" acceptance criterion;
* re-embedding identical text is stable (space-consistency rule, design §2.3);
* end-to-end sync → USearch HNSW recall returns the right wiki block for a
  Chinese query (gated on ``usearch`` being installed).

The whole module is **skipped** when ``NVIDIA_API_KEY`` is not set, so the
suite stays green in CI without secrets. To run the real check:

    NVIDIA_API_KEY=nvapi-xxx pytest tests/test_nvidia_real_recall.py -v

or run the companion script ``tools/verify_nvidia_recall.py``.
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
import pytest
from memory_store.embedder import BgeM3Embedder, cosine_similarity

# --- Chinese corpus: semantically distinct so recall@1 is unambiguous --------
_CHINESE_DOCS: dict[str, str] = {
    "malenia": "玛莲妮亚是化圣雪原的圣树boss，使用水鸟乱舞，弱火属性与出血。",
    "radahn": "拉塔恩是盖利德红狮子城的boss，使用重力魔法与陨石攻击。",
    "moonveil": "名刀月隐是智力流派太刀，战技为隙间月影，适合法师使用。",
    "erdtree": "黄金树是交界地的中心，是玛莉卡女王的神祇居所。",
}

# query -> expected top-1 doc key
_CHINESE_QUERIES: dict[str, str] = {
    "玛莲妮亚怎么打": "malenia",
    "法师应该拿什么武器": "moonveil",
    "红狮子城的boss是谁": "radahn",
    "交界地的中心是什么": "erdtree",
}


def _real_embedder() -> BgeM3Embedder:
    """Build a real NVIDIA embedder, or skip the test if no key is present."""
    if not os.getenv("NVIDIA_API_KEY"):
        pytest.skip("NVIDIA_API_KEY not set — skipping real-machine NVIDIA check")
    return BgeM3Embedder(provider="nvidia", timeout=60.0)


# -- provider wiring ---------------------------------------------------------


def test_nvidia_default_provider_and_endpoint():
    """Explicit ``provider="nvidia"`` wiring must still select NVIDIA
    constants. The default switched to ``local`` in PR #42, so the default
    assertion lives in test_local_real_recall.py instead."""
    emb = BgeM3Embedder(provider="nvidia")
    # NOTE: the correct NVIDIA-hosted bge-m3 OpenAI endpoint is
    # ``https://integrate.api.nvidia.com/v1`` (per NVIDIA's official NIM
    # OpenAPI spec). ``api.nvcf.nvidia.com`` is the NVCF *invoke* host and
    # returns 404 for /v1/embeddings — see QA report (base-URL bug).
    assert emb.provider == "nvidia"
    assert emb.api_base == "https://integrate.api.nvidia.com/v1"
    assert emb.model == "baai/bge-m3"
    assert emb.dim == 1024


# -- live health -------------------------------------------------------------


def test_nvidia_health_live():
    emb = _real_embedder()
    result = emb.health()
    assert result["ok"] is True, f"NVIDIA health failed: {result}"
    assert result["provider"] == "nvidia"
    assert result["model"] == "baai/bge-m3"
    assert result["dim"] == 1024
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] >= 0


# -- vector properties -------------------------------------------------------


def test_nvidia_vector_shape_dtype_norm():
    emb = _real_embedder()
    vec = emb.embed_query("测试中文向量维度与归一化")
    assert vec.shape == (1024,), vec.shape
    assert vec.dtype == np.float32
    norm = float(np.linalg.norm(vec))
    assert 0.99 <= norm <= 1.01, f"expected L2-normalized vector, got norm={norm}"


def test_nvidia_batch_shape_and_norm():
    emb = _real_embedder()
    vecs = emb.embed_texts(list(_CHINESE_DOCS.values()), is_query=False)
    assert vecs.shape == (len(_CHINESE_DOCS), 1024)
    assert vecs.dtype == np.float32
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=0.01), f"batch not normalized: {norms}"


# -- Chinese semantic recall (core acceptance criterion) ----------------------


def test_nvidia_chinese_recall_at_1():
    emb = _real_embedder()
    doc_keys = list(_CHINESE_DOCS.keys())
    doc_texts = [_CHINESE_DOCS[k] for k in doc_keys]
    doc_vecs = emb.embed_texts(doc_texts, is_query=False)

    failures = []
    for query, expected_key in _CHINESE_QUERIES.items():
        q_vec = emb.embed_query(query)
        sims = [cosine_similarity(q_vec, d) for d in doc_vecs]
        ranked = sorted(zip(doc_keys, sims), key=lambda x: x[1], reverse=True)
        top_key, top_sim = ranked[0]
        if top_key != expected_key:
            failures.append(
                f"query={query!r}: expected top-1={expected_key} "
                f"but got {top_key} (sim={top_sim:.3f}); ranking={ranked}"
            )
        # semantic signal must be clearly non-random
        assert top_sim > 0.3, f"query={query!r} max sim too low ({top_sim:.3f})"
    assert not failures, "Chinese recall@1 failures:\n" + "\n".join(failures)


def test_nvidia_identical_text_is_stable():
    """Space-consistency rule (design §2.3): same text → same vector."""
    emb = _real_embedder()
    text = "玛莲妮亚的弱点在于火属性与出血累积"
    a = emb.embed_query(text)
    b = emb.embed_query(text)
    assert cosine_similarity(a, b) > 0.999, "identical query embedding drifted"


# -- end-to-end sync + USearch HNSW recall ------------------------------------


def test_nvidia_e2e_wiki_sync_and_recall():
    pytest.importorskip("usearch")
    from memory_store.backends.sqlite_backend import SqliteBackend
    from memory_store.models import RecallFilter
    from memory_store.wiki_service import sync_wiki_dir

    emb = _real_embedder()
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="nvidia_wiki_"))
    wiki = tmp / "wiki" / "elden-ring"
    wiki.mkdir(parents=True)
    (wiki / "lore.md").write_text(
        "\n".join(f"# {k}\n\n{v}\n" for k, v in _CHINESE_DOCS.items()),
        encoding="utf-8",
    )

    be = SqliteBackend(
        str(tmp / "memory.sqlite"),
        vec_dir=str(tmp / "vec"),
        embedder=emb,
    )
    try:
        result = sync_wiki_dir(be, emb, "wiki:elden-ring", str(wiki))
        assert result.embedded >= len(_CHINESE_DOCS), result

        blocks = asyncio.run(
            be.recall(
                "玛莲妮亚怎么打",
                top_k=5,
                min_score=0.0,
                flt=RecallFilter(namespaces=["wiki:elden-ring"]),
                min_similarity=0.3,
            )
        )
        assert blocks, "NVIDIA end-to-end recall returned nothing"
        assert "玛莲妮亚" in blocks[0].content, (
            f"top-1 should be the Malenia chunk, got: {blocks[0].content!r}"
        )
    finally:
        be.close()
