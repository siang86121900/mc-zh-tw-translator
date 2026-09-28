"""Apply reviewed resource overrides while Minecraft is running; no JAR writes."""
import json,hashlib,collections,shutil,re,zipfile
from pathlib import Path
BASE=Path('C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1');OUT=Path('output/review_20260911')
r=json.loads((OUT/'batch_review.json').read_text(encoding='utf8'))
for rel,h in r['source_hashes'].items():assert hashlib.sha256((BASE/rel).read_bytes()).hexdigest()==h,rel
by_ns=collections.defaultdict(dict)
for x in r['approved']:
 ns=re.search(r'assets/([^/]+)/lang/',x['source'])[1]
 assert x['key'] not in by_ns[ns] or by_ns[ns][x['key']]==x['after']
 by_ns[ns][x['key']]=x['after']
installed=[]
for ns,entries in by_ns.items():
 rel=Path(f'kubejs/assets/{ns}/lang/zh_tw.json');p=BASE/rel
 before=p.read_bytes() if p.exists() else None
 if before is not None:
  backup=OUT/'before_overrides'/rel;backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(before)
 d=json.loads(before.decode('utf-8-sig')) if before else {};d.update(entries)
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf8')
 readback=json.loads(p.read_text(encoding='utf8'));assert all(readback[k]==v for k,v in entries.items())
 installed.append(dict(path=str(rel),created=before is None,entries=len(entries),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
(OUT/'installed_overrides.json').write_text(json.dumps(installed,ensure_ascii=False,indent=2),encoding='utf8')
print('Installed overrides:',len(installed),'files;',sum(x['entries'] for x in installed),'keys; JARs unchanged')
