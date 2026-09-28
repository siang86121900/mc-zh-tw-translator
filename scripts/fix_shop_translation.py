"""Stage reviewed display-only SDMShop conversions and structure-name aliases."""
import json,re,hashlib,shutil,zipfile
from pathlib import Path
from opencc import OpenCC

BASE=Path('C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
OUT=Path('output/shop_translation_fix'); OUT.mkdir(parents=True,exist_ok=True)
CC=OpenCC('s2twp')
STRING=r'"(?:\\.|[^"\\])*"'
changes=[]
def convert(s):
    s=CC.convert(s)
    for a,b in {'貨幣轉換':'貨幣兌換','房產置辦':'房屋購置','精緻儲存部件':'精緻儲存零件','瑞士卷':'瑞士捲','右擊':'按右鍵','回覆其使用次數':'恢復其使用次數','永珍':'萬象'}.items(): s=s.replace(a,b)
    for a,b in {'遠端攻擊':'遠程攻擊','遠端發射':'遠距離發射','按右鍵它':'對它按右鍵','其它':'其他','災變boss':'災變首領','對應boss':'對應首領','末影龍':'終界龍','按住Alt+滾輪':'按住 Alt 並滾動滑鼠滾輪','右鍵空氣':'對著空氣按右鍵','潛行右鍵地面':'蹲下並對地面按右鍵','右鍵地面':'對地面按右鍵','烈焰人':'烈焰使者','一個雕刻過的南瓜':'一個雕刻南瓜'}.items():s=s.replace(a,b)
    return s
rel='config/SDMShop/sdmshop.snbt'
original=(BASE/rel).read_text(encoding='utf-8-sig')
def replace(m):
    prefix,raw=m[1],m[2]
    value=json.loads(raw)
    if prefix.strip().startswith('Name:'):
        try:
            obj=json.loads(value)
            if not isinstance(obj,dict) or not isinstance(obj.get('text'),str):return m[0]
            obj['text']=convert(obj['text']);new=json.dumps(obj,ensure_ascii=False,separators=(',',':'))
        except ValueError:return m[0]
    else:new=convert(value)
    if new!=value: changes.append(dict(source=rel,before=value,after=new))
    return prefix+json.dumps(new,ensure_ascii=False)
updated=re.sub(r'((?:title|subtitle|Name):\s*)('+STRING+')',replace,original)
def desc(m):
    return re.sub(STRING,lambda s: replace(type('M',(),{'__getitem__':lambda self,k: {0:s[0],1:'',2:s[0]}[k]})()),m[0])
updated=re.sub(r'description:\s*\[(?:'+STRING+r'|[^"\]])*\]',desc,updated)
# Only quoted display values may change; all numbers, keys, and structure IDs stay identical.
assert re.sub(STRING,'""',original)==re.sub(STRING,'""',updated)
assert re.findall(r'StructureName:\s*('+STRING+')',original)==re.findall(r'StructureName:\s*('+STRING+')',updated)
p=OUT/'staged'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(updated,encoding='utf-8')
aliases={};conflicts=[]
for f in [BASE/rel,*sorted((BASE/'config/ftbquests/quests').rglob('*.snbt'))]:
    s=updated if f==BASE/rel else f.read_text(encoding='utf-8-sig')
    for m in re.finditer(r'StructureName:\s*("[^"\n]+")(?:(?!StructureName:).){0,1200}?\bName:\s*('+STRING+')',s,re.S):
        sid=json.loads(m[1]);obj=json.loads(json.loads(m[2]));name=convert(obj.get('text',''))
        if not name:continue
        key='item.nsprefab.'+sid
        if key in aliases and aliases[key]!=name:conflicts.append([key,aliases[key],name]);continue
        aliases[key]=name
assert aliases.get('item.nsprefab.starterhouse_08v2')=='瑞士捲小屋'
jar=BASE/'mods/nsprefab-1.20.1-1.4.3.jar'
with zipfile.ZipFile(jar) as z:
    lang=json.loads(z.read('assets/nsprefab/lang/zh_tw.json'))
    lang.update(aliases)
    dest=OUT/'staged/mods'/jar.name;dest.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as w:
        for i in z.infolist():
            if re.match(r'META-INF/.*\.(SF|RSA|DSA|EC)$',i.filename,re.I):continue
            data=z.read(i.filename)
            if i.filename=='assets/nsprefab/lang/zh_tw.json': data=json.dumps(lang,ensure_ascii=False,indent=2).encode()
            w.writestr(i,data)
report=dict(changes=changes,structure_aliases=aliases,conflicts=conflicts,source_sha256={rel:hashlib.sha256((BASE/rel).read_bytes()).hexdigest(),'mods/'+jar.name:hashlib.sha256(jar.read_bytes()).hexdigest()})
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('display changes',len(changes),'structure aliases',len(aliases),'conflicts',len(conflicts))
