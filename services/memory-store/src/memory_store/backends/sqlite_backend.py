# SPDX-License-Identifier: Apache-2.0
"""SqliteBackend (spec §D-5) + [Local Wiki] vector recall (ADR-0012).

Recall routing (vector semantic path only; FTS5 BM25 fallback removed per
D-2026-08-05-003):

- Vector KNN over per-namespace USearch sidecars (bge-m3 semantic recall).
- ``filter.namespaces`` is a REQUIRED scope. A bare recall (no namespaces)
  raises ``ValueError`` (mapped to HTTP 400) instead of silently returning
  empty or falling back to BM25.
- When the embedder is unavailable, recall raises ``EmbedderError``
  (mapped to HTTP 503) instead of silently degrading.
- ``query == "__warmup__"`` is a pure-SQL "most recent blocks" path that needs
  no embedder (preserved from the old FTS5 branch).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from ..embedder import BgeM3Embedder, EmbedderError
from ..models import MemoryBlock, RecallFilter
from ..vector_index import VectorIndexStore

_LOGGER = logging.getLogger(__name__)


# --- ADR-0014 JSONL event emission (services/common/event_json.py) ----------
try:

    def _ensure_event_json_importable() -> None:
        """Put ``services/common`` on ``sys.path`` by walking up from this file.

        Returns without inserting if the shared emitter cannot be located;
        the subsequent import then raises ImportError, which is caught below
        and downgraded to a logged no-op (约法三章: not silent, just not fatal).
        """
        here = os.path.dirname(os.path.abspath(__file__))
        cur = here
        while True:
            common = os.path.join(cur, "services", "common")
            if os.path.exists(os.path.join(common, "event_json.py")):
                if common not in sys.path:
                    sys.path.insert(0, common)
                return
            parent = os.path.dirname(cur)
            if parent == cur:
                return
            cur = parent

    _ensure_event_json_importable()
    from event_json import emit_event
except ImportError:
    logging.getLogger(__name__).warning(
        "event_json emitter unavailable; JSONL event emission disabled "
        "(packaged build without services/common on path?)"
    )

    def emit_event(*_args, **_kwargs):
        """No-op fallback used only when the shared emitter is unavailable.

        Logged once above (not silent) per 约法三章 - never swallow the failure.
        """
        return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_blocks (
    block_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    content     TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL,
    last_hit_at TEXT,
    hit_count   INTEGER NOT NULL DEFAULT 0,
    namespace   TEXT,
    images      TEXT,
    source_url  TEXT,
    content_hash TEXT
);
CREATE INDEX IF NOT EXISTS memory_blocks_session_idx ON memory_blocks(session_id);
CREATE INDEX IF NOT EXISTS memory_blocks_created_idx ON memory_blocks(created_at);
"""

# Columns added after v0.1; applied idempotently for existing databases.
_MIGRATION_COLUMNS = {
    "namespace": "TEXT",
    "images": "TEXT",
    "source_url": "TEXT",
    "content_hash": "TEXT",
}


