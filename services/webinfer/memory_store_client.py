"""memory-store v0.2 client.

Thin async wrapper over the memory-store JSON API. Construction is
fail-closed: ``__init__`` raises if neither an explicit ``base_url`` nor the
``MEMORY_STORE_URL`` env var is supplied, instead of silently defaulting to
the legacy empty-shell port 8996. Once constructed, the request methods stay
fail-soft: if the upstream is unreachable they return empty results and log a
warning rather than raising to the caller.

Protocol targets lock at the v0.1 skeleton spec — see
``doc/specs/memory-store-skeleton-spec.md`` D-3 (data model) and D-2
(endpoints). The endpoint URLs intentionally match that document.

Endpoints used:

- ``POST /v1/blocks/push`` — ingest a list of ``MemoryBlock``-shaped dicts
- ``POST /v1/blocks/recall`` — retrieve by query or ``__warmup__`` keyword
- ``GET  /health`` — connectivity / version probe
- ``GET  /v1/backends`` — list active + available backends

The client is stateless except for a single async ``httpx.AsyncClient`` that
is shared across calls. It is safe to construct once per ``StreamingInferAdapter``
instance; the adapter calls ``aclose()`` from ``stop_background_tasks``.

Only standard-library + ``httpx`` (already declared as a transitive dep via
``FastAPI`` in the memory-store pyproject) are used; nothing here is
specific to the webinfer process model.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import httpx

# --- ADR-0014 JSONL event emission (services/common/event_json.py) ----------
try:

    def _ensure_event_json_importable() -> None:
        """Put ``services/common`` on ``sys.path`` by walking up from this file.

        Returns without inserting if the shared emitter cannot be located;
        the subsequent import then raises ImportError, which is caught below
        and downgraded to a logged no-op (约法三章: not silent, just not fatal).
        """
        here = os.path.dirname(os.path.abspath(__file__))
        cur = here
        while True:
            common = os.path.join(cur, "services", "common")
            if os.path.exists(os.path.join(common, "event_json.py")):
                if common not in sys.path:
                    sys.path.insert(0, common)
                return
            parent = os.path.dirname(cur)
            if parent == cur:
                return
            cur = parent

    _ensure_event_json_importable()
    from event_json import emit_event
except ImportError:
    logging.getLogger(__name__).warning(
        "event_json emitter unavailable; JSONL event emission disabled "
        "(packaged build without services/common on path?)"
    )

    def emit_event(*_args, **_kwargs):
        """No-op fallback used only when the shared emitter is unavailable.

        Logged once above (not silent) per 约法三章 - never swallow the failure.
        """
        return None


LOGGER = logging.getLogger("streaming_infer_adapter.memory_client")

# Real backend port 8997. Retained only as a defensive last-resort fallback:
# the fail-closed guard in ``__init__`` raises before this is reached for any
# realistic caller (base_url is a truthy URL or None, and None-without-env
# already raised), so this third operand is effectively unreachable in normal
# operation. It still guards the degenerate empty-string ``base_url`` case,
# pointing it at the live backend instead of the deprecated empty-shell 8996.
DEFAULT_BASE_URL = "http://127.0.0.1:8997"
DEFAULT_TIMEOUT_S = 5.0


def _now_iso() -> str:
    """ISO-8601 UTC, second precision. Match memory-store schema requirement."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_block(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Trim/validate an upstream memory-store block to the keys live_adapter actually consumes.

    Return ``None`` if the row is unusable so callers can skip it without crashing.
    """
    if not isinstance(raw, dict):
        return None
    content = raw.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    block_id = raw.get("block_id")
    if not isinstance(block_id, str) or not block_id:
        block_id = ""
    return {
        "block_id": block_id,
        "content": content.strip(),
        "session_id": raw.get("session_id") or "",
        "score": float(raw.get("score") or 0.0),
        "created_at": raw.get("created_at") or "",
        "last_hit_at": raw.get("last_hit_at"),
        "hit_count": int(raw.get("hit_count") or 0),
    }


class MemoryStoreClient:
    """Async wrapper around the memory-store JSON API.

    Construct one per adapter, then ``await warmup(...)``,
    ``recall(...)`` and ``push(...)`` per session lifecycle.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        enabled: bool = True,
    ) -> None:
        # Fail-closed: refuse to silently fall back to the legacy empty-shell
        # port 8996. If neither an explicit ``base_url`` nor the
        # ``MEMORY_STORE_URL`` environment variable is supplied, raise instead
        # of defaulting to a dead endpoint — a historical incident had wiki
        # recall silently failing against the empty-shell port.
        env_url = os.environ.get("MEMORY_STORE_URL")
        if base_url is None and not env_url:
            raise ValueError(
                "MEMORY_STORE_URL is not set; refusing to fall back to legacy "
                "empty-shell port 8996. Set MEMORY_STORE_URL to the real "
                "memory-store backend, e.g. http://127.0.0.1:8997"
            )
        self.base_url = (base_url or env_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = float(timeout_s)
        self.enabled = bool(enabled)
        # We avoid eagerly opening the client so a misconfigured URL does not
        # spam warnings during tests. Callers that want a connection still
        # get one on the first request.
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._healthy: bool | None = None
        # --- Circuit breaker (v0.3, 2026-07-29) ---------------------
        # When ``memory-store`` is unreachable every recall/warmup/push
        # call would otherwise pay the full ``timeout_s`` (default 5s)
        # before failing-open. After ``_CB_FAILURE_THRESHOLD`` consecutive
        # failures the circuit opens for ``_CB_COOLDOWN_S`` seconds and
        # subsequent calls short-circuit to ``[]`` without touching the
        # network. A successful call resets the counter and re-closes.
        self._cb_failure_count: int = 0
        self._cb_open_until_monotonic: float = 0.0

    # Circuit breaker thresholds (module-level constants for easy tuning).
    _CB_FAILURE_THRESHOLD = 3
    _CB_COOLDOWN_S = 30.0

    def _circuit_open(self) -> bool:
        """Return True iff the breaker is currently OPEN (calls short-circuit).

        Time-based; if the cooldown has elapsed the breaker is auto-closed
        on the next check so a single probe is allowed through.
        """
        return self._cb_open_until_monotonic > time.monotonic()

    def _record_failure(self) -> None:
        self._cb_failure_count += 1
        if self._cb_failure_count >= self._CB_FAILURE_THRESHOLD:
            if self._cb_open_until_monotonic == 0.0:
                # transition closed -> open: emit exactly once per open window
                emit_event(
                    "webinfer",
                    "circuit_breaker_open",
                    level="warn",
                    extra={"failures_count": self._cb_failure_count},
                )
            self._cb_open_until_monotonic = time.monotonic() + self._CB_COOLDOWN_S
            LOGGER.warning(
                "memory-store circuit OPEN for %.0fs after %d failures",
                self._CB_COOLDOWN_S,
                self._cb_failure_count,
            )

    def _record_success(self) -> None:
        if self._cb_failure_count:
            emit_event(
                "webinfer",
                "circuit_breaker_close",
                level="info",
                extra={"prior_failures": self._cb_failure_count},
            )
            LOGGER.info(
                "memory-store circuit CLOSED after %d prior failure(s)",
                self._cb_failure_count,
            )
        self._cb_failure_count = 0
        self._cb_open_until_monotonic = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout_s,
                    headers={"Content-Type": "application/json"},
                )
            return self._client

    async def aclose(self) -> None:
        """Close the underlying httpx client if it was opened."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @property
    def is_enabled(self) -> bool:
        """True when the client should attempt upstream calls."""
        return self.enabled

    async def ping(self) -> bool:
        """Probe ``/health``.

        Caches the result once a success has been seen so the live adapter
        does not log a warning every chunk.
        """
        if not self.enabled:
            return False
        try:
            client = await self._get_client()
            resp = await client.get("/health")
        except httpx.HTTPError as exc:
            if self._healthy is not False:
                LOGGER.warning("memory-store ping failed: %s", exc)
            self._healthy = False
            return False
        if resp.status_code != 200:
            self._healthy = False
            return False
        self._healthy = True
        return True

    async def warmup(
        self,
        session_id: str,
        top_k: int = 16,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Pull blocks scoped to ``session_id``.

        Uses the spec ``query="__warmup__"`` convention so the backend
        returns the most recent ``top_k`` rows via a dedicated SQL path
        (``_recall_recent``) without running vector or BM25 ranking.
        Safe to call before the first user message.
        """
        if not self.enabled or not session_id:
            return []
        payload = {
            "query": "__warmup__",
            "top_k": max(1, int(top_k)),
            "min_score": float(min_score),
            "filter": {"session_ids": [session_id]},
        }
        if self._circuit_open():
            return []
        try:
            client = await self._get_client()
            resp = await client.post("/v1/blocks/recall", json=payload)
        except httpx.HTTPError as exc:
            LOGGER.warning("memory-store warmup failed for %s: %s", session_id, exc)
            self._record_failure()
            return []
        if resp.status_code != 200:
            LOGGER.warning(
                "memory-store warmup %s returned %s: %s",
                session_id,
                resp.status_code,
                resp.text[:200],
            )
            self._record_failure()
            return []
        self._record_success()
        try:
            body = resp.json()
        except ValueError:
            return []
        return [b for b in (_normalize_block(b) for b in body.get("blocks", [])) if b]

    async def recall(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 6,
        min_score: float = 0.0,
        namespaces: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Pull blocks similar to ``query``.

        Optional ``session_id`` and ``namespaces`` filters.

        ``namespaces`` is the ADR-0012 L1 isolation gate: the backend filters
        untrusted wiki scrubs from the same session view by routing the
        recall through ``filter.namespaces`` (wildcards like ``wiki:*`` are
        expanded by the backend). When both ``session_id`` and ``namespaces``
        are given, the two filter clauses are merged as a permissive AND.
        """
        if not self.enabled or not query:
            return []
        payload: dict[str, Any] = {
            "query": query,
            "top_k": max(1, int(top_k)),
            "min_score": float(min_score),
        }
        filter_clause: dict[str, Any] = {}
        if session_id:
            filter_clause["session_ids"] = [session_id]
        if namespaces:
            filter_clause["namespaces"] = list(namespaces)
        if filter_clause:
            payload["filter"] = filter_clause
        if self._circuit_open():
            return []
        try:
            client = await self._get_client()
            resp = await client.post("/v1/blocks/recall", json=payload)
        except httpx.HTTPError as exc:
            LOGGER.warning("memory-store recall failed: %s", exc)
            self._record_failure()
            return []
        if resp.status_code != 200:
            LOGGER.warning(
                "memory-store recall returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            self._record_failure()
            return []
        self._record_success()
        try:
            body = resp.json()
        except ValueError:
            return []
        return [b for b in (_normalize_block(b) for b in body.get("blocks", [])) if b]

    async def push(
        self,
        session_id: str,
        blocks: Iterable[dict[str, Any]],
    ) -> int:
        """Push a batch of blocks.

        Returns count actually accepted; 0 on failure (never raises).
        """
        if not self.enabled or not session_id:
            return 0
        cleaned: list[dict[str, Any]] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            content = b.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            cleaned.append(
                {
                    "content": content.strip(),
                    "score": float(b.get("score") or 1.0),
                    # ``created_at`` is generated server-side if absent; we
                    # only forward what we explicitly know.
                }
            )
        if not cleaned:
            return 0
        payload = {"session_id": session_id, "blocks": cleaned}
        if self._circuit_open():
            return 0
        try:
            client = await self._get_client()
            resp = await client.post("/v1/blocks/push", json=payload)
        except httpx.HTTPError as exc:
            LOGGER.warning("memory-store push failed for %s: %s", session_id, exc)
            self._record_failure()
            return 0
        if resp.status_code != 200:
            LOGGER.warning(
                "memory-store push %s returned %s: %s",
                session_id,
                resp.status_code,
                resp.text[:200],
            )
            self._record_failure()
            return 0
        self._record_success()
        try:
            pushed = int(resp.json().get("pushed", 0))
        except ValueError:
            return 0
        if pushed:
            emit_event(
                "webinfer",
                "push_memory",
                level="info",
                session_id=session_id,
                extra={"pushed": pushed},
            )
        return pushed

    async def push_block(
        self,
        session_id: str,
        content: str,
        score: float = 1.0,
    ) -> int:
        """Return a convenience helper for the ``_memory_push`` flush path."""
        return await self.push(
            session_id,
            [{"content": content, "score": score}],
        )

    def health_snapshot(self) -> dict[str, Any]:
        """Return a cached health view (no IO). Useful in sync handler paths.

        Reads the last cached ``_healthy`` value set by :meth:`ping`. Returns
        ``healthy=None`` when ping has never been called yet.
        """
        if not self.enabled:
            return {"enabled": False, "healthy": False, "url": self.base_url}
        return {"enabled": True, "healthy": self._healthy, "url": self.base_url}
