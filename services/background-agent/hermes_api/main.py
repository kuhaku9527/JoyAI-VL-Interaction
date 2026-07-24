"""StreamingHarness background-agent shim that fronts the NousResearch hermes-agent gateway.

This module mirrors the HTTP contract previously implemented by ``codex_api/main.py`` so
the webui can keep talking to ``POST /v1/solve`` unchanged. Internally we translate the
incoming request into an OpenAI-compatible chat completion call to a local
hermes-agent HTTP gateway (default ``http://127.0.0.1:8642/v1``).

The contract preserved here (field names, types, status enum) MUST stay in lock-step
with ``codex_api/main.py`` and the webui client in
``services/webui/src/joy_interaction_webui/background_model.py``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
import time
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment configuration (kept CODEX_API_* names to remain drop-in compatible
# with the webui, which already discovers the service via BACKGROUND_AGENT_API_URL
# and only reads CODEX_API_* knobs as legacy fallbacks).
# ---------------------------------------------------------------------------
DEFAULT_HOST = os.environ.get("CODEX_API_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CODEX_API_PORT", "8079"))
DEFAULT_MAX_SUBAGENTS = int(os.environ.get("CODEX_API_MAX_SUBAGENTS", "6"))
DEFAULT_MAX_CONCURRENT_RUNS = int(os.environ.get("CODEX_API_MAX_CONCURRENT_RUNS", "2"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("CODEX_API_TIMEOUT_SECONDS", "600"))
DEFAULT_MAX_FRAMES = int(os.environ.get("CODEX_API_MAX_FRAMES", "50"))

# hermes-agent gateway (NousResearch/hermes-agent v0.17.0+).
HERMES_API_URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642/v1").rstrip("/")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY") or os.environ.get("API_SERVER_KEY", "")
HERMES_MODEL = os.environ.get("HERMES_MODEL", "hermes-agent")
HERMES_GATEWAY_HOST = os.environ.get("HERMES_GATEWAY_HOST", "127.0.0.1")
HERMES_GATEWAY_PORT = int(os.environ.get("HERMES_GATEWAY_PORT", "8642"))
HERMES_GATEWAY_URL = f"http://{HERMES_GATEWAY_HOST}:{HERMES_GATEWAY_PORT}"

# memory-store (Local Wiki source). Recall-only; any failure is non-blocking so
# the hermes gateway simply falls back to live web search.
MEMORY_STORE_URL = os.environ.get("MEMORY_STORE_URL", "http://127.0.0.1:8996").rstrip("/")

# Concurrency guard. We do not want the shim to drown the hermes-agent gateway.
_run_semaphore = asyncio.Semaphore(max(1, DEFAULT_MAX_CONCURRENT_RUNS))


# ---------------------------------------------------------------------------
# Request / response models. Field names match the original codex_api shim and
# the webui dict accessors verbatim. Do not rename without also updating:
#   - services/background-agent/codex_api/main.py
#   - services/webui/src/joy_interaction_webui/background_model.py
# ---------------------------------------------------------------------------
class FrameInput(BaseModel):
    image_url: str = Field(..., description="JPEG data URL")
    timestamp: float | None = None
    timestamp_kind: str | None = None
    pts: int | None = None


class SolveRequest(BaseModel):
    session_id: str
    task_id: str
    question: str
    foreground_text: str = ""
    frames: list[FrameInput] = Field(default_factory=list)
    max_subagents: int | None = None
    timeout_seconds: float | None = None


class SolveResponse(BaseModel):
    status: Literal["completed", "failed", "timeout"]
    text: str
    thread_id: str | None = None
    usage: dict[str, Any] | None = None
    duration_ms: float
    events_digest: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


app = FastAPI(title="StreamingHarness Hermes API", version="0.1.0")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, Any]:
    """Probe hermes-agent gateway. Keep the ``codex_api`` key for webui compatibility."""
    gateway_status = 0
    gateway_model = ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{HERMES_GATEWAY_URL}/health")
            gateway_status = response.status_code
            if response.headers.get("content-type", "").startswith("application/json"):
                payload = response.json()
                if isinstance(payload, dict):
                    gateway_model = str(
                        payload.get("model")
                        or payload.get("default_model")
                        or payload.get("agent")
                        or ""
                    )
    except Exception:
        gateway_status = 0

    return {
        "codex_api": "ok",  # legacy field name; webui only checks HTTP 200
        "hermes_gateway": gateway_status,
        "model": gateway_model or HERMES_MODEL,
        "api_url": HERMES_API_URL,
    }


@app.post("/v1/solve")
async def solve(request: SolveRequest) -> SolveResponse:
    """Background solve entry point. Preserves the legacy codex_api contract."""
    max_subagents = _bounded_int(
        request.max_subagents, default=DEFAULT_MAX_SUBAGENTS, minimum=1, maximum=64
    )
    timeout_seconds = _bounded_float(
        request.timeout_seconds,
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=5.0,
        maximum=24 * 60 * 60,
    )
    frames = _limit_frames(request.frames)

    local_wiki = await _enrich_with_memory(request.question)
    prompt = _build_prompt(request, max_subagents, local_wiki=local_wiki)
    user_content = _frames_to_content(prompt, frames)

    body = {
        "model": HERMES_MODEL,
        "stream": False,
        "messages": [{"role": "user", "content": user_content}],
    }

    headers = {
        "Content-Type": "application/json",
        "X-Hermes-Session-Id": request.session_id,
        "X-Background-Task-Id": request.task_id,
    }
    if HERMES_API_KEY:
        headers["Authorization"] = f"Bearer {HERMES_API_KEY}"

    started = time.perf_counter()
    async with _run_semaphore:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds + 30.0, connect=10.0)
            ) as client:
                response = await client.post(
                    f"{HERMES_API_URL}/chat/completions",
                    json=body,
                    headers=headers,
                )
        except httpx.TimeoutException as err:
            duration_ms = (time.perf_counter() - started) * 1000.0
            return SolveResponse(
                status="timeout",
                text="",
                thread_id=request.session_id,
                usage=None,
                duration_ms=duration_ms,
                events_digest={"error": f"hermes gateway timeout: {err}"},
                error=str(err),
            )
        except httpx.HTTPError as err:
            duration_ms = (time.perf_counter() - started) * 1000.0
            return SolveResponse(
                status="failed",
                text="",
                thread_id=request.session_id,
                usage=None,
                duration_ms=duration_ms,
                events_digest={"error": f"hermes gateway transport error: {err}"},
                error=str(err),
            )

    duration_ms = (time.perf_counter() - started) * 1000.0
    return _build_solve_response(response, request, duration_ms)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_prompt(request: SolveRequest, max_subagents: int, *, local_wiki: str = "") -> str:
    """Build the user-facing system-of-instructions block.

    Kept byte-for-byte equivalent to the original codex_api prompt so the
    downstream hermes-agent produces the same shape of answer (Chinese prose,
    ``<summary>`` card, optional ``bar_chart`` JSON, optional HTML document).
    """
    frame_lines = []
    for index, frame in enumerate(request.frames, start=1):
        timestamp = frame.timestamp if frame.timestamp is not None else "unknown"
        timestamp_kind = frame.timestamp_kind or "unknown"
        pts = frame.pts if frame.pts is not None else "unknown"
        frame_lines.append(
            f"- Frame {index}: timestamp={timestamp} kind={timestamp_kind} pts={pts}"
        )
    frame_context = "\n".join(frame_lines) if frame_lines else "- No recent frames were provided."
    prompt = f"""You are the background solver for a real-time video assistant.

