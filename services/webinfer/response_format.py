"""Model output normalization and response payload formatting."""

from __future__ import annotations

import copy
import logging
import re
import time
import uuid
from typing import Any

from aiohttp import web
from time_ranges import _parse_start_second

LOGGER = logging.getLogger("streaming_infer_adapter")


def normalize_model_output(text: str) -> str:
    """Normalize raw model text into a clean decision token plus response body."""
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


def extract_response_payload(text: str) -> str | None:
    """Extract the response payload from normalized output, or ``None``."""
    normalized = normalize_model_output(text)
    if not normalized.startswith("</response>"):
        return None
    payload = normalized[len("</response>") :].strip()
    return payload or None


def parse_model_decision(raw_text: str) -> tuple[str, str, str | None]:
    """Single decision-parsing entry point (unified by #2).

    Returns ``(decision, clean_text, delegation_question)``:

      * ``decision`` ∈ {"silence", "response", "delegation"}, never ``None``;
      * ``clean_text``: body text with decision tokens stripped
        ("" for silence/delegation);
      * ``delegation_question``: the delegated question when ``decision``
        is "delegation", else ``None``.

    The runtime system prompt teaches the **delegation** format as
    ``</response> <brief note> </delegation> <the question>`` -- i.e. the
    ``</response>`` token precedes the delegation tag. A naive earliest-marker
    scan would therefore misclassify a real delegation as "response". To stay
    robust regardless of the 8B model's exact token order, a delegation tag
    (``<delegation>`` or ``</delegation>``) present ANYWHERE in the output
    takes priority; only when no delegation tag is present do we fall back to
    the earliest of ``</response>`` / ``</silence>``.
    """
    text = (raw_text or "").strip()
    if not text:
        return "silence", "", None

    # Delegation priority: detect either delegation tag anywhere in the output.
    delegation_idx: int | None = None
    delegation_tag: str | None = None
    for tag in ("</delegation>", "<delegation>"):
        idx = text.find(tag)
        if idx >= 0 and (delegation_idx is None or idx < delegation_idx):
            delegation_idx = idx
            delegation_tag = tag
    if delegation_idx is not None:
        tail = text[delegation_idx + len(delegation_tag) :].strip()
        return "delegation", "", tail or None

    # No delegation tag: fall back to the earliest of response / silence.
    earliest: tuple[int, str] | None = None
    for marker in ("</response>", "</silence>"):
        idx = text.find(marker)
        if idx >= 0 and (earliest is None or idx < earliest[0]):
            earliest = (idx, marker)
    if earliest is None:
        return "response", text, None
    _, marker = earliest
    tail = text[earliest[0] + len(marker) :].strip()
    if marker == "</silence>":
        return "silence", "", None
    # </response>
    return "response", tail, None


# All decision-token variants (case-insensitive). The opening ``<...>`` and
# closing ``</...>`` forms of silence / response / delegation are all control
# signals that must never reach the end-user ``content`` field. ``<the
# question>``-style placeholder text in the system prompt is NOT matched
# because only these three literal tag names are whitelisted.
_DECISION_TOKEN_RE = re.compile(r"\s*</?\s*(?:silence|response|delegation)\s*>\s*", re.IGNORECASE)


def strip_decision_tokens(text: str) -> str:
    """Strip every decision-token variant from model output text.

    The runtime system prompt teaches the model to bracket its reply with
    ``</silence>`` / ``</response>`` / ``</delegation>`` (and the opening
    ``<...>`` forms). Those tokens are control signals consumed by the
    ``streamingharness.decision`` field and must never reach the end-user
    ``content`` (issue #44). This removes all six variants (case-insensitive,
    with any surrounding whitespace) and collapses the result, so
    ``"</response> hi"`` -> ``"hi"`` and ``"</silence>"`` -> ``""``.

    The ``decision`` / ``delegation_question`` harness fields are derived
    separately by :func:`parse_model_decision` and are NOT affected by this
    strip -- callers must keep passing the raw text to that parser.
    """
    if not text:
        return ""
    cleaned = _DECISION_TOKEN_RE.sub(" ", text)
    return " ".join(cleaned.split())


# Backwards-compatible alias: keeps the existing
# ``from response_format import _parse_decision_tokens`` import working and
# routes the text path through the single unified parser.
_parse_decision_tokens = parse_model_decision


def build_model_input_record(
    chunk_index: int,
    messages: list[dict[str, Any]],
    frame_count: int,
    model: str | None = None,
    generation_kwargs: dict[str, Any] | None = None,
    inference_skipped: bool = False,
    skip_reason: str | None = None,
    image_paths: list[str] | None = None,
    frame_time_ranges: list[str] | None = None,
    prefix_content: str | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Build the per-chunk model-input record for persistence/debug output."""
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
    current_query_text: str | None,
    query_start_time: str | None,
    chunk_index: int = 0,
    before_time_sec: float = float("inf"),
) -> None:
    """Archive valid response records into the session QA history."""
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
    usage: dict[str, Any] | None,
    raw_model: str,
    raw_text: str,
    *,
    decision: str | None = None,
    delegation_question: str | None = None,
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
        "usage": usage
        or {
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
