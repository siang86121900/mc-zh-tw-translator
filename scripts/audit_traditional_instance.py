import json,re,zipfile,shutil,argparse
from pathlib import Path
from collections import Counter
from normalize_zh_tw import normalize_text
from mc_zh_tw_translator.translator import CTE2QuestTranslator

ap=argparse.ArgumentParser();ap.add_argument('--apply',action='store_true');a=ap.parse_args()
root=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
work=Path(__file__).resolve().parents[1]
backup=work/'output/VEFV2.7.1_traditional_backup'
stats=Counter();changes=[];errors=[]
sig=re.compile(r'^META-INF/[^/]+\.(SF|RSA|DSA|EC)$',re.I)
protected=re.compile(r'§[0-9a-fk-or]|&[0-9a-fk-or]|%(?:\d+\$)?[a-zA-Z%]|\$\([^)]*\)|\n')
def cv(s):
    if not re.search('[\u3400-\u9fff]',s):return s
    tokens=[]
    def hold(m):tokens.append(m[0]);return f'__KEEP_{len(tokens)-1}__'
    value=protected.sub(hold,s)
    for _ in range(4):
        converted=normalize_text(value)
        if converted==value:break
        value=converted
    for i,v in enumerate(tokens):value=value.replace(f'__KEEP_{i}__',v)
    return value
def node(v):
    if isinstance(v,str):return cv(v)
    if isinstance(v,list):return [node(x) for x in v]
    if isinstance(v,dict):return {k:node(x) for k,x in v.items()}
    return v
def convert(raw,name):
    stats['resources_scanned']+=1
    try:
        s=raw.decode('utf-8-sig')
        if name.lower().endswith('.json'):
            old=json.loads(CTE2QuestTranslator._strip_json_comments(s));new=node(old)
            if old==new:return raw
            return json.dumps(new,ensure_ascii=False,indent=2).encode()
        new=cv(s)
        return new.encode() if new!=s else raw
    except Exception as e:errors.append([name,str(e)]);return raw
def save(p,b):
    dest=backup/p.relative_to(root)
    if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    temp=p.with_name(p.name+'.tw-audit.tmp');temp.write_bytes(b);temp.replace(p)
def is_resource(n):
    n=n.lower()
    return (('/zh_tw/' in n or n.endswith('/zh_tw.json') or n.endswith('/zh_tw.lang')) and n.endswith(('.json','.txt','.lang'))) or ('/patchouli_books/' in n and n.endswith('/book.json'))
for folder,pattern in [('mods','*.jar'),('resourcepacks','*.zip')]:
    for p in sorted((root/folder).glob(pattern)):
        stats[folder+'_archives']+=1;edits={}
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if not is_resource(n):continue
                b=z.read(n);v=convert(b,n)
                if v!=b:edits[n]=v;changes.append([str(p.relative_to(root)),n])
            if edits and a.apply:
                dest=backup/p.relative_to(root)
                if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
                tmp=p.with_name(p.name+'.tw-audit.tmp')
                with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as w:
                    for item in z.infolist():
                        if sig.match(item.filename):continue
                        w.writestr(item,edits.get(item.filename,z.read(item.filename)))
        if edits and a.apply:tmp.replace(p)
        if edits:stats['archives_changed']+=1
for folder in ['kubejs','config','defaultconfigs','patchouli_books']:
    for p in (root/folder).rglob('*'):
        if not p.is_file():continue
        rel=p.relative_to(root).as_posix();stats['loose_files_examined']+=1
        raw=p.read_bytes() if is_resource('/'+rel) or p.suffix in ('.js','.snbt') or '/armorsets/' in rel else None
        if raw is None:continue
        if is_resource('/'+rel):new=convert(raw,rel)
        elif p.suffix=='.snbt' and '/ftbquests/' in rel:
            old=raw.decode('utf-8-sig')
            def quoted(m):
                return m[0] if re.match(r'"/?(?:execute|give|tellraw|summon|kubejs|ftbquests)\s',m[0]) else cv(m[0])
            new=re.sub(r'"(?:\\.|[^"\\])*"',quoted,old).encode()
            if new==old.encode():new=raw
        elif p.suffix=='.js':
            old=raw.decode('utf-8-sig')
            # Only explicit player-facing Text.of literals, not identifiers/logic.
            new=re.sub(r'(Text\.of\(\s*)([\x27"])(.*?)(\2)',lambda m:m[1]+m[2]+cv(m[3])+m[4],old).encode()
            if new==old.encode():new=raw
        elif '/armorsets/' in rel and p.suffix=='.json':
            d=json.loads(raw);old=json.dumps(d,ensure_ascii=False)
            def walk(v,key=''):
                if isinstance(v,dict):return {k:walk(x,k) for k,x in v.items()}
                if isinstance(v,list):return [walk(x,key) for x in v]
                return cv(v) if isinstance(v,str) and key in ('customTooltips','description') else v
            d=walk(d);new=json.dumps(d,ensure_ascii=False,indent=2).encode() if json.dumps(d,ensure_ascii=False)!=old else raw
        else:continue
        if new!=raw:
            changes.append([rel]);stats['loose_files_changed']+=1
            if a.apply:save(p,new)
result={'applied':a.apply,'stats':dict(stats),'changes':changes,'errors':errors}
(work/('instance_traditional_applied.json' if a.apply else 'instance_traditional_audit.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'stats':dict(stats),'changes':len(changes),'errors':errors},ensure_ascii=False))
