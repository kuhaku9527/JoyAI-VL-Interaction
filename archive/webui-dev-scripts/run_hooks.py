import io, re, sys

p = 'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

Q = chr(34)  # double quote
N = '\n'     # newline in single-quoted str

# 1. Helper function inserted after shouldShowVlmHistoryShell
anchor1 = (
    '        function shouldShowVlmHistoryShell() {\n'
    '            // BT-7274 ' + chr(0x94fe) + chr(0x8def) + chr(0x4e0b)
    + ' chat ' + chr(0x5bb9) + chr(0x5668) + chr(0x59cb) + chr(0x7ec8) + chr(0x5c55) + chr(0x5f00) + chr(0xff0c) + chr(0x65b9) + chr(0x4fbf) + ' Pilot ' + chr(0x770b) + chr(0x5230) + chr(0x5bf9) + chr(0x8bdd) + chr(0xff1b) + '\n'
    '            // ' + chr(0x7a7a) + chr(0x72b6) + chr(0x6001) + chr(0x4e0b) + chr(0x7531) + ' .vlm-history-empty-state ' + chr(0x63d0) + chr(0x4f9b) + chr(0x5360) + chr(0x4f4d) + chr(0x6587) + chr(0x6848) + chr(0x3002) + '\n'
    '            return true;\n'
    '        }\n'
)
print('len anchor1 =', len(anchor1))
# easier: just match by single line
pattern1 = re.compile(r'        function shouldVlmHistoryShell|function shouldShowVlmHistoryShell', re.S)
# skip the easier route - let's just match a unique anchor substring
anchor1_simple = '            return true;\n        }\n\n        function createJarvisDialogNode'
if anchor1_simple not in s:
    print('SIMPLE A1 NF')
    sys.exit(1)
new1 = (
    '            return true;\n'
    '        }\n'
    '\n'
    '        // empty-state ' + chr(0x662f) + ' resultText ' + chr(0x5b50) + chr(0x7ea7) + chr(0xff0c) + chr(0x4e0d) + chr(0x4f1a) + chr(0x88ab) + ' innerHTML ' + chr(0x6e05) + chr(0x6389) + '\n'
    '        function syncVlmHistoryEmpty() {\n'
    '            const empty = document.getElementById(' + Q + 'vlmHistoryEmpty' + Q + ');\n'
    '            if (!empty) return;\n'
    '            const hasReal = Array.isArray(vlmHistory) && vlmHistory.length > 0;\n'
    '            empty.classList.toggle(' + Q + 'is-hidden' + Q + ', hasReal);\n'
    '        }\n'
    '\n'
    '        function createJarvisDialogNode'
)
s = s.replace(anchor1_simple, new1, 1)

# 2. appendVlmHistoryEntry: insert syncVlmHistoryEmpty() after if (shouldAutoScroll)
pat2 = re.compile(r'            if \(shouldAutoScroll\) \{\n                scrollVlmHistoryToBottom\(contentDiv\);\n            \}\n')
m2 = pat2.search(s)
if not m2:
    print('A2 NF')
    sys.exit(2)
old2 = m2.group(0)
new2 = (
    '            if (shouldAutoScroll) {\n'
    '                scrollVlmHistoryToBottom(contentDiv);\n'
    '            }\n'
    '            syncVlmHistoryEmpty();\n'
)
s = s.replace(old2, new2, 1)

# 3. renderVlmHistory: insert after the display setting line
pat3 = re.compile(r'            resultText\.style\.display = shouldShowVlmHistoryShell\(\) \? .flex. : .none.;\n')
m3 = pat3.search(s)
if not m3:
    print('A3 NF')
    sys.exit(3)
old3 = m3.group(0)
new3 = (
    '            resultText.style.display = shouldShowVlmHistoryShell() ? ' + Q + 'flex' + Q + ' : ' + Q + 'none' + Q + ';\n'
    '            syncVlmHistoryEmpty();\n'
)
# replace first occurrence
s = s.replace(old3, new3, 1)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK')