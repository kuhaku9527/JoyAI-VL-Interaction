"""ASR websocket bridge for browser microphone audio."""

import asyncio
import json
import logging
import os

# ============================================================================
# In-process sherpa-onnx ASR fallback
# ============================================================================
import os as _os
import struct
import sys as _sys
import time
import uuid

import aiohttp
from aiohttp import web

_INPROC_ASR = None
_INPROC_ASR_LOCK_IMPORTED = False


def _ensure_repo_root_on_path() -> None:
    global _INPROC_ASR_LOCK_IMPORTED
    if _INPROC_ASR_LOCK_IMPORTED:
        return
    here = _os.path.dirname(_os.path.abspath(__file__))
    repo_root = _os.path.abspath(_os.path.join(here, "..", "..", "..", ".."))
    if repo_root not in _sys.path:
        _sys.path.insert(0, repo_root)
    _INPROC_ASR_LOCK_IMPORTED = True


def _get_inproc_asr():
    global _INPROC_ASR
    if _INPROC_ASR is not None:
        return _INPROC_ASR
    _ensure_repo_root_on_path()
    from services.asr.jarvis.asr import JarvisASR

    model_dir = _os.environ.get(
        "JARVIS_ASR_MODEL_DIR",
        "D:/AI/models/sherpa-onnx/models/asr/streaming-paraformer-bilingual-zh-en",
    )
    num_threads = int(_os.environ.get("JARVIS_ASR_NUM_THREADS", "2"))
    _INPROC_ASR = JarvisASR(model_dir=model_dir, num_threads=num_threads)
    _INPROC_ASR.start()
    return _INPROC_ASR


# ASR parameters
ASR_URL = os.getenv("ASR_URL", "").strip()
ASR_AUTHORIZATION = os.getenv(
    "ASR_AUTHORIZATION",
    "",
)
ASR_REQUEST_SID = os.getenv("ASR_REQUEST_SID", "browser-room")
ASR_SAMPLE_RATE = int(os.getenv("ASR_SAMPLE_RATE", "16000"))
ASR_CHUNK_SECONDS = float(os.getenv("ASR_CHUNK_SECONDS", "0.04"))
ASR_CONNECT_RETRIES = int(os.getenv("ASR_CONNECT_RETRIES", "0"))
ASR_OPEN_TIMEOUT = float(os.getenv("ASR_OPEN_TIMEOUT", "10"))
ASR_RETRY_INITIAL_DELAY = float(os.getenv("ASR_RETRY_INITIAL_DELAY", "0.5"))
ASR_RETRY_MAX_DELAY = float(os.getenv("ASR_RETRY_MAX_DELAY", "5"))
ASR_FINAL_TIMEOUT = float(os.getenv("ASR_FINAL_TIMEOUT", "8.0"))
ASR_FINAL_GRACE_SECONDS = float(os.getenv("ASR_FINAL_GRACE_SECONDS", "1.2"))
ASR_RECOGNIZE_PARAMS = {
    "do_post_process": True,
    "do_partial_result": True,
    "do_punc_end_process": True,
    "do_punc_partial_process": True,
    "do_show_nbest": False,
    "do_filter_modal_part": False,
    "do_dynamic_lm": False,
    "do_server_vad": True,
    "do_semantic_vad": False,
    "continuous_decoding": True,
    "llm_reply": "",
    "agent_id": "",
    "forceend_lowerlimit": 6000,
    "forceend_upperlimit": 8000,
}
ASR_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


