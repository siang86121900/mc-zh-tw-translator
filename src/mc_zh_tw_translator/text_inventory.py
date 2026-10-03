"""Read-only, position-level coverage checks, independent of the scan's format routing.

Candidates are evidence of a gap, not permission to translate. Shared syntax decoders are
used for JSON/NBT, but no reader's list of supported formats determines what is inspected.
Classes, generated/saved world text and pictures require separate checks.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import io
import json
import re
import struct
import time
import zipfile
import zlib
from pathlib import Path, PurePosixPath

FORMAT = 'text-inventory-2'
RULES_VERSION = '2026-10-03.8'
HAN = re.compile('[㐀-鿿]')
WORDS = re.compile(r'[A-Za-z]{2,}')
LOCALE = re.compile(r'(?:^|/)(?!en_us|zh_tw|zh_cn)[a-z]{2}[_-](?:[a-z]{2}|\d{3})(?:/|[.\[])', re.I)
LANG = re.compile(r'/lang/(en_us|zh_cn|zh_tw)\.(json|lang|snbt)$', re.I)
DISPLAY = {'name', 'text', 'title', 'subtitle', 'description', 'landing_text', 'header',
           'customTooltips', 'displayName', 'tooltip', 'label', 'hoverlabel', 'message',
           'lore', 'Lore', 'CustomName', 'pages', 'objective', 'display_name', 'alias', 'fallback',
           'Category','Text1','Text2','Text3','Text4','messages','filtered_messages',
           'minecraft:custom_name','minecraft:item_name','minecraft:lore'}
MACHINE = {'models', 'geo', 'geo_models', 'bedrock', 'animations', 'animation_controllers', 'textures', 'sounds',
           'font', 'fonts', 'blockstates', 'particles', 'shaders', 'render_controllers', 'recipes',
           'recipe', 'tags', 'worldgen', 'loot_modifiers', 'optifine', 'showdown'}
SKIP_TOP = {'saves', 'logs', 'crash-reports', 'screenshots', 'backups', 'cache', '.mixin.out',
            'natives', 'libraries', 'versions', 'downloads', 'local', 'modernfix',
            'lightspeed-cache', '.cache', '.fabric', 'simplebackups', 'xaero', 'journeymap',
            'schematics', 'debug', 'dynamic-resource-pack-cache', 'licenses', 'output',
            'MCTranslatorData', '.git', 'showdown'}
SUFFIXES = {'.json', '.json5', '.jsonc', '.snbt', '.toml', '.txt', '.lang', '.cfg', '.yaml',
            '.yml', '.properties', '.js', '.zs', '.mcfunction', '.md', '.nbt', '.data', '.cache'}
NOT_PLAYER = re.compile(r'(?i)(?:^|/)(?:META-INF/|license|licence|notice|readme|changelog|credits?|authors?|'
                        r'quests-backup/|com/ibm/icu/|org/apache/commons/codec/)|'
                        # Libraries' own messages (Pixelmon bundles commons-math, Essential bundles BouncyCastle), species
                        # definitions whose names are ids shown through language keys (Cobblemon, Pixelmon), and the
                        # copy of Essential its loader downloads (own font without Chinese: kept English, AGENTS).
                        r'(?:^|/)org/(?:bouncycastle|apache)/|(?:^|/)data/[^/]+/species(?:_additions)?/|^essential/|'
                        # Copies the game never reads (Chapter of Yuusha's DLC/tmp, saved worlds), CraftTweaker's own
                        # example scripts and library, Collective's rebuilt-on-start translations, a pinyin table,
                        # coremod scripts, change logs, mixin settings, animation and model files.
                        r'(?:^|/)(?:saves|tmp)/|/data/crafttweaker/scripts/|StdLibs\.jar!/|^data/serilum/|pinyin|'
                        r'!/coremods/|changelog|update_log|mixin[^/]*\.properties$|/(?:attack_animations|player_animation)/|'
                        # Touhou Little Maid's download cache (the loaded copy is tlm_custom_pack/), loaders' and script
                        # engines' own messages, scripts inside mod files (coremods, transformers), a pinyin table.
                        r'^config/touhou_little_maid/file/|/net/fabricmc/loader/Messages|/rhino/resources/|'
                        r'hotswap-agent|\.jar!/(?:[^!]*/)?[^/!]*\.js$|/pinin/|'
                        # Pixelmon's battle AI test puzzles, disclaimers, a layout's notes, Essential's pinned versions.
                        r'/ai_benchmark/|disclaimer|(?:^|/)_?notes\.json$|/pinned/|'
                        # Simplified copies in a Paxi pack (VEFV2.7.1 VEFC汉化包): shown only when the game is in zh_cn,
                        # read by the scan as references for the mods' own English (desktop_jobs.PAXI_PACKS).
                        r'^config/(?:paxi/resourcepacks|openloader/resources)/[^!]*!/.*(?:/_?zh_cn/|/zh_cn\.)|'
                        # The modpack's own update installer (Chapter of Yuusha DLC/update), never loaded by the game.
                        r'^DLC/|'
                        # A book's copy in a language with a code of its own (Alex's Caves books/tok/: Toki Pona).
                        r'/books?/tok/|'
                        r'(?:^|/)[^/]*(?:licens[ei]|credits|terms&conditions|mixin-config)[^/]*\.(?:txt|md)$|'
                        r'(?:^|/)(?:CONTRIBUTORS|CONTRIBUTING|ATTRIBUTION|patrons)\.(?:md|txt)$')
MAX_TEXT = 8 << 20
MAX_ARCHIVE = 1200 << 20
MAX_NESTED = 300 << 20
MAX_EXPANDED = 512 << 20


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def source_name(source):
    return source.removeprefix('instance!/').replace('\\', '/')


def locale_source(source):
    return re.sub(r'(?i)(/)(?:en_us|zh_cn|zh_tw)(?=[/.])', r'\1@locale', source_name(source))


def readable(text):
    if not isinstance(text, str) or not text.strip(): return False
    if re.fullmatch(r'[a-z0-9_.-]+:[a-z0-9_./-]+(?:\|(?:true|false))?',text.strip()):return False
    if text.startswith('file/'):return False
    # IDs, filenames, URLs, paths, expressions and format-only fragments are not prose.
    if re.fullmatch(r'\S+(?:\.zip|\.nbt|\.png|\.json|\.jar|\.ogg)', text, re.I): return False
    if re.match(r'^(?:https?://|\[source:|\$\{|query\.|variable\.)', text): return False
    if not HAN.search(text) and re.fullmatch(r'[\w./:@#%+\-]+', text) and re.search(r'[._/:@#%]', text): return False
    return bool(HAN.search(text) or WORDS.search(text) or re.fullmatch(r'[A-Za-z]',text.strip()))


def leaves(value, path=(), field=''):
    if isinstance(value, dict):
        for key, child in value.items(): yield from leaves(child, path + (key,), key)
    elif isinstance(value, list):
        for i, child in enumerate(value): yield from leaves(child, path + (i,), field)
    elif isinstance(value, str): yield path, field, value


FALLBACK = re.compile(r'"translate"\s*:\s*"(?P<k1>(?:\\.|[^"\\])*)"\s*,\s*"fallback"\s*:\s*"(?P<f1>(?:\\.|[^"\\])*)"'
                      r'|"fallback"\s*:\s*"(?P<f2>(?:\\.|[^"\\])*)"\s*,\s*"translate"\s*:\s*"(?P<k2>(?:\\.|[^"\\])*)"')


def machine_value(path, field, text):
    """Ids and names the game matches, never shows (Pixelmon 2026-10-03): a loot entry's item ("name": "crossbow"),
    an advancement's trigger conditions, a score target's name, a macro variable ("$speed")."""
    if field=='name' and len(path)>=3 and path[-3] in ('entries','children','pools'):return True
    if 'criteria' in path or ('target' in path and field=='name'):return True
    # A model's bones (majrusz's cerberus_model: "body"), a particle's id, a language key in braces
    # ({chair_pack.geckolib.desc}, Touhou Little Maid packs) and item NBT written as a string.
    if 'bones' in path or ('particle' in path and field=='name'):return True
    return machine_text(text)


def machine_text(text):
    """Values that are ids or code whatever field holds them: a language key in braces ({chair_pack.geckolib.desc},
    Touhou Little Maid packs), item NBT ({Potion:"ars_nouveau:mana_regen_potion"}), an item spec ("16x
    twilightforest:aurora_block", minecraft\\:purple_dye), a settings section ("[wallet_slot]"), a macro variable."""
    text = text or ''
    if re.fullmatch(r'\{[\w.]+\}',text) or re.search(r'\w+:\s*"[\w.\-]+:[\w./\-]+"',text):return True
    if re.fullmatch(r'(?:\d+x\s+)?[\w.\-]+\\?:[\w./\-]+',text) or re.fullmatch(r'\[[\w.\-]+\]',text):return True
    if re.fullmatch(r'\{image:[^}]*\}',text):return True  # an FTB Quests picture line
    # Commands a quest or script runs (Chapter of Yuusha: "/curios add hands @s", "summon cataclysm:… ~ ~10 ~",
    # "pmmo admin @p add magic xp 115000") and escaped components that are language keys only.
    if re.match(r'/[a-z_]+(?:\s|$)',text):return True
    if re.match(r'[a-z_]+ ',text) and re.search(r'@[parse]\b|(?:^|\s)~',text):return True
    if re.match(r'(?:summon|fill|setblock|give|kill|execute|effect|tp|particle|playsound|function|scoreboard|clear|'
                r'enchant|gamerule|weather|loot|item|attribute|spreadplayers|place) (?:[@~^]|[a-z0-9_.\-]+:)',text):return True
    if re.search(r'\\"(?:translate|ids)\\"',text) and not re.search(r'\\"text\\"',text):return True
    return bool(re.fullmatch(r'\$[\w.]+',text))


def inspect_file(source, raw):
    """Yield a stable position and complete value, including single-word display fields."""
    from full_translation_audit import decode, parse, parse_binary_nbt, string_literals
    from . import quest_lang
    suffix = PurePosixPath(source).suffix.lower()
    language = LANG.search('/' + source)
    if suffix in ('.nbt', '.data', '.cache'):
        data = parse_binary_nbt(raw)
    elif language and suffix == '.snbt':
        data = quest_lang.flatten(quest_lang.parse(decode(raw)))
    elif suffix in ('.json', '.jsonc', '.json5'):
        if not raw.strip(b' \t\r\n\xef\xbb\xbf'):return  # an empty settings file (cobblenav) has no text to check
        try:data = parse(raw)
        except ValueError:
            # JSON5 (unquoted keys, comments: lenientdeath.json5, yacl.json5) is checked string by string below.
            if suffix != '.json5':raise
            data = None
    elif language and suffix == '.lang':
        data = {}
        for line in decode(raw).splitlines():
            if '=' in line and not line.lstrip().startswith(('#', '!')):
                k, v = line.split('=', 1); data[k.strip()] = v.strip()
    else:
        data = None
    if data is not None:
        positions=collections.defaultdict(collections.deque)
        if not language and suffix in ('.json','.jsonc','.json5'):
            for line,index,text,is_key,_,_ in string_literals(decode(raw),'.json',source):
                if not is_key:positions[text].append(f'{line}:{index}')
        for path, field, text in leaves(data):
            literal_key=positions[text].popleft() if positions.get(text) else None
            if suffix=='.nbt':
                if field not in (DISPLAY-{'name','alias','displayName','display_name','objective','header'})|{'raw','Name'}:continue
                if field=='Name' and 'display' not in path:continue
                if field=='raw' and not ('pages' in path or 'title' in path):continue
            if language:
                if len(path)>1 and field not in ('text','fallback'):continue
                key = str(path[0]); mode = 'language'
            elif machine_value(path, field, text):continue
            else:
                # Locale objects are one unit in the scan; foreign-language branches stay untouched.
                if field in ('en_us', 'zh_cn', 'zh_tw', 'en', 'zh'):
                    key = json.dumps(path[:-1]); mode = 'path'
                elif (field in DISPLAY or str(field).endswith('Label')
                      or (len(path)>1 and str(path[-2]).endswith('Labels'))
                      or (path and path[-1] == 'translate' and readable(text))):
                    key = json.dumps(path); mode = 'path'
                else: continue
            if suffix in ('.nbt','.data','.cache'):
                try:
                    component=json.loads(text)
                    if isinstance(component,str):text=component
                    elif isinstance(component,(dict,list)):
                        words=[v for _,f,v in leaves(component) if f=='text' and v.strip()]
                        if not words:continue  # translatable components/formatting are not literal words
                        # Pixelmon gym and village chests: lore "village_taiga_house", "fridge" marks the loot table
                        # the structure fills them from; a word in lower case alone is a marker, not a description.
                        if field=='minecraft:lore' and all(re.fullmatch(r'[a-z][a-z0-9_]*',w) for w in words):continue
                        text=words[0] if len(words)==1 else json.dumps(component,ensure_ascii=True,sort_keys=True)
                except ValueError:pass
            if readable(text):
                value=dict(key=key,text=text,mode=mode,literal_key=literal_key)
                if field=='fallback':
                    parent=data
                    for part in path[:-1]:parent=parent[part]
                    if isinstance(parent,dict) and isinstance(parent.get('translate'),str):
                        value['translation_key']=parent['translate']
                elif field=='translate':value['translation_key']=text
                yield value
        return
    text = decode(raw)
    fancy = 'config/fancymenu/customization/' in source
    if fancy:
        # Independent field enumeration; an unknown direct-text format is reported, never written.
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r'\s*(label|hoverlabel|description|source)\s*=\s*(.*?)\s*$', line)
            if m and readable(m[2]): yield dict(key=str(i), text=m[2], mode='line')
        return
    short_names=bool(re.search(r'(?i)(?:^|/)[^/]*names?\.(?:cfg|txt|properties)$',source))
    # A function's {"translate": key, "fallback": "…"}: the fallback is shown only while no language file has the
    # key, and Audit.data_keys makes that key a row (Incendium 5.4.4 ships no language file).
    fallbacks={}
    if suffix=='.mcfunction':
        for n,content in enumerate(text.splitlines(),1):
            for m in FALLBACK.finditer(content):
                key,shown=(m['k1'],m['f1']) if m['k1'] is not None else (m['k2'],m['f2'])
                try:fallbacks[(n,json.loads('"'+shown+'"'))]=json.loads('"'+key+'"')
                except ValueError:pass
    # A book page is prose: an apostrophe ("the watcher's perspective") is not a quote, so its lines are compared whole.
    book_page = suffix == '.txt' and re.search(r'/books?/|/codex/|/bestiary/', source)
    for line, index, value, is_key, _, _ in ([] if book_page else string_literals(text, suffix, source)):
        if re.fullmatch(r'[0-9A-Fa-f]{16}',value) or machine_text(value):continue  # quest ids (469FC2D5B99CD7A1), item ids
        if not is_key and readable(value) and (HAN.search(value) or len(WORDS.findall(value))>=2 or short_names):
            found=dict(key=f'{line}:{index}', text=value, mode='literal')
            if (line,value) in fallbacks:found.update(translation_key=fallbacks[(line,value)],is_fallback=True)
            yield found
    if suffix in ('.txt', '.md'):
        for i, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if line and not line.startswith(('#', '//')) and readable(line):
                # Unquoted prose, including short book titles; quoted values were enumerated above.
                if book_page or (not re.search(r'[=:"\'{}]', line) and (HAN.search(line) or len(WORDS.findall(line))>=2
                        or short_names)):
                    yield dict(key=f'{i}:0', text=line, mode='literal')


