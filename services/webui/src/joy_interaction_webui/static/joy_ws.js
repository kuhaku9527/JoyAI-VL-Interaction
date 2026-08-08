'use strict';

// joy_ws.js — WebSocket / API-settings session cluster
// Extracted from services/webui/src/joy_interaction_webui/static/index.html
//   Block 4: applyApiSettings (~8683-8714) + cleanupServerSession (~9180-9200)
//   Block 5: connectWebSocket (~8938-9179) — WS lifecycle + 2s reconnect
// Mounted on window.JoyWs.
//
// Why a register(ctx) bridge instead of the plain IIFE-to-window used by Blocks 1-3:
//   cleanupServerSession is pure (only fetch + console) and needs no bridge.
//   applyApiSettings and connectWebSocket read closure-local refs that are reassigned
//   at runtime — most importantly `websocket` (a `let` that connectWebSocket/resetSession
//   reassign) and `sessionId` (reassigned by the server_config message handler). Live
//   accessors (getWebSocket/setWebSocket/getSessionId) keep this module in sync with the
//   inline script's single source of truth without turning the monolith inside-out. The
//   other refs (apiBaseUrl/apiKey/modelSelect DOM nodes, isValidModelName/updateStatus/
//   fetchModels/installLlmReplyHandler) are stable, so they are passed by value once.
//
// The server→client *protocol router* (ws.onmessage) is intentionally NOT extracted: it
// reassigns monolith closure vars (sessionId, serverConfigApplied, lastText, fadeTimeout)
// and must stay the single source of truth. It lives inline as `dispatchServerMessage(event)`
// and is handed in via register({ dispatchServerMessage }); connectWebSocket wires it with
// `ws.onmessage = _ctx.dispatchServerMessage`.
//
// Call window.JoyWs.register({...}) exactly once from the inline script, after every
// referenced closure symbol is in scope (placed at the old applyApiSettings location, which
// is after all of them; dispatchServerMessage is a hoisted function declaration so it is
// available here too). connectWebSocket() is then reachable as window.JoyWs.connectWebSocket()
// and via the inline `connectWebSocket` alias kept in index.html.
(function () {

    // Populated by register() from the main inline script.
    let _ctx = null;

    function register(ctx) {
        _ctx = ctx || {};
    }

    // ---- cleanupServerSession: pure, depends only on fetch + console ----
    async function cleanupServerSession(sessionIdToCleanup) {
        if (!sessionIdToCleanup) {
            return;
        }

        try {
            const response = await fetch('/api/session/cleanup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionIdToCleanup,
                    reset_adapter: true
                })
            });
            if (!response.ok) {
                console.warn('Session cleanup failed:', response.status);
            }
        } catch (error) {
            console.warn('Session cleanup request failed:', error);
        }
    }

    // ---- applyApiSettings: needs live closure refs via _ctx ----
    function applyApiSettings(options = {}) {
        if (!_ctx) {
            console.warn('[JoyWs] applyApiSettings called before register()');
            return;
        }

        const { apiBaseUrl, apiKey, modelSelect, isValidModelName, updateStatus, fetchModels, getWebSocket } = _ctx;

        const currentApiBase = apiBaseUrl.value.trim();
        const currentApiKey = apiKey.value.trim();
        const currentModel = modelSelect.value;

        if (!currentApiBase) {
            return; // Silently skip if no API base
        }

        if (!isValidModelName(currentModel)) {
            return; // Silently skip if no model selected yet
        }

        // Live read of the closure `websocket` (reassigned by connectWebSocket/resetSession).
        const websocket = getWebSocket ? getWebSocket() : null;

        // Send update to server
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(JSON.stringify({
                type: 'update_model',
                model: currentModel,
                api_base: currentApiBase,
                api_key: currentApiKey
            }));

            if (options.showFeedback) {
                updateStatus('API settings updated', 'connected');
            }

            // Refresh models from new endpoint if requested
            if (options.refreshModels) {
                fetchModels();
            }
        }
    }

    // ---- connectWebSocket: WS lifecycle (Block 5) ----
    // Moved out of the inline monolith. The protocol router (onmessage) stays inline as
    // dispatchServerMessage (registered via _ctx); we only bridge the lifecycle + a few
    // reassigned/stable refs so this module stays the owner of connection state.
    function connectWebSocket() {
        if (!_ctx) {
            console.warn('[JoyWs] connectWebSocket called before register()');
            return;
        }

        const {
            getWebSocket, setWebSocket, getSessionId,
            installLlmReplyHandler, updateStatus,
            modelSelect, isValidModelName, dispatchServerMessage
        } = _ctx;

        const websocket = getWebSocket ? getWebSocket() : null;
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws?session_id=${encodeURIComponent(getSessionId ? getSessionId() : '')}`;

        const ws = new WebSocket(wsUrl);
        if (setWebSocket) setWebSocket(ws);
        try {
            installLlmReplyHandler(ws);
        } catch (e) {
            console.error('[ws-connect] installLlmReplyHandler failed:', e);
        }
        // Belt-and-suspenders retry if first install didn't take (doc/subsystems/jarvis-mode.md §14.4 / v3.5).
        if (!ws.__llmReplyHookInstalled) {
            try { installLlmReplyHandler(ws); } catch (e) { console.error('[ws-connect] retry installLlmReplyHandler failed:', e); }
        }

        ws.onopen = () => {
            if (getWebSocket && getWebSocket() !== ws) {
                return;
            }
            console.log('WebSocket connected');
            updateStatus('Connected', 'connected');

            // Send current model/API settings to server after WebSocket connects.
            // Fixes race condition: page load might auto-select model before WS connects.
            const currentModel = modelSelect.value;
            if (isValidModelName(currentModel)) {
                console.log('Initializing server with current model:', currentModel);
                applyApiSettings({ showFeedback: false });
            }
        };

        ws.onmessage = (typeof dispatchServerMessage === 'function')
            ? dispatchServerMessage
            : (event) => console.warn('[JoyWs] dispatchServerMessage not registered; dropping', event.data);

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        ws.onclose = () => {
            if (getWebSocket && getWebSocket() !== ws) {
                return;
            }
            console.log('WebSocket disconnected, will reconnect...');
            if (setWebSocket) setWebSocket(null);
            updateStatus('Reconnecting...', 'disconnected');
            setTimeout(connectWebSocket, 2000);
        };
    }

    // ---- Memory Store settings: embedding/provider portion of /v1/settings/network ----
    // The 4-module LLM/Summary/TTS/ASR config lives in config_services.js (window.JoyConfig).
    // The [Local Wiki] network *proxy* sub-object (proxy / providers.siliconflow) is edited by
    // wiki_frontend.js. This cluster handles the *remaining* embedding/provider part of the same
    // endpoint, which the proxy form does not surface.
    //
    // Why echo the full snapshot on save: the GET response is rendered dynamically and the proxy
    // sub-object is intentionally NOT rendered here (it has its own editor). To avoid clobbering
    // proxy when we PUT, we clone the last GET snapshot and overlay only the edited fields, then
    // PUT the whole object. This is safe whether the backend merges slots or replaces the doc.
    let _msSnapshot = null;

    // Curated embedding/provider options for <select> fields whose key looks like a provider.
    // The current value is always appended if it is not already in the list.
    const MS_PROVIDER_OPTIONS = [
        'openai', 'azure', 'local', 'huggingface', 'ollama',
        'bedrock', 'siliconflow', 'vllm', 'dashscope', 'gemini'
    ];

    function _msSetError(msg) {
        const el = document.getElementById('memoryStoreError');
        const ok = document.getElementById('memoryStoreOk');
        if (ok) ok.style.display = 'none';
        if (!el) return;
        el.textContent = msg || '';
        el.style.display = msg ? 'block' : 'none';
    }

    function _msSetOk(msg) {
        const el = document.getElementById('memoryStoreOk');
        const err = document.getElementById('memoryStoreError');
        if (err) err.style.display = 'none';
        if (!el) return;
        el.textContent = msg || '';
        el.style.display = msg ? 'block' : 'none';
    }

    // Pick an input control from the field key + value. Heuristics keep the form
    // useful without knowing the exact server schema up front.
    function _msInputTypeForKey(key, value) {
        const k = String(key).toLowerCase();
        if (/(provider|model|engine|backend)/.test(k)) return 'select';
        if (/(key|secret|token|password|passwd)/.test(k)) return 'password';
        if (/(url|endpoint|base_url|baseurl|host|uri)/.test(k)) return 'url';
        if (typeof value === 'boolean') return 'checkbox';
        if (typeof value === 'number') return 'number';
        return 'text';
    }

    // All DOM is built with createElement + textContent/value (never innerHTML with
    // server data), so a hostile/malformed config value cannot inject markup.
    function _msRenderField(container, fieldKey, value) {
        const wrap = document.createElement('div');
        wrap.className = 'form-group';

        const label = document.createElement('label');
        label.textContent = fieldKey;
        wrap.appendChild(label);

        const type = _msInputTypeForKey(fieldKey, value);
        let input;
        if (type === 'select') {
            input = document.createElement('select');
            input.className = 'settings-select';
            const opts = MS_PROVIDER_OPTIONS.slice();
            const cur = value == null ? '' : String(value);
            if (cur && opts.indexOf(cur) === -1) opts.push(cur);
            opts.forEach(function (o) {
                const opt = document.createElement('option');
                opt.value = o;
                opt.textContent = o;
                if (o === cur) opt.selected = true;
                input.appendChild(opt);
            });
        } else if (type === 'checkbox') {
            input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = !!value;
        } else {
            input = document.createElement('input');
            input.type = (type === 'password' || type === 'url' || type === 'number') ? type : 'text';
            input.value = (value == null ? '' : String(value));
        }
        input.setAttribute('data-field', fieldKey);
        input.id = 'ms-' + fieldKey.replace(/[^a-zA-Z0-9_-]/g, '_');
        wrap.appendChild(input);
        container.appendChild(wrap);
    }

    // Nested objects (e.g. providers.embedding) become a titled sub-group of fields.
    function _msRenderGroup(container, groupKey, obj) {
        const title = document.createElement('div');
        title.className = 'service-row-header';
        title.style.marginTop = '12px';
        const span = document.createElement('span');
        span.textContent = groupKey;
        title.appendChild(span);
        container.appendChild(title);

        Object.keys(obj || {}).forEach(function (subKey) {
            const fieldKey = groupKey + '.' + subKey;
            const v = obj[subKey];
            if (v && typeof v === 'object' && !Array.isArray(v)) {
                _msRenderGroup(container, fieldKey, v);
            } else {
                _msRenderField(container, fieldKey, v);
            }
        });
    }

    function renderMemoryStoreForm(snapshot) {
        const form = document.getElementById('memoryStoreForm');
        if (!form) return;
        form.innerHTML = ''; // clears only; we rebuild below with createElement + textContent
        if (!snapshot || typeof snapshot !== 'object') return;
        Object.keys(snapshot).forEach(function (topKey) {
            if (topKey === 'proxy') return; // edited by the [Local Wiki] network proxy form
            const v = snapshot[topKey];
            if (v && typeof v === 'object' && !Array.isArray(v)) {
                _msRenderGroup(form, topKey, v);
            } else {
                _msRenderField(form, topKey, v);
            }
        });
        if (!form.children.length) {
            const hint = document.createElement('div');
            hint.className = 'input-hint';
            hint.textContent = 'No editable Memory Store fields returned by the server.';
            form.appendChild(hint);
        }
    }

    // Write edited form values back onto `target`, rebuilding the nested structure
    // implied by the dotted data-field keys.
    function _msApplyEdits(target) {
        const inputs = document.querySelectorAll('#memoryStoreForm [data-field]');
        inputs.forEach(function (input) {
            const fieldKey = input.getAttribute('data-field');
            const parts = String(fieldKey).split('.');
            let node = target;
            for (let i = 0; i < parts.length - 1; i++) {
                if (typeof node[parts[i]] !== 'object' || node[parts[i]] === null) node[parts[i]] = {};
                node = node[parts[i]];
            }
            const last = parts[parts.length - 1];
            if (input.type === 'checkbox') {
                node[last] = input.checked;
            } else if (input.type === 'number') {
                const n = parseFloat(input.value);
                node[last] = isNaN(n) ? input.value : n;
            } else {
                node[last] = input.value;
            }
        });
        return target;
    }

    async function loadMemoryStoreSettings() {
        _msSetError('');
        _msSetOk('');
        try {
            const r = await fetch('/v1/settings/network');
            if (!r.ok) {
                let reason = 'HTTP ' + r.status;
                try {
                    const body = await r.json();
                    reason = body.error || body.detail || reason;
                } catch (_e) { /* keep status reason */ }
                throw new Error(reason);
            }
            const snapshot = await r.json();
            _msSnapshot = snapshot;
            renderMemoryStoreForm(snapshot);
        } catch (e) {
            // Hard constraint: never swallow load failures — surface them in red.
            _msSetError('Failed to load Memory Store settings: ' + (e && e.message ? e.message : e));
            console.warn('[JoyWs] loadMemoryStoreSettings:', e);
        }
    }

    async function saveMemoryStoreSettings() {
        _msSetError('');
        _msSetOk('');
        // Start from the last GET snapshot so the proxy sub-object is preserved, then overlay edits.
        const base = (_msSnapshot && typeof _msSnapshot === 'object')
            ? JSON.parse(JSON.stringify(_msSnapshot))
            : {};
        _msApplyEdits(base);
        try {
            const r = await fetch('/v1/settings/network', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(base),
            });
            if (!r.ok) {
                let reason = 'HTTP ' + r.status;
                try {
                    const body = await r.json();
                    reason = body.error || body.detail || reason;
                } catch (_e) { /* keep status reason */ }
                throw new Error(reason);
            }
            // Re-sync the form with the saved snapshot, then show success.
            await loadMemoryStoreSettings();
            _msSetOk('Memory Store settings saved.');
            // Refresh status lights: service config badges (/api/services/status)
            // and provider health dots (/v1/providers/health).
            try { if (window.JoyConfig && window.JoyConfig.probe) window.JoyConfig.probe(); } catch (_e) {}
            try { if (window.JoyWiki && window.JoyWiki.loadHealth) window.JoyWiki.loadHealth(); } catch (_e) {}
            // Hard constraint: a 2xx PUT is not "success" if the provider is unhealthy.
            // Surface an ERR as a red error instead of pretending everything is fine.
            try {
                const hr = await fetch('/v1/providers/health');
                if (hr.ok) {
                    const hd = await hr.json();
                    const ms = (hd && hd.memory_store) || {};
                    if (ms.ok === false) {
                        _msSetError('Saved, but the Memory Store provider reports an error: ' + (ms.reason || 'unknown'));
                    }
                }
            } catch (_e) { /* health unreachable; loadHealth already painted the dots red */ }
        } catch (e) {
            // Hard constraint: a non-2xx response must show a red error, never pretend success.
            _msSetError('Save failed: ' + (e && e.message ? e.message : e));
            console.warn('[JoyWs] saveMemoryStoreSettings:', e);
        }
    }

    window.JoyWs = {
        register,
        cleanupServerSession,
        applyApiSettings,
        connectWebSocket,
        loadMemoryStoreSettings,
        saveMemoryStoreSettings,
        renderMemoryStoreForm
    };
})();
