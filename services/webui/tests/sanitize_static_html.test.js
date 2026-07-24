import { describe, it, expect, afterEach, vi } from 'vitest';

// JoyRender is referenced lazily by the fallback path; load it first.
import '../src/joy_interaction_webui/static/render_markdown.js';
// Side-effect import: mounts window.JoySanitize
import '../src/joy_interaction_webui/static/sanitize_static_html.js';

describe('JoySanitize (static-HTML sanitizers)', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('isSafeStaticUrl accepts empty, anchor, and data:image', () => {
    expect(window.JoySanitize.isSafeStaticUrl('')).toBe(true);
    expect(window.JoySanitize.isSafeStaticUrl('   ')).toBe(true);
    expect(window.JoySanitize.isSafeStaticUrl('#top')).toBe(true);
    expect(window.JoySanitize.isSafeStaticUrl('data:image/png;base64,AAAA')).toBe(true);
  });

  it('isSafeStaticUrl rejects remote http and javascript:', () => {
    expect(window.JoySanitize.isSafeStaticUrl('http://evil.com/a.png')).toBe(false);
    expect(window.JoySanitize.isSafeStaticUrl('javascript:alert(1)')).toBe(false);
  });

  it('sanitizeStaticCss strips @import, expression, javascript:, and external url()', () => {
    const out = window.JoySanitize.sanitizeStaticCss(
      "div{background:url(http://x.com/a.png);@import 'evil.css';behavior:expression(alert(1));x:javascript:alert(1)}"
    );
    expect(out).not.toContain('http://x.com');
    expect(out).not.toContain('@import');
    expect(out).not.toContain('expression(');
    expect(out).not.toContain('javascript:');
    expect(out).toContain('none'); // external url() replaced with none
  });

  it('completeStaticHtmlDocument returns empty for empty input', () => {
    expect(window.JoySanitize.completeStaticHtmlDocument('')).toBe('');
  });

  it('completeStaticHtmlDocument wraps a fragment in a full document', () => {
    const out = window.JoySanitize.completeStaticHtmlDocument('<p>hi</p>');
    expect(out).toContain('<!doctype html>');
    expect(out).toContain('<body>');
    expect(out).toContain('<p>hi</p>');
  });

  it('sanitizeStaticHtml (fallback, no DOMPurify) drops script, on* attrs, and unsafe href', () => {
    const out = window.JoySanitize.sanitizeStaticHtml(
      '<p>ok</p><script>alert(1)</script><div onclick="x()">a</div><a href="http://e.com">bad</a>'
    );
    expect(out).not.toContain('<script>');
    expect(out).not.toContain('onclick');
    expect(out).not.toContain('http://e.com');
    // safe anchor element is preserved and marked as a static link
    expect(out).toContain('data-static-link');
  });
});
