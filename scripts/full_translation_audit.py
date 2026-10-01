"""Read-only inventory and fail-closed, fingerprinted translation review gate."""
import argparse, hashlib, json, re, struct, zipfile, gzip, io
from collections import Counter, defaultdict
from pathlib import Path
from mc_zh_tw_translator.translator import CTE2QuestTranslator, PATCHOULI_SKIP_FIELDS
from opencc import OpenCC
from mc_zh_tw_translator.class_text import proven_strings, plain_strings, config_tooltips, developer_strings
from mc_zh_tw_translator import quest_lang

HAN=re.compile('[\u3400-\u9fff]'); LATIN=re.compile('[A-Za-z]{3,}')
# FTB Quests keeps quest text in config/ftbquests/quests/lang/<locale>.snbt (see quest_lang).
LANG=re.compile(r'^(.*?/lang/)(en_us|zh_tw|zh_cn)\.(json|lang)$|^(.*?/ftbquests/quests/lang/)(en_us|zh_tw|zh_cn)\.(snbt)$',re.I)

def lang_parts(m):
    """(folder, language, extension) of a LANG match, whichever of its two forms matched."""
    return (m[1],m[2],m[3]) if m[1] is not None else (m[4],m[5],m[6])
BOOK=re.compile(r'/(?:patchouli_books|books?|guidebook)/',re.I)
DISPLAY={'name','Name','text','title','subtitle','description','landing_text','header','customTooltips','displayName','tooltip','label','message','lore','Lore'}
# Folders of loose files the game reads player text from (mods and other archives are scanned on their own).
# scripts/ holds CraftTweaker's ZenScript (.zs): tooltips and names written straight into the script.
LOOSE_FOLDERS=('kubejs','config','defaultconfigs','patchouli_books','datapacks','resourcepacks','vaultpatcher','hotai',
               'immersive_furniture','scripts')
# Content packs a mod loads as resource packs: TACZ gun packs (GunPackLoader is a RepositorySource) and Touhou
# Little Maid custom packs (LanguageLoader reads assets/<ns>/lang/<code>.json). Only their language files and
# books are text; their other JSON is game data naming language keys.
CONTENT_PACK_FOLDERS=('tacz','tlm_custom_pack')
# Folders that hold no text the game shows from a file of their own, left out of the sweep for unscanned text.
NOT_PLAYER_TEXT={'mods','saves','logs','crash-reports','screenshots','backups','cache','shaderpacks','.mixin.out','natives',
                 'libraries','versions','assets','modernfix','lightspeed-cache','customskinloader','journeymap','xaero',
                 'xaerominimap','xaeroworldmap','schematics','.cache','.fabric','.idea','local','dlc','output','downloads'}
# Folders of loose files the game reads player text from (mods and other archives are scanned on their own).
# scripts/ holds CraftTweaker's ZenScript (.zs): tooltips and names written straight into the script.
LOOSE_FOLDERS=('kubejs','config','defaultconfigs','patchouli_books','datapacks','resourcepacks','vaultpatcher','hotai',
               'immersive_furniture','scripts')
# Content packs a mod loads as resource packs: TACZ gun packs (GunPackLoader is a RepositorySource) and Touhou
# Little Maid custom packs (LanguageLoader reads assets/<ns>/lang/<code>.json). Only their language files and
# books are text; their other JSON is game data naming language keys.
CONTENT_PACK_FOLDERS=('tacz','tlm_custom_pack')
# Top-level folders holding no text the game shows from a file of their own: left out of the unscanned sweep.
NOT_PLAYER_TEXT={'mods','saves','logs','crash-reports','screenshots','backups','cache','shaderpacks','.mixin.out','natives',
                 'libraries','versions','assets','modernfix','lightspeed-cache','customskinloader','journeymap','xaero',
                 'xaerominimap','xaeroworldmap','schematics','.cache','.fabric','local','dlc','downloads'}
TEXT_CONFIG_SUFFIXES={'.js','.zs','.zs','.json','.snbt','.toml','.txt','.local','.lang','.cfg','.yaml','.yml','.xml','.csv','.properties','.ini','.conf','.data','.cache'}
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

