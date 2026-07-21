"""Test list_voices endpoint repair (doc/voice-clone.md sec 15.5).

We mock httpx and check that:
  - HTTP verb is POST (not GET; the old /v1/voice/list GET endpoint 404s)
  - Body is the documented ``{"voice_type": "all"}``
  - Response with base_resp.status_code != 0 raises (so callers see auth
    failures instead of silently returning empty)
  - Successful response merges voice_cloning / voice_generation / system_voice,
    tagging each item with ``_kind`` for downstream selection.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VC_SRC = REPO / "services" / "voice-clone" / "src"
for _p in (str(REPO), str(VC_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _FakeResp:
    def __init__(self, body, status=200):
        self.body = body
        self.status_code = status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, body=None):
        self.last_path = None
        self.last_kwargs = None
        self.body = body

    async def post(self, path, **kwargs):
        self.last_path = path
        self.last_kwargs = kwargs
        return _FakeResp(self.body or {
            "voice_cloning": [
                {"voice_id": "bt-7274-x", "created_time": "2026-07-10"},
            ],
            "voice_generation": [],
            "system_voice": [{"voice_id": "sys-x", "voice_name": "sys"}],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        })

    async def get(self, *a, **kw):  # pragma: no cover - never called
        raise RuntimeError("GET should NOT be called by list_voices")


def _reload():
    import voice_clone_api.cloud_clone as cc
    importlib.reload(cc)
    return cc


def test_list_voices_uses_post_endpoint():
    cc = _reload()
    c = cc.MiniMaxClient(api_key="sk-api-fake", group_id="g-fake")
    fc = _FakeClient()
    c._client = fc

    asyncio.run(c.list_voices())

    assert fc.last_path == "/v1/get_voice", fc.last_path
    body = fc.last_kwargs.get("json")
    assert body == {"voice_type": "all"}, body


def test_list_voices_merges_three_kinds():
    cc = _reload()
    c = cc.MiniMaxClient(api_key="sk-api-fake", group_id="g-fake")
    c._client = _FakeClient()
    voices = asyncio.run(c.list_voices())
    kinds = sorted({v["_kind"] for v in voices})
    assert kinds == ["cloning", "system"], kinds
    cloning_v = [v for v in voices if v["_kind"] == "cloning"]
    assert cloning_v[0]["voice_id"] == "bt-7274-x"


def test_list_voices_raises_on_auth_error():
    cc = _reload()
    c = cc.MiniMaxClient(api_key="sk-api-fake", group_id="g-fake")
    c._client = _FakeClient(body={
        "base_resp": {"status_code": 1004, "status_msg": "login fail"},
    })
    with pytest.raises(RuntimeError, match="login fail"):
        asyncio.run(c.list_voices())
