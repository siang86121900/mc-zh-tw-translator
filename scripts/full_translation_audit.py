"""Read-only inventory and fail-closed, fingerprinted translation review gate."""
import argparse, hashlib, json, re, struct, zipfile, gzip, io
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from mc_zh_tw_translator.translator import CTE2QuestTranslator, PATCHOULI_SKIP_FIELDS
from opencc import OpenCC
from mc_zh_tw_translator.class_text import proven_strings, plain_strings, config_tooltips, developer_strings, JarFlow
from mc_zh_tw_translator import embedded_text
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
# Top-level folders holding no text the game shows from a file of their own: left out of the unscanned sweep.
# data/ is what mods write while the game runs (Collective rebuilds data/serilum/translations at every start).
NOT_PLAYER_TEXT={'mods','saves','data','logs','crash-reports','screenshots','backups','cache','shaderpacks','.mixin.out','natives',
                 'libraries','versions','assets','modernfix','lightspeed-cache','customskinloader','journeymap','xaero',
                 'xaerominimap','xaeroworldmap','schematics','.cache','.fabric','.idea','local','dlc','output','downloads'}
TEXT_CONFIG_SUFFIXES={'.js','.zs','.json','.snbt','.toml','.txt','.local','.lang','.cfg','.yaml','.yml','.xml','.csv','.properties','.ini','.conf','.data','.cache'}
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
# Chinese that reads as a sentence rather than a name (geometry.四叶十字, a bone called 头发): punctuation, or a long run.
SENTENCE=re.compile(r'[，。！？；：、]|^(?=(?:[^.()_/\=]*[\u3400-\u9fff]){8})[^.()_/\=]*$')
NOT_TEXT_FIELD=re.compile(r'(?i)author|credit|identifier|uuid|bone|(?:^|_)id$')
# Formats whose strings string_literals can find and the writer can put back byte for byte.
UNVERIFIED_SUFFIXES=('.json','.snbt','.toml','.txt','.yaml','.yml','.cfg','.properties','.js','.zs')

def other_language(n):
    """A path naming another language (zh_cn/, ja-JP.json): its Chinese is that language, not something to convert."""
    parts=PurePosixPath(n).parts
    return any(re.fullmatch(r'[a-z]{2,3}[_-][a-z]{2,4}',part,re.I) and part.casefold().replace('-','_')!='zh_tw'
               for part in parts[:-1]+(PurePosixPath(n).stem,))

# FancyMenu layouts (title and pause screen buttons): "label = 開始遊戲" lines, the text shown as written.
FANCYMENU=re.compile(r'(?:^|/)config/fancymenu/customization/[^/]+\.txt$',re.I)
FANCYMENU_TEXT={'label','hoverlabel','description','source','tooltip','text','title'}
ASSIGNED=re.compile(r'^(\s*)([^=#!\s][^=]*?)\s*=\s*(.*?)\s*$')

def assigned_values(text,fields=None):
    """string_literals' form for "name = value" lines with no quotes (.properties, FancyMenu): each value whose
    name is in `fields` (any name when None). The value's own span is its literal."""
    offset=0
    for lineno,line in enumerate(text.splitlines(True),1):
        body=line.rstrip('\r\n');m=ASSIGNED.match(body)
        if m and not body.lstrip().startswith(('#','!')) and m[3] and (fields is None or m[2].strip() in fields):
            yield lineno,0,m[3],False,offset+m.start(3),offset+m.end(3)
        offset+=len(line)

def plain_text(text):
    """A .txt whose Chinese lines hold no quotes: text shown as written, line by line (Tensura's welcome.txt, a
    Markdown note). Decided from the text itself, so the scan, the writer and the read-back always agree."""
    lines=[line for line in text.splitlines() if HAN.search(line)]
    # Chinese only in # lines is a settings file's comments (YSM's blacklist.txt), not a note to show.
    return (any(not line.lstrip().startswith('#') for line in lines)
            and not any(q in line for line in lines for q in '"\''))

def text_lines(text):
    """string_literals' form for a plain_text file: every line with Chinese, without its surrounding spaces.
    Headings (## ...) are shown too, so no line is taken for a comment."""
    offset=0
    for lineno,line in enumerate(text.splitlines(True),1):
        body=line.rstrip('\r\n');value=body.strip()
        if HAN.search(value):
            start=offset+body.index(value);yield lineno,0,value,False,start,start+len(value)
        offset+=len(line)

