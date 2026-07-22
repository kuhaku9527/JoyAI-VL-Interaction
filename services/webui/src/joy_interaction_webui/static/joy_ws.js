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
        // Belt-and-suspenders retry if first install didn't take (jarvis-mode.md §14.4 / v3.5).
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

    window.JoyWs = {
        register,
        cleanupServerSession,
        applyApiSettings,
        connectWebSocket
    };
})();
