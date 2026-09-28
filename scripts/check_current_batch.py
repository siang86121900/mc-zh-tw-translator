import json,re,zipfile,hashlib
from pathlib import Path
from normalize_zh_tw import normalize_text
root=Path(__file__).resolve().parents[1]; out=root/'output/2026-09-09'
# Only display strings passed to tooltip text.add calls; leave script logic intact.
changed=0
for p in (root/'input/kubejs/client_scripts').rglob('*.js'):
    text=p.read_text(encoding='utf-8-sig')
    pattern=r'(text\s*\.\s*add\s*\(\s*\d+\s*,\s*)("(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27)'
    result=re.sub(pattern,lambda m:m[1]+normalize_text(m[2]),text)
    if result!=text:
        (out/p.relative_to(root/'input')).write_text(result,encoding='utf-8');changed+=1
errors=[]; total=0; unchanged=0
ph=re.compile(r'%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?[sdf]|\{\d+\}')
for p in (out/'mods').glob('*.jar'):
    original=root/'input/mods'/p.name
    unchanged+=hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256(original.read_bytes()).digest()
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if not n.endswith('/lang/zh_tw.json'): continue
            tw=json.loads(z.read(n)); total+=len(tw)
            en_path=n.replace('zh_tw.json','en_us.json')
            if en_path not in z.namelist(): continue
            try: en=json.loads(re.sub(r',\s*}', '}',z.read(en_path).decode('utf-8-sig')))
            except Exception as e: errors.append([n,str(e)]);continue
            for k,v in en.items():
                w=tw.get(k)
                if w is None: errors.append([p.name,k,'missing'])
                elif isinstance(v,str) and isinstance(w,str):
                    if sorted(ph.findall(v))!=sorted(ph.findall(w)): errors.append([p.name,k,v,w])
                    if '\ufffd' in w or '__MC_FMT_' in w: errors.append([p.name,k,'broken formatting',w])
print(json.dumps({'jar_count':len(list((out/'mods').glob('*.jar'))),'unchanged_jars':unchanged,'jar_language_entries':total,'kubejs_language_files':len(list((out/'kubejs/assets').rglob('zh_tw.json'))),'tooltip_scripts':changed,'errors':errors},ensure_ascii=False,indent=2))
(out/'quality_check.json').write_text(json.dumps({'errors':errors,'jar_language_entries':total,'tooltip_scripts':changed},ensure_ascii=False,indent=2),encoding='utf-8')
