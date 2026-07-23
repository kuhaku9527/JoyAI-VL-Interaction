"""Tests for JarvisConfig env reading (ADR 0002).

Each test wipes JARVIS_* env vars before/after, then re-applies a known set
and asserts JarvisConfig.from_env() returns the right values.

Run: pytest services/webui/tests/test_jarvis_config_env.py -v
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

# Path setup: services/webui/src must be importable so `joy_interaction_webui`
# resolves. We also need the `services` top-level so `services.asr.jarvis.kws`
# imports work later. Use the same shape as services/scripts/test_jarvis_kws_e2e.py.
REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in os.sys.path:
        os.sys.path.insert(0, _p)


# Env vars touched by JarvisConfig.from_env(); we snapshot/restore around tests.
KWS_ENV_VARS = (
    "JARVIS_KWS_MODEL_DIR",
    "JARVIS_KWS_SCORE",
    "JARVIS_KWS_THRESHOLD",
    "JARVIS_KWS_TRAILING_BLANKS",
    "JARVIS_KWS_MAX_ACTIVE_PATHS",
    "JARVIS_KWS_SHADOW_ASR",
    "JARVIS_KWS_CAPTURE",
    "JARVIS_KWS_CAPTURE_DIR",
    "JARVIS_KWS_CAPTURE_WINDOW_S",
    "JARVIS_KWS_CAPTURE_INTERVAL_S",
    "JARVIS_KWS_CAPTURE_PEAK",
    "JARVIS_KWS_FRESH_PROBE",
    "JARVIS_KWS_FRESH_PROBE_INTERVAL_S",
    "JARVIS_KWS_FRESH_PROBE_MIN_S",
    "JARVIS_KWS_FRESH_DIRECT_WAKE",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    for var in KWS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def _reload_config_module():
    """Import jarvis_mode fresh so dataclass defaults are reset."""
    import joy_interaction_webui.jarvis_mode as mod

    importlib.reload(mod)
    return mod


def test_from_env_returns_defaults_when_no_env():
    mod = _reload_config_module()
    cfg = mod.JarvisConfig.from_env()
    assert cfg.kws_model_dir == "D:/AI/models/sherpa-onnx/models/kws/bt-en"
    assert cfg.kws_keywords_score == 10.0
    assert cfg.kws_keywords_threshold == 0.25
    assert cfg.kws_num_trailing_blanks == 1
    assert cfg.kws_max_active_paths == 10
    assert cfg.kws_shadow_asr_enabled is True
    assert cfg.kws_capture_enabled is True
    assert cfg.kws_capture_dir == "D:/AI/data/kws/mic_captures"
    assert cfg.kws_fresh_window_probe_enabled is True
    assert cfg.kws_fresh_window_direct_wake is True


def test_from_env_reads_model_dir_override(monkeypatch):
    monkeypatch.setenv("JARVIS_KWS_MODEL_DIR", "D:/x/bt-custom")
    mod = _reload_config_module()
    cfg = mod.JarvisConfig.from_env()
    assert cfg.kws_model_dir == "D:/x/bt-custom"


def test_from_env_reads_score_and_threshold(monkeypatch):
    monkeypatch.setenv("JARVIS_KWS_SCORE", "12.5")
    monkeypatch.setenv("JARVIS_KWS_THRESHOLD", "0.30")
    mod = _reload_config_module()
    cfg = mod.JarvisConfig.from_env()
    assert cfg.kws_keywords_score == 12.5
    assert cfg.kws_keywords_threshold == 0.30


def test_from_env_reads_int_params(monkeypatch):
    monkeypatch.setenv("JARVIS_KWS_TRAILING_BLANKS", "2")
    monkeypatch.setenv("JARVIS_KWS_MAX_ACTIVE_PATHS", "20")
    mod = _reload_config_module()
    cfg = mod.JarvisConfig.from_env()
    assert cfg.kws_num_trailing_blanks == 2
    assert cfg.kws_max_active_paths == 20


def test_from_env_reads_kws_diagnostic_params(monkeypatch):
    monkeypatch.setenv("JARVIS_KWS_SHADOW_ASR", "false")
    monkeypatch.setenv("JARVIS_KWS_CAPTURE", "0")
    monkeypatch.setenv("JARVIS_KWS_CAPTURE_DIR", "D:/tmp/kws-caps")
    monkeypatch.setenv("JARVIS_KWS_CAPTURE_WINDOW_S", "4.5")
    monkeypatch.setenv("JARVIS_KWS_CAPTURE_INTERVAL_S", "1.25")
    monkeypatch.setenv("JARVIS_KWS_CAPTURE_PEAK", "0.05")
    monkeypatch.setenv("JARVIS_KWS_FRESH_PROBE", "false")
    monkeypatch.setenv("JARVIS_KWS_FRESH_PROBE_INTERVAL_S", "0.25")
    monkeypatch.setenv("JARVIS_KWS_FRESH_PROBE_MIN_S", "0.8")
    monkeypatch.setenv("JARVIS_KWS_FRESH_DIRECT_WAKE", "false")
    mod = _reload_config_module()
    cfg = mod.JarvisConfig.from_env()
    assert cfg.kws_shadow_asr_enabled is False
    assert cfg.kws_capture_enabled is False
    assert cfg.kws_capture_dir == "D:/tmp/kws-caps"
    assert cfg.kws_capture_window_s == 4.5
    assert cfg.kws_capture_min_interval_s == 1.25
    assert cfg.kws_capture_peak_threshold == 0.05
    assert cfg.kws_fresh_window_probe_enabled is False
    assert cfg.kws_fresh_window_probe_interval_s == 0.25
    assert cfg.kws_fresh_window_min_s == 0.8
    assert cfg.kws_fresh_window_direct_wake is False


def test_from_env_falls_back_on_invalid_float(monkeypatch, caplog):
    monkeypatch.setenv("JARVIS_KWS_SCORE", "not_a_number")
    mod = _reload_config_module()
    with caplog.at_level("WARNING"):
        cfg = mod.JarvisConfig.from_env()
    assert cfg.kws_keywords_score == 10.0  # default
    assert any("JARVIS_KWS_SCORE" in rec.message for rec in caplog.records)


def test_default_model_dir_is_bt_en():
    """Regression: folder rename from bt-zai-ma to bt-en (2026-07-11)."""
    mod = _reload_config_module()
    cfg = mod.JarvisConfig()
    assert "bt-en" in cfg.kws_model_dir
    assert "bt-zai-ma" not in cfg.kws_model_dir