def eligible(source):
    if NOT_PLAYER.search(source) or LOCALE.search('/' + source): return False
    if source.endswith(('MCTranslator-zh_tw.zip', 'zz-MCTranslator-zh_tw.zip')): return False
    if source.startswith('kubejs/server_scripts/showdown/'): return False
    if '/showdown.zip!/' in source or source.endswith('/showdown.zip'):return False
    if '/showdown/' in source:return False
    if source.startswith('shaderpacks/') and '/shaders/lang/' not in source:return False
    if source.split('/',1)[0].startswith('.') or '/.connector/' in source:return False
    if re.fullmatch(r'options\w*\.txt',source,re.I):return False
    if source in ('usercache.json','minecraftinstance.json','manifest.json','modrinth.index.json',
                  'defaultoptions.journal.json','instance.cfg','mmc-pack.json'):return False
    if PurePosixPath(source).suffix.lower() not in SUFFIXES: return False
    parts = source.split('!/')[-1].split('/')
    if parts[-1] in ('fabric.mod.json','quilt.mod.json') or parts[-1].endswith(('.refmap.json','-refmap.json','.schema.json')):return False
    if parts[0]=='schemas':return False
    if '/relocations/' in source:return False  # shaded parser diagnostics, not Minecraft display calls
    for i, part in enumerate(parts[:-2]):
        if part in ('assets', 'data') and parts[i + 2] in MACHINE:
            # Shader language tables are an explicit exception to shader program files.
            if '/shaders/lang/' not in source: return False
    return True


