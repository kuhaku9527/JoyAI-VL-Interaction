# SPDX-License-Identifier: Apache-2.0
"""Pydantic models for memory-store v0.1 (spec §D-3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryBlock(BaseModel):
    block_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex)
    session_id: str | None = None
    content: str
    score: float = 1.0
    created_at: datetime | None = None
    last_hit_at: datetime | None = None
    hit_count: int = 0
    # [Local Wiki] fields (ADR-0012): namespace isolates corpora, e.g.
    # "wiki:<game>" for preloaded game-guide knowledge vs per-session chat
    # memory. images holds relative asset paths ("assets/boss.png") attached
    # to the block; source_url records provenance for CC BY-SA attribution;
    # content_hash enables incremental re-embedding on sync.
    namespace: str | None = None
    images: list[str] | None = None
    source_url: str | None = None
    content_hash: str | None = None


class PushRequest(BaseModel):
    session_id: str
    blocks: list[MemoryBlock]


class PushResponse(BaseModel):
    pushed: int
    session_id: str


class RecallFilter(BaseModel):
    session_ids: list[str] | None = None
    created_after: datetime | None = None
    namespaces: list[str] | None = None


class RecallRequest(BaseModel):
    query: str
    top_k: int = 8
    min_score: float = 0.3
    filter: RecallFilter | None = None
    # Vector path only: cosine-similarity threshold (0..1). Ignored on the
    # FTS5 fallback path.
    min_similarity: float = 0.25


class RecallResponse(BaseModel):
    blocks: list[MemoryBlock]


class SyncRequest(BaseModel):
    """Request for POST /v1/external/sync (ADR-0012).

    ``dir`` points at a ``wiki/<game>`` directory containing ``*.md`` files and
    an optional ``assets/`` folder. All blocks are written under ``namespace``.
    When ``drop_first`` is true the namespace is wiped (rows + vector index
    file) before ingest, giving a clean rebuild.
    """

    namespace: str
    dir: str
    drop_first: bool = False


class SyncResponse(BaseModel):
    namespace: str
    files: int
    chunks: int
    embedded: int
    skipped_unchanged: int
    dropped: bool = False
    errors: list[str] = Field(default_factory=list)


class DropNamespaceResponse(BaseModel):
    namespace: str
    deleted_rows: int
    index_file_removed: bool
