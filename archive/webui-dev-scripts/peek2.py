import io
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()
idx = s.find('syncVlmHistoryEmpty')
seg = s[idx:idx+700]
io.open('peek2.txt', 'w', encoding='utf-8').write(seg)
print('WROTE', len(seg))