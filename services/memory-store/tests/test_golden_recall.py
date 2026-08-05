# ruff: noqa: RUF002, RUF003
# SPDX-License-Identifier: Apache-2.0
"""钉死封闭回路的 golden recall@5 pytest 形态（[Local Wiki] 语料，ADR-0012）。

本文件是 `tools/README.md` 描述的「钉死封闭测试回路」的 pytest 入口，复用
`tools/eval_golden_recall.py` 的同一组钉死资产：

- 语料（SSOT）：``tools/sample_wiki/elden-ring/``（13 个 markdown，含
  bosses/areas/items/mechanics 子目录）
- golden 集（SSOT）：``tools/golden_recall_set.json``（24 条 query + expects）

测试在进程内用本地 bge-m3 embedder 摄入钉死语料（不起服务、不调外部 API），
对 24 条 golden query 跑 recall@5，并断言 ``recall@5 == 1.000``。

跳过条件（与 `tests/test_local_real_recall.py` 一致，CI 无权重时保持绿）：
``sentence_transformers`` 不可导入，或 `EMBEDDING_LOCAL_MODEL` 未指向真实权重
目录时，整模块 skip。

命中规则（ADR-0012 B9）：某条 golden query 为 *hit* 当且仅当其 top-k 个 block
的 ``content`` 中包含（大小写不敏感）任意一个 ``expects`` 关键词；
``recall@5 = hits / total``。

改这两条资产（语料 / golden 集）才算「改测试基线」，需评审；本测试平时只读。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

# 无本地 bge-m3 权重（CI）或 sentence_transformers 缺失时，整模块跳过，保持绿。
pytest.importorskip("sentence_transformers")
_LOCAL_MODEL = os.getenv("EMBEDDING_LOCAL_MODEL", "")
if not _LOCAL_MODEL or not os.path.isdir(_LOCAL_MODEL):
    pytest.skip(
        "EMBEDDING_LOCAL_MODEL not set to real bge-m3 weights — set it to run golden recall",
        allow_module_level=True,
    )

from memory_store.backends.sqlite_backend import SqliteBackend  # noqa: E402
from memory_store.embedder import BgeM3Embedder  # noqa: E402
from memory_store.models import RecallFilter  # noqa: E402
from memory_store.wiki_service import sync_wiki_dir  # noqa: E402

# 钉死路径：与 tools/eval_golden_recall.py 的默认路径一致（SSOT）。
_HERE = Path(__file__).resolve().parents[1] / "tools"
_DEFAULT_GOLDEN = _HERE / "golden_recall_set.json"
_DEFAULT_WIKI = _HERE / "sample_wiki" / "elden-ring"
_NAMESPACE = "wiki:elden-ring"
_TOP_K = 5


def load_golden(path: Path) -> list[dict]:
    """加载 golden recall 集（``{namespace, query, expects}`` 列表）。"""
    return json.loads(path.read_text(encoding="utf-8"))


def is_hit(golden: dict, blocks: list) -> bool:
    """若任意 top-k block 的 content 包含 expected 关键词则返回 True。"""
    expects = [e.lower() for e in golden.get("expects", [])]
    if not expects:
        return False
    for block in blocks:
        content = (block.content or "").lower()
        if any(exp in content for exp in expects):
            return True
    return False


async def _run_recall(backend: SqliteBackend, golden: list[dict], top_k: int) -> tuple[int, int]:
    """逐条跑 golden query；返回 ``(hits, total)``。"""
    total = 0
    hits = 0
    for item in golden:
        namespace = item.get("namespace", _NAMESPACE)
        blocks = await backend.recall(
            item["query"],
            top_k,
            min_score=0.0,
            flt=RecallFilter(namespaces=[namespace]),
            min_similarity=0.0,
        )
        ok = is_hit(item, blocks)
        total += 1
        hits += 1 if ok else 0
    return hits, total


def test_golden_recall_at_5(tmp_path: Path) -> None:
    """钉死语料的 closed-loop golden recall@5 必须等于 1.000。

    在进程内用本地 bge-m3 embedder 摄入钉死语料并跑 24 条 golden query，
    断言 recall@5 == 1.000（即全部命中）。无权重时整模块已 skip。
    """
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    embedder = BgeM3Embedder(provider="local", model=_LOCAL_MODEL)
    assert embedder.available(), (
        "local bge-m3 weights unavailable at EMBEDDING_LOCAL_MODEL; "
        "set EMBEDDING_LOCAL_MODEL to a real weights dir (e.g. D:/AI/models/bge-m3)"
    )

    db_path = tmp_path / "memory.sqlite"
    vec_dir = tmp_path / "vec"
    backend = SqliteBackend(str(db_path), vec_dir=str(vec_dir), embedder=embedder)
    try:
        sync_wiki_dir(backend, embedder, _NAMESPACE, str(_DEFAULT_WIKI), drop_first=True)
        golden = load_golden(_DEFAULT_GOLDEN)
        hits, total = asyncio.run(_run_recall(backend, golden, _TOP_K))
    finally:
        backend.close()

    recall = hits / total if total else 0.0
    assert recall == 1.0, f"golden recall@{_TOP_K} = {hits}/{total} = {recall:.3f}"
