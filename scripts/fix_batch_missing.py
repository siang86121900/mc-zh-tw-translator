import json, zipfile, re
from pathlib import Path
from mc_zh_tw_translator.translator import ReferencePackDB

root = Path(__file__).resolve().parents[1]
db = ReferencePackDB(root/'data')
db.load_all()
db.set_namespace('largemeals')
values = ['生羊肋排','熟羊肋排','河豚高湯','馬鈴薯湯','紅湯','番茄蛋花湯','豪華鱈魚餐','豐盛午餐','咖哩雞','蘑菇醬義大利麵','蛋包飯','一碗蛋包飯','蘑菇酥皮派','一盤蘑菇酥皮派','烤羊肋排','一盤烤羊肋排','甜莓卡士達','米布丁','羊肉屠夫','使用小刀從羊身上取得羊肋排']
for pattern in ('largemeals*.jar', 'ftb-quests*.jar'):
    p = next((root/'output/2026-09-09/mods').glob(pattern))
    with zipfile.ZipFile(p) as z:
        contents = {n:z.read(n) for n in z.namelist()}
    if pattern.startswith('largemeals'):
        en = json.loads(contents['assets/largemeals/lang/en_us.json'])
        assert len(en) == len(values)
        name = 'assets/largemeals/lang/zh_tw.json'
        contents[name] = json.dumps({k:db.lookup(k) or v for k,v in zip(en,values)},ensure_ascii=False,indent=2).encode()
    else:
        name = 'assets/ftbquests/lang/zh_tw.json'
        data = json.loads(contents[name])
        data['ftbquests.reward.blocked'] = '已封鎖隊伍「%2$s」的 %1$d 種獎勵'
        contents[name] = json.dumps(data,ensure_ascii=False,indent=2).encode()
    temp=p.with_suffix('.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for n,b in contents.items():
            if not re.match(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)$',n,re.I): z.writestr(n,b)
    temp.replace(p)
print('Repaired missing language and FTB Quests placeholders')
