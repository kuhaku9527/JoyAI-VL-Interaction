# SPDX-License-Identifier: Apache-2.0
"""Tests for the per-provider HTTP client factory (ADR-0012, task B1)."""

from __future__ import annotations

from memory_store import client_factory
from memory_store.config import NetworkConfig, ProviderNetConfig, ProxyConfig, reset_store


def _set_config(tmp_path, proxy_enabled: bool, use_proxy: dict[str, bool]) -> None:
    """Point the config singleton at a temp file with the given settings."""
    reset_store(str(tmp_path / "network_config.json"))
    net = NetworkConfig(
        proxy=ProxyConfig(enabled=proxy_enabled, url="http://127.0.0.1:7890"),
        providers={
            name: ProviderNetConfig(use_proxy=use_proxy.get(name, False))
            for name in ("siliconflow", "minimax", "gemini")
        },
    )
    # update_network_config persists + invalidates the client cache.
    from memory_store.config import update_network_config

    update_network_config(net)


def test_proxy_url_for_combinations(tmp_path):
    # Provider absent from the map → direct (never proxied).
    _set_config(tmp_path, proxy_enabled=False, use_proxy={})
    assert client_factory.proxy_url_for("openai") is None

    # Global proxy off: siliconflow (use_proxy=False) and gemini (use_proxy=True)
    # must both be direct.
    _set_config(tmp_path, proxy_enabled=False, use_proxy={"siliconflow": False, "gemini": True})
    assert client_factory.proxy_url_for("siliconflow") is None
    assert client_factory.proxy_url_for("gemini") is None

    # Global proxy on, gemini opts in → proxied; siliconflow stays direct.
    _set_config(tmp_path, proxy_enabled=True, use_proxy={"siliconflow": False, "gemini": True})
    assert client_factory.proxy_url_for("gemini") == "http://127.0.0.1:7890"
    assert client_factory.proxy_url_for("siliconflow") is None

    # Global proxy on, siliconflow opts in → proxied.
    _set_config(tmp_path, proxy_enabled=True, use_proxy={"siliconflow": True})
    assert client_factory.proxy_url_for("siliconflow") == "http://127.0.0.1:7890"


def test_get_sync_client_caches_per_provider(tmp_path):
    _set_config(tmp_path, proxy_enabled=False, use_proxy={})
    client_factory.invalidate()
    c1 = client_factory.get_sync_client("siliconflow")
    c2 = client_factory.get_sync_client("siliconflow")
    assert c1 is c2, "same provider must reuse the cached client"
    assert not c1.is_closed


def test_invalidate_rebuilds_client(tmp_path):
    _set_config(tmp_path, proxy_enabled=False, use_proxy={})
    client_factory.invalidate()
    c1 = client_factory.get_sync_client("siliconflow")
    client_factory.invalidate()
    c2 = client_factory.get_sync_client("siliconflow")
    assert c1 is not c2, "invalidate must drop the cached client"
    assert c1.is_closed, "old client should be closed on invalidate"
