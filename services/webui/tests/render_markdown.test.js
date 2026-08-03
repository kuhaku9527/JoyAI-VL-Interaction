import { describe, it, expect, afterEach, vi } from 'vitest';

// Side-effect import: mounts window.JoyRender
import '../src/joy_interaction_webui/static/render_markdown.js';

describe('JoyRender (markdown / static-text rendering)', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('escapeHtml escapes angle brackets and ampersands', () => {
    expect(window.JoyRender.escapeHtml('<script>alert(1)</script>'))
      .toBe('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(window.JoyRender.escapeHtml('a & b')).toBe('a &amp; b');
  });

  it('renderMarkdown falls back to escaped text when libs are missing (XSS guard)', () => {
    const out = window.JoyRender.renderMarkdown('<b>hi</b>');
    expect(out).toContain('&lt;b&gt;');
    expect(out).not.toContain('<b>');
  });

  it('renderMarkdown with libs sanitizes and forces target=_blank on links', () => {
    vi.stubGlobal('marked', { setOptions: vi.fn(), parse: () => '<a href="http://e.com">link</a>' });
    vi.stubGlobal('DOMPurify', { sanitize: (h) => h });
    const out = window.JoyRender.renderMarkdown('see [link](http://e.com)');
    expect(marked.setOptions).toHaveBeenCalled();
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
  });

  it('openLinksInNewTabs adds target=_blank and rel to anchors', () => {
    const out = window.JoyRender.openLinksInNewTabs('<a href="http://x.com">x</a>');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
  });

  it('renderMathToHtml falls back to a safe span when katex is missing', () => {
    const out = window.JoyRender.renderMathToHtml('E=mc^2', true);
    expect(out).toContain('markdown-math-fallback');
    expect(out).toContain('E=mc^2');
  });

  it('decodeHtmlEntities decodes basic entities', () => {
    expect(window.JoyRender.decodeHtmlEntities('a &amp; b')).toBe('a & b');
  });

  it('renderMarkdownMath keeps inline code spans intact', () => {
    const out = window.JoyRender.renderMarkdownMath('use `code` and text');
    expect(out).toContain('code');
  });

  it('renderMarkdown does NOT revive decision tokens as escaped visible text', () => {
    // Regression for issue #44: the old code escaped </silence>/<response> into
    // &lt;/silence&gt; etc., which re-exposed model decision tokens to the user.
    // With libs stubbed, the raw token must never appear as an escaped entity.
    vi.stubGlobal('marked', { setOptions: vi.fn(), parse: (s) => s });
    vi.stubGlobal('DOMPurify', { sanitize: (h) => h });
    const out = window.JoyRender.renderMarkdown('</silence> hello </response> world');
    expect(out).not.toContain('&lt;');
    expect(out).not.toContain('&gt;');
  });
});
