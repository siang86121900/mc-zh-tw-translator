"""Read-only planning, explicit review and guarded installation for desktop UI."""
from __future__ import annotations

import collections
import copy
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from full_translation_audit import Audit, parse, placeholders, at
from opencc import OpenCC
from .deployment import apply_reviewed, contained, file_hash, atomic_copy
from .desktop_references import refresh, pick_reference, HUMAN_TW_KINDS
from .translator import MINECRAFT_GLOSSARY, is_jar_signature_file
from .verifier import VerifyResult, check_java_zipfs

SOURCE_NAMES = {'same_source_zh_cn':'同檔簡中', 'instance_zh_cn':'模組包中文',
                'reference_pack_or_cfpa':'參考庫', 'glossary':'術語表',
                'translation_memory':'已確認記憶', 'existing_zh_tw':'既有繁中',
                'ai_translation':'AI 補譯', 'manual':'使用者修訂', 'untranslated':'缺少來源',
                'keep_original':'無需翻譯','instance_resourcepack':'已安裝資源包',
                'not_installed':'未安裝模組（略過）','user_glossary':'自訂譯名','not_display':'程式內部字串',
                'cross_version_reference':'跨版本參考','official_vanilla':'官方原版譯名','stale_reference':'參考庫（版本不同）'}
HAN = re.compile('[\u3400-\u9fff]')
FORMAT = re.compile(r'§[0-9a-fk-or]|\$\([^)]+\)|\{[\w.]+\}', re.I)
TRANSLATION_PACK = re.compile(r'(?:instance!/)?(?:config/openloader/|resourcepacks/)')
PARAMETER = re.compile(r'%(?:\d+\$)?[-#+ 0,(]*\d*(?:\.\d+)?[sdfxXeEgGc%]|\{\d*\}|\$\([^)]+\)|§[0-9a-fk-or]|\\n', re.I)
ROMAN = re.compile(r'(?=[MDCLXVI])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})')
KEY_NAMES = {'shift','ctrl','control','alt','tab','esc','escape','enter','return','space','backspace','delete','del',
             'insert','home','end','page up','page down','caps lock','num lock','lmb','rmb','mmb','lshift','rshift',
             'lctrl','rctrl','lalt','ralt','cmd','command','option','meta','win','super'}
# Technical abbreviations players read as-is; ordinary words stay translatable.
ABBREVIATIONS = {'NBT','RGB','RGBA','ARGB','HEX','HSV','UUID','JSON','ID','FPS','TPS','MSPT','GUI','HUD','API','URL',
                 'XP','HP','MP','CPU','GPU','RAM','FE','RF','EU','DPS','UI','JEI','REI','EMI','LOD','VBO','LAN','PVP','PVE',
                 'CF','AE','ME','EMC','Beta','Alpha','AP','SHP','EP','SP','POI','AABB','SNBT','IPN','OpenGL','REM'}
# Platform, brand and format names that stay as written (only reached when no source translated them).
BRANDS = {'patreon','discord','wiki','github','github releases','curseforge','modrinth','ko-fi','kofi','bluesky','twitter',
          'youtube','twitch','reddit','minecraft','markdown','opengl','bluemap','dynmap','journeymap','optifine'}
# Upper-case script keywords shown in visual script editors (e.g. FancyMenu action blocks).
SCRIPT_KEYWORDS = {'IF','ELSE','ELSE-IF','ELSEIF','WHILE','FOR','AND','OR','NOT','SWITCH','CASE','END'}
# Keys that name another mod's biome/dimension/structure; they only show when that mod is installed.
KEY_MOD_REFERENCE = re.compile(r'^(?:biome|dimension|structure)\.([a-z0-9_]+)[./]|^travelerstitles\.([a-z0-9_]+)\.')
# Measurement units shown next to numbers (energy, fluid, pressure, temperature, time, power).
UNITS = {'mb','b','kb','bar','psi','rpm','hz','khz','w','kw','mw','v','a','j','kj','t','s','ms','ns','μi','µi','°c','°f','k',
         'fe','rf','eu','cf','mj','su','xp','ep','mp','hp'}


def keep_original_reason(text, key='', namespace=''):
    """Explain why a missing-source string needs no translation, else ''.

    Only unambiguous cases qualify, so nothing a player would expect in Chinese is hidden.
    The language key gives context the text alone lacks (comments, credits, song titles).
    """
    if not isinstance(text,str) or not text.strip():return ''
    key=str(key or '')
    if re.match(r'_|.*(?:^|\.)__?comment',key,re.I):return '開發者註解，非顯示文字'
    if re.search(r'(?:^|\.)jukebox_song\.|music_disc[^.]*\.desc$|\.music\.',key) and re.fullmatch(r'[^-\n]+ - [^\n]+',text.strip()):return '歌曲作者與曲名'
    if re.search(r'painting\..*\.author$',key) or key.startswith('metadata.authors.'):return '作者名稱或作者備註'
    if re.search(r'(?:^|\.)font\..*\.preview$',key):return '字型預覽用的英文範例句'
    if key.endswith('.latin'):return '植物學名'
    stripped=text.strip()
    if '�' in text:return '刻意製作的亂碼效果'
    if stripped.casefold() in BRANDS:return '平台或品牌名稱'
    if re.fullmatch(r'#?[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',stripped) and re.search(r'\d',stripped):return '色碼'
    if re.fullmatch(r'#[A-Za-z_]+',stripped):return '書本樣板變數'
    if re.match(r'/[a-z]',stripped):return '指令用法'
    if re.fullmatch(r'(?:config|assets|data|kubejs|mods|saves|defaultconfigs)(?:/[a-z0-9_.\-]+)+|[a-z0-9_.\-]+:[a-z0-9_./\-]+|\w+=\w+(?:,\w+=\w+)*',stripped):return '檔案路徑、ID 或語法範例'
    compact=lambda s:re.sub('[^a-z0-9]','',s.lower().replace('&','and'))
    name=compact(re.sub(r'\s+wiki$','',stripped,flags=re.I));mod=compact(re.sub(r'\d+$','',namespace or ''))
    if mod and len(name)>=4 and name in (mod,mod.removesuffix('mod')):return '模組名稱'
    core=PARAMETER.sub(' ',text).strip()
    if not re.search('[A-Za-z]',core):return '只有參數、數字或符號'
    if re.fullmatch(r'[\d\s.,x×*+\-/:%()\[\]]+',core,re.I) and core!=text.strip():return '只有參數、數字或符號'  # e.g. %d (%dx)
    if core!=text.strip() and re.fullmatch(r'[A-Z]{1,4}|/[a-z]{1,2}',core):return '數值單位'  # e.g. %1$s HPS, %d FE, %s/t
    units=[p for p in re.split(r'\s*/\s*',core.strip('/ ')) if p]
    if units and all(p.casefold() in UNITS for p in units):return '數值單位'  # e.g. %dmB, bar, °C, FE/RF/μI/CF
    if re.match(r'(?i)https?://\S+$',core):return '網址'
    if re.fullmatch(r'[\d\s.,x×*+\-/:%()]+',core,re.I) and re.search(r'\d',core):return '尺寸或數值'
    if ROMAN.fullmatch(core) and core not in ('MIX','DIV','MID','DIM','MIL','LID'):return '羅馬數字'
    if re.fullmatch('[A-Za-z]',core):return '單一字母或按鍵'
    parts=[p.strip() for p in re.split(r'\s*[+/]\s*|\s+',core) if p.strip()]
    if parts and all(p.casefold() in KEY_NAMES or re.fullmatch(r'[A-Za-z]|F\d{1,2}',p) for p in parts):return '按鍵名稱'
    # Labels made only of abbreviations, single letters or units around values: "§lFPS:§r %s", "X: %d / Y: %d".
    if re.fullmatch(r'[A-Za-z0-9μµ°\s.,:：/()\[\]+\-|，]+',core):
        tokens=re.findall(r'[A-Za-zμµ°][A-Za-z0-9μµ°\-]*',core)
        if tokens and all(t in SCRIPT_KEYWORDS for t in tokens):return '程式關鍵字'
        if tokens and all(t in ABBREVIATIONS or len(t)==1 or t.casefold() in UNITS or t.casefold() in KEY_NAMES for t in tokens):
            return '技術縮寫、座標或按鍵'
    return ''