Use Chinese by default for user-facing prose unless the user explicitly asks otherwise.
Use live web search when current or external information is useful.
You may spawn at most {max_subagents} parallel subagents. Do not exceed this limit.
If you spawn subagents, wait for all of them and consolidate their useful results.
The answer is isolated background UI output. Do not write files unless the user explicitly requested an artifact and it is necessary for analysis; return the final content in the response.
For any visual deliverable request, including image generation, posters, illustrations, avatars, cartoon characters, or PPT/slides, default to imagegen / gpt-image-2 to generate real PNG/JPG assets; do not substitute Python/SVG/HTML/CSS drawings unless the user explicitly asks for code or vector output.
If you create a user-visible file artifact, save it under the current working directory. In the final response, include the existing artifact file path as plain text, not in backticks or a code block, and do not return a directory path.
At the very end of your final response, include a concise summary wrapped exactly as <summary>...</summary>. The text inside must be 1-2 Chinese sentences for the frontend summary card.
If a chart is useful, include a fenced JSON block like {{"type":"bar_chart","title":"...","labels":[],"values":[]}}.
If asked to recreate a visible webpage, return a complete static HTML document in a fenced html code block.

Session: {request.session_id}
Task: {request.task_id}
Foreground note: {request.foreground_text}
Delegated question:
{request.question}

