"""Verify the v3.32 stack is up: 7060/8070/8099/8985 + text-only /api/llm/message regression.

Usage:
    python services/scripts/verify-services.py
    python services/scripts/verify-services.py --webui http://host:port

Probes llama-server (7060), webinfer (8070), voice-clone (8985), webui (8099),
then exercises the text-only /api/llm/message regression path. Exits 0 on
all-green, 2 on failure.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4n"
    "ICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNGRgyGT0oGCgrLyQwNDQ0NDQ0NDQ0NDQ0NDQ0"
    "NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDQ0NDL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwR"
    "VS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4i"
    "JipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6"
    "/9oADAMBAAIRAxEAPwD3+iiigAooooAKKKKAP//Z"
)


def _http(method: str, url: str, body: dict | None = None, timeout: float = 10.0):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", errors="replace")[:300]}
    except Exception as exc:
        return 0, {"error": str(exc)[:300]}


def _ok(name: str, detail: str = "") -> bool:
    print(f"[OK]   {name}")
    if detail:
        print(f"      {detail}")
    return True


def _fail(name: str, detail: str = "") -> bool:
    print(f"[FAIL] {name}")
    if detail:
        print(f"      {detail}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify JoyAI services (7060/8070/8099/8985) + text regression.")
    parser.add_argument("--webui", default="http://127.0.0.1:8099")
    parser.add_argument("--webinfer", default="http://127.0.0.1:8070")
    parser.add_argument("--llama", default="http://127.0.0.1:7060")
    parser.add_argument("--voice-clone", default="http://127.0.0.1:8985")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    print("=== verify-services.py ===")
    results = []

    # 7060
    code, body = _http("GET", f"{args.llama}/v1/models", timeout=5.0)
    if code == 200 and isinstance(body, dict) and any("joyai" in str(m.get("id", "")) for m in body.get("data", []) or []):
        results.append(_ok("7060 llama-server", f"models={[m.get('id') for m in body.get('data', [])]}"))
    else:
        results.append(_fail("7060 llama-server", f"status={code} body={body}"))

    # 8070
    code, body = _http("GET", f"{args.webinfer}/v1/models", timeout=5.0)
    if code == 200 and isinstance(body, dict):
        ids = [m.get("id") for m in body.get("data", [])]
        if any(("streaming-infer-adapter" in str(x)) or ("joyai" in str(x)) for x in ids):
            results.append(_ok("8070 webinfer", f"models={ids}"))
        else:
            results.append(_fail("8070 webinfer", f"unknown models={ids}"))
    else:
        results.append(_fail("8070 webinfer", f"status={code}"))

    # 8985
    code, body = _http("GET", f"{args.voice_clone}/health", timeout=5.0)
    if code == 200 and isinstance(body, dict) and body.get("status") == "ok":
        results.append(_ok("8985 voice-clone", f"provider={body.get('tts_provider')}, voice_count={body.get('voice_count')}"))
    else:
        results.append(_fail("8985 voice-clone", f"status={code} body={body}"))

    # 8099 webui
    code, body = _http("GET", f"{args.webui}/api/tts/health", timeout=5.0)
    if code == 200:
        results.append(_ok("8099 webui"))
    else:
        results.append(_fail("8099 webui", f"status={code}"))

    # Plain text regression
    code, body = _http(
        "POST",
        f"{args.webui}/api/llm/message",
        body={"session_id": f"verify-{id({})}", "text": "BT 在吗"},
        timeout=args.timeout,
    )
    if code == 200 and isinstance(body, dict) and body.get("queued"):
        results.append(_ok("/api/llm/message (text-only regression)", f"queued=True, text_chars={body.get('text_chars')}"))
    else:
        results.append(_fail("/api/llm/message", f"status={code} body={body}"))

    fails = sum(1 for r in results if not r)
    print("")
    if fails == 0:
        print("ALL GREEN")
        return 0
    print(f"{fails} FAILURES")
    return 2


if __name__ == "__main__":
    sys.exit(main())