def reclassify_keep_original(session):
    """Apply keep_original rules to reports saved by older versions (in memory only)."""
    moved=0
    for row in session.get('rows',[]):
        if row.get('origin')!='untranslated' or not row.get('supported') or row.get('ai_attempted'):continue
        m=re.search(r'assets/([^/]+)/',row.get('source',''))
        reason=keep_original_reason(row.get('en') or row.get('zh_cn') or row.get('current') or '',row.get('key',''),m[1] if m else '')
        if reason:row.update(origin='keep_original',issue='無需翻譯：'+reason);moved+=1
    if moved:
        counts=session.setdefault('source_counts',{})
        counts['untranslated']=max(0,counts.get('untranslated',0)-moved)
        counts['keep_original']=counts.get('keep_original',0)+moved
        if 'preview_pending' in session:session['preview_pending']=max(0,session['preview_pending']-moved)
    return moved


def describe_error(error):
    """Turn a raw audit error list into one readable report line."""
    parts=[p for p in error if isinstance(p,str)] if isinstance(error,(list,tuple)) else [str(error)]
    where=Path(parts[0]).name if parts else ''
    detail=parts[-1] if len(parts)>1 else ''
    if 'Expecting' in detail:
        detail='檔案本身 JSON 格式錯誤（'+detail+'）'
        if any(isinstance(p,dict) and 'zh_tw' in p for p in error):detail+='。重新執行一鍵翻譯時會自動重建這個繁中檔。'
    return (where+'：'+detail) if detail else where


def validate_text(original, value):
    if not isinstance(value,str) or '\ufffd' in value:
        return False
    if not original:
        return True
    return (placeholders(original)==placeholders(value)
            and collections.Counter(FORMAT.findall(original))==collections.Counter(FORMAT.findall(value))
            and original.count('\n')==value.count('\n'))


S2T = OpenCC('s2t')  # character-only conversion: any change means simplified characters were present


class TranslationMemory:
    """Translations the user confirmed in the report, reused for the same mod, key and English text.

    Only user-confirmed rows are stored, so automatic, reference or AI output never becomes memory.
    """
    def __init__(self, home):
        self.path=Path(home)/'translation_memory.json'
        try:self.entries=json.loads(self.path.read_text(encoding='utf-8')).get('entries',{})
        except (OSError,ValueError):self.entries={}
    @staticmethod
    def ident(namespace,key,original):
        return namespace+'\t'+key+'\t'+hashlib.sha256(original.encode('utf-8')).hexdigest()[:16]
    def lookup(self,namespace,key,original):
        entry=self.entries.get(self.ident(namespace,key,original)) if namespace and original else None
        return entry['text'] if entry else None
    def remember(self,namespace,key,original,text,source):
        self.entries[self.ident(namespace,key,original)]=dict(text=text,original=original,source=source,
                                                              confirmed_at=datetime.now().isoformat(timespec='seconds'))
        write_json(self.path,dict(format=1,entries=self.entries))


class UserGlossary:
    """Names the user fixed on the 譯名與用詞 page (e.g. Benimaru → 紅丸).

    Whole strings that equal a term use it directly; AI requests receive the terms they contain.
    """
    def __init__(self, home):
        self.path=Path(home)/'user_glossary.json'
        try:self.entries={e['en'].casefold():e for e in json.loads(self.path.read_text(encoding='utf-8')).get('entries',[])}
        except (OSError,ValueError,KeyError,AttributeError):self.entries={}
    def lookup(self, original):
        entry=self.entries.get(original.strip().casefold()) if isinstance(original,str) else None
        return entry['zh'] if entry else None
    def terms_in(self, text):
        return {e['en']:e['zh'] for e in self.entries.values()
                if re.search(r'(?<![A-Za-z])'+re.escape(e['en'])+r'(?![A-Za-z])',text or '',re.I)}
    def set(self, en, zh):
        en=en.strip();zh=zh.strip()
        if not en or not zh:raise ValueError('英文與譯名都需要填寫。')
        self.entries[en.casefold()]=dict(en=en,zh=zh,updated_at=datetime.now().isoformat(timespec='seconds'));self.save()
    def remove(self, en):
        self.entries.pop(en.strip().casefold(),None);self.save()
    def save(self):
        write_json(self.path,dict(format=1,entries=sorted(self.entries.values(),key=lambda e:e['en'].casefold())))


def slim(row):
    """Report rows keep what review, apply and restore need; scan-only fields stay in the audit files."""
    return {k:v for k,v in row.items() if k not in ('flags','status','reason')}


def internal_reason(text):
    """Why a class/script/config candidate is clearly not player-facing text, else ''."""
    s=(text or '').strip()
    if not s:return '空白'
    if '{}' in s:return '記錄檔訊息（{} 參數）'
    if re.search(r'[;{}]|==|->|&&|\|\||\w\(\)|\w\.\w+\(',s):return '程式碼片段'
    if ' ' not in s and (re.search(r'[._/:$#<>]',s) or re.search(r'[a-z][A-Z]',s) or s.isupper()):return '程式識別字'
    if re.fullmatch(r'[\W\d_]+',s):return '只有符號或數字'
    return ''


# Keys that name a thing (item, block, mob...); a name should read the same in every mod, while UI words
# such as "None" or "Default" legitimately differ by context and are left alone.
NAME_KEY = re.compile(r'^(?:item|block|entity|effect|enchantment|biome|fluid|mob_effect)\.')
# Trust order when two sources name the same thing differently; mirrors the source order in plan().
ORIGIN_TRUST = ['manual','translation_memory','user_glossary','reference_human','instance_resourcepack','existing_zh_tw',
                'official_vanilla','instance_zh_cn','same_source_zh_cn','reference_converted','stale_reference',
                'cross_version_reference','glossary','ai_translation']


def trust_rank(row):
    origin=row.get('origin')
    if origin=='reference_pack_or_cfpa':
        # People-written zh_tw packs rank above CFPA, which is converted from simplified Chinese.
        origin='reference_human' if row.get('evidence') in ('reference:tw','reference:para') else 'reference_converted'
    return ORIGIN_TRUST.index(origin) if origin in ORIGIN_TRUST else len(ORIGIN_TRUST)


