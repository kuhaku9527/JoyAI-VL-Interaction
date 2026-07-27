# SPDX-License-Identifier: Apache-2.0
"""bge-m3 dual-mode embedder (ADR-0012).

Space-consistency rule: the model that embeds documents MUST be the model that
embeds queries — otherwise distance is meaningless. bge-m3 is uniquely suited
because the same weights are available both locally (offline bulk ingest, free,
no rate limits) and via a hosted OpenAI-compatible API (online recall).

Provider selection (``EMBEDDING_PROVIDER`` env or ``provider`` arg):

- ``nvidia`` (default): NVIDIA NIM ``baai/bge-m3`` endpoint
  (``https://integrate.api.nvidia.com/v1``), authenticated via ``NVIDIA_API_KEY``.
  NIM requires an ``input_type`` of ``query`` (recall) or ``passage`` (ingest)
  on the embeddings call.
- ``siliconflow``: SiliconFlow hosted API (``https://api.siliconflow.cn/v1``),
  authenticated via ``SILICONFLOW_API_KEY``. Selectable via
  ``EMBEDDING_PROVIDER=siliconflow`` — the original behaviour is preserved.
- ``local``: local FlagEmbedding/sentence-transformers weights when installed
  (offline bulk ingest, free, no rate limits).

Preprocessing lives in exactly one place (``_prepare``) so document and query
paths can never diverge. bge-m3 outputs are already L2-normalized — do NOT
normalize again.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time

import numpy as np

_LOGGER = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://api.siliconflow.cn/v1"
_DEFAULT_MODEL = "BAAI/bge-m3"
_NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
_NVIDIA_MODEL = "baai/bge-m3"
_NVIDIA_KEY_ENV = "NVIDIA_API_KEY"
_EMBED_DIM = 1024


class EmbedderError(RuntimeError):
    """Raised when embedding fails; callers fall back to FTS5 BM25."""


def content_hash(text: str) -> str:
    """Stable hash for incremental re-embedding (sync skips unchanged chunks)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _prepare(text: str, *, is_query: bool) -> str:
    """Single-point preprocessing for both document and query embedding.

    bge-m3 works fine without instruction prefixes for both sides; keeping
    both sides identical is what matters. Whitespace is normalized so locally
    ingested chunks and API-embedded queries see the same token stream.
    """
    del is_query  # currently identical; hook kept for future divergence
    return " ".join(text.split())


class BgeM3Embedder:
    """Dual-mode bge-m3 embedder with API-first recall and local bulk ingest."""

    def __init__(
        self,
        provider: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ):
        # Default provider is now nvidia; siliconflow remains selectable via
        # EMBEDDING_PROVIDER=siliconflow (see ADR-0012 provider switch).
        self.provider = (provider or os.getenv("EMBEDDING_PROVIDER", "nvidia")).lower()
        if self.provider == "nvidia":
            default_api_base = _NVIDIA_API_BASE
            default_model = _NVIDIA_MODEL
            key_env = _NVIDIA_KEY_ENV
        else:
            default_api_base = _DEFAULT_API_BASE
            default_model = _DEFAULT_MODEL
            key_env = "SILICONFLOW_API_KEY"
        self.api_base = (api_base or os.getenv("EMBEDDING_API_BASE", default_api_base)).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv(key_env, "")
        self.model = model or os.getenv("EMBEDDING_MODEL", default_model)
        self._timeout = timeout
        self._local_model = None  # lazy

    # -- public API ---------------------------------------------------------

    @property
    def dim(self) -> int:
        """Embedding dimensionality (bge-m3 = 1024)."""
        return _EMBED_DIM

    def available(self) -> bool:
        """Whether the recall (API) path is configured. Local mode counts too."""
        if self.provider == "none":
            return False
        if self.provider == "local":
            return True
        return bool(self.api_key)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single query string (online recall path)."""
        return self.embed_texts([text], is_query=True)[0]

    def embed_texts(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        """Embed texts, returning an ``(n, dim)`` float32 array.

        Provider selection: ``local`` → local weights; otherwise the selected
        API (default nvidia NIM, or siliconflow when ``EMBEDDING_PROVIDER`` is
        set). Raises EmbedderError on failure — callers implement fail-open.
        """
        if not texts:
            return np.zeros((0, _EMBED_DIM), dtype=np.float32)
        prepared = [_prepare(t, is_query=is_query) for t in texts]
        if self.provider == "local":
            return self._embed_local(prepared)
        return self._embed_api(prepared, is_query=is_query)

    def health(self) -> dict:
        """Real ping through the same config path as actual calls."""
        if self.provider == "none":
            return {"ok": False, "provider": "none", "error": "embedding disabled"}
        started = time.perf_counter()
        try:
            vec = self.embed_query("ping")
            latency_ms = round((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "provider": self.provider,
                "model": self.model,
                "dim": int(vec.shape[0]),
                "latency_ms": latency_ms,
            }
        except EmbedderError as exc:
            return {"ok": False, "provider": self.provider, "model": self.model, "error": str(exc)}

    # -- providers ----------------------------------------------------------

    def _embed_api(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        if not self.api_key:
            raise EmbedderError(f"{self.provider} API key not set")
        # Route through the per-provider client factory so proxy configuration
        # (reserved for phase 1) is honoured instead of a global HTTPS_PROXY.
        from . import client_factory

        # NVIDIA NIM's bge-m3 endpoint requires an ``input_type`` discriminator
        # (``query`` for recall, ``passage`` for ingest); siliconflow's
        # OpenAI-compatible endpoint does not accept it. Keep the two payloads
        # distinct so neither provider rejects the request.
        payload = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.provider == "nvidia":
            payload["input_type"] = "query" if is_query else "passage"
            payload["truncate"] = "NONE"
        client = client_factory.get_sync_client(self.provider)
        try:
            resp = client.post(
                f"{self.api_base}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise EmbedderError(f"embedding API call failed: {exc}") from exc
        try:
            items = sorted(data["data"], key=lambda d: d["index"])
            vecs = np.asarray([d["embedding"] for d in items], dtype=np.float32)
        except Exception as exc:
            raise EmbedderError(f"embedding API response malformed: {exc}") from exc
        if vecs.shape != (len(texts), _EMBED_DIM):
            raise EmbedderError(
                f"unexpected embedding shape {vecs.shape}, expected {(len(texts), _EMBED_DIM)}"
            )
        return vecs

    def _embed_local(self, texts: list[str]) -> np.ndarray:
        model = self._get_local_model()
        try:
            vecs = model.encode(
                texts,
                batch_size=32,
                normalize_embeddings=True,  # bge-m3 convention (already L2)
                show_progress_bar=False,
            )
        except Exception as exc:
            raise EmbedderError(f"local embedding failed: {exc}") from exc
        return np.asarray(vecs, dtype=np.float32)

    def _get_local_model(self):
        if self._local_model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbedderError(
                    "local embedding requires sentence-transformers "
                    "(pip install 'memory-store[local-embed]') or set EMBEDDING_PROVIDER=siliconflow"
                ) from exc
            name = os.getenv("EMBEDDING_LOCAL_MODEL", _DEFAULT_MODEL)
            _LOGGER.info("loading local embedding model %s ...", name)
            self._local_model = SentenceTransformer(name)
        return self._local_model


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for two 1-D vectors (used by the parity check tool)."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
