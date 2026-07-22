'use strict';

// sanitize_static_html.js
// Static-HTML sanitizers extracted from index.html (background HTML preview / ASR).
//
// Public API (attached to window.JoySanitize for non-module usage):
//   completeStaticHtmlDocument(value)              -> string
//   sanitizeStaticHtml(html)                       -> string  (DOMPurify + node walker)
//   normalizeStaticHtmlDocument(html, tags, attrs) -> string
//   sanitizeStaticHtmlFallback(html, tags, attrs)  -> string
//   makeStaticHtmlNodeCleaner(doc, tags, attrs)    -> (node) => Node|null
//   isSafeStaticUrl(url)                           -> boolean
//   sanitizeStaticCss(css)                         -> string
//
// Depends on:
//   - window.JoyRender.escapeHtml  (from render_markdown.js; referenced lazily)
//   - DOMPurify                     (CDN global)
//   - DOMParser / document / Node   (browser globals)
// Does NOT touch any inline-script closure variable.
//
// Loaded via <script src="./sanitize_static_html.js"></script> in index.html <head>,
// AFTER render_markdown.js, so window.JoyRender is ready.
//
// v1.0: extracted from the inline static-HTML sanitizer cluster
//       (completeStaticHtmlDocument ... sanitizeStaticCss) so the monolith shrinks.

