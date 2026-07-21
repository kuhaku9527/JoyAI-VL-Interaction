# SPDX-License-Identifier: Apache-2.0

"""FastAPI voice-clone service.

This service wraps the cloud MiniMax Rapid Clone + T2A v2 API. It owns
three concerns:

1. **Voice profile management** -- accept an upload of ~10 s of
   reference audio, persist it under ``voices/<voice_id>/``, and return
   a stable ``voice_id`` that downstream code can reference.

2. **Cloud register** -- immediately after a successful upload, call
   ``/v1/voice_clone`` on MiniMax to register the timbre in the cloud.

3. **Streaming synthesis** -- expose a single ``POST /v1/synthesize``
   endpoint that takes ``{text, voice_id}`` and returns either
   Server-Sent Events of base64 PCM16 chunks (streaming) or a single
   JSON envelope with the full wav inline (one-shot).

As of 2026-07-12 the project no longer ships a CosyVoice3 backend; the
MiniMax cloud is the sole supported TTS provider.

Default port: ``8985``.
"""


from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import re
import time
import uuid
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import aiofiles
import httpx
import uvicorn
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import JSONResponse

from .cloud_clone import MiniMaxClient
from .models import SynthesizeRequest, SynthesizeResponse, VoiceInfo

logger = logging.getLogger("joyvl_voice_clone")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8985
DEFAULT_VOICES_DIR = "voices"
DEFAULT_SAMPLE_RATE = 24000
ALLOWED_AUDIO_EXT = {".wav", ".mp3"}
VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{4,64}$")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


class Settings:
    """Runtime configuration loaded from environment variables."""

    def __init__(self) -> None:
        self.host: str = env_value("VOICE_CLONE_HOST", default=DEFAULT_HOST)
        self.port: int = int(env_value("VOICE_CLONE_PORT", default=str(DEFAULT_PORT)))
        self.voices_dir: Path = Path(
            env_value("VOICES_DIR", default=DEFAULT_VOICES_DIR)
        ).resolve()
        self.sample_rate: int = int(
            env_value("VOICE_SAMPLE_RATE", default=str(DEFAULT_SAMPLE_RATE))
        )
        self.request_timeout: float = float(
            env_value("VOICE_CLONE_TIMEOUT", default="120.0")
        )
        # TTS provider selection. As of 2026-07-12 only MiniMax is supported;
        # CosyVoice3 has been removed from the project (see doc/voice-clone.md
        # section 2). The provider must be set explicitly to ``minimax`` and
        # credentials must be present, otherwise the API refuses to boot.
        provider = env_value("TTS_PROVIDER", default="minimax").lower()
        if provider != "minimax":
            raise ValueError(
                f"Unsupported TTS_PROVIDER={provider!r}; expected 'minimax' "
                "(cosyvoice and stub were removed from this project)"
            )
        self.tts_provider: str = provider


        # MiniMax credentials (required when provider=minimax).
        self.minimax_api_key: str = env_value("MINIMAX_API_KEY", default="")
        self.minimax_group_id: str = env_value("MINIMAX_GROUP_ID", default="")
        self.minimax_base_url: str = env_value(
            "MINIMAX_BASE_URL", default="https://api.minimaxi.com"
        )
        # MiniMax defaults surfaced to /health and used as fallback for
        # synthesize requests. Override via env when testing newer model
        # versions or non-Mandarin personas.
        self.minimax_default_model: str = env_value(
            "MINIMAX_DEFAULT_MODEL", default="speech-2.8-hd"
        )
        self.minimax_language_boost: str = env_value(
            "MINIMAX_LANGUAGE_BOOST", default="Chinese"
        )
        # Hard requirement: MiniMax credentials must be present.
        if not (self.minimax_api_key and self.minimax_group_id):
            raise RuntimeError(
                "TTS_PROVIDER=minimax but MINIMAX_API_KEY / MINIMAX_GROUP_ID "
                "are missing. Set both before starting voice-clone."
            )


# ---------------------------------------------------------------------------
# Voice profile storage
# ---------------------------------------------------------------------------