def rewrite_binary_nbt(data,replacements):
    """Replace selected TAG_String values by their exact NBT paths.

    ``replacements`` maps tuple paths to ``(expected, new)``. The stream is copied tag for tag, so numeric
    values, arrays, keys, list types and their byte representation stay untouched. Every requested path must
    exist once and still contain the value seen by the scan; otherwise the write fails closed.
    """
    compressed=data.startswith(b'\x1f\x8b');raw=gzip.decompress(data) if compressed else data
    f=io.BytesIO(raw);found=set()
    def take(n):
        value=f.read(n)
        if len(value)!=n:raise ValueError('truncated NBT')
        return value
    def number(fmt):
        value=take(struct.calcsize('>'+fmt));return value,struct.unpack('>'+fmt,value)[0]
    def string_bytes():
        head,size=number('H');return head+take(size)
    def value(tag,path):
        if tag in (1,2,3,4,5,6):return take({1:1,2:2,3:4,4:8,5:4,6:8}[tag])
        if tag==8:
            encoded=string_bytes();old=encoded[2:].decode('utf-8',errors='strict')
            replacement=replacements.get(path)
            if replacement is None:return encoded
            if path in found or old!=replacement[0]:raise ValueError('NBT string changed since scan: '+json.dumps(path,ensure_ascii=False))
            new=replacement[1].encode('utf-8')
            if len(new)>65535:raise ValueError('NBT string is longer than 65535 bytes')
            found.add(path);return struct.pack('>H',len(new))+new
        if tag==9:
            head=take(1);count_raw,count=number('i')
            if not 0<=count<=1000000:raise ValueError('invalid NBT list length')
            return head+count_raw+b''.join(value(head[0],path+(i,)) for i in range(count))
        if tag==10:
            out=b''
            while True:
                kind=take(1);out+=kind
                if kind==b'\0':return out
                name=string_bytes();key=name[2:].decode('utf-8',errors='strict')
                out+=name+value(kind[0],path+(key,))
        if tag in (7,11,12):
            head,count=number('i')
            if not 0<=count<=1000000:raise ValueError('invalid NBT array length')
            return head+take(count*{7:1,11:4,12:8}[tag])
        raise ValueError('unsupported NBT tag '+str(tag))
    tag=take(1);name=string_bytes();rewritten=tag+name+value(tag[0],())
    if f.read():raise ValueError('trailing bytes in NBT')
    missing=set(replacements)-found
    if missing:raise ValueError('NBT strings not found: '+json.dumps(sorted(missing,key=str),ensure_ascii=False))
    return gzip.compress(rewritten,mtime=0) if compressed and rewritten!=raw else data if rewritten==raw else rewritten

