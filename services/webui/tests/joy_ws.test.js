import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Side-effect import: the IIFE mounts window.JoyWs
import '../src/joy_interaction_webui/static/joy_ws.js';

class FakeWebSocket {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.sent = [];
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    FakeWebSocket.last = this;
  }
  send(data) { this.sent.push(data); }
  close() {}
}

describe('JoyWs (WebSocket / API-settings session cluster)', () => {
  let ctx;
  let currentWs;
  let updateStatus;
  let fetchMock;

  beforeEach(() => {
    currentWs = null;
    updateStatus = vi.fn();
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.stubGlobal('fetch', fetchMock);
    ctx = {
      getWebSocket: () => currentWs,
      setWebSocket: (ws) => { currentWs = ws; },
      getSessionId: () => 'sess-1',
      installLlmReplyHandler: vi.fn(),
      updateStatus,
      modelSelect: { value: 'model-x' },
      isValidModelName: (m) => !!m,
      dispatchServerMessage: vi.fn(),
      apiBaseUrl: { value: 'http://api' },
      apiKey: { value: 'key' },
      fetchModels: vi.fn(),
    };
    window.JoyWs.register(ctx);
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('connectWebSocket creates a ws, installs handler, and reports Connected on open', () => {
    window.JoyWs.connectWebSocket();
    expect(currentWs).toBeInstanceOf(FakeWebSocket);
    expect(currentWs.url).toContain('/ws?session_id=');
    expect(ctx.installLlmReplyHandler).toHaveBeenCalledWith(currentWs);
    // simulate successful open (mark OPEN so applyApiSettings will send)
    currentWs.readyState = FakeWebSocket.OPEN;
    currentWs.onopen();
    expect(updateStatus).toHaveBeenCalledWith('Connected', 'connected');
    expect(currentWs.sent.length).toBeGreaterThan(0);
    const msg = JSON.parse(currentWs.sent[0]);
    expect(msg.type).toBe('update_model');
  });

  it('connectWebSocket is a no-op when a ws is already OPEN', () => {
    currentWs = new FakeWebSocket('ws://x');
    currentWs.readyState = FakeWebSocket.OPEN;
    window.JoyWs.connectWebSocket();
    expect(FakeWebSocket.last).toBe(currentWs); // no new instance created
  });

  it('applyApiSettings sends update_model over an OPEN ws', () => {
    currentWs = new FakeWebSocket('ws://x');
    currentWs.readyState = FakeWebSocket.OPEN;
    window.JoyWs.applyApiSettings({ showFeedback: true });
    expect(currentWs.sent.length).toBe(1);
    const msg = JSON.parse(currentWs.sent[0]);
    expect(msg.type).toBe('update_model');
    expect(msg.model).toBe('model-x');
    expect(updateStatus).toHaveBeenCalledWith('API settings updated', 'connected');
  });

  it('applyApiSettings is a no-op without an API base', () => {
    ctx.apiBaseUrl.value = '';
    currentWs = new FakeWebSocket('ws://x');
    currentWs.readyState = FakeWebSocket.OPEN;
    window.JoyWs.applyApiSettings({});
    expect(currentWs.sent.length).toBe(0);
  });

  it('applyApiSettings is a no-op with an invalid model name', () => {
    ctx.modelSelect.value = '';
    ctx.isValidModelName = () => false;
    currentWs = new FakeWebSocket('ws://x');
    currentWs.readyState = FakeWebSocket.OPEN;
    window.JoyWs.applyApiSettings({});
    expect(currentWs.sent.length).toBe(0);
  });

  it('cleanupServerSession POSTs to /api/session/cleanup', async () => {
    await window.JoyWs.cleanupServerSession('sid-9');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/session/cleanup');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body);
    expect(body.session_id).toBe('sid-9');
    expect(body.reset_adapter).toBe(true);
  });

  it('cleanupServerSession is a no-op without a session id', async () => {
    await window.JoyWs.cleanupServerSession();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