def conflicting_terms(session, limit=500):
    """Names translated differently across mods, each with a suggested translation.

    The suggestion is the variant backed by the most trusted source, then the most common one.
    """
    variants=collections.defaultdict(collections.Counter);trust=collections.defaultdict(dict);display={}
    for r in session.get('rows',[]):
        original=r.get('en')
        if not r.get('supported') or not NAME_KEY.match(r.get('key','')) or not isinstance(original,str) or len(original)>40:continue
        if not HAN.search(r.get('proposed') or '') or r.get('origin') in ('untranslated','keep_original'):continue
        # Same English and same key tail (e.g. palm_log) = the same thing in different mods. A different tail
        # (wall_torch vs torch, umvuthana vs umvuthana_follower) is a different thing that may be named apart on purpose.
        key=(original.strip().casefold(),r['key'].split('.',2)[-1]);zh=r['proposed'].strip();display.setdefault(key,original.strip())
        variants[key][zh]+=1
        rank=trust_rank(r)
        trust[key][zh]=min(rank,trust[key].get(zh,rank))
    rows=[]
    for key,counter in variants.items():
        if len(counter)<2:continue
        ordered=sorted(counter.items(),key=lambda kv:(trust[key][kv[0]],-kv[1]))
        rows.append(dict(en=display[key],key_tail=key[1],variants=ordered,suggested=ordered[0][0]))
    rows.sort(key=lambda x:-sum(c for _,c in x['variants']))
    return rows[:limit]


def apply_term(session, en, zh, key_tail=None):
    """Use the agreed name for every name row whose whole text is `en` (and key tail, when given)."""
    changed=0
    for r in session.get('rows',[]):
        if (isinstance(r.get('en'),str) and r['en'].strip().casefold()==en.strip().casefold() and r.get('supported')
                and not r.get('installed') and NAME_KEY.match(r.get('key',''))
                and (key_tail is None or r['key'].split('.',2)[-1]==key_tail)):
            if not validate_text(r['en'],zh):continue
            if r.get('origin') not in ('user_glossary',):r['previous_origin']=r.get('origin')
            r.update(proposed=zh,origin='user_glossary',evidence='user_glossary.json',issue='',changed=zh!=r.get('current'),
                     reviewed=False,review_method=None);changed+=1
    return changed


def usable(original, value):
    return isinstance(value,str) and bool(HAN.search(value)) and validate_text(original,value)


def write_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    # Reports hold ~100k rows; compact separators roughly halve the file and its load time.
    compact=path.name=='session.json'
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=None if compact else 2,separators=(',',':') if compact else None),encoding='utf-8')
    for attempt in range(10):
        try:
            temp.replace(path);break
        except PermissionError:
            # Windows refuses to replace a file another thread is reading at this instant.
            if attempt==9:raise
            time.sleep(.05)
    if path.name=='session.json' and isinstance(data,dict) and 'rows' in data:
        # Reports can be ~100 MB; the history list reads this small sidecar instead.
        # It is a display convenience, so failing to write it must never fail the job.
        try:write_json(path.with_name('summary.json'),session_summary(data))
        except OSError:pass


def session_summary(session):
    rows=session.get('rows',[])
    return dict(status=session.get('status'),installed_count=session.get('installed_count',0),
                translated=sum(bool(r.get('changed') and r.get('supported')) for r in rows),
                pending_apply=sum(bool(r.get('reviewed') and r.get('changed') and r.get('supported') and not r.get('installed')) for r in rows),
                missing=sum(r.get('origin')=='untranslated' and bool(r.get('supported')) for r in rows),
                instance=session.get('instance'),batch=session.get('batch'))


LAUNCHER_ROOTS = (
    ('CurseForge', '{home}/curseforge/minecraft/Instances'),
    ('Modrinth', '{appdata}/ModrinthApp/profiles'),
    ('Modrinth', '{appdata}/com.modrinth.theseus/profiles'),
    ('Prism', '{appdata}/PrismLauncher/instances'),
    ('PolyMC', '{appdata}/PolyMC/instances'),
    ('MultiMC', '{home}/MultiMC/instances'),
    ('ATLauncher', '{appdata}/ATLauncher/instances'),
    ('GDLauncher', '{appdata}/gdlauncher_carbon/data/instances'),
)


def is_instance(folder):
    return folder.is_dir() and any((folder/x).is_dir() for x in ('mods','kubejs','config'))


def curseforge_instances():
    """CurseForge's own instance list, which also covers a moved or custom instance folder.

    Returns dicts with name, path, projectID, fileID and gameVersion; projectID/fileID are 0
    for instances the user created by hand.
    """
    appdata=Path(os.environ.get('APPDATA',Path.home()/'AppData/Roaming'))
    try:
        data=json.loads((appdata/'CurseForge/agent/GameInstances/MinecraftGameInstance.json').read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):
        return []
    result=[]
    for x in data if isinstance(data,list) else []:
        try:
            path=Path(x['installPath'])
            if not is_instance(path):continue
            result.append(dict(name=x.get('name') or path.name,path=path,projectID=int(x.get('projectID') or 0),
                               fileID=int(x.get('fileID') or 0),gameVersion=x.get('gameVersion') or ''))
        except (KeyError,TypeError,ValueError,OSError):
            continue
    return result


def discover_instances(extra=()):
    """Modpack folders from common launcher locations plus folders the user picked before.

    Launchers let users move their data, so this is a convenience list only; pasting a
    path or choosing a folder always remains available.
    """
    home=Path.home(); appdata=Path(os.environ.get('APPDATA',home/'AppData/Roaming'))
    found={}
    for x in curseforge_instances():
        found.setdefault(str(x['path']).rstrip('\\/').casefold(),('CurseForge',x['name'],x['path']))
    for launcher,pattern in LAUNCHER_ROOTS:
        root=Path(pattern.format(home=home,appdata=appdata))
        try:
            children=[p for p in root.iterdir()] if root.is_dir() else []
        except OSError:
            continue
        for p in children:
            # Prism/MultiMC keep the game under .minecraft or minecraft.
            game=next((c for c in (p,p/'.minecraft',p/'minecraft') if is_instance(c)),None)
            if game:found.setdefault(str(game).casefold(),(launcher,p.name,game))
    for path in extra:
        p=Path(str(path).strip().strip('"'))
        if path and is_instance(p):found.setdefault(str(p).casefold(),('最近使用',p.name,p))
    return sorted(found.values(),key=lambda x:(x[0]!='最近使用',x[0],x[1].casefold()))


def asset_namespaces(z, depth=0):
    """Asset and data namespaces of a mod jar or datapack, including jar-in-jar libraries.

    Data namespaces count too: worldgen mods such as Terralith ship biomes without assets.
    """
    found={n.split('/')[1] for n in z.namelist() if n.startswith(('assets/','data/')) and n.count('/')>=2}
    if depth<2:
        for name in z.namelist():
            if not name.lower().endswith('.jar'):continue
            try:
                with zipfile.ZipFile(io.BytesIO(z.read(name))) as inner:found|=asset_namespaces(inner,depth+1)
            except (zipfile.BadZipFile,OSError,RuntimeError):continue
    return found


SCAN_CACHE_VERSION = 'scan-3'


def scan_cache(home, instance):
    # One folder per modpack, so pruning after a scan never touches another modpack's cache.
    return Path(home)/'cache'/'scan'/hashlib.sha256(str(Path(instance).resolve()).casefold().encode()).hexdigest()[:16]


