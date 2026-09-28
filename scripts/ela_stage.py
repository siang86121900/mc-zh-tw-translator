"""ELA-specific offline staging; never writes the live instance or calls a service."""
import collections, gzip, hashlib, json, re, struct, zipfile
from pathlib import Path
from opencc import OpenCC
from full_translation_audit import parse, leaves, at

BASE=Path('C:/Users/User/curseforge/minecraft/Instances/ELA')
OUT=Path('output/ELA'); STAGE=OUT/'staged'; STAGE.mkdir(parents=True,exist_ok=True)
CC=OpenCC('s2twp'); HAN=re.compile('[\u3400-\u9fff]')
REF=json.loads(Path('data/ref_pack_scoped.json').read_text(encoding='utf-8'))
CFPA=json.loads(Path('data/cfpa_scoped.json').read_text(encoding='utf-8'))
EXTERNAL={}
for root in ('config/openloader/resources','kubejs/assets'):
    for p in (BASE/root).rglob('zh_cn.json'):
        m=re.search(r'assets/([^/]+)/lang/zh_cn.json$',p.as_posix())
        if m:
            try:EXTERNAL.setdefault(m[1],{}).update(parse(p.read_bytes()))
            except Exception:pass
CHANGES=[]; PENDING=[]; ALIASES={}
MANUAL=dict(line.split('\t',1) for line in (OUT/'manual.tsv').read_text(encoding='utf-8').splitlines() if '\t' in line) if (OUT/'manual.tsv').exists() else {}
TERMS={'鼠標':'滑鼠','服務器':'伺服器','屏幕':'畫面','默認':'預設','加載':'載入','信息':'資訊','概率':'機率','幾率':'機率','暴擊':'爆擊','冷卻縮減':'冷卻時間縮短','爬行者':'苦力怕','爬山虎':'苦力怕','末影龍':'終界龍','末影珍珠':'終界珍珠','末地':'終界','下界':'地獄','烈焰人':'烈焰使者','凋靈':'凋零怪','凋零骷髏':'凋零骷髏','潛行':'蹲下','附魔':'附魔','耐久度':'耐久度','永珍':'萬象','治療立場':'治療力場','回覆生命':'恢復生命','其它':'其他','文件夾':'資料夾','按鍵綁定':'按鍵設定','生物群系':'生態域','群系':'生態域'}
PROTECTED=re.compile(r'(?:https?://\S+|[§&][0-9a-fk-or]|%(?:\d+\$)?[-#+0,(]*\d*(?:\.\d+)?[a-zA-Z%]|\$\([^)]*\)|\$\{[^}]*\}|\{[a-zA-Z_][^{}]*\}|\\[nrt]|\n|\b[a-z0-9_.-]+:[a-z0-9_/.-]+\b)',re.I)
def convert(s):
    if not isinstance(s,str):return s
    tokens=[]
    def protect(m):tokens.append(m[0]);return f'ZZTOKEN{len(tokens)-1}ZZ'
    t=PROTECTED.sub(protect,s);t=CC.convert(t)
    for a,b in TERMS.items():t=t.replace(a,b)
    t=re.sub(r'\bBoss\b','首領',t,flags=re.I)
    for i,v in enumerate(tokens):t=t.replace(f'ZZTOKEN{i}ZZ',v)
    return MANUAL.get(s,t)
def tokens(s):return PROTECTED.findall(s)
def record(source,key,before,after,origin):
    if before==after:return
    if isinstance(before,str) and tokens(before)!=tokens(after):
        raise ValueError(('protected tokens changed',source,key,before,after))
    CHANGES.append(dict(source=source,key=str(key),before=before,after=after,origin=origin,review='automatic_pending_context_review',fingerprint=hashlib.sha256(json.dumps([source,str(key),before,after],ensure_ascii=False).encode()).hexdigest()))
def save(rel,data):
    p=STAGE/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