def string_literals(text,suffix,path=''):
    """(line number, index on the line, value, is_key, start, end) of every quoted string, one line at a time.

    The scan, the writer and the read-back check all locate config and quest text with this, so a row's
    "line:index" key names the same string in all three. Keys (followed by : or =) are marked; comment lines
    are skipped. JSON/SNBT values are unescaped; TOML/TXT values are the raw text between the quotes, as the
    scan has always recorded them. Forge's old .cfg files write values without quotes (see cfg_values), as do
    .properties files and FancyMenu layouts (assigned_values; `path` names the file).
    """
    if FANCYMENU.search(path):
        yield from assigned_values(text,FANCYMENU_TEXT);return
    if suffix=='.properties':
        yield from assigned_values(text);return
    if suffix=='.txt' and plain_text(text):
        yield from text_lines(text);return
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
NOT_TEXT_FILE=re.compile(r'(?i)(?:^|/)(?:readme|changelog|change_log|update_?log|licen[cs]e|credits?|notice)[^/]*$|^config/jei/|(?:^|/)\.idea/')

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
    if n.lower().endswith(('.js','.zs','.json','.json5')):
        text=re.sub(r'/\*.*?\*/',' ',text,flags=re.S)  # block comments (string contents are already blanked)
        text=re.sub(r'(?m)(?<![:"\'])//.*$','',text)
    lines=[line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith(('#','//','--','*','/*'))]
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

def own_font_without_chinese(names,read):
    """A font a mod draws its screens with by itself (Elementa/UniversalCraft: fonts/<name>.json listing its glyphs
    and an atlas; Essential uses it) never falls back to the game's fonts, so Chinese shows as boxes (□) when none of
    its fonts has Chinese glyphs. Returns the font file then, else ''."""
    found=''
    for n in sorted(names):
        if not re.fullmatch(r'fonts/[^/]+\.json',n):continue
        try:data=json.loads(read(n))
        except (ValueError,KeyError,OSError,UnicodeError):continue
        if not isinstance(data,dict) or 'atlas' not in data or not isinstance(data.get('glyphs'),list):continue
        if any(isinstance(g,dict) and isinstance(g.get('unicode'),int) and g['unicode']>=0x2E80 for g in data['glyphs']):return ''
        found=found or n
    return found


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

# Text a mod reads from data packs and shows as written, with no language key (Whispering Quests 3.2: QuestDataManager
# and ChapterDataManager are SimpleJsonResourceReloadListeners, QuestScreen draws Component.literal). The game reads
# the topmost data pack's copy, so the translation is a data pack above the mods (desktop_jobs.DATA_PACK_FILE).
DATA_TEXT=re.compile(r'(?:^|/)data/[a-z0-9_.\-]+/whisperingquests/(?:tasks|chapters)/.+\.json$')
DATA_TEXT_FIELDS={'title','short_description','description','text','pool_name','display_name'}
# Any other data-pack JSON of a mod file: display fields with Chinese are listed as a format not supported yet.
DATA_JSON=re.compile(r'^data/([a-z0-9_.\-]+)/([a-z0-9_.\-]+)/.+\.json$')
# Biomes, structures, structure sets and dimensions a mod defines in its data. Their names are language keys made
# from the id (Util.makeDescriptionId: biome.<mod>.<path>), which many mods never write in any language file; the
# game and the compass mods then show the bare key or the id in English (Nature's Compass 1.11.2: I18n.get of
# "biome.<mod>.<path>"; Explorer's Compass 1.4.0: "structure.<mod>.<path>" and "dimension.<mod>.<path>", else the
# id title-cased). A missing key becomes a language row of its own, written into the translation resource pack.
REGISTRY_NAME=re.compile(r'(?:^|/)data/([a-z0-9_.\-]+)/(?:worldgen/(biome|structure|structure_set)|(dimension))/([a-z0-9_.\-/]+)\.json$')
# The game's own structures and structure sets (1.20 to 1.21), which the compass mods list by name.
VANILLA_STRUCTURES=('ancient_city','bastion_remnant','buried_treasure','desert_pyramid','end_city','fortress','igloo','jungle_pyramid',
                    'mansion','mineshaft','mineshaft_mesa','monument','nether_fossil','ocean_ruin_cold','ocean_ruin_warm','pillager_outpost',
                    'ruined_portal','ruined_portal_desert','ruined_portal_jungle','ruined_portal_mountain','ruined_portal_nether',
                    'ruined_portal_ocean','ruined_portal_swamp','shipwreck','shipwreck_beached','stronghold','swamp_hut','trail_ruins',
                    'trial_chambers','village_desert','village_plains','village_savanna','village_snowy','village_taiga',
                    'ancient_cities','buried_treasures','desert_pyramids','end_cities','igloos','jungle_temples','mineshafts',
                    'nether_complexes','nether_fossils','ocean_monuments','ocean_ruins','pillager_outposts','ruined_portals',
                    'shipwrecks','strongholds','swamp_huts','villages','woodland_mansions')
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