(function () {
  function completeStaticHtmlDocument(value) {
    let html = String(value || '').trim();
    if (!html) return '';

    if (/<style\b[^>]*>/i.test(html) && !/<\/style\s*>/i.test(html)) {
      html += '\n</style>';
    }
    if (/<head\b[^>]*>/i.test(html) && !/<\/head\s*>/i.test(html)) {
      html += '\n</head>';
    }
    if (!/<body\b/i.test(html)) {
      html += '\n<body><main style="min-height:100vh;display:grid;place-items:center;font-family:sans-serif;color:#333;background:#f7f7f7;">HTML 内容可能被截断，只有样式片段可预览。</main>';
    }
    if (/<body\b[^>]*>/i.test(html) && !/<\/body\s*>/i.test(html)) {
      html += '\n</body>';
    }
    if (/<html\b[^>]*>/i.test(html) && !/<\/html\s*>/i.test(html)) {
      html += '\n</html>';
    }
    if (!/<html\b/i.test(html)) {
      html = `<!doctype html>\n<html><head><meta charset="UTF-8"></head><body>${html}</body></html>`;
    }
    return html;
  }

  function sanitizeStaticHtml(html) {
    if (!html) return '';
    const rawHtml = String(html);
    const allowedTags = [
      'html', 'head', 'body', 'title', 'style',
      'main', 'header', 'footer', 'nav', 'section', 'article', 'aside',
      'div', 'span', 'p', 'br', 'strong', 'em', 'b', 'i', 'u', 'small',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'dl', 'dt', 'dd',
      'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption',
      'pre', 'code', 'blockquote', 'hr',
      'a', 'img', 'figure', 'figcaption', 'button'
    ];
    const allowedAttrs = [
      'class', 'id', 'style', 'title', 'role', 'aria-label',
      'href', 'src', 'alt', 'width', 'height', 'colspan', 'rowspan'
    ];

    if (typeof DOMPurify !== 'undefined') {
      const cleaned = DOMPurify.sanitize(rawHtml, {
        WHOLE_DOCUMENT: true,
        ALLOWED_TAGS: allowedTags,
        ALLOWED_ATTR: allowedAttrs,
        ALLOW_DATA_ATTR: false,
        ALLOW_ARIA_ATTR: true,
        ALLOWED_URI_REGEXP: /^(?:#|data:image\/(?:png|jpe?g|gif|webp);base64,)/i,
        FORBID_TAGS: ['script', 'form', 'input', 'textarea', 'select', 'option', 'iframe', 'object', 'embed', 'link', 'meta', 'base', 'svg', 'math']
      });
      return normalizeStaticHtmlDocument(cleaned, allowedTags, allowedAttrs);
    }

    return sanitizeStaticHtmlFallback(rawHtml, allowedTags, allowedAttrs);
  }

  function normalizeStaticHtmlDocument(html, allowedTags, allowedAttrs) {
    if (typeof DOMParser === 'undefined') {
      return window.JoyRender.escapeHtml(html);
    }
    const parser = new DOMParser();
    const source = parser.parseFromString(String(html || ''), 'text/html');
    const cleanDoc = document.implementation.createHTMLDocument('');
    const cleanNode = makeStaticHtmlNodeCleaner(cleanDoc, allowedTags, allowedAttrs);

    Array.from(source.head.childNodes).forEach((child) => {
      const cleaned = cleanNode(child);
      if (cleaned) cleanDoc.head.appendChild(cleaned);
    });
    Array.from(source.body.childNodes).forEach((child) => {
      const cleaned = cleanNode(child);
      if (cleaned) cleanDoc.body.appendChild(cleaned);
    });

    return '<!doctype html>\n' + cleanDoc.documentElement.outerHTML;
  }

  function sanitizeStaticHtmlFallback(html, allowedTags, allowedAttrs) {
    if (typeof DOMParser === 'undefined') {
      return window.JoyRender.escapeHtml(html);
    }
    return normalizeStaticHtmlDocument(html, allowedTags, allowedAttrs);
  }

  function makeStaticHtmlNodeCleaner(cleanDoc, allowedTags, allowedAttrs) {
    const tagSet = new Set(allowedTags);
    const attrSet = new Set(allowedAttrs);
    const dropTags = new Set(['script', 'form', 'input', 'textarea', 'select', 'option', 'iframe', 'object', 'embed', 'link', 'meta', 'base', 'svg', 'math']);

    const cleanNode = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        return cleanDoc.createTextNode(node.textContent || '');
      }
      if (node.nodeType !== Node.ELEMENT_NODE) {
        return null;
      }

      const tagName = node.tagName.toLowerCase();
      if (dropTags.has(tagName)) {
        return null;
      }
      if (!tagSet.has(tagName)) {
        const fragment = cleanDoc.createDocumentFragment();
        Array.from(node.childNodes).forEach((child) => {
          const cleanedChild = cleanNode(child);
          if (cleanedChild) fragment.appendChild(cleanedChild);
        });
        return fragment;
      }

      const element = cleanDoc.createElement(tagName);
      Array.from(node.attributes || []).forEach((attr) => {
        const attrName = attr.name.toLowerCase();
        if (!attrSet.has(attrName) || attrName.startsWith('on')) {
          return;
        }
        if (tagName === 'a' && attrName === 'href') {
          return;
        }
        if (attrName === 'src' && !isSafeStaticUrl(attr.value)) {
          return;
        }
        if (attrName === 'style') {
          element.setAttribute(attrName, sanitizeStaticCss(attr.value));
          return;
        }
        element.setAttribute(attrName, attr.value);
      });

      Array.from(node.childNodes).forEach((child) => {
        const cleanedChild = cleanNode(child);
        if (cleanedChild) element.appendChild(cleanedChild);
      });

      if (tagName === 'style') {
        element.textContent = sanitizeStaticCss(node.textContent || '');
      }
      if (tagName === 'a') {
        element.setAttribute('data-static-link', 'true');
        element.setAttribute('tabindex', '-1');
      }
      if (tagName === 'button') {
        element.setAttribute('type', 'button');
      }
      return element;
    };

    return cleanNode;
  }

  function isSafeStaticUrl(url) {
    const value = String(url || '').trim();
    return !value || value.startsWith('#') || /^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(value);
  }

  function sanitizeStaticCss(css) {
    return String(css || '')
      .replace(/@import\b[^;]+;?/gi, '')
      .replace(/javascript:/gi, '')
      .replace(/expression\s*\(/gi, '')
      .replace(/url\s*\(\s*(['"]?)(?!data:image\/(?:png|jpe?g|gif|webp);base64,)[^)]+\)/gi, 'none');
  }

  window.JoySanitize = {
    completeStaticHtmlDocument,
    sanitizeStaticHtml,
    normalizeStaticHtmlDocument,
    sanitizeStaticHtmlFallback,
    makeStaticHtmlNodeCleaner,
    isSafeStaticUrl,
    sanitizeStaticCss,
  };
})();
