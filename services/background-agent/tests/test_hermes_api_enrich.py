# SPDX-License-Identifier: Apache-2.0
"""Unit tests for hermes_api._enrich_with_memory ([Local Wiki] recall glue).

These lock in the architectural contract the bridge depends on:

* The shim must RETRIEVE relevant memory (top_k + min_score), never dump the
  whole store into the LLM context.
* Any failure (network error, 4xx/5xx, empty result, missing service) must
  fail OPEN and return "" so the hermes gateway silently falls back to web
  search. The solve must never be blocked by memory-store.

Run with:  python -m pytest services/background-agent/tests -o asyncio_mode=auto
"""

from __future__ import annotations

import httpx
import pytest
from hermes_api import main as hapi


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=None,
                response=None,  # type: ignore[arg-type]
            )

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Captures the POST call so we can assert the recall contract."""

    def __init__(self, response: _FakeResponse, capture: dict):
        self._response = response
        self._capture = capture

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url: str, json: dict | None = None) -> _FakeResponse:
        self._capture["url"] = url
        self._capture["json"] = json
        return self._response


@pytest.fixture
def capture():
    return {}


def _patch_client(monkeypatch, response, capture):
    monkeypatch.setattr(
        hapi.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeClient(response, capture),
    )


async def test_enrich_requests_top_k_and_min_score_contract(monkeypatch, capture):
    """The shim must ask memory-store for a bounded, ranked recall (retrieval,
    NOT a wholesale dump), scoped to wiki namespaces (ADR-0012)."""
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": []}), capture)
    await hapi._enrich_with_memory("BT-7274 weapon")
    assert capture["url"].endswith("/v1/blocks/recall")
    assert capture["json"] == {
        "query": "BT-7274 weapon",
        "top_k": 5,
        "min_score": 0.4,
        "filter": {"namespaces": ["wiki:*"]},
    }


async def test_enrich_renders_image_refs_for_wiki_blocks(monkeypatch, capture):
    """Wiki blocks carrying image paths must surface them for the main VLM."""
    blocks = [
        {"content": "火焰巨人弱打击", "images": ["assets/fire-giant.png"]},
        {"content": "纯文本块", "images": None},
    ]
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": blocks}), capture)
    out = await hapi._enrich_with_memory("火焰巨人怎么打")
    assert out == "- 火焰巨人弱打击 (附图: assets/fire-giant.png)\n- 纯文本块"


async def test_enrich_returns_empty_when_namespaces_blank(monkeypatch, capture):
    """WIKI_RECALL_NAMESPACES="" disables wiki recall entirely (fail open)."""
    monkeypatch.setattr(hapi, "WIKI_RECALL_NAMESPACES", "")
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": [{"content": "x"}]}), capture)
    assert await hapi._enrich_with_memory("q") == ""
    assert "url" not in capture  # no network call made


async def test_enrich_returns_ranked_bullets_for_relevant_blocks(monkeypatch, capture):
    blocks = [
        {"content": "alpha result"},
        {"content": "beta result"},
        {"content": "gamma result"},
    ]
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": blocks}), capture)
    out = await hapi._enrich_with_memory("some question")
    assert out == "- alpha result\n- beta result\n- gamma result"


async def test_enrich_returns_empty_when_no_blocks(monkeypatch, capture):
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": []}), capture)
    assert await hapi._enrich_with_memory("q") == ""


async def test_enrich_returns_empty_on_http_error_status(monkeypatch, capture):
    _patch_client(monkeypatch, _FakeResponse(503, {"blocks": []}), capture)
    assert await hapi._enrich_with_memory("q") == ""


async def test_enrich_returns_empty_when_network_raises(monkeypatch, capture):
    class _BoomClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            raise httpx.ConnectError("memory-store down")

    monkeypatch.setattr(hapi.httpx, "AsyncClient", lambda *a, **k: _BoomClient())
    assert await hapi._enrich_with_memory("q") == ""


async def test_enrich_returns_empty_on_empty_question(monkeypatch, capture):
    # No HTTP call should happen for an empty question.
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": ["x"]}), capture)
    assert await hapi._enrich_with_memory("") == ""
    assert "url" not in capture  # proves we short-circuit before any network call


async def test_enrich_skips_blocks_without_content(monkeypatch, capture):
    blocks = [
        {"content": "keep me"},
        {"content": ""},
        {"not_content": "drop me"},
        {"content": "keep me too"},
    ]
    _patch_client(monkeypatch, _FakeResponse(200, {"blocks": blocks}), capture)
    out = await hapi._enrich_with_memory("q")
    assert out == "- keep me\n- keep me too"
