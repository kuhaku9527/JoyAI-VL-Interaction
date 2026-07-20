"""System-prompt and message construction helpers for the webinfer adapter."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from system_prompts import (
    compose_system_prompt,
)

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

def _get_i18n(language: str = "en") -> dict[str, str]:
    if language == "en":
        return {
            "user_query_header": USER_QUERY_HEADER_EN,
            "video_history_header": VIDEO_HISTORY_HEADER_EN,
            "qa_history_header": QA_HISTORY_HEADER_EN,
            "qa_query_label": QA_QUERY_LABEL_EN,
            "qa_response_label": QA_RESPONSE_LABEL_EN,
        }
    return {
        "user_query_header": USER_QUERY_HEADER_EN,
        "video_history_header": VIDEO_HISTORY_HEADER_ZH,
        "qa_history_header": QA_HISTORY_HEADER_ZH,
        "qa_query_label": QA_QUERY_LABEL_ZH,
        "qa_response_label": QA_RESPONSE_LABEL_ZH,
    }


def _estimate_messages_chars(messages):
    # Estimate total character count of an OpenAI messages list.
    # Uses a cheap linear scan over the content field. Image content
    # parts contribute a fixed 1 KB placeholder so a multimodal request
    # is not severely under-counted (a real JPEG base64 is 100-300 KB
    # which would dominate the budget on its own).
    total = 0
    for message in messages or ():
        content = message.get('content') if isinstance(message, dict) else None
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get('type') == 'text':
                    text_value = part.get('text')
                    if isinstance(text_value, str):
                        total += len(text_value)
                elif part.get('type') in ('image', 'image_url'):
                    total += 1024
        total += 16  # role + json framing overhead
    return total


def _trim_messages_to_ctx(messages, max_total_chars, min_recent=_PROMPT_GUARD_MIN_RECENT):
    # Trim the messages list to fit within max_total_chars.
    # Always preserves the first message (the system prompt) and the last
    # min_recent user/assistant turns. Older turns are dropped from the
    # front (index 1..end-min_recent) until the budget is met.
    # Returns the (possibly trimmed) list and the number of messages removed.
    if not messages or max_total_chars <= 0:
        return list(messages or []), 0
    if _estimate_messages_chars(messages) <= max_total_chars:
        return list(messages), 0
    head = messages[:1]
    if len(messages) > 1 + min_recent:
        tail = messages[-min_recent:]
        middle = messages[1 : len(messages) - min_recent]
    else:
        tail = []
        middle = messages[1:]
    removed = 0
    while middle and (_estimate_messages_chars(head + middle + tail) > max_total_chars):
        middle.pop(0)
        removed += 1
    return head + middle + tail, removed


def _compute_prompt_guard_max_chars(ctx_tokens):
    # Compute the total character budget for the prompt guard.
    # Multiplies ctx_tokens by the chars-per-token budget and the safety
    # factor. A non-positive ctx_tokens disables the guard (returns 0).
    if not ctx_tokens or ctx_tokens <= 0:
        return 0
    return int(ctx_tokens * _CHARS_PER_TOKEN_BUDGET * _CTX_SAFETY_FACTOR)


def _build_system_prompt(
    base: str,
    character_prompts: list[str],
    language: str = "en",
) -> str:
    """Compose the final system prompt (character profile + base + tail).

    This is a thin wrapper around :func:`compose_system_prompt` so the
    same merge rule is shared between the cache-aware class method and
    any one-off callers (e.g. debug endpoints, tests).

    Parameters
    ----------
    base:
        The base (decision-token) system prompt to keep verbatim.
    character_prompts:
        Character / persona profile bodies.  Empty list disables
        character injection and the in-character tail.
    language:
        ``"zh"`` selects the Chinese in-character reminder; any other
        value falls back to English.
    """
    return compose_system_prompt(base, character_prompts, language)


def build_static_system_content(
    extra_system_messages: Optional[list[str]] = None,
    memory_state: Optional[dict[str, Any]] = None,
    mid_term_summaries: Optional[list[dict[str, Any]]] = None,
    language: str = "en",
) -> str:
    i18n = _get_i18n(language)
    sections: list[str] = []
    for message in extra_system_messages or []:
        if message and message.strip():
            sections.append(message.strip())

    history_parts: list[str] = []
    if memory_state is not None and memory_state.get("long_term_memory"):
        history_parts.append(memory_state["long_term_memory"])
    if mid_term_summaries:
        for entry in mid_term_summaries:
            history_parts.append(f"<{entry['frame_range']}>\n{entry['summary_text']}")

    if history_parts:
        sections.append(
            i18n["video_history_header"]
            + "\n\n".join(history_parts)
        )

    return "\n\n".join(sections) if sections else ""


def build_dynamic_system_content(
    current_query_text: Optional[str] = None,
    memory_state: Optional[dict[str, Any]] = None,
    include_qa_history: bool = True,
    current_chunk_index: int = 0,
    language: str = "en",
) -> str:
    i18n = _get_i18n(language)
    sections: list[str] = []

    if include_qa_history and memory_state is not None and memory_state.get("qa_history"):
        qa_entries = [
            entry for entry in memory_state["qa_history"]
            if (entry.get("archived_in_chunk") or 0) < current_chunk_index
        ]
        if qa_entries:
            qa_lines: list[str] = []
            for idx, entry in enumerate(qa_entries, 1):
                q_time = entry["query_time"] or "N/A"
                parts = [f"#{idx} [{i18n['qa_query_label']}@{q_time}] {entry['query']}"]
                for response_time, payload in entry.get("responses", []):
                    parts.append(f"[{i18n['qa_response_label']}@{response_time}] {payload}")
                qa_lines.append("\n".join(parts))
            sections.append(
                i18n["qa_history_header"]
                + "\n".join(qa_lines)
            )

    if current_query_text:
        sections.append(i18n["user_query_header"] + "\n" + current_query_text.strip())

    return "\n\n".join(sections) if sections else ""
