"""Inbound request parsing for the webinfer adapter (text / image / time-range)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from aiohttp import web
from io_utils import _file_url_to_path
from time_ranges import _normalize_time_range_text

LOGGER = logging.getLogger("streaming_infer_adapter")


def _safe_session_id(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "default"))
    return safe.strip("._")[:120] or "default"


def _request_session_id(request: web.Request, payload: dict[str, Any]) -> str:
    return (
        request.headers.get("x-streaming-session")
        or request.headers.get("x-session-id")
        or str(payload.get("user") or "")
        or "default"
    )


def _extract_time_range_from_request(
    request: web.Request,
    payload: dict[str, Any],
) -> str | None:
    candidates = (
        request.headers.get("x-frame-time-range"),
        request.headers.get("x-streaming-time-range"),
        str(payload.get("x_frame_time_range") or ""),
        str(payload.get("frame_time_range") or ""),
    )
    for candidate in candidates:
        normalized = _normalize_time_range_text(candidate)
        if normalized:
            return normalized
    return None


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text=f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="JSON body must be an object")
    return payload


def _extract_first_image_ref(
    messages: list[dict[str, Any]],
    request: web.Request,
    payload: dict[str, Any],
) -> dict[str, str] | None:
    local_path = _extract_local_image_path_from_request(request, payload)
    if local_path:
        return {"kind": "path", "value": local_path}

    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "image_url":
                continue
            image_url = item.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if isinstance(url, str) and url:
                file_path = _file_url_to_path(url)
                if file_path:
                    return {"kind": "path", "value": file_path}
                return {"kind": "data_url", "value": url}
    return None


def _extract_all_image_refs(
    messages: list[dict[str, Any]],
    request: web.Request,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    """Extract all image references from the request (supports batch frames)."""
    refs: list[dict[str, str]] = []

    local_path = _extract_local_image_path_from_request(request, payload)
    if local_path:
        refs.append({"kind": "path", "value": local_path})

    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "image_url":
                continue
            image_url = item.get("image_url")
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if isinstance(url, str) and url:
                file_path = _file_url_to_path(url)
                if file_path:
                    refs.append({"kind": "path", "value": file_path})
                else:
                    refs.append({"kind": "data_url", "value": url})
        if refs:
            break
    return refs


def _extract_time_ranges_from_request(
    request: web.Request,
    payload: dict[str, Any],
) -> list[str]:
    """Extract multiple time ranges from request (for batch frames)."""
    ranges = payload.get("frame_time_ranges")
    if isinstance(ranges, list) and ranges:
        parsed: list[str] = []
        for r in ranges:
            normalized = _normalize_time_range_text(r)
            if normalized:
                parsed.append(normalized)
        if parsed:
            return parsed

    single = _extract_time_range_from_request(request, payload)
    return [single] if single else []


def _extract_local_image_path_from_request(
    request: web.Request,
    payload: dict[str, Any],
) -> str | None:
    candidates = (
        request.headers.get("x-local-image-path"),
        request.headers.get("x-frame-image-path"),
        str(payload.get("x_local_image_path") or ""),
        str(payload.get("local_image_path") or ""),
        str(payload.get("frame_image_path") or ""),
    )
    for candidate in candidates:
        candidate = (candidate or "").strip()
        if candidate:
            return candidate
    return None


def _extract_user_prompt_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_parts = [
                str(item.get("text", "")).strip()
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "text"
                and str(item.get("text", "")).strip()
            ]
            return "\n".join(text_parts).strip()
    return ""