def scan_archive(audit, p, label, digest, cache):
    """Scan one archive, reusing the cached result when the same file (by hash) was scanned before."""
    key=hashlib.sha256(f'{SCAN_CACHE_VERSION}|{label}|{digest}'.encode()).hexdigest()[:40]
    path=cache/f'{key}.json.gz' if cache else None
    if path and path.exists():
        try:
            data=json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
            audit.rows.extend(data['rows']);audit.files.extend(data['files']);audit.errors.extend(data['errors'])
            audit.repairs.extend(data['repairs']);audit.counts.update(data['counts'])
            audit.installed_namespaces|=set(data['namespaces']);audit.cache_hits+=1
            return key
        except (OSError,ValueError,KeyError):path.unlink(missing_ok=True)
    marks=(len(audit.rows),len(audit.files),len(audit.errors),len(audit.repairs));before=collections.Counter(audit.counts)
    audit.archive(p,label)
    namespaces=set()
    if Path(label).parts[0] in ('mods','datapacks'):
        try:
            with zipfile.ZipFile(p) as z:namespaces=asset_namespaces(z)
        except (OSError,zipfile.BadZipFile):pass
    audit.installed_namespaces|=namespaces
    if path:
        delta=collections.Counter(audit.counts);delta.subtract(before)
        data=dict(rows=audit.rows[marks[0]:],files=audit.files[marks[1]:],errors=audit.errors[marks[2]:],
                  repairs=audit.repairs[marks[3]:],counts={k:v for k,v in delta.items() if v},namespaces=sorted(namespaces))
        try:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(gzip.compress(json.dumps(data,ensure_ascii=False).encode('utf-8'),5))
        except OSError:pass
    return key


def scan(instance, report, notify, cancelled, cache=None):
    audit = Audit(report/'audit',{});audit.cache_hits=0;used=set()
    audit.source_hashes={}
    archives=[]
    for folder in ('mods','resourcepacks','datapacks','config/openloader'):
        for p in (instance/folder).rglob('*'):
            if p.suffix.lower() in ('.jar','.zip') and p.is_file():
                contained(instance,p.relative_to(instance).as_posix())
                archives.append(p)
    audit.installed_namespaces={'minecraft','realms','c','forge','neoforge','fabric'}
    for i,p in enumerate(sorted(archives)):
        if cancelled(): raise InterruptedError('已停止，遊戲原檔未修改。')
        label=p.relative_to(instance).as_posix();digest=file_hash(p);audit.source_hashes[label]=digest
        notify(5+int(35*i/max(1,len(archives))),'掃描模組與資源',p.name+(f'（已沿用 {audit.cache_hits} 個未變動檔案的結果）' if audit.cache_hits else ''))
        used.add(scan_archive(audit,p,label,digest,cache))
    if cache and cache.is_dir():
        # Keep the cache to what this modpack currently contains so it cannot grow without bound.
        for stale in cache.glob('*.json.gz'):
            if stale.name.removesuffix('.json.gz') not in used:stale.unlink(missing_ok=True)
    kubejs=instance/'kubejs/assets'
    if kubejs.is_dir():audit.installed_namespaces|={p.name for p in kubejs.iterdir() if p.is_dir()}
    notify(42,'掃描任務、設定與腳本','正在檢查外部文字和程式字串候選')
    for folder in ('kubejs','config','defaultconfigs','patchouli_books','datapacks','resourcepacks','vaultpatcher','hotai','immersive_furniture'):
        for p in (instance/folder).rglob('*'):
            if p.is_file() and p.suffix.lower() not in ('.zip','.jar'):
                contained(instance,p.relative_to(instance).as_posix())
                audit.source_hashes[p.relative_to(instance).as_posix()]=file_hash(p)
    audit.loose(instance)
    audit.finish()
    return audit


