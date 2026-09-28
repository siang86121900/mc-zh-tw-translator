import json,re,zipfile
from pathlib import Path
from normalize_zh_tw import normalize_text
from apply_manual_zh_tw_fixes import FIXES
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/2026-09-09'
# Reuse the reviewed English-to-Chinese display-text mapping, without executing
# the older script's quest overwrites or unconditional continuation-line removal.
scope={'__file__':str(ROOT/'scripts/finish_current_batch.py')}
exec((ROOT/'scripts/finish_current_batch.py').read_text(encoding='utf-8').split('def process(data):')[0],scope)
mapping=scope['mapping']
count=0
for p in sorted((OUT/'mods').glob('*.jar')):
    changes={}
    with zipfile.ZipFile(p) as z:
        for name in z.namelist():
            if not name.endswith('/lang/zh_tw.json'): continue
            tw=json.loads(z.read(name)); new=dict(tw)
            enpath=name.replace('zh_tw.json','en_us.json')
            if enpath not in z.namelist(): continue
            from mc_zh_tw_translator.translator import CTE2QuestTranslator
            try: en=json.loads(CTE2QuestTranslator._strip_json_comments(z.read(enpath).decode('utf-8-sig')))
            except Exception: continue
            for k,v in tw.items():
                if isinstance(v,str) and v in mapping and en.get(k)==v: new[k]=normalize_text(mapping[v])
            for k,v in FIXES.get(p.name,{}).items():
                if k in en and k in tw: new[k]=v
            count+=sum(new[k]!=tw.get(k) for k in new)
            if new!=tw: changes[name]=json.dumps(new,ensure_ascii=False,indent=2).encode()
        if changes:
            tmp=p.with_suffix('.manual.tmp')
            with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as w:
                for item in z.infolist():
                    if re.match(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)$',item.filename,re.I): continue
                    w.writestr(item,changes.get(item.filename,z.read(item.filename)))
    if changes: tmp.replace(p)
for p in (OUT/'kubejs/assets').rglob('zh_tw.json'):
    data=json.loads(p.read_text(encoding='utf-8-sig')); new={k:normalize_text(mapping.get(v,v)) if isinstance(v,str) else v for k,v in data.items()}
    count+=sum(new[k]!=data[k] for k in new)
    if new!=data: p.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
print('Manual corrections:',count)
