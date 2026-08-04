# SPDX-License-Identifier: Apache-2.0
"""Pydantic models for memory-store v0.1 (spec §D-3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryBlock(BaseModel):
    """A single stored memory unit with optional [Local Wiki] metadata."""

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
    """Batch push request."""

    session_id: str
    blocks: list[MemoryBlock]


class PushResponse(BaseModel):
    """Batch push response."""

    pushed: int
    session_id: str


class RecallFilter(BaseModel):
    """Namespace / session / time filters for recall.

    ``namespaces`` is a REQUIRED scope for the vector semantic recall path:
    a recall without it is rejected (HTTP 400), not silently emptied or
    fallen back to BM25 (D-2026-08-05-003).
    """

    session_ids: list[str] | None = None
    created_after: datetime | None = None
    namespaces: list[str] | None = None


class RecallRequest(BaseModel):
    """Recall request."""

    query: str
    top_k: int = 8
    min_score: float = 0.3
    filter: RecallFilter | None = None
    # Vector path only: cosine-similarity threshold (0..1). Recall requires
    # filter.namespaces; a request without it is rejected (no BM25 fallback).
    min_similarity: float = 0.25


class RecallResponse(BaseModel):
    """Recall response."""

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
    """Wiki directory sync result."""

    namespace: str
    files: int
    chunks: int
    embedded: int
    skipped_unchanged: int
    dropped: bool = False
    errors: list[str] = Field(default_factory=list)


class DropNamespaceResponse(BaseModel):
    """Result of dropping a whole namespace."""

    namespace: str
    deleted_rows: int
    index_file_removed: bool


# --- [Local Wiki] network settings (ADR-0012, tasks B2/B4) ------------------
# These mirror ``config.ProxyConfig`` / ``config.ProviderNetConfig`` but live
# in the request contract so the settings UI can PATCH only what it touches.


class ProxySettings(BaseModel):
    """Proxy switch sent by the settings UI (reserved; disabled in phase 1)."""

    enabled: bool = False
    url: str = "http://127.0.0.1:7890"


class ProviderNetSettings(BaseModel):
    """Per-provider proxy opt-in sent by the settings UI."""

    use_proxy: bool = False


class NetworkSettingsRequest(BaseModel):
    """Body for ``PUT /v1/settings/network`` (ADR-0012 §7.1).

    ``proxy`` and ``providers`` are optional so the UI can update just one
    side. Omitted fields keep their current value.
    """

    proxy: ProxySettings | None = None
    providers: dict[str, ProviderNetSettings] | None = None
