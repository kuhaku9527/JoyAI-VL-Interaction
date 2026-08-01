'use strict';

// i18n_device_label.js
// Runtime device-label localization, extracted from index.html so the monolith
// shrinks AND the mapping becomes unit-testable (tests/i18n_device_label.test.js).
//
// Public API (attached to window.JoyI18n for non-module usage):
//   localizeDeviceLabel(label) -> string
//   DEVICE_LABEL_MAP          -> Array<[RegExp, string]>
//
// Maps OS-reported English device names (e.g. "OBS Virtual Camera") to Chinese.
// Conservative: only known English patterns are replaced; unknown labels —
// including already-Chinese labels on a zh-locale OS — pass through unchanged,
// so we never mistranslate. Loaded via <script src> in index.html <head> BEFORE
// the inline app script that calls window.JoyI18n.localizeDeviceLabel.
//
// v1.0: extracted from the inline localizeDeviceLabel() cluster (PR #56).

(function () {
  // Ordered most-specific first: a more specific phrase must precede its generic
  // substring so the generic rule does not partially mangle it
  // (e.g. "Integrated Webcam" before "Webcam"; "USB* Camera" before "Camera";
  // "FaceTime HD Camera" before "HD Camera" before "Camera"; "Headset Microphone"
  // before "Headset"/"Microphone").
  const DEVICE_LABEL_MAP = [
    [/\bOBS Virtual Camera\b/i, 'OBS 虚拟摄像头'],
    [/\bVirtual Camera\b/i, '虚拟摄像头'],
    [/\bIntegrated Webcam\b/i, '内置摄像头'],
    [/\bIntegrated Camera\b/i, '内置摄像头'],
    [/\bFaceTime HD Camera\b/i, 'FaceTime 高清摄像头'],
    [/\bHD Webcam\b/i, '高清摄像头'],
    [/\bUSB[\s0-9.]*Camera\b/i, 'USB 摄像头'],
    [/\bWebcam\b/i, '摄像头'],
    [/\bHD Camera\b/i, '高清摄像头'],
    [/\bCamera\b/i, '摄像头'],
    [/\bHeadset Microphone\b/i, '耳机麦克风'],
    [/\bHeadset\b/i, '耳机'],
    [/\bMicrophone\b/i, '麦克风'],
    [/\bMic\b/i, '麦克风'],
    [/\bSpeakers\b/i, '扬声器'],
    [/\bSpeaker\b/i, '扬声器'],
    [/\bBluetooth\b/i, '蓝牙'],
    [/\bHeadphones\b/i, '耳机'],
  ];

  function localizeDeviceLabel(label) {
    if (!label) return label;
    let s = label;
    for (const [re, zh] of DEVICE_LABEL_MAP) s = s.replace(re, zh);
    return s;
  }

  // window in browser/jsdom; globalThis fallback keeps a bare-node import safe.
  const root = typeof window !== 'undefined' ? window : globalThis;
  root.JoyI18n = { localizeDeviceLabel, DEVICE_LABEL_MAP };
})();
