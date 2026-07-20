import io
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

# 1. 在 shouldShowVlmHistoryShell 后插入 syncVlmHistoryEmpty 函数
anchor1 = (
    "        function shouldShowVlmHistoryShell() {\n"
    "            // BT-7274 链路下 chat 容器始终展开，方便 Pilot 看到对话；\n"
    "            // 空状态下由 .vlm-history-empty-state 提供占位文案。\n"
    "            return true;\n"
    "        }\n"
)
helper = (
    "        function shouldShowVlmHistoryShell() {\n"
    "            // BT-7274 链路下 chat 容器始终展开，方便 Pilot 看到对话；\n"
    "            // 空状态下由 .vlm-history-empty-state 提供占位文案。\n"
    "            return true;\n"
    "        }\n"
    "\n"
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
if anchor1 not in s:
    print('ANCHOR1 NOT FOUND'); raise SystemExit(2)
s = s.replace(anchor1, helper, 1)

# 2. appendVlmHistoryEntry 末尾调用
anchor2 = (
    "            if (shouldAutoScroll) {\n"
    "                scrollVlmHistoryToBottom(contentDiv);\n"
    "            }\n\n"
    "            const videoCard = document.getElementById('videoCard');\n"
    "            if (videoCard && videoCard.classList.contains('fullscreen')) {\n"
    "                syncVlmToFullscreen();\n"
    "            }\n"
    "        }\n"
)
hook2 = (
    "            if (shouldAutoScroll) {\n"
    "                scrollVlmHistoryToBottom(contentDiv);\n"
    "            }\n"
    "            syncVlmHistoryEmpty();\n\n"
    "            const videoCard = document.getElementById('videoCard');\n"
    "            if (videoCard && videoCard.classList.contains('fullscreen')) {\n"
    "                syncVlmToFullscreen();\n"
    "            }\n"
    "        }\n"
)
if anchor2 not in s:
    print('ANCHOR2 NOT FOUND'); raise SystemExit(3)
s = s.replace(anchor2, hook2, 1)

# 3. renderVlmHistory 末尾加 syncVlmHistoryEmpty（是在 display = ... 那行之后）
anchor3 = (
    "            contentDiv.appendChild(fragment);\n\n"
    "            resultText.style.display = shouldShowVlmHistoryShell() ? 'flex' : 'none';\n"
    "            if (shouldAutoScroll) {\n"
    "                scrollVlmHistoryToBottom(contentDiv);\n"
    "            }\n"
    "        }\n"
)
hook3 = (
    "            contentDiv.appendChild(fragment);\n\n"
    "            resultText.style.display = shouldShowVlmHistoryShell() ? 'flex' : 'none';\n"
    "            syncVlmHistoryEmpty();\n"
    "            if (shouldAutoScroll) {\n"
    "                scrollVlmHistoryToBottom(contentDiv);\n"
    "            }\n"
    "        }\n"
)
if anchor3 not in s:
    print('ANCHOR3 NOT FOUND'); raise SystemExit(4)
s = s.replace(anchor3, hook3, 1)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK')