def collect(root, cancelled=lambda: False, notify=lambda *_: None, cache=None, source_hashes=None):
    """Enumerate candidates and all failures/limits. Never extract archives to disk."""
    root = Path(root).resolve(); candidates = []; errors = []; checked = 0;last_notice=0.0;cache_hits=0
    cache=Path(cache) if cache else None
    if cache:cache.mkdir(parents=True,exist_ok=True)

    def problem(source, reason, exc=None):
        errors.append(dict(source=source, reason=reason,
                           detail=(type(exc).__name__ + ': ' + str(exc)[:160]) if exc else ''))

    def inspect(source, raw):
        nonlocal checked
        checked += 1
        if cancelled(): raise InterruptedError('已停止文字涵蓋檢查，遊戲檔案沒有修改。')
        try:
            seen=set()
            source_hash=hashlib.sha256(raw).hexdigest()
            for value in inspect_file(source, raw):
                identity=(value['key'],value['text'],value['mode'])
                if identity in seen:continue
                seen.add(identity)
                value.update(source=source)
                value['source_sha256']=source_hash
                value['fingerprint'] = digest([source, value['key'], value['text'], value['mode'],source_hash])
                candidates.append(value)
        except (ValueError, UnicodeError, OSError, IndexError, KeyError, RecursionError,zlib.error,struct.error,EOFError) as exc:
            problem(source, '文字內容無法解析，這個檔案的涵蓋範圍尚未確認', exc)

    def archive(z, label, depth):
        expanded = 0
        for info in sorted(z.infolist(), key=lambda x: x.filename):
            if cancelled(): raise InterruptedError('已停止文字涵蓋檢查，遊戲檔案沒有修改。')
            name = info.filename; source = label + '!/' + name
            if info.is_dir(): continue
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                problem(source, '壓縮檔內路徑不正常，沒有讀取'); continue
            nested = name.lower().endswith(('.jar', '.zip'))
            if name.endswith('/showdown.zip'):continue
            if not nested and not eligible(source): continue
            if name.endswith(('MCTranslator-zh_tw.zip', 'zz-MCTranslator-zh_tw.zip')): continue
            limit = MAX_NESTED if nested else MAX_TEXT
            if info.file_size > limit or (nested and depth >= 2):
                problem(source, '檔案大小或內嵌層數超過盤點範圍，沒有讀取'); continue
            expanded += info.file_size
            if expanded > MAX_EXPANDED:
                problem(label, '壓縮檔待讀內容超過盤點上限，其餘內容未檢查'); break
            try:
                raw = z.read(info)
                if nested:
                    with zipfile.ZipFile(io.BytesIO(raw)) as inner: archive(inner, source, depth + 1)
                else: inspect(source, raw)
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError, EOFError, zlib.error) as exc:
                problem(source, '壓縮檔內容讀取失敗，這部分尚未檢查', exc)

    # Prune saved worlds/logs before traversal, and never follow symlinks outside the instance.
    import os
    def walk_error(exc): problem(str(getattr(exc, 'filename', '') or root), '資料夾讀取失敗，這部分尚未檢查', exc)
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not d.lower().startswith('xaerowaypoints_backup')
                         and not (base / d).is_symlink()
                         and not (base == root and d in SKIP_TOP) and d != 'quests-backup')
        for filename in sorted(files):
            p = base / filename; source = p.relative_to(root).as_posix()
            if p.is_symlink():
                if eligible(source): problem(source, '連結檔案未納入盤點，避免讀取模組包以外的內容')
                continue
            if not eligible(source) and p.suffix.lower() not in ('.jar', '.zip'): continue
            if filename in ('MCTranslator-zh_tw.zip', 'zz-MCTranslator-zh_tw.zip'): continue
            if cancelled(): raise InterruptedError('已停止文字涵蓋檢查，遊戲檔案沒有修改。')
            if time.monotonic()-last_notice>=0.1:
                notify(source);last_notice=time.monotonic()
            try:
                size = p.stat().st_size; nested = p.suffix.lower() in ('.jar', '.zip')
                if size > (MAX_ARCHIVE if nested else MAX_TEXT):
                    problem(source, '檔案大小超過盤點範圍，沒有讀取'); continue
                cached=None;fingerprint=None
                if cache:
                    cached=cache/(digest(source)+'.json.gz')
                    sha=(source_hashes or {}).get(source)
                    if not sha:
                        from .deployment import file_hash
                        sha=file_hash(p)
                    fingerprint=digest([source,sha,RULES_VERSION,MAX_TEXT,MAX_ARCHIVE,MAX_NESTED,MAX_EXPANDED])
                    try:
                        with gzip.open(cached,'rt',encoding='utf-8') as f:old=json.load(f)
                        if (isinstance(old,dict) and old.get('fingerprint')==fingerprint
                                and isinstance(old.get('checked_files'),int) and old['checked_files']>=0
                                and isinstance(old.get('candidates'),list)
                                and all(isinstance(c,dict) and all(isinstance(c.get(k),str)
                                    for k in ('source','key','text','mode','fingerprint','source_sha256'))
                                    for c in old['candidates'])):
                            candidates.extend(old['candidates']);checked+=old['checked_files'];cache_hits+=1;continue
                    except (OSError,ValueError,KeyError,EOFError):pass
                first=len(candidates);first_error=len(errors);first_checked=checked
                if nested:
                    with zipfile.ZipFile(p) as z: archive(z, source, 0)
                else: inspect(source, p.read_bytes())
                if cached and len(errors)==first_error:
                    # Never cache read failures. A later retry must get another chance to read them.
                    temp=cached.with_suffix('.tmp')
                    try:
                        with gzip.open(temp,'wt',encoding='utf-8') as f:
                            json.dump(dict(fingerprint=fingerprint,candidates=candidates[first:],
                                           checked_files=checked-first_checked),f,ensure_ascii=True)
                        temp.replace(cached)
                    except OSError:pass  # cache persistence is optional, not scan evidence
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError, EOFError, zlib.error) as exc:
                problem(source, '檔案讀取失敗，這部分尚未檢查', exc)
    return dict(format=FORMAT, rules_version=RULES_VERSION, checked_files=checked, cache_hits=cache_hits,
                candidates=candidates, errors=errors,
                limits=['未檢查存檔、圖片文字與程式動態組句；class 文字由既有用途分析另行檢查。',
                        '這是檔案文字涵蓋檢查，不是遊戲畫面實測或逐句語意保證。'])