# A string of three words or more (an apostrophe inside a word: "Where opponent's Pokemon spawns").
SENTENCE_LIKE=re.compile(r"\b[A-Za-z][A-Za-z']{2,} [A-Za-z][A-Za-z']{2,} [A-Za-z][A-Za-z']{2,}")
# Three English words or more in a row, short ones included ("Welcome to my shop"): words a player reads.
ENGLISH_WORDS=re.compile(r"\b[A-Za-z][A-Za-z']+(?:[ ,]+[A-Za-z][A-Za-z']*){2,}")
# Minecraft fills in only %s and %n$s; any other letter (%d, %2$i) makes the game show the whole text as written
# (TranslatableContents.decomposeTemplate fails and the key itself is shown).
UNRENDERED=re.compile(r'%(\d+\$)?([A-Za-rt-z])')
NAME_KINDS=('block','item','entity','effect','fluid')

def mod_ids(z,names):
    """The mod ids a mod file declares: Forge/NeoForge [[mods]] or Fabric's fabric.mod.json id."""
    ids=declared_mods(z,names)
    if not ids and 'fabric.mod.json' in names:
        # Some fabric.mod.json files hold raw line breaks inside strings (Cobblemon Additions), which Fabric accepts.
        try:
            i=json.loads(z.read('fabric.mod.json').decode('utf-8-sig'),strict=False).get('id')
            if isinstance(i,str) and NAMESPACE.match(i):ids=[i]
        except (ValueError,UnicodeError,AttributeError):pass
    return ids

def renderable(text):
    """`text` with the parameters Minecraft cannot fill in (%2$i) written as ones it can (%2$s), and the changed ones."""
    changed=[m[0] for m in UNRENDERED.finditer(text)]
    return UNRENDERED.sub(lambda m:'%'+(m[1] or '')+'s',text),changed


