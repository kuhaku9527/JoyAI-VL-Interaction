"""Hot-reload contract tests for the ASR runtime config source.

These verify that the webui's live service config (server._services_config["asr"])
is read by asr.connect_asr / build_asr_headers at connect time, so a PUT to
/api/services/config takes effect on the next browser ASR session without a
process restart.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_get_asr_url_reads_runtime_source():
    from joy_interaction_webui import asr

    asr.set_asr_config_source(
        {"asr": {"api_base": "wss://asr.example.com/ws", "api_key": "sk-test", "model": ""}}
    )
    try:
        assert asr.get_asr_url() == "wss://asr.example.com/ws"
    finally:
        # Reset so we never leak runtime state into other test modules
        # (e.g. test_asr_inproc_reset, which asserts get_asr_url() == "").
        asr.set_asr_config_source(None)


def test_build_asr_headers_adds_bearer_with_key():
    from joy_interaction_webui import asr

    headers = asr.build_asr_headers({"api_key": "sk-secret-1234"})
    assert headers.get("authorization") == "Bearer sk-secret-1234"


def test_build_asr_headers_omits_authorization_without_key():
    from joy_interaction_webui import asr

    headers = asr.build_asr_headers({"api_key": ""})
    assert "authorization" not in headers


def test_build_asr_headers_preserves_existing_scheme():
    from joy_interaction_webui import asr

    # If the operator already prefixed the scheme (legacy ASR_AUTHORIZATION
    # env style), we must not double-prefix it.
    headers = asr.build_asr_headers({"api_key": "Bearer preconfigured-token"})
    assert headers.get("authorization") == "Bearer preconfigured-token"
