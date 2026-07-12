from __future__ import annotations

import base64
import io
import sys
import wave
from pathlib import Path

from fastapi.testclient import TestClient


PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


class _FakeMiniMax:
    def __init__(self):
        self.calls = []

    async def test_connection(self):
        return {"status": "ok"}

    async def zero_shot_synthesize(self, **kwargs):
        self.calls.append(kwargs)
        yield _wav_from_pcm(b"\x01\x00\x02\x00", 24000)

    async def close(self):
        pass


def _wav_from_pcm(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def test_minimax_provider_accepts_direct_cloud_voice_id(tmp_path):
    from voice_clone_api.main import Settings, create_app

    settings = Settings()
    settings.tts_provider = "minimax"
    settings.minimax_api_key = "sk-cp-fake"
    settings.minimax_group_id = "<your_minimax_group_id>"
    settings.voices_dir = tmp_path
    fake_minimax = _FakeMiniMax()
    app = create_app(settings=settings, minimax=fake_minimax)

    with TestClient(app) as client:
        resp = client.post(
            "/v1/synthesize",
            json={
                "text": "BT ready.",
                "voice_id": "minimax_man_33333",
                "streaming": False,
            },
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["voice_id"] == "minimax_man_33333"
    assert base64.b64decode(payload["pcm16_base64"]) == b"\x01\x00\x02\x00"
    assert fake_minimax.calls[0]["voice_id"] == "minimax_man_33333"