class VoiceStore:
    """File-backed CRUD for voice profiles.

    Each profile lives in ``voices/<voice_id>/`` with three files:

    * ``ref.wav``     -- the original upload, rewritten as mono wav at
                          ``settings.sample_rate`` when possible.
    * ``ref.txt``     -- optional transcript stored with the reference audio.
    * ``meta.json``   -- serialised :class:`VoiceInfo`.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _is_valid_id(self, voice_id: str) -> bool:
        return bool(VOICE_ID_PATTERN.match(voice_id))

    def _dir(self, voice_id: str) -> Path:
        return self._root / voice_id

    async def _read_meta(self, voice_id: str) -> dict[str, Any] | None:
        meta_path = self._dir(voice_id) / "meta.json"
        if not meta_path.is_file():
            return None
        async with aiofiles.open(meta_path, encoding="utf-8") as fh:
            return json.loads(await fh.read())

    async def _write_meta(self, voice_id: str, payload: dict[str, Any]) -> None:
        meta_path = self._dir(voice_id) / "meta.json"
        async with aiofiles.open(meta_path, "w", encoding="utf-8") as fh:
            await fh.write(json.dumps(payload, ensure_ascii=False, indent=2))

    # -- public API ---------------------------------------------------------

    async def list(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir() or not self._is_valid_id(entry.name):
                continue
            meta = await self._read_meta(entry.name)
            if meta is not None:
                results.append(meta)
        return results

    async def get(self, voice_id: str) -> dict[str, Any]:
        if not self._is_valid_id(voice_id):
            raise HTTPException(status_code=400, detail="Invalid voice_id")
        meta = await self._read_meta(voice_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"voice_id {voice_id!r} not found")
        return meta

    async def delete(self, voice_id: str) -> None:
        if not self._is_valid_id(voice_id):
            raise HTTPException(status_code=400, detail="Invalid voice_id")
        target = self._dir(voice_id)
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"voice_id {voice_id!r} not found")
        for child in target.iterdir():
            try:
                child.unlink()
            except OSError:
                pass
        target.rmdir()

    async def create(
        self,
        *,
        name: str,
        audio_bytes: bytes,
        audio_ext: str,
        transcript: str | None,
        language: str,
        sample_rate_hint: int,
        language_boost: str = "Chinese",
        prompt_audio_path: str | None = None,
        prompt_audio_text: str | None = None,
    ) -> dict[str, Any]:
        """Persist a new voice profile and return its metadata.

        The optional ``language_boost`` / ``prompt_audio_*`` fields are
        forwarded to the MiniMax Rapid Clone endpoint at upload time
        (see cloud_clone.upload_reference). For non-MiniMax providers
        they are stored verbatim in ``meta.json`` for later inspection.
        """
        voice_id = f"vc_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        profile_dir = self._dir(voice_id)
        profile_dir.mkdir(parents=True, exist_ok=False)

        try:
            mono_bytes, mono_rate = _ensure_mono_pcm16(
                audio_bytes, audio_ext, sample_rate_hint
            )
        except (wave.Error, ValueError, EOFError):
            # MiniMax accepts encoded mp3/m4a payloads directly.
            mono_bytes, mono_rate = audio_bytes, sample_rate_hint

        ref_path = profile_dir / "ref.wav"
        async with aiofiles.open(ref_path, "wb") as fh:
            await fh.write(mono_bytes)

        meta: dict[str, Any] = {
            "voice_id": voice_id,
            "name": name,
            "duration_sec": round(len(mono_bytes) / max(1, mono_rate * 2), 3),
            "sample_rate": mono_rate,
            "language": language,
            "language_boost": language_boost,
            "prompt_audio_path": prompt_audio_path,
            "prompt_audio_text": prompt_audio_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ref_text": (transcript or "").strip(),
            "ref_audio_path": str(Path(voice_id) / "ref.wav"),
        }
        await self._write_meta(voice_id, meta)

        transcript_path = profile_dir / "ref.txt"
        async with aiofiles.open(transcript_path, "w", encoding="utf-8") as fh:
            await fh.write(meta["ref_text"])

        return meta


def _ensure_mono_pcm16(
    audio_bytes: bytes, ext: str, fallback_rate: int
) -> tuple[bytes, int]:
    """Normalize a wav upload to mono PCM16; pass other formats through.

    For ``.wav`` uploads we use the stdlib ``wave`` decoder. For
    ``.mp3`` and friends we hand the bytes back unchanged for MiniMax upload.
    """
    if ext.lower() != ".wav":
        return audio_bytes, fallback_rate
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frames = wav_file.readframes(wav_file.getnframes())
    if sample_width != 2:
        return audio_bytes, sample_rate
    if channels == 1:
        return audio_bytes, sample_rate
    # Down-mix stereo to mono by averaging the two channels.
    samples = wave.struct.unpack(f"<{len(frames) // 2}h", frames)
    mono = bytearray()
    for left, right in zip(samples[0::2], samples[1::2]):
        mono.extend(int((left + right) / 2).to_bytes(2, "little", signed=True))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(bytes(mono))
    return buffer.getvalue(), sample_rate


def _strip_wav_header(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """Return ``(pcm_bytes, sample_rate, sample_width)`` from a wav blob."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        return (
            wav_file.readframes(wav_file.getnframes()),
            wav_file.getframerate(),
            wav_file.getsampwidth(),
        )





# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    minimax: MiniMaxClient | None = None,
) -> FastAPI:
    """Build the FastAPI app. ``TTS_PROVIDER=minimax`` is the only supported
    provider as of 2026-07-12; the MiniMax client is constructed lazily from
    settings / env on first call.
    """
    settings = settings or Settings()
    if minimax is None and settings.tts_provider == "minimax":
        minimax = MiniMaxClient(
            api_key=settings.minimax_api_key,
            group_id=settings.minimax_group_id,
            base_url=settings.minimax_base_url,
            timeout=settings.request_timeout,
        )
    store = VoiceStore(settings.voices_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.voices_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "voice-clone ready on %s:%d (provider=%s, voices=%s)",
            settings.host,
            settings.port,
            settings.tts_provider,
            settings.voices_dir,
        )
        yield
        if minimax is not None:
            await minimax.close()

    app = FastAPI(title="JoyVL Voice Clone", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.minimax = minimax
    app.state.store = store

    # ----------------------------------------------------------------- routes

    @app.get("/health")
    async def health() -> JSONResponse:
        minimax_ok = None
        if minimax is not None:
            try:
                await minimax.test_connection()
                minimax_ok = True
            except (httpx.HTTPError, OSError) as err:
                minimax_ok = False
                logger.warning("MiniMax probe failed: %s", err)
        status = "ok" if minimax_ok else "degraded"
        return JSONResponse(
            {
                "status": status,
                "tts_provider": settings.tts_provider,
                "minimax_ok": minimax_ok,
                "minimax_model": settings.minimax_default_model,
                "minimax_language_boost": settings.minimax_language_boost,
                "voices_dir": str(settings.voices_dir),
                "voice_count": len(await store.list()),
                "sample_rate": settings.sample_rate,
            }
        )

    @app.get("/v1/voices")
    async def list_voices() -> dict[str, Any]:
        items = await store.list()
        return {"items": items, "count": len(items)}

    @app.post("/v1/voices", response_model=VoiceInfo)
    async def create_voice(
        name: Annotated[str, Form(min_length=1, max_length=64)],
        audio: Annotated[UploadFile, File(description="Reference wav/mp3")],
        transcript: Annotated[str | None, Form()] = None,
        language: Annotated[str, Form()] = "zh",
        language_boost: Annotated[str, Form()] = "Chinese",
        prompt_audio_path: Annotated[str | None, Form()] = None,
        prompt_audio_text: Annotated[str | None, Form()] = None,
    ) -> JSONResponse:
        ext = Path(audio.filename or "").suffix.lower() or ".wav"
        if ext not in ALLOWED_AUDIO_EXT:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported audio extension "
                    f"{ext!r}; expected one of {sorted(ALLOWED_AUDIO_EXT)}"
                ),
            )
        if language not in {"zh", "en", "auto"}:
            raise HTTPException(status_code=400, detail="language must be zh|en|auto")

        payload = audio.file.read()
        if not payload:
            raise HTTPException(status_code=400, detail="Empty audio upload")
        if len(payload) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Audio upload exceeds 25 MiB cap")

        meta = await store.create(
            name=name.strip(),
            audio_bytes=payload,
            audio_ext=ext,
            transcript=transcript,
            language=language,
            sample_rate_hint=settings.sample_rate,
            language_boost=language_boost,
            prompt_audio_path=prompt_audio_path,
            prompt_audio_text=prompt_audio_text,
        )

        # Register the profile with the MiniMax-only TTS backend.
        # Register the freshly-uploaded reference with MiniMax so /v1/synthesize
        # can route by cloud voice_id. Failure here is non-fatal -- the user can
        # re-trigger registration later via /v1/voices/{voice_id}/refresh.
        if settings.tts_provider == "minimax":
            if minimax is None:
                logger.warning("TTS_PROVIDER=minimax but client not initialised; skipping clone registration")
            else:
                try:
                    # MiniMax voice_id must start with a letter, 8-256 chars.
                    safe_local = ''.join(c if c.isalnum() or c in '-_' else '-' for c in meta['voice_id'])
                    clone_voice_id = f"bt-{safe_local[:240]}"
                    ref_path = settings.voices_dir / meta["ref_audio_path"]
                    clone_result = await minimax.upload_reference(
                        audio_path=str(ref_path),
                        voice_id=clone_voice_id,
                        ref_text=(meta.get("ref_text") or "")[:1000] or None,
                        prompt_audio_path=Path(prompt_audio_path) if prompt_audio_path else None,
                        prompt_audio_text=prompt_audio_text or None,
                        language_boost=language_boost or settings.minimax_language_boost,
                        model=settings.minimax_default_model,
                    )
                    meta["minimax_voice_id"] = clone_result.get("voice_id") or clone_voice_id
                    meta["minimax_cloned_at"] = datetime.now(timezone.utc).isoformat()
                    await store._write_meta(meta["voice_id"], meta)
                    logger.info(
                        "MiniMax clone registered: local=%s cloud=%s",
                        meta["voice_id"], meta["minimax_voice_id"],
                    )
                except (httpx.HTTPError, OSError, ValueError, RuntimeError) as err:
                    logger.warning(
                        "MiniMax clone failed for %s (local clone still kept): %s",
                        meta["voice_id"], err,
                    )

        return JSONResponse(meta, status_code=201)

    @app.get("/v1/voices/{voice_id}", response_model=VoiceInfo)
    async def get_voice(voice_id: str) -> dict[str, Any]:
        return await store.get(voice_id)

    @app.delete("/v1/voices/{voice_id}")
    async def delete_voice(voice_id: str) -> JSONResponse:
        await store.delete(voice_id)
        return JSONResponse({"status": "deleted", "voice_id": voice_id})

    # ------------------------------------------------------- /v1/synthesize

    @app.post("/v1/synthesize")
    async def synthesize(request: SynthesizeRequest):
        # Thin wrapper around the shared inner implementation; the real
        # provider branching lives in _do_synthesize() so the
        # /v1/synthesize/async alias can reuse it with use_async forced.
        return await _do_synthesize(request)

    # ------------------------------------------------------- /v1/synthesize/async

    @app.post("/v1/synthesize/async")
    async def synthesize_async_endpoint(request: SynthesizeRequest):
        """Convenience alias: always routes through the MiniMax async T2A path.

        For one-shot long-text synthesis (e.g. 剧情念白 > 10k chars). The
        response shape matches ``/v1/synthesize`` with ``streaming=false``.
        For real-time dialogue keep using ``/v1/synthesize``.
        """
        # Build a copy with use_async forced on and reuse the shared MiniMax
        # implementation below.
        forced = request.model_copy(update={"use_async": True, "streaming": False})
        return await _do_synthesize(forced)

    async def _do_synthesize(request: SynthesizeRequest):
        """Inner implementation shared by /v1/synthesize and /v1/synthesize/async."""
        try:
            meta = await store.get(request.voice_id)
        except HTTPException as err:
            if err.status_code != 404:
                raise
            # In MiniMax mode callers may pass an already-created cloud
            # voice_id directly (for example minimax_man_33333 from the
            # voice cloning console). Local reference audio is not needed
            # for synthesis in that path.
            meta = {
                "voice_id": request.voice_id,
                "minimax_voice_id": request.voice_id,
                "sample_rate": settings.sample_rate,
                "language_boost": settings.minimax_language_boost,
            }
        # MiniMax cloud synthesis.
        if settings.tts_provider == "minimax":
            if minimax is None:
                raise HTTPException(status_code=503, detail="MiniMax client not initialised")
            voice_id_field = meta.get("minimax_voice_id") or meta["voice_id"]
            target_sr = int(meta.get("sample_rate") or settings.sample_rate)
            language_boost = (
                request.language_boost
                or meta.get("language_boost")
                or settings.minimax_language_boost
            )
            model_name = request.model or settings.minimax_default_model

            if request.use_async:
                try:
                    wav_bytes = await minimax.synthesize_async(
                        text=request.text,
                        voice_id=voice_id_field,
                        model=model_name,
                        language_boost=language_boost,
                        sample_rate=target_sr,
                    )
                except (httpx.HTTPError, OSError, TimeoutError, RuntimeError) as err:
                    raise HTTPException(
                        status_code=502, detail=f"MiniMax async failed: {err}"
                    ) from err
                if not wav_bytes:
                    raise HTTPException(
                        status_code=502, detail="MiniMax async returned empty audio"
                    )
                try:
                    pcm, sample_rate, sample_width = _strip_wav_header(wav_bytes)
                except (wave.Error, ValueError, EOFError) as err:
                    raise HTTPException(
                        status_code=502, detail=f"MiniMax async returned invalid wav: {err}"
                    ) from err
                if sample_width != 2:
                    raise HTTPException(
                        status_code=502,
                        detail=f"MiniMax async returned non-pcm16 audio (width={sample_width})",
                    )
                response = SynthesizeResponse(
                    voice_id=request.voice_id,
                    sample_rate=sample_rate,
                    pcm16_base64=base64.b64encode(pcm).decode("ascii"),
                    duration_sec=round(len(pcm) / max(1, sample_rate * 2), 3),
                )
                return JSONResponse(response.model_dump())

            try:
                chunks = []
                async for chunk in minimax.zero_shot_synthesize(
                    text=request.text,
                    voice_id=voice_id_field,
                    model=model_name,
                    language_boost=language_boost,
                    sample_rate=target_sr,
                    streaming=False,
                ):
                    chunks.append(chunk)
                wav_bytes = b"".join(chunks)
            except (httpx.HTTPError, OSError) as err:
                raise HTTPException(
                    status_code=502, detail=f"MiniMax failed: {err}"
                ) from err
            if not wav_bytes:
                raise HTTPException(status_code=502, detail="MiniMax returned empty audio")
            try:
                pcm, sample_rate, sample_width = _strip_wav_header(wav_bytes)
            except (wave.Error, ValueError, EOFError) as err:
                raise HTTPException(
                    status_code=502, detail=f"MiniMax returned invalid wav: {err}"
                ) from err
            if sample_width != 2:
                raise HTTPException(
                    status_code=502,
                    detail=f"MiniMax returned non-pcm16 audio (width={sample_width})",
                )
            response = SynthesizeResponse(
                voice_id=request.voice_id,
                sample_rate=sample_rate,
                pcm16_base64=base64.b64encode(pcm).decode("ascii"),
                duration_sec=round(len(pcm) / max(1, sample_rate * 2), 3),
            )
            return JSONResponse(response.model_dump())



    return app

