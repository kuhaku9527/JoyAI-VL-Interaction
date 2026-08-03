"""JSONL event emitter for ADR-0014 / spec ``log-event-schema`` v1.0.

Zero third-party dependencies — stdlib :mod:`logging` + :mod:`json` only.
Each event is written as one JSON object per line to
``logs/events/<service>-<UTC-YYYY-MM-DD>.jsonl`` (per-service, per-UTC-day
file; see decision D-2026-08-01-060).

Schema (required): ``ts`` (ISO-8601 UTC, millisecond), ``level``
(debug/info/warn/error/critical), ``service``, ``event`` (kebab-case).
Optional: ``session_id``, ``latency_ms``, ``status``, ``user``, ``extra``.

PII red line (decision D-061): callers MUST NOT pass raw request/response
bodies, API keys/tokens, file contents, or client IPs in ``extra`` — use
lengths / hashes / flags only. The emitter cannot scrub PII; CI adds a lint
gate. Violations are treated as incidents (DRIFT-7).

约法三章 compliance:
* No silent fallbacks. If the events directory or the day's log file cannot
  be created, logger setup raises — a service that cannot record its event
  stream should fail loud at startup, not run blind (缺失即报错).
* ``emit_event`` never swallows exceptions. Serialization or handler errors
  surface through the logging module's own error channel (stderr) rather than
  being hidden, and never abort the instrumented business path.
"""

from __future__ import annotations

import json
import logging
import os
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

# Per-(service, UTC-date) logger cache so files roll at UTC midnight (D-060).
_LOGGERS: dict[tuple[str, str], logging.Logger] = {}


def _close_logger(logger: logging.Logger) -> None:
    """Drop and close every handler on ``logger`` (used at day rollover)."""
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except OSError as exc:  # cleanup only; report, never abort
            logging.getLogger(__name__).warning("event logger handler close failed: %s", exc)


class EventJsonFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as exactly one JSONL line."""

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as one JSONL line (no trailing newline added).

        Args:
            record: the :class:`logging.LogRecord` produced by ``emit_event``.

        Returns
        -------
            A single-line JSON string matching the ADR-0014 event schema.
        """
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        ts = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
        payload: dict[str, object] = {
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
    """Return (creating if needed) the per-service, per-UTC-day JSONL logger.

    Raises
    ------
        OSError: if the events directory or the day's log file cannot be
            created. A service that cannot open its event stream should fail
            loud (约法三章: 缺失即报错), not silently drop events.
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = (service, date)
    cached = _LOGGERS.get(key)
    if cached is not None:
        return cached

    # Day rollover: release the previous UTC-day's file handles for this service.
    for old_key in [k for k in _LOGGERS if k[0] == service and k[1] != date]:
        _close_logger(_LOGGERS.pop(old_key))

    logger = logging.getLogger(f"events.{service}.{date}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    os.makedirs(_EVENTS_DIR, exist_ok=True)
    path = os.path.join(_EVENTS_DIR, f"{service}-{date}.jsonl")
    handler: logging.Handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(EventJsonFormatter())
    logger.addHandler(handler)
    _LOGGERS[key] = logger
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
    """Emit one JSONL event with the ADR-0014 schema.

    Does not swallow exceptions: a non-serializable ``extra`` raises
    ``ValueError`` so the caller's bug surfaces, and a handler write error is
    reported by the logging module to stderr (non-propagating). The business
    path is therefore observable but not aborted on a logging hiccup.

    Args:
        service: stable service identifier (e.g. ``"webinfer"``).
        event: kebab-case event name (e.g. ``"wiki_recall_fail"``).
        level: one of debug/info/warn/error/critical (case-insensitive).
        session_id / latency_ms / status / user: optional schema fields.
        extra: optional payload object. MUST NOT contain PII (see module doc).
    """
    canon = _LEVEL_MAP.get(str(level).lower(), "INFO")
    lvl = logging.getLevelName(canon)
    if not isinstance(lvl, int):
        lvl = logging.INFO
    attrs: dict[str, object] = {"service": service, "event": event}
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
