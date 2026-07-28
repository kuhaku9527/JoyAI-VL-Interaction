# SPDX-License-Identifier: Apache-2.0
"""Real-machine verification of LOCAL ``bge-m3`` vector recall (ADR-0012).

Companion to ``test_nvidia_real_recall.py``: the local path is the default
after PR #42 (ADR-0012 §6), so it earns first-class coverage here. The
module is **skipped** when ``sentence-transformers`` is not importable or
when ``EMBEDDING_LOCAL_MODEL`` is not set to a real weights path, so CI
without the bge-m3 weights stays green.

Difference from the provider-switch test: this one runs the actual local
model weights to prove the default path is real, not just a stub. The
assertions mirror the NVIDIA real-recall suite so the two paths stay
behaviorally comparable.
"""

from __future__ import annotations

import asyncio
import os

import numpy as np
import pytest

# Skip the whole module when local embedding isn't usable in this env.
# Imports kept at the top despite the conditional skip — the heavy
# ``sentence_transformers`` import is itself skipped by the test runner
# before this module's body runs, so bench-time cost is paid zero times.
pytest.importorskip("sentence_transformers")
_LOCAL_MODEL = os.getenv("EMBEDDING_LOCAL_MODEL", "")
if not _LOCAL_MODEL or not os.path.isdir(_LOCAL_MODEL):
    pytest.skip(
        "EMBEDDING_LOCAL_MODEL not pointing at a real weights directory — "
        "set EMBEDDING_LOCAL_MODEL=D:/AI/models/bge-m3 to run this test",
        allow_module_level=True,
    )

from memory_store.embedder import BgeM3Embedder, cosine_similarity  # noqa: E402

# --- Chinese corpus: same as the NVIDIA real-recall suite so the two stay
#     comparable on the same semantic acceptance criterion. ---
_CHINESE_DOCS: dict[str, str] = {
    "malenia": "玛莲妮亚是化圣雪原的圣树boss，使用水鸟乱舞，弱火属性与出血。",
    "radahn": "拉塔恩是盖利德红狮子城的boss，使用重力魔法与陨石攻击。",
    "moonveil": "名刀月隐是智力流派太刀，战技为隙间月影，适合法师使用。",
    "erdtree": "黄金树是交界地的中心，是玛莉卡女王的神祇居所。",
}
_CHINESE_QUERIES: dict[str, str] = {
    "玛莲妮亚怎么打": "malenia",
    "法师应该拿什么武器": "moonveil",
    "红狮子城的boss是谁": "radahn",
    "交界地的中心是什么": "erdtree",
}


def _build_local() -> BgeM3Embedder:
    """Build a real local embedder pointing at the verified weights. Local
    weights honour ``EMBEDDING_LOCAL_MODEL`` so the test never touches the
    HF cache (which would not be populated on CI)."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    return BgeM3Embedder(provider="local", model=_LOCAL_MODEL)


# -- default provider is local -----------------------------------------------


def test_local_is_default_when_no_env_or_provider_arg():
    os.environ.pop("EMBEDDING_PROVIDER", None)
    emb = BgeM3Embedder()
    assert emb.provider == "local"
    assert emb.available() is True


# -- vector properties -------------------------------------------------------


def test_local_vector_shape_dtype_norm():
    emb = _build_local()
    vec = emb.embed_query("测试中文向量维度与归一化")
    assert vec.shape == (1024,), vec.shape
    assert vec.dtype == np.float32
    norm = float(np.linalg.norm(vec))
    assert 0.99 <= norm <= 1.01, f"expected L2-normalized vector, got norm={norm}"


def test_local_batch_shape_and_norm():
    emb = _build_local()
    vecs = emb.embed_texts(list(_CHINESE_DOCS.values()), is_query=False)
    assert vecs.shape == (len(_CHINESE_DOCS), 1024)
    assert vecs.dtype == np.float32
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=0.01), f"batch not normalized: {norms}"


# -- semantic recall (core acceptance criterion) -----------------------------


def test_local_chinese_recall_at_1():
    emb = _build_local()
    doc_keys = list(_CHINESE_DOCS.keys())
    doc_vecs = emb.embed_texts([_CHINESE_DOCS[k] for k in doc_keys], is_query=False)

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
        assert top_sim > 0.3, f"query={query!r} max sim too low ({top_sim:.3f})"
    assert not failures, "Local Chinese recall@1 failures:\n" + "\n".join(failures)


def test_local_identical_text_is_stable():
    """Space-consistency rule (design §2.3): same text → same vector."""
    emb = _build_local()
    text = "玛莲妮亚的弱点在于火属性与出血累积"
    a = emb.embed_query(text)
    b = emb.embed_query(text)
    assert cosine_similarity(a, b) > 0.999, "identical query embedding drifted"


# -- end-to-end sync + USearch HNSW recall ------------------------------------


def test_local_e2e_wiki_sync_and_recall(tmp_path):
    pytest.importorskip("usearch")
    from memory_store.backends.sqlite_backend import SqliteBackend
    from memory_store.models import RecallFilter
    from memory_store.wiki_service import sync_wiki_dir

    emb = _build_local()
    wiki = tmp_path / "wiki" / "elden-ring"
    wiki.mkdir(parents=True)
    (wiki / "lore.md").write_text(
        "\n".join(f"# {k}\n\n{v}\n" for k, v in _CHINESE_DOCS.items()),
        encoding="utf-8",
    )

    be = SqliteBackend(
        str(tmp_path / "memory.sqlite"),
        vec_dir=str(tmp_path / "vec"),
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
        assert blocks, "local end-to-end recall returned nothing"
        assert "玛莲妮亚" in blocks[0].content, (
            f"top-1 should be the Malenia chunk, got: {blocks[0].content!r}"
        )
    finally:
        be.close()


# -- health() -----------------------------------------------------------------


def test_local_health():
    emb = _build_local()
    h = emb.health()
    assert h["ok"] is True, h
    assert h["provider"] == "local"
    assert h["dim"] == 1024
    assert isinstance(h["latency_ms"], int) and h["latency_ms"] >= 0