class Audit:
    def __init__(self,out,decisions):
        self.out=out;out.mkdir(parents=True,exist_ok=True)
        self.rows=[];self.files=[];self.errors=[];self.repairs=[];self.counts=Counter();self.decisions=decisions
        self.mixin_targets=set()  # classes some Mixin changes when the game starts (see mixin_targets)
        self.registry=[]  # [file, mod, language key] of every biome, structure, structure set and dimension (REGISTRY_NAME)
        self.extra_keys=[]  # [source, key, English, zh_cn, row fields]: keys a mod's program asks for (unnamed_keys)
    def registry_names(self,label,names):
        for n in sorted(names):
            m=REGISTRY_NAME.search(n)
            if m and '/tags/' not in n:
                kind='biome' if m[2]=='biome' else 'dimension' if m[3] else 'structure'
                self.registry.append([label,m[1],f"{kind}.{m[1]}.{m[4].replace('/','.')}"])
    def missing_names(self,installed=None):
        """A language row for each name key no language file of the modpack has, its English made from the id the way
        the compass mods show it (ghostly_graveyard → Ghostly Graveyard). The row belongs to a mod file of that mod,
        so its translation goes into the translation resource pack like the mod's own text."""
        # The translation resource pack this program made holds keys added here earlier: they are not the mod's own.
        # Paxi's packs are read as references only (desktop_jobs.PAXI_PACKS): a name only they have still needs its row.
        have={r['key'] for r in self.rows if r['kind']=='language'
              and not r['source'].startswith(('resourcepacks/MCTranslator-zh_tw.zip!/','config/paxi/resourcepacks/'))}
        jars={}
        for label,mod,_ in self.registry:
            if label.startswith('mods/') and '!/' not in label:jars.setdefault(mod,label)
        for r in self.rows:
            m=re.match(r'(mods/[^!]+)!/assets/([a-z0-9_.\-]+)/lang/',r['source'])
            if m and r['kind']=='language':jars.setdefault(m[2],m[1])
        # Minecraft itself has no structure names in its language files (the compass mods carry some of them, Explorer's
        # Compass under structure.minecraft.*). Names under minecraft: (the game's own structures and groups, and those
        # mods add there: Trek's pillager_outpost_dark_forest) go into the language file of the mod that shows them.
        host=next((r['source'] for r in self.rows if r['kind']=='language' and r['key'].startswith('structure.minecraft.')
                   and re.match(r'mods/[^!]+!/assets/[a-z0-9_.\-]+/lang/en_us\.json$',r['source'])),None)
        wanted=list(self.registry)+([['minecraft','minecraft',f'structure.minecraft.{n}'] for n in VANILLA_STRUCTURES] if host else [])
        done=set()
        for _,mod,key in wanted:
            if key in have or key in done:continue
            if mod=='minecraft':
                if not host or not key.startswith('structure.'):continue
                source=host
            else:
                if mod not in jars or (installed is not None and mod not in installed):continue
                source=f'{jars[mod]}!/assets/{mod}/lang/en_us.json'
            done.add(key)
            words=[w for w in re.split(r'[_.\-]+',key.split('.',2)[2]) if w]
            self.add(source,key,' '.join(w[:1].upper()+w[1:] for w in words),None,kind='language')
            self.rows[-1]['name_from_id']=True;self.counts['names_from_ids']+=1
    def unnamed_keys(self,label,z,names,keys,constants):
        """Language keys a mod's program asks for that its language files miss, so the game shows them raw even in English.

        - The English sentence handed to Component.translatable as the key (Cobblemon Additions 4.1.6:
          "Spawner: %1$s\nOffset: %2$i"): an entry keyed by that sentence shows the translation. Parameters Minecraft
          cannot fill in become ones it can (renderable; the owner chose this on 2026-10-03) and are noted for checking.
        - Names written under another namespace than the one the mod registers its things with (the same mod registers
          cobblemon-additions:pokemon_spawner and names it block.bca.pokemon_spawner): an entry under the registered
          namespace with the English of the written one, only when the path is a string of the mod's program.
        missing_keys adds the rows, only for keys no language file of the modpack has."""
        ids=mod_ids(z,names)
        spaces=sorted({m[1] for n in names if (m:=re.match(r'assets/([a-z0-9_.\-]+)/lang/en_us\.json$',n))})
        home=ids[0] if len(ids)==1 else spaces[0] if len(spaces)==1 else None
        if not home:return
        for text in sorted(keys):
            if HAN.search(text) or len(text)>1200 or not (' ' in text.strip() and re.search(r'[A-Za-z]{3}',text)):continue
            en,changed=renderable(text);extra=dict(key_sentence=True)
            if changed:extra['format_fixed']=changed
            self.extra_keys.append([f'{label}!/assets/{home}/lang/en_us.json',text,en,None,extra])
        if len(ids)!=1 or ids[0] in spaces:return
        for space in spaces:
            try:
                en=parse(z.read(f'assets/{space}/lang/en_us.json'))
                cn=parse(z.read(f'assets/{space}/lang/zh_cn.json')) if f'assets/{space}/lang/zh_cn.json' in names else {}
            except (ValueError,UnicodeError,KeyError):continue
            for k,v in en.items():
                m=re.fullmatch(r'([a-z]+)\.'+re.escape(space)+r'\.([a-z0-9_/.\-]+)',k)
                if m and m[1] in NAME_KINDS and m[2] in constants and isinstance(v,str):
                    self.extra_keys.append([f'{label}!/assets/{ids[0]}/lang/en_us.json',f'{m[1]}.{ids[0]}.{m[2]}',v,
                                            cn.get(k) if isinstance(cn.get(k),str) else None,dict(key_from_namespace=[space,k])])
    def missing_keys(self):
        """Rows for the keys unnamed_keys found that no language file of the modpack has."""
        have={r['key'] for r in self.rows if r['kind']=='language'
              and not r['source'].startswith(('resourcepacks/MCTranslator-zh_tw.zip!/','config/paxi/resourcepacks/'))}
        for source,key,en,cn,extra in self.extra_keys:
            if key in have:continue
            have.add(key)
            self.add(source,key,en,None,cn,kind='language')
            self.rows[-1].update(extra);self.counts['keys_from_program']+=1
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
        first=len(self.rows);font=own_font_without_chinese(names,read)
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
        for row in self.rows[first:] if font else ():
            if row['kind']=='language':row['no_chinese_font']=label+'!/'+font
        for n in names:
            if not BOOK.search('/'+n) or not n.endswith(('.json','.txt')):continue
            # Other languages are represented by the corresponding English/TW row.
            if re.search(r'/(?!en_us/|zh_tw/)[a-z]{2}_(?:[a-z]{2}|\d{3})/',n,re.I):continue
            # Another language's copy of an English page under a code of its own (Alex's Caves books/tok/: Toki Pona).
            parts=n.split('/')
            if any(p not in ('en_us','zh_tw','zh_cn') and '/'.join(parts[:i]+['en_us']+parts[i+1:]) in names for i,p in enumerate(parts[:-1])):continue
            if '/models/' in '/'+n or '/textures/' in '/'+n:continue  # a block model's "credit": Made with Blockbench
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
                    if field in PATCHOULI_SKIP_FIELDS or NOT_TEXT_FIELD.search(str(field)):continue
                    if field in DISPLAY or HAN.search(value) or (LATIN.search(value) and ' ' in value):
                        self.add(label+'!/'+n,json.dumps(path),value,at(tw,path),at(cn,path),'book')
            except Exception as e:self.errors.append([label,n,str(e)])
        for n in sorted(names):
            # Words a data pack shows as written: structures (NPC names, shop categories, signs, books), functions
            # (tellraw, books it gives), loot tables and advancements, RCT trainer names; see embedded_text.
            if not embedded_text.is_file('/'+n):continue
            try:
                for key,text in embedded_text.units(n,read(n)):self.add(label+'!/'+n,key,None,text,kind='embedded_text')
                self.counts['embedded_text_files']+=1
            except Exception as e:self.errors.append([label,n,'embedded text: '+str(e)])
        for n in sorted(names):
            if not DATA_TEXT.search('/'+n):continue
            try:
                for path,field,value in leaves(parse(read(n))):
                    if field not in DATA_TEXT_FIELDS or not value.strip():continue
                    # Chinese is what the game shows (converted to Taiwan wording); English needs a translation.
                    if HAN.search(value):self.add(label+'!/'+n,json.dumps(path),None,value,kind='data_text')
                    elif LATIN.search(value):self.add(label+'!/'+n,json.dumps(path),value,None,kind='data_text')
                self.counts['data_text_files']+=1
            except Exception as e:self.errors.append([label,n,str(e)])
    def unsupported_data(self,label,names,read):
        """A mod's data-pack JSON whose display fields hold a sentence (Chinese, or three English words or more), in a
        format no reader covers: listed once per folder (data/<mod>/<kind>/) so a whole kind of text (quests,
        dialogue, NPC names) is never silently left out. Fields other than display ones (a tag file's "__comment")
        are a developer's notes and are not listed."""
        found=defaultdict(list)
        for n in sorted(names):
            m=DATA_JSON.match(n)
            if (not m or DATA_TEXT.search('/'+n) or BOOK.search('/'+n) or embedded_text.is_file('/'+n)
                    or m[2] in ('lang','patchouli_books','tags','recipe','recipes','worldgen')):continue
            try:
                raw=read(n)
                for _,field,value in leaves(parse(raw)):
                    if field in DISPLAY and ((HAN.search(value) and SENTENCE.search(value))
                                             or (not HAN.search(value) and ENGLISH_WORDS.search(value))):
                        found[f'data/{m[1]}/{m[2]}/'].append((n,value));break
            except Exception:continue
        for folder,files in found.items():
            n,value=files[0]
            self.add(label+'!/'+folder,'folder',None,f'{len(files)} 個資料檔含顯示文字，例如 {n}：{value[:200]}',kind='unsupported_config_text')
            self.counts['unsupported_data_text_files']+=len(files)
    def archive(self,p,label):
        self.counts['archives']+=1
        first_row=len(self.rows)
        try:
            with zipfile.ZipFile(p) as z:
                names=set(z.namelist())
                for info in z.infolist():
                    self.files.append(dict(source=label+'!/'+info.filename,size=info.file_size,crc=info.CRC,kind='class' if info.filename.endswith('.class') else 'resource'))
                self.collection(label,names,z.read)
                self.unsupported_data(label,names,z.read)
                self.registry_names(label,names)
                self.nested(z,label,names)
                screen=False;linked=[];literals=[];compared=set();keys=set();constants_seen=set()
                flow=JarFlow.of_zip(z)  # follows a text a class hands to a helper method or field of this file
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
                            cf,safe=proven_strings(raw,flow);constants=cf.utf.items();keys|=cf.keys;constants_seen|=set(cf.utf.values())
                            tips=config_tooltips(raw) if any('設定說明' in use for _,use in safe.values()) else {}
                            developer=developer_strings(raw)
                            _,plain,seen=plain_strings(raw);compared|=seen
                        except (ValueError,KeyError,IndexError,struct.error,UnicodeError):
                            # An unsupported class remains visible for inspection; it is never writable.
                            safe={};tips={};developer=set();plain={};constants=enumerate(utf8_constants(raw))
                        for i,s in constants:
                            if (i in safe and LATIN.search(s)) or HAN.search(s) or (len(s)<1200 and SENTENCE_LIKE.search(s)):
                                supported=i in safe and label.startswith('mods/') and label.count('!/')==0
                                self.add(label+'!/'+n,i,None,s,kind='class_display' if supported else 'class_candidate')
                                if not supported and i in developer:self.rows[-1]['developer_use']=True
                                if not supported and generator:self.rows[-1]['language_generator']=True
                                if not supported and i in plain and HAN.search(s):literals.append(self.rows[-1])
                                if supported:
                                    self.rows[-1]['display_use']=safe[i][1]
                                    if tips.get(i):linked.append((self.rows[-1],tips[i]))
                    except Exception as e:self.errors.append([label,n,'class extraction: '+str(e)])
                if label.startswith('mods/') and label.count('!/')==0:self.unnamed_keys(label,z,names,keys,constants_seen)
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
        self.registry_names('instance',names)  # data packs in folders (OpenLoader, datapacks)
        for n,p in names.items():
            self.files.append(dict(source=n,size=p.stat().st_size,kind='loose'))
            if p.suffix=='.class':
                try:
                    for i,s in enumerate(utf8_constants(p.read_bytes())):
                        if HAN.search(s) or (len(s)<1200 and SENTENCE_LIKE.search(s)):
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
            if LANG.match('/'+n) or BOOK.search('/'+n) or DATA_TEXT.search('/'+n):continue
            if n.split('/',1)[0] in CONTENT_PACK_FOLDERS:
                # Beside language files, a content pack shows Chinese of its own only in display fields
                # (TACZ text_show "text": a brand name printed on the gun model).
                if p.suffix.lower()=='.json':
                    try:
                        for path,field,value in leaves(parse(p.read_bytes())):
                            if field in DISPLAY and HAN.search(value):self.add(n,json.dumps(path),None,value,kind='config')
                    except (ValueError,UnicodeError):pass
                continue
            if p.suffix not in ('.js','.zs','.json','.snbt','.toml','.txt','.local','.lang','.cfg','.yaml','.yml','.properties'):continue
            if NOT_TEXT_FILE.search(n):continue  # notes for people (readme, notice), tool caches, IDE files
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
                    for lineno,i,value,is_key,_,_ in string_literals(raw,p.suffix,n):
                        if is_key:continue  # a setting's or an object's name, not text
                        if (p.suffix in ('.cfg','.yaml','.yml','.properties') or FANCYMENU.search(n)) and not HAN.search(value):continue  # English stays unlisted
                        line=lines[lineno-1]
                        visible=HAN.search(value) or re.search(r'\b(title|subtitle|description|Text\.of|text\.add|tooltip|displayName|label|message)\b'
                                                               r'|\.(?:add(?:Shift)?Tooltip|setDisplayName|addJEIInfo|addInfo)\(',line)
                        if visible and (HAN.search(value) or LATIN.search(value)):
                            self.add(n,f'{lineno}:{i}',None,value,kind='script_candidate' if p.suffix in SCRIPT_SUFFIXES else 'config')
                            # A plain note read by some mod (welcome.txt): converted, but no reader was checked.
                            if p.suffix=='.txt' and not FANCYMENU.search(n) and plain_text(raw):self.rows[-1]['unverified']=True
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
        # Do not silently lose a future shop/config format. In a file that produced no row above, Chinese in quotes
        # is converted to Taiwan wording in place, marked as not proven to be read (unverified_literals); what is
        # left (Chinese outside quotes, a likely display field in English) is listed as an unsupported candidate.
        produced={r['source'].removeprefix('instance!/') for r in self.rows}
        for n,p in names.items():
            content=n.split('/',1)[0] in CONTENT_PACK_FOLDERS
            if (n in produced or LANG.match('/'+n) or BOOK.search('/'+n) or DATA_TEXT.search('/'+n) or (content and p.suffix.lower()!='.json')
                    or p.suffix.lower() not in TEXT_CONFIG_SUFFIXES or p.stat().st_size>16*1024*1024):continue
            try:
                text=decode(p.read_bytes())
                if '\0' in text:continue
            except (OSError,UnicodeError):continue
            # A content pack's own data (TACZ gun definitions, model files) is read for display fields only.
            sample=unsupported_sample(n,self.unverified_literals(n,text,content),root,strict=content)
            if sample:
                self.add(n,'file',None,sample[:500],kind='unsupported_config_text')
                self.counts['unsupported_config_text_files']+=1
        self.unscanned(root)
    def unscanned(self,root):
        """List text in folders no reader covers, so a new kind of text (CraftTweaker scripts, TACZ gun packs) is
        never silently left out: a text file with Chinese, a language file, or an archive carrying language files,
        in any top-level folder of the modpack other than those scanned and those holding no player text.
        Language files there are read like any other (a missing zh_tw.json is added beside them) and Chinese in
        quotes is converted in place (unverified_literals); both are marked unverified, since no mod's code was
        checked to read them. What is left is listed in the report as a format not supported yet."""
        scanned={f.casefold() for f in LOOSE_FOLDERS+CONTENT_PACK_FOLDERS+('mods',)};langs=[]
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
                if LANG.match('/'+n):langs.append(n);continue  # read below as language files
                sample=unsupported_sample(n,self.unverified_literals(n,text,True),root,strict=True)
                if sample:
                    self.add(n,'file',None,sample[:500],kind='unsupported_config_text')
                    self.counts['unscanned_text_files']+=1
        if langs:
            first=len(self.rows);files={n:root/n for n in langs}
            self.collection('instance',set(files),lambda n:files[n].read_bytes())
            for row in self.rows[first:]:row['unverified']=True
            self.counts['unverified_language_rows']+=len(self.rows)-first
    def unverified_literals(self,n,text,strict):
        """Rows for the Chinese strings of a file no reader covers, to be converted to Taiwan wording in place;
        returns the text with every quoted string blanked, so what is left over can still be listed.

        Only quoted strings that are not keys count (string_literals, the same reader the writer and the read-back
        use); strict keeps JSON to display fields, as a model's bone names or a gun's identifier are names other
        files look up. Saves (player progress), other languages' files and tool caches are never touched."""
        suffix=PurePosixPath(n).suffix.lower()
        if (suffix not in UNVERIFIED_SUFFIXES or n.startswith('saves/') or NOT_TEXT_FILE.search(n)
                or re.search(r'(?:^|/)lang/',n) or other_language(n)):return text
        try:literals=list(string_literals(text,suffix,n))
        except Exception:return text
        starts=[0]
        for line in text.splitlines(True):starts.append(starts[-1]+len(line))
        blank=list(text);fields=defaultdict(set)
        if strict and suffix=='.json':
            # Each value's field, arrays included (an "author": [...] list names its people on lines of their own).
            try:
                for _,field,value in leaves(parse(text.encode('utf-8'))):fields[value].add(field)
            except ValueError:pass
        for lineno,i,value,is_key,start,end in literals:
            if strict and suffix=='.json' and not is_key and HAN.search(value):
                line_field=re.search(r'"([^"]+)"\s*:\s*$',text[starts[lineno-1]:start])
                names=fields.get(value) or ({line_field[1]} if line_field else set())
                if not names or not names<=DISPLAY:
                    # A sentence under a field of unknown use stays in the text, so it is listed; a name is not.
                    if (not SENTENCE.search(value) or any(NOT_TEXT_FIELD.search(str(f)) for f in names)
                            or re.search(r"['\";]",value)):
                        blank[start:end]=' '*(end-start)  # a name, an author list or a model's expression
                    continue
            blank[start:end]=' '*(end-start)
            if is_key or not HAN.search(value):continue
            self.add(n,f'{lineno}:{i}',None,value,kind='config');self.rows[-1]['unverified']=True
            self.counts['unverified_literals']+=1
        return ''.join(blank)
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
