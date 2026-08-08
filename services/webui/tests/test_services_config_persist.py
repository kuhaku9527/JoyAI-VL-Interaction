"""Regression tests for issue #122: webui services config persistence +
PUT validation hardening.

- Persistence: a successful PUT writes ``config/services.json`` atomically; a
  subsequent "restart" (reset to defaults + re-merge the file) restores the
  values, including ``api_key`` (persisted plaintext, gitignored, 0600).
- PUT validation: an invalid ``api_base`` is rejected with a structured 4xx
  (400 format / 422 unreachable) and is NEVER applied or persisted; a valid,
  reachable config returns 200 and is applied + persisted.

The handlers are exercised through a self-contained aiohttp server (no pytest
plugin needed), mirroring ``test_asr_websocket_failure.py``. Probe functions
are monkeypatched so no real network is touched, and propagation is stubbed so
the tests stay hermetic (no env mutation / webinfer POST).
"""

from __future__ import annotations

import copy
import json
import os
import stat
import sys
from pathlib import Path

import aiohttp
import pytest

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui import server  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_runtime(monkeypatch):
    """Snapshot/restore the live config and stub propagation for hermeticity."""
    snapshot = copy.deepcopy(server._services_config)
    monkeypatch.setattr(server, "_propagate_services_to_runtime", lambda: None)
    yield
    server._services_config.clear()
    server._services_config.update(snapshot)


@pytest.fixture
def persist_path(tmp_path, monkeypatch):
    """Point persistence at a tmp file and start from defaults (no file yet)."""
    path = tmp_path / "config" / "services.json"
    monkeypatch.setattr(server, "_SERVICES_CONFIG_PATH", str(path))
    server._reload_services_config_from_file()
    yield path


def _patch_probes_ok(monkeypatch) -> None:
    """Make every reachability probe report success (no real network)."""
    monkeypatch.setattr(server, "_probe_llm", lambda _u: {"status": "ok", "models": []})
    monkeypatch.setattr(
        server, "_probe_summary", lambda _c: {"ok": True, "endpoint": "x", "code": 200}
    )
    monkeypatch.setattr(
        server, "_probe_tts", lambda _u: {"status": "ok", "endpoint": "x", "code": 200}
    )
    monkeypatch.setattr(server, "_probe_asr", lambda _c: {"ok": True, "model_dir": "x"})


async def _start_server():
    app = aiohttp.web.Application()
    app.router.add_get("/api/services/config", server._services_config_handler)
    app.router.add_put("/api/services/config", server._services_config_handler)
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, "http://127.0.0.1:%d/api/services/config" % port


async def test_put_persists_and_survives_restart(persist_path, monkeypatch):
    _patch_probes_ok(monkeypatch)
    runner, url = await _start_server()
    try:
        new_base = "http://127.0.0.1:8070/v1"
        new_model = "some-model-id"
        new_key = "sk-test-plaintext-key"
        async with (
            aiohttp.ClientSession() as session,
            session.put(
                url,
                json={"llm": {"api_base": new_base, "model": new_model, "api_key": new_key}},
            ) as resp,
        ):
            assert resp.status == 200
            body = await resp.json()
            assert body["llm"]["api_base"] == new_base
            assert body["llm"]["model"] == new_model
            assert body["llm"]["api_key"] == new_key

        # File was written atomically under config/.
        assert persist_path.exists()

        # Simulate a webui restart: reset to defaults then re-merge the file.
        server._reload_services_config_from_file()
        assert server._services_config["llm"]["api_base"] == new_base
        assert server._services_config["llm"]["model"] == new_model
        # api_key is persisted in plaintext so the config survives a restart
        # (local-only, gitignored, 0600 — see issue tradeoff note).
        assert server._services_config["llm"]["api_key"] == new_key

        on_disk = json.loads(persist_path.read_text(encoding="utf-8"))
        assert on_disk["llm"]["api_key"] == new_key
        assert on_disk["llm"]["model"] == new_model

        # File perms: 0600 on POSIX. Windows does not honor Unix modes, so the
        # exact check is skipped there (protection relies on gitignore + local).
        mode = stat.S_IMODE(persist_path.stat().st_mode)
        if os.name != "nt":
            assert mode == 0o600, oct(mode)
    finally:
        await runner.cleanup()


async def test_put_rejects_bad_api_base_format(persist_path, monkeypatch):
    _patch_probes_ok(monkeypatch)
    runner, url = await _start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.put(url, json={"llm": {"api_base": "htp://not-a-valid-url"}}) as resp,
        ):
            assert resp.status == 400
            body = await resp.json()
            assert body["slot"] == "llm"
            assert body["field"] == "api_base"
            assert "url" in body["reason"].lower()
        # Invalid config is never applied or persisted (约法三章②).
        assert (
            server._services_config["llm"]["api_base"]
            == server._SERVICES_CONFIG_DEFAULTS["llm"]["api_base"]
        )
        assert not persist_path.exists()
    finally:
        await runner.cleanup()


