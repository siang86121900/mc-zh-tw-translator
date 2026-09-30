"""Read-only inventory and fail-closed, fingerprinted translation review gate."""
import argparse, hashlib, json, re, struct, zipfile, gzip, io
from collections import Counter, defaultdict
from pathlib import Path
from mc_zh_tw_translator.translator import CTE2QuestTranslator, PATCHOULI_SKIP_FIELDS
from opencc import OpenCC
from mc_zh_tw_translator.class_text import proven_strings, config_tooltips
from mc_zh_tw_translator import quest_lang

HAN=re.compile('[\u3400-\u9fff]'); LATIN=re.compile('[A-Za-z]{3,}')
# FTB Quests keeps quest text in config/ftbquests/quests/lang/<locale>.snbt (see quest_lang).
LANG=re.compile(r'^(.*?/lang/)(en_us|zh_tw|zh_cn)\.(json|lang)$|^(.*?/ftbquests/quests/lang/)(en_us|zh_tw|zh_cn)\.(snbt)$',re.I)

def lang_parts(m):
    """(folder, language, extension) of a LANG match, whichever of its two forms matched."""
    return (m[1],m[2],m[3]) if m[1] is not None else (m[4],m[5],m[6])
BOOK=re.compile(r'/(?:patchouli_books|books?|guidebook)/',re.I)
DISPLAY={'name','Name','text','title','subtitle','description','landing_text','header','customTooltips','displayName','tooltip','label','message','lore','Lore'}
CC=OpenCC('s2twp')

