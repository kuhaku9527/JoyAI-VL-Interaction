# SPDX-License-Identifier: Apache-2.0
"""Network/proxy configuration (Local Wiki ADR-0012, tasks B1/B2/B4).

Per-provider proxy design: every outbound call resolves its proxy through
``client_factory.proxy_url_for(provider)`` instead of a global
``HTTPS_PROXY`` env var. This keeps domestic traffic (SiliconFlow, MiniMax)
on a direct route while still allowing Gemini — if ever enabled — to hop
through a local Clash instance. The proxy itself is *reserved* for phase 1:
it defaults to disabled and all providers default to ``use_proxy=false``, so
real traffic in phase 1 is fully direct. See design doc §4.

The config lives in a JSON file (path via ``MEMORY_NETWORK_CONFIG_PATH``,
default ``data/network_config.json``) so the settings UI can persist changes
without a restart. ``update_network_config`` hot-reloads the in-memory store
and invalidates the client factory cache so subsequent calls pick up the new
proxy routing immediately.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

_LOGGER = logging.getLogger(__name__)


class ProxyConfig(BaseModel):
    """Global proxy switch (reserved; disabled in phase 1)."""

    enabled: bool = False
    url: str = "http://127.0.0.1:7890"


class ProviderNetConfig(BaseModel):
    """Per-provider proxy opt-in. Rejects a global proxy in favour of this."""

    use_proxy: bool = False


# Defaults: SiliconFlow + MiniMax are domestic (direct); NVIDIA NIM defaults to
# direct too (like siliconflow). Gemini would need a proxy if it is ever
# enabled. The set is extensible via PUT /v1/settings/network.
_DEFAULT_PROVIDERS: dict[str, ProviderNetConfig] = {
    "siliconflow": ProviderNetConfig(use_proxy=False),
    "nvidia": ProviderNetConfig(use_proxy=False),
    "minimax": ProviderNetConfig(use_proxy=False),
    "gemini": ProviderNetConfig(use_proxy=True),
}


class NetworkConfig(BaseModel):
    """Top-level network configuration persisted to JSON."""

    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    providers: dict[str, ProviderNetConfig] = Field(
        default_factory=lambda: dict(_DEFAULT_PROVIDERS)
    )

    @classmethod
    def default(cls) -> NetworkConfig:
        """Fresh default config (no disk I/O)."""
        return cls()


def _default_path() -> Path:
    return Path(os.getenv("MEMORY_NETWORK_CONFIG_PATH", "data/network_config.json"))


class NetworkConfigStore:
    """Load/persist :class:`NetworkConfig`; module-level singleton for hot reload."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else _default_path()
        self._config = self._load()

    def _load(self) -> NetworkConfig:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                return NetworkConfig.model_validate(raw)
            except Exception as exc:  # noqa: BLE001 - corrupt config must not crash startup
                _LOGGER.warning(
                    "failed to load network config %s: %s; using defaults", self.path, exc
                )
        return NetworkConfig.default()

    def get(self) -> NetworkConfig:
        """Return the live in-memory network config."""
        return self._config

    def update(self, incoming: NetworkConfig) -> NetworkConfig:
        """Replace in-memory config and persist it to disk."""
        self._config = incoming
        self._persist()
        return self._config

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(self._config.model_dump_json(indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - best-effort persist; non-fatal
            _LOGGER.warning("failed to persist network config %s: %s", self.path, exc)


# Module-level singleton, created lazily on first import with the default path.
_store = NetworkConfigStore()


def get_network_config() -> NetworkConfig:
    """Return the live network config (hot-reloaded on PUT /v1/settings/network)."""
    return _store.get()


def update_network_config(cfg: NetworkConfig) -> NetworkConfig:
    """Persist a new config and invalidate the cached HTTP clients.

    Importing client_factory inside the function avoids a circular import
    (client_factory imports this module at top level).
    """
    updated = _store.update(cfg)
    try:
        from . import client_factory

        client_factory.invalidate()
    except Exception as exc:  # noqa: BLE001 - invalidation is best-effort
        _LOGGER.debug("client factory invalidation skipped: %s", exc)
    return updated


def reset_store(path: str | os.PathLike | None = None) -> NetworkConfigStore:
    """Re-create the singleton (used by tests to point at a temp path)."""
    global _store
    _store = NetworkConfigStore(path)
    try:
        from . import client_factory

        client_factory.invalidate()
    except Exception as exc:  # noqa: BLE001 - best-effort
        _LOGGER.debug("client factory invalidation skipped: %s", exc)
    return _store