def coverage_index(rows):
    exact = collections.defaultdict(set); values = collections.defaultdict(list); listed = set()
    data_keys=collections.defaultdict(set);language_keys=collections.defaultdict(set)
    for row in rows:
        source = locale_source(row['source'])
        if row.get('kind') == 'unsupported_config_text':
            listed.add(source); continue
        texts = [row.get(k) for k in ('en', 'current', 'zh_cn') if isinstance(row.get(k), str)]
        if row.get('kind')=='language':
            for field in ('en','current','zh_cn'):
                value=row.get(field)
                if isinstance(value,(dict,list)):
                    texts.extend(v for _,f,v in leaves(value) if f in ('text','fallback'))
        key = row['key']; kind = row.get('kind', 'language')
        if kind=='language':language_keys[key].update(texts+[key])
        for text in texts:
            exact[(source, key)].add(text)
            if kind=='embedded_text':
                try:
                    component=json.loads(text)
                    if isinstance(component,str):exact[(source,key)].add(component)
                    elif isinstance(component,(dict,list)):
                        exact[(source,key)].add(json.dumps(component,ensure_ascii=True,sort_keys=True))
                except ValueError:pass
        if kind=='embedded_text' and not source.endswith('.nbt'):
            # Function, loot table, trade and REI units are keyed by their order ([line, n], [k], ["plain", k]), the
            # inventory's by line or JSON path: matched by words instead, each piece of a component counting.
            for text in texts:
                values[source].append(text)
                try:parsed=json.loads(text)
                except ValueError:parsed=None
                if isinstance(parsed,(dict,list)):values[source].extend(v for _,_,v in leaves(parsed))
        if kind in ('book', 'inline_lang', 'embedded_text'):
            try:
                path = tuple(json.loads(key))
                for text in texts:
                    try: parsed = json.loads(text)
                    except ValueError: parsed = None
                    if parsed is not None:
                        for child, _, value in leaves(parsed): exact[(source, json.dumps(path + child))].add(value)
            except (ValueError, TypeError): pass
        if key == 'text': values[source].extend(texts)  # a whole plain-text book page
        if row.get('key_from_data'):
            data_source = locale_source(row['key_from_data'])
            data_keys[(data_source,key)].update(texts+[key])
            if row.get('key_from_data_path'):
                exact[(data_source,row['key_from_data_path'])].update(texts+[key])
    return exact, values, listed,data_keys,language_keys


