# SPDX-License-Identifier: Apache-2.0
"""Per-provider HTTP client factory (Local Wiki ADR-0012, task B1).

Every outbound HTTP call in memory-store should obtain its client from here
rather than constructing one ad hoc. The factory resolves the proxy *per
provider* from :mod:`memory_store.config`, so:

* domestic providers (siliconflow, minimax) stay on a direct route;
* a provider may opt into the (reserved) proxy via ``use_proxy=true``;
* there is never a global ``HTTPS_PROXY`` that would silently reroute
  domestic traffic through an unintended egress.

Clients are cached per provider and invalidated whenever the network config
is hot-reloaded (see :func:`config.update_network_config`).
"""

from __future__ import annotations

import logging
import threading

import httpx

from .config import get_network_config

_LOGGER = logging.getLogger(__name__)

_lock = threading.Lock()
_sync_clients: dict[str, httpx.Client] = {}


def proxy_url_for(provider: str) -> str | None:
    """Return the proxy URL for ``provider`` or ``None`` for a direct route.

    A proxy is only returned when BOTH the provider opts in (``use_proxy``)
    AND the global proxy switch is enabled. Otherwise the call is direct.
    """
    cfg = get_network_config()
    pc = cfg.providers.get(provider)
    if pc is None or not pc.use_proxy:
        return None
    if not cfg.proxy.enabled:
        return None
    return cfg.proxy.url or None


def get_sync_client(provider: str, *, timeout: float = 30.0) -> httpx.Client:
    """Return a cached synchronous client for ``provider`` (proxy-aware)."""
    with _lock:
        client = _sync_clients.get(provider)
        if client is not None and not client.is_closed:
            return client
        proxy = proxy_url_for(provider)
        client = (
            httpx.Client(proxy=proxy, timeout=timeout) if proxy else httpx.Client(timeout=timeout)
        )
        _sync_clients[provider] = client
        return client


def invalidate() -> None:
    """Close and drop all cached clients (call after a config hot-reload)."""
    with _lock:
        for client in _sync_clients.values():
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001 - closing is best-effort
                _LOGGER.debug("error closing cached client: %s", exc)
        _sync_clients.clear()
