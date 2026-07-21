"""Configuration loading and environment-variable parsing for the webinfer adapter."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

LOGGER = logging.getLogger("streaming_infer_adapter")
USER_QUERY_HEADER_EN = "[User Query (IMPORTANT — follow this instruction)]"
USER_QUERY_HEADER_ZH = "[用户问题（重要——请遵循此指令）]"
VIDEO_HISTORY_HEADER_EN = (
    "[Video History]\n"
    "The following are summaries of earlier video segments you can no longer see. "
    "Use them as background context, but always prioritize the current visual frames "
    "and the User Query below when making decisions.\n"
    "IMPORTANT: These summaries are written by an external system in a descriptive style. "
    "Do NOT imitate their writing style in your responses.\n"
)
VIDEO_HISTORY_HEADER_ZH = (
    "[Video History]\n"
    "以下是你已无法看到的早期视频片段的文字摘要。"
    "将其作为背景上下文使用，但在做决策时始终优先参考当前视觉帧及下方的用户问题。\n"
    "重要：这些摘要由外部系统以描述性风格撰写。不要在你的回复中模仿其写作风格。\n"
)
QA_HISTORY_HEADER_EN = (
    "[Q&A History]\n"
    "The following are previous queries and the system's responses.\n\n"
)
QA_HISTORY_HEADER_ZH = (
    "[Q&A History]\n"
    "以下是之前的用户提问及系统的回复。\n\n"
)
QA_QUERY_LABEL_EN = "Query"
QA_QUERY_LABEL_ZH = "提问"
QA_RESPONSE_LABEL_EN = "Response"
QA_RESPONSE_LABEL_ZH = "回复"
_CHARS_PER_TOKEN_BUDGET: float = 3.0
_CTX_SAFETY_FACTOR: float = 0.85
_PROMPT_GUARD_MIN_RECENT: int = 2
DEFAULT_SAVE_ROOT = "result"
TIME_RANGE_RE = re.compile(
    r"<(?P<range>\d+(?:\.\d+)?\s*(?:seconds?|s)(?:\s*(?:~|-)\s*\d+(?:\.\d+)?\s*(?:seconds?|s))?)>"
)
TIME_RANGE_VALUE_RE = re.compile(
    r"^(?P<range>\d+(?:\.\d+)?\s*(?:seconds?|s)\s*(?:~|-)\s*\d+(?:\.\d+)?\s*(?:seconds?|s))$"
)
TIME_VALUE_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?:\s*(?:seconds?|s))$")
DEFAULT_SYSTEM_PROMPT_EN = """You are a real-time video streaming assistant observing a continuous camera feed frame by frame. The last frame represents the current moment.
## Action Format
At every inference step you MUST choose exactly one of the following three actions:
**Stay silent** — output ONLY:
</silence>
Choose this when nothing noteworthy has changed in the scene, no user query is pending, or there is nothing useful to say.
**Speak** — output the token followed by a concise reply:
</response> Your reply here.
Choose this when you observe something worth reporting or a significant state change, or when you can answer a user question based on available evidence.

**Delegate** — when a question is too hard or error-prone to answer reliably yourself, speak a brief note that you're delegating, then hand the question to the background solver:
</response> Brief note that you're delegating. </delegation> <the question>""".strip()
DEFAULT_SYSTEM_PROMPT="""You are a real-time video streaming assistant observing a continuous camera feed frame by frame. The last frame represents the current moment.
## Action Format
At every inference step you MUST choose exactly one of the following three actions:
**Stay silent** — output ONLY:
</silence>
Choose this when nothing noteworthy has changed in the scene, no user query is pending, or there is nothing useful to say.
**Speak** — output the token followed by a concise reply:
</response> Your reply here.
Choose this when you observe something worth reporting or a significant state change, or when you can answer a user question based on available evidence.

**Delegate** — when a question is too hard or error-prone to answer reliably yourself, speak a brief note that you're delegating, then hand the question to the background solver:
</response> Brief note that you're delegating. <delegation> <the question>""".strip()

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
