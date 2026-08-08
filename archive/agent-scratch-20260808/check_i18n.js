'use strict';
const fs = require('fs');
const path = require('path');

const REPO = 'D:/AI/workspace/JoyAI-VL-Interaction-main';
const jsPath = path.join(REPO, 'services/webui/src/joy_interaction_webui/static/i18n_device_label.js');
const htmlPath = path.join(REPO, 'services/webui/src/joy_interaction_webui/static/index.html');

// Load the module so globalThis.JoyI18n is mounted (window undefined in node -> globalThis).
require(jsPath);
const JoyI18n = globalThis.JoyI18n;
if (!JoyI18n || typeof JoyI18n.localizeUiString !== 'function') {
  console.error('FAIL: JoyI18n.localizeUiString not mounted');
  process.exit(2);
}

const html = fs.readFileSync(htmlPath, 'utf8');

// 1) boolean data-i18n element text content
const textRe = /<([a-zA-Z0-9]+)([^>]*)\bdata-i18n\b([^>]*)>([^<]*)</g;
const keys = [];
let m;
while ((m = textRe.exec(html)) !== null) {
  const text = m[4].trim();
  if (text) keys.push({ kind: 'data-i18n(text)', key: text, tag: m[1] });
}
// 2) data-i18n-title / data-i18n-aria / data-i18n-placeholder attribute values
const attrRe = /<([a-zA-Z0-9]+)([^>]*)\b(data-i18n-(?:title|aria|placeholder))="([^"]*)"/g;
while ((m = attrRe.exec(html)) !== null) {
  keys.push({ kind: m[3], key: m[4].trim(), tag: m[1] });
}

console.log('Total data-i18n keys extracted:', keys.length);

let unmapped = [];
let mapped = 0;
for (const k of keys) {
  const out = JoyI18n.localizeUiString(k.key);
  if (out === k.key) {
    unmapped.push(k);
  } else {
    mapped++;
  }
}
console.log('Mapped (localized):', mapped);
console.log('Unmapped (passthrough):', unmapped.length);
if (unmapped.length) {
  console.log('--- UNMAPPED (potential stale/missing English UI copy) ---');
  for (const k of unmapped) console.log(`[${k.kind}] <${k.tag}> "${k.key}"`);
}
