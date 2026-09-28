import re, json
from pathlib import Path
from opencc import OpenCC

root=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
cc=OpenCC('s2twp')
changed=0
for p in (root/'config/ftbquests/quests').rglob('*.snbt'):
    old=p.read_text(encoding='utf-8-sig')
    def cv(m):
        s=m.group(0)
        # Convert visible quoted text while preserving command strings and IDs.
        if re.search('[\u3400-\u9fff]',s) and not re.match(r'"/?(?:execute|give|tellraw|summon|kubejs|ftbquests)\s',s):
            return cc.convert(s)
        return s
    new=re.sub(r'"(?:\\.|[^"\\])*"',cv,old)
    if new!=old: p.write_text(new,encoding='utf-8'); changed+=1
print('normalized quest files',changed)
