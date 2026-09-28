from pathlib import Path
import json,zipfile,struct,shutil,hashlib
BASE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
REL='mods/PasterDream-forge1.20.1-beta0.4.2.jar'
ENTRY='net/pasterdream/procedures/DyedreamCrackPr1Procedure.class'
PAIRS={
'§5身体从这个奇怪的空洞中穿过，但并没有什么反应。':'§5你的身體穿過這個奇怪的空洞，卻沒有發生任何反應。',
'§5你能感觉到这个类似裂隙一样的东西在与这个世界和另外一处地方交互，附近不同的环境可能正是因为此而诞生。':'§5你能感覺到，這道裂隙似乎連結著這個世界與另一個地方，附近異於周遭的環境或許正是因此形成的。',
'§5现在可能还不是时候，让我们交给在日夜轮转之间的时光中给予答案。':'§5現在或許還不是時候，就讓時間在日夜交替之間，慢慢揭曉答案吧。',
'一种神秘的力量阻止了你，或许可以想想通过别的办法回去...':'一股神祕的力量阻止了你，或許可以試著用其他方法回去……',
}
p=BASE/REL;backup=Path('output/VEFV2.7.1_pasterdream_backup')/REL
backup.parent.mkdir(parents=True,exist_ok=True)
if not backup.exists():shutil.copy2(p,backup)
with zipfile.ZipFile(p) as z:
 b=z.read(ENTRY)
 for old,new in PAIRS.items():
  old=old.encode();new=new.encode();needle=b'\x01'+struct.pack('>H',len(old))+old
  assert b.count(needle)==1
  b=b.replace(needle,b'\x01'+struct.pack('>H',len(new))+new)
 with zipfile.ZipFile(p.with_suffix('.translation.tmp'),'w',zipfile.ZIP_DEFLATED) as w:
  import re
  for info in z.infolist():
   if re.fullmatch(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)',info.filename,re.I):continue
   w.writestr(info,b if info.filename==ENTRY else z.read(info.filename))
p.with_suffix('.translation.tmp').replace(p)
pack=Path('output/VEFV2.7.1_繁體中文化補丁_20260910');shutil.copy2(p,pack/REL)
manifest=json.loads((pack/'檔案清單.json').read_text(encoding='utf-8'))
for r in manifest:
 if r['path']==REL:r.update(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),reason='中文語系、書本與裂隙事件四句硬編碼提示修正')
(pack/'檔案清單.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
readme=(pack/'安裝說明.txt').read_text(encoding='utf-8-sig').replace('及一處已確認的硬編碼提示翻譯','及已確認的硬編碼提示翻譯')
(pack/'安裝說明.txt').write_text(readme,encoding='utf-8-sig')
Path('output/pasterdream_crack_changes.json').write_text(json.dumps(PAIRS,ensure_ascii=False,indent=2),encoding='utf-8')
print('Patched four display constants; staged share package updated')
