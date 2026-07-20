# SPDX-License-Identifier: Apache-2.0

"""Pydantic schemas for the voice clone API.

These models define the wire contract between the webui/Jarvis chain
and the voice-clone FastAPI service. Keep field names stable: they are
documented in ``README.md`` and consumed by the WebUI without any
transformation.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Voice profile CRUD
# ---------------------------------------------------------------------------


class VoiceCreateRequest(BaseModel):
    """Form-style metadata for ``POST /v1/voices``.

    The audio file itself is uploaded as a multipart ``audio`` field; the
    fields here describe how to interpret the upload.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Display name for the voice profile",
    )
    transcript: str | None = Field(
        default=None,
        description=(
            "Reference text spoken in the uploaded audio. Optional, but "
            "recommended for deterministic MiniMax clone alignment."
        ),
    )
    language: Literal["zh", "en", "auto"] = Field(
        default="zh",
        description="Reference audio language hint for MiniMax cloning.",
    )
    language_boost: str = Field(
        default="Chinese",
        description=(
            "Language hint forwarded to MiniMax T2A (e.g. 'Chinese', "
            "'auto', 'English')."
        ),
    )
    prompt_audio_path: str | None = Field(
        default=None,
        description=(
            "Optional path to a short (<8s) reference clip. When provided "
            "this clip is uploaded as MiniMax "
            "``clone_prompt.prompt_audio`` to raise timbre similarity. The "
            "clip's transcript should be passed via ``prompt_audio_text``."
        ),
    )
    prompt_audio_text: str | None = Field(
        default=None,
        description=(
            "Transcript of ``prompt_audio_path``. Required when "
            "``prompt_audio_path`` is set, so the TTS model knows what "
            "the prompt clip says."
        ),
    )


class VoiceInfo(BaseModel):
    """Public representation of a stored voice profile."""

    voice_id: str = Field(..., description="Stable id used in /v1/synthesize calls")
    name: str
    duration_sec: float = Field(..., description="Length of the reference audio in seconds")
    sample_rate: int = Field(..., description="Sample rate of the reference audio (Hz)")
    language: str
    created_at: datetime
    ref_text: str = Field(default="", description="Stored transcript for the reference audio")
    ref_audio_path: str = Field(..., description="Relative path under the voices/ directory")


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


class SynthesizeRequest(BaseModel):
    """Body for ``POST /v1/synthesize``."""

    text: str = Field(..., min_length=1, max_length=4000, description="Text to synthesise")
    voice_id: str = Field(..., description="Voice profile id from /v1/voices")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech-rate multiplier (best-effort)")
    streaming: bool = Field(
        default=False,
        description=(
            "When true the endpoint replies with Server-Sent Events of base64 "
            "PCM16 chunks. When false it returns a single ``SynthesizeResponse`` "
            "with the full wav bytes inline."
        ),
    )
    language_boost: str = Field(
        default="Chinese",
        description=(
            "MiniMax language hint ('Chinese', 'auto', 'English', etc.)."
        ),
    )
    use_async: bool = Field(
        default=False,
        description=(
            "When true, route the call through the MiniMax async T2A v2 "
            "path. Use only for texts that exceed the "
            "10k char sync limit or when batch latency is acceptable; "
            "async polling adds ~1-3s on top of synthesis."
        ),
    )
    model: str = Field(
        default="speech-2.8-hd",
        description=(
            "MiniMax model name (e.g. 'speech-2.8-hd', 'speech-2.8-turbo'). "
            "Used by the MiniMax synthesis request."
        ),
    )


class SynthesizeResponse(BaseModel):
    """Single-shot synthesis result (used when ``streaming=false``)."""

    voice_id: str
    sample_rate: int
    channels: int = 1
    pcm16_base64: str = Field(..., description="Raw 16-bit PCM little-endian mono samples")
    duration_sec: float
    format: Literal["pcm16"] = "pcm16"


def encode_pcm16(pcm: bytes) -> str:
    """Helper: return a base64 string for raw pcm16 bytes."""
    return base64.b64encode(pcm).decode("ascii")
