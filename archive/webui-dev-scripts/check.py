import io
p = r'services\webui\src\joy_interaction_webui\static\index.html'
s = io.open(p, 'r', encoding='utf-8').read()
idx = s.find('resultTextContent')
seg = s[idx:idx+500]
io.open('snippet.txt', 'w', encoding='utf-8').write(seg)
print('LEN', len(seg))
