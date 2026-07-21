import io, re
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

# 该死的 PowerShell -replace 把转义当成字面写了，替换回去
old = (
    '<div class="result-text-content vlm-history" id="resultTextContent">`r`n'
    '                        <div class="vlm-history-empty-state" id="vlmHistoryEmpty">`r`n'
    '                            <div class="empty-emoji" aria-hidden="true">🎙️</div>`r`n'
    '                            <div class="empty-title">等待 Pilot 输入</div>`r`n'
    '                            <div class="empty-hint">在下方对话框输入文字，或喊一声 \\u0022BT\\u0022，即可开始与 BT-7274 对话。</div>`r`n'
    '                        </div>`r`n'
    '                    </div>'
)
new = (
    '<div class="result-text-content vlm-history" id="resultTextContent">\n'
    '                        <div class="vlm-history-empty-state" id="vlmHistoryEmpty">\n'
    '                            <div class="empty-emoji" aria-hidden="true">🎙️</div>\n'
    '                            <div class="empty-title">等待 Pilot 输入</div>\n'
    '                            <div class="empty-hint">在下方对话框输入文字，或喊一声 &quot;BT&quot;，即可开始与 BT-7274 对话。</div>\n'
    '                        </div>\n'
    '                    </div>'
)
if old not in s:
    print('NOT FOUND')
    raise SystemExit(2)
s = s.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(s)
print('OK')

# 再检查一下
idx = s.find('resultTextContent')
print(repr(s[idx:idx+400]))
