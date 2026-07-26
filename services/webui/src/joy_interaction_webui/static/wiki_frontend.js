'use strict';

// wiki_frontend.js — [Local Wiki] frontend tasks F1-F4 (ADR-0012 §7.3)
// Exposes window.JoyWiki so index.html can wire the Settings (F1/F2/F3) and
// Knowledge Base (F4) UI. All calls hit the webui gateway's /v1/* contract:
//   GET  /v1/providers/health     (B3)
//   GET/PUT /v1/settings/network   (B4)
//   GET  /v1/namespaces            (F4 list)
//   POST /v1/external/sync         (F4 folder sync)
//   POST /v1/external/ingest-text  (F4 pasted markdown)
//   DELETE /v1/namespaces/{ns}     (F4 delete)
(function () {
  async function apiJson(method, path, body) {
    const opts = { method: method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    let data = null;
    try {
      data = await resp.json();
    } catch (_e) {
      /* non-JSON response */
    }
    if (!resp.ok) {
      const msg = (data && (data.error || data.detail)) || ('HTTP ' + resp.status);
      throw new Error(msg);
    }
    return data;
  }

  function setStatusDot(provider, ok, meta) {
    const dot = document.getElementById('status-' + provider);
    const metaEl = document.getElementById('meta-' + provider);
    if (dot) {
      dot.classList.remove('ok', 'err', 'pending');
      dot.classList.add(ok === null ? 'pending' : ok ? 'ok' : 'err');
    }
    if (metaEl) metaEl.textContent = meta || '--';
  }

  // ---- F2: API status panel ----
  async function loadHealth() {
    ['main_llm', 'summarizer', 'embedding', 'memory_store', 'tts'].forEach(function (p) {
      setStatusDot(p, null, '...');
    });
    try {
      const data = await apiJson('GET', '/v1/providers/health');
      const map = {
        main_llm: data.main_llm,
        summarizer: data.summarizer,
        embedding: data.embedding,
        memory_store: data.memory_store,
        tts: data.tts,
      };
      Object.keys(map).forEach(function (p) {
        const item = map[p] || {};
        const lat = item.latency_ms != null ? item.latency_ms + 'ms' : '';
        const meta = [item.provider, lat, item.reason].filter(Boolean).join(' · ') || (item.ok ? 'ok' : 'down');
        setStatusDot(p, item.ok, meta);
      });
    } catch (_e) {
      ['main_llm', 'summarizer', 'embedding', 'memory_store', 'tts'].forEach(function (p) {
        setStatusDot(p, false, String(_e.message || _e).slice(0, 60));
      });
    }
  }

  // ---- F1/F3: Network proxy settings ----
  async function loadNetwork() {
    try {
      const data = await apiJson('GET', '/v1/settings/network');
      const proxy = (data && data.proxy) || {};
      const enabled = document.getElementById('proxyEnabledToggle');
      const host = document.getElementById('proxyHost');
      const port = document.getElementById('proxyPort');
      if (enabled) enabled.checked = !!proxy.enabled;
      if (host) {
        const url = proxy.url || '';
        const m = url.match(/:\/\/([^:/]+)(?::(\d+))?/);
        host.value = m ? m[1] : '';
        if (port && m && m[2]) port.value = m[2];
      }
    } catch (_e) {
      const st = document.getElementById('proxyStatus');
      if (st) st.textContent = 'Failed to load network settings: ' + _e.message;
    }
  }

  function buildProxyUrl() {
    const host = (document.getElementById('proxyHost') || {}).value || '127.0.0.1';
    const port = (document.getElementById('proxyPort') || {}).value || '7890';
    return 'http://' + host + ':' + port;
  }

  async function testConnection() {
    const st = document.getElementById('proxyStatus');
    if (st) st.textContent = 'Probing providers...';
    await loadHealth();
    if (st) st.textContent = 'Probe complete (v1 traffic stays direct per ADR-0012 §4).';
  }

  // F3: optimistic save -> PUT /v1/settings/network
  async function saveNetwork() {
    const st = document.getElementById('proxyStatus');
    const enabled = document.getElementById('proxyEnabledToggle');
    const payload = {
      proxy: {
        enabled: !!(enabled && enabled.checked),
        url: buildProxyUrl(),
      },
      providers: { siliconflow: { use_proxy: !!(enabled && enabled.checked) } },
    };
    // optimistic: reflect immediately
    if (st) {
      st.textContent = 'Saving...';
      st.style.color = '';
    }
    try {
      await apiJson('PUT', '/v1/settings/network', payload);
      if (st) st.textContent = 'Saved. Health re-tested below.';
      await loadHealth();
    } catch (_e) {
      if (st) {
        st.textContent = 'Save failed: ' + _e.message;
        st.style.color = 'var(--warning-color)';
      }
    }
  }

  // ---- F4: Knowledge Base page ----
  async function loadNamespaces() {
    const list = document.getElementById('namespaceList');
    const empty = document.getElementById('namespaceEmpty');
    if (!list) return;
    list.innerHTML = '<div class="input-hint">Loading…</div>';
    try {
      const data = await apiJson('GET', '/v1/namespaces');
      const ns = (data && data.namespaces) || [];
      if (!ns.length) {
        list.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
      }
      if (empty) empty.style.display = 'none';
      list.innerHTML = '';
      ns.forEach(function (item) {
        const row = document.createElement('div');
        row.className = 'namespace-row';
        const label = document.createElement('div');
        label.className = 'namespace-info';
        const name = document.createElement('div');
        name.className = 'namespace-name';
        name.textContent = item.namespace;
        const sub = document.createElement('div');
        sub.className = 'namespace-sub';
        sub.textContent = (item.blocks || 0) + ' blocks · ' + (item.indexed || 0) + ' indexed';
        label.appendChild(name);
        label.appendChild(sub);
        const del = document.createElement('button');
        del.className = 'icon-btn namespace-del';
        del.type = 'button';
        del.title = 'Delete ' + item.namespace;
        del.setAttribute('aria-label', 'Delete ' + item.namespace);
        del.innerHTML = '<i data-lucide="trash-2"></i>';
        del.addEventListener('click', function () {
          deleteNamespace(item.namespace);
        });
        row.appendChild(label);
        row.appendChild(del);
        list.appendChild(row);
      });
      if (window.lucide && window.lucide.createIcons) window.lucide.createIcons();
    } catch (_e) {
      list.innerHTML = '<div class="input-hint" style="color: var(--warning-color);">Failed to load: ' + (_e.message || _e) + '</div>';
    }
  }

  async function syncWiki() {
    const st = document.getElementById('wikiStatus');
    const path = (document.getElementById('wikiSyncPath') || {}).value || '';
    const ns = path.split(/[\\/]/).pop().replace(/^wiki[\\/]?/, '') || '';
    const drop = document.getElementById('wikiDropFirst');
    if (!path) {
      if (st) st.textContent = 'Enter a wiki/<game> folder path first.';
      return;
    }
    if (st) st.textContent = 'Syncing ' + ns + ' ...';
    try {
      const data = await apiJson('POST', '/v1/external/sync', {
        namespace: ns,
        dir: path,
        drop_first: !!(drop && drop.checked),
      });
      if (st) st.textContent = 'Synced ' + ns + ': ' + (data.chunks || 0) + ' chunks, ' + (data.embedded || 0) + ' embedded' + (data.errors && data.errors.length ? (', ' + data.errors.length + ' errors') : '');
      await loadNamespaces();
    } catch (_e) {
      if (st) st.textContent = 'Sync failed: ' + _e.message;
    }
  }

  async function pasteWiki() {
    const st = document.getElementById('wikiStatus');
    const ns = (document.getElementById('wikiNamespace') || {}).value || '';
    const text = (document.getElementById('wikiPaste') || {}).value || '';
    if (!ns || !text.trim()) {
      if (st) st.textContent = 'Provide both a namespace (game) and markdown text.';
      return;
    }
    if (st) st.textContent = 'Ingesting ' + ns + ' ...';
    try {
      const data = await apiJson('POST', '/v1/external/ingest-text', {
        namespace: ns,
        text: text,
      });
      if (st) st.textContent = 'Ingested ' + ns + ': ' + (data.chunks || 0) + ' chunks, ' + (data.embedded || 0) + ' embedded';
      const ta = document.getElementById('wikiPaste');
      if (ta) ta.value = '';
      await loadNamespaces();
    } catch (_e) {
      if (st) st.textContent = 'Ingest failed: ' + _e.message;
    }
  }

  async function deleteNamespace(ns) {
    if (!confirm('Delete knowledge base \'' + ns + '\'? This removes all its blocks and the vector index.')) {
      return;
    }
    const st = document.getElementById('wikiStatus');
    if (st) st.textContent = 'Deleting ' + ns + ' ...';
    try {
      const data = await apiJson('DELETE', '/v1/namespaces/' + encodeURIComponent(ns));
      if (st) st.textContent = 'Deleted ' + ns + ': ' + (data.deleted_rows || 0) + ' rows removed';
      await loadNamespaces();
    } catch (_e) {
      if (st) st.textContent = 'Delete failed: ' + _e.message;
    }
  }

  function bind() {
    const refresh = document.getElementById('apiStatusRefresh');
    if (refresh) refresh.addEventListener('click', loadHealth);
    const test = document.getElementById('proxyTestBtn');
    if (test) test.addEventListener('click', testConnection);
    const save = document.getElementById('proxySaveBtn');
    if (save) save.addEventListener('click', saveNetwork);
    const sync = document.getElementById('wikiSyncBtn');
    if (sync) sync.addEventListener('click', syncWiki);
    const paste = document.getElementById('wikiPasteBtn');
    if (paste) paste.addEventListener('click', pasteWiki);
  }

  // Bind after DOM ready (script is loaded at end of body, so DOM exists).
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }

  window.JoyWiki = {
    loadHealth: loadHealth,
    loadNetwork: loadNetwork,
    saveNetwork: saveNetwork,
    testConnection: testConnection,
    loadNamespaces: loadNamespaces,
    syncWiki: syncWiki,
    pasteWiki: pasteWiki,
    deleteNamespace: deleteNamespace,
  };
})();
