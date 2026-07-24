import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Side-effect import: mounts window.JoyConfig
import '../src/joy_interaction_webui/static/config_services.js';

const BADGE_IDS = ['llm', 'summary', 'tts', 'asr'].map((s) => `badge-${s}`);
const FIELD_IDS = [
  'svc-llm-api-base', 'svc-llm-model', 'svc-llm-api-key',
  'svc-summary-api-base', 'svc-summary-model',
  'svc-tts-api-base', 'svc-asr-api-base', 'svc-asr-model',
];

describe('JoyConfig (services panel config/API form cluster)', () => {
  let fetchMock;

  beforeEach(() => {
    document.body.innerHTML =
      BADGE_IDS.map((id) => `<span id="${id}"></span>`).join('') +
      FIELD_IDS.map((id) => `<input id="${id}" value="">`).join('');
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('readForm reads values from the DOM', () => {
    document.getElementById('svc-llm-api-base').value = 'http://llm';
    document.getElementById('svc-llm-model').value = 'gpt';
    document.getElementById('svc-llm-api-key').value = 'k';
    const cfg = window.JoyConfig.readForm();
    expect(cfg.llm.api_base).toBe('http://llm');
    expect(cfg.llm.model).toBe('gpt');
    expect(cfg.llm.api_key).toBe('k');
  });

  it('writeForm writes values back to the DOM', () => {
    window.JoyConfig.writeForm({
      llm: { api_base: 'u', model: 'm', api_key: 'k' },
      summary: { api_base: 's', model: 'sm' },
      tts: { api_base: 't' },
      asr: { api_base: 'a', model: 'am' },
    });
    expect(document.getElementById('svc-llm-api-base').value).toBe('u');
    expect(document.getElementById('svc-llm-model').value).toBe('m');
    expect(document.getElementById('svc-asr-model').value).toBe('am');
  });

  it('setBadge OK sets the ok class', () => {
    window.JoyConfig.setBadge('llm', 'OK');
    const b = document.getElementById('badge-llm');
    expect(b.textContent).toBe('OK');
    expect(b.className).toContain('ok');
  });

  it('setBadge ERR sets the err class and a title hint', () => {
    window.JoyConfig.setBadge('tts', 'ERR', 'down');
    const b = document.getElementById('badge-tts');
    expect(b.className).toContain('err');
    expect(b.title).toBe('down');
  });

  it('save PUTs the config to /api/services/config', async () => {
    document.getElementById('svc-llm-api-base').value = 'http://llm';
    await window.JoyConfig.save();
    const configCall = fetchMock.mock.calls.find((c) => c[0] === '/api/services/config');
    expect(configCall).toBeTruthy();
    expect(configCall[1].method).toBe('PUT');
    const body = JSON.parse(configCall[1].body);
    expect(body.llm.api_base).toBe('http://llm');
  });
});
