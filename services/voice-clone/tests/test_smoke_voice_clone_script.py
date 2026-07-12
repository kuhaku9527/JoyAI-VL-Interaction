from __future__ import annotations

import base64
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "smoke_voice_clone.py"


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.content = self.text.encode("utf-8")

    def json(self):
        return self._payload


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("smoke_voice_clone", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_smoke_script_writes_wav_from_pcm16_base64(monkeypatch, tmp_path):
    smoke = _load_smoke_module()
    pcm = b"\x01\x00\x02\x00"

    def fake_post(*args, **kwargs):
        return _Resp(200, {"pcm16_base64": base64.b64encode(pcm).decode("ascii")})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(smoke.httpx, "post", fake_post)

    assert smoke.main() == 0
    wavs = list((tmp_path / "services" / "scripts").glob("smoke_*.wav"))
    assert len(wavs) == 1
    assert wavs[0].read_bytes().startswith(b"RIFF")


def test_smoke_script_reports_minimax_auth_failure(monkeypatch, capsys):
    smoke = _load_smoke_module()

    def fake_post(*args, **kwargs):
        return _Resp(502, {"detail": "MiniMax t2a_v2 failed: 1004 login fail"})

    monkeypatch.setattr(smoke.httpx, "post", fake_post)

    assert smoke.main() == 1
    out = capsys.readouterr().out
    assert "1004" in out
    assert "MiniMax rejected" in out
