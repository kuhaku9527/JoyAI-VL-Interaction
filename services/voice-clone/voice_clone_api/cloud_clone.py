"""MiniMax Rapid Clone + T2A v2 (sync + async) client.

Official docs:
  - Rapid Clone:    https://platform.minimaxi.com/docs/api-reference/voice-cloning-clone
  - File Upload:    https://platform.minimaxi.com/docs/api-reference/file-management-upload
  - T2A v2:         https://platform.minimaxi.com/docs/api-reference/speech-t2a-http
  - T2A async v2:   https://platform.minimaxi.com/docs/api-reference/speech-t2a-async-create
  - T2A async query:https://platform.minimaxi.com/docs/api-reference/speech-t2a-async-query
  - Files Retrieve: https://platform.minimaxi.com/docs/api-reference/file-management-retrieve-content

Environment variables (**never hard-code**):
  - MINIMAX_API_KEY  : Bearer Token (sk-cp-* Token Plan or sk-api-* pay-as-you-go)
  - MINIMAX_GROUP_ID : query param for file uploads

Base URL: https://api.minimaxi.com/

Sync flow (Rapid Clone + T2A v2, used for real-time dialogue):
  1. Upload reference audio to /v1/files/upload?GroupId=<group_id> -> file_id
  2. (Optional) Upload prompt_audio (purpose=prompt_audio, <8s) -> prompt_file_id
  3. POST /v1/voice_clone {file_id, voice_id, model, text, language_boost, clone_prompt?...}
     -> voice_id (7-day window; activated voice_ids persist)
  4. POST /v1/t2a_v2 {model, text, voice_setting, audio_setting, language_boost, stream}
     -> SSE stream (or single JSON) of hex-encoded audio chunks

Async flow (long-text T2A, for >10k chars only):
  1. POST /v1/t2a_async_v2 -> task_id
  2. Poll GET /v1/query/t2a_async_query_v2?task_id=<id> until status == "success"
  3. GET /v1/files/retrieve_content?file_id=<file_id> -> audio bytes
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

logger = logging.getLogger("joyai.voice-clone.minimax")

MINIMAX_BASE = "https://api.minimaxi.com"

# speech-2.8 added interjection (laugh/sigh/cough) and improved prosody for
# Mandarin. We default to HD because the BT-7274 persona is immersive dialogue.
DEFAULT_MODEL = "speech-2.8-hd"
SUPPORTED_MODELS = [
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
]

# File upload limits (per MiniMax File Upload API).
MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MiB
ALLOWED_AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a")
# clone_prompt.prompt_audio must be < 8s per the Rapid Clone API.
PROMPT_AUDIO_MAX_SECONDS = 8

# Default language hint for T2A. The BT-7274 persona is Mandarin.
DEFAULT_LANGUAGE_BOOST = "Chinese"

BT_DESIGNATION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])BT\s*[-‐‑‒–—−]?\s*7274(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _get_credentials(api_key: str | None = None, group_id: str | None = None) -> tuple[str, str]:
    """Read credentials from arguments or environment. Never hard-coded."""
    key = api_key or os.environ.get("MINIMAX_API_KEY", "")
    gid = group_id or os.environ.get("MINIMAX_GROUP_ID", "")
    if not key:
        raise ValueError(
            "MINIMAX_API_KEY not set. Use one of:\n"
            "  PowerShell: [Environment]::SetEnvironmentVariable('MINIMAX_API_KEY','<key>','User')\n"
            "  Bash:       export MINIMAX_API_KEY=<key>\n"
            "  .env:       MINIMAX_API_KEY=<key>"
        )
    if not gid:
        raise ValueError("MINIMAX_GROUP_ID not set")
    return key, gid


def _validate_voice_id(voice_id: str) -> str:
    """Enforce MiniMax Rapid Clone constraints: 8-256 chars, letter start."""
    voice_id = voice_id.strip()
    if not voice_id:
        raise ValueError("voice_id must not be empty")
    if not voice_id[0].isalpha():
        raise ValueError(f"voice_id must start with a letter: {voice_id!r}")
    if len(voice_id) < 8 or len(voice_id) > 256:
        raise ValueError(f"voice_id length must be 8-256 chars (got {len(voice_id)}): {voice_id!r}")
    if voice_id[-1] in "-_":
        raise ValueError(f"voice_id must not end with '-' or '_': {voice_id!r}")
    return voice_id


def _raise_on_minimax_error(payload: dict, context: str) -> None:
    """Raise if MiniMax returned an application-level error in base_resp."""
    base_resp = payload.get("base_resp") or {}
    code = base_resp.get("status_code")
    if code not in (None, 0):
        msg = base_resp.get("status_msg", "")
        raise RuntimeError(f"{context}: {code} {msg}".strip())


def _decode_audio_payload(audio: str) -> bytes:
    """Decode MiniMax audio payloads.

    Current T2A v2 returns hex text (for example WAV starts with
    ``52494646``). Keep a base64 fallback for older/local mocks.
    """
    value = audio.strip()
    if not value:
        return b""
    try:
        return bytes.fromhex(value)
    except ValueError:
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as err:
            raise RuntimeError("MiniMax audio payload is neither hex nor base64") from err


def _normalize_tts_text(text: str) -> str:
    """Keep display text untouched, but make known call signs TTS-friendly."""
    return BT_DESIGNATION_PATTERN.sub("BT七二七四", text)


class MiniMaxClient:
    """Async HTTP client for MiniMax Rapid Clone + T2A v2 + T2A async v2."""

    def __init__(
        self,
        api_key: str | None = None,
        group_id: str | None = None,
        base_url: str = MINIMAX_BASE,
        timeout: float = 30.0,
    ):
        self.api_key, self.group_id = _get_credentials(api_key, group_id)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self, content_type: str | None = None) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ------------------------------------------------------------------
    # Health / probe
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict:
        """Probe auth with the documented voice-management endpoint."""
        voices = await self.list_voices()
        return {
            "provider": "minimax",
            "group_id": self.group_id,
            "status": "ok",
            "msg": "success",
            "voice_count": len(voices),
        }

    # ------------------------------------------------------------------
    # Step 1: upload reference / prompt audio
    # ------------------------------------------------------------------

    async def _upload_audio_file(self, audio_path: Path, *, purpose: str) -> str:
        """Upload an audio file to /v1/files/upload with the given purpose.

        ``purpose="voice_clone"`` -> file_id for the /v1/voice_clone payload.
        ``purpose="prompt_audio"`` -> file_id for clone_prompt.prompt_audio.
        """
        if purpose not in {"voice_clone", "prompt_audio"}:
            raise ValueError(f"Invalid upload purpose: {purpose!r}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Reference audio not found: {audio_path}")
        suffix = audio_path.suffix.lower()
        if suffix not in ALLOWED_AUDIO_SUFFIXES:
            raise ValueError(f"Unsupported audio format: {suffix} (need wav/mp3/m4a)")
        size = audio_path.stat().st_size
        if size > MAX_AUDIO_BYTES:
            raise ValueError(f"Audio file exceeds {MAX_AUDIO_BYTES} bytes: {size} bytes")

        client = await self._get_client()
        files = {
            "file": (
                audio_path.name,
                audio_path.read_bytes(),
                {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(
                    suffix, "audio/wav"
                ),
            )
        }
        data = {"purpose": purpose}
        resp = await client.post(
            "/v1/files/upload",
            params={"GroupId": self.group_id},
            files=files,
            data=data,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("base_resp", {}).get("status_code") != 0:
            raise RuntimeError(f"MiniMax file upload ({purpose}) failed: {payload}")
        file_id = payload.get("file", {}).get("file_id")
        if not file_id:
            raise RuntimeError(f"No file_id in upload response: {payload}")
        logger.info(
            "Audio uploaded: purpose=%s, file_id=%s, bytes=%d, name=%s",
            purpose,
            file_id,
            size,
            audio_path.name,
        )
        return file_id

    # Backwards-compat alias used by older callers / smoke tests.
    async def _upload_reference_file(self, audio_path: Path) -> str:
        """Legacy wrapper: uploads with purpose=voice_clone."""
        return await self._upload_audio_file(audio_path, purpose="voice_clone")

    # ------------------------------------------------------------------
    # Step 2: Rapid Clone (with optional clone_prompt for higher similarity)
    # ------------------------------------------------------------------

    async def upload_reference(
        self,
        audio_path: str | Path,
        *,
        voice_id: str,  # 8-256 chars, letter start
        ref_text: str | None = None,  # preview text (<=1000 chars)
        prompt_audio_path: str | Path | None = None,  # optional <8s clip for higher similarity
        prompt_audio_text: str | None = None,  # transcript of prompt_audio_path
        language_boost: str = DEFAULT_LANGUAGE_BOOST,  # "Chinese" | "auto" | other ISO codes
        model: str = DEFAULT_MODEL,
        need_noise_reduction: bool = False,
        need_volume_normalization: bool = False,
        aigc_watermark: bool = False,
    ) -> dict:
        """Full Rapid Clone flow: upload -> clone -> return voice metadata.

        Args:
            audio_path: 10s-5min reference audio (wav/mp3/m4a, <=20MB).
            voice_id: explicit voice_id (length 8-256, must start with a letter).
            ref_text: optional preview text shown in voice inventory (<=1000 chars).
            prompt_audio_path: optional extra <8s reference clip, uploaded as
                ``clone_prompt.prompt_audio`` to raise timbre similarity. If
                provided, ``prompt_audio_text`` is required.
            prompt_audio_text: transcript of ``prompt_audio_path``; required
                when ``prompt_audio_path`` is set so the TTS model knows
                what the prompt clip says.
            language_boost: language hint for T2A ("Chinese", "auto", or an
                ISO code like "English", "Japanese"). Defaults to "Chinese"
                because the BT-7274 persona speaks Mandarin.
            model: speech-2.8-hd (default) / speech-2.8-turbo / etc.
            need_noise_reduction: apply MiniMax noise reduction.
            need_volume_normalization: normalise loudness.
            aigc_watermark: embed an AIGC watermark in clone preview.

        Returns
        -------
            {"voice_id", "file_id", "model", "prompt_file_id" (or None)}.
        """
        if model not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model {model!r}; expected one of {SUPPORTED_MODELS}")
        voice_id = _validate_voice_id(voice_id)

        p = Path(audio_path)
        file_id = await self._upload_audio_file(p, purpose="voice_clone")

        clone_prompt: dict | None = None
        prompt_file_id: str | None = None
        if prompt_audio_path is not None:
            prompt_p = Path(prompt_audio_path)
            if not prompt_audio_text:
                raise ValueError("prompt_audio_text is required when prompt_audio_path is provided")
            prompt_file_id = await self._upload_audio_file(prompt_p, purpose="prompt_audio")
            clone_prompt = {
                "prompt_audio": prompt_file_id,
                "prompt_text": prompt_audio_text,
            }

        client = await self._get_client()
        payload: dict = {
            "file_id": file_id,
            "voice_id": voice_id,
            "model": model,
            "text": (ref_text or "This is a sample text.")[:1000],
            "need_noise_reduction": need_noise_reduction,
            "need_volume_normalization": need_volume_normalization,
            "aigc_watermark": aigc_watermark,
            "language_boost": language_boost,
        }
        if clone_prompt is not None:
            payload["clone_prompt"] = clone_prompt

        resp = await client.post("/v1/voice_clone", json=payload)
        resp.raise_for_status()
        result = resp.json()
        if result.get("base_resp", {}).get("status_code") != 0:
            raise RuntimeError(f"MiniMax voice clone failed: {result}")

        logger.info(
            "Voice cloned: voice_id=%s, model=%s, ref_audio=%s, prompt_audio=%s, ref_text=%d chars",
            voice_id,
            model,
            p.name,
            Path(prompt_audio_path).name if prompt_audio_path else None,
            len(ref_text or ""),
        )
        return {
            "voice_id": voice_id,
            "file_id": file_id,
            "model": model,
            "prompt_file_id": prompt_file_id,
        }

    # ------------------------------------------------------------------
    # Step 3: T2A v2 sync synthesis (real-time dialogue, default path)
    # ------------------------------------------------------------------

    async def zero_shot_synthesize(
        self,
        text: str,
        voice_id: str,
        *,
        model: str = DEFAULT_MODEL,
        speed: float = 1.0,
        vol: float = 1.0,
        pitch: int = 0,
        sample_rate: int = 24000,
        streaming: bool = True,
        language_boost: str = DEFAULT_LANGUAGE_BOOST,  # backward-compat kwarg (default-safe)
    ) -> AsyncIterator[bytes]:
        """T2A v2 synthesis (SSE stream or one-shot JSON).

        This is the **default** synthesis path for real-time dialogue.
        For texts exceeding the 10k char limit or batch jobs, use
        ``synthesize_async`` instead -- async polling adds ~1-3s
        latency on top of synthesis.

        Args:
            text: text to synthesise (<=10000 chars).
            voice_id: voice_id returned by ``upload_reference``.
            model: speech-2.8-hd / speech-2.8-turbo / etc.
            speed: 0.5-2.0.
            vol: 0.1-10.0.
            pitch: -12 ~ 12.
            sample_rate: 16000 / 24000 / 32000.
            streaming: True = SSE chunks / False = single response.
            language_boost: language hint forwarded to the T2A payload.
                Added as a backward-compatible kwarg with default
                "Chinese"; pre-existing callers are unaffected.

        Yields
        ------
            Audio bytes (WAV when ``audio_setting.format`` is ``wav``).
        """
        if len(text) > 10000:
            raise ValueError(f"text exceeds 10000 chars: {len(text)}")

        tts_text = _normalize_tts_text(text)
        client = await self._get_client()
        payload = {
            "model": model,
            "text": tts_text,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": vol,
                "pitch": pitch,
            },
            "audio_setting": {
                "sample_rate": sample_rate,
                "format": "wav",
                "channel": 1,
            },
            "stream": streaming,
            "language_boost": language_boost,
        }
        headers = {"Accept": "text/event-stream"} if streaming else {}
        resp = await client.post("/v1/t2a_v2", json=payload, headers=headers)
        resp.raise_for_status()

        if not streaming:
            data = resp.json()
            _raise_on_minimax_error(data, "MiniMax t2a_v2 failed")
            audio_hex = data.get("data", {}).get("audio") or ""
            if audio_hex:
                yield _decode_audio_payload(audio_hex)
            return

        # SSE streaming
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]" or not data_str:
                continue
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            _raise_on_minimax_error(chunk, "MiniMax t2a_v2 stream failed")
            audio_hex = (
                chunk.get("data", {}).get("audio") or chunk.get("extra_info", {}).get("audio") or ""
            )
            if audio_hex:
                yield _decode_audio_payload(audio_hex)

    # ------------------------------------------------------------------
    # Step 3b: T2A v2 ASYNC synthesis (long-text only)
    # ------------------------------------------------------------------

    async def synthesize_async(
        self,
        text: str,
        voice_id: str,
        *,
        model: str = DEFAULT_MODEL,
        language_boost: str = DEFAULT_LANGUAGE_BOOST,
        speed: float = 1.0,
        vol: float = 1.0,
        pitch: int = 0,
        sample_rate: int = 24000,
        format: str = "wav",
        max_wait_s: float = 60.0,
        poll_interval_s: float = 0.5,
    ) -> bytes:
        """Submit a T2A async task, poll for completion, return WAV bytes.

        Use this **only** for texts >10k chars (e.g. narration scripts).
        For real-time dialogue keep using ``zero_shot_synthesize`` --
        async polling adds ~1-3s latency on top of synthesis.

        Flow:
            1. POST /v1/t2a_async_v2 -> task_id
            2. GET /v1/query/t2a_async_query_v2?task_id=<id> every
               ``poll_interval_s`` seconds until status == "success"
               (or "failed")
            3. GET /v1/files/retrieve?file_id=<file_id> -> raw audio
               bytes (the URL is valid 9h after success)

        Args:
            text: long text to synthesise.
            voice_id: voice_id from ``upload_reference``.
            model: speech-2.8-hd (default) / speech-2.8-turbo / etc.
            language_boost: language hint ("Chinese", "auto", or ISO code).
            speed / vol / pitch: same constraints as sync synthesis.
            sample_rate: 16000 / 24000 / 32000.
            format: audio container ("wav" / "mp3" / etc.).
            max_wait_s: max seconds to wait for task completion.
            poll_interval_s: sleep between poll requests.

        Returns
        -------
            Raw audio bytes (container = ``format``).
        """
        if model not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model {model!r}; expected one of {SUPPORTED_MODELS}")
        if not text:
            raise ValueError("text must not be empty")

        tts_text = _normalize_tts_text(text)
        client = await self._get_client()
        payload = {
            "model": model,
            "text": tts_text,
            "voice_setting": {
                "voice_id": voice_id,
                "speed": speed,
                "vol": vol,
                "pitch": pitch,
            },
            "audio_setting": {
                "audio_sample_rate": sample_rate,
                "format": format,
                "channel": 1,
            },
            "language_boost": language_boost,
        }

        # 1. Submit
        resp = await client.post("/v1/t2a_async_v2", json=payload)
        resp.raise_for_status()
        submit = resp.json()
        if submit.get("base_resp", {}).get("status_code") != 0:
            raise RuntimeError(f"MiniMax t2a_async_v2 submit failed: {submit}")
        task_id = submit.get("task_id")
        if not task_id:
            raise RuntimeError(f"No task_id in submit response: {submit}")
        logger.info("T2A async task submitted: task_id=%s, chars=%d", task_id, len(tts_text))

        # 2. Poll for completion
        deadline = time.monotonic() + max_wait_s
        file_id: str | None = None
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval_s)
            poll_resp = await client.get(
                "/v1/query/t2a_async_query_v2", params={"task_id": task_id}
            )
            poll_resp.raise_for_status()
            poll = poll_resp.json()
            _raise_on_minimax_error(poll, "MiniMax t2a_async_v2 poll failed")
            status = (poll.get("status") or poll.get("task_status") or "").lower()
            if status == "success":
                file_id = poll.get("file_id")
                if not file_id:
                    raise RuntimeError(f"success status without file_id: {poll}")
                break
            if status in {"failed", "fail", "error"}:
                raise RuntimeError(f"MiniMax t2a_async_v2 task failed: {poll}")
            # else: "processing" / "pending" / "queued" -- keep polling

        if file_id is None:
            raise TimeoutError(f"T2A async task {task_id} did not complete within {max_wait_s}s")

        # 3. Download the produced audio
        dl_resp = await client.get("/v1/files/retrieve_content", params={"file_id": file_id})
        dl_resp.raise_for_status()
        audio_bytes = dl_resp.content
        logger.info(
            "T2A async task complete: task_id=%s, file_id=%s, bytes=%d",
            task_id,
            file_id,
            len(audio_bytes),
        )
        return audio_bytes

    # ------------------------------------------------------------------
    # Voice management
    # ------------------------------------------------------------------

    async def list_voices(self) -> list[dict]:
        """List all voices under this account.

        Uses POST /v1/get_voice with body {"voice_type": "all"} per the
        MiniMax docs at:
            https://platform.minimaxi.com/docs/api-reference/voice-management-get

        Note: ``voice_type=voice_cloning`` returns only voices that have
        been activated (used at least once via /v1/t2a_v2).

        Token Plan subscription keys (``sk-cp-*``) and pay-as-you-go API
        keys (``sk-api-*``) are separate billing credentials, but both can
        authenticate here when the account/team has access. See
        doc/voice-clone.md sec 15.4.
        """
        client = await self._get_client()
        resp = await client.post("/v1/get_voice", json={"voice_type": "all"})
        resp.raise_for_status()
        data = resp.json()
        if data.get("base_resp", {}).get("status_code") != 0:
            raise RuntimeError(f"MiniMax list_voices failed: {data}")
        cloning = data.get("voice_cloning") or []
        generated = data.get("voice_generation") or []
        system_v = data.get("system_voice") or []
        out = (
            sorted(
                [{"_kind": "cloning", **d} for d in cloning],
                key=lambda d: d.get("created_time", ""),
                reverse=True,
            )
            + sorted(
                [{"_kind": "generation", **d} for d in generated],
                key=lambda d: d.get("created_time", ""),
                reverse=True,
            )
            + [{"_kind": "system", **d} for d in system_v]
        )
        return out

    async def delete_voice(self, voice_id: str) -> None:
        """Delete a cloned voice."""
        client = await self._get_client()
        resp = await client.post(
            "/v1/voice/delete",
            json={"GroupId": self.group_id, "voice_id": voice_id},
        )
        resp.raise_for_status()
        logger.info("Voice deleted: %s", voice_id)


# ============================================================================
# Standalone smoke test: clone once + synthesise one sentence.
# ============================================================================


async def _smoke_test():
    ref_wav = Path(
        "D:/AI/workspace/bt-voice/ref_audio/1.BT-7274/diag_sp_pilotLink_WD141_43_01_mcor_bt.wav"
    )
    if not ref_wav.exists():
        print(f"Reference audio missing: {ref_wav}")
        return

    async with MiniMaxClient() as client:
        # 1. Health check
        status = await client.test_connection()
        print(f"[1] connection: {status}")

        # 2. Clone (uses new voice_id-keyed signature)
        result = await client.upload_reference(
            audio_path=str(ref_wav),
            voice_id="bt7274_smoke_test",
            ref_text="\u6211\u662fBT7274\u3002",  # "I am BT-7274."
            model="speech-2.8-hd",
        )
        print(f"[2] clone ok: {result}")

        # 3. Synthesise one short sentence
        print("[3] synthesising short utterance ...")
        total = 0
        async for chunk in client.zero_shot_synthesize(
            "Iron Lady, reporting in.",
            result["voice_id"],
            sample_rate=24000,
        ):
            total += len(chunk)
        print(f"[3] audio bytes: {total}")


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_smoke_test())