def dumps(obj):return (json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
def component(value):
    if isinstance(value,dict):
        return {k:convert(v) if k=='text' and isinstance(v,str) else component(v) if k in ('extra','with','contents') else v for k,v in value.items()}
    if isinstance(value,list):return [component(v) for v in value]
    if isinstance(value,str):return convert(value)
    return value
def display(s):
    if s.lstrip().startswith(('{','[')):
        try:return json.dumps(component(json.loads(s)),ensure_ascii=False,separators=(',',':'))
        except ValueError:return s
    return convert(s)
def lang_group(label,langs,namespace):
    en,cn,tw=(langs.get(x,{}) for x in ('en_us','zh_cn','zh_tw'))
    result=dict(tw)
    for k in sorted(set(en)|set(cn)|set(tw)):
        old=tw.get(k);english=en.get(k);chinese=cn.get(k) or EXTERNAL.get(namespace,{}).get(k);value=old;origin='existing_zh_tw'
        # Same-source CN wins over an English/mixed or simplified existing value.
        valid=isinstance(old,str) and HAN.search(old) and convert(old)==old
        if not valid:
            if isinstance(chinese,str) and HAN.search(chinese):value=convert(chinese);origin='same_source_zh_cn'
            elif isinstance(old,str) and HAN.search(old):value=convert(old)
            else:
                value=REF.get(namespace,{}).get(k) or CFPA.get(namespace,{}).get(k) or old or english or chinese
                origin='namespace_reference'
                if isinstance(value,str):value=convert(value)
        if isinstance(value,str):
            src=chinese if origin=='same_source_zh_cn' else english
            if isinstance(src,str) and tokens(src)!=tokens(value):
                if isinstance(chinese,str) and tokens(chinese)==tokens(src):value=convert(chinese);origin='same_source_zh_cn_format_fallback'
                else:value=src;PENDING.append(dict(source=label,key=k,reason='reference_format_mismatch',text=src))
            if value in MANUAL:value=MANUAL[value];origin='manual'
            if not HAN.search(value) and re.search('[A-Za-z]{3}',value):PENDING.append(dict(source=label,key=k,reason='english_or_proper_name',text=value))
        result[k]=value
        # Existing bad formatting is repaired against the source, not retained.
        if old!=value:
            CHANGES.append(dict(source=label,key=k,before=old,after=value,origin=origin,review='automatic_pending_context_review',fingerprint=hashlib.sha256(json.dumps([label,k,old,value],ensure_ascii=False).encode()).hexdigest()))
    return result

def resources(label,names,read):
    updates={};groups={}
    for n in sorted(names):
        m=re.search(r'(assets/([^/]+)/lang/)(en_us|zh_cn|zh_tw)\.json$',n,re.I)
        if m:groups.setdefault((n[:m.start(3)],m[2]),{})[m[3].lower()]=n
    for (prefix,ns),paths in groups.items():
        langs={}
        for lang,n in paths.items():
            b=read(n)
            if not b.strip():langs[lang]={};continue
            try:langs[lang]=parse(b)
            except Exception as e:PENDING.append(dict(source=label+'!/'+n,reason='parse_error',error=str(e)))
        result=lang_group(label+'!/'+prefix+'zh_tw.json',langs,ns)
        if result and result!=langs.get('zh_tw'):updates[prefix+'zh_tw.json']=dumps(result)
    # Books: retain non-display fields and same-language topology.
    bookgroups={}
    for n in sorted(names):
        if re.search(r'/(patchouli_books|books?|guidebook)/',n) and n.endswith(('.json','.txt')):
            m=re.search(r'/(en_us|zh_cn|zh_tw)/',n)
            if m:bookgroups.setdefault(n[:m.start()]+'/zh_tw/'+n[m.end():],{})[m[1]]=n
    for target,paths in bookgroups.items():
        source=paths.get('zh_cn') or paths.get('en_us') or paths.get('zh_tw')
        if target.endswith('.txt'):
            raw=read(source).decode('utf-8-sig');new=convert(raw);updates[target]=new.encode();record(label+'!/'+target,'text',raw,new,'book_source');continue
        try:obj=parse(read(source))
        except Exception as e:PENDING.append(dict(source=label+'!/'+source,reason='book_parse',error=str(e)));continue
        def walk(v,path=()):
            if isinstance(v,dict):return {k:convert(x) if k in {'name','title','text','subtitle','landing_text'} and isinstance(x,str) else walk(x,path+(k,)) for k,x in v.items()}
            if isinstance(v,list):return [walk(x,path+(i,)) for i,x in enumerate(v)]
            return v
        new=walk(obj);updates[target]=dumps(new)
        for path,_,v in leaves(obj):record(label+'!/'+target,path,v,at(new,path),'book_source')
    return updates

def jars():
    for jar in sorted((BASE/'mods').glob('*.jar')):
        with zipfile.ZipFile(jar) as z:
            updates=resources('mods/'+jar.name,set(z.namelist()),z.read)
            updates={k:v for k,v in updates.items() if k not in z.namelist() or z.read(k)!=v}
            if not updates:continue
            dest=STAGE/'mods'/jar.name;dest.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as w:
                for i in z.infolist():
                    if re.match(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)$',i.filename,re.I):continue
                    w.writestr(i,updates.pop(i.filename,z.read(i.filename)))
                for n,b in updates.items():w.writestr(n,b)

STRING=r'"(?:\\.|[^"\\])*"'
def snbt_text(text,label):
    def repl(m):
        s=json.loads(m[2]);new=display(s);record(label,m[1].strip(),s,new,'display_field');return m[1]+(json.dumps(new,ensure_ascii=False) if new!=s else m[2])
    text=re.sub(r'((?<![\w])(?:title|subtitle|description|text|Name|displayName):\s*)('+STRING+')',repl,text)
    def arr(m):
        def r(s):
            old=json.loads(s[0]);new=display(old);record(label,m[1],old,new,'display_array');return json.dumps(new,ensure_ascii=False) if new!=old else s[0]
        return m[1]+re.sub(STRING,r,m[2])
    text=re.sub(r'((?:description|Lore|lore|customTooltips):\s*)(\[(?:'+STRING+r'|[^"\]])*\])',arr,text)
    return text

def nbt(raw,label):
    compressed=raw.startswith(b'\x1f\x8b');b=gzip.decompress(raw) if compressed else raw;pos=0
    def take(n):
        nonlocal pos
        r=b[pos:pos+n];pos+=n;assert len(r)==n;return r
    def string():
        head=take(2);return head+take(struct.unpack('>H',head)[0])
    def val(tag,path):
        if tag in (1,2,3,4,5,6):return take({1:1,2:2,3:4,4:8,5:4,6:8}[tag])
        if tag==8:
            s=string();old=s[2:].decode('utf-8');field=path[-1] if path else '';new=old
            if field in ('title','subtitle','description','Name','Lore','name','tooltip_list') and HAN.search(old):new=display(old)
            elif field in ('nbt','tag') and HAN.search(old):new=snbt_text(old,label+str(path))
            record(label,path,old,new,'binary_display');v=new.encode('utf-8');return struct.pack('>H',len(v))+v
        if tag==9:
            head=take(5);kind=head[0];count=struct.unpack('>i',head[1:])[0];assert 0<=count<1000000
            return head+b''.join(val(kind,path) for _ in range(count))
        if tag==10:
            out=b''
            while True:
                t=take(1);out+=t
                if t==b'\0':return out
                name=string();out+=name+val(t[0],path+(name[2:].decode('utf-8'),))
        if tag in (7,11,12):
            head=take(4);count=struct.unpack('>i',head)[0];assert 0<=count<1000000
            return head+take(count*{7:1,11:4,12:8}[tag])
        raise ValueError(tag)
    tag=take(1);name=string();result=tag+name+val(tag[0],());assert pos==len(b)
    return raw if result==b else gzip.compress(result,mtime=0) if compressed else result

def scripts(text,label):
    # Lexical replacement is limited to verified display call/field contexts.
    token=re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|`(?:\\.|[^`\\])*`')
    def replace(m):
        raw=m[0]
        if raw.startswith(('/',)):return raw
        old=raw[1:-1]
        if not HAN.search(old):return raw
        prefix=text[max(0,m.start()-100):m.start()]
        if re.search(r'(?:translate|translatable)\(\s*$',prefix):
            ALIASES[old]=convert(old);return raw
        safe=re.search(r'(?:Text\.[A-Za-z]+|Component\.(?:literal|of)|\.displayName|\.append|\.tell|\.setStatusMessage)\(\s*$',prefix) or re.search(r'\b(?:name|condition|label)\s*:\s*$',prefix)
        if label=='kubejs/client_scripts/spell/food_effects.js' and re.search(r'\battribute\s*:\s*$',prefix):safe=True
        if label=='kubejs/client_scripts/scroll.js' and old in ('${colorMap.common}初阶法术','${colorMap.uncommon}中阶法术','${colorMap.epic}高阶法术','§e此法术可升级'):safe=True
        if not safe:
            PENDING.append(dict(source=label,key=text.count('\n',0,m.start())+1,reason='script_context',text=old));return raw
        new=convert(old);record(label,text.count('\n',0,m.start())+1,old,new,'verified_display_context')
        return raw[0]+new+raw[-1]
    return token.sub(replace,text)

def loose():
    files={p.relative_to(BASE).as_posix():p for root in ('kubejs','config','defaultconfigs','resourcepacks','patchouli_books') for p in (BASE/root).rglob('*') if p.is_file() and p.suffix not in ('.zip','.jar')}
    for n,b in resources('instance',set(files),lambda n:files[n].read_bytes()).items():save(n,b)
    for n,p in files.items():
        original=p.read_bytes();new=original
        if p.suffix=='.js':new=scripts(original.decode('utf-8-sig'),n).encode('utf-8')
        elif p.suffix=='.snbt':new=snbt_text(original.decode('utf-8-sig'),n).encode('utf-8')
        elif p.suffix=='.data' and '/SDMShop/shops/' in n:new=nbt(original,n)
        elif p.suffix=='.json' and '/lang/' not in n and re.search(r'/(?:patchouli_books|books?|guidebook)/',n) is None:
            try:obj=parse(original)
            except Exception:continue
            def walk(v,path=()):
                if isinstance(v,dict):
                    result={}
                    for k,x in v.items():
                        if isinstance(x,str) and k in {'text','title','subtitle','description','landing_text','displayName','customTooltips'} and HAN.search(x):
                            new=convert(x);record(n,path+(k,),x,new,'json_display');result[k]=new
                        else:result[k]=walk(x,path+(k,))
                    return result
                if isinstance(v,list):return [walk(x,path+(i,)) for i,x in enumerate(v)]
                return v
            obj2=walk(obj)
            if obj!=obj2:new=dumps(obj2)
        if new!=original:save(n,new)
    if ALIASES:
        rel='kubejs/assets/kubejs/lang/zh_tw.json';p=STAGE/rel;obj=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {};obj.update(ALIASES);save(rel,dumps(obj))

if __name__=='__main__':
    jars();loose()
    for name,rows in [('changes.jsonl',CHANGES),('stage_pending.jsonl',PENDING)]:
        (OUT/name).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
    print(json.dumps(dict(changes=len(CHANGES),pending=len(PENDING),files=sum(1 for p in STAGE.rglob('*') if p.is_file()),origins=dict(collections.Counter(x['origin'] for x in CHANGES))),ensure_ascii=False))
