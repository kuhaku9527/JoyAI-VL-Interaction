# SPDX-License-Identifier: Apache-2.0
"""Wiki sync orchestration (ADR-0012): directory → chunks → embed → sqlite + HNSW.

Incremental semantics: chunks are keyed by ``content_hash`` inside the
namespace. Unchanged chunks are skipped (no re-embedding, no row churn);
chunks that disappeared from the source directory are deleted (stale rows +
their vector keys). ``drop_first=True`` wipes the namespace first for a clean
rebuild.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

from .backends.sqlite_backend import SqliteBackend
from .embedder import BgeM3Embedder, EmbedderError, content_hash
from .models import MemoryBlock, SyncResponse
from .wiki_ingest import ingest_directory

_LOGGER = logging.getLogger(__name__)

_EMBED_BATCH = 32  # conservative for both local models and hosted APIs


def sync_wiki_dir(
    backend: SqliteBackend,
    embedder: BgeM3Embedder | None,
    namespace: str,
    dir_path: str,
    drop_first: bool = False,
) -> SyncResponse:
    """Sync a wiki directory into a namespace: chunk, embed, and index blocks."""
    chunks, files, errors = ingest_directory(dir_path)
    dropped = False

    if drop_first:
        deleted_rows, _ = backend.delete_namespace(namespace)
        _LOGGER.info("namespace %s dropped before sync (%d rows)", namespace, deleted_rows)
        dropped = True

    existing = backend.namespace_hashes(namespace)
    seen_hashes: set[str] = set()
    new_blocks: list[MemoryBlock] = []
    for chunk in chunks:
        h = content_hash(chunk.text)
        seen_hashes.add(h)
        if h in existing:
            continue  # unchanged — skip re-embedding
        new_blocks.append(
            MemoryBlock(
                content=chunk.text,
                score=1.0,
                created_at=datetime.utcnow(),
                namespace=namespace,
                images=chunk.images or None,
                source_url=chunk.source_url,
                content_hash=h,
            )
        )

    skipped = len(chunks) - len(new_blocks)
    embedded = 0

    # Stale cleanup: hashes present in DB but absent from the source directory.
    stale_rowids = [rowid for h, rowid in existing.items() if h not in seen_hashes]
    if stale_rowids:
        backend.delete_rows(stale_rowids, namespace=namespace)
        _LOGGER.info("namespace %s: removed %d stale chunks", namespace, len(stale_rowids))

    want_vectors = embedder is not None and embedder.available()
    if new_blocks and embedder is not None and not embedder.available():
        # Provider-aware hint: the default is now nvidia, so pointing users at
        # SILICONFLOW_API_KEY when the nvidia key is missing would mislead them.
        if embedder.provider == "nvidia":
            key_hint = "NVIDIA_API_KEY"
        elif embedder.provider == "siliconflow":
            key_hint = "SILICONFLOW_API_KEY"
        else:
            key_hint = "embedding provider configuration"
        errors.append(f"embedder unavailable (check {key_hint}); blocks stored without vectors")

    for start in range(0, len(new_blocks), _EMBED_BATCH):
        batch = new_blocks[start : start + _EMBED_BATCH]
        vectors: np.ndarray | None = None
        if want_vectors and embedder is not None:
            try:
                vectors = embedder.embed_texts([b.content for b in batch])
            except EmbedderError as exc:
                errors.append(f"embedding batch {start // _EMBED_BATCH} failed: {exc}")
                vectors = None
        for i, block in enumerate(batch):
            vec = vectors[i] if vectors is not None else None
            backend.insert_block_with_vector(session_id=namespace, block=block, vector=vec)
        if vectors is not None:
            embedded += len(batch)

    return SyncResponse(
        namespace=namespace,
        files=files,
        chunks=len(chunks),
        embedded=embedded,
        skipped_unchanged=skipped,
        dropped=dropped,
        errors=errors,
    )


def drop_wiki_namespace(backend: SqliteBackend, namespace: str) -> tuple[int, bool]:
    """Delete a whole game corpus: rows + sidecar index file."""
    return backend.delete_namespace(namespace)
