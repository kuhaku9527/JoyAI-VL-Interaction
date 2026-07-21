import io
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

css = (
    "\n"
    "        /* vlm-history empty-state placeholder (BT-7274 pilot panel) */\n"
    "        .vlm-history > .vlm-history-empty-state {\n"
    "            margin: auto;\n"
    "            padding: 32px 24px;\n"
    "            border: 1px dashed var(--border-color);\n"
    "            border-radius: 14px;\n"
    "            background: var(--bg-secondary);\n"
    "            color: var(--text-muted);\n"
    "            text-align: center;\n"
    "            max-width: 560px;\n"
    "            min-width: 320px;\n"
    "            align-self: center;\n"
    "            justify-self: center;\n"
    "        }\n"
    "        .vlm-history > .vlm-history-empty-state .empty-emoji {\n"
    "            font-size: 36px;\n"
    "            line-height: 1;\n"
    "            margin-bottom: 8px;\n"
    "        }\n"
    "        .vlm-history > .vlm-history-empty-state .empty-title {\n"
    "            font-size: 15px;\n"
    "            font-weight: 600;\n"
    "            color: var(--text-secondary);\n"
    "            margin-bottom: 6px;\n"
    "        }\n"
    "        .vlm-history > .vlm-history-empty-state .empty-hint {\n"
    "            font-size: 13px;\n"
    "            line-height: 1.55;\n"
    "            color: var(--text-muted);\n"
    "        }\n"
    "        .vlm-history > .vlm-history-empty-state.is-hidden {\n"
    "            display: none;\n"
    "        }\n"
)

# 插到 .vlm-history-shell 的 .fade 之后
anchor = "        .vlm-history-shell.fade {\n            opacity: 1;\n        }\n"
if anchor not in s:
    print('ANCHOR NOT FOUND'); raise SystemExit(2)

s = s.replace(anchor, anchor + css, 1)
io.open(p, 'w', encoding='utf-8').write(s)
print('OK')