def _connect(path: str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(memory_blocks)")}
    for col, decl in _MIGRATION_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE memory_blocks ADD COLUMN {col} {decl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS memory_blocks_namespace_idx ON memory_blocks(namespace)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS memory_blocks_hash_idx ON memory_blocks(namespace, content_hash)"
    )


class SqliteBackend:
    """Single-thread sqlite owner; serialize via ``asyncio.Lock``."""

    def __init__(
        self,
        path: str,
        vec_dir: str | None = None,
        embedder: BgeM3Embedder | None = None,
    ):
        self._path = path
        try:
            self._conn = _connect(path)
        except Exception as exc:
            emit_event(
                "memory-store",
                "backend_startup_fail",
                level="error",
                extra={"path": path, "error_type": type(exc).__name__},
            )
            raise
        self._lock = asyncio.Lock()
        default_vec_dir = str(Path(path).parent / "vec")
        self._vectors = VectorIndexStore(vec_dir or default_vec_dir)
        self._embedder = embedder

    def name(self) -> str:
        """Return the backend identifier ``"sqlite"``."""
        return "sqlite"

    @property
    def embedder(self) -> BgeM3Embedder | None:
        """Expose the configured embedder (or ``None``) for wiki vector ingest."""
        return self._embedder

    # -- push ----------------------------------------------------------------

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        """Persist a batch of memory blocks; returns the count stored."""
        if not blocks:
            return 0
        try:
            async with self._lock:
                await asyncio.to_thread(self._push_sync, session_id, blocks)
        except sqlite3.Error as exc:
            emit_event(
                "memory-store",
                "backend_query_error",
                level="error",
                session_id=session_id,
                extra={"op": "push", "error_type": type(exc).__name__},
            )
            raise
        return len(blocks)

    def _push_sync(self, session_id: str, blocks: list[MemoryBlock]) -> None:
        cur = self._conn.cursor()
        for b in blocks:
            bid = b.block_id or uuid.uuid4().hex
            # Backfill created_at here too (app layer also backfills) so direct
            # backend callers cannot crash on None.
            created = b.created_at or datetime.utcnow()
            cur.execute(
                "INSERT OR REPLACE INTO memory_blocks("
                "block_id,session_id,content,score,created_at,last_hit_at,hit_count,"
                "namespace,images,source_url,content_hash)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    bid,
                    session_id,
                    b.content,
                    b.score,
                    created.isoformat(),
                    b.last_hit_at.isoformat() if b.last_hit_at else None,
                    b.hit_count,
                    b.namespace,
                    json.dumps(b.images, ensure_ascii=False) if b.images else None,
                    b.source_url,
                    b.content_hash,
                ),
            )
        self._conn.commit()

    # -- wiki sync write path (used by wiki_service) --------------------------

    def namespace_hashes(self, namespace: str) -> dict[str, int]:
        """``{content_hash: rowid}`` for a namespace (incremental sync diffing)."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT rowid, content_hash FROM memory_blocks WHERE namespace=? AND content_hash IS NOT NULL",
            (namespace,),
        )
        return {r["content_hash"]: int(r["rowid"]) for r in cur.fetchall()}

    def insert_block_with_vector(
        self,
        session_id: str,
        block: MemoryBlock,
        vector: np.ndarray | None,
    ) -> int:
        """Insert one block and (optionally) index its vector. Returns rowid."""
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO memory_blocks("
            "block_id,session_id,content,score,created_at,last_hit_at,hit_count,"
            "namespace,images,source_url,content_hash)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                block.block_id or uuid.uuid4().hex,
                session_id,
                block.content,
                block.score,
                (block.created_at or datetime.utcnow()).isoformat(),
                None,
                0,
                block.namespace,
                json.dumps(block.images, ensure_ascii=False) if block.images else None,
                block.source_url,
                block.content_hash,
            ),
        )
        rowid = int(cur.lastrowid)
        self._conn.commit()
        if vector is not None and block.namespace:
            self._vectors.add(block.namespace, [rowid], vector)
        return rowid

    def delete_rows(self, rowids: list[int], namespace: str | None = None) -> int:
        """Delete rows by rowid; also removes their vector keys when namespace given."""
        if not rowids:
            return 0
        cur = self._conn.cursor()
        cur.executemany("DELETE FROM memory_blocks WHERE rowid=?", [(int(r),) for r in rowids])
        self._conn.commit()
        if namespace:
            self._vectors.remove(namespace, rowids)
        return len(rowids)

    def delete_namespace(self, namespace: str) -> tuple[int, bool]:
        """Wipe a namespace: SQL rows + the whole sidecar index file."""
        cur = self._conn.cursor()
        cur.execute("DELETE FROM memory_blocks WHERE namespace=?", (namespace,))
        deleted = cur.rowcount
        self._conn.commit()
        index_removed = self._vectors.drop_namespace(namespace)
        return int(deleted), index_removed

    def namespace_stats(self) -> list[dict]:
        """Aggregate per-namespace block counts and indexed-vector counts."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT namespace, COUNT(*) AS blocks FROM memory_blocks "
            "WHERE namespace IS NOT NULL GROUP BY namespace ORDER BY namespace"
        )
        rows = [
            {
                "namespace": r["namespace"],
                "blocks": int(r["blocks"]),
                "indexed": self._vectors.count(r["namespace"]),
            }
            for r in cur.fetchall()
        ]
        return rows

    # -- recall ---------------------------------------------------------------

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
        min_similarity: float = 0.25,
    ) -> list[MemoryBlock]:
        """Recall the top-k blocks for ``query`` (vector semantic path only)."""
        try:
            async with self._lock:
                return await asyncio.to_thread(
                    self._recall_sync, query, top_k, min_score, flt, min_similarity
                )
        except sqlite3.Error as exc:
            emit_event(
                "memory-store",
                "backend_query_error",
                level="error",
                extra={
                    "op": "recall",
                    "error_type": type(exc).__name__,
                    "query_chars": len(query or ""),
                },
            )
            raise

    def _expand_namespaces(self, namespaces: list[str]) -> list[str]:
        """Expand ``wiki:*``-style wildcards against existing namespaces."""
        if not any(ns.endswith("*") for ns in namespaces):
            return namespaces
        cur = self._conn.cursor()
        cur.execute("SELECT DISTINCT namespace FROM memory_blocks WHERE namespace IS NOT NULL")
        existing = {r["namespace"] for r in cur.fetchall()}
        expanded: list[str] = []
        for ns in namespaces:
            if ns.endswith("*"):
                prefix = ns[:-1]
                expanded.extend(sorted(e for e in existing if e.startswith(prefix)))
            else:
                expanded.append(ns)
        return expanded

    def _recall_sync(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
        min_similarity: float,
    ) -> list[MemoryBlock]:
        # Warmup is a pure-SQL "most recent blocks" path; no embedder needed.
        if query == "__warmup__":
            return self._recall_recent(top_k, min_score, flt)
        # Vector semantic path only. filter.namespaces is a REQUIRED scope: a
        # bare recall (no namespaces) must error, never silently empty.
        namespaces = self._expand_namespaces(flt.namespaces) if flt and flt.namespaces else None
        if not namespaces:
            raise ValueError(
                "recall requires filter.namespaces "
                "(vector semantic path only; BM25 fallback removed)"
            )
        if self._embedder is None or not self._embedder.available():
            raise EmbedderError("embedder unavailable; vector recall cannot run")
        return self._recall_vector(query, namespaces, top_k, min_score, min_similarity, flt)

    def _recall_vector(
        self,
        query: str,
        namespaces: list[str],
        top_k: int,
        min_score: float,
        min_similarity: float,
        flt: RecallFilter | None = None,
    ) -> list[MemoryBlock]:
        """Vector KNN recall over ``namespaces`` (bge-m3 cosine).

        Blocks must satisfy ``min_similarity`` (cosine) and ``min_score``
        (stored), then the ``session_ids`` / ``created_after`` post-filters are
        applied (previously only on the removed FTS5 path) before truncating
        to ``top_k``, avoiding a capability regression.

        The returned ``MemoryBlock.score`` carries the **true cosine similarity**
        from USearch/HNSW (遗留#1: it used to be the constant stored
        ``DEFAULT 1.0``, hiding real retrieval quality). The stored
        ``score`` column is still used for the ``min_score`` gate;
        only the field on the *returned* blocks is overwritten with the
        similarity.
        """
        if self._embedder is None:
            raise EmbedderError("embedder not configured")
        qvec = self._embedder.embed_query(query)
        hits: list[tuple[int, float]] = []
        for ns in namespaces:
            hits.extend(self._vectors.search(ns, qvec, k=max(top_k * 2, 8)))
        hits = [h for h in hits if h[1] >= min_similarity]
        hits.sort(key=lambda h: h[1], reverse=True)
        hits = hits[: max(top_k * 2, 8)]

        rowids = [h[0] for h in hits]
        if not rowids:
            return []
        sim_by_rowid = dict(hits)
        placeholders = ",".join("?" for _ in rowids)
        ns_placeholders = ",".join("?" for _ in namespaces)
        cur = self._conn.cursor()
        cur.execute(
            f"SELECT * FROM memory_blocks WHERE rowid IN ({placeholders}) "
            f"AND namespace IN ({ns_placeholders}) AND score >= ?",
            (*rowids, *namespaces, min_score),
        )
        blocks = [self._row_to_block(r) for r in cur.fetchall()]
        # Tag each block with its true cosine similarity from USearch/HNSW
        # before ranking and post-filtering. The stored ``score`` column
        # (DEFAULT 1.0) is preserved so ``_apply_post_filters`` keeps using it
        # for the ``min_score`` gate; only the field on the *returned* blocks
        # is later overwritten with the similarity (遗留#1).
        sim_by_block: dict[str, float] = {}
        for b in blocks:
            rowid = self._rowid_of(b.block_id)
            sim_by_block[b.block_id] = sim_by_rowid.get(rowid, 0.0)
        blocks.sort(key=lambda b: sim_by_block.get(b.block_id, 0.0), reverse=True)
        # Apply session_ids / created_after post-filters before truncating.
        blocks = self._apply_post_filters(blocks, flt, min_score)
        # 遗留#1: surface the real cosine similarity instead of the constant
        # stored 1.0. ``VectorIndexStore.search`` already converts the HNSW
        # cosine *distance* to similarity (``1 - distance``), so values are in
        # [-1, 1] (bge-m3 vectors are L2-normalized, making this effectively the
        # dot product; semantically similar text scores well above 0.3).
        for b in blocks:
            b.score = sim_by_block.get(b.block_id, 0.0)
        return blocks[:top_k]

    def _rowid_of(self, block_id: str) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT rowid FROM memory_blocks WHERE block_id=?", (block_id,))
        row = cur.fetchone()
        return int(row["rowid"]) if row else -1

    def _recall_recent(
        self, top_k: int, min_score: float, flt: RecallFilter | None
    ) -> list[MemoryBlock]:
        """Pure-SQL "most recent blocks" path for ``query == "__warmup__"``.

        No embedder required. Fetches the most recent rows then applies the
        same ``score`` / ``session_ids`` / ``created_after`` post-filters used
        by the vector path, preserving the warmup contract after the FTS5
        branch was removed.
        """
        limit = max(int(top_k), 1)
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM memory_blocks ORDER BY created_at DESC LIMIT ?", (limit * 4,))
        blocks = [self._row_to_block(r) for r in cur.fetchall()]
        return self._apply_post_filters(blocks, flt, min_score)[:limit]

    def _apply_post_filters(
        self,
        blocks: list[MemoryBlock],
        flt: RecallFilter | None,
        min_score: float,
    ) -> list[MemoryBlock]:
        """Filter ``blocks`` by ``score`` / ``session_ids`` / ``created_after``.

        ``min_score`` is applied here too so callers that do not pre-filter it
        in SQL (e.g. ``_recall_recent``) stay consistent with the vector path.
        """
        if flt is None:
            return blocks
        out: list[MemoryBlock] = []
        for b in blocks:
            if b.score < min_score:
                continue
            if flt.session_ids is not None and b.session_id not in flt.session_ids:
                continue
            if (
                flt.created_after is not None
                and b.created_at is not None
                and b.created_at < flt.created_after
            ):
                continue
            out.append(b)
        return out

    @staticmethod
    def _row_to_block(row) -> MemoryBlock:
        keys = set(row.keys())  # sqlite3.Row: membership test needs the key list
        images_raw = row["images"] if "images" in keys else None
        try:
            images = json.loads(images_raw) if images_raw else None
        except (json.JSONDecodeError, TypeError):
            images = None
        return MemoryBlock(
            block_id=row["block_id"],
            session_id=row["session_id"],
            content=row["content"],
            score=row["score"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_hit_at=datetime.fromisoformat(row["last_hit_at"]) if row["last_hit_at"] else None,
            hit_count=row["hit_count"],
            namespace=row["namespace"] if "namespace" in keys else None,
            images=images,
            source_url=row["source_url"] if "source_url" in keys else None,
            content_hash=row["content_hash"] if "content_hash" in keys else None,
        )

    async def health(self) -> dict:
        """Return a readiness snapshot with block count and backend name."""
        async with self._lock:
            count = await asyncio.to_thread(self._count_sync)
        return {"ok": True, "path": self._path, "blocks": count, "backend": self.name()}

    def _count_sync(self) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM memory_blocks")
        return int(cur.fetchone()["c"])

    def close(self) -> None:
        """Release the vector store and sqlite connection (best-effort)."""
        try:
            self._vectors.close()
        except Exception as exc:
            _LOGGER.warning("vector store close failed: %s", exc)
        try:
            self._conn.close()
        except Exception as exc:  # best-effort cleanup on shutdown
            _LOGGER.warning("sqlite connection close failed: %s", exc)