def mask_secret(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def build_asr_headers():
    request_params = {
        "sid": ASR_REQUEST_SID,
        "reqid": str(uuid.uuid1()),
        "sample_rate": ASR_SAMPLE_RATE,
    }
    return {
        "authorization": ASR_AUTHORIZATION,
        "request": json.dumps(request_params),
        "recognize": json.dumps(ASR_RECOGNIZE_PARAMS),
    }


def retry_asr_delay(attempt):
    return min(ASR_RETRY_INITIAL_DELAY * (2**attempt), ASR_RETRY_MAX_DELAY)


def is_retryable_asr_connect_error(err):
    if isinstance(err, (asyncio.TimeoutError, OSError, aiohttp.ClientConnectionError)):
        return True
    status = getattr(err, "status", None)
    return status in ASR_RETRYABLE_STATUS_CODES


async def connect_asr_inproc(session_id):
    logger.info("[%s] ASR: using in-process sherpa-onnx fallback", session_id)
    engine = _get_inproc_asr()
    engine.start()
    return None, engine


async def connect_asr(session_id):
    if not ASR_URL:
        raise RuntimeError("ASR_URL is not configured")

    attempt = 0
    while True:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
        try:
            logger.info(
                "[%s] ASR connect attempt %s url=%s authorization=%s",
                session_id,
                attempt + 1,
                ASR_URL,
                mask_secret(ASR_AUTHORIZATION),
            )
            asr_ws = await session.ws_connect(
                ASR_URL,
                headers=build_asr_headers(),
                timeout=ASR_OPEN_TIMEOUT,
                heartbeat=20,
                max_msg_size=0,
            )
            return session, asr_ws
        except Exception as err:
            await session.close()
            retryable = is_retryable_asr_connect_error(err)
            retries_left = ASR_CONNECT_RETRIES < 0 or attempt < ASR_CONNECT_RETRIES
            logger.warning(
                "[%s] ASR connect attempt %s failed retryable=%s retries_left=%s: %s",
                session_id,
                attempt + 1,
                retryable,
                retries_left,
                err,
            )
            if not retryable or not retries_left:
                raise
            delay = retry_asr_delay(attempt)
            attempt += 1
            await asyncio.sleep(delay)


def pack_asr_audio(seqid, audio, is_final=False):
    packet_seqid = -abs(seqid) if is_final else seqid
    return struct.pack(">iii", packet_seqid, 0, 0) + audio


def extract_asr_result(payload):
    asr_response = payload.get("asr_response") or {}
    event_type = asr_response.get("event_type", "")
    recognition = asr_response.get("recognition_result") or {}
    hypotheses = recognition.get("hypothesis") or []
    first = hypotheses[0] if hypotheses else {}
    text = first.get("text", "")
    if event_type not in {"IS_PARTIAL", "IS_FINAL", "IS_END"}:
        text = ""
    return {
        "type": "result",
        "event": event_type,
        "mid": payload.get("mid", ""),
        "text": text,
        "confidence": first.get("confidence"),
        "final": event_type in {"IS_FINAL", "IS_END"},
        "code": payload.get("code"),
        "msg": payload.get("msg", ""),
    }


def make_asr_synthetic_final(mid, text, message):
    return {
        "type": "result",
        "event": "IS_FINAL",
        "mid": mid or "",
        "text": text,
        "confidence": None,
        "final": True,
        "code": 0,
        "msg": message,
        "synthetic": True,
    }


async def send_asr_client_json(client_ws, payload):
    if not client_ws.closed:
        await client_ws.send_str(json.dumps(payload, ensure_ascii=False))


async def forward_asr_audio_inproc(session_id, client_ws, engine, client_end_event):
    while True:
        if client_end_event and client_end_event.is_set():
            return
        msg = await client_ws.receive()
        if msg.type == aiohttp.WSMsgType.BINARY:
            try:
                engine.feed_chunk(msg.data)
            except Exception as exc:
                logger.exception("[%s] inproc ASR feed failed: %s", session_id, exc)
                return
        elif msg.type == aiohttp.WSMsgType.TEXT:
            try:
                payload = json.loads(msg.data)
                control_type = payload.get("type")
                if control_type == "segment_end":
                    engine.stop()
                    engine.start()
                    return
                if control_type == "end":
                    return
            except (json.JSONDecodeError, TypeError):
                pass
        elif msg.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
        }:
            return
        elif msg.type == aiohttp.WSMsgType.ERROR:
            return