async def test_put_rejects_unreachable_api_base(persist_path, monkeypatch):
    # Probe reports the endpoint is unreachable (valid URL, nothing listening).
    monkeypatch.setattr(
        server, "_probe_llm", lambda _u: {"status": "error", "reason": "connection refused"}
    )
    runner, url = await _start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.put(url, json={"llm": {"api_base": "http://127.0.0.1:9/v1"}}) as resp,
        ):
            assert resp.status == 422
            body = await resp.json()
            assert body["slot"] == "llm"
            assert body["field"] == "api_base"
            assert body["error"].startswith("service unreachable")
            assert body["reason"] == "connection refused"
        assert not persist_path.exists()
    finally:
        await runner.cleanup()


async def test_put_rejects_missing_asr_model_dir(persist_path, monkeypatch):
    # ASR model is a filesystem path; a missing dir must be rejected (422).
    monkeypatch.setattr(
        server, "_probe_asr", lambda _c: {"ok": False, "reason": "model dir not found: /nope"}
    )
    runner, url = await _start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.put(url, json={"asr": {"model": "/nonexistent/asr/model/dir"}}) as resp,
        ):
            assert resp.status == 422
            body = await resp.json()
            assert body["slot"] == "asr"
            assert body["field"] == "model"
        assert not persist_path.exists()
    finally:
        await runner.cleanup()


async def test_put_api_key_only_no_probe_and_persists(persist_path, monkeypatch):
    # Changing only api_key does not trigger a reachability probe; it is valid
    # and persisted.
    _patch_probes_ok(monkeypatch)
    runner, url = await _start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.put(url, json={"summary": {"api_key": "sk-only-key-change"}}) as resp,
        ):
            assert resp.status == 200
        assert server._services_config["summary"]["api_key"] == "sk-only-key-change"
        assert persist_path.exists()
    finally:
        await runner.cleanup()


async def test_put_clearing_api_base_is_valid(persist_path, monkeypatch):
    # Clearing a non-empty default api_base to "" is the legal "use default /
    # local" semantics — must NOT be probed and must return 200 (regression:
    # the gate previously rejected an empty api_base with a 422).
    _patch_probes_ok(monkeypatch)
    runner, url = await _start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.put(url, json={"summary": {"api_base": ""}}) as resp,
        ):
            assert resp.status == 200
            body = await resp.json()
            assert body["summary"]["api_base"] == ""
        # Empty string is persisted, not rejected by a probe.
        assert server._services_config["summary"]["api_base"] == ""
        assert persist_path.exists()
    finally:
        await runner.cleanup()


async def test_put_noop_does_not_probe(persist_path, monkeypatch):
    # A PUT carrying values identical to the current config must not trigger
    # any reachability probe (changing is empty -> early return). The probes
    # below would FAIL if called, proving they are not.
    monkeypatch.setattr(
        server, "_probe_llm", lambda _u: {"status": "error", "reason": "must not be called"}
    )
    monkeypatch.setattr(
        server, "_probe_summary", lambda _c: {"ok": False, "reason": "must not be called"}
    )
    monkeypatch.setattr(
        server, "_probe_tts", lambda _u: {"status": "error", "reason": "must not be called"}
    )
    monkeypatch.setattr(
        server, "_probe_asr", lambda _c: {"ok": False, "reason": "must not be called"}
    )
    runner, url = await _start_server()
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.put(
                url,
                json={
                    "llm": dict(server._SERVICES_CONFIG_DEFAULTS["llm"]),
                    "summary": dict(server._SERVICES_CONFIG_DEFAULTS["summary"]),
                    "tts": dict(server._SERVICES_CONFIG_DEFAULTS["tts"]),
                    "asr": dict(server._SERVICES_CONFIG_DEFAULTS["asr"]),
                },
            ) as resp,
        ):
            assert resp.status == 200
        # No-op PUT writes nothing (no changes) — file must not be created.
        assert not persist_path.exists()
    finally:
        await runner.cleanup()


async def test_get_returns_current_config(persist_path):
    runner, url = await _start_server()
    try:
        async with aiohttp.ClientSession() as session, session.get(url) as resp:
            assert resp.status == 200
            body = await resp.json()
        assert set(body.keys()) == {"llm", "summary", "tts", "asr"}
    finally:
        await runner.cleanup()
