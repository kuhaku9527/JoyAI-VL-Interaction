"""HTTP routes for the BT-7274 Jarvis mode.

Exposes three endpoints (used by the browser UI to inspect and control
the per-session Jarvis state machine) plus a helper invoked from
``server.py``'s WebRTC offer handler to wire audio:

* ``GET  /api/jarvis/status?session_id=...`` -- snapshot of state machine
* ``POST /api/jarvis/force_state`` -- manually move the state machine
  (used by the UI to skip KWS while the pre-trained model is not yet
  accurate; see ``doc/jarvis-mode.md`` v3.2 P2 notes)
* ``POST /api/jarvis/stop`` -- tear down the Jarvis session for a given
  webui session (called on peer-connection close)

The actual mic <-> speaker WebRTC bridging is done in
``server.py``'s ``offer`` handler using the
:class:`audio_processor.MicAudioTrack` and
:class:`audio_processor.SpeakerAudioTrack` classes.
"""
from __future__ import annotations

import asyncio
import os
import time
import logging
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from aiohttp import web

from .jarvis_mode import JarvisState
from .jarvis_session import JarvisSessionManager

if TYPE_CHECKING:
    from .audio_processor import SpeakerAudioTrack

logger = logging.getLogger("joyai.jarvis.routes")


# Per-session speaker tracks so the WebRTC offer handler can wire
# audio output back to the right peer connection.
_speaker_tracks: dict[str, "SpeakerAudioTrack"] = {}


def get_speaker_track(session_id: str) -> Optional["SpeakerAudioTrack"]:
    """Return the speaker track for a session, if any."""
    return _speaker_tracks.get(session_id)


def bind_audio(session_id: str, manager: JarvisSessionManager) -> "SpeakerAudioTrack":
    """Create (or reuse) a SpeakerAudioTrack and attach it to the
    Jarvis session. Called from ``server.py``'s WebRTC ``offer`` handler
    when an audio track is received.
    """
    from .audio_processor import SpeakerAudioTrack

    track = _speaker_tracks.get(session_id)
    if track is None:
        track = SpeakerAudioTrack(sample_rate=24000)
        _speaker_tracks[session_id] = track
        logger.info("Created SpeakerAudioTrack for session %s", session_id)
    # We cannot ``await`` here (this helper is sync); callers must
    # ensure the session exists before invoking ``bind_audio``.
    session = manager.get_session(session_id)
    if session is not None:
        session.attach_audio_output(track.push_pcm)
    return track



async def feed_wav_to_session(
    session,
    wav_path: Path,
    chunk_frames: int = 1600,
    sleep_s: float = 0.1,
    max_duration_s: Optional[float] = None,
) -> dict:
    """Feed a 16kHz mono int16 WAV into a Jarvis session.

    Diagnostic seam.  Pass max_duration_s to bound total runtime so a
    runaway injection cannot keep pushing audio forever.
    """
    wav_path = Path(wav_path)
    chunks = 0
    total_bytes = 0
    start_ts = time.time()
    deadline_s = max_duration_s if max_duration_s and max_duration_s > 0 else None
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise ValueError("diagnostic wav must be 16kHz mono int16")
        while True:
            pcm = wf.readframes(chunk_frames)
            if not pcm:
                break
            await session.feed_audio(pcm)
            chunks += 1
            total_bytes += len(pcm)
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            if deadline_s is not None and (time.time() - start_ts) >= deadline_s:
                logger.info("feed_wav hit max_duration=%.1fs, stopping", deadline_s)
                break
    return {"path": str(wav_path), "chunks": chunks, "bytes": total_bytes}
def _is_allowed_diagnostic_wav(path: Path) -> bool:
    resolved = path.resolve()
    allowed_roots = [
        Path("D:/AI/data/kws").resolve(),
        Path(__file__).resolve().parents[4],
    ]
    return any(resolved == root or root in resolved.parents for root in allowed_roots)

def setup_jarvis_routes(app: web.Application) -> None:
    """Register the Jarvis HTTP routes on the given aiohttp app."""
    app.router.add_get("/api/jarvis/status", jarvis_status)
    app.router.add_post("/api/jarvis/force_state", jarvis_force_state)
    app.router.add_post("/api/jarvis/stop", jarvis_stop)
    app.router.add_post("/api/jarvis/feed_wav", jarvis_feed_wav)


    app.router.add_post("/api/diagnostic/save_wav", diagnostic_save_wav)

# ============================================================================
# Handlers
# ============================================================================


