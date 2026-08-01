import { describe, it, expect } from 'vitest';

// Side-effect import mounts window.JoyI18n (jsdom env, see vitest.config.js).
import '../src/joy_interaction_webui/static/i18n_device_label.js';

const L = () => window.JoyI18n.localizeDeviceLabel;

describe('JoyI18n.localizeDeviceLabel (device-name i18n)', () => {
  it('exposes the mapping table', () => {
    expect(Array.isArray(window.JoyI18n.DEVICE_LABEL_MAP)).toBe(true);
    expect(window.JoyI18n.DEVICE_LABEL_MAP.length).toBeGreaterThan(0);
  });

  it('maps common camera device names to Chinese', () => {
    expect(L()('OBS Virtual Camera')).toBe('OBS 虚拟摄像头');
    expect(L()('Integrated Webcam')).toBe('内置摄像头');
    expect(L()('Integrated Camera')).toBe('内置摄像头');
    expect(L()('FaceTime HD Camera')).toBe('FaceTime 高清摄像头');
    expect(L()('USB2.0 Camera')).toBe('USB 摄像头');
    expect(L()('USB Camera')).toBe('USB 摄像头');
    expect(L()('HD Webcam')).toBe('高清摄像头');
    expect(L()('Webcam')).toBe('摄像头');
    expect(L()('HD Camera')).toBe('高清摄像头');
    expect(L()('Camera')).toBe('摄像头');
  });

  it('maps common audio device names to Chinese', () => {
    expect(L()('Headset Microphone')).toBe('耳机麦克风');
    expect(L()('Headset')).toBe('耳机');
    expect(L()('Microphone')).toBe('麦克风');
    expect(L()('Mic')).toBe('麦克风');
    expect(L()('Speakers')).toBe('扬声器');
    expect(L()('Speaker')).toBe('扬声器');
    expect(L()('Bluetooth')).toBe('蓝牙');
    expect(L()('Headphones')).toBe('耳机');
  });

  it('most-specific rule wins over generic substring', () => {
    // "Integrated Webcam" -> 内置摄像头, NOT "Integrated 摄像头"
    expect(L()('Integrated Webcam')).toBe('内置摄像头');
    // "USB2.0 Camera" -> USB 摄像头 (not just 摄像头 from generic Camera)
    expect(L()('USB2.0 Camera')).toBe('USB 摄像头');
    // "FaceTime HD Camera" -> FaceTime 高清摄像头 (not overridden by 摄像头)
    expect(L()('FaceTime HD Camera')).toBe('FaceTime 高清摄像头');
  });

  it('passes through unknown labels unchanged (no mistranslation)', () => {
    expect(L()('Logitech BRIO')).toBe('Logitech BRIO');
    expect(L()('Some Random Device 123')).toBe('Some Random Device 123');
  });

  it('does not double-translate already-Chinese labels', () => {
    expect(L()('OBS 虚拟摄像头')).toBe('OBS 虚拟摄像头');
    expect(L()('内置摄像头')).toBe('内置摄像头');
    expect(L()('USB 摄像头')).toBe('USB 摄像头');
  });

  it('returns empty / falsy input unchanged', () => {
    expect(L()('')).toBe('');
    expect(L()(null)).toBe(null);
    expect(L()(undefined)).toBe(undefined);
  });

  it('composes multiple keywords in one label', () => {
    expect(L()('Bluetooth Headset')).toBe('蓝牙 耳机');
  });
});