def plan(instance: Path, home: Path, notify, cancelled=lambda:False, references=None, checkpoint=lambda _:None):
    instance=instance.resolve(); home=home.resolve()
    if not instance.is_dir() or not any((instance/x).is_dir() for x in ('mods','kubejs','config')):
        raise ValueError('請選擇模組包的根資料夾，裡面應有 mods、kubejs 或 config。')
    if home.is_relative_to(instance) or instance.is_relative_to(home):
        raise ValueError('程式資料目錄不能與遊戲資料夾重疊，請將 EXE 移到遊戲資料夾以外。')
    batch=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    report=home/'output'/instance.name/'報告'/batch
    report.mkdir(parents=True)
    result=dict(instance=str(instance),report=str(report),batch=batch,status='scanning',rows=[],
                errors=[],source_counts={},backup=None,installed_count=0,limits=[
                    'AI 補翻需另行連接 ChatGPT 並同意使用原方案 Codex 額度；不使用付費翻譯 API。',
                    '程式字串、腳本和非語系設定需確認顯示用途；掃描候選不等於漏翻。',
                    '譯文需在介面校對後才能套用；結構檢查不代表遊戲內實測。'])
    def publish():
        write_json(report/'session.json',result)
        checkpoint(result)
    publish()
    try:
        audit=scan(instance,report,notify,cancelled,scan_cache(home,instance))
    except Exception as exc:
        result.update(status='cancelled' if isinstance(exc,InterruptedError) else 'blocked')
        result['errors'].append(['掃描',str(exc)])
        publish()
        return result
    result['audit_counts']=dict(audit.counts)
    result['source_hashes']=audit.source_hashes
    result['errors']=audit.errors
    result['repairs']=audit.repairs
    result['rows']=[dict(r,proposed=r.get('current') or r.get('en') or r.get('zh_cn') or '',
                        origin='pending',issue='等待來源比對',supported=False,reviewed=False,changed=False)
                    for r in audit.rows if r['kind'] in ('language','book') or r['flags']]
    result['status']='references'
    publish()
    try:
        if references is None:
            refs, versions=refresh(instance,home/'cache',lambda s:notify(46,'更新參考庫',s),cancelled)
        else:
            refs,versions=references  # tests inject deterministic references; GUI never uses this
        result['references']=versions
    except Exception as exc:
        result.update(status='cancelled' if isinstance(exc,InterruptedError) else 'blocked',errors=result['errors']+[['參考庫預檢',str(exc)]])
        publish()
        return result
    result['rows']=[]
    result['status']='matching'
    cc=OpenCC('s2twp')
    instance_cn={}
    for r in audit.rows:
        if r['kind']!='language' or not isinstance(r['zh_cn'],str): continue
        m=re.search(r'assets/([^/]+)/lang/',r['source'])
        if m and (r['source'].startswith('instance!/kubejs/assets/') or r['source'].startswith('config/openloader/')):
            instance_cn.setdefault((m[1],r['key']),[]).append((r['source'],r['zh_cn']))
    # Translation resource packs installed in this modpack (often community work) come before
    # online references; zh_tw is used as-is and zh_cn is converted to Taiwan wording.
    instance_rp_tw={};instance_rp_cn={}
    for r in audit.rows:
        m=re.search(r'assets/([^/]+)/lang/',r['source'])
        if r['kind']!='language' or not m or not re.match(r'(?:instance!/)?resourcepacks/',r['source']):continue
        if isinstance(r['current'],str) and HAN.search(r['current']):
            instance_rp_tw.setdefault((m[1],r['key']),[]).append((r['source'],r['current']))
        if isinstance(r['zh_cn'],str) and HAN.search(r['zh_cn']):
            instance_rp_cn.setdefault((m[1],r['key']),[]).append((r['source'],r['zh_cn']))
    counts=collections.Counter()
    memory=TranslationMemory(home);user_terms=UserGlossary(home)
    ref_kinds=(result.get('references') or {}).get('sources') or ['tw','cn']
    vanilla=next((ref for n,ref in enumerate(refs) if n<len(ref_kinds) and ref_kinds[n]=='vanilla'),None)
    # Without any scanned mod jar there is nothing to compare against, so nothing is skipped.
    installed=getattr(audit,'installed_namespaces',None) if any(r['source'].startswith('mods/') for r in audit.rows) else None
    last_publish=time.monotonic()
    for i,r in enumerate(audit.rows):
        if i%200==0:
            if cancelled():
                result.update(status='cancelled',source_counts=dict(counts))
                publish()
                return result
            notify(50+int(42*i/max(1,len(audit.rows))),'比對中文來源',f'{i:,} / {len(audit.rows):,} 筆掃描文字')
            if time.monotonic()-last_publish>=2:
                result['source_counts']=dict(counts)
                publish();last_publish=time.monotonic()
        # Non-language candidates are retained explicitly rather than reclassifying IDs as text.
        if r['kind'] not in ('language','book'):
            if r['flags']:
                value=r['current'] or r['en'] or '';hidden=internal_reason(value)
                # Obvious identifiers, code and log lines are set aside so 待查 lists what may really be shown.
                result['rows'].append(dict(slim(r),proposed=value,origin='not_display' if hidden else 'untranslated',
                                           issue='程式內部字串：'+hidden if hidden else '需確認顯示用途與上下文',
                                           supported=False,reviewed=False,changed=False))
                counts['not_display' if hidden else 'context_candidate']+=1
            continue
        original=r['en'] if isinstance(r['en'],str) else r['zh_cn'] or r['current'] or ''
        m=re.search(r'assets/([^/]+)/lang/',r['source']); ns=m[1] if m else ''
        if installed is not None and ns and ns not in installed and TRANSLATION_PACK.match(r['source']):
            # Bundled translation packs (e.g. a whole CFPA pack via OpenLoader) cover mods this
            # modpack does not have; the game never shows those strings.
            counts['not_installed']+=1;continue
        ref=KEY_MOD_REFERENCE.match(r['key'])
        ref=ref and (ref[1] or ref[2])
        if installed is not None and ref and ref not in (ns,'minecraft') and ref not in installed:
            # e.g. Traveler's Titles names for biomes of mods that are not installed.
            counts['not_installed']+=1;continue
        # Source order: most accurate Taiwan wording first (see README 翻譯邏輯 / AGENTS.md).
        # Decisions the user made → people-written zh_tw (reference packs whose English matches this
        # version, the modpack's zh_tw packs, the mod's own zh_tw) → Mojang's official names →
        # converted zh_cn (modpack, same mod, CFPA) → unverified candidates → glossary → AI later.
        existing=r['current'] if isinstance(r['current'],str) and S2T.convert(r['current'])==r['current'] else None
        human_tw=[];converted_cn=[];stale_tw=[];cross=[]
        if ns:
            for n,ref in enumerate(refs):
                kind=ref_kinds[n] if n<len(ref_kinds) else 'reference'
                if kind=='vanilla':continue
                if kind in HUMAN_TW_KINDS:
                    value,matches=pick_reference(ref,ns,r['key'],r['en'])
                    (stale_tw if matches is False else human_tw).append(('reference_pack_or_cfpa',value,'reference:'+kind))
                elif kind.startswith('cn-'):cross.append(('cross_version_reference',ref.get(ns,{}).get(r['key']),'reference:'+kind))
                else:converted_cn.append(('reference_pack_or_cfpa',ref.get(ns,{}).get(r['key']),'reference:'+kind))
        options=[('translation_memory',memory.lookup(ns,r['key'],original),'translation_memory.json'),
                 ('user_glossary',user_terms.lookup(original),'user_glossary.json')]
        options+=human_tw
        options+=[('instance_resourcepack',v,p) for p,v in instance_rp_tw.get((ns,r['key']),[]) if p!=r['source']]
        options.append(('existing_zh_tw',existing,r['source']))
        if vanilla:
            options.append(('official_vanilla',vanilla['minecraft'].get(r['key']) if ns=='minecraft' else None,'Minecraft 官方 zh_tw'))
            options.append(('official_vanilla',vanilla['__terms__'].get(original.strip().casefold()),'Minecraft 官方 zh_tw 譯名'))
        options+=[('instance_zh_cn',v,p) for p,v in instance_cn.get((ns,r['key']),[]) if p!=r['source']]
        options+=[('instance_zh_cn',v,p) for p,v in instance_rp_cn.get((ns,r['key']),[]) if p!=r['source']]
        options.append(('same_source_zh_cn',r['zh_cn'],r['source']))
        options+=converted_cn
        options+=[('stale_reference',v,s) for _,v,s in stale_tw]
        options+=cross
        options.append(('glossary',MINECRAFT_GLOSSARY.get(original.lower()),'MINECRAFT_GLOSSARY'))
        if existing is None and isinstance(r['current'],str):
            # A zh_tw that still contains simplified characters is only a last-resort candidate.
            options.append(('existing_zh_tw',cc.convert(r['current']),r['source']+'（原含簡體，已轉繁）'))
        value=original; origin='untranslated'; evidence=''; issue='缺少可用中文來源'
        for name,candidate,source in options:
            if usable(original,candidate):
                value=cc.convert(candidate) if name in ('same_source_zh_cn','instance_zh_cn') else candidate
                if not validate_text(original,value):continue
                origin=name;evidence=source
                issue=('' if name in ('existing_zh_tw','translation_memory','user_glossary','official_vanilla','instance_resourcepack')
                       or (name=='reference_pack_or_cfpa' and source in ('reference:tw','reference:para'))
                       else '參考譯文對應的英文與目前版本不同，需核對' if name=='stale_reference'
                       else '跨版本參考：來自其他 Minecraft 版本的 CFPA，需核對版本差異' if name=='cross_version_reference'
                       else '簡中轉繁：需校對台灣用語、版本語意與名稱')
                break
        if origin=='existing_zh_tw' and existing is None:
            issue='既有繁中含簡體字，已轉為台灣繁體，請核對'
        elif origin=='existing_zh_tw' and cc.convert(value)!=value:
            issue='既有繁中用語可能與台灣用語不同，請核對'
        reason=keep_original_reason(original,r['key'],ns) if origin=='untranslated' else ''
        if reason:
            # Parameters, key names and similar strings stay as-is; they are neither gaps nor AI work.
            origin='keep_original';evidence=reason;issue=''
            if r['en'] is None and r['current'] is None:issue='無需翻譯：'+evidence  # no en_us fallback in game
        supported=r['kind']=='language' or ('/en_us/' in r['source'] or '/zh_tw/' in r['source'])
        changed=value!=r['current'] and origin!='untranslated' and (origin!='keep_original' or bool(issue))
        counts[origin]+=1
        if changed or issue or origin=='keep_original':  # keep rows stay visible under the report's 無需翻譯 filter
            result['rows'].append(dict(slim(r),proposed=value,origin=origin,evidence=evidence,issue=issue,
                                       supported=supported,reviewed=False,changed=changed))
    result.update(source_counts=dict(counts),status='needs_review',api=0,ai_translation=0)
    for name,expected in result['source_hashes'].items():
        if file_hash(contained(instance,name))!=expected:
            result['status']='blocked';result['errors'].append([name,'掃描途中原檔變動，請重新掃描。'])
            break
    publish()
    notify(100,'來源整理完成','尚未套用；請在報告中核對譯文。')
    return result


