import json,zipfile,shutil,struct
from pathlib import Path
from full_translation_audit import parse
ROOT=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
BACK=Path(__file__).resolve().parents[1]/'output/VEFV2.7.1_full_audit_backup'
def rewrite(p,changes):
    backup=BACK/p.relative_to(ROOT)
    if not backup.exists():backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,backup)
    temp=p.with_suffix('.audit-fix.tmp')
    with zipfile.ZipFile(p) as z,zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as w:
        for info in z.infolist():
            from mc_zh_tw_translator.translator import is_jar_signature_file
            if not is_jar_signature_file(info.filename):w.writestr(info,changes.get(info.filename,z.read(info.filename)))
    temp.replace(p)
p=next((ROOT/'mods').glob('GameStages-*.jar'))
with zipfile.ZipFile(p) as z:
    n='assets/gamestages/lang/zh_tw.json';d=parse(z.read(n))
d['commands.gamestage.clear.sender']='已從 %2$s 清除 %1$d 個遊戲階段'
rewrite(p,{n:json.dumps(d,ensure_ascii=False,indent=2).encode()})
p=ROOT/'mods/item_split_bug_fix-1.20.1-1.2.jar'
n='com/iwaliner/item_split_bug_fix/ModCoreItemSplitBugFix.class'
with zipfile.ZipFile(p) as z:b=z.read(n)
old=b'has an empty NBT tag! This is a bug!'
new='含有空的 NBT 標籤！這是一個程式錯誤！'.encode('utf-8')
needle=b'\x01'+struct.pack('>H',len(old))+old
assert b.count(needle)==1,'Expected exactly one CONSTANT_Utf8 string'
b=b.replace(needle,b'\x01'+struct.pack('>H',len(new))+new)
rewrite(p,{n:b})
print('Fixed GameStages parameter ordering and Item Split Bug Fix display string')
