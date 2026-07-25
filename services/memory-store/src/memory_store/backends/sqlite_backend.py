# SPDX-License-Identifier: Apache-2.0
"""SqliteBackend (spec §D-5) + [Local Wiki] vector recall (ADR-0012).

Recall routing:
- If the request filters on namespaces that have a USearch sidecar index AND
  the embedder is available → vector KNN path (semantic recall for wiki
  corpora).
- Otherwise → legacy FTS5 BM25 path (chat memory, and fail-open fallback when
  the embedding API is down).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from ..embedder import BgeM3Embedder, EmbedderError
from ..models import MemoryBlock, RecallFilter
from ..vector_index import VectorIndexStore

_LOGGER = logging.getLogger(__name__)

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
CREATE INDEX IF NOT EXISTS memory_blocks_namespace_idx ON memory_blocks(namespace);
CREATE INDEX IF NOT EXISTS memory_blocks_hash_idx ON memory_blocks(namespace, content_hash);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_blocks_fts USING fts5(
    content, block_id UNINDEXED, session_id UNINDEXED,
    content='memory_blocks', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS memory_blocks_ai AFTER INSERT ON memory_blocks BEGIN
    INSERT INTO memory_blocks_fts(rowid, content, block_id, session_id)
    VALUES (new.rowid, new.content, new.block_id, new.session_id);
END;
CREATE TRIGGER IF NOT EXISTS memory_blocks_ad AFTER DELETE ON memory_blocks BEGIN
    INSERT INTO memory_blocks_fts(memory_blocks_fts, rowid, content, block_id, session_id)
    VALUES('delete', old.rowid, old.content, old.block_id, old.session_id);
END;
CREATE TRIGGER IF NOT EXISTS memory_blocks_au AFTER UPDATE ON memory_blocks BEGIN
    INSERT INTO memory_blocks_fts(memory_blocks_fts, rowid, content, block_id, session_id)
    VALUES('delete', old.rowid, old.content, old.block_id, old.session_id);
    INSERT INTO memory_blocks_fts(rowid, content, block_id, session_id)
    VALUES (new.rowid, new.content, new.block_id, new.session_id);
END;
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
        self._conn = _connect(path)
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
        async with self._lock:
            await asyncio.to_thread(self._push_sync, session_id, blocks)
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
        """Recall the top-k blocks for ``query`` (vector path, else FTS5)."""
        async with self._lock:
            return await asyncio.to_thread(
                self._recall_sync, query, top_k, min_score, flt, min_similarity
            )

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
        namespaces = self._expand_namespaces(flt.namespaces) if flt and flt.namespaces else None
        # Vector path: semantic recall over namespaced wiki corpora.
        if namespaces and self._embedder is not None and self._embedder.available():
            try:
                return self._recall_vector(query, namespaces, top_k, min_score, min_similarity)
            except EmbedderError as exc:
                _LOGGER.warning("vector recall unavailable (%s); falling back to FTS5", exc)
        return self._recall_fts(query, top_k, min_score, flt, namespaces)

    def _recall_vector(
        self,
        query: str,
        namespaces: list[str],
        top_k: int,
        min_score: float,
        min_similarity: float,
    ) -> list[MemoryBlock]:
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
        blocks.sort(key=lambda b: sim_by_rowid.get(self._rowid_of(b.block_id), 0.0), reverse=True)
        return blocks[:top_k]

    def _rowid_of(self, block_id: str) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT rowid FROM memory_blocks WHERE block_id=?", (block_id,))
        row = cur.fetchone()
        return int(row["rowid"]) if row else -1

    def _recall_fts(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
        expanded_namespaces: list[str] | None = None,
    ) -> list[MemoryBlock]:
        limit = max(int(top_k), 1)
        session_ids: list[str] | None = flt.session_ids if flt else None
        created_after = flt.created_after if flt else None
        namespaces: list[str] | None = (
            expanded_namespaces
            if expanded_namespaces is not None
            else (flt.namespaces if flt else None)
        )

        def _apply_post_filters(rows):
            out = []
            for r in rows:
                if r["score"] < min_score:
                    continue
                if session_ids is not None and r["session_id"] not in session_ids:
                    continue
                if namespaces is not None and r["namespace"] not in namespaces:
                    continue
                if (
                    created_after is not None
                    and datetime.fromisoformat(r["created_at"]) < created_after
                ):
                    continue
                out.append(r)
                if len(out) >= limit:
                    break
            return out

        if query == "__warmup__":
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM memory_blocks ORDER BY created_at DESC LIMIT ?", (limit * 4,)
            )
            rows = cur.fetchall()
            return [self._row_to_block(r) for r in _apply_post_filters(rows)]

        # FTS5 BM25 sort (bm25() returns lower = better; negate to make higher = better).
        cur = self._conn.cursor()
        # Wrap each token with a double-quote to escape FTS5 reserved chars in case
        # the query contains punctuation, then OR-join.
        tokens = [tok.strip() for tok in query.split() if tok.strip()]
        if not tokens:
            return []
        fts_expr = " OR ".join(f'"{tok.replace(chr(34), "")}"' for tok in tokens)
        cur.execute(
            "SELECT m.*, bm25(memory_blocks_fts) AS rank "
            "FROM memory_blocks_fts f "
            "JOIN memory_blocks m ON m.rowid = f.rowid "
            "WHERE memory_blocks_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_expr, max(int(limit * 1.5), limit)),
        )
        rows = cur.fetchall()
        return [self._row_to_block(r) for r in _apply_post_filters(rows)]

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