def sentence_key_source(source):
    """A data file whose sentences the mod uses as language keys (full_translation_audit.DATA_KEY_SENTENCES)."""
    from full_translation_audit import DATA_KEY_SENTENCES
    inner='/'+source.split('!/')[-1]
    return any(pattern.search(inner) for pattern,_ in DATA_KEY_SENTENCES)


def function_forms(text):
    """What a function's quoted value may be once read: SNBT escapes taken out, and a JSON string component
    (CustomName:'"Desert Blaze"', Incendium) without its quotes."""
    plain=re.sub(r'\\(.)',r'\1',text);forms={text,plain}
    for value in (text,plain):
        if value.startswith('"'):
            try:
                found=json.loads(value)
                if isinstance(found,str):forms.add(found)
            except ValueError:pass
    return forms


def component_words(text):
    """The readable "text" pieces of a JSON text component; [] for anything else."""
    if not text.lstrip().startswith(('{','[')):return []
    try:parsed=json.loads(text)
    except ValueError:return []
    return [v for _,f,v in leaves(parsed) if f=='text' and readable(v)]


def shows_nothing_literal(text, language_keys):
    """A JSON text component with no literal words: only language keys ({"translate":"name.gateways.necrotic_farmer"}),
    whose fallbacks, if any, belong to keys some language file defines."""
    if not text.lstrip().startswith(('{','[')):return False
    try:parsed=json.loads(text)
    except ValueError:return False
    literal=[];fallbacks=[];translated=[]
    def walk(node):
        if isinstance(node,dict):
            if isinstance(node.get('text'),str) and readable(node['text']):literal.append(node['text'])
            if isinstance(node.get('translate'),str):translated.append(node['translate'])
            if isinstance(node.get('fallback'),str):fallbacks.append((node.get('translate'),node['fallback']))
            for v in node.values():walk(v)
        elif isinstance(node,list):
            for v in node:
                if isinstance(v,str) and readable(v):literal.append(v)
                else:walk(v)
    walk(parsed)
    return bool(translated) and not literal and all(isinstance(k,str) and k in language_keys for k,_ in fallbacks)