def full_translation(instance, home, model, notify, cancelled=lambda:False, checkpoint=lambda _:None, options=None):
    """Publish durable reports even when application is blocked after planning.

    options: apply_mode ('jar' rewrites mod files, 'pack' writes KubeJS assets or a translation mod)
    and set_language (switch options.txt to zh_tw, backed up like every other file).
    """
    result=plan(instance,home,notify,cancelled,checkpoint=checkpoint)
    result.update(options or {})
    if result['status'] in ('blocked','cancelled'):return result
    try:
        if model:
            from . import codex_bridge as ai
            if ai.pending_rows(result):
                result=ai.supplement(result,home,model,notify,cancelled,checkpoint=checkpoint)
            else:
                result.update(ai_status='skipped',ai_message='沒有需要 AI 補翻的語系缺漏。')
        else:
            result.update(ai_status='skipped',ai_message='未連接 AI；缺少中文來源的文字保留原文。')
        if cancelled():
            result['status']='cancelled'
        elif result.get('ai_status')=='paused':
            result['status']='needs_review'
        else:
            auto_confirm_safe(result)
            result['status']='ready_to_apply'
            write_json(Path(result['report'])/'session.json',result);checkpoint(result)
            if any(r.get('reviewed') and r.get('changed') and r.get('supported') for r in result['rows']):
                result=apply_session(result,home,notify)
            else:
                result['status']='needs_review'
    except GameRunningError as exc:
        result.update(status='awaiting_game',apply_error=str(exc))
    except Exception as exc:
        result.update(status='apply_failed',apply_error=str(exc))
    write_json(Path(result['report'])/'session.json',result)
    checkpoint(result)
    return result


def auto_confirm_safe(session):
    """Approve validated player-text candidates for the one-click workflow.

    This is deliberately not labelled ``manual``: provenance stays attached to
    every row, while the structural checks already performed by plan/AI are
    recorded as the reason the user did not need to review thousands of rows.
    """
    count = 0
    for row in session.get('rows', []):
        if (row.get('supported') and row.get('changed') and row.get('origin') != 'untranslated'
                and not row.get('installed') and validate_text(
                    row.get('en') or row.get('zh_cn') or row.get('current') or '', row.get('proposed', ''))):
            row['reviewed'] = True
            row['review_method'] = 'auto_validated_one_click'
            row['auto_review_reason'] = '來源優先順序、格式碼、佔位符、換行與數值檢查通過'
            count += 1
    session['auto_confirmed_count'] = count
    session['automatic_apply_notice'] = ('已自動套用通過格式與來源檢查的玩家文字；'
                                         'AI／參考庫來源仍保留，未宣稱人工逐筆校對。')
    write_json(Path(session['report']) / 'session.json', session)
    return session


def target_for(row):
    outer,path=row['source'].split('!/',1)
    if row['kind']=='language':
        path=re.sub(r'/(?:en_us|zh_cn|zh_tw)\.(json|lang)$',r'/zh_tw.\1',path,flags=re.I)
    else:
        path=re.sub('/en_us/','/zh_tw/',path,flags=re.I)
    if outer=='instance':return path,None
    return outer,path


class GameRunningError(RuntimeError):
    pass


def game_process_blocker(instance, processes):
    target=str(instance).replace('\\','/').rstrip('/').casefold()
    for process in processes:
        line=process.get('CommandLine') or ''
        pid=process.get('ProcessId','?')
        lower=line.replace('\\','/').casefold()
        cwd=(process.get('cwd') or '').replace('\\','/').rstrip('/').casefold()
        if cwd==target:
            return f'目標資料夾仍由 Java（PID {pid}）使用，請關閉對應程式後重試套用。'
        if process.get('server_target') and cwd and cwd!=target:continue
        if not line:
            return f'無法讀取 Java 程序 PID {pid} 的用途。請關閉相關遊戲後按「重試套用」。譯文已保存。'
        match=re.search(r'--gamedir(?:=|\s+)(?:"([^"]+)"|([^\s]+))',lower)
        if match:
            directory=(match[1] or match[2]).rstrip('/')
            if directory==target:
                return f'此模組包的 Minecraft（PID {pid}）仍在執行。關閉遊戲後按「重試套用」，不必重新翻譯。'
            if re.match(r'^(?:[a-z]:/|/)',directory):continue
        # Known dedicated servers must not block an unrelated client instance.
        if re.search(r'--launchtarget\s+\S*server\b|net\.minecraft\.server\.main|fabricserverlauncher|server\.jar\b',lower) and target not in lower:
            continue
        if target in lower or re.search(r'minecraft|modlauncher|bootstraplauncher|fabric',lower):
            return f'偵測到 Minecraft 程序（PID {pid}），但無法確認遊戲資料夾。請關閉相關遊戲後重試；譯文與報告已保留。'
    return None


def inspect_java_processes():
    import psutil
    result=[]
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').lower() not in ('java.exe','javaw.exe'):continue
        row=dict(ProcessId=process.pid,CommandLine=None,cwd=None,server_target=False)
        try:
            arguments=process.cmdline()
            row['CommandLine']=subprocess.list2cmdline(arguments)
            row['cwd']=process.cwd()
            for arg in arguments:
                # Only inspect known Forge server installer argument files, never JVM secrets.
                if not re.fullmatch(r'@libraries/net/(?:minecraftforge/forge|neoforged/neoforge)/[^/]+/(?:win|unix)_args\.txt',arg.replace('\\','/')):continue
                file=Path(row['cwd'])/arg[1:]
                if file.stat().st_size>1024*1024:continue
                text=file.read_text(encoding='utf-8-sig')
                row['server_target']=bool(re.search(r'--launchTarget\s+(?:forgeserver|neoforgeserver)\b',text))
        except psutil.NoSuchProcess:continue
        except (psutil.AccessDenied,OSError,UnicodeError):pass
        result.append(row)
    return result


def ensure_game_closed(instance):
    if os.name!='nt': return
    message=game_process_blocker(instance,inspect_java_processes())
    if message:raise GameRunningError(message)


PACK_MOD_FILE = 'mods/mctranslator_zh_tw.jar'
PACK_MOD_ID = 'mctranslator_zh_tw'


def is_nested(row):
    return row['source'].count('!/')>=2


def read_archive_entry(instance, outer, entry):
    """Read an entry of a mod jar; 'inner.jar!/path' reaches into jar-in-jar libraries."""
    with zipfile.ZipFile(contained(instance,outer)) as z:
        if '!/' not in entry:return z.read(entry) if entry in z.namelist() else None
        inner,rest=entry.split('!/',1)
        with zipfile.ZipFile(io.BytesIO(z.read(inner))) as nested:
            return nested.read(rest) if rest in nested.namelist() else None


def pack_target(instance):
    """Where pack mode writes: KubeJS assets (loaded above mod resources) or a small resource mod."""
    kubejs=any(p.name.lower().startswith('kubejs') for p in (instance/'mods').glob('*.jar')) and (instance/'kubejs').is_dir()
    return 'kubejs' if kubejs else 'mod'


