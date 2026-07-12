/**
 * Screen Capture via getDisplayMedia.
 * 
 * Captures a game window at 1fps, encodes to JPEG, and sends as base64
 * over the existing WebSocket connection (replaces RTSP).
 * 
 * Usage: call `startScreenCapture(ws)` from the UI.
 * To stop: call `stopScreenCapture()`.
 */

let screenCaptureStream = null;
let screenCaptureInterval = null;

/**
 * Start capturing a display surface (game window).
 * @param {WebSocket} ws - already-established WebSocket connection
 * @param {Object} options
 * @param {number} [options.fps=1] - capture frame rate
 * @param {string} [options.preferredWindow] - window name hint (ignored, browser picks)
 */
export async function startScreenCapture(ws, options = {}) {
  if (screenCaptureStream) {
    console.warn("Screen capture already active");
    return;
  }

  const fps = options.fps || 1;
  const intervalMs = Math.floor(1000 / fps);

  try {
    // Prompt user to select a window/tab/screen
    screenCaptureStream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "window",   // prefer application window
        frameRate: { ideal: fps },
        width: { ideal: 960 },      // low-res capture (game runs in window)
        height: { ideal: 540 },
      },
      audio: false,                  // no audio from video capture
    });

    console.log("Screen capture started:", screenCaptureStream);

    const track = screenCaptureStream.getVideoTracks()[0];
    const imageCapture = new ImageCapture(track);

    // Listen for user clicking "Stop Sharing" in browser UI
    track.addEventListener("ended", () => stopScreenCapture());

    screenCaptureInterval = setInterval(async () => {
      try {
        const bitmap = await imageCapture.grabFrame();
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(bitmap, 0, 0);

        // To JPEG base64 (smaller than PNG)
        const jpegDataUrl = canvas.toDataURL("image/jpeg", 0.75);
        const base64 = jpegDataUrl.split(",")[1];

        // Send over WS (same protocol as old RTSP frames)
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({
            type: "frame",
            format: "jpeg",
            width: canvas.width,
            height: canvas.height,
            data: base64,
            timestamp: Date.now(),
          }));
        }
      } catch (err) {
        console.error("Screen capture frame error:", err);
      }
    }, intervalMs);

  } catch (err) {
    console.error("Failed to start screen capture:", err);
    stopScreenCapture();
  }
}

/**
 * Stop screen capture and clean up.
 */
export function stopScreenCapture() {
  if (screenCaptureStream) {
    screenCaptureStream.getTracks().forEach(t => t.stop());
    screenCaptureStream = null;
  }
  if (screenCaptureInterval) {
    clearInterval(screenCaptureInterval);
    screenCaptureInterval = null;
  }
  console.log("Screen capture stopped");
}