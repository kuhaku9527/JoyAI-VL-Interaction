"""Regression tests for KWS parameter sweep accounting."""
from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "services" / "scripts"
for _p in (str(REPO), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_eval_dir_resets_kws_stream_before_each_wav(monkeypatch, tmp_path):
    import kws_param_sweep

    for idx in range(3):
        (tmp_path / f"sample_{idx}.wav").write_bytes(b"")

    starts = []

    class FakeKWS:
        def start(self):
            starts.append("start")

    monkeypatch.setattr(kws_param_sweep, "feed_wav", lambda kws, wav_path: 1)

    n, hits, pct = kws_param_sweep.eval_dir(FakeKWS(), tmp_path, "positive")

    assert n == 3
    assert hits == 3
    assert pct == 100.0
    assert starts == ["start", "start", "start"]