def pack_mod_metadata(mod_ids):
    """Resource-only mod metadata for NeoForge, Forge and Fabric; loads after every translated mod."""
    after=''.join(f'\n[[dependencies.{PACK_MOD_ID}]]\nmodId="{m}"\ntype="optional"\nmandatory=false\nversionRange="*"\nordering="AFTER"\nside="CLIENT"\n'
                  for m in sorted(mod_ids))
    toml=(f'modLoader="lowcodefml"\nloaderVersion="[1,)"\nlicense="All rights reserved"\n\n[[mods]]\nmodId="{PACK_MOD_ID}"\n'
          f'version="1.0.0"\ndisplayName="MC Translator 繁體中文翻譯"\ndescription="由 MC Translator 產生的繁體中文翻譯包，不含程式碼。"\n'+after)
    fabric=json.dumps(dict(schemaVersion=1,id=PACK_MOD_ID,version='1.0.0',name='MC Translator 繁體中文翻譯',
                           environment='client',suggests={m:'*' for m in sorted(mod_ids)}),ensure_ascii=False,indent=2)
    return {'META-INF/neoforge.mods.toml':toml,'META-INF/mods.toml':toml,'fabric.mod.json':fabric,
            'pack.mcmeta':json.dumps(dict(pack=dict(pack_format=34,description='MC Translator 繁體中文翻譯')),ensure_ascii=False)}


def jar_mod_ids(instance, outer):
    try:
        with zipfile.ZipFile(contained(instance,outer)) as z:
            for name in ('META-INF/neoforge.mods.toml','META-INF/mods.toml'):
                if name in z.namelist():
                    return set(re.findall(r'(?m)^\s*modId\s*=\s*"([^"]+)"',z.read(name).decode('utf-8','replace')))
            if 'fabric.mod.json' in z.namelist():return {json.loads(z.read('fabric.mod.json').decode('utf-8-sig'))['id']}
    except (OSError,ValueError,KeyError,zipfile.BadZipFile):pass
    return set()


def build_pack(instance, staged, pack_rows, session, notify):
    """Stage translations as KubeJS assets or a resource-only mod instead of rewriting mod jars.

    Each file carries the mod's own zh_tw, any earlier pack content and this batch, so it is
    complete whichever way the loader orders same-named resources.
    """
    target=pack_target(instance);resources=collections.defaultdict(list);mod_ids=set()
    for outer,entry,row in pack_rows:
        resources[entry.split('!/')[-1]].append((outer,entry,row));mod_ids|=jar_mod_ids(instance,outer)
    existing={}
    if target=='mod' and (instance/PACK_MOD_FILE).exists():
        with zipfile.ZipFile(instance/PACK_MOD_FILE) as z:
            existing={n:z.read(n) for n in z.namelist() if n.startswith('assets/')}
            meta=z.read('META-INF/neoforge.mods.toml').decode('utf-8') if 'META-INF/neoforge.mods.toml' in z.namelist() else ''
            mod_ids|=set(re.findall(r'(?m)^modId="([^"]+)"',meta))-{PACK_MOD_ID}
    repaired={n for _,n,*_ in session.get('repairs',[])}
    built={}
    for i,(resource,items) in enumerate(sorted(resources.items())):
        if i%50==0:notify(int(40*i/max(1,len(resources))),'整理翻譯包',resource)
        outer,entry,first=items[0];rows=[row for *_,row in items]
        previous=(contained(instance,'kubejs/'+resource).read_bytes() if target=='kubejs' and (instance/'kubejs'/resource).exists()
                  else existing.get(resource))
        if first['kind']=='book' and first['key']=='text':
            built[resource]=first['proposed'].encode('utf-8');continue
        own=read_archive_entry(instance,outer,entry)
        try:data=parse(own) if own and resource.endswith('.json') else dict(l.split('=',1) for l in own.decode('utf-8-sig').splitlines() if '=' in l and not l.startswith('#')) if own else {}
        except ValueError:
            if entry.split('!/')[-1] not in repaired:raise
            data={}
        if first['kind']=='book' and not own:
            data=parse(read_archive_entry(instance,outer,first['source'].split('!/',1)[1]))  # English structure
        if previous:
            before=parse(previous) if resource.endswith('.json') else dict(l.split('=',1) for l in previous.decode('utf-8-sig').splitlines() if '=' in l)
            data=before if first['kind']=='book' else {**data,**before}
        for r in rows:
            if r['kind']=='language':data[r['key']]=r['proposed'];continue
            keys=json.loads(r['key']);node=data
            for key in keys[:-1]:node=node[key]
            node[keys[-1]]=r['proposed']
        built[resource]=(json.dumps(data,ensure_ascii=False,indent=2) if resource.endswith('.json')
                         else '\n'.join(f'{k}={v}' for k,v in data.items())+'\n').encode('utf-8')
    records=[]
    if target=='kubejs':
        for resource,content in built.items():
            path='kubejs/'+resource;dst=contained(staged,path);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(content)
            src=instance/path
            records.append(dict(file=path,before=file_hash(src) if src.exists() else None,after=file_hash(dst),reviewed=True,verified=True))
    else:
        dst=contained(staged,PACK_MOD_FILE);dst.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
            for name,text in pack_mod_metadata(mod_ids).items():w.writestr(name,text)
            for name,content in {**existing,**built}.items():w.writestr(name,content)
        src=instance/PACK_MOD_FILE
        records.append(dict(file=PACK_MOD_FILE,before=file_hash(src) if src.exists() else None,after=file_hash(dst),reviewed=True,verified=True))
    session['pack_target']=target
    return records


def rewrite_archive(z, dst, modified, label):
    """Copy archive z to dst with `modified` entries replaced/added; everything else byte-identical.

    Jar signatures are dropped (they would be invalid) and the result is verified entry by entry.
    """
    if len(z.namelist())!=len(set(z.namelist())):raise ValueError('原始壓縮檔有重複項目，需先修復：'+label)
    with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
        for info in z.infolist():
            if info.filename not in modified and not is_jar_signature_file(info.filename):
                # writestr() rewrites the ZipInfo's offsets; passing the source archive's own
                # object would make later reads from that archive land in the wrong place.
                w.writestr(copy.copy(info),z.read(info.filename))
        for n,b in modified.items():w.writestr(n,b)
    with zipfile.ZipFile(dst) as check:
        if check.testzip():raise ValueError('ZIP 完整性驗證失敗：'+label)
        for n in z.namelist():
            if n not in modified and not is_jar_signature_file(n) and check.read(n)!=z.read(n):
                raise ValueError('非翻譯內容被改動：'+n)


def set_language_record(instance, staged):
    """Stage options.txt with lang:zh_tw so the game opens in Traditional Chinese after applying."""
    src=instance/'options.txt';text=src.read_text(encoding='utf-8') if src.exists() else ''
    if re.search(r'(?m)^lang:zh_tw\s*$',text):return None
    text=re.sub(r'(?m)^lang:.*$','lang:zh_tw',text) if re.search(r'(?m)^lang:',text) else text+('' if not text or text.endswith('\n') else '\n')+'lang:zh_tw\n'
    dst=staged/'options.txt';dst.write_text(text,encoding='utf-8')
    return dict(file='options.txt',before=file_hash(src) if src.exists() else None,after=file_hash(dst),reviewed=True,verified=True)


