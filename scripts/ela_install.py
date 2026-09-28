"""Install only hash-verified ELA translations after successful validation."""
import hashlib,json,subprocess
from pathlib import Path
BASE=Path('C:/Users/User/curseforge/minecraft/Instances/ELA').resolve()
OUT=Path('output/ELA');BACK=Path('input/ELA');STAGE=OUT/'staged'
def sha(b):return hashlib.sha256(b).hexdigest()
assert json.loads((OUT/'validation.json').read_text(encoding='utf-8'))['ok']
proc=subprocess.run(['powershell','-NoProfile','-Command','@(Get-Process java,javaw -ErrorAction SilentlyContinue).Count'],capture_output=True,text=True)
assert proc.returncode==0 and proc.stdout.strip()=='0','Minecraft/Java must be closed before install'
rows=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
# Preflight every file before the first write.
for r in rows:
    p=BASE/r['path'];assert p.resolve().is_relative_to(BASE)
    assert (sha(p.read_bytes()) if p.exists() else None)==r['before_sha256'],('live source changed',r['path'])
    assert sha((STAGE/r['path']).read_bytes())==r['after_sha256']
for r in rows:
    p=BASE/r['path'];p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((STAGE/r['path']).read_bytes())
    assert sha(p.read_bytes())==r['after_sha256']
options=BASE/'options.txt';old=options.read_bytes();backup=BACK/'options.txt'
if not backup.exists():backup.write_bytes(old)
assert backup.read_bytes()==old
import re
new=re.sub(rb'(?m)^lang:[^\r\n]*',b'lang:zh_tw',old)
assert b'lang:zh_tw' in new
options.write_bytes(new);assert options.read_bytes()==new
rows.append(dict(path='options.txt',before_sha256=sha(old),after_sha256=sha(new),size=len(new)))
(OUT/'installed.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print('Installed and read-back verified',len(rows),'files. Language: zh_tw')
