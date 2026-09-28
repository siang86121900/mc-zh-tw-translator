"""Install staged, source-hash-bound shop fixes; sharing is disabled by user."""
import hashlib,json,shutil,zipfile
from pathlib import Path
BASE=Path('C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
WORK=Path('output/shop_translation_fix')
report=json.loads((WORK/'report.json').read_text(encoding='utf-8'))
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for rel,expected in report['source_sha256'].items():
    assert digest(BASE/rel)==expected,rel
    backup=WORK/'before'/rel;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(BASE/rel,backup)
for rel in report['source_sha256']:
    src=WORK/'staged'/rel
    if rel.startswith('mods/'):
        with zipfile.ZipFile(WORK/'before'/rel) as a,zipfile.ZipFile(src) as b:
            for name in a.namelist():
                if name!='assets/nsprefab/lang/zh_tw.json':assert a.read(name)==b.read(name),name
    shutil.copy2(src,BASE/rel);assert digest(src)==digest(BASE/rel)
print('Installed and read back',len(report['source_sha256']),'files')
