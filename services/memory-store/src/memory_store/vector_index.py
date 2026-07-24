# SPDX-License-Identifier: Apache-2.0
"""USearch sidecar HNSW vector index (ADR-0012).

Design:
- One ``.usearch`` file per namespace (``wiki:<game>``), stored under
  ``<vec_dir>/<safe-namespace>.usearch``. Dropping a namespace = deleting the
  file + a SQL ``DELETE`` — HNSW's weak batch-deletion story is sidestepped
  structurally.
- Keys are ``memory_blocks.rowid`` (u64); sqlite remains the single source of
  truth for content/metadata, so the index is always rebuildable from a sync.
- Indexes are lazily loaded on first touch and kept open for the process
  lifetime (they are small: ~200 MB for 50k x 1024d f32).
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

import numpy as np
from usearch.index import Index

_LOGGER = logging.getLogger(__name__)

_DEFAULT_NDIM = 1024  # bge-m3


def _safe_name(namespace: str) -> str:
    """Map a namespace to a filesystem-safe index file stem."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", namespace).strip("-") or "default"


class VectorIndexStore:
    """Lazily-opened per-namespace USearch HNSW indexes."""

    def __init__(self, vec_dir: str | Path, ndim: int = _DEFAULT_NDIM):
        self._dir = Path(vec_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ndim = ndim
        self._indexes: dict[str, Index] = {}
        self._lock = threading.Lock()

    def _path(self, namespace: str) -> Path:
        return self._dir / f"{_safe_name(namespace)}.usearch"

    def _open(self, namespace: str) -> Index:
        with self._lock:
            idx = self._indexes.get(namespace)
            if idx is not None:
                return idx
            path = self._path(namespace)
            idx = Index(ndim=self._ndim, metric="cos", dtype="f32")
            if path.exists():
                try:
                    idx.load(str(path))
                    _LOGGER.info("vector index loaded: %s (%d keys)", path, len(idx))
                except Exception as exc:  # noqa: BLE001 - binding may raise any error type on corrupt files; recovery path must catch all
                    # Corrupt/partial index file → rebuild from scratch (sqlite
                    # is the source of truth; sync will repopulate).
                    _LOGGER.warning("vector index %s unreadable (%s); starting empty", path, exc)
                    idx = Index(ndim=self._ndim, metric="cos", dtype="f32")
            self._indexes[namespace] = idx
            return idx

    def add(self, namespace: str, keys: list[int], vectors: np.ndarray) -> None:
        if not keys:
            return
        idx = self._open(namespace)
        vecs = np.asarray(vectors, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        keys_arr = np.asarray(keys, dtype=np.uint64)
        with self._lock:
            idx.add(keys_arr, vecs)
            idx.save(str(self._path(namespace)))

    def remove(self, namespace: str, keys: list[int]) -> None:
        if not keys or not self._path(namespace).exists():
            return
        idx = self._open(namespace)
        with self._lock:
            for k in keys:
                try:
                    idx.remove(int(k))
                except Exception as exc:  # noqa: BLE001 - binding error type varies; absent key must stay idempotent
                    # Key absent is fine (idempotent deletes).
                    _LOGGER.debug("vector remove skipped for key %s: %s", k, exc)
            idx.save(str(self._path(namespace)))

    def search(self, namespace: str, vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        """Return ``[(rowid, cosine_similarity)]`` best-first; similarity = 1 - distance."""
        if not self._path(namespace).exists():
            return []
        idx = self._open(namespace)
        if len(idx) == 0:
            return []
        vec = np.asarray(vector, dtype=np.float32)
        with self._lock:
            matches = idx.search(vec, min(int(k), len(idx)))
        return [(int(key), float(1.0 - dist)) for key, dist in zip(matches.keys, matches.distances)]

    def drop_namespace(self, namespace: str) -> bool:
        """Delete the whole namespace index file. Returns True if a file was removed."""
        with self._lock:
            self._indexes.pop(namespace, None)
            path = self._path(namespace)
            if path.exists():
                path.unlink()
                _LOGGER.info("vector index dropped: %s", path)
                return True
            return False

    def count(self, namespace: str) -> int:
        if not self._path(namespace).exists():
            return 0
        return len(self._open(namespace))

    def close(self) -> None:
        with self._lock:
            for ns, idx in self._indexes.items():
                try:
                    idx.save(str(self._path(ns)))
                except Exception as exc:  # noqa: BLE001 - best-effort cleanup on shutdown (matches sqlite close pattern)
                    _LOGGER.warning("vector index save failed for %s: %s", ns, exc)
            self._indexes.clear()
