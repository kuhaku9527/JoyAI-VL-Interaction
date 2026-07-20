import io
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()
idx = s.find('function renderVlmHistory')
seg = s[idx:idx+1500]
io.open('peek.txt', 'w', encoding='utf-8').write(seg)