def reconcile(inventory, rows):
    exact, values, listed,data_keys,language_keys = coverage_index(rows)
    for item in inventory['candidates']:
        source = locale_source(item['source']); text = item['text']
        if (text in exact.get((source, item['key']), ())
                or item.get('literal_key') and text in exact.get((source,item['literal_key']),())):
            state = 'covered'
        # Book lines are indented ("    Welcome to the Abyssal Chasm..."); the inventory keeps them stripped.
        elif any(text == v or (item['mode'] == 'literal' and text in (line.strip() for line in v.splitlines()))
                 for v in values.get(source, ())):
            state = 'covered'
        elif source.endswith('.mcfunction') and function_forms(text) & set(values.get(source,())):
            state = 'covered'  # the quoted SNBT string still has its escapes (\\n) or JSON quotes, the scanned unit has not
        elif text in language_keys and sentence_key_source(source):
            # Pixelmon NPC lines are language keys: one row per sentence serves every NPC and position that says it.
            state = 'covered'
        elif shows_nothing_literal(text,language_keys):
            # {"translate":"incendium.mob.castle.alchemist.name","fallback":"Piglin Alchemist"} with the key defined.
            state = 'covered'
        elif len(pieces:=component_words(text))==1 and pieces[0] in exact.get((source,item['key']),()):
            # {"extra":[{"text":"Eternatus"}],"text":""}: an empty "text" beside one word is still one piece of words,
            # which is what the scan made its row of (a lectern book's name in Legendary Monuments).
            state = 'covered'
        elif item.get('translation_key') and (text in data_keys.get((source,item['translation_key']),())
                or text in language_keys.get(item['translation_key'],())):
            state='covered'
        elif item.get('translation_key') in language_keys and (item['key'].endswith('"fallback"]') or item.get('is_fallback')):
            # A language file defines the key, so the game never shows this fallback (Mega Showdown's advancement
            # titles differ from their en_us only by a full stop); the language row is what gets translated.
            state='covered'
        elif source in listed or any(source.startswith(s) for s in listed if s.endswith('/')):
            state = 'listed'  # known unsupported, never claimed to be translated
        else: state = 'uncovered'
        item['state'] = state
    inventory['counts'] = dict(collections.Counter(c['state'] for c in inventory['candidates']))
    return inventory


