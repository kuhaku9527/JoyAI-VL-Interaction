"""Configuration loading and environment-variable parsing for the webinfer adapter."""

from __future__ import annotations

import logging
import os
from typing import Any

LOGGER = logging.getLogger("streaming_infer_adapter")


def reset_chunk_state() -> dict[str, Any]:
    return {
        "messages": [],
        "response_records": [],
        "image_paths": [],
        "frame_time_ranges": [],
        "summarizer_frame_cache": [],
        "frame_count": 0,
        "turn_count": 0,
        "api_msg_cache": [],
    }


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return float(value)


def _split_paths(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    normalized = value.replace(",", os.pathsep)
    return tuple(item.strip() for item in normalized.split(os.pathsep) if item.strip())