def decode(b):
    return b.decode('utf-16' if b.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')

def parse_binary_nbt(data):
    """Read configuration NBT without changing numeric types or writing it back."""
    if data.startswith(b'\x1f\x8b'):data=gzip.decompress(data)
    f=io.BytesIO(data)
    def number(fmt):return struct.unpack('>'+fmt,f.read(struct.calcsize('>'+fmt)))[0]
    def string():return f.read(number('H')).decode('utf-8',errors='strict')
    def value(tag):
        if tag in (1,2,3,4,5,6):return number({1:'b',2:'h',3:'i',4:'q',5:'f',6:'d'}[tag])
        if tag==8:return string()
        if tag==9:
            kind,count=number('B'),number('i')
            if not 0<=count<=1000000:raise ValueError('invalid NBT list length')
            return [value(kind) for _ in range(count)]
        if tag==10:
            result={}
            while True:
                kind=number('B')
                if not kind:return result
                key=string();result[key]=value(kind)
        if tag in (7,11,12):
            count=number('i')
            if not 0<=count<=1000000:raise ValueError('invalid NBT array length')
            return [number({7:'b',11:'i',12:'q'}[tag]) for _ in range(count)]
        raise ValueError('unsupported NBT tag '+str(tag))
    tag=number('B');string();result=value(tag)
    if f.read():raise ValueError('trailing bytes in NBT')
    return result

def parse(b):
    s=CTE2QuestTranslator._strip_json_comments(decode(b))
    s=re.sub(r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',lambda m:m[0] if m[0].startswith('"') else '',s)
    return json.loads(s,strict=False)

def leaves(value,path=(),field=''):
    if isinstance(value,dict):
        for k,v in value.items():yield from leaves(v,path+(k,),k)
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from leaves(v,path+(i,),field)
    elif isinstance(value,str):yield path,field,value

LOCALE=re.compile(r'[a-z]{2,3}_[a-z]{2,3}$')
CONFIG_SCREEN=b'net/neoforged/neoforge/client/gui/ConfigurationScreen'
LANG_KEY=re.compile(r'[A-Za-z0-9_.\-]+$')
NAMESPACE=re.compile(r'[a-z0-9_.\-]+$')

def declared_mods(z,names):
    """The mod ids a Forge/NeoForge mod file declares in its [[mods]] tables, in order."""
    import tomllib
    for t in ('META-INF/neoforge.mods.toml','META-INF/mods.toml'):
        if t in names:
            try:mods=tomllib.loads(z.read(t).decode('utf-8-sig')).get('mods',[])
            except (ValueError,UnicodeError):return []
            ids=[m.get('modId') for m in mods if isinstance(m,dict)]
            return [i for i in ids if isinstance(i,str) and NAMESPACE.match(i)] if all(isinstance(i,str) for i in ids) else []
    return []

def inline_languages(value,path=()):
    """(path, {locale: text}) for every object whose keys are all language codes and hold text, with
    English or Simplified Chinese among them: the same text written in several languages in one file."""
    if isinstance(value,dict):
        if value and all(isinstance(k,str) and LOCALE.match(k) for k in value) and all(isinstance(v,str) for v in value.values()) \
                and ('en_us' in value or 'zh_cn' in value):
            yield list(path),value;return
        for k,v in value.items():yield from inline_languages(v,path+(k,))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from inline_languages(v,path+(i,))

def at(value,path):
    try:
        for k in path:value=value[k]
        return value if isinstance(value,str) else None
    except (KeyError,IndexError,TypeError):return None

def placeholders(s):
    # %% is a literal, and indexed parameters may legally reorder arguments.
    found=Counter();pos=0
    for m in re.finditer(r'%%|%(?:(\d+)\$)?([-#+0,(]*\d*(?:\.\d+)?)?([sdif])',s):
        if m[0]=='%%':continue
        if not m[1]:pos+=1
        found[(int(m[1]) if m[1] else pos,m[3])]+=1
    return found

def fingerprint(row):
    return hashlib.sha256(json.dumps([row.get(k) for k in ('source','key','en','current','zh_cn')],ensure_ascii=False).encode()).hexdigest()

def utf8_constants(b):
    if b[:4]!=b'\xca\xfe\xba\xbe':return
    count=struct.unpack_from('>H',b,8)[0];i=1;pos=10
    sizes={3:4,4:4,5:8,6:8,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}
    while i<count:
        tag=b[pos];pos+=1
        if tag==1:
            size=struct.unpack_from('>H',b,pos)[0];pos+=2
            yield b[pos:pos+size].decode('utf-8',errors='replace');pos+=size
        else:
            if tag not in sizes:return
            pos+=sizes[tag]
            if tag in (5,6):i+=1
        i+=1

def exclude_tooltip_conflicts(rows):
    """A shared tooltip cannot represent different comments or replace an existing language entry."""
    existing=set(); groups=defaultdict(lambda: defaultdict(set)); lengths=defaultdict(set)
    for row in rows:
        jar,_,entry=row['source'].partition('!/')
        if row['kind']=='language' and entry.startswith('assets/'):
            resource=re.sub(r'/lang/(?:en_us|zh_cn|zh_tw)\.(?:json|lang)$','/lang/zh_tw.json',entry)
            existing.add((jar,row['key'],resource))
        for key,part,parts,resource in row.get('tooltips',[]):
            target=(jar,key,resource)
            groups[target][part].add(row['current']);lengths[target].add(parts)
    conflicts={target for target,lines in groups.items() if len(lengths[target])!=1 or any(len(values)!=1 for values in lines.values())}
    for row in rows:
        tips=row.get('tooltips')
        if not tips:continue
        jar=row['source'].split('!/')[0];kept=[];notes=[]
        for tip in tips:
            target=(jar,tip[0],tip[3])
            if target in existing:notes.append('設定說明已有語系條目，交由語系檔翻譯，避免互相覆蓋')
            elif target in conflicts:notes.append('不同設定共用同一語系鍵，但原文不同，無法安全共用譯文')
            else:kept.append(tip)
        if kept:row['tooltips']=kept
        else:row.pop('tooltips',None)
        if notes:row['tooltip_note']='；'.join(sorted(set(notes)))


class Audit:
    def __init__(self,out,decisions):
        self.out=out;out.mkdir(parents=True,exist_ok=True)
        self.rows=[];self.files=[];self.errors=[];self.repairs=[];self.counts=Counter();self.decisions=decisions
    def add(self,source,key,en,current,cn=None,kind='language'):
        if not any(isinstance(v,str) and v.strip() for v in (en,current,cn)):return
        row=dict(source=source,key=str(key),en=en,current=current,zh_cn=cn,kind=kind)
        flags=[]
        if current is None:flags.append('missing')
        else:
            if HAN.search(current) and CC.convert(current)!=current:flags.append('traditional_review')
            if LATIN.search(current):flags.append('mixed_english' if HAN.search(current) else 'english')
            if isinstance(en,str) and placeholders(en)!=placeholders(current):flags.append('parameter_mismatch')
            if re.search(r'__MC_(?:FMT|PH|NL|BOOK|BRACE)_\d+__|\ufffd',current):flags.append('broken_format')
        if kind in ('class_candidate','script_candidate'):flags.append('context_required')
        row['flags']=flags;row['fingerprint']=fingerprint(row)
        decision=self.decisions.get(row['fingerprint'])
        if decision and decision.get('status') in ('reviewed','keep_original') and decision.get('reason'):
            row['status']=decision['status'];row['reason']=decision['reason']
        elif not flags and current is not None and not re.search('[A-Za-z\u3400-\u9fff]',current):row['status']='nonlinguistic'
        else:row['status']='needs_review'
        self.counts[row['status']]+=1
        for flag in flags:self.counts[flag]+=1
        self.rows.append(row)
    def collection(self,label,names,read):
        groups={}
        for n in names:
            m=LANG.match('/'+n)
            if m:
                folder,lang,ext=lang_parts(m);groups.setdefault((folder,ext.lower()),{})[lang.lower()]=n
        for (_,ext),langs in groups.items():
            try:
                def load(lang):
                    if lang not in langs:return {}
                    b=read(langs[lang])
                    if not b.strip():
                        self.counts['empty_language_files']+=1
                        return {}
                    if ext=='snbt':return quest_lang.parse(decode(b))
                    return parse(b) if ext=='json' else dict(s.split('=',1) for s in decode(b).splitlines() if '=' in s and not s.startswith('#'))
                en,cn=load('en_us'),load('zh_cn')
                if ext=='snbt':
                    # Description lines are rows of their own; Chinese lines count only where they line up.
                    self.counts['quest_language_files']+=1
                    en_table=en;en=quest_lang.flatten(en_table);cn=quest_lang.aligned(en_table,cn)
                try:
                    tw=load('zh_tw')
                    if ext=='snbt':tw=quest_lang.flatten(tw)
                except ValueError as e:
                    # The game cannot read a malformed zh_tw either; rebuild it from en_us/zh_cn.
                    if not (en or cn):raise
                    tw={};self.counts['broken_zh_tw_rebuilt']+=1
                    self.repairs.append([label,langs['zh_tw'],str(e)])
                source=label+'!/'+langs.get('en_us',langs.get('zh_tw',langs.get('zh_cn')))
                for k in sorted(set(en)|set(tw)|set(cn)):
                    self.add(source,k,en.get(k),tw.get(k),cn.get(k))
            except Exception as e:self.errors.append([label,langs,str(e)])
        for n in names:
            if not BOOK.search('/'+n) or not n.endswith(('.json','.txt')):continue
            # Other languages are represented by the corresponding English/TW row.
            if re.search(r'/(?!en_us/|zh_tw/)[a-z]{2}_(?:[a-z]{2}|\d{3})/',n,re.I):continue
            if '/zh_tw/' in n and n.replace('/zh_tw/','/en_us/') in names:continue
            try:
                target=n.replace('/en_us/','/zh_tw/');c=n.replace('/en_us/','/zh_cn/')
                raw=read(n);twraw=read(target) if target in names else None;cnraw=read(c) if c!=n and c in names else None
                if n.endswith('.txt'):
                    self.add(label+'!/'+n,'text',decode(raw),decode(twraw) if twraw else None,decode(cnraw) if cnraw else None,'book');continue
                en=parse(raw);tw=parse(twraw) if twraw else {};cn=parse(cnraw) if cnraw else {}
                for path,field,value in leaves(en):
                    if field in PATCHOULI_SKIP_FIELDS:continue
                    if field in DISPLAY or HAN.search(value) or (LATIN.search(value) and ' ' in value):
                        self.add(label+'!/'+n,json.dumps(path),value,at(tw,path),at(cn,path),'book')
            except Exception as e:self.errors.append([label,n,str(e)])
    def archive(self,p,label):
        self.counts['archives']+=1
        first_row=len(self.rows)
        try:
            with zipfile.ZipFile(p) as z:
                names=set(z.namelist())
                for info in z.infolist():
                    self.files.append(dict(source=label+'!/'+info.filename,size=info.file_size,crc=info.CRC,kind='class' if info.filename.endswith('.class') else 'resource'))
                self.collection(label,names,z.read)
                self.nested(z,label,names)
                screen=False;linked=[]
                for n in names:
                    if not n.endswith('.class'):continue
                    try:
                        raw=z.read(n)
                        screen|=CONFIG_SCREEN in raw
                        try:
                            cf,safe=proven_strings(raw);constants=cf.utf.items()
                            tips=config_tooltips(raw) if any('設定說明' in use for _,use in safe.values()) else {}
                        except (ValueError,KeyError,IndexError,struct.error,UnicodeError):
                            # An unsupported class remains visible for inspection; it is never writable.
                            safe={};tips={};constants=enumerate(utf8_constants(raw))
                        for i,s in constants:
                            if (i in safe and LATIN.search(s)) or HAN.search(s) or (len(s)<1200 and re.search(r'\b[A-Za-z]{3,} [A-Za-z]{3,} [A-Za-z]{3,}\b',s)):
                                supported=i in safe and label.startswith('mods/') and label.count('!/')==0
                                self.add(label+'!/'+n,i,None,s,kind='class_display' if supported else 'class_candidate')
                                if supported:
                                    self.rows[-1]['display_use']=safe[i][1]
                                    if tips.get(i):linked.append((self.rows[-1],tips[i]))
                    except Exception as e:self.errors.append([label,n,'class extraction: '+str(e)])
                if linked and label.startswith('mods/') and label.count('!/')==0:
                    mods=declared_mods(z,names)
                    for row,tips in linked:
                        found=set()
                        for kind,text,part,parts in tips:
                            # NeoForge's own screen names a value <modid>.configuration.<name> when the mod gave no
                            # key: only for a mod (one per file) that opens that screen. Configured needs the mod's key.
                            if kind=='name' and not (screen and len(mods)==1):continue
                            key=text if kind=='key' else f'{mods[0]}.configuration.{text}'
                            if mods and LANG_KEY.match(key):found.add((key+'.tooltip',part,parts,f'assets/{mods[0]}/lang/zh_tw.json'))
                        if found:row['tooltips']=[list(t) for t in sorted(found)]
                    exclude_tooltip_conflicts(self.rows[first_row:])
        except Exception as e:self.errors.append([label,str(e)])
    def nested(self,z,label,names):
        # Jar-in-jar libraries (META-INF/jarjar etc.) ship their own language files; sources get a
        # second '!/' so writers can tell they live inside an embedded jar.
        for n in sorted(names):
            if not n.lower().endswith('.jar'):continue
            try:
                if z.getinfo(n).file_size>512*1024*1024:raise ValueError('embedded jar is larger than 512 MB')
                with zipfile.ZipFile(io.BytesIO(z.read(n))) as inner:
                    self.counts['nested_archives']+=1
                    self.collection(label+'!/'+n,set(inner.namelist()),inner.read)
            except Exception as e:self.errors.append([label,n,'nested jar: '+str(e)])
    def loose(self,root):
        paths=[]
        for folder in ('kubejs','config','defaultconfigs','patchouli_books','datapacks','resourcepacks','vaultpatcher','hotai','immersive_furniture'):
            paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix not in ('.zip','.jar'))
        paths.extend(p for p in (root/'saves').rglob('*') if p.is_file() and 'ftbquests' in str(p).lower())
        names={p.relative_to(root).as_posix():p for p in paths}
        self.collection('instance',set(names),lambda n:names[n].read_bytes())
        for n,p in names.items():
            self.files.append(dict(source=n,size=p.stat().st_size,kind='loose'))
            if p.suffix=='.class':
                try:
                    for i,s in enumerate(utf8_constants(p.read_bytes())):
                        if HAN.search(s) or (len(s)<1200 and re.search(r'\b[A-Za-z]{3,} [A-Za-z]{3,} [A-Za-z]{3,}\b',s)):
                            self.add(n,i,None,s,kind='class_candidate')
                except Exception as e:self.errors.append([n,'loose class extraction: '+str(e)])
                continue
            if p.suffix=='.data':
                try:
                    for path,field,value in leaves(parse_binary_nbt(p.read_bytes())):
                        if field in DISPLAY or HAN.search(value):self.add(n,json.dumps(path),None,value,kind='binary_config_candidate')
                    self.counts['binary_config_files']+=1
                except Exception as e:self.errors.append([n,'binary configuration: '+str(e)])
                continue
            if LANG.match('/'+n) or BOOK.search('/'+n):continue
            if p.suffix not in ('.js','.json','.snbt','.toml','.txt','.local','.lang'):continue
            try:
                raw=decode(p.read_bytes())
                if p.suffix=='.snbt':
                    for m in re.finditer(r'\b(?:description|Lore):\s*\[(?:"(?:\\.|[^"\\])*"|[^"\]])*\]',raw):
                        for i,s in enumerate(re.finditer(r'"(?:\\.|[^"\\])*"',m[0])):
                            self.add(n,f'array@{m.start()}:{i}',None,json.loads(s[0]),kind='snbt_display_array')
                if p.suffix=='.json':
                    if not raw.strip():
                        self.counts['empty_config_files']+=1;continue
                    data=parse(p.read_bytes());inline=set()
                    for path,texts in inline_languages(data):
                        # {"en_us": "...", "zh_cn": "..."}: one text in several languages (Ponderer scenes)
                        inline.add(tuple(path))
                        self.add(n,json.dumps(path),texts.get('en_us'),texts.get('zh_tw'),texts.get('zh_cn'),kind='inline_lang')
                    for path,field,value in leaves(data):
                        if tuple(path[:-1]) in inline:continue
                        if field in DISPLAY or HAN.search(value):self.add(n,json.dumps(path),None,value,kind='config')
                else:
                    for lineno,line in enumerate(raw.splitlines(),1):
                        if line.lstrip().startswith(('//','#')):continue
                        for i,m in enumerate(re.finditer(r'"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27',line)):
                            value=m[0][1:-1]
                            visible=HAN.search(value) or re.search(r'\b(title|subtitle|description|Text\.of|text\.add|tooltip|displayName|label|message)\b',line)
                            if visible and (HAN.search(value) or LATIN.search(value)):
                                self.add(n,f'{lineno}:{i}',None,value,kind='script_candidate' if p.suffix=='.js' else 'config')
            except Exception as e:self.errors.append([n,str(e)])
    def finish(self,details='full',quiet=False):
        # details: 'full' writes plain lists (command-line audits); 'compressed' writes the two lists the
        # desktop report keeps for diagnosis as .gz; 'summary' writes the counts only.
        lists=[('files.jsonl',self.files),('strings.jsonl',self.rows),('pending.jsonl',[r for r in self.rows if r['status']=='needs_review'])]
        for name,items in lists if details=='full' else lists[:2] if details=='compressed' else []:
            with ((self.out/name).open('w',encoding='utf-8') if details=='full'
                  else gzip.open(self.out/(name+'.gz'),'wt',encoding='utf-8',compresslevel=5)) as f:
                for row in items:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        summary=dict(counts=dict(self.counts),file_entries=len(self.files),text_records=len(self.rows),errors=self.errors,repairs=self.repairs,complete=self.counts['needs_review']==0 and not self.errors,limits=['靜態程式字串為待查候選，無法證明所有動態組句與遊戲畫面均已實測。','其他語言資源保留原文，檢查 zh_tw 的實際內容與缺漏。'])
        (self.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        if not quiet:
            print(json.dumps({k:v for k,v in summary.items() if k!='errors'},ensure_ascii=False));print('Errors:',len(self.errors))
        return 0 if summary['complete'] else 1

def main():
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--decisions',type=Path);args=ap.parse_args()
    decisions=json.loads(args.decisions.read_text(encoding='utf-8')) if args.decisions else {}
    audit=Audit(args.output,decisions)
    for folder in ('mods','resourcepacks','datapacks','config/openloader'):
        for p in sorted((args.root/folder).rglob('*')):
            if p.suffix in ('.jar','.zip'):audit.archive(p,p.relative_to(args.root).as_posix())
    audit.loose(args.root)
    return audit.finish()
if __name__=='__main__':raise SystemExit(main())
