"""Model output normalization and response payload formatting."""

from __future__ import annotations

import copy
import logging
import re
import time
import uuid
from typing import Any, Optional

from aiohttp import web
from time_ranges import _parse_start_second

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

def normalize_model_output(text: str) -> str:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return "</silence>"

    marker_positions = []
    for marker in ("</response>", "</silence>"):
        idx = raw.find(marker)
        if idx != -1:
            marker_positions.append((idx, marker))

    if marker_positions:
        _, marker = min(marker_positions, key=lambda item: item[0])
        if marker == "</silence>":
            return "</silence>"
        response_text = raw.split(marker, 1)[1].strip()
        if not response_text:
            return "</response>"
        first_line = " ".join(response_text.splitlines()[0].split())
        return f"</response> {first_line}" if first_line else "</response>"

    first_line = " ".join(raw.splitlines()[0].split())
    return f"</response> {first_line}" if first_line else "</silence>"


def extract_response_payload(text: str) -> Optional[str]:
    normalized = normalize_model_output(text)
    if not normalized.startswith("</response>"):
        return None
    payload = normalized[len("</response>"):].strip()
    return payload or None


def parse_model_decision(raw_text: str) -> tuple[str, str, Optional[str]]:
    """Single decision-parsing entry point (unified by #2).

    Returns ``(decision, clean_text, delegation_question)``:

      * ``decision`` ∈ {"silence", "response", "delegation"}, never ``None``;
      * ``clean_text``: body text with decision tokens stripped
        ("" for silence/delegation);
      * ``delegation_question``: the delegated question when ``decision``
        is "delegation", else ``None``.

    Recognizes the ``</response>`` / ``</silence>`` / ``</delegation>``
    tokens and takes the EARLIEST occurrence. A bare reply with no token
    is treated as "response" (aligned with :func:`normalize_model_output`).
    """
    text = (raw_text or "").strip()
    if not text:
        return "silence", "", None
    earliest: Optional[tuple[int, str]] = None
    for marker in ("</response>", "</silence>", "</delegation>"):
        idx = text.find(marker)
        if idx >= 0 and (earliest is None or idx < earliest[0]):
            earliest = (idx, marker)
    if earliest is None:
        return "response", text, None
    _, marker = earliest
    tail = text[earliest[0] + len(marker):].strip()
    if marker == "</silence>":
        return "silence", "", None
    if marker == "</delegation>":
        return "delegation", "", tail or None
    # </response>
    return "response", tail, None


# Backwards-compatible alias: keeps the existing
# ``from response_format import _parse_decision_tokens`` import working and
# routes the text path through the single unified parser.
_parse_decision_tokens = parse_model_decision


def build_model_input_record(
    chunk_index: int,
    messages: list[dict[str, Any]],
    frame_count: int,
    model: Optional[str] = None,
    generation_kwargs: Optional[dict[str, Any]] = None,
    inference_skipped: bool = False,
    skip_reason: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
    frame_time_ranges: Optional[list[str]] = None,
    prefix_content: Optional[str] = None,
    prompt: Optional[str] = None,
) -> dict[str, Any]:
    if inference_skipped:
        return {
            "http_payload_skipped": True,
            "inference_skipped": True,
            "skip_reason": skip_reason,
            "would_be_messages": list(messages),
        }

    del chunk_index, frame_count, image_paths, frame_time_ranges, prefix_content, prompt
    record = {
        "model": model,
        "messages": list(messages),
    }
    if generation_kwargs:
        record.update(copy.deepcopy(generation_kwargs))
    return record


def archive_chunk_response_records(
    current_chunk: dict[str, Any],
    memory_state: dict[str, Any],
    current_query_text: Optional[str],
    query_start_time: Optional[str],
    chunk_index: int = 0,
    before_time_sec: float = float("inf"),
) -> None:
    if not current_chunk["response_records"] or not current_query_text:
        return

    query_start_sec = _parse_start_second(query_start_time)
    valid_records = [
        (time_range, payload)
        for time_range, payload in current_chunk["response_records"]
        if query_start_sec <= _parse_start_second(time_range) < before_time_sec
    ]
    if not valid_records:
        return

    existing = None
    for entry in memory_state["qa_history"]:
        if (
            entry["query"] == current_query_text
            and entry.get("archived_in_chunk") == chunk_index
            and entry.get("query_time") == query_start_time
        ):
            existing = entry
            break
    if existing:
        existing["responses"].extend(valid_records)
        existing["archived_in_chunk"] = chunk_index
    else:
        memory_state["qa_history"].append(
            {
                "query_time": query_start_time,
                "query": current_query_text,
                "responses": list(valid_records),
                "archived_in_chunk": chunk_index,
            }
        )


def _chat_completion_response(
    model: str,
    content: str,
    usage: Optional[dict[str, Any]],
    raw_model: str,
    raw_text: str,
    *,
    decision: Optional[str] = None,
    delegation_question: Optional[str] = None,
    memory_chars: int = 0,
    qa_history_len: int = 0,
    prompt_chars: int = 0,
    trimmed_turns: int = 0,
) -> dict[str, Any]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    harness: dict[str, Any] = {
        "main_model": raw_model,
        "raw_content": raw_text,
    }
    if decision is not None:
        harness["decision"] = decision
    # delegation_question is always present (None when not delegating)
    # so callers see a stable field shape across all decisions.
    harness["delegation_question"] = delegation_question
    harness["memory_chars"] = int(memory_chars)
    harness["qa_history_len"] = int(qa_history_len)
    harness["prompt_chars"] = int(prompt_chars)
    harness["trimmed_turns"] = int(trimmed_turns)
    response["streamingharness"] = harness
    return response


def _openai_error_response(message: str, status: int) -> web.Response:
    return web.json_response(
        {
            "error": {
                "message": message,
                "type": "streaming_infer_adapter_error",
                "param": None,
                "code": None,
            }
        },
        status=status,
    )


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
