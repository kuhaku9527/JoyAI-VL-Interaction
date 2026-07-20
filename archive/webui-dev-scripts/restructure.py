import io
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

# 1. HTML: 把 empty-state 从 resultTextContent 内提到 resultTextContent 后面（resultText 子级）
old_html = (
    '<div class="result-text-content vlm-history" id="resultTextContent">\n'
    '                        <div class="vlm-history-empty-state" id="vlmHistoryEmpty">\n'
    '                            <div class="empty-emoji" aria-hidden="true">🎙️</div>\n'
    '                            <div class="empty-title">等待 Pilot 输入</div>\n'
    '                            <div class="empty-hint">在下方对话框输入文字，或喊一声 &quot;BT&quot;，即可开始与 BT-7274 对话。</div>\n'
    '                        </div>\n'
    '                    </div>'
)
new_html = (
    '<div class="result-text-content vlm-history" id="resultTextContent"></div>\n'
    '                    <div class="vlm-history-empty-state" id="vlmHistoryEmpty">\n'
    '                        <div class="empty-emoji" aria-hidden="true">🎙️</div>\n'
    '                        <div class="empty-title">等待 Pilot 输入</div>\n'
    '                        <div class="empty-hint">在下方对话框输入文字，或喊一声 &quot;BT&quot;，即可开始与 BT-7274 对话。</div>\n'
    '                    </div>'
)
if old_html not in s:
    print('OLD HTML NOT FOUND')
    raise SystemExit(2)
s = s.replace(old_html, new_html, 1)

# 2. CSS: 旧规则改成 absolute 定位（覆盖 .vlm-history）；保留内部元素装饰
old_css_old = (
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
new_css_new = (
    "\n"
    "        /* vlm-history empty-state placeholder (BT-7274 pilot panel) */\n"
    "        #vlmHistoryEmpty {\n"
    "            position: absolute;\n"
    "            top: 18px;\n"
    "            right: 4px;\n"
    "            bottom: 36px;\n"
    "            left: 4px;\n"
    "            margin: auto;\n"
    "            padding: 32px 24px;\n"
    "            border: 1px dashed var(--border-color);\n"
    "            border-radius: 14px;\n"
    "            background: var(--bg-secondary);\n"
    "            color: var(--text-muted);\n"
    "            text-align: center;\n"
    "            max-width: 560px;\n"
    "            min-width: 320px;\n"
    "            width: min(560px, calc(100% - 24px));\n"
    "            height: max-content;\n"
    "            display: flex;\n"
    "            flex-direction: column;\n"
    "            align-items: center;\n"
    "            justify-content: center;\n"
    "            pointer-events: none;\n"
    "            z-index: 1;\n"
    "        }\n"
    "        #vlmHistoryEmpty .empty-emoji {\n"
    "            font-size: 36px;\n"
    "            line-height: 1;\n"
    "            margin-bottom: 8px;\n"
    "        }\n"
    "        #vlmHistoryEmpty .empty-title {\n"
    "            font-size: 15px;\n"
    "            font-weight: 600;\n"
    "            color: var(--text-secondary);\n"
    "            margin-bottom: 6px;\n"
    "        }\n"
    "        #vlmHistoryEmpty .empty-hint {\n"
    "            font-size: 13px;\n"
    "            line-height: 1.55;\n"
    "            color: var(--text-muted);\n"
    "        }\n"
    "        #vlmHistoryEmpty.is-hidden {\n"
    "            display: none;\n"
    "        }\n"
)
if old_css_old not in s:
    print('OLD CSS NOT FOUND')
    raise SystemExit(3)
s = s.replace(old_css_old, new_css_new, 1)

# 3. JS helper 改成：empty-state 是 resultText 子，根据 vlmHistory.length 决定。
old_helper = (
    "        // 根据 vlm-history 真实 children 同步 empty-state 占位显隐\n"
    "        function syncVlmHistoryEmpty() {\n"
    "            const empty = document.getElementById('vlmHistoryEmpty');\n"
    "            if (!empty) return;\n"
    "            const content = document.getElementById('resultTextContent');\n"
    "            if (!content) return;\n"
    "            const hasReal = !!content.querySelector('.result-prompt, .result-text, .background-result');\n"
    "            empty.classList.toggle('is-hidden', hasReal);\n"
    "        }\n"
)
new_helper = (
    "        // 根据 vlmHistory 长度切换 empty-state 占位（empty 是 resultText 子级，不会被 innerHTML 清掉）\n"
    "        function syncVlmHistoryEmpty() {\n"
    "            const empty = document.getElementById('vlmHistoryEmpty');\n"
    "            if (!empty) return;\n"
    "            const hasReal = Array.isArray(vlmHistory) && vlmHistory.length > 0;\n"
    "            empty.classList.toggle('is-hidden', hasReal);\n"
    "        }\n"
)
if old_helper not in s:
    print('OLD HELPER NOT FOUND')
    raise SystemExit(4)
s = s.replace(old_helper, new_helper, 1)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK')
