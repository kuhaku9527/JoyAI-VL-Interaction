# SPDX-License-Identifier: Apache-2.0
"""SqliteBackend (spec §D-5)."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from ..models import MemoryBlock, RecallFilter

_LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_blocks (
    block_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    content     TEXT NOT NULL,
    score       REAL NOT NULL DEFAULT 1.0,
    created_at  TEXT NOT NULL,
    last_hit_at TEXT,
    hit_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS memory_blocks_session_idx ON memory_blocks(session_id);
CREATE INDEX IF NOT EXISTS memory_blocks_created_idx ON memory_blocks(created_at);
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


def _connect(path: str) -> sqlite3.Connection:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


class SqliteBackend:
    """Single-thread sqlite owner; serialize via ``asyncio.Lock``."""

    def __init__(self, path: str):
        self._path = path
        self._conn = _connect(path)
        self._lock = asyncio.Lock()

    def name(self) -> str:
        return "sqlite"

    async def push(self, session_id: str, blocks: list[MemoryBlock]) -> int:
        if not blocks:
            return 0
        async with self._lock:
            await asyncio.to_thread(self._push_sync, session_id, blocks)
        return len(blocks)

    def _push_sync(self, session_id: str, blocks: list[MemoryBlock]) -> None:
        cur = self._conn.cursor()
        for b in blocks:
            bid = b.block_id or uuid.uuid4().hex
            cur.execute(
                "INSERT OR REPLACE INTO memory_blocks(block_id,session_id,content,score,created_at,last_hit_at,hit_count)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    bid,
                    session_id,
                    b.content,
                    b.score,
                    b.created_at.isoformat(),
                    b.last_hit_at.isoformat() if b.last_hit_at else None,
                    b.hit_count,
                ),
            )
        self._conn.commit()

    async def recall(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        async with self._lock:
            return await asyncio.to_thread(self._recall_sync, query, top_k, min_score, flt)

    def _recall_sync(
        self,
        query: str,
        top_k: int,
        min_score: float,
        flt: RecallFilter | None,
    ) -> list[MemoryBlock]:
        limit = max(int(top_k), 1)
        session_ids: list[str] | None = flt.session_ids if flt else None
        created_after = flt.created_after if flt else None

        def _apply_post_filters(rows):
            out = []
            for r in rows:
                if r["score"] < min_score:
                    continue
                if session_ids is not None and r["session_id"] not in session_ids:
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
        return MemoryBlock(
            block_id=row["block_id"],
            session_id=row["session_id"],
            content=row["content"],
            score=row["score"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_hit_at=datetime.fromisoformat(row["last_hit_at"]) if row["last_hit_at"] else None,
            hit_count=row["hit_count"],
        )

    async def health(self) -> dict:
        async with self._lock:
            count = await asyncio.to_thread(self._count_sync)
        return {"ok": True, "path": self._path, "blocks": count, "backend": self.name()}

    def _count_sync(self) -> int:
        cur = self._conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM memory_blocks")
        return int(cur.fetchone()["c"])

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception as exc:  # best-effort cleanup on shutdown
            _LOGGER.warning("sqlite connection close failed: %s", exc)
