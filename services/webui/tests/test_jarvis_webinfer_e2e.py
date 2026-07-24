"""Slice 5 — End-to-end: jarvis_state_machine -> webinfer /v1/text/chat.

Spins up a real aiohttp webinfer app on a randomly-allocated localhost
port in a daemon thread (its own asyncio loop), points
``JarvisStateMachine`` at the live URL, and verifies the full pipeline:

  1. ``_send_to_llm`` posts text to ``/v1/text/chat``
  2. webinfer composes system prompt + token guard
  3. webinfer parses decision tokens
  4. jarvis_mode broadcasts clean text via ``on_llm_response``
  5. ``</delegation>`` triggers BackgroundModelService

The trick is to avoid ``aiohttp.test_utils.TestClient``/``TestServer``
(both want to bind to the running loop) and run ``aiohttp.web.AppRunner``
on a real port from a separate daemon-thread loop. ``httpx.AsyncClient``
calls happen inside the test, which already runs in pytest-asyncio's
loop. Webinfer's aiohttp server runs in its own loop on another thread,
so they coexist without ``RuntimeError: no running event loop``.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# conftest.py already puts webui/src + webinfer on sys.path. Re-doing it
# defensively in case this file is run in isolation.
_REPO = Path(__file__).resolve().parents[3]
for _p in (
    str(_REPO / "services" / "webui" / "src"),
    str(_REPO / "services" / "webinfer"),
    str(_REPO),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_webinfer_app():
    """Build a webinfer app with stubbed main client (no llama-server needed)."""
    from aiohttp import web
    from live_adapter import AdapterConfig, StreamingInferAdapter
    from memory_store_client import MemoryStoreClient

    cfg = AdapterConfig()
    cfg.host = "127.0.0.1"
    cfg.port = 0  # not used (we start via AppRunner on our own port)
    cfg.enable_summarizer = False
    cfg.character_prompts_enabled = False
    cfg.memory_store_enabled = False
    cfg.main_ctx_tokens = 16384

    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.config = cfg
    adapter.sessions = {}
    adapter._cleanup_task = None
    adapter._character_prompt_mtime = 0.0
    adapter._system_prompt_cache = {}
    adapter._invalidate_system_prompt_cache = lambda: None
    adapter.memory_store = MemoryStoreClient(enabled=False)

    @dataclass
    class _StubUsage:
        prompt_tokens: int = 10
        completion_tokens: int = 5
        total_tokens: int = 15

        def model_dump(self) -> dict:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            }

    @dataclass
    class _StubMessage:
        content: str

    @dataclass
    class _StubChoice:
        message: _StubMessage

    @dataclass
    class _StubChatCompletion:
        choices: list
        usage: object = None

    class _StubChatCompletions:
        def __init__(self):
            self.scripted: list[str] = []
            self.calls: list = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            content = self.scripted.pop(0) if self.scripted else "</silence>"
            return _StubChatCompletion(
                choices=[_StubChoice(message=_StubMessage(content=content))],
                usage=_StubUsage(),
            )

    class _StubChat:
        def __init__(self):
            self.completions = _StubChatCompletions()

    stub = SimpleNamespace()
    stub.chat = _StubChat()
    adapter.main_client = stub
    adapter.main_clients = {cfg.main_model: (stub, cfg.main_model)}

    app = web.Application()
    app.router.add_post("/v1/text/chat", adapter.handle_text_chat)
    app.router.add_post("/v1/chat/completions", adapter.handle_chat_completions)
    return app, stub.chat.completions


@pytest.fixture
async def webinfer_server():
    """Async fixture that owns a real aiohttp webinfer on a free port.

    Returns ``(base_url, stub)``. The aiohttp server runs on its own
    event loop in a daemon thread; the test calls the live URL via
    ``httpx.AsyncClient`` running in this fixture's loop.
    """
    app, stub = _build_webinfer_app()
    port = _pick_free_port()

    server_loop = asyncio.new_event_loop()

    async def _startup() -> None:
        from aiohttp import web

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        # Stash on the loop so the shutdown callback can find them.
        server_loop._runner = runner  # type: ignore[attr-defined]

    def _loop_run() -> None:
        try:
            server_loop.run_until_complete(_startup())
        except Exception as exc:  # pragma: no cover
            print(f"[webinfer_server] startup failed: {exc}")
            return
        try:
            server_loop.run_forever()
        finally:
            server_loop.close()

    thread = threading.Thread(target=_loop_run, daemon=True, name="webinfer-test")
    thread.start()

    # Wait until TCPSite is listening (max 2 s). The probe goes through
    # the full webinfer pipeline and records a stub.calls entry; clear it
    # afterwards so test assertions don't see the probe call.
    import httpx

    base_url = f"http://127.0.0.1:{port}"
    deadline = asyncio.get_event_loop().time() + 2.0
    server_up = False
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=0.5) as probe:
                resp = await probe.post(
                    f"{base_url}/v1/text/chat",
                    json={"messages": [{"role": "user", "content": "ping"}]},
                )
                # 200/400 both indicate the server accepted the connection.
                if resp.status_code in (200, 400):
                    server_up = True
                    break
        except Exception:
            await asyncio.sleep(0.05)
    if not server_up:  # pragma: no cover
        raise RuntimeError("webinfer test server did not come up in 2 s")
    stub.calls = []

    try:
        yield base_url, stub
    finally:
        runner = getattr(server_loop, "_runner", None)
        if runner is not None:

            async def _shutdown() -> None:
                await runner.cleanup()

            try:
                future = asyncio.run_coroutine_threadsafe(_shutdown(), server_loop)
                future.result(timeout=5.0)
            except Exception:  # noqa: S110
                pass
        server_loop.call_soon_threadsafe(server_loop.stop)
        thread.join(timeout=5.0)


def _build_jarvis_sm(base_url: str):
    from joy_interaction_webui.jarvis_mode import JarvisConfig, JarvisStateMachine

    cfg = JarvisConfig(
        wake_word="bt",
        kws_model_dir="ignored",
        asr_model_dir="ignored",
        llm_api_url=f"{base_url}/v1",
        llm_text_path="/text/chat",
        llm_multimodal_path="/chat/completions",
        llm_model="stub",
        llm_system_prompt="be brief",
    )
    return JarvisStateMachine(config=cfg)


async def test_e2e_jarvis_to_webinfer_text_chat_clean_response(webinfer_server):
    """Voice path: text -> webinfer -> clean assistant reply."""
    base_url, stub = webinfer_server
    stub.scripted.append("</response> Confirmed, iron lady.")

    sm = _build_jarvis_sm(base_url)
    broadcast: list = []
    sm.on_llm_response = lambda text, source: broadcast.append(text)

    await sm._send_to_llm("hi", stream_tts=False)

    assert broadcast == ["Confirmed, iron lady."]
    assert len(stub.calls) == 1
    payload = stub.calls[0]["messages"]
    roles = [m["role"] for m in payload]
    assert roles[0] == "system"
    assert any(r == "user" for r in roles)


async def test_e2e_jarvis_to_webinfer_text_chat_delegation_triggers_background(webinfer_server):
    """Voice path: text -> webinfer delegation -> BackgroundModelService fires."""
    base_url, stub = webinfer_server
    stub.scripted.append("</delegation> 查 Cyberpunk 螳螂帮打法攻略")

    from joy_interaction_webui import server

    bg = SimpleNamespace(enabled=True, _closed=False, handle_foreground_response=Mock())
    server.sessions["e2e-delegation"] = {
        "background_service": bg,
        "vlm_service": SimpleNamespace(),
    }
    try:
        sm = _build_jarvis_sm(base_url)
        sm._background_service = bg

        broadcast: list = []
        sm.on_llm_response = lambda text, source: broadcast.append(text)

        await sm._send_to_llm("帮我查下 Cyberpunk 螳螂帮 boss 攻略", stream_tts=False)

        assert broadcast == [""]
        bg.handle_foreground_response.assert_called_once()
        call = bg.handle_foreground_response.call_args
        payload_text = call.args[0]
        metrics = call.kwargs.get("metrics") or {}
        assert "查 Cyberpunk 螳螂帮打法攻略" in payload_text
        assert metrics.get("delegation_question") == "查 Cyberpunk 螳螂帮打法攻略"
    finally:
        server.sessions.pop("e2e-delegation", None)


async def test_e2e_jarvis_to_webinfer_text_chat_silence_skips_tts(webinfer_server):
    """When webinfer returns </silence>, jarvis does NOT schedule TTS."""
    base_url, stub = webinfer_server
    stub.scripted.append("</silence>")

    sm = _build_jarvis_sm(base_url)
    await sm._send_to_llm("hi", stream_tts=True)

    assert sm._tts_task is None
