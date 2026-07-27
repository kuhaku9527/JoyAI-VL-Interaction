# SPDX-License-Identifier: Apache-2.0
"""Tests for network/proxy configuration + persistence (ADR-0012, tasks B2/B4)."""

from __future__ import annotations

from memory_store import client_factory, config
from memory_store.config import (
    NetworkConfig,
    NetworkConfigStore,
    ProviderNetConfig,
    ProxyConfig,
    reset_store,
    update_network_config,
)


def test_defaults_are_direct_except_gemini():
    cfg = NetworkConfig.default()
    assert cfg.proxy.enabled is False
    assert cfg.providers["siliconflow"].use_proxy is False
    assert cfg.providers["minimax"].use_proxy is False
    # Gemini is the only reserved opt-in (phase-1 proxy is off globally).
    assert cfg.providers["gemini"].use_proxy is True


def test_store_loads_from_disk(tmp_path):
    path = tmp_path / "net.json"
    path.write_text(
        NetworkConfig(
            proxy=ProxyConfig(enabled=True, url="http://127.0.0.1:8888"),
            providers={"siliconflow": ProviderNetConfig(use_proxy=True)},
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    store = NetworkConfigStore(path)
    cfg = store.get()
    assert cfg.proxy.enabled is True
    assert cfg.proxy.url == "http://127.0.0.1:8888"
    assert cfg.providers["siliconflow"].use_proxy is True


def test_store_corrupt_falls_back_to_default(tmp_path):
    path = tmp_path / "net.json"
    path.write_text("{ this is : not valid json ]", encoding="utf-8")
    store = NetworkConfigStore(path)
    cfg = store.get()
    # Corrupt file must not raise; falls back to defaults.
    assert cfg.proxy.enabled is False
    assert cfg.providers["siliconflow"].use_proxy is False


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "net.json"
    reset_store(path)
    update_network_config(
        NetworkConfig(
            proxy=ProxyConfig(enabled=True, url="http://127.0.0.1:7890"),
            providers={"siliconflow": ProviderNetConfig(use_proxy=True)},
        )
    )
    # A fresh store reading the same file reflects the persisted config.
    reloaded = NetworkConfigStore(path).get()
    assert reloaded.proxy.enabled is True
    assert reloaded.providers["siliconflow"].use_proxy is True


def test_update_reflects_and_invalidates_factory(tmp_path, monkeypatch):
    reset_store(str(tmp_path / "net.json"))
    invalidations = []

    def _spy():
        invalidations.append(1)

    monkeypatch.setattr(client_factory, "invalidate", _spy)
    update_network_config(
        NetworkConfig(
            proxy=ProxyConfig(enabled=True), providers={"gemini": ProviderNetConfig(use_proxy=True)}
        )
    )
    # get_network_config reflects the new value...
    assert config.get_network_config().proxy.enabled is True
    assert config.get_network_config().providers["gemini"].use_proxy is True
    # ...and the client factory cache was invalidated.
    assert invalidations == [1]
