"""Time-range parsing and normalization helpers for video segments."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from prompt_constants import TIME_RANGE_RE, TIME_RANGE_VALUE_RE, TIME_VALUE_RE

LOGGER = logging.getLogger("streaming_infer_adapter")


def _parse_start_second(time_range: str | None) -> float:
    if not time_range:
        return -1.0
    try:
        start = re.split(r"\s*(?:-|~)\s*", str(time_range), maxsplit=1)[0].strip()
        start = re.sub(r"\s*seconds?$", "", start).strip()
        if start.endswith("s"):
            start = start[:-1]
        return float(start)
    except (ValueError, IndexError):
        return -1.0


def _format_seconds_words(value: float) -> str:
    rounded = math.floor(value * 10 + 0.5) / 10
    return f"{rounded:.1f} seconds"


def _parse_time_value_seconds(text: str) -> float | None:
    match = TIME_VALUE_RE.fullmatch(str(text or "").strip())
    if not match:
        return None
    return float(match.group("value"))


def _normalize_time_range_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    match = TIME_RANGE_RE.search(text)
    if match:
        text = match.group("range").strip()

    match = TIME_VALUE_RE.fullmatch(text)
    if match:
        return _format_seconds_words(float(match.group("value")))

    match = TIME_RANGE_VALUE_RE.fullmatch(text)
    if match:
        range_text = match.group("range")
        separator = " ~ " if "~" in range_text else "-"
        parts = re.split(r"\s*(?:~|-)\s*", range_text, maxsplit=1)
        if len(parts) == 2:
            start = _parse_time_value_seconds(parts[0])
            end = _parse_time_value_seconds(parts[1])
            if start is not None and end is not None:
                return f"{_format_seconds_words(start)}{separator}{_format_seconds_words(end)}"
        return range_text

    return None


def _format_time_span(time_ranges: list[str]) -> str | None:
    ranges = [str(tr).strip() for tr in time_ranges if str(tr or "").strip()]
    if not ranges:
        return None
    if len(ranges) == 1:
        return ranges[0]
    return f"{ranges[0]} ~ {ranges[-1]}"


def _format_batch_time_marker(time_ranges: list[str]) -> str | None:
    ranges = [str(tr).strip() for tr in time_ranges if str(tr or "").strip()]
    return ranges[0] if ranges else None


def _format_turn_time_range(time_ranges: list[str]) -> str:
    ranges = [str(tr).strip() for tr in time_ranges if str(tr or "").strip()]
    if not ranges:
        return ""
    if all(time_range == ranges[0] for time_range in ranges):
        return ranges[0]
    return " ~ ".join(ranges)


def _extract_time_range_from_message(message: dict[str, Any]) -> str | None:
    content = message.get("content", "")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                match = TIME_RANGE_RE.search(text)
                if match:
                    return match.group("range")
    elif isinstance(content, str):
        match = TIME_RANGE_RE.search(content)
        if match:
            return match.group("range")
    return None


def _compute_chunk_frame_range(current_chunk: dict[str, Any]) -> str:
    frame_time_ranges = [
        str(time_range).strip()
        for time_range in current_chunk.get("frame_time_ranges", [])
        if str(time_range or "").strip()
    ]
    if frame_time_ranges:
        return _format_time_span(frame_time_ranges) or "unknown"

    user_messages = [
        message for message in current_chunk.get("messages", []) if message.get("role") == "user"
    ]
    if not user_messages:
        return "unknown"

    first_range = _extract_time_range_from_message(user_messages[0])
    last_range = _extract_time_range_from_message(user_messages[-1])
    if first_range and last_range:
        return f"{first_range} ~ {last_range}"
    return first_range or last_range or "unknown"


def _get_response_frame_indices(messages: list[dict[str, Any]]) -> list[int]:
    indices: list[int] = []
    frame_idx = -1
    for message in messages:
        if message.get("role") == "user":
            content = message.get("content")
            has_image = isinstance(content, list) and any(
                isinstance(item, dict) and item.get("type") == "image" for item in content
            )
            if has_image:
                frame_idx += 1
        elif message.get("role") == "assistant":
            if "</response>" in str(message.get("content", "")) and frame_idx >= 0:
                indices.append(frame_idx)
    return indices


def _format_seconds(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return f"{round(value)}s"
    return f"{value:.3f}".rstrip("0").rstrip(".") + "s"


def _extract_time_range_from_text(text: str) -> str | None:
    return _normalize_time_range_text(text)


def _strip_time_range_from_text(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if TIME_RANGE_RE.fullmatch(stripped):
            continue
        lines.append(line)
    return "\n".join(lines).strip()