Recent frame metadata:
{frame_context}
"""
    if local_wiki:
        prompt += f"\n[Local Wiki]\n{local_wiki}\n(优先用本地资料, 无关时才用 web search)\n"
    return prompt


async def _enrich_with_memory(question: str) -> str:
    """Recall local wiki blocks from memory-store before delegating to web search.

    Fails open: any error, empty result, or missing service returns "" so the
    hermes gateway simply falls back to live web search. Never blocks the solve.
    """
    if not question:
        return ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{MEMORY_STORE_URL}/v1/blocks/recall",
                json={"query": question, "top_k": 5, "min_score": 0.4},
            )
            if resp.status_code >= 400:
                return ""
            payload = resp.json()
            blocks = payload.get("blocks") if isinstance(payload, dict) else None
            if not blocks:
                return ""
            lines = [
                f"- {b['content']}" for b in blocks if isinstance(b, dict) and b.get("content")
            ]
            return "\n".join(lines)
    except Exception as exc:  # fail open: any recall error falls back to web search
        logger.warning("local wiki recall failed, falling back to web search: %s", exc)
        return ""


def _frames_to_content(prompt: str, frames: list[FrameInput]) -> list[dict[str, Any]]:
    """Convert frames into OpenAI multimodal content parts. Decodes base64 lazily so
    the gateway can stream them straight into its image_url slots.
    """
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for index, frame in enumerate(frames, start=1):
        image_url = _normalize_frame_data_url(frame.image_url, index)
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": image_url, "detail": "auto"},
            }
        )
    return parts


def _normalize_frame_data_url(value: str, index: int) -> str:
    """Pass through jpeg/png data URLs, fall back to wrapping raw base64 for other inputs."""
    if value.startswith("data:image/"):
        return value
    # Accept either pure base64 (webui currently sends jpeg data URLs) or http(s) URLs.
    if value.startswith("http://") or value.startswith("https://"):
        return value
    try:
        base64.b64decode(value, validate=True)
    except Exception as err:
        raise HTTPException(
            status_code=400,
            detail=f"frame {index} image_url is not a data URL or base64 string: {err}",
        ) from err
    return f"data:image/jpeg;base64,{value}"


def _limit_frames(frames: list[FrameInput]) -> list[FrameInput]:
    if DEFAULT_MAX_FRAMES <= 0:
        return []
    return list(frames or [])[-DEFAULT_MAX_FRAMES:]


def _bounded_int(value: int | None, *, default: int, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return min(max(resolved, minimum), maximum)


def _bounded_float(value: float | None, *, default: float, minimum: float, maximum: float) -> float:
    try:
        resolved = float(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return min(max(resolved, minimum), maximum)


def _build_solve_response(
    upstream: httpx.Response,
    request: SolveRequest,
    duration_ms: float,
) -> SolveResponse:
    """Map an OpenAI-compatible hermes response into the legacy SolveResponse shape."""
    status = "completed"
    text = ""
    usage: dict[str, Any] | None = None
    error: str | None = None
    events_digest: dict[str, Any] = {"status_code": upstream.status_code}
    thread_id = request.session_id

    if upstream.status_code >= 400:
        status = "failed"
        error = _extract_error_message(upstream)
        events_digest["error"] = error
        return SolveResponse(
            status=status,
            text="",
            thread_id=thread_id,
            usage=None,
            duration_ms=duration_ms,
            events_digest=events_digest,
            error=error,
        )

    try:
        payload = upstream.json()
    except ValueError as err:
        return SolveResponse(
            status="failed",
            text="",
            thread_id=thread_id,
            usage=None,
            duration_ms=duration_ms,
            events_digest={**events_digest, "error": f"non-json upstream: {err}"},
            error=f"hermes gateway returned non-JSON body: {err}",
        )

    if not isinstance(payload, dict):
        return SolveResponse(
            status="failed",
            text="",
            thread_id=thread_id,
            usage=None,
            duration_ms=duration_ms,
            events_digest={**events_digest, "error": "upstream payload is not a JSON object"},
            error="hermes gateway returned an unexpected payload shape",
        )

    text = _extract_chat_completion_text(payload)
    if not text:
        status = "failed"
        error = "hermes gateway returned an empty completion"
        events_digest["error"] = error

    raw_usage = payload.get("usage")
    if isinstance(raw_usage, dict):
        usage = raw_usage

    model_name = payload.get("model")
    if isinstance(model_name, str) and model_name:
        events_digest["model"] = model_name

    finish_reason = _extract_finish_reason(payload)
    if finish_reason:
        events_digest["finish_reason"] = finish_reason

    # Surface delegated child work if the gateway reported it.
    children = payload.get("children") or payload.get("delegations")
    if isinstance(children, list) and children:
        events_digest["children"] = len(children)

    return SolveResponse(
        status=status,
        text=text,
        thread_id=thread_id,
        usage=usage,
        duration_ms=duration_ms,
        events_digest=events_digest,
        error=error,
    )


def _extract_chat_completion_text(payload: dict[str, Any]) -> str:
    """Robustly pull the assistant text from an OpenAI chat completion payload."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
            return "\n".join(chunks).strip()
    text = first.get("text")
    if isinstance(text, str):
        return text
    return ""


def _extract_finish_reason(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    reason = first.get("finish_reason")
    return str(reason) if reason is not None else ""


def _extract_error_message(upstream: httpx.Response) -> str:
    try:
        payload = upstream.json()
    except ValueError:
        return f"hermes gateway HTTP {upstream.status_code}: {upstream.text[:500]}"
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            message = err.get("message")
            if isinstance(message, str):
                return f"hermes gateway HTTP {upstream.status_code}: {message}"
        if isinstance(err, str):
            return f"hermes gateway HTTP {upstream.status_code}: {err}"
    return f"hermes gateway HTTP {upstream.status_code}: {upstream.text[:500]}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import uvicorn

    uvicorn.run(
        "hermes_api.main:app",
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        reload=False,
    )


if __name__ == "__main__":
    sys.exit(main())
