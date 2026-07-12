"""Tests for WebRTC audio binding into the Jarvis listening chain."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
WEBUI_SRC = REPO / "services" / "webui" / "src"
for _p in (str(REPO), str(WEBUI_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class FakePeerConnection:
    def __init__(self):
        self.handlers = {}
        self.added_tracks = []
        self.localDescription = None
        self.remote_description = None

    def on(self, event_name):
        def decorator(fn):
            self.handlers[event_name] = fn
            return fn
        return decorator

    def addTrack(self, track):
        self.added_tracks.append(track)
        return track

    async def setRemoteDescription(self, desc):
        self.remote_description = desc

    async def createAnswer(self):
        class Answer:
            sdp = "v=0\r\nanswer"
            type = "answer"
        return Answer()

    async def setLocalDescription(self, desc):
        self.localDescription = desc


class FakeManager:
    def __init__(self):
        self.created = []
        self.session = object()

    async def create_session(self, session_id):
        self.created.append(session_id)
        return self.session


def test_bind_jarvis_audio_for_peer_creates_session_speaker_and_audio_handler(monkeypatch):
    from joy_interaction_webui import server

    pc = FakePeerConnection()
    manager = FakeManager()
    started_consumers = []
    created_mics = []

    class FakeDoneTask:
        def add_done_callback(self, cb):
            self.done_callback = cb

    class FakeMicAudioTrack:
        def __init__(self, track, session):
            self.track = track
            self.session = session
            created_mics.append(self)

    monkeypatch.setattr(server, "bind_audio", lambda session_id, manager: "speaker-track")
    monkeypatch.setattr(server, "MicAudioTrack", FakeMicAudioTrack, raising=False)
    monkeypatch.setattr(
        server,
        "_start_mic_audio_consumer",
        lambda mic_track, session_id: started_consumers.append((mic_track, session_id)) or FakeDoneTask(),
        raising=False,
    )

    asyncio.run(server.bind_jarvis_audio_for_peer(pc, "s1", manager))

    assert manager.created == ["s1"]
    assert pc.added_tracks == ["speaker-track"]
    assert "track" in pc.handlers

    class AudioTrack:
        kind = "audio"

    pc.handlers["track"](AudioTrack())

    assert len(created_mics) == 1
    assert created_mics[0].session is manager.session
    assert started_consumers == [(created_mics[0], "s1")]


def test_offer_invokes_jarvis_audio_binding(monkeypatch):
    from joy_interaction_webui import server

    fake_pc = FakePeerConnection()
    calls = []

    class FakeRequest:
        app = {"jarvis_manager": "manager"}

        async def json(self):
            return {"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111", "type": "offer", "session_id": "s1", "jarvis_audio": True}

    def fake_rtc_session_description(sdp, type):
        return {"sdp": sdp, "type": type}

    async def fake_bind(pc, session_id, manager):
        calls.append((pc, session_id, manager))

    monkeypatch.setattr(server, "RTCSessionDescription", fake_rtc_session_description)
    monkeypatch.setattr(server, "RTCPeerConnection", lambda configuration=None: fake_pc)
    monkeypatch.setattr(server, "bind_jarvis_audio_for_peer", fake_bind, raising=False)
    server.pcs.clear()
    server.session_peer_connections.clear()

    response = asyncio.run(server.offer(FakeRequest()))
    payload = json.loads(response.text)

    assert payload["type"] == "answer"
    assert calls == [(fake_pc, "s1", "manager")]
    assert fake_pc in server.pcs
    assert fake_pc in server.session_peer_connections["s1"]