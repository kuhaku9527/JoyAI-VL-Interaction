# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
WebRTC Joy VL Interaction Server
Main server that handles WebRTC connections and serves the web interface
"""

import asyncio, base64, io, json, logging, os, signal, socket, subprocess, sys, time, uuid

# Fix double-module-load bug: when run via `python -m joy_interaction_webui.server`,
# Python executes this file as __main__ and *also* registers a separate module
# instance under the dotted name when jarvis_session.py does
# `from .server import notify_session_llm_reply`. Those two instances have
# *independent globals* (separate session_websockets, websockets, ...), so
# websocket_handler writes to one dict while notify_session_llm_reply reads
# from the other, silently dropping every LLM reply.
# Aliasing __main__ under the dotted name makes downstream `from .server import ...`
# resolve to the SAME module instance. See doc/jarvis-mode.md changelog v3.22.
if __name__ == "__main__":
    sys.modules.setdefault("joy_interaction_webui.server", sys.modules["__main__"])
from collections import defaultdict

import aiohttp
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaRelay

from .vlm_service import VLMService
from .video_processor import VideoProcessorTrack
from .rtsp_track import RTSPVideoTrack
from .audio_processor import MicAudioTrack
from .asr import setup_asr_routes
from .tts import setup_tts_routes
from .jarvis_session import JarvisSessionManager
from .jarvis_mode import JarvisState
from .jarvis_routes import setup_jarvis_routes, bind_audio
from .background_model import BackgroundModelService
from .local_file_server import setup_local_file_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

relay = MediaRelay()
pcs = set()
vlm_service = None
websockets = set()
rtsp_tracks = {}

default_vlm_config = {}
sessions = {}
session_websockets = defaultdict(set)
ws_to_session = {}
session_peer_connections = defaultdict(set)

# send_to_session must actually run the WS send coroutine. The previous
# implementation used asyncio.create_task(ws.send_str(message)) directly,
# which silently drops the message on real aiohttp WebSocketResponse
# (send_str awaits internally and the surrounding coroutine returns
# before the scheduler runs the task). See
# tests/test_send_to_session_actually_awaits.py for the regression test.

async def _safe_send_str(ws, message, session_id):
    try:
        await ws.send_str(message)
    except Exception as exc:
        logger.warning("send_to_session: WS send failed for %s: %s", session_id, exc)

def send_to_session(session_id, message):
    targets = list(session_websockets.get(session_id, set()))
    if not targets:
        # Common during early LLM startup before browser WS reconnects, log at INFO.
        logger.info("send_to_session: no WS targets for session %s (total sessions in dict: %d). Message DROPPED: %s", session_id, len(session_websockets), message[:200])
        return
    for ws in targets:
        try:
            asyncio.create_task(_safe_send_str(ws, message, session_id))
        except RuntimeError as exc:
            logger.error("send_to_session: schedule failed for %s: %s", session_id, exc)

def notify_session_json(session_id, payload):
    handle_background_handoff_for_interaction(session_id, payload)
    send_to_session(session_id, json.dumps(payload, ensure_ascii=False))

def notify_session_llm_reply(session_id, text, source="jarvis"):
    payload = {"type": "llm_reply", "text": text or "", "source": source or "jarvis", "ts": time.time()}
    send_to_session(session_id, json.dumps(payload, ensure_ascii=False))

def notify_session_pilot_utterance(session_id, text, source="asr"):
    payload = {"type": "pilot_utterance", "text": text or "", "source": source or "asr", "ts": time.time()}
    send_to_session(session_id, json.dumps(payload, ensure_ascii=False))

def notify_session_asr_partial(session_id, text, is_final=False):
    payload = {"type": "asr_partial", "text": text or "", "is_final": bool(is_final), "ts": time.time()}
    send_to_session(session_id, json.dumps(payload, ensure_ascii=False))


def handle_background_handoff_for_interaction(session_id, payload):
    if not isinstance(payload, dict) or payload.get("type") != "background_result_ready":
        return
    session = sessions.get(session_id)
    if not session or not session.get("vlm_service"):
        return

def get_session_callback(session_id):
    def callback(text, metrics):
        session = sessions.get(session_id)
        display_text = text
        if session and session.get("background_service"):
            display_text = session["background_service"].handle_foreground_response(text, metrics=metrics)
        sh = metrics.get("summarizer_history") if isinstance(metrics, dict) else None
        summarizer_timing = sh.get("summarizer_timing") if isinstance(sh, dict) else None
        out = {"type": "vlm_response", "text": display_text, "metrics": metrics}
        if summarizer_timing:
            out["summarizer_timing"] = summarizer_timing
        send_to_session(session_id, json.dumps(out, ensure_ascii=False))
    return callback

async def _safe_send_str_all(ws, message):
    try:
        await ws.send_str(message)
    except Exception as exc:
        logger.warning("broadcast_text_update: WS send failed: %s", exc)

def broadcast_text_update(text, metrics):
    if not websockets:
        return
    message = json.dumps({"type": "vlm_response", "text": text, "metrics": metrics})
    for ws in list(websockets):
        try:
            asyncio.create_task(_safe_send_str_all(ws, message))
        except RuntimeError as exc:
            logger.error("broadcast_text_update: schedule failed: %s", exc)

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    session_id = request.query.get("session_id", "").strip() or str(uuid.uuid4())
    ws_to_session[ws] = session_id
    session_websockets[session_id].add(ws)
    websockets.add(ws)
    logger.info("WebSocket client connected. session_id=%s, total clients: %d", session_id, len(websockets))
    session = get_or_create_session(session_id)
    svc = session["vlm_service"]
    bg_svc = session.get("background_service")
    background_service = bg_svc
    try:
        await ws.send_json({"type": "status", "text": "Connected to server", "status": "Ready", "session_id": session_id})
        from .video_processor import VideoProcessorTrack as _VPT
        await ws.send_json({"type": "server_config", "model": svc.model, "api_base": svc.api_base, "prompt": svc.prompt, "process_interval": _VPT.process_interval_seconds, "frames_per_batch": _VPT.frames_per_batch, "background_model": (background_service.get_config() if background_service else None), "session_id": session_id})
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                try:
                    t = data.get("type")
                    if t == "update_prompt":
                        svc.update_prompt(data.get("prompt", ""))
                        await ws.send_json({"type": "prompt_updated", "prompt": data.get("prompt", "")})
                    elif t == "update_model":
                        if svc.set_model(data.get("model", "")):
                            await ws.send_json({"type": "model_updated", "model": data.get("model", "")})
                    elif t == "update_process_interval":
                        from .video_processor import VideoProcessorTrack
                        VideoProcessorTrack.process_interval_seconds = float(data.get("process_interval", 1.0))
                        await ws.send_json({"type": "processing_updated", "process_interval": VideoProcessorTrack.process_interval_seconds})
                    elif t == "update_frames_per_batch":
                        from .video_processor import VideoProcessorTrack
                        await ws.send_json({"type": "frames_per_batch_updated", "frames_per_batch": VideoProcessorTrack.frames_per_batch})
                    elif t == "frame":
                        # Screen capture frames shipped via WebSocket (parallel to WebRTC).
                        # Decode base64 JPEG -> PIL Image -> vlm_service.process_frame, then broadcast the
                        # resulting text exactly like VideoProcessorTrack does for webcam/RTSP streams.
                        payload = data.get("data") or ""
                        if not isinstance(payload, str) or not payload:
                            logger.warning("frame: empty data")
                        else:
                            try:
                                from PIL import Image as _PILImage
                                raw = base64.b64decode(payload)
                                img = _PILImage.open(io.BytesIO(raw)).convert("RGB")
                                meta = {"source": data.get("source") or "screen", "format": data.get("format") or "jpeg", "width": data.get("width"), "height": data.get("height"), "timestamp": data.get("timestamp")}
                                await svc.process_frame(img, frame_metadata=meta)
                                response, _ = svc.get_current_response()
                                metrics = svc.get_metrics()
                                if response:
                                    get_session_callback(session_id)(response, metrics)
                            except Exception as frame_exc:
                                logger.warning("frame decode/process failed: %s", frame_exc)
                    elif t == "background_request":
                        if background_service and data.get("question"):
                            try:
                                task_id = background_service.handle_background_request(data["question"], session_id=session_id)
                                await ws.send_json({"type": "background_request_accepted", "task_id": task_id, "session_id": session_id})
                            except Exception as exc:
                                await ws.send_json({"type": "background_result_error", "task_id": "", "error": str(exc)})
                except Exception as e:
                    logger.error("Error handling client message: %s", e)
            elif msg.type == web.WSMsgType.ERROR:
                logger.error("WebSocket error: %s", ws.exception())
    finally:
        s = session_websockets.get(session_id)
        if s is not None:
            s.discard(ws)
            if not s: session_websockets.pop(session_id, None)
        ws_to_session.pop(ws, None)
        websockets.discard(ws)
        logger.info("WebSocket client disconnected. session_id=%s, total clients: %d", session_id, len(websockets))
    return ws

def _probe_llm(llm_api_url):
    import httpx
    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(llm_api_url.rstrip("/") + "/models")
        if resp.status_code == 200:
            try:
                data = resp.json()
                models = data.get("data") or []
                return {"status": "ok", "models": [m.get("id", "") for m in models if isinstance(m, dict)]}
            except Exception as exc:
                return {"status": "degraded", "reason": "parse: %s" % exc}
        return {"status": "error", "reason": "http %d" % resp.status_code}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:120]}

def _probe_tts(tts_api_url):
    # Probe the voice_clone_api ``/health`` endpoint first; if absent,
    # fall back to a GET on ``/v1/synthesize`` (POST-only, so 405 also
    # counts as "endpoint present"). Two short-lived clients per probe
    # to avoid any keep-alive edge cases.
    import httpx
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(tts_api_url.rstrip("/"))
    service_root = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    health_url = service_root + "/health" if service_root else None
    synth_url = tts_api_url.rstrip("/")
    for url in (h for h in (health_url, synth_url) if h):
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(url)
        except Exception:
            continue
        if resp.status_code == 200:
            return {"status": "ok", "endpoint": url, "code": 200}
        if "synthesize" in url and resp.status_code in (405, 422):
            return {"status": "ok", "endpoint": url, "code": resp.status_code, "note": "POST-only"}
    return {"status": "error", "reason": "unreachable"}

def _probe_kws(kws_model_dir):
    from pathlib import Path
    p = Path(kws_model_dir)
    if not p.exists():
        return {"status": "missing", "reason": "dir not found: %s" % kws_model_dir}
    matches = list(p.glob("encoder*chunk-*.onnx"))
    if not matches and all((p / name).exists() for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx")):
        matches = [p / "encoder.onnx"]
    if not matches:
        return {"status": "missing", "reason": "no encoder*.onnx in %s" % kws_model_dir}
    return {"status": "ok", "model": matches[0].name}

_LLM_PROBE_CACHE = {"payload": None, "ts": 0.0}
_LLM_PROBE_TTL_S = 5.0

def _now():
    return time.time()

def _resolve_service_targets(app):
    from .jarvis_mode import JarvisConfig
    cfg = JarvisConfig.from_env()
    return cfg.llm_api_url, cfg.tts_api_url

async def llm_status(request):
    llm_url, tts_url = _resolve_service_targets(request.app)
    kws_dir = os.environ.get("JARVIS_KWS_MODEL_DIR", "D:/AI/models/sherpa-onnx/models/kws/bt-en")
    now = _now()
    cached = _LLM_PROBE_CACHE
    if cached["payload"] is not None and (now - cached["ts"]) < _LLM_PROBE_TTL_S:
        llm_payload = dict(cached["payload"])
    else:
        llm_payload = _probe_llm(llm_url)
        cached["payload"] = llm_payload
        cached["ts"] = now
    tts_payload = _probe_tts(tts_url)
    kws_payload = _probe_kws(kws_dir) if kws_dir else {"status": "missing", "reason": "kws_model_dir not configured"}
    overall = "ok"
    for p in (llm_payload, tts_payload, kws_payload):
        if p.get("status") in ("error", "missing"):
            overall = "error"
            break
        if p.get("status") == "degraded" and overall == "ok":
            overall = "degraded"
    return web.json_response({"ts": now, "overall": overall, "llm": {"url": llm_url, **llm_payload}, "tts": {"url": tts_url, **tts_payload}, "kws": {"model_dir": kws_dir, **kws_payload}})

async def tts_health(request):
    _llm_url, tts_url = _resolve_service_targets(request.app)
    payload = _probe_tts(tts_url)
    return web.json_response({"ts": _now(), "url": tts_url, **payload})


def _wav_chunk_header(sample_rate: int, channels: int, bits_per_sample: int = 16) -> bytes:
    """Return a 44-byte canonical PCM WAV header for the given format."""
    riff = b"RIFF"
    wave = b"WAVE"
    fmt_ = b"fmt "
    data = b"data"
    audio_format = 1  # PCM
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    fmt_chunk_size = 16
    return (
        riff
        + b"\x00\x00\x00\x00"  # placeholder; caller fills RIFF size after data
        + wave
        + fmt_
        + fmt_chunk_size.to_bytes(4, "little")
        + audio_format.to_bytes(2, "little")
        + channels.to_bytes(2, "little")
        + sample_rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + block_align.to_bytes(2, "little")
        + bits_per_sample.to_bytes(2, "little")
        + data
        + b"\x00\x00\x00\x00"  # placeholder; caller fills data size after data
    )


def build_tts_synthesize_payload(upstream_json: dict) -> bytes:
    """Wrap a voice_clone_api /v1/synthesize response in a playable WAV blob.

    The upstream returns ``{"pcm16_base64": "...", "sample_rate": 24000, ...}``;
    browsers need a RIFF/WAVE container to play it via HTML5 ``<audio>``.
    Defaults: sample_rate=24000, channels=1 (MiniMax ``speech-2.8-hd`` shape).
    """
    import base64 as _b64
    pcm_b64 = upstream_json.get("pcm16_base64")
    if not pcm_b64:
        raise ValueError(
            "upstream /v1/synthesize response missing pcm16_base64; "
            f"keys={list(upstream_json.keys())}"
        )
    pcm = _b64.b64decode(pcm_b64)
    sample_rate = int(upstream_json.get("sample_rate") or 24000)
    channels = int(upstream_json.get("channels") or 1)
    header = _wav_chunk_header(sample_rate, channels)
    out = bytearray(header)
    out[4:8] = (len(out) + len(pcm) - 8).to_bytes(4, "little")
    out[40:44] = len(pcm).to_bytes(4, "little")
    out.extend(pcm)
    return bytes(out)


async def _tts_synthesize_handler(request):
    """POST /api/tts/synthesize -- wrap voice_clone_api into playable WAV.

    Body: ``{"text": "..."}`` (voice_id is read from ``JARVIS_TTS_VOICE_ID``).
    Returns ``audio/wav`` bytes on 200; 400 on empty text; 502 on upstream error.
    """
    import httpx as _httpx
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    text = (data.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "text is required"}, status=400)
    # Reuse the same JARVIS_TTS_* env that jarvis_mode.py uses, so behavior
    # stays in sync with the audio path used by the WebRTC speaker track.
    tts_api_url = os.environ.get("JARVIS_TTS_API_URL", "http://127.0.0.1:8985/v1/synthesize")
    voice_id = os.environ.get("JARVIS_TTS_VOICE_ID", "minimax_man_33333")
    body = {
        "text": text,
        "voice_id": voice_id,
        "model": os.environ.get("MINIMAX_DEFAULT_MODEL", "speech-2.8-hd"),
        "language_boost": os.environ.get("MINIMAX_LANGUAGE_BOOST", "Chinese"),
        "streaming": False,
    }
    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(tts_api_url, json=body)
    except Exception as exc:
        logger.warning("tts_synthesize: upstream unreachable: %s", exc)
        return web.json_response({"error": "upstream unreachable", "reason": str(exc)[:120]}, status=502)
    if resp.status_code >= 500:
        return web.json_response({"error": "upstream error", "status": resp.status_code}, status=502)
    try:
        upstream_json = resp.json()
    except Exception as exc:
        return web.json_response({"error": "upstream non-json", "reason": str(exc)[:120]}, status=502)
    try:
        wav = build_tts_synthesize_payload(upstream_json)
    except ValueError as exc:
        return web.json_response({"error": "upstream payload invalid", "reason": str(exc)[:120]}, status=502)
    return web.Response(body=wav, content_type="audio/wav")

async def llm_message(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    session_id = (data.get("session_id") or "").strip()
    text = (data.get("text") or "").strip()
    if not session_id or not text:
        return web.json_response({"error": "missing session_id or text"}, status=400)
    app = request.app
    manager = app.get("jarvis_manager")
    if manager is None:
        return web.json_response({"error": "jarvis_manager not initialised"}, status=503)
    jarvis_session = await manager.create_session(session_id)
    sm = jarvis_session.state_machine
    if sm.state != JarvisState.DIALOG_ACTIVE:
        sm.state = JarvisState.DIALOG_ACTIVE
    try:
        sm._init_asr()
    except Exception as exc:
        logger.debug("LLM-message: ASR init skipped (%s)", exc)
    task = asyncio.create_task(sm._send_to_llm(text, stream_tts=False))
    app.setdefault("_llm_tasks", set()).add(task)
    task.add_done_callback(app["_llm_tasks"].discard)
    return web.json_response({"session_id": session_id, "queued": True, "text_chars": len(text)})
def get_or_create_session(session_id):
    api_base = default_vlm_config.get("api_base", "http://127.0.0.1:8070/v1")
    model_name = default_vlm_config.get("model", "streaming-infer-adapter")
    prompt = default_vlm_config.get("prompt")
    vlm = VLMService(api_base=api_base, model=model_name, prompt=prompt)
    sessions[session_id] = {"vlm_service": vlm, "background_service": BackgroundModelService(session_id=session_id, notify_callback=lambda payload, sid=session_id: notify_session_json(sid, payload), summarizer_api_base=api_base), "show_request_payload": False}
    logger.info("Created new session: %s", session_id)
    return sessions[session_id]

async def session_cleanup(request):
    session_id = request.query.get("session_id", "").strip()
    if not session_id:
        return web.json_response({"error": "missing session_id"}, status=400)
    logger.info("[%s] Cleaning up session", session_id)
    session_sockets = list(session_websockets.pop(session_id, set()))
    for ws in session_sockets:
        try:
            await ws.close()
        except Exception as e:
            logger.warning("[%s] Error closing websocket: %s", session_id, e)
        finally:
            websockets.discard(ws); ws_to_session.pop(ws, None)
    if session_id in rtsp_tracks:
        rtsp_track, processor_track, frame_task = rtsp_tracks.pop(session_id)
        try:
            rtsp_track.stop()
        except Exception as e:
            logger.warning("[%s] Error stopping RTSP track: %s", session_id, e)
        try:
            await frame_task
        except Exception as e:
            logger.warning("[%s] Frame task error: %s", session_id, e)
    pcs_for_session = list(session_peer_connections.pop(session_id, set()))
    for pc in pcs_for_session:
        try:
            await pc.close()
        except Exception as e:
            logger.warning("[%s] Error closing peer connection: %s", session_id, e)
        finally:
            pcs.discard(pc)
    cancelled_vlm_tasks = 0
    cancelled_background_tasks = 0
    session = sessions.pop(session_id, None)
    if session:
        vlm = session.get("vlm_service")
        if vlm:
            try:
                tasks = getattr(vlm, "tasks", set())
                cancelled_vlm_tasks = len(tasks)
                for task in tasks: task.cancel()
            except Exception as e:
                logger.warning("[%s] Error cancelling VLM tasks: %s", session_id, e)
        bg_svc = session.get("background_service")
        if bg_svc:
            try:
                await bg_svc.close(cancel_requests=False)
            except Exception as e:
                logger.warning("[%s] Error closing background service: %s", session_id, e)
    logger.info("[%s] Session cleanup complete", session_id)
    return web.json_response({"session_id": session_id, "removed": bool(session), "websockets_closed": len(session_sockets), "peer_connections_closed": len(pcs_for_session), "cancelled_vlm_tasks": cancelled_vlm_tasks, "cancelled_background_tasks": cancelled_background_tasks})

async def _drain_mic_audio_track(mic_track, session_id):
    """Continuously consume browser mic frames and feed Jarvis.

    aiortc remote tracks only produce frames when something awaits recv().
    MicAudioTrack.recv() does the resample + Jarvis feed, so this task is the
    bridge that makes the always-on KWS listener real.
    """
    try:
        while True:
            await mic_track.recv()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.info("Jarvis mic audio consumer ended for %s: %s", session_id, exc)
    finally:
        try:
            mic_track.stop()
        except Exception:
            pass


def _start_mic_audio_consumer(mic_track, session_id):
    return asyncio.create_task(_drain_mic_audio_track(mic_track, session_id))


async def bind_jarvis_audio_for_peer(pc, session_id, manager):
    """Wire a WebRTC peer connection into the Jarvis listening chain."""
    session = await manager.create_session(session_id)
    speaker_track = bind_audio(session_id, manager)
    pc.addTrack(speaker_track)
    mic_tasks = set()

    @pc.on("track")
    def on_track(track):
        if getattr(track, "kind", None) != "audio":
            return
        mic_track = MicAudioTrack(track, session)
        task = _start_mic_audio_consumer(mic_track, session_id)
        mic_tasks.add(task)
        task.add_done_callback(mic_tasks.discard)
        logger.info("Jarvis mic track bound for session %s", session_id)

    return {"session": session, "speaker_track": speaker_track, "mic_tasks": mic_tasks}


def _offer_has_jarvis_audio(params):
    if params.get("jarvis_audio") is True:
        return True
    sdp = params.get("sdp") or ""
    return "m=audio" in sdp


async def offer(request):
    params = await request.json()
    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    session_id = params.get("session_id", "default")
    pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
    pcs.add(pc)
    session_peer_connections[session_id].add(pc)
    if _offer_has_jarvis_audio(params):
        manager = request.app.get("jarvis_manager")
        if manager is None:
            return web.json_response({"error": "jarvis_manager not initialised"}, status=503)
        await bind_jarvis_audio_for_peer(pc, session_id, manager)
    await pc.setRemoteDescription(offer_sdp)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.Response(content_type="application/json", text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "session_id": session_id}))

async def on_startup(app):
    import asyncio, os, sys
    here = os.path.dirname(__file__)
    repo_root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from .jarvis_mode import JarvisConfig
    cfg = JarvisConfig.from_env()
    if os.environ.get("JARVIS_ASR_MODEL_DIR"):
        cfg.asr_model_dir = os.environ["JARVIS_ASR_MODEL_DIR"]
    app["jarvis_manager"] = JarvisSessionManager(config=cfg)
    async def warm_browser_asr():
        try:
            from .asr import ASR_URL, _get_inproc_asr
            if ASR_URL:
                return
            await asyncio.to_thread(_get_inproc_asr)
            logger.info("Browser ASR in-process fallback warmed")
        except Exception as exc:
            logger.warning("Browser ASR warm-up skipped: %s", exc)
    app["browser_asr_warmup_task"] = asyncio.create_task(warm_browser_asr())
    logger.info("Jarvis session manager initialised (KWS=%s, ASR=%s)", cfg.kws_model_dir, cfg.asr_model_dir)

async def on_shutdown(app):
    for ws in list(websockets):
        try:
            await ws.close()
        except Exception:
            pass
    for session_id, session in list(sessions.items()):
        bg_svc = session.get("background_service")
        if bg_svc:
            try:
                await bg_svc.close(cancel_requests=False)
            except Exception:
                pass
    for pc in list(pcs):
        try:
            await pc.close()
        except Exception:
            pass

def main():
    import argparse
    parser = argparse.ArgumentParser(description="JoyAI VL Interaction WebUI Server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--no-ssl", action="store_true")
    parser.add_argument("--model", default="streaming-infer-adapter")
    parser.add_argument("--api-base", default="http://127.0.0.1:8070/v1")
    args = parser.parse_args()
    default_vlm_config.update({"api_base": args.api_base, "model": args.model, "prompt": None})
    app = web.Application()
    app.router.add_get("/", _index_handler)
    app.router.add_get("/models", _models_handler)
    app.router.add_get("/detect-services", _detect_services_handler)
    app.router.add_get("/ws", websocket_handler)
    setup_asr_routes(app)
    setup_tts_routes(app)
    setup_local_file_routes(app)
    setup_jarvis_routes(app)
    app.router.add_post("/offer", offer)
    app.router.add_post("/api/session/cleanup", session_cleanup)
    app.router.add_get("/api/llm/status", llm_status)
    app.router.add_get("/api/tts/health", tts_health)
    app.router.add_post("/api/llm/message", llm_message)
    app.router.add_post("/api/tts/synthesize", _tts_synthesize_handler)
    app.router.add_post("/api/rtsp/start", _rtsp_start_stub)
    app.router.add_post("/api/rtsp/stop", _rtsp_stop_stub)
    app.router.add_get("/api/rtsp/status", _rtsp_status_stub)
    images_dir = os.path.join(os.path.dirname(__file__), "static", "images")
    images_dir = os.path.abspath(images_dir)
    if os.path.exists(images_dir):
        app.router.add_static("/images", images_dir, name="images"); logger.info("Serving static files from: %s", images_dir)
    else:
        logger.warning("static images directory missing: %s", images_dir)
    favicon_dir = os.path.join(os.path.dirname(__file__), "static", "favicon")
    favicon_dir = os.path.abspath(favicon_dir)
    if os.path.exists(favicon_dir):
        app.router.add_static("/favicon", favicon_dir, name="favicon"); logger.info("Serving favicon files from: %s", favicon_dir)
    else:
        logger.warning("favicon directory missing: %s", favicon_dir)
    test_mode = os.environ.get("JOYAI_TEST_MODE") == "1"
    if not test_mode:
        app.on_startup.append(on_startup); app.on_shutdown.append(on_shutdown)
    if args.no_ssl:
        logger.warning("SSL disabled with --no-ssl flag"); ssl_context = None
    else:
        ssl_context = _build_ssl_context()
    logger.info("Initialized VLM service: model=%s, api_base=%s", args.model, args.api_base)
    print("\n======== Running on http://%s:%d ========" % (args.host, args.port))
    print("(Press CTRL+C to quit)")
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)

def _build_ssl_context():
    import ssl
    cert = os.path.join(os.path.dirname(__file__), "static", "favicon", "cert.pem")
    key = os.path.join(os.path.dirname(__file__), "static", "favicon", "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=cert)
    return None

async def _index_handler(request):
    from pathlib import Path
    static_dir = Path(os.path.dirname(__file__)) / "static"
    idx = static_dir / "index.html"
    if idx.exists():
        return web.Response(text=idx.read_text(encoding="utf-8"), content_type="text/html")
    return web.Response(text="webui running", content_type="text/plain")

async def _models_handler(request):
    return web.json_response({"models": ["joyai-vl-interaction-preview"]})

async def _detect_services_handler(request):
    return web.json_response({"llm": {"url": default_vlm_config.get("api_base")}, "tts": {"url": os.environ.get("JARVIS_TTS_API_URL", "http://127.0.0.1:8985/v1/synthesize")}, "kws": {"model_dir": os.environ.get("JARVIS_KWS_MODEL_DIR", "D:/AI/models/sherpa-onnx/models/kws/bt-en")}})

async def _rtsp_start_stub(request):
    return web.json_response({"error": "RTSP not implemented"}, status=501)

async def _rtsp_stop_stub(request):
    return web.json_response({"error": "RTSP not implemented"}, status=501)

async def _rtsp_status_stub(request):
    return web.json_response({"error": "RTSP not implemented"}, status=501)


if __name__ == '__main__':
    main()

