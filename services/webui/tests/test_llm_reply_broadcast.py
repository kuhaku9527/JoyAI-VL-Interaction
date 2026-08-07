"""Tests for LLM reply broadcast + status endpoint (ADR 0003)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _isolate_session():
    from joy_interaction_webui import server

    server.websockets.clear()
    server.session_websockets.clear()
    server.ws_to_session.clear()
    yield
    server.websockets.clear()
    server.session_websockets.clear()
    server.ws_to_session.clear()


def test_notify_session_llm_reply_well_formed():
    from joy_interaction_webui import server

    captured = {}

    class FakeWS:
        async def send_str(self, s):
            captured["raw"] = s

    async def _run():
        ws = FakeWS()
        server.websockets.add(ws)
        server.session_websockets.setdefault("default", set()).add(ws)
        server.notify_session_llm_reply("default", "hello iron lady", source="jarvis")

    asyncio.run(_run())
    assert "raw" in captured, captured
    payload = json.loads(captured["raw"])
    assert payload["type"] == "llm_reply"
    assert payload["text"] == "hello iron lady"
    assert payload["source"] == "jarvis"
    assert isinstance(payload["ts"], float)


def test_notify_session_pilot_utterance_well_formed():
    from joy_interaction_webui import server

    captured = {}

    class FakeWS:
        async def send_str(self, s):
            captured["raw"] = s

    async def _run():
        ws = FakeWS()
        server.websockets.add(ws)
        server.session_websockets.setdefault("default", set()).add(ws)
        server.notify_session_pilot_utterance("default", "你好 BT", source="asr")

    asyncio.run(_run())
    assert "raw" in captured, captured
    payload = json.loads(captured["raw"])
    assert payload["type"] == "pilot_utterance"
    assert payload["text"] == "你好 BT"
    assert payload["source"] == "asr"
    assert isinstance(payload["ts"], float)


def test_probe_llm_parses_models(monkeypatch):
    import httpx

    from joy_interaction_webui import server

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            class R:
                status_code = 200

                def json(self_):
                    return {
                        "data": [
                            {"id": "joyai-vl-iq4"},
                            {"id": "other-gguf"},
                        ]
                    }

            return R()

    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: FakeClient())
    payload = server._probe_llm("http://127.0.0.1:7060/v1")
    assert payload["status"] == "ok"
    assert payload["models"] == ["joyai-vl-iq4", "other-gguf"]


def test_probe_tts_checks_voice_clone_health_for_synthesize_url(monkeypatch):
    import httpx

    from joy_interaction_webui import server

    seen = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            seen.append(url)

            class R:
                status_code = 200 if url == "http://127.0.0.1:8985/health" else 404

            return R()

    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: FakeClient())
    payload = server._probe_tts("http://127.0.0.1:8985/v1/synthesize")
    assert payload["status"] == "ok"
    assert payload["endpoint"] == "http://127.0.0.1:8985/health"
    assert seen[0] == "http://127.0.0.1:8985/health"


def test_probe_kws_accepts_plain_encoder_decoder_joiner(tmp_path):
    from joy_interaction_webui import server

    for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt", "keywords.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    payload = server._probe_kws(str(tmp_path))

    assert payload["status"] == "ok"
    assert payload["model"] == "encoder.onnx"


def test_vlm_service_rejects_placeholder_model_names():
    from joy_interaction_webui.vlm_service import VLMService

    svc = VLMService(model="streaming-infer-adapter")

    assert svc.set_model("undefined") is False
    assert svc.model == "streaming-infer-adapter"
    assert svc.set_model("joyai-vl-iq4") is True
    assert svc.model == "joyai-vl-iq4"


def test_llm_message_schedules_async_llm_task():
    from joy_interaction_webui import server
    from joy_interaction_webui.jarvis_mode import JarvisState

    class FakeStateMachine:
        def __init__(self):
            self.state = JarvisState.KWS_LISTENING
            self.sent = []
            self.stream_tts_flags = []
            self.image_b64_flags = []

        def _init_asr(self):
            pass

        async def _send_to_llm(self, text, *, stream_tts=True, image_b64=None, interaction_mode="call"):
            # v3.37: jarvis_mode._send_to_llm accepts image_b64 for the
            # multimodal paper-plane path; the Smart Turn feature added
            # `interaction_mode` (forwarded to webinfer, see server.llm_message).
            # The fake records both so tests that care can assert.
            self.sent.append(text)
            self.stream_tts_flags.append(stream_tts)
            self.image_b64_flags.append(image_b64)

    class FakeSession:
        def __init__(self):
            self.state_machine = FakeStateMachine()

    class FakeManager:
        def __init__(self):
            self.session = FakeSession()

        async def create_session(self, session_id):
            return self.session

    class FakeRequest:
        app: ClassVar[dict] = {"jarvis_manager": FakeManager()}

        async def json(self):
            return {"session_id": "s1", "text": "报告状态"}

    async def _run():
        resp = await server.llm_message(FakeRequest())
        assert resp.status == 200
        await asyncio.sleep(0)
        sm = FakeRequest.app["jarvis_manager"].session.state_machine
        return sm.sent, sm.stream_tts_flags

    sent, stream_tts_flags = asyncio.run(_run())
    assert sent == ["报告状态"]
    assert stream_tts_flags == [False]
