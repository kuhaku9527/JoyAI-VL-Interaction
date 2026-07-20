import io, re, sys
p = r\"services\\webui\\src\\joy_interaction_webui\\static\\index.html\"
s = io.open(p, \"r\", encoding=\"utf-8\").read()

anchor1 = \"        function shouldShowVlmHistoryShell() {\n            // BT-7274 \u94fe\u8def\u4e0b chat \u5bb9\u5668\u59cb\u7ec8\u5c55\u5f00\uff0c\u65b9\u4fbf Pilot \u770b\u5230\u5bf9\u8bdd\uff1b\n            // \u7a7a\u72b6\u6001\u4e0b\u7531 .vlm-history-empty-state \u63d0\u4f9b\u5360\u4f4d\u6587\u6848\u3002\n            return true;\n        }\n\"
if anchor1 not in s: sys.exit(\"A1\")
new1 = anchor1 + \"\n        // empty-state \u662f resultText \u5b50\u7ea7\uff0c\u4e0d\u4f1a\u88ab innerHTML \u6e05\u6389\n        function syncVlmHistoryEmpty() {\n            const empty = document.getElementById(
"\""
vlmHistoryEmpty
"\""
);\n            if (!empty) return;\n            const hasReal = Array.isArray(vlmHistory) && vlmHistory.length > 0;\n            empty.classList.toggle(
"\""
is-hidden
"\""
, hasReal);\n        }\n\"
s = s.replace(anchor1, new1, 1)

# 2. appendVlmHistoryEntry
pat2 = re.compile(r\"            if \\(shouldAutoScroll\\) \\{\\n                scrollVlmHistoryToBottom\\(contentDiv\\);\\n            \\}\\n\")
m2 = pat2.search(s)
if not m2: sys.exit(\"A2\")
old2 = m2.group(0)
new2 = \"            if (shouldAutoScroll) {\n                scrollVlmHistoryToBottom(contentDiv);\n            }\n            syncVlmHistoryEmpty();\n\"
s = s.replace(old2, new2, 1)

# 3. renderVlmHistory
pat3 = re.compile(r\"            contentDiv\\.appendChild\\(fragment\\);\\n\\n            resultText\\.style\\.display = shouldShowVlmHistoryShell\\(\\) \\? .flex. : .none.;\\n\")
m3 = pat3.search(s)
if not m3: sys.exit(\"A3\")
old3 = m3.group(0)
new3 = \"            contentDiv.appendChild(fragment);\n\n            resultText.style.display = shouldShowVlmHistoryShell() ? 
'
flex
'
 : 
'
none
'
;\n            syncVlmHistoryEmpty();\n\"
s = s.replace(old3, new3, 1)

io.open(p, \"w\", encoding=\"utf-8\").write(s)
print(\"OK\")