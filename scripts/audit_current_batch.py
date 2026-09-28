import json,zipfile,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]; out=root/'output/2026-09-09'
rows=[]
def audit(label,en,tw):
    for k,v in en.items():
        w=tw.get(k,'')
        if isinstance(v,str) and re.search('[A-Za-z]{3}',v) and (v==w or not w): rows.append([label,k,v,w])
for p in (out/'mods').glob('*.jar'):
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.endswith('/lang/en_us.json'):
                try: audit(p.name+':'+n,json.loads(z.read(n)),json.loads(z.read(n.replace('en_us','zh_tw'))))
                except Exception as e: print(p.name,n,e)
for p in (out/'kubejs').rglob('en_us.json'):
    audit(str(p.relative_to(out)),json.loads(p.read_text(encoding='utf-8-sig')),json.loads(p.with_name('zh_tw.json').read_text(encoding='utf-8-sig')))
(out/'untranslated.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Remaining',len(rows))
for row in rows: print(json.dumps(row,ensure_ascii=False))
