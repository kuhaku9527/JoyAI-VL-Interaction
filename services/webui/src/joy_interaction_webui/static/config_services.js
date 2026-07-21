// config_services.js — Services panel config/API form cluster (Block 3)
// Extracted from services/webui/src/joy_interaction_webui/static/index.html
// (original inline IIFE ~lines 4873-4944). Mounted on window.JoyConfig.
//
// NOTE: the button-wiring + load() auto-call stay inline in index.html.
// load() must run only after the services-panel DOM is parsed, otherwise
// writeForm() would populate form fields that do not yet exist.
(function () {
    const SERVICES = ["llm", "summary", "tts", "asr"];

    function setBadge(name, status, hint) {
        const b = document.getElementById("badge-" + name);
        if (!b) return;
        b.textContent = status;
        b.className = "service-badge " + (status === "OK" ? "ok" : status === "ERR" ? "err" : "");
        if (hint) b.title = hint;
    }

    function readForm() {
        const cfg = { llm: {}, summary: {}, tts: {}, asr: {} };
        const urlEl = function (s, k) { return document.getElementById("svc-" + s + "-" + k); };
        cfg.llm.api_base = (urlEl("llm", "api-base") || {}).value || "";
        cfg.llm.model = (urlEl("llm", "model") || {}).value || "";
        cfg.llm.api_key = (urlEl("llm", "api-key") || {}).value || "";
        cfg.summary.api_base = (urlEl("summary", "api-base") || {}).value || "";
        cfg.summary.model = (urlEl("summary", "model") || {}).value || "";
        cfg.tts.api_base = (urlEl("tts", "api-base") || {}).value || "";
        cfg.asr.api_base = (urlEl("asr", "api-base") || {}).value || "";
        cfg.asr.model = (urlEl("asr", "model") || {}).value || "";
        return cfg;
    }

    function writeForm(cfg) {
        const setVal = function (id, v) { const el = document.getElementById(id); if (el) el.value = v || ""; };
        setVal("svc-llm-api-base", cfg.llm && cfg.llm.api_base);
        setVal("svc-llm-model", cfg.llm && cfg.llm.model);
        setVal("svc-llm-api-key", cfg.llm && cfg.llm.api_key);
        setVal("svc-summary-api-base", cfg.summary && cfg.summary.api_base);
        setVal("svc-summary-model", cfg.summary && cfg.summary.model);
        setVal("svc-tts-api-base", cfg.tts && cfg.tts.api_base);
        setVal("svc-asr-api-base", cfg.asr && cfg.asr.api_base);
        setVal("svc-asr-model", cfg.asr && cfg.asr.model);
    }

    async function load() {
        try {
            const r = await fetch("/api/services/config");
            if (!r.ok) throw new Error("HTTP " + r.status);
            const cfg = await r.json();
            writeForm(cfg);
        } catch (e) {
            console.warn("load services config:", e);
        }
        await probe();
    }

    async function probe() {
        SERVICES.forEach(function (s) { setBadge(s, "..."); });
        try {
            const r = await fetch("/api/services/status");
            if (!r.ok) throw new Error("HTTP " + r.status);
            const data = await r.json();
            SERVICES.forEach(function (s) {
                const item = data[s] || {};
                setBadge(s, item.ok ? "OK" : "ERR", item.reason || "");
            });
        } catch (e) {
            SERVICES.forEach(function (s) { setBadge(s, "ERR", String(e)); });
        }
    }

    async function save() {
        const cfg = readForm();
        try {
            const r = await fetch("/api/services/config", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(cfg),
            });
            if (!r.ok) throw new Error("HTTP " + r.status);
            await probe();
        } catch (e) {
            alert("Save failed: " + e);
        }
    }

    window.JoyConfig = { SERVICES, setBadge, readForm, writeForm, load, probe, save };
})();
