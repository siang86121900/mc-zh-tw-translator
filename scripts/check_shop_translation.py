import json,re,zipfile
from pathlib import Path
from full_translation_audit import parse_binary_nbt
BASE=Path('C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
OUT=Path('output/shop_translation_fix')
report=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
keys=report['structure_aliases'];hits={k:[] for k in keys}
for folder in ('mods','resourcepacks'):
    for p in (BASE/folder).iterdir():
        if p.suffix not in ('.jar','.zip'):continue
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                if not name.endswith('/lang/zh_tw.json'):continue
                try: d=json.loads(z.read(name).decode('utf-8-sig'))
                except (ValueError,UnicodeError):continue
                for k in keys:
                    if k in d:hits[k].append([p.name+'!/'+name,d[k]])
for p in (BASE/'kubejs').rglob('zh_tw.json'):
    d=json.loads(p.read_text(encoding='utf-8-sig'))
    for k in keys:
        if k in d:hits[k].append([str(p.relative_to(BASE)),d[k]])
conflicts={k:v for k,v in hits.items() if any(x[1]!=keys[k] for x in v)}
assert not conflicts,conflicts
assert all(hits.values())
ids=set()
for folder in ('config/SDMShop','config/ftbquests'):
    for p in (BASE/folder).rglob('*.snbt'):
        ids.update(re.findall(r'StructureName:\s*"([^"\n]+)"',p.read_text(encoding='utf-8-sig')))
unmapped=sorted(x for x in ids if 'item.nsprefab.'+x not in keys)
binary={str(p.relative_to(BASE)):parse_binary_nbt(p.read_bytes()) for p in (BASE/'config/SDMShop').rglob('*.data')}
result=dict(alias_count=len(keys),structure_ids=len(ids),unmapped=unmapped,conflicts=conflicts,binary_configuration=binary)
(OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
