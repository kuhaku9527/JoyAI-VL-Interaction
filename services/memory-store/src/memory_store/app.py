# SPDX-License-Identifier: Apache-2.0
"""memory-store FastAPI entrypoint (spec §D-1, §D-2)."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import __version__
from .backends import get_backend
from .models import (
    PushRequest,
    PushResponse,
    RecallRequest,
    RecallResponse,
)

logger = logging.getLogger("memory_store")
if not logger.handlers:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s memory_store %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(os.getenv("MEMORY_LOG_LEVEL", "INFO"))


# Module-level so ASGI test clients (without lifespan) can reach the backend.
app = FastAPI(title="JoyAI Memory Store", version=__version__)
app.state.backend = get_backend()
logger.info("memory-store v%s loaded backend=%s", __version__, app.state.backend.name())


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    app.state.backend = get_backend()


@app.get("/health")
async def health() -> dict:
    backend = app.state.backend
    try:
        h = await backend.health()
    except NotImplementedError as exc:
        return JSONResponse(
            status_code=501,
            content={"ok": False, "backend": backend.name(), "error": str(exc)},
        )
    return h


@app.get("/v1/backends")
async def list_backends() -> dict:
    backend = app.state.backend
    return {
        "active": backend.name(),
        "available": ["sqlite", "psql", "obsidian"],
    }


@app.post("/v1/blocks/push", response_model=PushResponse)
async def push_blocks(req: PushRequest) -> PushResponse:
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
    backend = app.state.backend
    try:
        blocks = await backend.recall(req.query, req.top_k, req.min_score, req.filter)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return RecallResponse(blocks=blocks)


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
