from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


class _FakeResp:
    def __init__(self, body=None, *, status=200, content=b""):
        self.body = body or {}
        self.status_code = status
        self.content = content

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    async def aiter_lines(self):
        for line in self.body:
            yield line


class _FakeClient:
    def __init__(self, *, post_responses=None, get_responses=None):
        self.post_responses = list(post_responses or [])
        self.get_responses = list(get_responses or [])
        self.posts = []
        self.gets = []

    async def post(self, path, **kwargs):
        self.posts.append((path, kwargs))
        if self.post_responses:
            return self.post_responses.pop(0)
        return _FakeResp({"base_resp": {"status_code": 0, "status_msg": "success"}})

    async def get(self, path, **kwargs):
        self.gets.append((path, kwargs))
        if self.get_responses:
            return self.get_responses.pop(0)
        raise AssertionError(f"unexpected GET {path}")


def _reload():
    import voice_clone_api.cloud_clone as cc

    importlib.reload(cc)
    return cc


async def _collect(ait):
    return [chunk async for chunk in ait]


def test_zero_shot_synthesize_decodes_minimax_hex_audio():
    cc = _reload()
    wav_bytes = b"RIFF\x04\x00\x00\x00WAVE"
    c = cc.MiniMaxClient(api_key="sk-cp-fake", group_id="<your_minimax_group_id>")
    c._client = _FakeClient(
        post_responses=[
            _FakeResp(
                {
                    "data": {"audio": wav_bytes.hex(), "status": 2},
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )
        ]
    )

    chunks = asyncio.run(
        _collect(c.zero_shot_synthesize("BT ready.", "minimax_man_33333", streaming=False))
    )

    assert b"".join(chunks) == wav_bytes
    path, kwargs = c._client.posts[0]
    assert path == "/v1/t2a_v2"
    assert kwargs["json"]["audio_setting"]["sample_rate"] == 24000


def test_zero_shot_synthesize_normalizes_bt_designation_for_tts():
    cc = _reload()
    c = cc.MiniMaxClient(api_key="sk-cp-fake", group_id="<your_minimax_group_id>")
    c._client = _FakeClient(
        post_responses=[
            _FakeResp(
                {
                    "data": {"audio": b"RIFF\x04\x00\x00\x00WAVE".hex()},
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )
        ]
    )

    asyncio.run(
        _collect(
            c.zero_shot_synthesize(
                "铁御，BT-7274 就绪。",
                "minimax_man_33333",
                streaming=False,
            )
        )
    )

    assert c._client.posts[0][1]["json"]["text"] == "铁御，BT七二七四 就绪。"


def test_zero_shot_synthesize_raises_on_minimax_error():
    cc = _reload()
    c = cc.MiniMaxClient(api_key="sk-cp-fake", group_id="<your_minimax_group_id>")
    c._client = _FakeClient(
        post_responses=[
            _FakeResp({"base_resp": {"status_code": 1004, "status_msg": "login fail"}})
        ]
    )

    with pytest.raises(RuntimeError, match="1004.*login fail"):
        asyncio.run(
            _collect(c.zero_shot_synthesize("BT ready.", "minimax_man_33333", streaming=False))
        )


def test_connection_uses_get_voice_post_endpoint():
    cc = _reload()
    c = cc.MiniMaxClient(api_key="sk-cp-fake", group_id="<your_minimax_group_id>")
    c._client = _FakeClient(
        post_responses=[
            _FakeResp(
                {
                    "system_voice": [{"voice_id": "sys-a"}],
                    "voice_cloning": [{"voice_id": "minimax_man_33333"}],
                    "voice_generation": [],
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )
        ]
    )

    status = asyncio.run(c.test_connection())

    assert c._client.posts[0][0] == "/v1/get_voice"
    assert c._client.posts[0][1]["json"] == {"voice_type": "all"}
    assert c._client.gets == []
    assert status["status"] == "ok"
    assert status["voice_count"] == 2


def test_synthesize_async_uses_official_schema_and_download_endpoint():
    cc = _reload()
    audio_bytes = b"RIFF\x04\x00\x00\x00WAVE"
    c = cc.MiniMaxClient(api_key="sk-cp-fake", group_id="<your_minimax_group_id>")
    c._client = _FakeClient(
        post_responses=[
            _FakeResp(
                {
                    "task_id": 123,
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            )
        ],
        get_responses=[
            _FakeResp(
                {
                    "status": "success",
                    "file_id": 456,
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                }
            ),
            _FakeResp(content=audio_bytes),
        ],
    )

    result = asyncio.run(
        c.synthesize_async(
            "BT ready.",
            "minimax_man_33333",
            poll_interval_s=0,
            max_wait_s=1,
        )
    )

    assert result == audio_bytes
    post_payload = c._client.posts[0][1]["json"]
    assert post_payload["audio_setting"]["audio_sample_rate"] == 24000
    assert "sample_rate" not in post_payload["audio_setting"]
    assert post_payload["text"] == "BT ready."
    assert [path for path, _ in c._client.gets] == [
        "/v1/query/t2a_async_query_v2",
        "/v1/files/retrieve_content",
    ]