def apply_session(session, home, notify):
    instance=Path(session['instance']); report=Path(session['report'])
    pack=session.get('apply_mode')=='pack'
    # Rewriting an embedded (jar-in-jar) library is too risky, so its text goes to KubeJS assets when
    # KubeJS is installed and is otherwise skipped and reported; ordinary text is written into the mods.
    nested_to_kubejs=not pack and pack_target(instance)=='kubejs'
    selected=[r for r in session['rows'] if r.get('reviewed') and r.get('supported') and r.get('changed')
              and (pack or nested_to_kubejs or not is_nested(r))]
    skipped_nested=0 if pack or nested_to_kubejs else sum(1 for r in session['rows'] if r.get('reviewed') and r.get('changed') and is_nested(r))
    if not selected:raise ValueError('尚未有確認可套用的譯文。請先在報告選擇文字並按「確認這筆」。')
    if session.get('status')=='blocked':raise ValueError('此批次預檢未通過，不能套用。')
    if session.get('status')=='installed':raise ValueError('這一批已套用，請重新掃描後建立下一批。')
    ensure_game_closed(instance)
    for name,expected in session.get('source_hashes',{}).items():
        if file_hash(contained(instance,name))!=expected:raise ValueError('來源在掃描後有變更，請重新掃描：'+name)
    changes=collections.defaultdict(list);pack_rows=[]
    for row in selected:
        original=row.get('en') or row.get('zh_cn') or row.get('current') or ''
        if not validate_text(original,row['proposed']):raise ValueError('譯文格式或參數不一致：'+row['key'])
        path,entry=target_for(row); contained(instance,path)
        if entry is not None and path.startswith('mods/') and (pack or is_nested(row)):pack_rows.append((path,entry,row));continue
        changes[path].append((entry,row))
    staged=report/'staged'
    if staged.exists():
        staged=report/('staged-'+uuid.uuid4().hex[:8])
    staged.mkdir()
    records=build_pack(instance,staged,pack_rows,session,notify) if pack_rows else []
    for i,(path,edits) in enumerate(changes.items()):
        notify(int(70*i/len(changes)),'驗證並準備套用',path)
        src=contained(instance,path); dst=contained(staged,path)
        before=file_hash(src)
        by_entry=collections.defaultdict(list)
        for entry,row in edits:by_entry[entry].append(row)
        z=zipfile.ZipFile(src) if any(entry is not None for entry in by_entry) else None
        try:
            modified={}
            for entry,rows in by_entry.items():
                raw=z.read(entry) if z and entry in z.namelist() else src.read_bytes() if not z and src.exists() else None
                name=entry or path
                is_text=rows[0]['kind']=='book' and rows[0]['key']=='text'
                if is_text:
                    content=rows[0]['proposed'].encode('utf-8')
                else:
                    try:
                        data=parse(raw) if raw and name.endswith('.json') else dict(line.split('=',1) for line in raw.decode('utf-8-sig').splitlines() if '=' in line and not line.startswith('#')) if raw else {}
                    except ValueError:
                        # Only zh_tw files the scan already recorded as unreadable may be rebuilt.
                        if not any(l==path and n==name or entry is None and path.endswith(n) for l,n,*_ in session.get('repairs',[])):raise
                        data={}
                    # Missing book target needs the English structure, never an empty object.
                    if not raw and rows[0]['kind']=='book':
                        sourcepath=rows[0]['source'].split('!/',1)[1]
                        data=parse(z.read(sourcepath) if z else contained(instance,sourcepath).read_bytes())
                    for r in rows:
                        if r['kind']=='language':
                            if data.get(r['key'])!=r['current']:
                                raise ValueError('原檔已變動，請重新掃描：'+path+' / '+r['key'])
                            data[r['key']]=r['proposed']
                        else:
                            keys=json.loads(r['key']);node=data
                            for key in keys[:-1]:node=node[key]
                            if raw and node[keys[-1]]!=r['current']:raise ValueError('書本已變動，請重新掃描。')
                            node[keys[-1]]=r['proposed']
                    content=(json.dumps(data,ensure_ascii=False,indent=2) if name.endswith('.json') else '\n'.join(f'{k}={v}' for k,v in data.items())+'\n').encode('utf-8')
                modified[entry]=content
            dst.parent.mkdir(parents=True,exist_ok=True)
            if z:rewrite_archive(z,dst,modified,path)
            else:dst.write_bytes(modified[None])
        finally:
            if z:z.close()
        records.append(dict(file=path,before=before,after=file_hash(dst),reviewed=True,verified=True))
    if session.get('set_language'):
        record=set_language_record(instance,staged)
        if record:records.append(record)
    jars=[staged/r['file'] for r in records if r['file'].endswith('.jar')]
    if jars:
        vr=VerifyResult();check_java_zipfs(jars,vr)
        if not vr.ok:raise ValueError('Java 驗證未通過：'+'; '.join(vr.errors))
    notify(80,'備份與套用','先保存所有原檔，再寫入已校對文字')
    ensure_game_closed(instance)
    backup=apply_reviewed(instance,staged,records,home/'output')
    for row in selected:row['installed']=True
    session.update(status='installed',backup=str(backup),installed_count=len(selected),nested_skipped=skipped_nested,
                   nested_packed=0 if pack else sum(1 for r in selected if is_nested(r)),
                   language_set=bool(session.get('set_language')))  # options.txt changed now or already zh_tw
    write_json(report/'session.json',session)
    notify(92,'重新掃描實際遊戲資料','檢查套用後的語系與待查項目')
    try:
        after=scan(instance,report/'after',lambda *_:None,lambda:False,scan_cache(home,instance))
        session['after_counts']=dict(after.counts)
    except Exception as exc:
        session['errors'].append(['套用後稽核',str(exc)])
    write_json(report/'session.json',session)
    notify(100,'已套用已校對的文字',f'{len(selected):,} 筆；其他待查內容仍保留在報告')
    return session


def restore_backup(backup: Path, expected_instance: Path):
    backup=backup.resolve()
    journal=backup/'_備份紀錄/manifest.json'
    record=json.loads(journal.read_text(encoding='utf-8'))
    instance=Path(record['instance']).resolve()
    if instance!=expected_instance.resolve():raise ValueError('備份不屬於目前選擇的模組包。')
    if record['status']!='installed':raise ValueError('這份備份不是可還原的已套用批次。')
    ensure_game_closed(instance)
    seen=set()
    for row in record['files']:
        path=contained(instance,row['file']);source=contained(backup,row['file'])
        if str(path).casefold() in seen:raise ValueError('備份清冊包含重複路徑。')
        seen.add(str(path).casefold())
        if file_hash(path)!=row['after']:raise ValueError('檔案後來有修改，已停止還原以免覆蓋：'+row['file'])
        if row['before'] is not None and file_hash(source)!=row['before']:raise ValueError('備份內容不符：'+row['file'])
    # Persist each restored item so an interrupted restore is diagnosable.
    record.update(status='restoring',restored_files=[])
    write_json(journal,record)
    for row in record['files']:
        path=contained(instance,row['file'])
        if file_hash(path)!=row['after']:raise ValueError('還原途中檔案被修改：'+row['file'])
        if row['before'] is None:path.unlink()
        else:atomic_copy(contained(backup,row['file']),path)
        if file_hash(path)!=row['before']:raise ValueError('還原後雜湊不符：'+row['file'])
        record['restored_files'].append(row['file']);write_json(journal,record)
    record['status']='restored';write_json(journal,record)
    return dict(record,backup_path=str(backup))