def parse(b):
    s=CTE2QuestTranslator._strip_json_comments(decode(b))
    s=re.sub(r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',lambda m:m[0] if m[0].startswith('"') else '',s)
    return mend_surrogates(json.loads(s,strict=False))

LONE_SURROGATE=re.compile('[\ud800-\udfff]')

# Text files where a string is written in quotes: JSON and SNBT take JSON escapes, TOML/TXT lines are kept raw.
QUOTED=re.compile(r'"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27')
DOUBLE_QUOTED=re.compile(r'"(?:\\.|[^"\\])*"')

SCRIPT_SUFFIXES=('.js','.zs')

def string_literals(text,suffix):
    """(line number, index on the line, value, is_key, start, end) of every quoted string, one line at a time.

    The scan, the writer and the read-back check all locate config and quest text with this, so a row's
    "line:index" key names the same string in all three. Keys (followed by : or =) are marked; comment lines
    are skipped. JSON/SNBT values are unescaped; TOML/TXT values are the raw text between the quotes, as the
    scan has always recorded them. Forge's old .cfg files write values without quotes (see cfg_values).
    """
    if suffix=='.cfg':
        yield from cfg_values(text);return
    escaped=suffix in ('.json','.snbt','.json5');pattern=DOUBLE_QUOTED if escaped else QUOTED;offset=0
    script=suffix in SCRIPT_SUFFIXES;block=False
    for lineno,line in enumerate(text.splitlines(True),1):
        stripped=line.lstrip()
        # A script's /* ... */ comment lines are notes, not text; the whole line holding /* or */ is left out.
        if script and (block or stripped.startswith('/*')):
            block='*/' not in (stripped if block else stripped[2:])
            offset+=len(line);continue
        if not stripped.startswith(('//','#')):
            for i,m in enumerate(pattern.finditer(line)):
                literal=m[0]
                if escaped:
                    try:value=json.loads(literal,strict=False)
                    except ValueError:continue
                else:value=literal[1:-1]
                is_key=line[m.end():].lstrip().startswith((':','='))
                # In a script, cond ? '是' : '否' is text; a key starts the line or follows { or ,
                if is_key and script:is_key=line[:m.start()].rstrip()[-1:] in ('','{',',')
                yield lineno,i,value,is_key,offset+m.start(),offset+m.end()
        offset+=len(line)

# Files that describe a pack rather than hold game text, and tool caches (JEI's sort order and lookup history).
NOT_TEXT_FILE=re.compile(r'(?i)(?:^|/)(?:readme|changelog|change_log|update_?log|licen[cs]e|credits?)[^/]*$|^config/jei/')

def unsupported_sample(n,text,root,strict=False):
    """A line of what may be player text in a file no reader produced a row for, or None.

    Any line with Chinese counts, and, unless strict, a line naming a display field (title = ..., shop: ...).
    Strict (content packs, folders no reader covers) keeps to what is surely text: in JSON only display fields
    (a model's bone names or an author list are not shown as text), and a language file only in English or
    Simplified Chinese where its folder has no zh_tw. Another language's file is never listed."""
    m=re.search(r'/lang/([^/]+)\.(?:json|lang)$',n,re.I)
    if NOT_TEXT_FILE.search(n) or (m and m[1].casefold() not in ('en_us','zh_cn')):return None
    if m:
        if not strict:return None
        folder=root/n.rsplit('/',1)[0]
        if any((folder/name).exists() for name in ('zh_tw.json','zh_tw.lang')):return None
        return next((line.strip() for line in text.splitlines() if LATIN.search(line) or HAN.search(line)),None)
    if strict and n.lower().endswith('.json'):
        try:data=parse(text.encode('utf-8'))
        except ValueError:data=None
        if data is not None:return next((v for _,field,v in leaves(data) if field in DISPLAY and HAN.search(v)),None)
    lines=[line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith(('#','//','--'))]
    sample=next((line for line in lines if HAN.search(line)),None)
    if sample is None and not strict:
        sample=next((line for line in lines if re.search(
            r'(?i)\b(?:title|name|description|label|tooltip|message|category|shop|store|market|vendor|trade)\b\s*[:=].*[A-Za-z]',line)),None)
    return sample

CFG_SETTING=re.compile(r'\s*[A-Za-z]:(?:"[^"]*"|[^=<]*?)=(.*)$')

def cfg_values(text):
    """The values of a Forge 1.12-style .cfg file (Apotheosis's names.cfg) in string_literals' form: S:name=value
    gives its value; a list, from "S:name <" to ">", gives each line between. Values carry no quotes, so the
    value's own span is its literal."""
    offset=0;in_list=False
    for lineno,line in enumerate(text.splitlines(True),1):
        body=line.rstrip('\r\n');s=body.strip();start=None
        if s and not s.startswith('#'):
            if in_list:
                if s=='>':in_list=False
                else:start=body.index(s);value=s
            elif s.endswith('<'):in_list=True
            else:
                m=CFG_SETTING.match(body)
                if m and m[1].strip():value=m[1].strip();start=body.index(value,m.start(1))
        if start is not None:yield lineno,0,value,False,offset+start,offset+start+len(value)
        offset+=len(line)

MIXIN=b'Lorg/spongepowered/asm/mixin/Mixin;'
CLASS_REF=re.compile(r'L([A-Za-z_$][\w$/]*);')
CLASS_NAME=re.compile(r'[A-Za-z_$][\w$]*(?:[./][\w$]+)+')

def mixin_targets(raw):
    """Every class a Mixin class names, as internal names (a/b/C). @Mixin(Foo.class) is a type in the class
    file and @Mixin(targets="a.b.C") a string; both are caught, along with types it merely mentions.

    A Mixin can look for an exact string in its target (@ModifyConstant(stringValue=...)): The Foll's
    RevelationFix replaces one GoetyRevelation config comment, and the game stopped loading once that
    comment had been translated. Text in these classes is therefore never rewritten.
    """
    names=set()
    for text in utf8_constants(raw):
        names|=set(CLASS_REF.findall(text))  # types: LSample; (a/b/C) in annotations and descriptors
        if CLASS_NAME.fullmatch(text):names.add(text.replace('.','/'))  # @Mixin(targets="a.b.C"), class names
    return {n for n in names if not n.startswith(('java/','org/spongepowered/'))}

def mend_surrogates(value):
    """Half of an emoji written wrongly as \\uXXXX (seen: TravelOptics zh_cn "\\uD810E\\uDD87") cannot be saved
    as text, and failed the whole file. It becomes U+FFFD, which the format checks already refuse, so that one
    line falls back to another source while the rest of the file is used."""
    if isinstance(value,str):return LONE_SURROGATE.sub('�',value)
    if isinstance(value,dict):return {mend_surrogates(k):mend_surrogates(v) for k,v in value.items()}
    if isinstance(value,list):return [mend_surrogates(v) for v in value]
    return value

def leaves(value,path=(),field=''):
    if isinstance(value,dict):
        for k,v in value.items():yield from leaves(v,path+(k,),k)
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from leaves(v,path+(i,),field)
    elif isinstance(value,str):yield path,field,value

LOCALE=re.compile(r'[a-z]{2,3}_[a-z]{2,3}$')
NOT_READ=('config/ftbquests/quests-backup/',)
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
        # The config screen shows the language entry (its own row) instead of this comment.
        if not kept and any((jar,tip[0],tip[3]) in existing for tip in tips):row['tooltip_in_language']=True


class Audit:
    def __init__(self,out,decisions):
        self.out=out;out.mkdir(parents=True,exist_ok=True)
        self.rows=[];self.files=[];self.errors=[];self.repairs=[];self.counts=Counter();self.decisions=decisions
        self.mixin_targets=set()  # classes some Mixin changes when the game starts (see mixin_targets)
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
                en=load('en_us')
                try:cn=load('zh_cn')
                except (ValueError,UnicodeError):
                    # A mod's optional Simplified Chinese can be malformed while its English is sound
                    # (Patchouli 1.20.1-84). Keep scanning from English and other sources instead of
                    # presenting the whole mod as damaged.
                    cn={};self.counts['broken_zh_cn_skipped']+=1
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
                if not decode(raw).strip():
                    # Some mods ship 0-byte placeholder pages; there is no text to translate or show.
                    self.counts['empty_book_skipped']+=1;continue
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
                screen=False;linked=[];literals=[];compared=set()
                ships_lang=any(re.match(r'assets/[^/]+/lang/[^/]+\.json$',x) for x in names)
                for n in names:
                    if not n.endswith('.class'):continue
                    try:
                        raw=z.read(n)
                        screen|=CONFIG_SCREEN in raw
                        # A data generator (Forge/NeoForge/Fabric LanguageProvider) writes the mod's language files
                        # while the mod is built; the game reads those files, never these strings.
                        generator=ships_lang and b'LanguageProvider' in raw
                        if MIXIN in raw:self.mixin_targets|=mixin_targets(raw)
                        try:
                            cf,safe=proven_strings(raw);constants=cf.utf.items()
                            tips=config_tooltips(raw) if any('設定說明' in use for _,use in safe.values()) else {}
                            developer=developer_strings(raw)
                            _,plain,seen=plain_strings(raw);compared|=seen
                        except (ValueError,KeyError,IndexError,struct.error,UnicodeError):
                            # An unsupported class remains visible for inspection; it is never writable.
                            safe={};tips={};developer=set();plain={};constants=enumerate(utf8_constants(raw))
                        for i,s in constants:
                            if (i in safe and LATIN.search(s)) or HAN.search(s) or (len(s)<1200 and re.search(r'\b[A-Za-z]{3,} [A-Za-z]{3,} [A-Za-z]{3,}\b',s)):
                                supported=i in safe and label.startswith('mods/') and label.count('!/')==0
                                self.add(label+'!/'+n,i,None,s,kind='class_display' if supported else 'class_candidate')
                                if not supported and i in developer:self.rows[-1]['developer_use']=True
                                if not supported and generator:self.rows[-1]['language_generator']=True
                                if not supported and i in plain and HAN.search(s):literals.append(self.rows[-1])
                                if supported:
                                    self.rows[-1]['display_use']=safe[i][1]
                                    if tips.get(i):linked.append((self.rows[-1],tips[i]))
                    except Exception as e:self.errors.append([label,n,'class extraction: '+str(e)])
                # Chinese literals a class of this file compares with keep their characters in every class.
                for row in literals:
                    if row['current'] not in compared:row['plain_literal']=True
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
        for folder in LOOSE_FOLDERS+CONTENT_PACK_FOLDERS:
            paths.extend(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix not in ('.zip','.jar'))
        paths.extend(p for p in (root/'saves').rglob('*') if p.is_file() and 'ftbquests' in str(p).lower())
        # A copy of the quests some modpacks keep beside them (The Foll): FTB Quests never reads it.
        unread=[p for p in paths if p.relative_to(root).as_posix().startswith(NOT_READ)]
        self.counts['not_read_by_game']+=len(unread)
        if unread:paths=[p for p in paths if p not in set(unread)]
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
            if p.suffix.lower() in ('.data','.cache'):
                try:
                    for path,field,value in leaves(parse_binary_nbt(p.read_bytes())):
                        if field in DISPLAY or HAN.search(value):self.add(n,json.dumps(path),None,value,kind='binary_config_candidate')
                    self.counts['binary_config_files']+=1
                except Exception as e:self.errors.append([n,'binary configuration: '+str(e)])
                continue
            if LANG.match('/'+n) or BOOK.search('/'+n):continue
            if n.split('/',1)[0] in CONTENT_PACK_FOLDERS:
                # Beside language files, a content pack shows Chinese of its own only in display fields
                # (TACZ text_show "text": a brand name printed on the gun model).
                if p.suffix.lower()=='.json':
                    try:
                        for path,field,value in leaves(parse(p.read_bytes())):
                            if field in DISPLAY and HAN.search(value):self.add(n,json.dumps(path),None,value,kind='config')
                    except (ValueError,UnicodeError):pass
                continue
            if p.suffix not in ('.js','.zs','.json','.snbt','.toml','.txt','.local','.lang','.cfg','.yaml','.yml'):continue
            try:
                raw=decode(p.read_bytes())
                if p.suffix=='.snbt':
                    # FTB Quests 1.20.1 and other SNBT files hold their text inline: every Chinese string that is
                    # not a key (titles, subtitles, descriptions) is a row of its own, keyed by line.
                    lines=raw.splitlines()
                    for lineno,i,value,is_key,_,_ in string_literals(raw,'.snbt'):
                        if is_key:continue
                        # English is listed where the line names it as display text (title: "..."); array lines are below.
                        line=lines[lineno-1]
                        if HAN.search(value) or (LATIN.search(value) and re.search(r'\b(title|subtitle|text|Name)\b',line)
                                                 and not re.search(r'\b(?:description|Lore):\s*\[',line)):
                            self.add(n,f'{lineno}:{i}',None,value,kind='snbt_display_array')
                    for m in re.finditer(r'\b(?:description|Lore):\s*\[(?:"(?:\\.|[^"\\])*"|[^"\]])*\]',raw):
                        for i,s in enumerate(re.finditer(r'"(?:\\.|[^"\\])*"',m[0])):
                            value=json.loads(s[0])
                            if not HAN.search(value):self.add(n,f'array@{m.start()}:{i}',None,value,kind='snbt_display_array')
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
                elif p.suffix!='.snbt':  # SNBT text is read above
                    lines=raw.splitlines()
                    for lineno,i,value,is_key,_,_ in string_literals(raw,p.suffix):
                        if is_key:continue  # a setting's or an object's name, not text
                        if p.suffix in ('.cfg','.yaml','.yml') and not HAN.search(value):continue  # English stays unlisted
                        line=lines[lineno-1]
                        visible=HAN.search(value) or re.search(r'\b(title|subtitle|description|Text\.of|text\.add|tooltip|displayName|label|message)\b'
                                                               r'|\.(?:add(?:Shift)?Tooltip|setDisplayName|addJEIInfo|addInfo)\(',line)
                        if visible and (HAN.search(value) or LATIN.search(value)):
                            self.add(n,f'{lineno}:{i}',None,value,kind='script_candidate' if p.suffix in SCRIPT_SUFFIXES else 'config')
            except Exception as e:
                if p.suffix.lower()=='.json' and isinstance(e,(ValueError,UnicodeError)):
                    # OpenLoader also stores recipes, affixes and combat numbers under config. Broken JSON
                    # with no display-looking text is a game-data problem, not a translation failure.
                    try:text=decode(p.read_bytes())
                    except (OSError,UnicodeError):text=''
                    display=re.search(r'(?i)["\x27](?:title|name|description|label|tooltip|message|text|lore)["\x27]\s*:',text)
                    if not HAN.search(text) and not display:
                        self.counts['invalid_nontext_json_skipped']+=1;continue
                self.errors.append([n,str(e)])
        # Do not silently lose a future shop/config format. A file with Chinese, or a likely display field in
        # a known text format, that produced no row above is listed as an unsupported candidate. It is never
        # written until its reader and format have been verified.
        produced={r['source'].removeprefix('instance!/') for r in self.rows}
        for n,p in names.items():
            content=n.split('/',1)[0] in CONTENT_PACK_FOLDERS
            if (n in produced or LANG.match('/'+n) or BOOK.search('/'+n) or (content and p.suffix.lower()!='.json')
                    or p.suffix.lower() not in TEXT_CONFIG_SUFFIXES or p.stat().st_size>16*1024*1024):continue
            try:
                text=decode(p.read_bytes())
                if '\0' in text:continue
            except (OSError,UnicodeError):continue
            # A content pack's own data (TACZ gun definitions, model files) is read for display fields only.
            sample=unsupported_sample(n,text,root,strict=content)
            if sample:
                self.add(n,'file',None,sample[:500],kind='unsupported_config_text')
                self.counts['unsupported_config_text_files']+=1
        self.unscanned(root)
    def unscanned(self,root):
        """List text in folders no reader covers, so a new kind of text (CraftTweaker scripts, TACZ gun packs) is
        never silently left out: a text file with Chinese, a language file, or an archive carrying language files,
        in any top-level folder of the modpack other than those scanned and those holding no player text.
        Nothing listed here is written; the report shows it as a format not supported yet."""
        scanned={f.casefold() for f in LOOSE_FOLDERS+CONTENT_PACK_FOLDERS+('mods',)}
        try:folders=[d for d in root.iterdir() if d.is_dir() and d.name.casefold() not in scanned|NOT_PLAYER_TEXT]
        except OSError:return
        for folder in sorted(folders):
            for p in sorted(folder.rglob('*')):
                if not p.is_file():continue
                n=p.relative_to(root).as_posix();suffix=p.suffix.lower()
                try:
                    if suffix in ('.zip','.jar'):
                        if p.stat().st_size>512*1024*1024:continue
                        with zipfile.ZipFile(p) as z:found=sorted(x for x in z.namelist() if LANG.match('/'+x))
                        if found:
                            self.add(n,'file',None,'含有語系檔：'+'、'.join(found[:3]),kind='unsupported_config_text')
                            self.counts['unscanned_text_files']+=1
                        continue
                    if suffix not in TEXT_CONFIG_SUFFIXES or p.stat().st_size>16*1024*1024:continue
                    text=decode(p.read_bytes())
                except (OSError,UnicodeError,ValueError,zipfile.BadZipFile):continue
                if '\0' in text:continue
                sample=unsupported_sample(n,text,root,strict=True)
                if sample:
                    self.add(n,'file',None,sample[:500],kind='unsupported_config_text')
                    self.counts['unscanned_text_files']+=1
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