def _sse(payload: dict[str, Any]) -> str:
    """Format ``payload`` as a single Server-Sent Event data line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JoyVL voice clone service")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the FastAPI service")
    serve.add_argument("--host", default=env_value("VOICE_CLONE_HOST", default=DEFAULT_HOST))
    serve.add_argument(
        "--port",
        type=int,
        default=int(env_value("VOICE_CLONE_PORT", default=str(DEFAULT_PORT))),
    )
    serve.add_argument("--reload", action="store_true")

    parser.add_argument("--host", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args()

    if args.command is None:
        args.command = "serve"
        args.host = args.host or env_value("VOICE_CLONE_HOST", default=DEFAULT_HOST)
        args.port = args.port or int(env_value("VOICE_CLONE_PORT", default=str(DEFAULT_PORT)))
        args.reload = False

    settings = Settings()
    settings.host = args.host or settings.host
    settings.port = args.port or settings.port
    app = create_app(settings=settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=bool(args.reload),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
    return 0


# ---------------------------------------------------------------------------
# Module-level ASGI app. Lets users launch with
# ``uvicorn voice_clone_api.main:app`` (no --factory) as well as the
# factory form ``uvicorn voice_clone_api.main:create_app --factory``.
# ---------------------------------------------------------------------------
app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())

