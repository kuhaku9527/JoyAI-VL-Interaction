#!/usr/bin/env python3
"""Generate BT-7274 Jarvis event audio (wake.wav, goodbye.wav).

Calls the local voice_clone_api FastAPI shim (port 8985), which in turn
forwards synthesis to either the local CosyVoice3 server (port 8991) or
the MiniMax cloud (when a MiniMax API key is configured). After running,
the three event wav files live in ``prompts/bt/events/``.

Prereqs:
    * voice_clone_api (port 8985) is up and reports ``cosyvoice_ok=true``
      OR has MiniMax credentials set.
    * A voice profile is already registered under ``voice_id`` (e.g.
      ``bt-7274``); use the :func:`register_voice` helper below.

Usage:
    python services/scripts/generate_event_audio.py \\
        --voice-id bt-7274 \\
        --api-url http://127.0.0.1:8985

The script never crashes the pipeline if the cloud TTS is unavailable;
it just logs a warning and leaves the pre-existing placeholder files in
place so the state machine can still be smoke-tested.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import sys
from pathlib import Path

import httpx

logger = logging.getLogger("event-audio-gen")

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO_ROOT / "prompts" / "bt" / "events"

EVENTS: list[tuple[str, str, float]] = [
    # (filename, text, expected_duration_sec)
    ("wake", "铁御，我在", 1.6),
    ("goodbye", "任务完成，断开神经链接", 2.2),
]


async def register_voice(
    client: httpx.AsyncClient,
    api_url: str,
    ref_wav: Path,
    ref_text: str,
    voice_id_hint: str = "bt-7274",
) -> str:
    """Register a voice profile on the voice_clone_api shim.

    Returns the ``voice_id`` returned by the server (may differ from the
    hint because the server generates a ``vc_<ts>_<rand>`` id).
    """
    if not ref_wav.is_file():
        raise FileNotFoundError(f"Reference wav not found: {ref_wav}")

    with open(ref_wav, "rb") as fh:
        files = {"audio": (ref_wav.name, fh, "audio/wav")}
        data = {"name": voice_id_hint, "transcript": ref_text, "language": "zh"}
        resp = await client.post(
            f"{api_url}/v1/voices",
            files=files,
            data=data,
            timeout=60.0,
        )
    resp.raise_for_status()
    payload = resp.json()
    actual_id = payload["voice_id"]
    logger.info("Registered voice %r -> server voice_id=%s", voice_id_hint, actual_id)
    return actual_id


async def synthesize(
    client: httpx.AsyncClient,
    api_url: str,
    voice_id: str,
    text: str,
) -> bytes:
    """POST /v1/synthesize -> raw PCM16 bytes (24kHz mono)."""
    resp = await client.post(
        f"{api_url}/v1/synthesize",
        json={
            "text": text,
            "voice_id": voice_id,
            "streaming": False,
            "sample_rate": 24000,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    # voice_clone_api returns pcm16_base64 (when non-streaming)
    audio_b64 = payload.get("pcm16_base64") or payload.get("audio")
    if not audio_b64:
        raise RuntimeError(f"No audio in synthesize response: {payload}")
    return base64.b64decode(audio_b64)


def wrap_pcm16_as_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw PCM16 mono as a minimal RIFF/WAV file."""
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


async def main_async(args: argparse.Namespace) -> int:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient() as client:
        # 1) Register voice (skip with --skip-register)
        if args.skip_register:
            voice_id = args.voice_id
            logger.info("Skipping register, using voice_id=%s", voice_id)
        else:
            ref_wav = Path(args.ref_wav).resolve()
            voice_id = await register_voice(
                client, args.api_url, ref_wav, args.ref_text, args.voice_id
            )

        # 2) Synthesize each event
        for name, text, _expected_dur in EVENTS:
            out_path = EVENTS_DIR / f"{name}.wav"
            logger.info("Synthesizing %s.wav: %r", name, text)
            try:
                pcm = await synthesize(client, args.api_url, voice_id, text)
            except httpx.HTTPError as exc:
                logger.warning(
                    "TTS failed for %s.wav (%s); leaving existing file in place",
                    name, exc,
                )
                continue

            wav_bytes = wrap_pcm16_as_wav(pcm, sample_rate=24000)
            out_path.write_bytes(wav_bytes)
            logger.info("Wrote %s (%d bytes)", out_path, len(wav_bytes))

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api-url", default="http://127.0.0.1:8985")
    p.add_argument(
        "--voice-id",
        default="bt-7274",
        help="Friendly voice name; server assigns a real voice_id on register.",
    )
    p.add_argument(
        "--ref-wav",
        default=r"D:\AI\workspace\bt-voice\ref_audio\1.BT-7274\diag_sp_pilotLink_WD141_43_01_mcor_bt.wav",
        help="Reference audio (BT-7274 voice sample, 5-15s).",
    )
    p.add_argument(
        "--ref-text",
        default="我们的命令是要展开特殊作业二一七",
        help="Transcript of the reference audio (improves clone quality).",
    )
    p.add_argument(
        "--skip-register",
        action="store_true",
        help="Skip the POST /v1/voices call (use an existing voice_id).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())