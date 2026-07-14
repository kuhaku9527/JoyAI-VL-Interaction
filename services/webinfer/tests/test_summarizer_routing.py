"""Tests for the v3.42 live summarizer routing endpoints.

The webui sidebar panel POSTs `/api/webinfer/summarizer/route` -> webui
proxies -> webinfer `POST /v1/summarizer/route` -> `SummarizerModel.update_routing`.

These tests pin:
  1. update_routing mutates the underlying OpenAI clients + model names.
  2. snapshot_routing reflects current state without leaking the API key.
  3. POST /v1/summarizer/route returns the new snapshot.
  4. POST /v1/summarizer/route with empty/missing api_key leaves the
     previously-set key alone (None sentinel semantics).
  5. POST with bad JSON returns 400.
  6. POST without summarizer enabled returns 503.

The real `memory_summarizer.SummarizerModel` constructor does
`from transformers import AutoTokenizer` inline, which is a 9-second
import even when no tokenizer is ever instantiated. The `_tokenizer`
is loaded lazily in `_get_tokenizer`, so the import is pure overhead
for routing-only tests. We stub `transformers.AutoTokenizer` to keep
the suite fast.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_FAKE_TRANSFORMERS_INSTALLED = "transformers" in sys.modules


@pytest.fixture(autouse=True)
def _stub_transformers_if_missing(monkeypatch):
    """If transformers is not installed, inject a fake module so the
    SummarizerModel constructor's inline `from transformers import
    AutoTokenizer` succeeds instantly. If transformers IS installed
    (this is a heavy ~9s import on first call), the fixture still
    forces a fast stub so routing tests don't pay that cost.
    """
    fake = types.ModuleType("transformers")
    fake.AutoTokenizer = None  # never instantiated by routing tests
    monkeypatch.setitem(sys.modules, "transformers", fake)
    yield
    if not _FAKE_TRANSFORMERS_INSTALLED:
        sys.modules.pop("transformers", None)


@dataclass
class _FakeRequest:
    method: str = "POST"
    headers: dict = None
    _body: dict = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"Content-Type": "application/json"}

    async def json(self):
        if self._body is None:
            raise ValueError("not json at all")
        return self._body

    async def text(self):
        return ""


def _make_summarizer():
    from memory_summarizer import SummarizerModel
    return SummarizerModel(
        model_name="old-model",
        api_base="http://localhost:7060/v1",
    )


def test_update_routing_replaces_api_base():
    summarizer = _make_summarizer()
    snapshot = summarizer.update_routing(
        api_base="https://api.minimaxi.com/v1/",
        model_name="MiniMax-VL-01",
        api_key="sk-real",
    )
    assert summarizer._client.base_url == "https://api.minimaxi.com/v1/"
    assert summarizer.model_name == "MiniMax-VL-01"
    assert summarizer._client.api_key == "sk-real"
    assert snapshot["api_base"] == "https://api.minimaxi.com/v1/"
    assert snapshot["model_name"] == "MiniMax-VL-01"
    assert snapshot["api_key_set"] is True


def test_snapshot_does_not_leak_api_key():
    summarizer = _make_summarizer()
    summarizer.update_routing(api_key="sk-secret-key")
    snap = summarizer.snapshot_routing()
    assert snap["api_key_set"] is True
    blob = json.dumps(snap)
    assert "sk-secret" not in blob
    assert "secret" not in blob


def test_update_routing_partial_keeps_others():
    summarizer = _make_summarizer()
    summarizer.update_routing(
        api_base="https://api.minimaxi.com/v1/",
        model_name="MiniMax-VL-01",
        api_key="sk-keep",
    )
    snap = summarizer.update_routing(api_base="https://other.example.com/v1/")
    assert summarizer._client.base_url == "https://other.example.com/v1/"
    assert summarizer.model_name == "MiniMax-VL-01"
    assert summarizer._client.api_key == "sk-keep"
    assert snap["model_name"] == "MiniMax-VL-01"
    assert snap["api_key_set"] is True


def test_update_routing_empty_string_clears_api_key():
    summarizer = _make_summarizer()
    summarizer.update_routing(api_key="sk-something")
    assert summarizer._client.api_key == "sk-something"
    snap = summarizer.update_routing(api_key="")
    assert summarizer._client.api_key in ("EMPTY", "")
    assert snap["api_key_set"] is False


def test_update_routing_omitted_kwargs_unchanged():
    summarizer = _make_summarizer()
    summarizer.update_routing(
        api_base="https://api.minimaxi.com/v1/",
        model_name="MiniMax-VL-01",
        api_key="sk-keep",
    )
    snap = summarizer.update_routing()
    assert snap["api_base"] == "https://api.minimaxi.com/v1/"
    assert snap["model_name"] == "MiniMax-VL-01"
    assert snap["api_key_set"] is True


def test_get_returns_503_when_summarizer_disabled():
    from live_adapter import StreamingInferAdapter
    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.summarizer = None

    async def _run():
        return await adapter.handle_summarizer_route(_FakeRequest(method="GET"))

    resp = asyncio.run(_run())
    assert resp.status == 503


def test_post_returns_503_when_summarizer_disabled():
    from live_adapter import StreamingInferAdapter
    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.summarizer = None

    async def _run():
        return await adapter.handle_summarizer_route(_FakeRequest(method="POST"))

    resp = asyncio.run(_run())
    assert resp.status == 503


def test_post_bad_json_returns_400():
    from live_adapter import StreamingInferAdapter
    summarizer = _make_summarizer()
    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.summarizer = summarizer
    request = _FakeRequest(method="POST")
    request._body = None  # make json() raise

    async def _run():
        return await adapter.handle_summarizer_route(request)

    resp = asyncio.run(_run())
    assert resp.status == 400


def test_post_returns_new_snapshot():
    from live_adapter import StreamingInferAdapter
    summarizer = _make_summarizer()
    adapter = StreamingInferAdapter.__new__(StreamingInferAdapter)
    adapter.summarizer = summarizer
    request = _FakeRequest(method="POST")
    request._body = {
        "api_base": "https://api.minimaxi.com/v1/",
        "model_name": "MiniMax-VL-01",
        "api_key": "sk-x",
    }

    async def _run():
        return await adapter.handle_summarizer_route(request)

    resp = asyncio.run(_run())
    assert resp.status == 200
    snap = summarizer.snapshot_routing()
    assert snap["api_base"] == "https://api.minimaxi.com/v1/"
    assert snap["model_name"] == "MiniMax-VL-01"
    assert snap["api_key_set"] is True
