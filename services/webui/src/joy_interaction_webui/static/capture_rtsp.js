// capture_rtsp.js
// RTSP capture via WebRTC peer connection (server fetches the RTSP stream,
// re-encodes, and ships it back via WebRTC).
//
// Public API (attached to window for non-module usage):
//   startRtspCapture(ws?, opts?) -> Promise<void>
//   stopRtspCapture()            -> void
//   isRtspCapturing()            -> boolean
//   getRtspStream()              -> MediaStream | null
//
// Independent state machine -- does not share globals with capture_webcam.js
// or screen_capture.js.
//
// v3.38: extracted from index.html global startRTSP() so each video source
// has its own start/stop API.

(function () {
  let rtspPeer = null;
  let rtspStream = null;
  let rtspUrl = "";

  function resolveWebSocket(ws) {
    if (ws && ws.readyState !== undefined) return ws;
    if (typeof window !== "undefined" && window.websocket) return window.websocket;
    return null;
  }

  async function startRtspCapture(ws, options) {
    if (options === undefined) options = {};
    if (rtspPeer) {
      console.warn("RTSP capture already active");
      return;
    }
    const url = (options.rtspUrl || "").trim();
    if (!url) {
      throw new Error("rtspUrl is required");
    }
    const sessionId = options.sessionId || (window.sessionId || "default");
    const onState = typeof options.onState === "function" ? options.onState : null;
    const onStream = typeof options.onStream === "function" ? options.onStream : null;

    rtspUrl = url;

    rtspPeer = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });

    rtspPeer.ontrack = function (event) {
      if (event.track.kind === "video" && event.streams && event.streams[0]) {
        rtspStream = event.streams[0];
        if (onStream) onStream(rtspStream);
      }
    };

    rtspPeer.oniceconnectionstatechange = function () {
      if (!rtspPeer) return;
      if (onState) {
        switch (rtspPeer.iceConnectionState) {
          case "connected":
          case "completed":
            onState("streaming");
            break;
          case "disconnected":
          case "failed":
          case "closed":
            onState("disconnected");
            break;
        }
      }
    };

    rtspPeer.addTransceiver("video", { direction: "recvonly" });
    const offer = await rtspPeer.createOffer();
    await rtspPeer.setLocalDescription(offer);

    // Wait for ICE gathering (max 5s) so all candidates embed in the SDP
    await new Promise(function (resolve) {
      if (rtspPeer.iceGatheringState === "complete") {
        resolve();
      } else {
        const check = function () {
          if (rtspPeer && rtspPeer.iceGatheringState === "complete") {
            rtspPeer.removeEventListener("icegatheringstatechange", check);
            resolve();
          }
        };
        rtspPeer.addEventListener("icegatheringstatechange", check);
        setTimeout(function () {
          if (rtspPeer) rtspPeer.removeEventListener("icegatheringstatechange", check);
          resolve();
        }, 5000);
      }
    });

    const response = await fetch("/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: rtspPeer.localDescription.sdp,
        type: rtspPeer.localDescription.type,
        rtsp_url: rtspUrl,
        session_id: sessionId,
      }),
    });
    if (!response.ok) {
      const errBody = await response.json().catch(function () { return {}; });
      throw new Error(errBody.error || ("HTTP " + response.status));
    }
    const answer = await response.json();
    await rtspPeer.setRemoteDescription(new RTCSessionDescription(answer));
    if (onState) onState("negotiated");
  }

  function stopRtspCapture() {
    if (rtspPeer) {
      rtspPeer.close();
      rtspPeer = null;
    }
    rtspStream = null;
    rtspUrl = "";
  }

  function isRtspCapturing() {
    return rtspPeer !== null;
  }

  function getRtspStream() {
    return rtspStream;
  }

  window.startRtspCapture = startRtspCapture;
  window.stopRtspCapture = stopRtspCapture;
  window.isRtspCapturing = isRtspCapturing;
  window.getRtspStream = getRtspStream;
})();