async def forward_asr_results_inproc(session_id, client_ws, engine, stop_on_final=True):
    last_text = ""
    mid_counter = 0
    silent_polls = 0
    while True:
        await asyncio.sleep(0.08)
        text = engine.last_text or ""
        if text and text != last_text:
            mid_counter += 1
            mid = f"inproc-{mid_counter}"
            await send_asr_client_json(
                client_ws,
                {
                    "type": "result",
                    "event": "IS_PARTIAL",
                    "mid": mid,
                    "text": text,
                    "confidence": None,
                    "final": False,
                },
            )
            last_text = text
            silent_polls = 0
        elif not text:
            silent_polls += 1
            if last_text and silent_polls >= 20:
                await send_asr_client_json(
                    client_ws,
                    {
                        "type": "result",
                        "event": "IS_FINAL",
                        "mid": f"inproc-{mid_counter}",
                        "text": last_text,
                        "confidence": None,
                        "final": True,
                    },
                )
                if stop_on_final:
                    return
                last_text = ""
                silent_polls = 0
        else:
            silent_polls += 1


async def forward_asr_audio(session_id, client_ws, asr_ws, client_end_event):
    seqid = 1
    pending = bytearray()
    chunk_bytes = max(2, int(ASR_SAMPLE_RATE * ASR_CHUNK_SECONDS) * 2)
    final_sent = False
    sent_bytes = 0

    async def send_audio(audio, is_final=False):
        nonlocal seqid, sent_bytes
        await asr_ws.send_bytes(pack_asr_audio(seqid, audio, is_final=is_final))
        sent_bytes += len(audio)
        seqid += 1

    async def flush_final():
        nonlocal final_sent
        client_end_event.set()
        if final_sent or asr_ws.closed:
            return
        final_sent = True
        while pending:
            audio = bytes(pending[:chunk_bytes])
            del pending[:chunk_bytes]
            await send_audio(audio)
        await send_audio(b"", is_final=True)
        logger.info(
            "[%s] ASR final audio sent audio_seconds=%.3f",
            session_id,
            sent_bytes / (ASR_SAMPLE_RATE * 2),
        )

    async for msg in client_ws:
        if msg.type == web.WSMsgType.BINARY:
            pending.extend(msg.data)
            while len(pending) >= chunk_bytes:
                await send_audio(bytes(pending[:chunk_bytes]))
                del pending[:chunk_bytes]
        elif msg.type == web.WSMsgType.TEXT:
            try:
                control = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            if control.get("type") == "ping":
                await send_asr_client_json(
                    client_ws,
                    {
                        "type": "pong",
                        "id": control.get("id"),
                        "client_ts": control.get("client_ts"),
                        "server_ts": time.time(),
                    },
                )
            elif control.get("type") in {"end", "segment_end"}:
                await flush_final()
                return
        elif msg.type in {web.WSMsgType.CLOSE, web.WSMsgType.CLOSING, web.WSMsgType.CLOSED}:
            break
        elif msg.type == web.WSMsgType.ERROR:
            raise client_ws.exception() or RuntimeError("ASR client websocket error")

    await flush_final()


