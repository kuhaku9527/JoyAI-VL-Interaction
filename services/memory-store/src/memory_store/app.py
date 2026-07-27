# SPDX-License-Identifier: Apache-2.0
"""memory-store FastAPI entrypoint (spec §D-1, §D-2) + [Local Wiki] endpoints (ADR-0012)."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import __version__
from .backends import get_backend
from .backends.sqlite_backend import SqliteBackend
from .client_factory import proxy_url_for
from .config import NetworkConfig, ProviderNetConfig, get_network_config, update_network_config
from .embedder import BgeM3Embedder
from .models import (
    DropNamespaceResponse,
    NetworkSettingsRequest,
    PushRequest,
    PushResponse,
    RecallRequest,
    RecallResponse,
    SyncRequest,
    SyncResponse,
)
from .wiki_service import drop_wiki_namespace, sync_wiki_dir

logger = logging.getLogger("memory_store")
if not logger.handlers:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s memory_store %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(os.getenv("MEMORY_LOG_LEVEL", "INFO"))


def _build_sqlite_backend() -> SqliteBackend:
    """Assemble sqlite backend with wiki dependencies (embedder, vec dir)."""
    name = os.getenv("MEMORY_BACKEND", "sqlite").lower()
    if name != "sqlite":
        raise ValueError(f"wiki endpoints require sqlite backend, got {name}")
    return SqliteBackend(
        os.getenv("MEMORY_SQLITE_PATH", "./data/memory.sqlite"),
        vec_dir=os.getenv("MEMORY_VEC_DIR"),
        embedder=BgeM3Embedder(),
    )


# Module-level so ASGI test clients (without lifespan) can reach the backend.
app = FastAPI(title="JoyAI Memory Store", version=__version__)
app.state.backend = (
    _build_sqlite_backend()
    if os.getenv("MEMORY_BACKEND", "sqlite").lower() == "sqlite"
    else get_backend()
)
app.state.embedder = (
    app.state.backend.embedder if isinstance(app.state.backend, SqliteBackend) else None
)
logger.info("memory-store v%s loaded backend=%s", __version__, app.state.backend.name())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Close the storage backend gracefully when the app shuts down."""
    try:
        yield
    finally:
        close = getattr(app.state.backend, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.exception("backend close error")


app.router.lifespan_context = lifespan


def _reset_backend_for_tests() -> None:
    """Test helper: re-pick backend from current env (monkeypatch safe)."""
    if os.getenv("MEMORY_BACKEND", "sqlite").lower() == "sqlite":
        app.state.backend = _build_sqlite_backend()
        app.state.embedder = app.state.backend.embedder
    else:
        app.state.backend = get_backend()
        app.state.embedder = None


@app.get("/health")
async def health() -> dict:
    """Liveness/readiness probe for the backend and the configured embedder."""
    backend = app.state.backend
    try:
        h = await backend.health()
    except NotImplementedError as exc:
        return JSONResponse(
            status_code=501,
            content={"ok": False, "backend": backend.name(), "error": str(exc)},
        )
    embedder = getattr(app.state, "embedder", None)
    h["embedding"] = (
        {"configured": embedder.available(), "provider": embedder.provider}
        if embedder is not None
        else {"configured": False}
    )
    return h


@app.get("/v1/backends")
async def list_backends() -> dict:
    """Report the active storage backend and the available alternatives."""
    backend = app.state.backend
    return {
        "active": backend.name(),
        "available": ["sqlite", "psql", "obsidian"],
    }


@app.post("/v1/blocks/push", response_model=PushResponse)
async def push_blocks(req: PushRequest) -> PushResponse:
    """Persist a batch of memory blocks, backfilling per-block session/created_at."""
    backend = app.state.backend
    # Backfill per-block fields that legacy clients (e.g. webinfer) omit.
    # The storage layer requires non-null session_id / created_at, and recall
    # path compares naive datetimes, so created_at must be a naive UTC value.
    for block in req.blocks:
        if block.session_id is None:
            block.session_id = req.session_id
        if block.created_at is None:
            block.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        pushed = await backend.push(req.session_id, req.blocks)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return PushResponse(pushed=pushed, session_id=req.session_id)


@app.post("/v1/blocks/recall", response_model=RecallResponse)
async def recall_blocks(req: RecallRequest) -> RecallResponse:
    """Recall the top-k memory blocks for a query from the active backend."""
    backend = app.state.backend
    try:
        if isinstance(backend, SqliteBackend):
            blocks = await backend.recall(
                req.query, req.top_k, req.min_score, req.filter, req.min_similarity
            )
        else:
            blocks = await backend.recall(req.query, req.top_k, req.min_score, req.filter)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return RecallResponse(blocks=blocks)


# -- [Local Wiki] endpoints ---------------------------------------------------


@app.post("/v1/external/sync", response_model=SyncResponse)
async def external_sync(req: SyncRequest) -> SyncResponse:
    """Sync a ``wiki/<game>`` directory into a namespace (chunk → embed → index)."""
    backend = app.state.backend
    if not isinstance(backend, SqliteBackend):
        raise HTTPException(status_code=501, detail="sync requires sqlite backend")
    if not req.namespace:
        raise HTTPException(status_code=422, detail="namespace required")
    try:
        return sync_wiki_dir(
            backend,
            getattr(app.state, "embedder", None),
            namespace=req.namespace,
            dir_path=req.dir,
            drop_first=req.drop_first,
        )
    except Exception as exc:
        logger.exception("sync failed for namespace %s", req.namespace)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/v1/namespaces/{namespace}", response_model=DropNamespaceResponse)
async def delete_namespace(namespace: str) -> DropNamespaceResponse:
    """Drop a whole game corpus: rows + sidecar vector index file."""
    backend = app.state.backend
    if not isinstance(backend, SqliteBackend):
        raise HTTPException(status_code=501, detail="namespace ops require sqlite backend")
    deleted, index_removed = drop_wiki_namespace(backend, namespace)
    return DropNamespaceResponse(
        namespace=namespace, deleted_rows=deleted, index_file_removed=index_removed
    )


@app.get("/v1/namespaces")
async def list_namespaces() -> dict:
    """Namespace distribution for the webui knowledge-base page."""
    backend = app.state.backend
    if not isinstance(backend, SqliteBackend):
        return {"namespaces": []}
    return {"namespaces": backend.namespace_stats()}


# -- [Local Wiki] provider health + network settings (ADR-0012, B3/B4) -------


def _provider_env(name: str) -> tuple[str | None, str | None]:
    """Read optional external provider endpoint config from env.

    External LLM/summarizer/tts providers are not configured in phase 1; when
    their base URL env is absent we report ``not configured`` rather than a
    fake green. The env keys are ``MEMORY_EXT_<NAME>_URL`` / ``_KEY``.
    """
    upper = name.upper().replace("-", "_")
    base = os.getenv(f"MEMORY_EXT_{upper}_URL")
    key = os.getenv(f"MEMORY_EXT_{upper}_KEY")
    return base, key


async def _ping_external(name: str) -> dict:
    """Real 1-token completion ping for an external provider, same config path.

    Returns ``not configured`` when the provider has no base URL; otherwise
    pings through the per-provider proxy and reports latency or the error.
    """
    base, key = _provider_env(name)
    if not base:
        return {
            "ok": False,
            "configured": False,
            "error": "not configured",
            "hint": f"set MEMORY_EXT_{name.upper().replace('-', '_')}_URL (+_KEY) to enable ping",
        }
    started = time.perf_counter()
    try:
        import httpx

        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(proxy=proxy_url_for(name), timeout=10.0) as client:
            resp = await client.post(
                base,
                headers=headers,
                json={
                    "model": os.getenv(f"MEMORY_EXT_{name.upper().replace('-', '_')}_MODEL", ""),
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
            resp.raise_for_status()
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {"ok": True, "configured": True, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001 - health must report, never 500
        return {
            "ok": False,
            "configured": True,
            "error": str(exc),
            "hint": "check API key / endpoint / network",
        }


async def _ping_memory_store(backend) -> dict:
    """Probe the local sqlite backend through the same path as /health."""
    started = time.perf_counter()
    try:
        h = await backend.health()
        latency_ms = round((time.perf_counter() - started) * 1000)
        result = dict(h)
        result["latency_ms"] = latency_ms
        return result
    except Exception as exc:  # noqa: BLE001 - health must report, never 500
        return {"ok": False, "error": str(exc), "hint": "sqlite backend health failed"}


@app.get("/v1/providers/health")
async def providers_health() -> dict:
    """Multi-provider real health (ADR-0012 §5).

    Every slot is pinged through the *same* config path as real traffic
    (same proxy, key, endpoint) to avoid false greens. External providers
    (main_llm / summarizer / tts) report ``not configured`` until their
    endpoints are set via env.
    """
    backend = app.state.backend
    out: dict = {}
    out["memory_store"] = await _ping_memory_store(backend)
    embedder = getattr(app.state, "embedder", None)
    out["embedding"] = (
        embedder.health() if embedder is not None else {"ok": False, "error": "no embedder"}
    )
    for name in ("main_llm", "summarizer", "tts"):
        out[name] = await _ping_external(name)
    return out


@app.put("/v1/settings/network")
async def put_network_settings(req: NetworkSettingsRequest) -> dict:
    """Update network/proxy config (ADR-0012 §7.1): hot-reload + re-test.

    ``proxy`` and ``providers`` are merged over the current config (omitted
    fields are preserved). The result is persisted, the client factory cache
    is invalidated, and a fresh provider-health snapshot is returned so the
    UI can confirm the change took effect.
    """
    cur = get_network_config()
    proxy_cfg = cur.proxy
    if req.proxy is not None:
        proxy_cfg = type(cur.proxy)(enabled=req.proxy.enabled, url=req.proxy.url)
    merged_providers = dict(cur.providers)
    if req.providers:
        for name, pc in req.providers.items():
            merged_providers[name] = ProviderNetConfig(use_proxy=pc.use_proxy)
    update_network_config(NetworkConfig(proxy=proxy_cfg, providers=merged_providers))
    return await providers_health()


@app.get("/v1/settings/network")
async def get_network_settings() -> dict:
    """Read the live network/proxy config (ADR-0012 §7.1, B4 read path).

    The settings UI loads the current proxy + per-provider opt-in on open;
    this mirrors the persisted :class:`NetworkConfig` exactly so the write
    path (``PUT``) round-trips. Returns ``{"proxy": {...}, "providers": {...}}``.
    """
    return get_network_config().model_dump()


def main() -> int:
    """Console-script entrypoint. Returns non-zero on bind failure (ADR 0005 E)."""
    import uvicorn

    host = os.getenv("MEMORY_HOST", "127.0.0.1")
    port = int(os.getenv("MEMORY_PORT", "8996"))
    reload = os.getenv("MEMORY_RELOAD", "false").lower() in {"1", "true", "yes"}
    # Pre-bind so we can detect conflicts before uvicorn's sys.exit() hides the cause.
    import socket as _socket

    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        logger.error("memory-store cannot bind %s:%s: %s", host, port, exc)
        probe.close()
        return 2
    probe.close()
    try:
        uvicorn.run(
            "memory_store.app:app",
            host=host,
            port=port,
            reload=reload,
            log_level=os.getenv("MEMORY_LOG_LEVEL", "info").lower(),
        )
        return 0
    except OSError as exc:
        logger.error("memory-store failed to start: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
