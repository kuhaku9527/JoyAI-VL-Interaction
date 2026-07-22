'use strict';

// Screen Capture via getDisplayMedia.
// Captures a user-selected window/tab at 1 fps and ships JPEG frames to the
// server over the existing WebSocket (type: frame). Runs alongside the
// WebRTC webcam / RTSP pipeline -- does not touch VideoProcessorTrack.
//
// Public API (attached to window for non-module usage):
//   startScreenCapture(ws?, options?)  -> Promise<void>
//   stopScreenCapture()                -> void
//   isScreenCapturing()                -> boolean
//   getScreenCaptureStream()           -> MediaStream | null
//   getScreenCaptureVideo()            -> HTMLVideoElement | null
//
// v3.33: getScreenCaptureStream / getScreenCaptureVideo let index.html mount
// the same MediaStream on <video id="videoElement"> for a local preview tile,
// so the operator can see the captured window in the WebUI while BT-7274
// also receives the 1 fps JPEG frames over the WS frame pipeline.

(function () {
  let screenCaptureStream = null;
  let screenCaptureInterval = null;
  let screenCaptureVideo = null;

  function resolveWebSocket(ws) {
    if (ws && ws.readyState !== undefined) return ws;
    if (typeof window !== 'undefined' && window.websocket) return window.websocket;
    return null;
  }

  async function startScreenCapture(ws, options) {
    if (options === undefined) options = {};
    if (screenCaptureStream) {
      console.warn('Screen capture already active');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      console.error('getDisplayMedia not supported in this browser');
      return;
    }

    const fps = options.fps || 1;
    const intervalMs = Math.floor(1000 / fps);

    try {
      screenCaptureStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          displaySurface: 'window',
          frameRate: { ideal: fps },
          width: { ideal: 960 },
          height: { ideal: 540 },
        },
        audio: false,
      });

      console.log('Screen capture started:', screenCaptureStream);

      const track = screenCaptureStream.getVideoTracks()[0];
      let imageCapture = null;
      if (typeof ImageCapture === 'function') {
        try {
          imageCapture = new ImageCapture(track);
        } catch (err) {
          console.warn('ImageCapture unavailable, falling back to video + drawImage:', err);
        }
      }

      screenCaptureVideo = document.createElement('video');
      screenCaptureVideo.srcObject = screenCaptureStream;
      screenCaptureVideo.muted = true;
      screenCaptureVideo.playsInline = true;
      try {
        await screenCaptureVideo.play();
      } catch (err) {
        console.warn('screen capture video play() rejected:', err);
      }

      track.addEventListener('ended', () => stopScreenCapture());

      screenCaptureInterval = setInterval(async () => {
        try {
          const liveWs = resolveWebSocket(ws);
          if (!liveWs || liveWs.readyState !== WebSocket.OPEN) {
            return;
          }
          let width = 0;
          let height = 0;
          let bitmap = null;
          if (imageCapture) {
            bitmap = await imageCapture.grabFrame();
            width = bitmap.width;
            height = bitmap.height;
          } else if (screenCaptureVideo && screenCaptureVideo.readyState >= 2 && screenCaptureVideo.videoWidth > 0) {
            width = screenCaptureVideo.videoWidth;
            height = screenCaptureVideo.videoHeight;
          } else {
            return;
          }
          const canvas = document.createElement('canvas');
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext('2d');
          if (bitmap) {
            ctx.drawImage(bitmap, 0, 0, width, height);
          } else if (screenCaptureVideo) {
            ctx.drawImage(screenCaptureVideo, 0, 0, width, height);
          }
          const jpegDataUrl = canvas.toDataURL('image/jpeg', 0.75);
          const base64 = jpegDataUrl.split(',')[1];
          liveWs.send(JSON.stringify({
            type: 'frame',
            format: 'jpeg',
            width: width,
            height: height,
            data: base64,
            timestamp: Date.now(),
            source: 'screen',
          }));
        } catch (err) {
          console.error('Screen capture frame error:', err);
        }
      }, intervalMs);
    } catch (err) {
      console.error('Failed to start screen capture:', err);
      stopScreenCapture();
    }
  }

  function stopScreenCapture() {
    if (screenCaptureInterval) {
      clearInterval(screenCaptureInterval);
      screenCaptureInterval = null;
    }
    if (screenCaptureStream) {
      try {
        screenCaptureStream.getTracks().forEach(function (t) { t.stop(); });
      } catch (err) {
        console.warn('stopScreenCapture track.stop failed:', err);
      }
      screenCaptureStream = null;
    }
    if (screenCaptureVideo) {
      try {
        screenCaptureVideo.pause();
      } catch {
        // ignore
      }
      screenCaptureVideo.srcObject = null;
      screenCaptureVideo = null;
    }
    console.log('Screen capture stopped');
  }

  function isScreenCapturing() {
    return screenCaptureStream !== null;
  }

  function getScreenCaptureStream() {
    return screenCaptureStream;
  }

  function getScreenCaptureVideo() {
    return screenCaptureVideo;
  }

  if (typeof window !== 'undefined') {
    window.startScreenCapture = startScreenCapture;
    window.stopScreenCapture = stopScreenCapture;
    window.isScreenCapturing = isScreenCapturing;
    window.getScreenCaptureStream = getScreenCaptureStream;
    window.getScreenCaptureVideo = getScreenCaptureVideo;
  }
})();
