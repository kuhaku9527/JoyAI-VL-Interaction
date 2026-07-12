"""MiniMax Speech 2.8 cloud TTS streaming synthesizer.

Plugs into tts_adapter.py as the primary cloud TTS backend.
MiniMax is the project's all-in-one provider (LLM + Agent + TTS + Voice Clone + Vision).

Docs: https://platform.minimax.chat/document/T2A%20V2

Usage:
    from http_synthesizer import MiniMaxTTSSynthesizer
    synth = MiniMaxTTSSynthesizer(api_key="eyJ...", group_id="...", voice_id="...")
    async for audio_chunk in synth.synthesize("你好"):
        await client.send_bytes(audio_chunk)
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import httpx

logger = logging.getLogger("joyai.tts.minimax")

MINIMAX_TTS_URL = "https://api.minimax.chat/v1/t2a_v2"


@dataclass
class MiniMaxTTSConfig:
    """MiniMax Speech 2.8 TTS parameters."""

    api_key: str = ""
    """MiniMax API key (Token Plan 内自动续)."""

    group_id: str = ""
    """MiniMax group ID."""

    voice_id: str = ""
    """MiniMax cloned voice_id (from Rapid Clone upload)."""

    model: str = "speech-2.8-minimax"

    sample_rate: int = 16000
    """Output sample rate (16000 or 24000)."""

    speed: float = 1.0
    """0.5 - 2.0."""

    vol: float = 1.0
    """0.1 - 2.0."""


class MiniMaxTTSSynthesizer:
    """Stream TTS via MiniMax Speech 2.8 SSE API."""

    def __init__(self, config: MiniMaxTTSConfig):
        if not config.api_key:
            raise ValueError("MINIMAX_API_KEY is required")
        if not config.group_id:
            raise ValueError("MINIMAX_GROUP_ID is required")
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: Optional[str] = None,
        speed: Optional[float] = None,
        vol: Optional[float] = None,
    ) -> AsyncIterator[bytes]:
        """Stream-synthesize text via MiniMax T2A V2 SSE, yielding raw audio chunks.

        Args:
            text: Chinese text (≤ 2000 chars).
            voice_id: override voice_id (uses config.voice_id if None).
            speed: override speed (0.5-2.0).
            vol: override volume (0.1-2.0).

        Yields:
            Raw WAV audio chunks (concatenable into a complete WAV file).
        """
        vid = voice_id or self.config.voice_id
        if not vid:
            raise ValueError("voice_id is required — set MINIMAX_VOICE_ID or pass explicitly")

        voice_setting: dict = {"voice_id": vid}
        voice_setting["speed"] = speed or self.config.speed
        voice_setting["vol"] = vol or self.config.vol

        payload = {
            "model": self.config.model,
            "text": text,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": self.config.sample_rate,
                "format": "wav",
                "channel": 1,
            },
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST", MINIMAX_TTS_URL, json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()

                total = 0
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            extra = chunk.get("extra_info", {})
                            audio_b64 = extra.get("audio")
                            if audio_b64:
                                audio_chunk = base64.b64decode(audio_b64)
                                total += len(audio_chunk)
                                yield audio_chunk
                        except json.JSONDecodeError:
                            continue

        logger.debug("MiniMax TTS complete: voice=%s, bytes=%d", vid, total)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def ping(self) -> bool:
        """Quick connectivity check via voice list endpoint (no charge)."""
        try:
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.minimax.chat/v1/voice/list",
                    params={"group_id": self.config.group_id},
                    headers=headers,
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("MiniMax TTS ping failed: %s", exc)
            return False


# ============================================================================
# Smoke test
# ============================================================================

async def _smoke_test():
    import os
    api_key = os.getenv("MINIMAX_API_KEY", "")
    group_id = os.getenv("MINIMAX_GROUP_ID", "")
    voice_id = os.getenv("MINIMAX_VOICE_ID", "")

    if not api_key:
        print("Skipping: set MINIMAX_API_KEY")
        return

    config = MiniMaxTTSConfig(api_key=api_key, group_id=group_id, voice_id=voice_id)
    synth = MiniMaxTTSSynthesizer(config)

    ok = await synth.ping()
    print(f"Ping: {ok}")

    if voice_id:
        chunks = []
        async for chunk in synth.synthesize("铁御，我在"):
            chunks.append(chunk)
        print(f"TTS: {sum(len(c) for c in chunks)} bytes")


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_smoke_test())