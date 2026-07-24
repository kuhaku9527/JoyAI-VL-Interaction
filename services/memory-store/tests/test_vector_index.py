# SPDX-License-Identifier: Apache-2.0
"""VectorIndexStore (USearch sidecar) tests."""

from __future__ import annotations

import numpy as np
from memory_store.vector_index import VectorIndexStore


def _vec(dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def test_add_search_and_persist(tmp_path):
    store = VectorIndexStore(tmp_path / "vec", ndim=8)
    dim = 8
    v1, v2 = _vec(dim, 1), _vec(dim, 2)
    store.add("wiki:test", [1, 2], np.stack([v1, v2]))

    hits = store.search("wiki:test", v1, k=2)
    assert hits, "expected hits after add"
    assert hits[0][0] == 1, "nearest neighbor of v1 should be key 1"
    assert hits[0][1] > hits[1][1], "hits sorted best-first"

    # Persisted file reloads in a fresh store.
    store.close()
    store2 = VectorIndexStore(tmp_path / "vec", ndim=8)
    hits2 = store2.search("wiki:test", v2, k=1)
    assert hits2 and hits2[0][0] == 2


def test_namespace_isolation(tmp_path):
    store = VectorIndexStore(tmp_path / "vec", ndim=8)
    store.add("wiki:a", [1], _vec(8, 1))
    assert store.search("wiki:b", _vec(8, 1), k=1) == [], "other namespace must be empty"
    assert store.count("wiki:a") == 1
    assert store.count("wiki:b") == 0


def test_remove_and_drop(tmp_path):
    store = VectorIndexStore(tmp_path / "vec", ndim=8)
    store.add("wiki:a", [1, 2], np.stack([_vec(8, 1), _vec(8, 2)]))
    store.remove("wiki:a", [1])
    hits = store.search("wiki:a", _vec(8, 1), k=5)
    assert all(key != 1 for key, _ in hits), "removed key must not appear"

    assert store.drop_namespace("wiki:a") is True
    assert store.count("wiki:a") == 0
    assert store.drop_namespace("wiki:a") is False, "second drop is a no-op"


def test_corrupt_index_file_recovers_empty(tmp_path):
    vec_dir = tmp_path / "vec"
    vec_dir.mkdir(exist_ok=True)
    (vec_dir / "wiki-broken.usearch").write_bytes(b"not-a-valid-index")
    store = VectorIndexStore(vec_dir, ndim=8)
    store.add("wiki:broken", [1], _vec(8, 1))
    assert store.count("wiki:broken") == 1, "corrupt index should be rebuilt empty"