def category(source):
    inner = source.split('!/')[-1]; top = source.split('/', 1)[0]; suffix = PurePosixPath(inner).suffix
    match = re.search(r'(?:^|/)(assets|data)/[^/]+/([^/]+)/', inner)
    if match: return f'{top} {match[1]}/*/{match[2]} ({suffix})'
    return f'{top} ({suffix})'


def categories(inventory):
    grouped = collections.defaultdict(list)
    for item in inventory['candidates']:
        if item['state'] in ('uncovered','listed'): grouped[category(item['source'])].append(item)
    for error in inventory['errors']:
        grouped['未能完成檢查'].append(dict(source=error['source'], key='', text=error['reason'],
                                         fingerprint=digest(error)))
    return {name: dict(files=len({i['source'] for i in items}), strings=len(items),
                      fingerprint=digest(sorted((i['fingerprint'],i.get('state')) for i in items)),
                      samples=[[i['source'], [i['key'], i['text'][:160]]] for i in items[:3]])
            for name, items in sorted(grouped.items())}


def changed_categories(current, previous):
    # Legacy summaries lack a fingerprint: they must be inspected once, even at identical counts.
    return {key: value for key, value in current.items()
            if not previous.get(key, {}).get('fingerprint')
            or value['fingerprint'] != previous[key]['fingerprint']}
