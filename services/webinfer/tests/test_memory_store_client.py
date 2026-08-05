"""Unit tests for MemoryStoreClient (memory-store v0.2 client)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx
import pytest
from memory_store_client import MemoryStoreClient


class _FakeAsyncClient:
    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url):
        self.calls.append(("GET", url, None))
        return self._handler("GET", url, None)

    async def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        return self._handler("POST", url, json)


def _make_handler(responses):
    def handler(method, url, body):
        key = (method, url)
        if key not in responses:
            return httpx.Response(404, json={"error": "no stub"})
        return responses[key]

    return handler


def _ok(payload):
    return httpx.Response(200, json=payload)


def test_is_enabled_reflects_constructor():
    c = MemoryStoreClient(base_url="http://x", enabled=True)
    assert c.is_enabled is True
    c2 = MemoryStoreClient(base_url="http://x", enabled=False)
    assert c2.is_enabled is False


@pytest.mark.asyncio
async def test_ping_true(monkeypatch):
    async def fake_get_client(self):
        return _FakeAsyncClient(_make_handler({("GET", "/health"): _ok({"ok": True})}))

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    assert await c.ping() is True


@pytest.mark.asyncio
async def test_ping_false(monkeypatch):
    async def fake_get_client(self):
        return _FakeAsyncClient(_make_handler({("GET", "/health"): httpx.Response(500)}))

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    assert await c.ping() is False


@pytest.mark.asyncio
async def test_warmup_uses_sentinel(monkeypatch):
    captured = {}

    def handler(method, url, body):
        captured.setdefault("calls", []).append((method, url, body))
        if method == "POST" and url == "/v1/blocks/recall":
            return _ok({"blocks": [{"block_id": "b1", "content": "hi", "score": 0.9}]})
        return httpx.Response(404)

    async def fake_get_client(self):
        return _FakeAsyncClient(handler)

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    blocks = await c.warmup("s1", top_k=8, min_score=0.1)
    assert blocks and blocks[0]["block_id"] == "b1"
    assert blocks[0]["content"] == "hi"
    assert blocks[0]["score"] == 0.9
    assert len(captured["calls"]) == 1
    method, _url, body = captured["calls"][0]
    assert method == "POST"
    assert body["query"] == "__warmup__"
    assert body["top_k"] == 8
    assert body["filter"]["session_ids"] == ["s1"]
    assert body["min_score"] == 0.1


@pytest.mark.asyncio
async def test_recall_with_question(monkeypatch):
    captured = {}

    def handler(method, url, body):
        captured["body"] = body
        return _ok({"blocks": [{"content": "x", "score": 1.0}]})

    async def fake_get_client(self):
        return _FakeAsyncClient(handler)

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    blocks = await c.recall("how are you?", session_id="s2", top_k=4)
    assert blocks and blocks[0]["content"] == "x"
    assert captured["body"]["query"] == "how are you?"
    assert captured["body"]["filter"]["session_ids"] == ["s2"]


@pytest.mark.asyncio
async def test_recall_no_session_filter(monkeypatch):
    captured = {}

    def handler(method, url, body):
        captured["body"] = body
        return _ok({"blocks": []})

    async def fake_get_client(self):
        return _FakeAsyncClient(handler)

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    await c.recall("anything", session_id=None)
    assert "filter" not in captured["body"] or not captured["body"].get("filter")


@pytest.mark.asyncio
async def test_push_returns_count(monkeypatch):
    captured = {}

    def handler(method, url, body):
        captured["body"] = body
        return _ok({"pushed": 3, "ids": ["a", "b", "c"]})

    async def fake_get_client(self):
        return _FakeAsyncClient(handler)

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    n = await c.push("s1", [{"content": "a"}, {"content": "b"}, {"content": "c"}])
    assert n == 3
    assert captured["body"]["session_id"] == "s1"
    assert len(captured["body"]["blocks"]) == 3


@pytest.mark.asyncio
async def test_disabled_client_is_noop():
    c = MemoryStoreClient(base_url="http://x", enabled=False)
    assert await c.ping() is False
    assert await c.warmup("s1") == []
    assert await c.recall("q") == []
    assert await c.push("s1", [{"content": "x"}]) == 0


@pytest.mark.asyncio
async def test_network_failure_degrades(monkeypatch):
    async def fake_get_client(self):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    assert await c.ping() is False
    assert await c.warmup("s1") == []
    assert await c.recall("q") == []
    assert await c.push("s1", [{"content": "x"}]) == 0


@pytest.mark.asyncio
async def test_health_snapshot_initial():
    c = MemoryStoreClient(base_url="http://x", enabled=True)
    snap = c.health_snapshot()
    assert snap["enabled"] is True
    assert snap["url"] == "http://x"
    assert snap["healthy"] is None


@pytest.mark.asyncio
async def test_health_snapshot_after_ping(monkeypatch):
    async def fake_get_client(self):
        return _FakeAsyncClient(_make_handler({("GET", "/health"): _ok({"ok": True})}))

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")
    assert await c.ping() is True
    snap = c.health_snapshot()
    assert snap["healthy"] is True


# Update warmup test expectation to match _normalize_block shape.


# ---------------------------------------------------------------------------
# Circuit breaker v0.3 (2026-07-29) — see ADR-0013 / doc/specs/memory-client-resilience.md
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold(monkeypatch):
    """3 consecutive failures open the circuit; subsequent calls short-circuit to [].

    The mock client counter proves the 4th call did NOT touch the network.
    """
    calls = {"n": 0}

    async def fake_get_client(self):
        calls["n"] += 1
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")

    # Threshold is 3 — first 3 calls hit the network and fail.
    assert await c.warmup("s1") == []
    assert await c.recall("q1") == []
    assert await c.push("s1", [{"content": "x"}]) == 0
    assert calls["n"] == 3, f"expected 3 network calls before trip, got {calls['n']}"

    # 4th call: breaker OPEN → returns [] without touching the network.
    assert await c.recall("q2") == []
    assert calls["n"] == 3, "breaker should have prevented the 4th call"


@pytest.mark.asyncio
async def test_circuit_breaker_resets_on_success(monkeypatch):
    """A successful call clears the failure counter and re-closes the circuit."""
    network_calls = {"n": 0}
    response = _ok({"blocks": []})

    async def fake_get_client(self):
        network_calls["n"] += 1
        return _FakeAsyncClient(_make_handler({("POST", "/v1/blocks/recall"): response}))

    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    c = MemoryStoreClient(base_url="http://x")

    # 2 failures — counter is 2, breaker still closed (threshold is 3).
    async def boom(self):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(MemoryStoreClient, "_get_client", boom)
    assert await c.warmup("s1") == []
    assert await c.recall("q") == []
    assert c._cb_failure_count == 2

    # Now succeed — counter resets.
    monkeypatch.setattr(MemoryStoreClient, "_get_client", fake_get_client)
    assert await c.warmup("s2") == []
    assert c._cb_failure_count == 0
    assert c._cb_open_until_monotonic == 0.0

    # After reset, a fresh failure streak still needs 3 to trip.
    async def boom2(self):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(MemoryStoreClient, "_get_client", boom2)
    assert await c.recall("q") == []
    assert await c.recall("q") == []
    assert c._cb_open_until_monotonic == 0.0, "should not yet be open at 2 failures"


@pytest.mark.asyncio
async def test_circuit_breaker_cooldown_expires(monkeypatch):
    """After the cooldown elapses, the next call is allowed through as a probe."""
    network_calls = {"n": 0}

    async def boom(self):
        network_calls["n"] += 1
        raise httpx.ConnectError("down")

    monkeypatch.setattr(MemoryStoreClient, "_get_client", boom)
    c = MemoryStoreClient(base_url="http://x")

    # Trip the breaker (3 failures).
    for _ in range(3):
        assert await c.recall("q") == []
    assert c._circuit_open() is True

    # While OPEN, the 4th call short-circuits without touching the network.
    pre_count = network_calls["n"]
    assert await c.recall("q") == []
    assert network_calls["n"] == pre_count, "should not probe while OPEN"

    # Fast-forward monotonic clock past the cooldown. We patch
    # ``time.monotonic`` on the module that the client imports from.
    import memory_store_client as msc

    real_mono = msc.time.monotonic
    cooldown_end = real_mono() + c._CB_COOLDOWN_S + 0.001
    monkeypatch.setattr(msc.time, "monotonic", lambda: cooldown_end)
    try:
        assert c._circuit_open() is False, "cooldown should have expired"
        # The next call is allowed through as a probe; it will fail and re-open.
        assert await c.recall("q") == []
        assert c._circuit_open() is True, "probe failure should re-open"
    finally:
        monkeypatch.setattr(msc.time, "monotonic", real_mono)


def test_constructor_raises_without_url_or_env(monkeypatch):
    """Fail-closed: no explicit base_url AND no MEMORY_STORE_URL -> ValueError.

    This is the historical-incident guard — without an explicit URL or the env
    var we must refuse to silently default to the dead empty-shell port 8996.
    """
    monkeypatch.delenv("MEMORY_STORE_URL", raising=False)
    with pytest.raises(ValueError, match="MEMORY_STORE_URL"):
        MemoryStoreClient()


def test_constructor_uses_env_url(monkeypatch):
    """MEMORY_STORE_URL is used as the base URL when no explicit one is given."""
    monkeypatch.setenv("MEMORY_STORE_URL", "http://127.0.0.1:8997")
    client = MemoryStoreClient()
    assert client.base_url == "http://127.0.0.1:8997"
