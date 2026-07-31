#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime probe for VLM (llama-server) — writes /props values to a stable file.

Why this exists:
  The original drift_gate runtime check parsed `logs/llama-main.log` for
  `n_ctx_slot = <N>`. The launcher never actually wrote that log (it
  displayed the path in the banner but set `RedirectStandardOutput = $false`),
  so the check was structurally impossible to pass on Windows.

  This probe runs *after* llama is up, queries `/props` directly (the
  same endpoint that the runtime check would grep for n_ctx), and writes
  the relevant fields to `logs/vlm-runtime-props.json`. The contract
  then checks that file for the expected n_ctx value.

  The probe is intentionally small + stdlib only (no extra deps) so it
  can run in the launcher pre-Start phase and also from CI / smoke
  tests without a venv.

Usage:
  python scripts/vlm_runtime_probe.py --base-url http://127.0.0.1:7060 \
      --out logs/vlm-runtime-props.json
  python scripts/vlm_runtime_probe.py --wait 60  # wait up to 60s for /health
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def http_get_json(url: str, timeout: float = 3.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def wait_for_health(base_url: str, timeout_s: float) -> bool:
    """Block until /health returns 200 or timeout. Returns True if healthy."""
    deadline = time.monotonic() + timeout_s
    url = base_url.rstrip("/") + "/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        time.sleep(1.0)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="VLM runtime probe: dump /props to JSON")
    ap.add_argument("--base-url", default="http://127.0.0.1:7060", help="llama-server base URL")
    ap.add_argument("--out", required=True, help="output JSON path (overwritten)")
    ap.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="seconds to wait for /health before probing (0 = no wait)",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="per-request timeout in seconds",
    )
    args = ap.parse_args()

    if args.wait > 0 and not wait_for_health(args.base_url, args.wait):
        print(f"[FAIL] /health not ready after {args.wait}s", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    snapshot: dict = {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base,
    }

    # /health (cheap liveness)
    try:
        h = http_get_json(base + "/health", timeout=args.timeout)
        snapshot["health"] = h
    except Exception as exc:
        snapshot["health_error"] = repr(exc)

    # /v1/models (model list — also implicitly proves the server is up)
    try:
        m = http_get_json(base + "/v1/models", timeout=args.timeout)
        snapshot["models"] = m
    except Exception as exc:
        snapshot["models_error"] = repr(exc)

    # /props — the actual contract surface (n_ctx lives here).
    try:
        p = http_get_json(base + "/props", timeout=args.timeout)
        snapshot["props"] = p
        gs = p.get("default_generation_settings", {}) or {}
        snapshot["n_ctx"] = gs.get("n_ctx")
    except Exception as exc:
        snapshot["props_error"] = repr(exc)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    n_ctx = snapshot.get("n_ctx")
    print(f"wrote {out}  n_ctx={n_ctx}")
    return 0 if n_ctx is not None else 3


if __name__ == "__main__":
    raise SystemExit(main())
