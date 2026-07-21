import io, re, sys
p = 'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()

# 1. 找 const resultText = document.getElementById('resultText');
pat = re.compile(r"const resultText = document\.getElementById\('resultText'\);")
m = pat.search(s)
if not m:
    sys.exit('resultText const NF')

# 直接追加 sync 调用，注释使用 ASCII 标签
note = chr(10) + chr(10) + '        // initial sync: show empty-state until first history entry arrives'
note += chr(10) + '        if (typeof syncVlmHistoryEmpty === ' + chr(34) + 'function' + chr(34) + ') syncVlmHistoryEmpty();'

s = s.replace(m.group(0), m.group(0) + note, 1)
io.open(p, 'w', encoding='utf-8').write(s)
print('OK')