"""Rebuild the verified staged translation share, checking every payload hash."""
from pathlib import Path
import collections,hashlib,json,re,zipfile
p=Path('output/VEFV2.7.1_繁體中文化補丁_20260910')
assert '驗證通過' in Path('output/translation_share_verify.log').read_text(encoding='utf-8-sig')
m=json.loads((p/'檔案清單.json').read_text(encoding='utf-8'));counts=collections.Counter(x['path'].split('/')[0] for x in m)
readme=(p/'安裝說明.txt').read_text(encoding='utf-8-sig')
readme=re.sub(r'收錄 \d+ 個修改過的 JAR',f"收錄 {counts['mods']} 個修改過的 JAR",readme)
readme=re.sub(r'KubeJS 檔案 \d+ 個，config 檔案 \d+ 個',f"KubeJS 檔案 {counts['kubejs']} 個，config 檔案 {counts['config']} 個",readme)
if '本次追加修正' not in readme:
 readme+='\n本次追加修正\n已加入 PasterDream 裂隙事件的四句提示，以及其他 1,085 處\n硬編碼顯示文字、動態組句與設定說明。包含 14 個模組的修正。\n'
(p/'安裝說明.txt').write_text(readme,encoding='utf-8-sig')
archive=Path(str(p)+'.zip');temp=Path(str(archive)+'.building')
with zipfile.ZipFile(temp,'w',allowZip64=True) as z:
 for f in sorted(p.rglob('*')):
  if f.is_file():z.write(f,f.relative_to(p).as_posix(),compress_type=zipfile.ZIP_STORED if f.suffix=='.jar' else zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(temp) as z:
 assert set(z.namelist())=={x['path'] for x in m}|{'安裝說明.txt','檔案清單.json'}
 for x in m:
  h=hashlib.sha256()
  with z.open(x['path']) as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  assert h.hexdigest()==x['sha256'],x['path']
temp.replace(archive)
h=hashlib.sha256()
with archive.open('rb') as f:
 for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
Path(str(archive)+'.sha256').write_text(h.hexdigest()+'  '+archive.name+'\n',encoding='utf-8')
summary=dict(files=len(m),counts=dict(counts),bytes=archive.stat().st_size,sha256=h.hexdigest())
Path('output/translation_share_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
