'use strict';

// render_markdown.js
// Markdown / static-text rendering helpers extracted from index.html.
//
// Public API (attached to window.JoyRender for non-module usage):
//   escapeHtml(text)                 -> string  (text -> HTML-escaped string)
//   decodeHtmlEntities(text)         -> string  (HTML entities -> raw text)
//   protectMarkdownCodeSpans(text)   -> { text, placeholders }
//   restoreMarkdownCodeSpans(text,p) -> string
//   renderMathToHtml(math, display)  -> string  (KaTeX -> HTML, with fallback)
//   renderMarkdownMath(text)         -> string  ($-delimited math -> HTML)
//   renderMarkdown(text)             -> string  (sanitized Markdown -> HTML)
//   openLinksInNewTabs(html)         -> string  (forces target=_blank+rel)
//
// Depends ONLY on CDN globals (marked, DOMPurify, katex) plus `document`.
// Does NOT touch any inline-script closure variable (markdownEnabled,
// resultText, markdownIcon, markdownText, ...); updateMarkdownToggleUI stays
// inline because it binds those closure vars and the live UI toggle.
//
// Loaded via <script src="./render_markdown.js"></script> in index.html <head>,
// before the main inline script, so window.JoyRender is ready by DOMContentLoaded.
//
// v1.0: extracted from the inline markdown cluster (escapeHtml ... openLinksInNewTabs)
//       so the index.html monolith can shrink incrementally.

(function () {
  function escapeHtml(text) {
    const element = document.createElement('div');
    element.textContent = String(text || '');
    return element.innerHTML;
  }

  function decodeHtmlEntities(text) {
    const element = document.createElement('textarea');
    element.innerHTML = String(text || '');
    return element.value;
  }

  function protectMarkdownCodeSpans(text) {
    const placeholders = [];
    const store = (value) => {
      const token = `@@LIVE_VLM_CODE_${placeholders.length}@@`;
      placeholders.push({ token, value });
      return token;
    };
    const protectedText = String(text || '')
      .replace(/```[\s\S]*?(?:```|$)/g, store)
      .replace(/`[^`\n]+`/g, store);
    return { text: protectedText, placeholders };
  }

  function restoreMarkdownCodeSpans(text, placeholders) {
    let restored = String(text || '');
    placeholders.forEach(({ token, value }) => {
      restored = restored.split(token).join(value);
    });
    return restored;
  }

  function renderMathToHtml(math, displayMode) {
    const source = String(math || '').trim();
    if (!source) return '';
    if (typeof katex === 'undefined' || typeof katex.renderToString !== 'function') {
      return displayMode
        ? `<div class="markdown-math-fallback">$${escapeHtml(source)}$</div>`
        : `<span class="markdown-math-fallback">$${escapeHtml(source)}$</span>`;
    }
    try {
      return katex.renderToString(source, {
        displayMode,
        throwOnError: false,
        strict: 'ignore',
        trust: false,
        output: 'html'
      });
    } catch (error) {
      console.warn('Error rendering LaTeX:', error);
      return displayMode
        ? `<div class="markdown-math-fallback">$${escapeHtml(source)}$</div>`
        : `<span class="markdown-math-fallback">$${escapeHtml(source)}$</span>`;
    }
  }

  function renderMarkdownMath(text) {
    const protectedParts = protectMarkdownCodeSpans(text);
    let source = protectedParts.text;

    source = source.replace(/\$\$([\s\S]+?)\$\$/g, (_match, math) => {
      return renderMathToHtml(math, true);
    });
    source = source.replace(/\\\[([\s\S]+?)\\\]/g, (_match, math) => {
      return renderMathToHtml(math, true);
    });
    source = source.replace(/\\\(([\s\S]+?)\\\)/g, (_match, math) => {
      return renderMathToHtml(math, false);
    });
    source = source.replace(/(^|[^\w\\])\$([^\n$]+?)\$(?!\w)/g, (match, prefix, math) => {
      const trimmed = String(math || '').trim();
      if (!trimmed) return match;
      return `${prefix}${renderMathToHtml(trimmed, false)}`;
    });

    return restoreMarkdownCodeSpans(source, protectedParts.placeholders);
  }

  // Markdown rendering function
  function renderMarkdown(text) {
    if (!text) return '';
    const rawText = String(text);
    // Check if libraries are loaded
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
      console.warn('Markdown libraries not loaded, falling back to plain text');
      return escapeHtml(rawText);
    }
    try {
      text = renderMarkdownMath(text);
      // Configure marked options
      marked.setOptions({
        breaks: true,  // Convert line breaks to <br>
        gfm: true,     // GitHub Flavored Markdown
      });
      // Parse markdown and sanitize HTML
      const html = marked.parse(text);
      const sanitized = DOMPurify.sanitize(html, {
        ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'code', 'pre', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'a', 'span', 'div', 'math', 'semantics', 'annotation', 'mrow', 'mi', 'mn', 'mo', 'msup', 'msub', 'msubsup', 'mfrac', 'msqrt', 'mroot', 'mtable', 'mtr', 'mtd', 'mtext'],
        ALLOWED_ATTR: ['href', 'title', 'class', 'style', 'aria-hidden', 'xmlns', 'encoding', 'target', 'rel'],
      });
      return openLinksInNewTabs(sanitized);
    } catch (e) {
      console.error('Error rendering markdown:', e);
      return escapeHtml(rawText); // Fallback to escaped plain text on error
    }
  }

  function openLinksInNewTabs(html) {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = String(html || '');
    wrapper.querySelectorAll('a[href]').forEach((link) => {
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    });
    return wrapper.innerHTML;
  }

  window.JoyRender = {
    escapeHtml,
    decodeHtmlEntities,
    protectMarkdownCodeSpans,
    restoreMarkdownCodeSpans,
    renderMathToHtml,
    renderMarkdownMath,
    renderMarkdown,
    openLinksInNewTabs,
  };
})();
