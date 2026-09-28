import json,re,zipfile,shutil
from pathlib import Path
from collections import Counter
from mc_zh_tw_translator.translator import ReferencePackDB,CTE2QuestTranslator
from normalize_zh_tw import normalize_text
ROOT=Path(__file__).resolve().parents[1];BASE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
BACK=ROOT/'output/VEFV2.7.1_20260910_backup';REPORT=ROOT/'output/VEFV2.7.1_20260910_report.json'
db=ReferencePackDB(ROOT/'data');db.load_all();counts=Counter();changes=[];remaining=[];errors=[]
def pairs(s):return dict(x.split('|',1) for x in s.splitlines() if x)
materials=pairs('''Dark Oak|黑橡木
Oak|橡木
Spruce|杉木
Birch|樺木
Jungle|叢林木
Acacia|相思木
Cherry|櫻花木
Mangrove|紅樹林木
Bamboo|竹製
Crimson|緋紅蕈木
Warped|扭曲蕈木
Quartz|石英
Light Gray|淺灰色
Light Blue|淺藍色
Black|黑色
Blue|藍色
Brown|棕色
Cyan|青色
Gray|灰色
Green|綠色
Lime|淺綠色
Magenta|洋紅色
Orange|橙色
Pink|粉紅色
Purple|紫色
Red|紅色
White|白色
Yellow|黃色''')
furniture=pairs('''Bench|長凳
Chair|椅子
Counter|流理臺
Counter Sink|水槽流理臺
Sink Counter|水槽流理臺
Counter Storage|收納流理臺
Storage Counter|收納流理臺
Desk|書桌
Drawer|抽屜櫃
Fireplace|壁爐
Grandfather Clock|落地鐘
Lamp|燈
Mirror|鏡子
Mirror Stand|立鏡
Pillow|枕頭
Plank|木板
Sofa|沙發
Stacked Pillows|堆疊枕頭
Stump|樹樁
Stump Table|樹樁桌
Table|桌子
Tent|帳篷
Wall Clock|掛鐘''')
manual=pairs('''Crimson Large Fungus|巨型緋紅蕈菇
Warped Large Fungus|巨型扭曲蕈菇
Sink Turned On|水龍頭：開啟
Clock Entity|時鐘
Clock ticking...|時鐘滴答作響……
Brick Chimney|紅磚煙囪
Cobblestone Chimney|鵝卵石煙囪
Stonebrick Chimney|石磚煙囪
Netherbrick Chimney|地獄磚煙囪
Ceiling Fan Oak|橡木吊扇
Grandfather Clock Night Tune|落地鐘：夜間報時
Large Fungus|巨型蕈菇
Light Beyond|彼方之光
Light House|燈塔
Merchant Rug|商人地毯
Midnight|午夜報時
Mushroom|蘑菇
Running Water|流水聲
Seat|座位
Seat Spawn Egg|座位生成蛋
Spy Glass|望遠鏡
Telescope|望遠鏡
Tick|滴答聲
Unknown|佚名
World Map|世界地圖
cutting|切割聲
Netherite Bell|獄髓鐘
Gilded Netherite Shield|鍍金獄髓盾牌
Crushed Withered Debris|粉碎凋零殘骸
Netherite Scrap Nugget|獄髓碎料粒
Netherite Scrap Ingot|獄髓碎料錠
Withered Blackstone Vertical Slab|凋零黑石直立半磚
Cracked Withered Blackstone Vertical Slab|裂紋凋零黑石直立半磚
Warped Nether Brick Vertical Slab|扭曲地獄磚直立半磚
Saving Private Swine|搶救豬布林
Rescue a Piglin Prisoner|救出一名豬布林囚犯
Appears in %1$s mod|來自 %1$s 模組
Small Plated Pineapple Pie Side Block|小盤鳳梨派切片
Small Plated Pineapple Cake Slice Block|小盤鳳梨蛋糕切片
Bowl of Gleaming Salad Block|一碗閃耀沙拉
Onion Soup Block|洋蔥湯
Small Plated Pumpkin Pie Slice Block|小盤南瓜派切片
Plated Bacon-Wrapped Sausage on a Stick|盤裝培根香腸串
Clam Bake Block|烤蛤蜊
Clam Chowder Block|蛤蜊巧達濃湯
Coconut Milk Block|椰奶
Coconut Pudding Block|椰子布丁
Coral Crunch Block|珊瑚脆餅
Kelp Shake Block|海帶奶昔
Bisque Block|海鮮濃湯
Plated Fish Stick Block|盤裝魚條
Plated Frog Leg Kebab Block|盤裝蛙腿烤串
Plated Shrimp Skewer Block|盤裝烤蝦串
Plated Squid Kebab Block|盤裝魷魚烤串
Plated Stuffed Nautilus Shell Block|盤裝釀鸚鵡螺
Seafood Gumbo Block|海鮮秋葵濃湯
Shrimp Fried Rice Block|蝦仁炒飯
Surf 'n Turf Block|海陸大餐
Ground Strider Block|烤熾足獸
Plated Nether Skewer Block|盤裝地獄烤串
Plate Of Stuffed Hoglin Ham Block|盤裝釀豬布獸火腿
Plate Of Stuffed Hoglin Roast Block|盤裝釀烤豬布獸
Plate Of Stuffed Hoglin Snout Block|盤裝釀豬布獸鼻
Strider Moss Stew Block|熾足獸苔蘚燉湯
Warped Moldy Meat Block|扭曲霉肉
Food block items can be obtained by breaking placed food blocks with silk touch tools, or buying from wandering trader.|使用附有絲綢之觸的工具破壞已擺放的食物方塊，或向流浪商人購買，即可取得食物方塊物品。
A decorative item where you can place on finger foods from Farmer's Delight and other add-ons|可擺放 Farmer's Delight 與其他附加模組中小點心的裝飾餐盤。
A decorative item where you can place on smaller finger foods from Farmer's Delight and other add-ons.|可擺放 Farmer's Delight 與其他附加模組中較小點心的裝飾餐盤。''')
def zh(s):return isinstance(s,str) and bool(re.search('[\u3400-\u9fff]',s))
def parse(b):
    s=CTE2QuestTranslator._strip_json_comments(b.decode('utf-8-sig'))
    try:return json.loads(s,strict=False)
    except json.JSONDecodeError:
        # Remove trailing commas outside quoted strings in lenient mod JSON.
        s=re.sub(r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',lambda m:m[0] if m[0].startswith('"') else '',s)
        return json.loads(s,strict=False)
def tokens(s):return Counter(re.findall(r'%(?:\d+\$)?[sdif%]|§[0-9a-fk-or]|\$\([^)]*\)|\n',s))
targets={'cozy_home','bygonenether','displaydelight'}
def fill(en,tw,cn,ns,label):
    db.set_namespace(ns);new=dict(tw)
    for k,v in en.items():
        if not isinstance(v,str) or zh(tw.get(k)):continue
        if k.startswith('itemGroup.') or (ns=='cozy_home' and v.startswith('Cozy Home')):continue
        candidate=None;source=None
        for s,tag in [(cn.get(k),'same_jar_zh_cn'),(db.lookup(k),'namespace_reference')]:
            if zh(s) and tokens(v)==tokens(s):candidate=normalize_text(s);source=tag;break
        if candidate is None and ns in targets:
            if v in manual:candidate=manual[v];source='manual_from_english'
            elif ns=='cozy_home':
                if v in furniture:candidate=furniture[v];source='manual_from_english'
                for prefix,chinese in materials.items():
                    if v.startswith(prefix+' ') and v[len(prefix)+1:] in furniture:
                        candidate=chinese+furniture[v[len(prefix)+1:]];source='manual_from_english';break
        if candidate is not None and tokens(candidate)==tokens(v):
            new[k]=candidate
            if tw.get(k)!=candidate:counts[source]+=1;changes.append([label,k,v,candidate,source])
        elif ns in targets and re.search('[A-Za-z]{3}',v):remaining.append([label,k,v,tw.get(k)])
    return new
def backup(p):
    dest=BACK/p.relative_to(BASE)
    if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
for p in sorted((BASE/'mods').glob('*.jar')):
    edits={};counts['jars_scanned']+=1
    with zipfile.ZipFile(p) as z:
        names=set(z.namelist())
        for n in names:
            if not re.match(r'^assets/[^/]+/lang/en_us.json$',n):continue
            try:
                ns=n.split('/')[1];target=n.replace('en_us','zh_tw');c=n.replace('en_us','zh_cn')
                en=parse(z.read(n));tw=parse(z.read(target)) if target in names else {};cn=parse(z.read(c)) if c in names else {}
                new=fill(en,tw,cn,ns,p.name+':'+n);counts['language_files_scanned']+=1
                if new!=tw:edits[target]=json.dumps(new,ensure_ascii=False,indent=2).encode()
            except Exception as e:errors.append([p.name,n,str(e)])
        if edits:
            backup(p);temp=p.with_suffix('.sept10.tmp')
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as w:
                for info in z.infolist():
                    if re.match(r'^META-INF/[^/]+\.(SF|RSA|DSA|EC)$',info.filename,re.I):continue
                    w.writestr(info,edits.pop(info.filename,z.read(info.filename)))
                for n,b in edits.items():w.writestr(n,b)
    if 'temp' in locals() and temp.exists():temp.replace(p);counts['jars_changed']+=1
for p in (BASE/'kubejs/assets').glob('*/lang/en_us.json'):
    target=p.with_name('zh_tw.json');cp=p.with_name('zh_cn.json')
    en=parse(p.read_bytes());tw=parse(target.read_bytes()) if target.exists() else {};cn=parse(cp.read_bytes()) if cp.exists() else {}
    new=fill(en,tw,cn,p.parent.parent.name,str(p.relative_to(BASE)))
    if new!=tw:
        if target.exists():backup(target)
        target.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8');counts['kubejs_changed']+=1
REPORT.write_text(json.dumps({'counts':dict(counts),'changes':changes,'target_remaining':remaining,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'counts':dict(counts),'remaining':remaining,'errors':errors},ensure_ascii=False))
