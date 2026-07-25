# SPDX-License-Identifier: Apache-2.0
"""B9 golden recall evaluation for the [Local Wiki] corpus (ADR-0012).

Offline-first: it builds the corpus in-process (no running server, no external
API) by importing :mod:`memory_store.wiki_service` and :mod:`memory_store.backends`.
Two modes:
  * ``fts5``   (default) — embedder is ``None`` so recall falls back to the
    FTS5 BM25 path. Fully offline; needs neither the siliconflow key nor the
    local bge-m3 weights.
  * ``vector`` — uses the siliconflow embedding API for both ingest and recall.
    Requires ``SILICONFLOW_API_KEY`` (set in env). If the key is missing or the
    call fails, the script prints a hint to top up siliconflow or fetch the
    local weights, and exits non-zero.

Hit rule (per ADR-0012 B9): a golden query is a *hit* when any of the top-``k``
blocks' ``content`` contains (case-insensitively) any of its ``expects``
keywords. ``recall@5`` = hits / total.

Usage:
    python tools/eval_golden_recall.py --mode fts5
    python tools/eval_golden_recall.py --mode vector

Achieved recall@5 (offline fts5, sample_wiki/elden-ring): 24/24 = 1.000
(measured 2026-07-24). Re-run with ``--mode fts5`` to reproduce; the vector
mode requires the siliconflow key and is not exercised here by default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Make the in-repo ``src`` package importable when run as a bare script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_store.backends.sqlite_backend import SqliteBackend
from memory_store.embedder import BgeM3Embedder
from memory_store.models import RecallFilter
from memory_store.wiki_service import sync_wiki_dir

_HERE = Path(__file__).resolve().parent
_DEFAULT_GOLDEN = _HERE / "golden_recall_set.json"
_DEFAULT_WIKI = _HERE / "sample_wiki" / "elden-ring"
_NAMESPACE = "wiki:elden-ring"
_TOP_K = 5


def load_golden(path: Path) -> list[dict]:
    """Load the golden recall set (list of ``{namespace, query, expects}``)."""
    return json.loads(path.read_text(encoding="utf-8"))


def is_hit(golden: dict, blocks: list) -> bool:
    """Return True if any top-k block content contains an expected keyword."""
    expects = [e.lower() for e in golden.get("expects", [])]
    if not expects:
        return False
    for block in blocks:
        content = (block.content or "").lower()
        if any(exp in content for exp in expects):
            return True
    return False


async def run_recall(
    backend: SqliteBackend, golden: list[dict], top_k: int
) -> tuple[int, int, list[tuple[dict, bool, int]]]:
    """Run every golden query; return (hits, total, per-query detail)."""
    total = 0
    hits = 0
    details: list[tuple[dict, bool, int]] = []
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
        details.append((item, ok, len(blocks)))
    return hits, total, details


def print_report(hits: int, total: int, details: list[tuple[dict, bool, int]]) -> float:
    """Print a per-query table and the aggregate recall@5; return recall@5."""
    print(f"\n=== B9 golden recall (top_k={_TOP_K}) ===")
    for item, ok, n in details:
        status = "HIT " if ok else "MISS"
        expects = ", ".join(item.get("expects", []))
        print(f"[{status}] blocks={n} | {item['query']}")
        if not ok:
            print(f"        expected one of: {expects}")
    recall = (hits / total) if total else 0.0
    print(f"\nrecall@{_TOP_K} = {hits} / {total} = {recall:.3f}")
    return recall


async def run_fts5(wiki_dir: Path, golden: list[dict], db_path: Path, vec_dir: Path) -> float:
    """Ingest with no embedder so recall uses the FTS5 BM25 fallback path."""
    backend = SqliteBackend(str(db_path), vec_dir=str(vec_dir), embedder=None)
    try:
        sync_wiki_dir(backend, None, _NAMESPACE, str(wiki_dir), drop_first=True)
        hits, total, details = await run_recall(backend, golden, _TOP_K)
        return print_report(hits, total, details)
    finally:
        backend.close()


async def run_vector(wiki_dir: Path, golden: list[dict], db_path: Path, vec_dir: Path) -> float:
    """Ingest + recall with the siliconflow embedding API (needs a key)."""
    embedder = BgeM3Embedder(provider="siliconflow")
    if not embedder.available():
        print(
            "vector mode requires SILICONFLOW_API_KEY. Top up siliconflow or "
            "download the local bge-m3 weights, then retry."
        )
        return -1.0
    backend = SqliteBackend(str(db_path), vec_dir=str(vec_dir), embedder=embedder)
    try:
        sync_wiki_dir(backend, embedder, _NAMESPACE, str(wiki_dir), drop_first=True)
        hits, total, details = await run_recall(backend, golden, _TOP_K)
        return print_report(hits, total, details)
    finally:
        backend.close()


def parse_args() -> argparse.Namespace:
    """Parse CLI args for the golden recall evaluator."""
    parser = argparse.ArgumentParser(description="Evaluate B9 golden recall@5.")
    parser.add_argument(
        "--mode",
        choices=["fts5", "vector"],
        default="fts5",
        help="recall mode (default: fts5, fully offline)",
    )
    parser.add_argument("--golden", default=str(_DEFAULT_GOLDEN), help="golden recall set JSON")
    parser.add_argument("--wiki-dir", default=str(_DEFAULT_WIKI), help="wiki/<game> directory")
    parser.add_argument("--db", default=None, help="sqlite path (default: temp file)")
    parser.add_argument("--top-k", type=int, default=_TOP_K, help="recall top-k (default: 5)")
    return parser.parse_args()


async def main() -> int:
    """Entrypoint: ingest the sample corpus and report recall@5."""
    args = parse_args()
    golden_path = Path(args.golden)
    wiki_dir = Path(args.wiki_dir)
    if not golden_path.is_file():
        print(f"golden set not found: {golden_path}")
        return 2
    if not wiki_dir.is_dir():
        print(f"wiki dir not found: {wiki_dir}")
        return 2

    golden = load_golden(golden_path)
    tmp_root = tempfile.mkdtemp(prefix="golden_recall_")
    db_path = Path(args.db) if args.db else Path(tmp_root) / "memory.sqlite"
    vec_dir = Path(tmp_root) / "vec"

    global _TOP_K
    _TOP_K = args.top_k

    if args.mode == "fts5":
        recall = await run_fts5(wiki_dir, golden, db_path, vec_dir)
    else:
        recall = await run_vector(wiki_dir, golden, db_path, vec_dir)

    if recall < 0:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
