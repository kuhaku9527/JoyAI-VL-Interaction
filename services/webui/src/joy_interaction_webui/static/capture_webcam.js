'use strict';

// capture_webcam.js
// Webcam capture via getUserMedia + WebRTC peer connection to backend.
//
// Public API (attached to window for non-module usage):
//   startWebcamCapture(ws?, opts?) -> Promise<void>
//   stopWebcamCapture()           -> void
//   isWebcamCapturing()           -> boolean
//   getWebcamStream()             -> MediaStream | null
//   getWebcamVideo()              -> HTMLVideoElement | null
//
// Independent state machine -- does not share globals with capture_rtsp.js
// or screen_capture.js. Each capture source owns its own RTCPeerConnection.
//
// v3.38: extracted from index.html global startWebcam() so each video source
// has its own start/stop API and the global start() dispatcher can go away.

(function () {
  let webcamStream = null;
  let webcamPeer = null;
  let webcamVideo = null;

  async function startWebcamCapture(ws, options) {
    if (options === undefined) options = {};
    if (webcamPeer) {
      console.warn('Webcam capture already active');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('getUserMedia not supported in this browser');
    }

    const constraints = options.constraints || {
      width: { ideal: 1280 },
      height: { ideal: 720 },
    };
    const sessionId = options.sessionId || (window.sessionId || 'default');
    const onState = typeof options.onState === 'function' ? options.onState : null;
    const onStream = typeof options.onStream === 'function' ? options.onStream : null;

    if (onState) onState('requesting-camera');
    webcamStream = await navigator.mediaDevices.getUserMedia({
      video: constraints,
      audio: false,
    });

    if (onStream) onStream(webcamStream);

    webcamPeer = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    });

    webcamStream.getTracks().forEach(function (track) {
      webcamPeer.addTrack(track, webcamStream);
    });

    webcamPeer.ontrack = function () {
      // Server-side track (re-encoded). UI handles remote stream via onStream
      // from the offer response if needed.
    };

    webcamPeer.oniceconnectionstatechange = function () {
      if (!webcamPeer) return;
      if (onState) {
        switch (webcamPeer.iceConnectionState) {
          case 'connected':
          case 'completed':
            onState('streaming');
            break;
          case 'disconnected':
          case 'failed':
          case 'closed':
            onState('disconnected');
            break;
        }
      }
    };

    const offer = await webcamPeer.createOffer();
    await webcamPeer.setLocalDescription(offer);

    const response = await fetch('/offer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sdp: webcamPeer.localDescription.sdp,
        type: webcamPeer.localDescription.type,
        session_id: sessionId,
      }),
    });
    if (!response.ok) {
      const errBody = await response.json().catch(function () { return {}; });
      throw new Error(errBody.error || ('HTTP ' + response.status));
    }
    const answer = await response.json();
    await webcamPeer.setRemoteDescription(new RTCSessionDescription(answer));
    if (onState) onState('negotiated');
  }

  function stopWebcamCapture() {
    if (webcamStream) {
      webcamStream.getTracks().forEach(function (track) { track.stop(); });
      webcamStream = null;
    }
    if (webcamPeer) {
      webcamPeer.close();
      webcamPeer = null;
    }
    if (webcamVideo) {
      webcamVideo.srcObject = null;
    }
  }

  function isWebcamCapturing() {
    return webcamPeer !== null;
  }

  function getWebcamStream() {
    return webcamStream;
  }

  function getWebcamVideo() {
    return webcamVideo;
  }

  window.startWebcamCapture = startWebcamCapture;
  window.stopWebcamCapture = stopWebcamCapture;
  window.isWebcamCapturing = isWebcamCapturing;
  window.getWebcamStream = getWebcamStream;
  window.getWebcamVideo = getWebcamVideo;
})();
