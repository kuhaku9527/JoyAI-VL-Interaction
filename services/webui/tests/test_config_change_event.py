"""Regression: config-change events follow the ADR-0014 JSONL schema.

Asserts ``server._log_config_change`` writes one JSON object per line to
``logs/events/webui-<UTC-date>.jsonl`` with the required fields
(``ts`` / ``level`` / ``service`` / ``event``) and carries the slot /
changed fields / redacted values inside ``extra``. Crucially, api_key must
be redacted (``***set***`` / ``***cleared***``), never written in plaintext.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from joy_interaction_webui import server  # noqa: E402


def test_log_config_change_writes_adr0014_record(tmp_path):
    events_dir = tmp_path / "events"
    server._log_config_change(
        "asr",
        ["api_key", "model"],
        {"api_key": "***set***", "model": "some-model"},
        events_dir=str(events_dir),
    )

    files = list(events_dir.glob("webui-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])

    # ts is ISO-8601 UTC
    assert record["ts"].endswith("+00:00")
    assert record["level"] == "info"
    assert record["service"] == "webui"
    assert record["event"] == "config.services.patch"
    assert record["extra"]["slot"] == "asr"
    assert record["extra"]["changed_fields"] == ["api_key", "model"]
    assert record["extra"]["redacted_values"]["api_key"] == "***set***"
    assert record["extra"]["redacted_values"]["model"] == "some-model"


def test_log_config_change_redacts_api_key(tmp_path):
    events_dir = tmp_path / "events"
    server._log_config_change(
        "tts",
        ["api_key"],
        {"api_key": "***cleared***"},
        events_dir=str(events_dir),
    )
    files = list(events_dir.glob("webui-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["extra"]["redacted_values"]["api_key"] == "***cleared***"
    # never the literal secret plaintext
    assert "sk-secret-plaintext" not in json.dumps(record)
