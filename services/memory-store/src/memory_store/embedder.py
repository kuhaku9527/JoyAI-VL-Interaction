# SPDX-License-Identifier: Apache-2.0
"""bge-m3 dual-mode embedder (ADR-0012 v6).

Space-consistency rule: the model that embeds documents MUST be the model that
embeds queries — otherwise distance is meaningless. bge-m3 is uniquely suited
because the same weights are available both locally (offline bulk ingest, free,
no rate limits) and via a hosted OpenAI-compatible API (online recall).

Provider selection (``EMBEDDING_PROVIDER`` env or ``provider`` arg, ADR-0012 §6
provider switch):

- ``local`` (default): local sentence-transformers weights. The path the test
  harness and CI use today; works offline as long as the weights are present at
  ``EMBEDDING_LOCAL_MODEL`` (default ``BAAI/bge-m3``). Zero network dependency,
  zero quota, predictable latency. **The default was switched from ``nvidia``
  → ``local`` in PR #42 to restore the v5 "open the box and it works"**
  contract; ``nvidia`` and ``siliconflow`` remain selectable for parity /
  cross-validation.
- ``siliconflow``: SiliconFlow hosted API (``https://api.siliconflow.cn/v1``),
  authenticated via ``SILICONFLOW_API_KEY``. Original v5 default. Useful when
  the local weights are missing or as a sanity check for the local path.
- ``nvidia``: NVIDIA NIM ``baai/bge-m3`` endpoint
  (``https://integrate.api.nvidia.com/v1``), authenticated via ``NVIDIA_API_KEY``.
  Requires an ``input_type`` of ``query`` (recall) or ``passage`` (ingest) on
  the embeddings call. Use only when proxy + quota are validated — see
  ADR-0012 §6 for the cutoff before reaching for it.

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
        # Default provider is local (offline-friendly, no quota, no proxy):
        # #42 reverted #38's ad-hoc change to ``nvidia`` because the new
        # default did not work out of the box for users without a NVIDIA NIM
        # key, and there was no ADR entry to back the change. Each provider is
        # still selectable via ``EMBEDDING_PROVIDER`` — see the module docstring
        # and ADR-0012 §6.
        self.provider = (provider or os.getenv("EMBEDDING_PROVIDER", "local")).lower()
        if self.provider == "nvidia":
            default_api_base = _NVIDIA_API_BASE
            default_model = _NVIDIA_MODEL
            key_env = _NVIDIA_KEY_ENV
        elif self.provider == "siliconflow":
            default_api_base = _DEFAULT_API_BASE
            default_model = _DEFAULT_MODEL
            key_env = "SILICONFLOW_API_KEY"
        elif self.provider == "local":
            # No API base / key needed for local inference; the toggles below
            # are placeholders so the dataclass shape stays uniform.
            default_api_base = ""
            default_model = os.getenv("EMBEDDING_LOCAL_MODEL", _DEFAULT_MODEL)
            key_env = ""
        else:
            raise ValueError(
                f"unknown EMBEDDING_PROVIDER={self.provider!r}; "
                "expected one of: local, siliconflow, nvidia"
            )
        self.api_base = (api_base or os.getenv("EMBEDDING_API_BASE", default_api_base)).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv(key_env, "")
        self.model = model or os.getenv("EMBEDDING_MODEL", default_model)
        self._timeout = timeout
        self._local_model = None  # lazy
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
            # Fail-open: still report available so callers attempt embedding,
            # but warn loudly if the local weights path is missing. A missing
            # or wrong EMBEDDING_LOCAL_MODEL is silent config drift (FA-4)
            # that otherwise only surfaces as empty recall -- never crash here.
            model_path = os.getenv("EMBEDDING_LOCAL_MODEL", "")
            if model_path and os.path.isdir(model_path):
                return True
            _LOGGER.warning(
                "local provider selected but EMBEDDING_LOCAL_MODEL=%r is unset or "
                "not a directory; embedding will fail to load weights",
                model_path or "(unset)",
            )
            return True
        return bool(self.api_key)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a single query string (online recall path)."""
        return self.embed_texts([text], is_query=True)[0]

    def embed_texts(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        """Embed texts, returning an ``(n, dim)`` float32 array.

        Provider selection: ``local`` → local weights; otherwise the selected
        API (``siliconflow`` or ``nvidia`` when ``EMBEDDING_PROVIDER`` is set).
        Raises EmbedderError on failure — callers implement fail-open.
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
                    "(pip install 'memory-store[local-embed]') or set "
                    "EMBEDDING_PROVIDER=siliconflow"
                ) from exc
            # Honour EMBEDDING_LOCAL_MODEL when set; otherwise fall back to the
            # bge-m3 default. The override path lets users point at a local
            # weights checkout (e.g. D:/AI/models/bge-m3) without the HF cache
            # being populated.
            name = self.model if self.model else os.getenv("EMBEDDING_LOCAL_MODEL", _DEFAULT_MODEL)
            _LOGGER.info("loading local embedding model %s ...", name)
            self._local_model = SentenceTransformer(name)
        return self._local_model


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for two 1-D vectors (used by the parity check tool)."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
