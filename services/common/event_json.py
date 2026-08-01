"""JSONL event emitter for ADR-0014 / spec ``log-event-schema`` v1.0.

Zero third-party dependencies — uses only the stdlib :mod:`logging` module.
Writes one JSON object per event to ``logs/events/<service>-<UTC-YYYY-MM-DD>.jsonl``.

Design contract (see ``doc/specs/log-event-schema.md``):

* **Best-effort**: a write failure MUST NEVER block the calling business path.
  Every public function swallows its own exceptions.
* **Schema** (required): ``ts`` (ISO-8601 UTC, millisecond), ``level``
  (debug/info/warn/error/critical), ``service``, ``event`` (kebab-case).
* **Optional fields**: ``session_id``, ``latency_ms``, ``status``, ``user``,
  ``extra`` (object).
* **PII red line** (decision D-061): do NOT pass raw message bodies, API keys,
  file contents, or client IP in ``extra``. Use lengths / hashes / flags only.
  The schema layer cannot magically scrub PII — callers must respect the line;
  CI adds a lint gate (see decision book).

Typical use::

    from event_json import emit_event
    emit_event("webinfer", "wiki_recall_fail", level="warn",
               session_id=state.session_id, extra={"error_type": type(exc).__name__})
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

# This file lives at <repo>/services/common/event_json.py. Walk up two levels
# to reach the repo root so the events dir is found regardless of the caller's
# current working directory.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
_EVENTS_DIR = os.path.join(_REPO_ROOT, "logs", "events")

# Normalize caller-friendly level names to logging's canonical upper-case
# names (so "warn" -> "WARNING", etc.).
_LEVEL_MAP = {
    "debug": "DEBUG",
    "info": "INFO",
    "warn": "WARNING",
    "warning": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
}

# Map logging level names back to the schema's compact vocabulary.
_LEVEL_OUT = {
    "debug": "debug",
    "info": "info",
    "warning": "warn",
    "error": "error",
    "critical": "critical",
}

# Per-service logger cache (one JSONL file per service per day).
_LOGGERS: dict[str, logging.Logger] = {}


class EventJsonFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as exactly one JSONL line."""

    def format(self, record: logging.LogRecord) -> str:
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
        payload: dict = {
            "ts": ts,
            "level": _LEVEL_OUT.get(record.levelname.lower(), record.levelname.lower()),
            "service": getattr(record, "service", "unknown"),
            "event": getattr(record, "event", "unknown"),
        }
        for field in ("session_id", "latency_ms", "status", "user"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        extra = getattr(record, "extra", None)
        if extra:
            payload["extra"] = extra
        return json.dumps(payload, ensure_ascii=False)


def get_event_logger(service: str) -> logging.Logger:
    """Return (creating if needed) a per-service JSONL event logger.

    The logger carries a filter that stamps ``service`` on every record so
    callers never have to repeat it. If the events file cannot be opened, the
    logger degrades to ``stderr`` rather than raising.
    """
    cached = _LOGGERS.get(service)
    if cached is not None:
        return cached

    logger = logging.getLogger(f"events.{service}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addFilter(lambda r, svc=service: setattr(r, "service", svc) or True)

    try:
        os.makedirs(_EVENTS_DIR, exist_ok=True)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(_EVENTS_DIR, f"{service}-{date}.jsonl")
        handler: logging.Handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(EventJsonFormatter())
        logger.addHandler(handler)
    except Exception:
        # Best-effort: fall back to stderr so events are never silently lost
        # nor do they crash the caller.
        try:
            fallback = logging.StreamHandler(sys.stderr)
            fallback.setFormatter(EventJsonFormatter())
            logger.addHandler(fallback)
        except Exception:
            pass

    _LOGGERS[service] = logger
    return logger


def emit_event(
    service: str,
    event: str,
    level: str = "info",
    *,
    session_id: str | None = None,
    latency_ms: int | None = None,
    status: int | None = None,
    user: str | None = None,
    extra: dict | None = None,
) -> None:
    """Emit one JSONL event. Never raises, never blocks the caller.

    Args:
        service: stable service identifier (e.g. ``"webinfer"``).
        event: kebab-case event name (e.g. ``"wiki_recall_fail"``).
        level: one of debug/info/warn/error/critical (case-insensitive).
        session_id / latency_ms / status / user: optional schema fields.
        extra: optional payload object. MUST NOT contain PII (see module doc).
    """
    try:
        canon = _LEVEL_MAP.get(str(level).lower(), "INFO")
        lvl = logging.getLevelName(canon)
        if not isinstance(lvl, int):
            lvl = logging.INFO

        attrs: dict = {"event": event}
        if session_id is not None:
            attrs["session_id"] = session_id
        if latency_ms is not None:
            attrs["latency_ms"] = latency_ms
        if status is not None:
            attrs["status"] = status
        if user is not None:
            attrs["user"] = user
        if extra is not None:
            attrs["extra"] = extra

        get_event_logger(service).log(lvl, "", extra=attrs)
    except Exception:
        # Best-effort: swallow everything so event logging can never take
        # down the business path it instruments.
        pass