async def forward_asr_results(
    session_id,
    client_ws,
    asr_ws,
    stop_on_final=True,
    client_end_event=None,
):
    last_text = ""
    ending_mid = None
    while True:
        timeout = ASR_FINAL_GRACE_SECONDS if ending_mid else None
        try:
            msg = await asr_ws.receive(timeout=timeout)
        except asyncio.TimeoutError:
            if last_text:
                await send_asr_client_json(
                    client_ws,
                    make_asr_synthetic_final(
                        ending_mid,
                        last_text,
                        "synthetic final after ASR end timeout",
                    ),
                )
            if stop_on_final or (client_end_event and client_end_event.is_set()):
                return
            ending_mid = None
            continue

        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            result = extract_asr_result(payload)
            logger.debug("[%s] ASR result: %s", session_id, result)
            if ending_mid and result["mid"] and result["mid"] != ending_mid:
                if last_text:
                    await send_asr_client_json(
                        client_ws,
                        make_asr_synthetic_final(
                            ending_mid,
                            last_text,
                            "synthetic final before next ASR segment",
                        ),
                    )
                if stop_on_final or (client_end_event and client_end_event.is_set()):
                    return
                ending_mid = None
            await send_asr_client_json(client_ws, result)
            if result["text"]:
                last_text = result["text"]
            if result["final"] and (
                stop_on_final or (client_end_event and client_end_event.is_set())
            ):
                return
            if result["event"] == "IS_IPU_END":
                ending_mid = result["mid"] or "unknown"
        elif msg.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
        }:
            return
        elif msg.type == aiohttp.WSMsgType.ERROR:
            raise asr_ws.exception() or RuntimeError("ASR upstream websocket error")


async def asr_websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    session_id = request.query.get("session_id", "").strip() or uuid.uuid4().hex[:8]
    continuous_results = request.query.get("continuous") == "1"
    client_end_event = asyncio.Event()
    asr_session = None
    asr_ws = None
    logger.info("[%s] Browser ASR websocket connected", session_id)

    inproc_mode = False
    try:
        asr_session, asr_ws = await connect_asr(session_id)
        await send_asr_client_json(
            ws,
            {"type": "status", "message": "connected", "sample_rate": ASR_SAMPLE_RATE},
        )

        audio_task = asyncio.create_task(
            forward_asr_audio(session_id, ws, asr_ws, client_end_event)
        )
        result_task = asyncio.create_task(
            forward_asr_results(
                session_id,
                ws,
                asr_ws,
                stop_on_final=not continuous_results,
                client_end_event=client_end_event,
            )
        )
    except Exception as connect_err:
        logger.info(
            "[%s] external ASR unreachable (%s); using in-process sherpa-onnx",
            session_id,
            connect_err,
        )
        inproc_mode = True
        try:
            asr_session, asr_ws = await connect_asr_inproc(session_id)
            await send_asr_client_json(
                ws,
                {"type": "status", "message": "connected", "sample_rate": ASR_SAMPLE_RATE},
            )
            audio_task = asyncio.create_task(
                forward_asr_audio_inproc(session_id, ws, asr_ws, client_end_event)
            )
            result_task = asyncio.create_task(
                forward_asr_results_inproc(
                    session_id,
                    ws,
                    asr_ws,
                    stop_on_final=not continuous_results,
                )
            )
        except Exception as inproc_err:
            logger.error("[%s] in-process ASR init failed: %s", session_id, inproc_err)
            await send_asr_client_json(
                ws,
                {"type": "error", "message": f"ASR unavailable: {inproc_err}"},
            )
            return
        done, pending = await asyncio.wait(
            {audio_task, result_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if audio_task in done and not result_task.done():
            try:
                await asyncio.wait_for(result_task, timeout=ASR_FINAL_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("[%s] ASR final result timeout", session_id)
                result_task.cancel()
        else:
            for task in pending:
                task.cancel()
        for task in done:
            task.result()
    except Exception as err:
        logger.exception("[%s] ASR websocket failed", session_id)
        try:
            await send_asr_client_json(ws, {"type": "error", "message": f"ASR failed: {err}"})
        except Exception:
            pass
    finally:
        if not inproc_mode:
            if asr_ws is not None and not asr_ws.closed:
                await asr_ws.close()
            if asr_session is not None:
                await asr_session.close()
        if not ws.closed:
            await ws.close()
        logger.info("[%s] Browser ASR websocket closed", session_id)

    return ws


def setup_asr_routes(app):
    app.router.add_get("/ws/asr", asr_websocket_handler)
