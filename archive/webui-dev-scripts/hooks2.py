import io, sys
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

# 1. Helper
anchor1 = ('        function shouldShowVlmHistoryShell() {
            // BT-7274 链路下 chat 容器始终展开，方便 Pilot 看到对话；
            // 空状态下由 .vlm-history-empty-state 提供占位文案。
            return true;
        }
')
if anchor1 not in s: sys.exit('ANCHOR1 NF')
helper = (anchor1 + '
        // empty-state 是 resultText 子级，不会被 innerHTML 清掉
        function syncVlmHistoryEmpty() {
            const empty = document.getElementById('vlmHistoryEmpty');
            if (!empty) return;
            const hasReal = Array.isArray(vlmHistory) && vlmHistory.length > 0;
            empty.classList.toggle('is-hidden', hasReal);
        }
')
s = s.replace(anchor1, helper, 1)

# 2. appendVlmHistoryEntry
import re
m = re.search(r'            if \(shouldAutoScroll\) \{
                scrollVlmHistoryToBottom\(contentDiv\);
            \}
', s)
if not m: sys.exit('APPEND NF: ' + s[m.start()-200:m.end()+200] if m else 'none')
old2 = m.group(0)
new2 = ('            if (shouldAutoScroll) {
                scrollVlmHistoryToBottom(contentDiv);
            }
            syncVlmHistoryEmpty();
')
s = s.replace(old2, new2, 1)

# 3. renderVlmHistory
m2 = re.search(r'            contentDiv\.appendChild\(fragment\);

            resultText\.style\.display = shouldShowVlmHistoryShell\(\) \? .flex. : .none.;
            if \(shouldAutoScroll\) \{
', s)
if not m2: sys.exit('RENDER NF')
old3 = m2.group(0)
new3 = ('            contentDiv.appendChild(fragment);

            resultText.style.display = shouldShowVlmHistoryShell() ? 'flex' : 'none';
            syncVlmHistoryEmpty();
            if (shouldAutoScroll) {
')
s = s.replace(old3, new3, 1)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK')