# SPDX-File-Identifier: Apache-2.0

"""Voice clone API package.

This service wraps the cloud MiniMax Rapid Clone + T2A v2 API and exposes
a small, OpenAI-style HTTP surface so the rest of the JoyAI-VL stack can
register user voice profiles (~10 s reference audio + transcript) and
synthesise arbitrary text as PCM16 audio.

As of 2026-07-12 the CosyVoice3 backend has been removed from this project;
see doc/voice-clone.md section 2 for the migration story.

Modules:
    main: FastAPI application exposing /v1/voices and /v1/synthesize.
    models: Pydantic request/response schemas.
    cloud_clone: MiniMax Rapid Clone + T2A v2 client.
"""

from __future__ import annotations

__all__ = ["cloud_clone", "main", "models"]
