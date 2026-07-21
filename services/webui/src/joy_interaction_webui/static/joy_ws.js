// joy_ws.js — WebSocket / API-settings session cluster (Block 4)
// Extracted from services/webui/src/joy_interaction_webui/static/index.html
// (original inline function applyApiSettings ~lines 8683-8714 and
//  cleanupServerSession ~lines 9180-9200). Mounted on window.JoyWs.
//
// Why a register(ctx) bridge instead of the plain IIFE-to-window used by
// Blocks 1-3:
//   cleanupServerSession is pure (only fetch + console) and needs no bridge.
//   applyApiSettings, however, reads closure-local refs that are reassigned at
//   runtime — most importantly `websocket` (a `let` that connectWebSocket/
//   resetSession reassign). A live getWebSocket() accessor keeps the module in
//   sync with the inline script's single source of truth without turning the
//   whole monolith inside-out. The other refs (apiBaseUrl/apiKey/modelSelect
//   DOM nodes, isValidModelName/updateStatus/fetchModels) are stable, so they
//   are passed by value once at register() time.
//
// Call window.JoyWs.register({...}) exactly once from the inline script, after
// every referenced closure symbol is in scope (it is — the alias is placed at
// the old applyApiSettings location, which is after all of them). connectWebSocket
// stays inline (Block 5) and calls window.JoyWs.applyApiSettings via the alias.
(function () {
    'use strict';

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

    window.JoyWs = {
        register,
        cleanupServerSession,
        applyApiSettings
    };
})();