async def jarvis_status(request: web.Request) -> web.Response:
    session_id = request.query.get("session_id", "").strip()
    if not session_id:
        return web.json_response({"error": "missing session_id"}, status=400)
    manager: JarvisSessionManager = request.app["jarvis_manager"]
    session = manager.get_session(session_id)
    if session is None:
        return web.json_response(
            {"session_id": session_id, "exists": False, "state": "KWS_LISTENING"}
        )
    return web.json_response(
        {
            "session_id": session_id,
            "exists": True,
            "state": session.state_machine.state.name,
            "wake_word": session.state_machine.config.wake_word,
            "is_awake": session.is_awake,
            "should_synthesize": session.should_synthesize(),
            "should_analyze_frame": session.should_analyze_frame(),
        }
    )


async def jarvis_force_state(request: web.Request) -> web.Response:
    """Force a state transition. Used by the UI for development /
    when KWS is not yet trained.

    Body: ``{"session_id": "...", "state": "DIALOG_ACTIVE"}``
    """
    try:
        data = await request.json()
    except Exception:
        data = {}
    session_id = (data.get("session_id") or "").strip()
    target = (data.get("state") or "").strip()
    if not session_id or not target:
        return web.json_response(
            {"error": "missing session_id or state"}, status=400
        )
    try:
        new_state = JarvisState[target]
    except KeyError:
        return web.json_response(
            {"error": f"unknown state {target!r}",
             "valid": [s.name for s in JarvisState]},
            status=400,
        )
    manager: JarvisSessionManager = request.app["jarvis_manager"]
    session = manager.get_session(session_id)
    if session is None:
        # Auto-create the session so the UI can force state before any
        # WebRTC track arrives (e.g. for KWS-less testing).
        session = await manager.create_session(session_id)
    # Ensure ASR is alive for DIALOG_ACTIVE entry
    if new_state == JarvisState.DIALOG_ACTIVE:
        from .jarvis_mode import JarvisConfig
        cfg: JarvisConfig = session.state_machine.config
        session.state_machine._init_asr()
        session.state_machine._asr.start()
        session.state_machine._asr_stream_active = True
        import time as _t
        session.state_machine._last_speech_time = _t.time()
    session.state_machine.state = new_state
    logger.info("Forced state %s for session %s", new_state.name, session_id)
    return web.json_response({"session_id": session_id, "state": new_state.name})


async def jarvis_stop(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return web.json_response({"error": "missing session_id"}, status=400)
    manager: JarvisSessionManager = request.app["jarvis_manager"]
    await manager.remove_session(session_id)
    track = _speaker_tracks.pop(session_id, None)
    if track is not None:
        track.stop()
    return web.json_response({"session_id": session_id, "stopped": True})
async def jarvis_feed_wav(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    session_id = (data.get("session_id") or "").strip()
    if not session_id:
        return web.json_response({"error": "missing session_id"}, status=400)
    wav_path = Path(data.get("path") or "D:/AI/data/kws/bt-en/test_bt.wav")
    if not wav_path.exists():
        return web.json_response({"error": "wav not found", "path": str(wav_path)}, status=404)
    if not _is_allowed_diagnostic_wav(wav_path):
        return web.json_response({"error": "wav path not allowed"}, status=403)

    manager: JarvisSessionManager = request.app["jarvis_manager"]
    session = manager.get_session(session_id)
    if session is None:
        session = await manager.create_session(session_id)

    # Bound total runtime so a runaway injection (e.g. HTTP client
    # timeout) cannot keep feeding audio forever.
    raw_max = data.get("max_duration_s")
    if raw_max is None:
        raw_max = os.environ.get("JARVIS_FEED_MAX_DURATION_S", "30")
    try:
        max_duration_s = float(raw_max)
    except (TypeError, ValueError):
        max_duration_s = 30.0

    # Run the feed loop as a tracked task so session.stop() / new feed_wav
    # calls can cancel a runaway in-flight task, and the client
    # disconnect transport callback cancels the task even if the response
    # never reaches the caller.
    feed_task = asyncio.create_task(
        feed_wav_to_session(session, wav_path, max_duration_s=max_duration_s)
    )

    try:
        result = await feed_task
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except asyncio.CancelledError:
        return web.json_response({"session_id": session_id, "cancelled": True})
    return web.json_response({"session_id": session_id, "fed": result})
    return web.json_response({"session_id": session_id, "fed": result})

async def diagnostic_save_wav(request: web.Request) -> web.Response:
    """Save an uploaded WAV to D:/AI/data/kws/mic_captures/ for offline analysis."""
    try:
        reader = await request.multipart()
    except Exception as exc:
        return web.json_response({"error": f"multipart failed: {exc}"}, status=400)
    out_dir = Path("D:/AI/data/kws/mic_captures")
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    async for part in reader:
        if part.name != "wav":
            await part.release()
            continue
        filename = part.filename or "mic.wav"
        out_path = out_dir / filename
        with out_path.open("wb") as f:
            while True:
                chunk = await part.read_chunk(8192)
                if not chunk:
                    break
                f.write(chunk)
        saved.append(str(out_path))
    return web.json_response({"saved": saved})
