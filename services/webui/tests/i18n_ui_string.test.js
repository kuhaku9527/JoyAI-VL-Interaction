import { describe, it, expect } from 'vitest';

// Side-effect import mounts window.JoyI18n (jsdom env, see vitest.config.js).
import '../src/joy_interaction_webui/static/i18n_device_label.js';

const U = () => window.JoyI18n.localizeUiString;

describe('JoyI18n.localizeUiString (key-panel UI i18n, issue #47)', () => {
  it('exposes the UI mapping table and helpers', () => {
    expect(Array.isArray(window.JoyI18n.UI_STRING_MAP)).toBe(true);
    expect(window.JoyI18n.UI_STRING_MAP.length).toBeGreaterThan(0);
    expect(typeof window.JoyI18n.localizeUiString).toBe('function');
    expect(typeof window.JoyI18n.applyUiI18n).toBe('function');
  });

  it('maps common key-panel strings to Chinese', () => {
    expect(U()('Streaming')).toBe('直播中');
    expect(U()('Connected')).toBe('已连接');
    expect(U()('Disconnected')).toBe('未连接');
    expect(U()('Idle')).toBe('空闲');
    expect(U()('Video Source')).toBe('视频源');
    expect(U()('Services')).toBe('服务');
    expect(U()('Knowledge Base')).toBe('知识库');
    expect(U()('Camera Selection')).toBe('摄像头选择');
    expect(U()('Processing Interval')).toBe('处理间隔');
    expect(U()('Frames per Batch')).toBe('每批帧数');
    expect(U()('API Base URL')).toBe('API 基础地址');
    expect(U()('API Key')).toBe('API 密钥');
    expect(U()('API URL')).toBe('API 地址');
    expect(U()('Model')).toBe('模型');
    expect(U()('Summary')).toBe('摘要');
    expect(U()('Summarizer')).toBe('摘要');
    expect(U()('Embedding')).toBe('嵌入');
    expect(U()('Memory Store')).toBe('记忆存储');
    expect(U()('Layout')).toBe('布局');
    expect(U()('Debug')).toBe('调试');
    expect(U()('Dark')).toBe('深色');
    expect(U()('Light')).toBe('浅色');
    expect(U()('Auto')).toBe('自动');
    expect(U()('Plain Text')).toBe('纯文本');
    expect(U()('Ready')).toBe('就绪');
    expect(U()('None')).toBe('无');
    expect(U()('At the top')).toBe('顶部');
    expect(U()('At the bottom')).toBe('底部');
  });

  it('most-specific rule wins over generic substring', () => {
    // "RTSP Stream URL" -> RTSP 流地址 (NOT "RTSP 流 URL")
    expect(U()('RTSP Stream URL')).toBe('RTSP 流地址');
    // "RTSP Stream" -> RTSP 流 (the more generic one still resolves)
    expect(U()('RTSP Stream')).toBe('RTSP 流');
    // "Camera Selection" -> 摄像头选择 (NOT "摄像头 Selection")
    expect(U()('Camera Selection')).toBe('摄像头选择');
    // "VLM Output on Camera View" -> 摄像头画面 VLM 输出 (Camera rule must not mangle)
    expect(U()('VLM Output on Camera View')).toBe('摄像头画面 VLM 输出');
    // "Delete failed: " -> 删除失败： (not partial from "Delete " / ": ")
    expect(U()('Delete failed: ')).toBe('删除失败：');
    // " chunks, " -> 个分块， (not partial from ", ")
    expect(U()(' chunks, ')).toBe(' 个分块，');
  });

  it('passes through unknown labels unchanged (no mistranslation)', () => {
    expect(U()('Some Random Panel 123')).toBe('Some Random Panel 123');
    expect(U()('WebRTC')).toBe('WebRTC');
    expect(U()('LLM')).toBe('LLM');
    expect(U()('ASR')).toBe('ASR');
  });

  it('does not double-translate already-Chinese strings', () => {
    expect(U()('视频源')).toBe('视频源');
    expect(U()('直播中')).toBe('直播中');
    expect(U()('深色')).toBe('深色');
    expect(U()('RTSP 流地址')).toBe('RTSP 流地址');
  });

  it('returns empty / falsy input unchanged', () => {
    expect(U()('')).toBe('');
    expect(U()(null)).toBe(null);
    expect(U()(undefined)).toBe(undefined);
  });

  it('composes fragments for dynamic wiki messages', () => {
    const line = U()('Synced ') + 'elden-ring' + U()(': ') + 12 + U()(' chunks, ') + 3 + U()(' embedded');
    expect(line).toBe('已同步 elden-ring：12 个分块，3 已嵌入');
    expect(U()('Delete ') + 'elden-ring').toBe('删除 elden-ring');
    expect(U()('Syncing ') + 'elden-ring' + ' ...').toBe('正在同步 elden-ring ...');
  });

  it('localizes static [data-i18n] markup via applyUiI18n', () => {
    document.body.innerHTML =
      '<span id="t" data-i18n>Video Source</span>' +
      '<span id="u">Unknown Panel</span>';
    window.JoyI18n.applyUiI18n(document);
    expect(document.getElementById('t').textContent).toBe('视频源');
    // unknown strings are left untouched (passthrough, not blanked)
    expect(document.getElementById('u').textContent).toBe('Unknown Panel');
  });

  it('localizes data-i18n-title / data-i18n-placeholder via applyUiI18n', () => {
    document.body.innerHTML =
      '<button id="b" title="Start webcam capture" data-i18n-title="Start webcam capture">x</button>' +
      '<input id="i" placeholder="optional" data-i18n-placeholder="optional">';
    window.JoyI18n.applyUiI18n(document);
    expect(document.getElementById('b').getAttribute('title')).toBe('开始摄像头采集');
    expect(document.getElementById('i').getAttribute('placeholder')).toBe('可选');
  });

  it('is idempotent (a localized string is not rematched)', () => {
    const once = U()('Video Source');
    expect(U()(once)).toBe(once);
  });
});
