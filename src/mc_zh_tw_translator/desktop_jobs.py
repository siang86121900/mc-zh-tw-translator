"""Read-only planning, explicit review and guarded installation for desktop UI."""
from __future__ import annotations

import collections
import difflib
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
from pathlib import Path, PurePosixPath

from full_translation_audit import (Audit, parse, lang_table, inline_field, parse_binary_nbt, rewrite_binary_nbt, placeholders, at, string_literals,
                                    LOOSE_FOLDERS, CONTENT_PACK_FOLDERS, FANCYMENU, plain_text, VAULTPATCHER_MODULE)
from .deployment import apply_reviewed, contained, file_hash, atomic_copy, when_free
from .desktop_references import refresh, pick_reference, HUMAN_TW_KINDS, to_taiwan, has_simplified, VANILLA_STRUCTURE_NAMES
from .translator import MINECRAFT_GLOSSARY, is_jar_signature_file
from . import quest_lang
from . import embedded_text
from .verifier import VerifyResult, check_java_zipfs

SOURCE_NAMES = {'same_source_zh_cn':'同檔簡中', 'instance_zh_cn':'模組包中文',
                'shared_translation':'分享者的譯文（未經本機使用者確認）',
                'reference_pack_or_cfpa':'參考庫', 'glossary':'術語表',
                'translation_memory':'已確認記憶', 'existing_zh_tw':'既有繁中',
                'ai_translation':'AI 補譯', 'manual':'使用者修訂', 'untranslated':'缺少來源',
                'keep_original':'無需翻譯','instance_resourcepack':'已安裝資源包',
                'not_installed':'未安裝模組（略過）','user_glossary':'自訂譯名','not_display':'程式內部字串',
                'cross_version_reference':'跨版本參考','official_vanilla':'官方原版譯名','stale_reference':'參考庫（版本待確認）',
                'duplicate_copy':'模組內的重複舊版文字（略過）','server_lang':'伺服器用的英文語系檔（遊戲不讀繁中，略過）'}
HAN = re.compile('[\u3400-\u9fff]')
FOREIGN_LETTER = re.compile('[\u0370-\u03ff\u0400-\u04ff]')  # Greek and Cyrillic
# Names the game looks up from a biome, structure or dimension id (see full_translation_audit.REGISTRY_NAME).
REGISTRY_KEY = re.compile(r'(?:biome|structure|dimension)\.[a-z0-9_.\-]+\.')
# §-codes, Patchouli macros, {0} arguments, and FTB Quests' page breaks and inline images.
FORMAT = re.compile(r'§[0-9a-fk-or]|\$\([^)]+\)|\{[\w.]+\}|\{@\w+\}|\{image:[^}]*\}', re.I)
# FTB Quests and some other mods write colour codes with & (&6&lTitle&r); lower case only, so Q&A is not one.
AMPERSAND_CODE = re.compile(r'&[0-9a-fk-or]')
QUEST_NAMESPACE = 'ftbquests_quests'


# Files holding one text in several languages ({"en_us": ..., "zh_cn": ...}) whose mod is confirmed to show
# the entry of the game's language (zh_tw), falling back to en_us. Checked in the mod before adding a path:
# Ponderer (com.nododiiiii.ponderer.ponder.LocalizedText reads LanguageManager.getSelected()).
# Chrono Dawn 0.8.0's Chronicle book (assets/chronodawn/chronicle/): LocalizedText.get takes the game's language code
# (ChronicleScreen.getLanguageCode) with getOrDefault and en_us as the default; the book is read through the resource
# manager (ChronicleData), so the translation resource pack carries the file with zh_tw added. foxablazeaqzl_wiki
# 1.0.2.5 reads its wiki through the resource manager too and shows the zh_cn text for zh_tw (inline_field).
INLINE_ZH_TW = ('config/ponderer/scripts/','assets/chronodawn/chronicle/','assets/foxablazeaqzl_wiki/wiki/')
INLINE_UNVERIFIED = '並列多種語言的文字：還沒確認這個模組會讀繁中（zh_tw），暫不寫入'
# Mods that draw their own screens with a font holding no Chinese characters (Audit.own_font_without_chinese, e.g.
# Essential's fonts/Minecraft-Regular.json: 95 glyphs, U+0020-U+007E): Chinese there shows as □, so their text stays
# English. The font lies outside assets/, so a resource pack cannot replace it (see docs/translation-reference.md).
# Keys a mod's program asks for with a parameter Minecraft cannot fill in (full_translation_audit.renderable).
FORMAT_FIXED_NOTE = '原文的 {} 遊戲看不懂，英文版也會照原樣顯示；譯文改用 %s 才會顯示數值'
NO_CHINESE_FONT ='這個模組用自己的字型顯示介面（{}），字型裡沒有中文字，翻成中文會變成方框（□）'
KEPT_BY_AUTHOR = '模組自帶的繁中與簡中都刻意保留這個英文縮寫（例如 Lv.、HP、mB），照模組原樣顯示'


# Text the scan lists as a format no reader covers that stays English on purpose, with the reason checked in the mod.
# Beyond Adventures 1.1.9 draws its quest names (MissionsScreen) and its summon guide (InfoScreen, info_text/text.txt)
# in its own bitmap fonts (assets/beyond_gacha_c/font/tensura_*.json), which hold Latin letters and digits only.
# Better Pokédex Scanner 1.0.0 (VariantLabelLoader) reads every pack's variant_labels with listResourceStacks, lowest
# pack first, and VariantLabelRegistry.findMappedLabel returns the first group that matches: the mod's own English is
# always found before a resource pack's copy, so only the mod file itself could change it (COBBLEVERSE 2026-10-03).
KEEP_ENGLISH_FORMATS = [
    (re.compile(r'!/(?:data/beyond_gacha_c/quests|assets/beyond_gacha_c/info_text)/'),
     'Beyond Adventures 用自己的像素字型畫任務名稱與說明頁，字型裡只有英文字母，翻成中文會變成方框'),
    (re.compile(r'!/assets/better_pokedex_scanner/(?:variant_labels|entity_accessor_labels)/'),
     'Better Pokédex Scanner 的型態標籤會先讀模組自己的英文，翻譯資源包蓋不過去；只有改模組檔本身才能換掉，程式不修改模組檔的這類資源'),
    # Music Notification 3.0 (MusicResourceReloadListener) shows each track's "title", "author" and "album" as written;
    # random.json is not read by its program at all.
    (re.compile(r'!/assets/musicnotification/(?:musics|random)\.json$'),
     '音樂通知顯示的是曲名、作者與專輯名稱，屬於作品名稱，比照 Minecraft 官方繁中的唱片名保留英文'),
    # Ice and Fire 2.1.13 IceAndFireMainMenu: shown only with "Custom main menu" on (off by default), read from GitHub
    # first and else from its own jar by getResourceAsStream, which no resource pack reaches.
    (re.compile(r'!/assets/iceandfire/splashes\.txt$'),
     '冰與火的主選單標語只在開啟「Custom main menu」時出現（預設關閉），而且先從網路讀英文版，讀不到才用模組檔裡那份，翻譯資源包蓋不過去'),
]


def node_at(value, path):
    """The object or list at `path` in parsed JSON (at() returns text only); None when it is not there."""
    try:
        for k in path:value=value[k]
        return value
    except (KeyError,IndexError,TypeError):return None


def reads_inline_zh_tw(source):
    path=(source or '').split('!/')[-1]
    return any(path.startswith(p) for p in INLINE_ZH_TW)


def memory_scope(row):
    """What confirmed and AI translations are remembered under: the mod for language files, the file itself
    for text that lives in one file only (program text, several-language config text)."""
    ns=lang_namespace(row.get('source',''))
    return ns or (row.get('source','') if row.get('kind') in ('class_display','inline_lang','data_text','embedded_text') else '')


def lang_namespace(source):
    """The mod a language row belongs to (assets/<mod>/lang/..., or a mod's data/<mod>/lang/ that pack_resource puts
    under assets); quest language files form their own."""
    m=re.search(r'(?:assets|^[^!]+\.jar!/data)/([^/]+)/lang/',source or '')
    if m:return m[1]
    return QUEST_NAMESPACE if quest_lang.QUEST_LANG.search(source or '') else ''
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
KEY_MOD_REFERENCE = re.compile(r'^(?:biome|dimension|structure)\.([a-z0-9_]+)[./]|^travelerstitles\.(?!commands\.)([a-z0-9_]+)\.')
# Measurement units shown next to numbers (energy, fluid, pressure, temperature, time, power).
UNITS = {'mb','b','kb','bar','psi','rpm','hz','khz','w','kw','mw','v','a','j','kj','t','s','ms','ns','μi','µi','°c','°f','k',
         'fe','rf','eu','cf','mj','su','xp','ep','mp','hp'}


INDEX_NUMBER = re.compile(r'(?<!\S)\d{1,2}(?!\S)')


def numbered_names(rows):
    """(source, key) of names whose English tells look-alikes apart only by a number the mod's Chinese replaces with names
    of their own: Elemental Awakening's Wine Fox / Wine Fox 1…5 are 「奧術」「巫女」「冰霜」「櫻花」「魔女」「月汐」酒狐 in
    the author's zh_cn. The number check had sent 「冰霜」酒狐 to AI, which wrote 「奧術」酒狐 2 (owner, 2026-10-05).
    Only when every name of the group has Chinese without a number and no two of them are the same."""
    groups=collections.defaultdict(list)
    for r in rows:
        en=r.get('en')
        # Names only (item.<mod>.<path>): a tooltip or description under the name (item.pixelmon.rare_soda.tooltip) is a sentence.
        if r.get('kind')!='language' or not NAME_KEY.match(r['key']) or r['key'].count('.')!=2 or not isinstance(en,str) or len(en)>40:continue
        numbers=INDEX_NUMBER.findall(en)
        if len(numbers)>1:continue
        base=' '.join(INDEX_NUMBER.sub(' ',en).split()).casefold()
        chinese=next((v for v in (r.get('zh_cn'),r.get('current')) if isinstance(v,str) and HAN.search(v)),None)
        groups[(r['source'],r['key'].split('.')[0],base)].append((r['key'],bool(numbers),chinese))
    found=set()
    for (source,_,_),names in groups.items():
        numbered=[k for k,has,_ in names if has]
        chinese=[c for _,_,c in names]
        if (len(numbered)>=2 and all(chinese) and len(set(chinese))==len(chinese)
                and not any(re.search(r'\d',c) for c in chinese)):
            found|={(source,k) for k in numbered}
    return found


def author_kept(english, own_tw, zh_cn):
    """The mod's own zh_tw and zh_cn both keep this English as it is, and it is an abbreviation (Lv., HP, mB, X, IV),
    not a word: a word both translators left (Done, Fuel, Toad, Fox) is still translated. The caller also requires
    the mod's zh_tw to be mostly Chinese, so a zh_tw that is a plain copy of en_us keeps nothing."""
    if not isinstance(english,str) or not all(isinstance(v,str) and not HAN.search(v) and v.strip()==english.strip()
                                              for v in (own_tw,zh_cn)):return False
    core=PARAMETER.sub(' ',english)
    return 0<len(re.findall('[A-Za-z]',core))<=4 and not re.search(r'[A-Za-z][a-z]{2}',core)


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
    if re.fullmatch(r'\{@\w+\}|\{image:[^}]*\}',stripped):return '任務書的換頁或圖片指令'
    if '�' in text:return '刻意製作的亂碼效果'
    if stripped.casefold() in BRANDS:return '平台或品牌名稱'
    if re.fullmatch(r'#?[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',stripped) and re.search(r'\d',stripped):return '色碼'
    if re.fullmatch(r'#[A-Za-z_]+',stripped):return '書本樣板變數'
    if re.match(r'/[a-z]',stripped):return '指令用法'
    if re.fullmatch(r'(?:config|assets|data|kubejs|mods|saves|defaultconfigs)(?:/[a-z0-9_.\-]+)+|[a-z0-9_.\-]+:[a-z0-9_./\-]+|\w+=\w+(?:,\w+=\w+)*',stripped):return '檔案路徑、ID 或語法範例'
    if stripped=='Boss':return '官方繁中也直接寫 Boss'
    if REGISTRY_KEY.match(key):namespace=''  # a structure that shares the mod's name ([Let's Do] Bakery's bakery) is a place
    if namespace and key==namespace and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9&+'\- ]{2,39}",stripped):return '模組名稱'
    compact=lambda s:re.sub('[^a-z0-9]','',s.lower().replace('&','and'))
    name=compact(re.sub(r'\s+wiki$','',stripped,flags=re.I));mod=compact(re.sub(r'\d+$','',namespace or ''))
    if mod and len(name)>=4 and name in (mod,mod.removesuffix('mod')):return '模組名稱'
    core=PARAMETER.sub(' ',text).strip()
    if not re.search('[A-Za-z]',core):return '只有參數、數字或符號'
    # Internet laughter (ww, www) and a kaomoji greeting such as Ciallo～(∠・ω< )⌒★ read the same in Chinese.
    if re.fullmatch(r'w{2,}|W{2,}',core):return '網路用語或表情符號'
    if re.search(r'[ω∠⌒・ﾟ´｀]',core) and len(re.findall(r'[A-Za-z]{2,}',core))<=1:return '網路用語或表情符號'
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
        reason=keep_original_reason(original_of(row),row.get('key',''),lang_namespace(row.get('source','')))
        if reason:row.update(origin='keep_original',issue='無需翻譯：'+reason);moved+=1
    if moved:
        counts=session.setdefault('source_counts',{})
        counts['untranslated']=max(0,counts.get('untranslated',0)-moved)
        counts['keep_original']=counts.get('keep_original',0)+moved
        session.pop('preview_cards',None)  # counted again from the rows
    return moved


def readopt_rejected(session):
    """AI answers an earlier, stricter check turned down that the current checks accept, taken without asking
    AI again (the answer is kept in the row). Numbers are still checked. Returns how many were taken."""
    taken=0
    for row in session.get('rows',[]):
        rejected=row.get('ai_rejected') or {}
        if row.get('origin')!='untranslated' or not row.get('supported') or rejected.get('reason') not in ('format','number') or not rejected.get('text'):continue
        original=original_of(row);text=repair(original,rejected['text'])
        if not validate_text(original,text) or number_doubt(original,text) or added_numbers(original,text):continue
        row.pop('ai_rejected',None)
        row.update(proposed=text,origin='ai_translation',evidence='ChatGPT/Codex: '+str(rejected.get('model') or ''),ai_model=rejected.get('model'),
                   changed=text!=row.get('current'),reviewed=False,
                   issue='AI 補譯（先前被較嚴的'+('數字' if rejected['reason']=='number' else '格式')+'檢查退回，現在的檢查已接受），尚未人工校對。')
        taken+=1
    if taken:
        counts=session.setdefault('source_counts',{})
        counts['untranslated']=max(0,counts.get('untranslated',0)-taken);counts['ai_translation']=counts.get('ai_translation',0)+taken
        session['ai_translation']=sum(r.get('origin')=='ai_translation' for r in session.get('rows',[]))
        session.pop('preview_cards',None)
    return taken


JSON_BROKEN=re.compile(r'^(Expecting|Unterminated string|Invalid control character|Invalid \\escape|Extra data)')

# Compressed data the mod ships damaged (Dungeon Now Loading 2.2: four structure files whose gzip data does not unpack).
DAMAGED=re.compile(r'(?:^|: )(?:CRC check failed|Error -3 while decompressing|Not a gzipped file|Compressed file ended)')

def broken_source_file(error):
    """A file that ships broken: the game cannot read it either, so no text is missing from the screen."""
    parts=[p for p in error if isinstance(p,str)] if isinstance(error,(list,tuple)) else [str(error)]
    return len(parts)>1 and bool(JSON_BROKEN.match(parts[-1]) or DAMAGED.search(parts[-1]))


def broken_inventory_file(error):
    """The coverage check's read failure of a file that ships broken (damaged compression, malformed JSON)."""
    detail=(error.get('detail') or '') if isinstance(error,dict) else ''
    kind,_,message=detail.partition(': ')
    return kind in ('BadGzipFile','error','EOFError','JSONDecodeError') and bool(DAMAGED.search(detail) or JSON_BROKEN.match(message))


def describe_error(error):
    """Turn a raw audit error list into one readable report line."""
    parts=[p for p in error if isinstance(p,str)] if isinstance(error,(list,tuple)) else [str(error)]
    where=Path(parts[0]).name if parts else ''
    detail=parts[-1] if len(parts)>1 else ''
    if DAMAGED.search(detail):
        detail='檔案在模組裡原本就是壞的（壓縮資料解不開，遊戲讀它也會失敗），這個檔案的文字無法掃描（檔案沒有被修改）。（技術細節：'+detail[:160]+'）'
    elif 'Expecting' in detail:
        detail='檔案本身格式錯誤，遊戲也讀不到，這個檔案的文字這次沒有掃描（檔案沒有被修改）。（技術細節：'+detail[:160]+'）'
        if any(isinstance(p,dict) and 'zh_tw' in p for p in error):detail+='。重新執行一鍵翻譯時會自動重建這個繁中檔。'
    elif detail and not HAN.search(detail):
        # The audit keeps the raw exception text; the screen gets what it means for the player.
        kind='裡面有無法辨識的文字編碼' if 'codec' in detail or 'surrogate' in detail else '讀取時發生沒有預料到的問題'
        detail=f'{kind}，這個檔案的文字這次沒有掃描（檔案沒有被修改）。（技術細節：{detail[:160]}）'
    return (where+'：'+detail) if detail else where


def explain_error(exc):
    """What went wrong and what to do next, in plain words; the raw text is kept as a short detail.

    Messages this program raises itself are already written for players and pass through.
    """
    import errno
    import requests
    from .desktop_references import network_message, RateLimited
    text=str(exc)
    if isinstance(exc,(requests.RequestException,RateLimited)):return network_message(exc)
    if HAN.search(text) and not isinstance(exc,OSError):return text
    name=Path(getattr(exc,'filename',None) or '').name
    where=f'「{name}」' if name else '檔案'
    code=getattr(exc,'winerror',None);number=getattr(exc,'errno',None)
    if isinstance(exc,OSError) and (number==errno.ENOSPC or code in (39,112)):
        plain='硬碟空間不足，已停止。請清出空間後再試；已完成的譯文和報告都有保存。'
    elif isinstance(exc,OSError) and (number==errno.ENAMETOOLONG or code in (206,3) and len(str(getattr(exc,'filename','') or ''))>240):
        plain='檔案路徑太長，Windows 無法處理。請把 MCTranslator.exe 連同 MCTranslatorData 移到較短的位置（例如 C:\\MCTranslator）後再試。'
    elif isinstance(exc,PermissionError):
        plain=f'{where}正被其他程式使用，或沒有寫入權限。請關閉遊戲、啟動器和正在掃描的防毒軟體後再試。'
    elif isinstance(exc,FileNotFoundError):
        plain=f'找不到{where}，可能已被移動、改名或刪除。請重新選擇模組包後再試。'
    elif isinstance(exc,zipfile.BadZipFile):
        plain='有模組檔或壓縮檔已損壞，無法讀取。請用啟動器修復或重新下載這個模組包後再試。'
    elif isinstance(exc,MemoryError):
        plain='電腦記憶體不足，已停止。請關閉其他程式後再試。'
    elif isinstance(exc,subprocess.TimeoutExpired):
        plain='檢查模組檔花費太久，已停止，沒有修改遊戲檔案。請稍後再試。'
    elif isinstance(exc,(ValueError,UnicodeError,KeyError,IndexError,TypeError)):
        plain='有檔案的內容格式和預期不同，無法處理，已停止，沒有修改遊戲檔案。'
    elif isinstance(exc,OSError):
        plain=f'讀寫{where}時發生問題，已停止。請確認磁碟正常、資料夾沒有被其他程式鎖住後再試。'
    else:
        plain='發生沒有預料到的問題，已停止。已完成的譯文和報告都有保存。'
    return plain+'\n（技術細節：'+type(exc).__name__+'：'+text[:200]+'）'


def original_of(row):
    """The text a translation is checked against: the row's English, else the installed mod's English
    for the same key (en_ref), else the Chinese the row was read from (mod_text: a data file's own text, which the
    translation data pack covers, see data_text_row)."""
    return row.get('en') or row.get('en_ref') or row.get('zh_cn') or row.get('mod_text') or row.get('current') or ''


def english_of(row):
    """The English a row stands for: its own, else the installed mod's for the same key; None when there is none."""
    return row['en'] if isinstance(row.get('en'),str) else row.get('en_ref') if isinstance(row.get('en_ref'),str) else None


NUMBER = re.compile(r'\d+(?:\.\d+)?')
UNITS_OF_NUMBER = {'thousand':1e3,'million':1e6,'billion':1e9,'k':1e3,'千':1e3,'萬':1e4,'億':1e8}
NUMBER_UNIT = re.compile(r'(\d+(?:\.\d+)?)\s*(thousand|million|billion|k(?![a-z])|[千萬億])',re.I)
CHINESE_NUMERAL = re.compile('[零〇一二兩三四五六七八九十百千萬億半雙]')


MONTHS = ('January','February','March','April','May','June','July','August','September','October','November','December')
# A month name is a number once translated (December → 12 月). "May" only next to a date or another month name.
MONTH = re.compile(r'\b(?:'+'|'.join(m for m in MONTHS if m!='May')+r')\b|\bMay\b(?=\s+\d|\s*(?:,|and\b|or\b|to\b|-)\s*[A-Z])|\b(?:(?<=in )|(?<=of )|(?<=and )|(?<=to ))May\b')


def numbers_in(text):
    """The plain numbers a text states, parameters left out, 10k / 1萬 and English month names written out."""
    text=re.sub(r'(?<=\d),(?=\d{3})','',PARAMETER.sub(' ',text))
    text=MONTH.sub(lambda m:f' {MONTHS.index(m[0])+1} ',text)
    # 1 million, 10k, 100萬 and 1億 are written out so that both sides compare as plain numbers.
    text=NUMBER_UNIT.sub(lambda m:f' {float(m[1])*UNITS_OF_NUMBER[m[2].casefold()]:.10g} ',text)
    return [f'{float(n):.10g}' for n in NUMBER.findall(text)]


def added_numbers(original, value):
    """Numbers a new translation states that the original does not, as a note; '' when none."""
    extra=list((collections.Counter(numbers_in(value))-collections.Counter(numbers_in(original))).elements())
    return '譯文多了原文沒有的數字（'+'、'.join(extra[:4])+'），請核對' if extra else ''


def number_doubt(original, value):
    """Numbers of the English original that the translation dropped or changed, as a note; '' when fine.

    The usual cause is Chinese written for another version of the mod (gains 20 experience → 獲得 10 點).
    Numbers written in Chinese (九十九, 雙倍) and parameters such as %1$s are not counted.
    """
    if not isinstance(original,str) or not isinstance(value,str):return ''
    wanted=numbers_in(original);found=numbers_in(value)
    missing=[n for n in wanted if n not in found];extra=[n for n in found if n not in wanted]
    if not missing or (not extra and CHINESE_NUMERAL.search(value)):return ''
    if not extra and set(missing)=={'0'} and re.search('[無沒未]',value):return ''
    return '數值和原文不同（原文 '+'、'.join(missing[:4])+('，譯文 '+'、'.join(extra[:4]) if extra else '，譯文沒有寫出')+'），請核對'


def json_text_shape(text):
    """A JSON text component line ({"text": ..., "clickEvent": ...}) with its shown text blanked, else None.

    Only the words shown to the player may change; the link target and styling must stay as they are.
    """
    s=(text or '').strip()
    if not (s.startswith('{') and s.endswith('}') and '"' in s):return None
    try:data=json.loads(s)
    except ValueError:return None
    def blank(node,field=''):
        if isinstance(node,dict):return {k:blank(v,k) for k,v in node.items()}
        if isinstance(node,list):return [blank(v,field) for v in node]
        return '' if field=='text' and isinstance(node,str) else node
    return blank(data) if isinstance(data,dict) else None


def same_format(original, value):
    """Everything validate_text compares except the number of line breaks."""
    if not isinstance(value,str) or '\ufffd' in value:return False
    if not original:return True
    shape=json_text_shape(original)
    if shape is not None and json_text_shape(value)!=shape:return False
    words=embedded_text.blank_words(original) if original.lstrip()[:1] in ('[','{') else None
    if words is not None and embedded_text.blank_words(value)!=words:return False  # a whole text component's shape
    if embedded_text.fancymenu_marks(original)!=embedded_text.fancymenu_marks(value):return False  # FancyMenu's codes
    return (placeholders(original)==placeholders(value)
            and re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',original)==re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value)
            and code_signature(original)==code_signature(value))


def code_signature(text):
    """What the codes of a text must keep through translation.

    - Colour and style codes (§6, &l): which ones are used. Chinese word order often needs a colour to be
      opened again after a coloured name (§8以§7皇家弓§8射中), and a code before every English word has no
      one-to-one Chinese counterpart, so how often a code appears is not compared.
    - Patchouli macros that point somewhere ($(l:items/x), $(k:use), $(t:tip)) and arguments ({0}, page
      breaks, images): each one, as often as the original has it.
    - Other Patchouli macros only style or insert a word ($(item), $(thing), $(), $(br), $(aura)); a
      translation may use them more or less often.
    """
    styles=set(re.findall(r'§[0-9a-fk-or]',text or '',re.I))|set(AMPERSAND_CODE.findall(text or ''))
    fixed=collections.Counter(m for m in FORMAT.findall(text or '') if not m.startswith('§') and (not m.startswith('$(') or ':' in m))
    return frozenset(x.lower() for x in styles),fixed


def index_placeholders(original, value):
    """`value` with its %s / %d written as %2$s / %1$d when Chinese word order put them in another order.

    Each kind keeps its own order (the first %s of the translation is the first %s of the original), so
    the game fills in the same values as in English. Unchanged when that cannot be done safely.
    """
    if not isinstance(original,str) or not isinstance(value,str) or placeholders(original)==placeholders(value):return value
    pattern=r'%%|%(\d+\$)?([sdif])'
    wanted=[(m[2]) for m in re.finditer(pattern,original) if m[0]!='%%']
    if any(m[1] for m in re.finditer(pattern,original)) or any(m[1] for m in re.finditer(pattern,value)):return value
    got=[m[2] for m in re.finditer(pattern,value) if m[0]!='%%']
    if sorted(wanted)!=sorted(got):return value
    slots={k:[i+1 for i,t in enumerate(wanted) if t==k] for k in set(wanted)}
    used=collections.Counter()
    def number(m):
        if m[0]=='%%':return m[0]
        n=slots[m[2]][used[m[2]]];used[m[2]]+=1
        return f'%{n}${m[2]}'
    fixed=re.sub(pattern,number,value)
    return fixed if placeholders(original)==placeholders(fixed) else value


def repair(original, value):
    """Only the layout differs: parameters numbered for Chinese word order, then line breaks laid out again."""
    return fit_lines(original,index_placeholders(original,value))


def validate_text(original, value):
    return same_format(original,value) and (not original or original.count('\n')==value.count('\n'))


def fits(original, value, own_lines=False):
    """validate_text, except that Chinese written by people (the mod author, a translation group) keeps its own
    line breaks: they often need fewer lines than the English, and breaking them again cut words in two."""
    return validate_text(original,value) or bool(own_lines and isinstance(value,str) and same_format(original,value))


def row_fits(row, value=None):
    return fits(original_of(row),row.get('proposed','') if value is None else value,row.get('own_lines'))


def required_codes(original):
    """The codes a translation must carry over unchanged, in the order the original has them (told to AI)."""
    found=[(m.start(),m[0]) for pattern in (FORMAT,AMPERSAND_CODE) for m in pattern.finditer(original or '')]
    found+=[(m.start(),m[0]) for m in re.finditer(r'%%|%(?:\d+\$)?[-#+0,(]*\d*(?:\.\d+)?[sdif]',original or '') if m[0]!='%%']
    return [code for _,code in sorted(found)]


def format_problem(original, value):
    """What makes `value` fail validate_text, in words a player can act on."""
    (want_styles,want_fixed),(got_styles,got_fixed)=code_signature(original),code_signature(value)
    missing=sorted(want_styles-got_styles)+list((want_fixed-got_fixed).elements())
    extra=sorted(got_styles-want_styles)+list((got_fixed-want_fixed).elements())
    parts=[]
    if missing:parts.append('譯文少了這些代碼：'+'　'.join(missing[:8]))
    if extra:parts.append('譯文多了原文沒有的代碼：'+'　'.join(extra[:8]))
    if placeholders(original)!=placeholders(index_placeholders(original,value)):parts.append('參數（%s、%d 這類）的數量或種類和原文不同。')
    if json_text_shape(original) is not None and json_text_shape(value)!=json_text_shape(original):
        parts.append('這一行是任務書的連結，只能改 "text" 引號裡的文字，其他部分要照原樣保留。')
    if not parts:parts.append('請保留原文的參數、格式碼及特殊符號。')
    return '\n'.join(parts)+'\n\n代碼要原樣照抄（例如 §6、&l、%s、$(l:連結)），位置可以依中文調整。'


# Where a line may not be broken: inside a code, parameter or macro, or inside an English word.
UNBREAKABLE = re.compile(PARAMETER.pattern+'|'+FORMAT.pattern+'|'+AMPERSAND_CODE.pattern+r"|[A-Za-z0-9'\u2019]{2,}",re.I)
BREAK_AFTER = '\u3002\uff0c\u3001\uff1b\uff1a\uff01\uff1f,.;:!?\uff09)\u300d\u300f '


def fit_lines(original, text):
    """`text` with as many line breaks as `original`, else `text` unchanged.

    A translation often needs fewer lines than the English it replaces (tooltips and descriptions break
    lines for width). The line breaks are laid out again in proportion to the English lines, at
    punctuation where possible and never inside a code, parameter or word; blank lines of the original
    stay blank. Nothing but line breaks changes, so the text passes the same checks it did.
    """
    if not isinstance(original,str) or not isinstance(text,str):return text
    want=original.count('\n')
    if text.count('\n')==want or not same_format(original,text):return text
    pieces=[p.strip() for p in text.split('\n')];joined=''
    for p in pieces:
        if not p:continue
        # English words on both sides of a removed break keep a space between them.
        joined+=(' ' if joined and re.match(r'[A-Za-z0-9]',p) and re.search(r'[A-Za-z0-9.,!?:;]$',joined) else '')+p
    if not joined:return text
    blocked=set()
    for m in UNBREAKABLE.finditer(joined):blocked.update(range(m.start()+1,m.end()))
    lengths=[len(l.strip()) for l in original.split('\n')];total=sum(lengths) or 1
    cuts=[];done=0;last=0
    for length in lengths[:-1]:
        done+=length;target=round(len(joined)*done/total)
        if length==0 or target<=last:cuts.append(last);continue  # an empty English line stays empty
        best=None
        for span in range(0,9):
            for p in (target-span,target+span):
                if last<p<len(joined) and p not in blocked and (best is None or (joined[p-1] in BREAK_AFTER)>(joined[best-1] in BREAK_AFTER)):
                    best=p
            if best is not None and joined[best-1] in BREAK_AFTER:break
        if best is None:best=next((p for p in range(max(target,last+1),len(joined)) if p not in blocked),len(joined))
        cuts.append(best);last=best
    bounds=[0]+cuts+[len(joined)]
    fitted='\n'.join(joined[a:b].strip() for a,b in zip(bounds,bounds[1:]))
    return fitted if validate_text(original,fitted) else text


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
        self.remember_many([(namespace,key,original,text,source)])
    def remember_many(self,items,batch=None):
        """items: (namespace, key, original, text, source); `batch` names a confirm-all so it can be undone."""
        now=datetime.now().isoformat(timespec='seconds')
        for namespace,key,original,text,source in items:
            ident=self.ident(namespace,key,original);entry=dict(text=text,original=original,source=source,confirmed_at=now)
            if batch:
                entry['batch']=batch
                if ident in self.entries:entry['before']=self.entries[ident]  # what undo puts back
            self.entries[ident]=entry
        write_json(self.path,dict(format=1,entries=self.entries))
    def forget_batch(self,batch):
        """Undo one confirm-all: its entries go, and entries it replaced come back."""
        count=0
        for ident,entry in list(self.entries.items()):
            if entry.get('batch')==batch:
                count+=1
                if entry.get('before'):self.entries[ident]=entry['before']
                else:del self.entries[ident]
        if count:write_json(self.path,dict(format=1,entries=self.entries))
        return count


# v0.32.0 told AI to translate the names of people, trainers, Pokémon and places. Answers remembered before then
# that still show such a name in English (定位 §eMisty§r 道館, COBBLEVERSE 2026-10-04) are asked once more.
NAMES_RULE_AT='2026-10-04T00:43'
# Names that stay English in Chinese text: the game, loaders, keys, values and sites, never a person or place.
KEPT_ENGLISH_NAMES=frozenset('Minecraft Mojang Forge Neoforge Fabric Quilt Json Shift Ctrl Alt Tab Enter Esc Space True False '
                             'Null Patreon Discord Curseforge Modrinth Github Kubejs Java Windows Iris Optifine Sodium Jei Rei Emi'.split())


def english_names_left(original, text):
    """Capitalised English words of `original` that the Chinese `text` still shows (Misty in 定位 §eMisty§r 道館)."""
    if not isinstance(original,str) or not isinstance(text,str) or not HAN.search(text):return []
    plain=lambda s:re.sub(r'§.|%(\d+\$)?[a-z]|\$\([^)]*\)|\{[^}]*\}|<[^>]*>|https?://\S+',' ',s)
    words={w for w in re.findall(r'(?<![A-Za-zà-ÿ])[A-Z][a-zà-ÿ]{2,}',plain(original)) if w not in KEPT_ENGLISH_NAMES}
    return sorted(w for w in words if re.search(r'(?<![A-Za-zà-ÿ])'+re.escape(w)+r'(?![A-Za-zà-ÿ])',plain(text)))


def reuse_marks(earlier):
    """The fields of a row that uses an earlier AI answer; ai_redo names the English it left (see AiMemory)."""
    return dict(ai_reused=True,ai_model=earlier.get('model'),**({'ai_redo':earlier['redo']} if earlier.get('redo') else {}))


class AiMemory:
    """AI translations made earlier, reused for the same mod, key and English text in any modpack.

    It saves quota and keeps wording the same between modpacks. Reused text stays labelled as AI
    translation and ranks last, so every other source and everything the user confirmed come first.
    An answer from before NAMES_RULE_AT that left a name in English comes back with redo: it is still used,
    so the game does not fall back to the English sentence, and the next AI run translates it again.
    """
    def __init__(self, home):
        self.path=Path(home)/'ai_memory.json'
        try:self.entries=json.loads(self.path.read_text(encoding='utf-8')).get('entries',{})
        except (OSError,ValueError,AttributeError):self.entries={}
    def lookup(self,namespace,key,original):
        entry=self.entries.get(TranslationMemory.ident(namespace,key,original)) if namespace and original else None
        if not isinstance(entry,dict) or not isinstance(entry.get('text'),str):return None
        if not entry.get('keep') and str(entry.get('made_at') or '')<NAMES_RULE_AT:
            names=english_names_left(original,entry['text'])
            if names:return dict(entry,redo=names)
        return entry
    def checked(self,namespace,key,original):
        """The name AI read for English left in it (see name_doubts) and kept as it was; None when it has not."""
        entry=self.entries.get(TranslationMemory.ident(namespace,key,original)+'\nchecked') if namespace and original else None
        return entry.get('checked') if isinstance(entry,dict) else None
    def remember_checked(self,rows,model):
        """Names AI found right in spite of the English in them; kept apart from translations, which they are not."""
        for r in rows:
            ns=lang_namespace(r.get('source',''));original=english_of(r)
            if ns and original:
                self.entries[TranslationMemory.ident(ns,r['key'],original)+'\nchecked']=dict(
                    checked=r['proposed'],model=model,made_at=datetime.now().isoformat(timespec='seconds'))
        if rows:write_json(self.path,dict(format=1,entries=self.entries))
    def remember_many(self,rows,model):
        """Keeps AI's translations, and its "leave as it is" answers (keep=True, with its reason)."""
        for r in rows:
            ns=lang_namespace(r.get('source',''));original=original_of(r)
            entry=dict(text=original if r.get('ai_keep') else r['proposed'],original=original,model=model,
                       made_at=datetime.now().isoformat(timespec='seconds'))
            if r.get('ai_keep'):entry.update(keep=True,reason=r.get('evidence') or '')
            # embedded_text too: a launcher that puts the original data pack back (COBBLEVERSE 2026-10-03) must not
            # send its NPC names to AI again, where a second answer kept 小霞 as Misty.
            if original and r.get('kind') in ('class_display','inline_lang','data_text','embedded_text'):
                self.entries[TranslationMemory.ident(r['source'],r['key'],original)]=entry
            if ns and original and r.get('kind')=='language':
                self.entries[TranslationMemory.ident(ns,r['key'],original)]=entry
        if rows:write_json(self.path,dict(format=1,entries=self.entries))


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
    return {k:v for k,v in row.items() if k not in ('flags','status','reason','own_tw')}


def literal_conversion(r, curseforge, provenance, lang_text):
    """Whether a program string whose use is unproven is converted from Simplified to Taiwan Traditional in
    place: plain Chinese literal, in a mod file the launcher does not put back, not inside a nested jar, not
    a generator's or log line, and Simplified (or written by this program before, so a rerun recognises it)."""
    if r.get('kind')!='class_candidate' or not r.get('plain_literal'):return False
    value=r.get('current') or ''
    if managed(curseforge,r) or is_nested(r) or r.get('language_generator') or r.get('developer_use'):return False
    if internal_reason(value) or in_language_file(r,value,lang_text):return False
    return has_simplified(value) or bool(provenance.lookup(r))


def in_language_file(r, text, lang_text):
    """A program string whose use is unproven, word for word a sentence of the same mod file's language files:
    a helper of the mod's language-file generator (Age of Mythology's TarotCompletionTranslations hands its
    entries to AOMChineseProvider), so the game shows the language file's copy, which is translated there.
    Short names are left listed: a mod may also show a word such as 'Fire' straight from its program."""
    s=(text or '').strip()
    if r.get('kind')!='class_candidate' or (r['source'].rsplit('!/',1)[0],s) not in lang_text:return False
    return len(HAN.findall(s))>=4 or len(re.findall(r'\b[A-Za-z]{3,}\b',s))>=3


def show_language_copies(rows, decided):
    """A program copy of a language-file sentence is listed with the language file's wording, what the game
    shows ('長按%s跳過劇情' for 长按%s跳过剧情), so the report never shows text the player does not see.
    Only the listed wording changes: the row stays unsupported and is never written."""
    shown={}
    for row in decided:
        if row.get('kind')=='language' and row['source'].startswith('mods/') and HAN.search(row.get('proposed') or ''):
            for v in (row.get('en'),row.get('zh_cn'),row.get('own_tw'),row.get('current')):
                if isinstance(v,str):shown.setdefault((row['source'].rsplit('!/',1)[0],v.strip()),row['proposed'])
    for row in rows:
        if row.get('language_copy'):
            text=shown.get((row['source'].rsplit('!/',1)[0],str(row.get('current') or row.get('en') or '').strip()))
            if text:row['proposed']=text


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
        original=english_of(r)
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
    return rows[:limit] if limit else rows


def apply_term(session, en, zh, key_tail=None):
    """Use the agreed name for every name row whose whole text is `en` (and key tail, when given)."""
    changed=0
    for r in session.get('rows',[]):
        if (isinstance(english_of(r),str) and english_of(r).strip().casefold()==en.strip().casefold() and r.get('supported')
                and not r.get('installed') and NAME_KEY.match(r.get('key',''))
                and (key_tail is None or r['key'].split('.',2)[-1]==key_tail)):
            if not validate_text(english_of(r),zh):continue
            if r.get('origin') not in ('user_glossary',):r['previous_origin']=r.get('origin')
            r.update(proposed=zh,origin='user_glossary',evidence='user_glossary.json',issue='',changed=zh!=r.get('current'),
                     reviewed=False,review_method=None);changed+=1
    return changed


UNCERTAIN_ORIGINS = ('ai_translation','stale_reference','cross_version_reference')


class Provenance:
    """Where each applied translation came from, per instance.

    After applying, our text sits in the mod's own zh_tw; a later run would otherwise take it for
    people-written zh_tw and drop its AI / converted label. Matching text and English restore the label.
    """
    def __init__(self, home, instance):
        digest=hashlib.sha1(str(Path(instance).resolve()).casefold().encode('utf-8')).hexdigest()[:16]
        self.path=Path(home)/'provenance'/(digest+'.json')
        try:self.entries=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.entries={}
    @staticmethod
    def key(row):return row['source']+'\n'+row['key']
    def lookup(self, row):
        e=self.entries.get(self.key(row))
        return e if e and e.get('text')==row.get('current') and e.get('en')==row.get('en') else None
    def record(self, rows):
        for r in rows:
            self.entries[self.key(r)]=dict(text=r['proposed'],en=r.get('en'),origin=r['origin'],evidence=r.get('evidence') or '',
                                           issue=r.get('issue') or '',unified_from=r.get('unified_from'),model=r.get('ai_model'),
                                           original=original_of(r) if r.get('kind') in ('class_display','embedded_text') else None)
        self.path.parent.mkdir(parents=True,exist_ok=True);write_json(self.path,self.entries)


def needs_check(row):
    """Concrete unresolved doubts. Origin and automatic repairs stay in source details;
    their presence alone is not evidence that the player must inspect the sentence."""
    if str(row.get('review_method') or '').startswith('user_confirmed'):return False  # the user has looked at it
    if (row.get('ai_review') or {}).get('verdict')=='ok':return False  # AI read it against the English and agreed
    if row.get('supported') and row.get('number_doubt') and row.get('origin') not in ('untranslated','keep_original'):return True
    if row.get('supported') and (row.get('name_doubt') or row.get('map_word')) and row.get('origin') not in ('untranslated','keep_original'):return True
    if row.get('supported') and row.get('format_fixed') and row.get('origin') not in ('untranslated','keep_original'):return True
    if row.get('supported') and (row.get('ai_review') or {}).get('verdict')=='rejected':return True
    return bool(row.get('supported') and row.get('origin') in ('stale_reference','cross_version_reference'))


# Unambiguous mainland words that some mods' "zh_tw" keeps after a character-only conversion.
# A full OpenCC s2twp pass over traditional text is not used: it turns 用戶端 into 用使者端,
# 項目 into 專案 and 權限 into 許可權.
TW_WORDING = [(re.compile(a),b) for a,b in (
    # 控制代碼, 錯誤代碼, 國家代碼 and the like are Taiwan wording too; only code in the programming sense changes.
    ('激活','啟用'),('添加','新增'),('(?<![制誤家態言色式區])代碼','程式碼'),('默認','預設'),('信息','資訊'),('啓','啟'),
    ('視頻','影片'),('軟件','軟體'),('硬件','硬體'),('文件夾','資料夾'),('菜單','選單'),('鼠標','滑鼠'),
    # 數據機 (modem) and 大數據 are Taiwan wording; 增加載入 is 增加 + 載入, not 加載.
    ('屏幕','螢幕'),('界面','介面'),('服務器','伺服器'),('(?<!大)數據(?!機)','資料'),('(?<![增附追添外])加載(?!入)','載入'),('兼容','相容'),
    # 質量 (mass) and 支持 (支持者, 感謝支持) are left alone: both are also correct Taiwan wording.
    ('用戶(?!端)','使用者'),('網絡','網路'),('設置','設定'),('緩存','快取'),
    ('西蘭花','青花菜'),  # SMC's 西蘭花農場 (Broccoli Farm)
    ('疆盜','強盜'),  # a typo in Explorer's Compass's own zh_tw and the compass translation pack (Bandit Towers)
)]
KANA = re.compile('[぀-ヿ]')


def taiwan_wording(text):
    if not isinstance(text,str) or KANA.search(text):return text
    for pattern,replacement in TW_WORDING:text=pattern.sub(replacement,text)
    from .desktop_references import minecraft_terms, fix_slips
    return minecraft_terms(fix_slips(text))  # also the wrong characters of a character-only conversion (下界合金鍾)  # 下界 → 地獄, 末影 → 終界…: Minecraft's own names as Taiwan's official zh_tw has them


def unsupported_note(session):
    """A red report line for files holding what may be player text in a format no reader covers yet (see
    Audit.unsupported_sample / Audit.unscanned); '' when there are none. These are the gaps a new modpack can
    bring, so they are shown to the player instead of only being counted."""
    # Only what is surely text: Chinese, or language files. A config line that merely names a field (name = "minecraft")
    # stays in the list below without a red line.
    files=sorted({r['source'] for r in session.get('rows',[]) if r.get('kind')=='unsupported_config_text'
                  and r.get('origin')!='keep_original'  # checked and kept English on purpose (KEEP_ENGLISH_FORMATS)
                  and (HAN.search(r.get('current') or '') or '/lang/' in r['source']
                       or r.get('inventory_gap') or re.search(r'[A-Za-z]{2,}',r.get('current') or ''))})
    if not files:return ''
    shown='、'.join(files[:3])+('…' if len(files)>3 else '')
    return (f'有 {len(files):,} 個檔案可能含有玩家看得到的文字，但程式還不會讀這種格式，遊戲裡可能仍是英文或簡體'
            f'（例如 {shown}）。完整清單在下方明細的「無法確定是否顯示」分類；請把截圖或檔案名稱回報給開發者。')


IMAGE_BUTTON = re.compile(r'^\s*(?:source|backgroundnormal)\s*=\s*\[source:local\][^\n]*button[^\n]*\.(?:png|gif|apng|jpe?g)\s*$',re.M|re.I)
BUTTON_LABEL = re.compile(r'^\s*label\s*=\s*\S',re.M)


def inventory_note(session):
    """Incomplete reads are not silently treated as a clean scan."""
    info=session.get('text_inventory') or {};errors=[e for e in info.get('errors') or [] if not broken_inventory_file(e)]
    if not errors:return ''
    examples='、'.join(e['source'] for e in errors[:3])
    return (f'有 {len(errors):,} 項文字涵蓋檢查未完成（{examples}），這些內容沒有被此檢查證明已涵蓋。'
            '已完成的譯文照常保留；讀取原因已保存在本機報告。')


def image_menus(instance):
    """FancyMenu layouts that draw buttons with pictures and no text label (The Pixelmon Modpack: buttons/main_single.png).
    English painted in a picture is not text, so the report says so instead of leaving it to look like a gap."""
    found=[]
    for p in sorted((Path(instance)/'config/fancymenu/customization').glob('*.txt')):
        try:text=p.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        if any(IMAGE_BUTTON.search(block) and not BUTTON_LABEL.search(block) for block in text.split('element {')[1:]):
            found.append(p.name)
    return found


def mod_count(instance) -> int:
    """How many mod files a modpack folder holds (mods/*.jar); 0 when it cannot be read."""
    try:return sum(1 for _ in (Path(instance)/'mods').glob('*.jar'))
    except OSError:return 0


def image_text_note(session):
    """A grey report line: menu buttons that are pictures keep the English painted on them."""
    if not session.get('image_menus'):return ''
    return ('主選單由 FancyMenu 自訂，部分按鈕和說明是整合包作者畫好的圖片；圖片上的英文不是文字，程式無法翻譯，'
            '不算漏翻（例如 Pixelmon 主選單的 singleplayer、quit）。')


def unverified_note(session):
    """A grey report line for text written into files no reader covers (Audit.unverified_literals/unscanned):
    done, restorable, but no mod's code was checked to read them, so it is not counted in the completion rate."""
    rows=[r for r in session.get('rows',[]) if r.get('unverified') and r.get('installed') and r.get('changed')]
    if not rows:return ''
    files=len({r['source'] for r in rows})
    return (f'另外在 {files:,} 個程式還不認得的檔案裡，把 {len(rows):,} 句簡體轉成繁體或補上繁中語系檔；'
            '還沒確認遊戲會讀這些檔案，所以不算進中文化完成率，可在「備份與還原」還原。')


def report_overview(session):
    """What the player cares about first: applied, not applied (and why), worth checking, backup."""
    rows=session.get('rows',[])
    applied=session.get('installed_count',0)+session.get('recovered_count',0)
    reasons=[]
    missing=sum(r['origin']=='untranslated' and r['supported'] for r in rows)
    if missing:reasons.append((missing,'找不到中文來源'+('（可用 AI 補翻）' if not session.get('ai_translation') else '')))
    waiting=0 if session.get('status')=='restored' else applicable_count(session)
    if waiting:reasons.append((waiting,'已翻好但還沒寫入（'+('關閉遊戲後重試套用' if session.get('status') in ('awaiting_game','apply_failed') else '尚未套用')+'）'))
    for why,n in (session.get('held_back') or {}).items():reasons.append((n,'沒有寫入：'+why))
    # Program/config strings are candidates, not known gaps; they are reported beside, not inside, 未套用.
    groups=collections.Counter(categories(session))  # the same rows the report filters list
    held=groups['held'];context=groups['context']
    check=collections.Counter()
    for r in rows:
        if needs_check(r):
            check['數值和原文不同' if r.get('number_doubt')
                  else '名稱和地圖或原文不一致' if r.get('name_doubt') or r.get('map_word')
                  else '原文顯示格式已修正' if r.get('format_fixed')
                  else 'AI 改寫未通過檢查' if (r.get('ai_review') or {}).get('verdict')=='rejected'
                  else '版本待確認的參考']+=1
    after=session.get('after_counts')
    return dict(applied=applied,not_applied=reasons,context=context,held=held,check=sum(check.values()),check_kinds=check.most_common(),
                backup=session.get('backup'),rechecked=after is not None,renamed=session.get('renamed_count',0),
                recovered=session.get('recovered_count',0))


def names_in(names, text, limit=40):
    """Modpack item/block/... names mentioned in text (whole words, up to five words long)."""
    words=re.findall(r"[A-Za-z][A-Za-z'-]*",text or '');found={};used=set()
    for n in range(5,0,-1):
        for i in range(len(words)-n+1):
            if used.intersection(range(i,i+n)):continue  # 'Iron' inside a matched 'Iron Sword' is not a separate name
            hit=names.get(' '.join(words[i:i+n]).casefold())
            if hit:
                used.update(range(i,i+n))
                if hit[0] not in found:found[hit[0]]=hit[1]
            if len(found)>=limit:return found
    return found


def load_name_terms(session):
    """casefolded English -> (English, Chinese) for names decided in this run (see plan)."""
    try:data=json.loads((Path(session['report'])/'name_terms.json').read_text(encoding='utf-8'))
    except (OSError,ValueError,KeyError):return {}
    return {en.casefold():(en,zh) for en,zh in data.items()}


def unify_suggested_terms(session):
    """One-click: give every inconsistently named thing its suggested (most trusted) name.

    Rows keep the provenance of the variant they adopt and record what they replaced; nothing is
    written to the user's glossary, so the suggestion never overrides a later explicit choice.
    """
    changed=0
    for item in conflicting_terms(session,limit=None):
        en=item['en'].casefold();zh=item['suggested']
        rows=[r for r in session['rows'] if isinstance(english_of(r),str) and english_of(r).strip().casefold()==en
              and r.get('supported') and not r.get('installed') and NAME_KEY.match(r.get('key',''))
              and r['key'].split('.',2)[-1]==item['key_tail'] and r.get('origin') not in ('untranslated','keep_original')]
        model=next((r for r in rows if (r.get('proposed') or '').strip()==zh),None)
        if not model:continue
        for r in rows:
            if (r.get('proposed') or '').strip()==zh or not validate_text(english_of(r),zh):continue
            r.update(unified_from=r.get('proposed'),proposed=zh,origin=model['origin'],evidence=model.get('evidence'),
                     issue='已依其他模組統一譯名（原為「'+str(r.get('proposed'))+'」）',changed=zh!=r.get('current'))
            changed+=1
    session['terms_unified']=changed
    return changed


USER_ORIGINS = ('manual','translation_memory','user_glossary')
LATE_ORIGINS = ('ai_translation','stale_reference','cross_version_reference','glossary')  # below every other source


def shown_first(source):
    """Which file the game reads first for one key: KubeJS assets, then bundled packs, then the mod."""
    return 0 if source.startswith('instance!/kubejs/') else 1 if TRANSLATION_PACK.match(source) else 2


def same_key_groups(rows):
    """Rows that are the same text of the same mod in different files: (mod, key, English) -> rows."""
    groups=collections.defaultdict(list)
    for r in rows:
        ns=lang_namespace(r.get('source',''))
        if ns and ns!=QUEST_NAMESPACE and r.get('kind')=='language' and r.get('supported'):
            # A name the scan added under the namespace the mod registers with shares the name it was written under.
            twin=r.get('key_from_namespace')
            groups[(twin[0],twin[1],english_of(r)) if twin else (ns,r['key'],english_of(r))].append(r)
        elif r.get('kind')=='class_display' and r.get('supported'):
            # A config comment written twice in the mod's program (e.g. client and common config classes)
            # becomes one '<key>.tooltip' entry: both copies need the same wording to be written at all.
            jar=r['source'].split('!/')[0]
            for key,part,parts,_ in r.get('tooltips') or ():groups[(jar,f'{key}#{part}/{parts}',r.get('current'))].append(r)
    return groups


def unify_same_key(rows):
    """One translation per mod, language key and English text, in every file that carries the key.

    A modpack often holds the same key three times: in the mod, in a bundled language pack and in
    KubeJS assets. The game shows the topmost file, so differing translations would hide the better
    one. The most trusted translation is used for all of them; what the user confirmed stays.
    Returns how many rows changed.
    """
    changed=0
    for (_,_,english),group in same_key_groups(rows).items():
        if len(group)<2 or len({r['proposed'] for r in group})<2:continue
        decided=[r for r in group if r.get('origin') not in ('untranslated','keep_original','pending','not_display')
                 and HAN.search(r.get('proposed') or '')]
        if not decided:continue
        best=min(decided,key=lambda r:(trust_rank(r),shown_first(r['source'])))
        for r in group:
            if r is best or r['proposed']==best['proposed']:continue
            if r.get('origin') in USER_ORIGINS or str(r.get('review_method') or '').startswith('user_confirmed'):continue
            if r.get('origin')=='keep_original':continue  # shown as it is on purpose
            if not fits(original_of(r),best['proposed'],best.get('own_lines')):continue
            for field in ('recovered','installed','review_method','auto_review_reason','number_doubt','unified_from','ai_model','ai_reused','ai_redo','ai_review','own_lines'):
                r.pop(field,None)
            r.update(proposed=best['proposed'],origin=best['origin'],evidence=best.get('evidence'),issue=best.get('issue') or '',
                     changed=best['proposed']!=r.get('current'),reviewed=False,same_key_as=best['source'])
            for field in ('number_doubt','ai_model','ai_reused','ai_redo','unified_from','own_lines'):
                if best.get(field) is not None:r[field]=best[field]
            changed+=1
    return changed


def singular_names(rows):
    """A structure group the scan named from its id (minecraft:pillager_outposts, atmospheric:kousa_sanctums) and found
    no Chinese for takes the name of the structure it is the plural of; Explorer's Compass shows both, as 名稱 and 團體.
    Returns how many rows changed."""
    named={r['key']:r for r in rows if r.get('kind')=='language' and r.get('origin') not in ('untranslated','keep_original')
           and HAN.search(r.get('proposed') or '')}
    changed=0
    for r in rows:
        if not (r.get('name_from_id') and r.get('origin')=='untranslated' and r['key'].startswith('structure.')):continue
        key=r['key']
        twin=next((named[k] for k in (key[:-3]+'y' if key.endswith('ies') else None,key[:-2] if key.endswith('es') else None,
                                      key[:-1] if key.endswith('s') else None) if k in named),None)
        if not twin or not validate_text(original_of(r),twin['proposed']):continue
        r.update(proposed=twin['proposed'],origin=twin['origin'],evidence=twin.get('evidence') or '',
                 issue=f'結構分組沿用「{english_of(twin) or twin["key"]}」的譯名'+('；'+twin['issue'] if twin.get('issue') else ''),
                 changed=twin['proposed']!=r.get('current'),plural_of=twin['key'])
        for field in ('number_doubt','ai_model'):
            if twin.get(field) is not None:r[field]=twin[field]
        changed+=1
    return changed


# Biome names whose Mojang zh_cn, converted, differs from the zh_tw the minimap and F3 show (1.20.1 / 1.21.1). A
# structure or biome name whose English has the biome (Savanna Village) takes the map's word (CTOV's own zh_tw:
# 熱帶草原村莊 → 莽原村莊). Only inside such names: 熱帶草原 and 溶洞 are ordinary words elsewhere.
MAP_BIOME_WORDS = (
    ('savanna', ('熱帶草原', '稀樹草原'), '莽原'), ('windswept', ('風襲',), '風蝕'), ('mushroom fields', ('蘑菇島',), '蘑菇地'),
    ('dripstone caves', ('溶洞',), '鐘乳石洞窟'), ('deep dark', ('深暗之域',), '深淵'), ('lush caves', ('繁茂洞穴',), '蒼鬱洞窟'),
    ('warped forest', ('詭異森林',), '扭曲森林'), ('soul sand valley', ('靈魂沙峽谷',), '靈魂砂谷'),
)
# Biome names too common as plain words to hold a name to (Quest Grove is a grove, Ocean Ruin is 海底廢墟 in zh_tw).
PLAIN_BIOME_WORDS = {'grove','ocean','river','the end','the void','forest','beach','meadow','desert','plains','jungle'}


# The game's own structures inside mods' names, under the zh_tw names the compass shows for the game's own (Repurposed
# Structures: 林地府邸（白樺）beside 綠林府邸), by the id of the name (its English is often missing).
VANILLA_WORDS = ((r'mansion',('林地府邸',),'綠林府邸'),(r'mineshaft',('廢棄礦井','廢棄礦坑'),'礦坑'),(r'bastion',('堡壘遺跡',),'堡壘遺蹟'),
                 (r'jungle_(?:temple|pyramid)',('叢林神廟',),'叢林遺跡'),(r'end_?city',('終界城',),'終末都市'))
# Character forms Taiwan's official zh_tw does not use (岩, 床; see desktop_references.TAIWAN_FORMS).
NAME_FORMS = str.maketrans({'巖':'岩','牀':'床'})


def map_wording(key, en, value):
    """(name, why) with the words the map and the compass show for the game's own biomes and structures; the name
    as it was and '' when nothing applies."""
    from .desktop_references import VANILLA_STRUCTURE_NAMES
    path=key.split('.',2)[2] if key.count('.')>=2 else ''
    # Two words and more: a mod's Monument or Fortress is its own (Meadow's Monument is 紀念碑, not 海底遺跡).
    same=re.sub(r'[^a-z0-9]+','_',(en or '').casefold()).strip('_')
    vanilla=VANILLA_STRUCTURE_NAMES.get(same) if key.startswith('structure.') and '_' in same else None
    if vanilla and value!=vanilla:return vanilla,'和原版同名的結構改用官方名稱'
    fixed=value.translate(NAME_FORMS);why=[] if fixed==value else ['改用台灣字形']
    for word,others,shown in MAP_BIOME_WORDS:
        if isinstance(en,str) and has_word(word,en) and shown not in fixed and any(o in fixed for o in others):
            for o in others:fixed=fixed.replace(o,shown)
            why.append('生態域改用地圖上的名稱')
    if key.startswith('structure.'):
        for pattern,others,shown in VANILLA_WORDS:
            if re.search(pattern,path) and shown not in fixed and any(o in fixed for o in others):
                for o in others:fixed=fixed.replace(o,shown)
                why.append('原版結構改用官方名稱')
    return fixed,'、'.join(dict.fromkeys(why))


def map_biome_names(vanilla):
    """English biome name (casefolded) -> the zh_tw name the game shows on the map, from Mojang's language files."""
    if not vanilla:return {}
    shown={z for k,z in vanilla.get('minecraft',{}).items() if k.startswith('biome.minecraft.')}
    return {en:zh for en,zh in vanilla.get('__terms__',{}).items() if zh in shown}


def same_place(a, b):
    """Whether two English names are one place written two ways (Arch / Arches, Fortress / Fotress, End City / Endcity)."""
    def norm(text):
        words=re.findall(r'[a-z]+',(text or '').lower())
        return ''.join(w[:-3]+'y' if w.endswith('ies') else w[:-2] if w.endswith(('ches','shes','sses')) else w[:-1] if w.endswith('s') and len(w)>3 else w for w in words)
    a,b=norm(a),norm(b)
    return a==b or difflib.SequenceMatcher(None,a,b).ratio()>=0.85


def repeated_names(rows, only=None):
    """Different places of one mod given the same Chinese name (Nature's Spirit's own zh_tw names Cypress Fields, Tropical
    Woods and Sparse Tropical Woods all 檜木森林, while its zh_cn tells them apart): the compass and the map would show
    two places as one. Where the mod's own Simplified Chinese differs, that is used (converted); the rest is listed as a
    doubt (name_doubt) for AI to check. Returns how many rows changed or were marked."""
    groups=collections.defaultdict(list)
    for r in rows:
        if (r.get('kind')=='language' and REGISTRY_KEY.match(r.get('key','')) and isinstance(english_of(r),str)
                and HAN.search(r.get('proposed') or '') and r.get('origin') not in USER_ORIGINS+('official_vanilla','keep_original','untranslated')
                and not str(r.get('review_method') or '').startswith('user_confirmed')):
            groups[(lang_namespace(r['source']),r['key'].split('.')[0],r['proposed'].strip())].append(r)
    marked=0
    for (_,_,name),group in groups.items():
        if len(group)<2:continue
        for r in group:
            if only is not None and id(r) not in only:continue
            if all(same_place(english_of(r),english_of(o)) for o in group if o is not r):continue
            own=taiwan_wording(to_taiwan(r['zh_cn'])) if isinstance(r.get('zh_cn'),str) and HAN.search(r['zh_cn']) else None
            if own and own!=name and fits(original_of(r),own,False):
                r.update(previous_origin=r['origin'],previous_proposed=r['proposed'],proposed=own,origin='same_source_zh_cn',evidence=r['source'],
                         issue=f'模組繁中把不同的地方都寫成「{name}」，改用模組簡中轉繁，請核對',changed=own!=r.get('current'))
                if r['changed']:r.pop('installed',None);r.pop('recovered',None)
            else:
                others='、'.join(f'「{english_of(o)}」' for o in group if o is not r and not same_place(english_of(r),english_of(o)))
                r['name_doubt']=(r.get('name_doubt') or [])+[f'同模組的{others}也叫「{name}」']
                r['issue']=(r['issue']+'；' if r.get('issue') else '')+f'同模組的{others}也叫「{name}」，請核對'
            marked+=1
    return marked


def has_word(word, text):
    return bool(re.search(r'(?<![A-Za-z])'+re.escape(word)+r'(?![A-Za-z])',text or '',re.I))


def name_doubts(rows, ai_memory=None, biomes=None, only=None):
    """Biome, structure and dimension names (what the compasses and the map waypoints they add show) checked once more:

    - a biome the English names is written the way the map shows it (Savanna → 莽原); a known other wording is replaced;
    - an English word of the original left in the Chinese (CTOV's own Alpine村莊, an AI's Kousa 聖所 where the same
      mod's blocks say 棶木) is listed with how the same mod translates that word elsewhere;
    - a biome the Chinese names differently from the map is listed with the map's word.
    Listed names are doubts AI may check (codex_bridge.doubt_rows). A name AI already read and kept is not listed again,
    and one it rewrote takes that answer again. Returns how many rows were marked or corrected."""
    biomes=biomes or {}
    by_mod=collections.defaultdict(list);own_biomes={}
    for r in rows:
        if r.get('kind')=='language' and isinstance(english_of(r),str) and HAN.search(r.get('proposed') or ''):
            by_mod[lang_namespace(r.get('source',''))].append(r)
            if r['key'].startswith('biome.'):own_biomes[(r['key'].split('.')[1],english_of(r).strip().casefold())]=r['proposed'].strip()
    marked=0
    for r in rows:
        en=english_of(r);value=r.get('proposed') or ''
        if only is not None and id(r) not in only:continue
        if (r.get('kind')!='language' or not REGISTRY_KEY.match(r.get('key','')) or not HAN.search(value)
                or r.get('origin') in USER_ORIGINS+('untranslated','keep_original','official_vanilla')
                or str(r.get('review_method') or '').startswith('user_confirmed')):continue
        fixed,why=map_wording(r['key'],en,value)
        if fixed!=value and fits(original_of(r),fixed,r.get('own_lines')):
            r.update(proposed=fixed,changed=fixed!=r.get('current'),map_word=True,
                     issue=(r['issue']+'；' if r.get('issue') else '')+f'{why}（原為「{value}」），請核對')
            if r['changed']:r.pop('installed',None);r.pop('recovered',None)
            value=fixed;marked+=1
        if not isinstance(en,str):continue
        notes=[]
        words=[w for w in dict.fromkeys(re.findall(r'[A-Za-z]{3,}',value))
               if not w.isupper() and has_word(w,en) and not keep_original_reason(w)]
        ns=lang_namespace(r.get('source',''))
        if words:
            hints=[]
            for w in words:
                other=next((o for o in by_mod[ns] if o is not r and has_word(w,english_of(o)) and not has_word(w,o['proposed'])
                            and not REGISTRY_KEY.match(o['key'])),None)
                if other:hints.append(f'同模組的「{english_of(other)}」譯為「{other["proposed"]}」')
            notes.append('名稱留有英文「'+'、'.join(words)+'」'+('，'+'；'.join(hints) if hints else ''))
        own=taiwan_wording(to_taiwan(r['zh_cn'])) if isinstance(r.get('zh_cn'),str) and HAN.search(r['zh_cn']) else ''
        if (own and r.get('origin') not in ('ai_translation','same_source_zh_cn','instance_zh_cn')
                and difflib.SequenceMatcher(None,own,value).ratio()<0.34):
            # The mod's zh_tw and zh_cn name two different things (Nature's Spirit: Arid Highlands 高嶺土 / 高原旱地).
            notes.append(f'模組簡中寫作「{own}」，和繁中意思不同')
        # Structures only: a mod's own biome is itself what the map shows (Twilight Forest's Dark Forest is 黑暗森林).
        rest=en.casefold() if r['key'].startswith('structure.') else ''
        for biome in sorted(biomes,key=len,reverse=True):
            if biome in PLAIN_BIOME_WORDS or not has_word(biome,rest):continue
            rest=re.sub(r'(?<![a-z])'+re.escape(biome)+r'(?![a-z])',' ',rest)  # Snowy Taiga is not checked as Taiga too
            # The map shows the biome's own name: a mod's biome of that name (Twilight Forest's Dark Forest, 黑暗森林) or the game's.
            shown=own_biomes.get((r['key'].split('.')[1],biome)) or biomes[biome]
            if shown not in value:notes.append(f'地圖上的「{biome.title()}」顯示為「{shown}」')
        if not notes:continue
        if ai_memory is not None and ai_memory.checked(ns,r['key'],en)==value:continue
        earlier=ai_memory.lookup(ns,r['key'],en) if ai_memory is not None else None
        fixed=earlier.get('text') if earlier and not earlier.get('keep') else None
        if (isinstance(fixed,str) and fixed!=value and HAN.search(fixed) and validate_text(en,fixed)
                and not any(has_word(w,fixed) for w in words)):
            # AI rewrote this name in an earlier run (see codex_bridge.review); its answer is used again, not asked for again.
            r.update(previous_origin=r['origin'],previous_proposed=value,proposed=fixed,origin='ai_translation',
                     evidence='ChatGPT/Codex: '+str(earlier.get('model') or '')+'（沿用先前的核對）',ai_model=earlier.get('model'),
                     ai_reused=True,issue=f'AI 依疑點改寫（原為「{value}」），尚未人工校對。',changed=fixed!=r.get('current'))
            r.pop('installed',None);r.pop('recovered',None)
            marked+=1;continue
        r['name_doubt']=(r.get('name_doubt') or [])+notes
        r['issue']=(r['issue']+'；' if r.get('issue') else '')+'；'.join(notes)+'，請核對'
        marked+=1
    return marked


def check_ai_names(session, rows, ai_memory=None):
    """Names AI has just written (codex_bridge.supplement) get the checks names from other sources had in plan: the map's
    words, two places under one name, English left in. Doubts found go to the AI check that follows."""
    names=[r for r in rows if REGISTRY_KEY.match(r.get('key','')) and r.get('origin')=='ai_translation']
    if not names:return 0
    keys={id(r) for r in names}
    for r in names:r.pop('name_doubt',None)
    return (repeated_names(session['rows'],only=keys)
            +name_doubts(session['rows'],ai_memory,session.get('map_biomes'),only=keys))


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


def translated_instances(home):
    try:return json.loads((Path(home)/'translated_instances.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def record_translated(home, instance):
    """Remember which modpack version was translated, to notice when a launcher update replaces the files."""
    from .patches import instance_identity
    identity=instance_identity(Path(instance));data=translated_instances(home)
    data[str(Path(instance).resolve()).casefold()]=dict(path=str(Path(instance).resolve()),name=identity['name'],
        fileID=identity['fileID'],version=identity['version'],translated=datetime.now().isoformat(timespec='seconds'))
    write_json(Path(home)/'translated_instances.json',data)


def outdated_translations(home):
    """Translated modpacks whose installed version changed since (a CurseForge update replaces the mod files)."""
    from .patches import instance_identity
    found=[]
    for key,record in translated_instances(home).items():
        path=Path(record.get('path',''))
        if not record.get('fileID') or not is_instance(path) or record.get('dismissed')==instance_identity(path)['fileID']:continue
        now=instance_identity(path)
        if now['fileID'] and now['fileID']!=record['fileID']:
            found.append(dict(key=key,path=str(path),name=now['name'],old_version=record.get('version',''),new_version=now['version'],fileID=now['fileID']))
    return found


def dismiss_outdated(home, key, fileID):
    data=translated_instances(home)
    if key in data:data[key]['dismissed']=fileID;write_json(Path(home)/'translated_instances.json',data)


def total_memory_mb() -> int:
    """This computer's physical memory in MB; 0 when Windows does not say."""
    try:
        import ctypes
        class Status(ctypes.Structure):
            _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),('ullTotalPhys',ctypes.c_ulonglong),
                      ('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),
                      ('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
        status=Status();status.dwLength=ctypes.sizeof(Status)
        return int(status.ullTotalPhys//(1024*1024)) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0
    except (AttributeError,OSError,ValueError):return 0


def curseforge_instances():
    """CurseForge's own instance list, which also covers a moved or custom instance folder.

    Returns dicts with name, path, projectID, fileID and gameVersion; projectID/fileID are 0
    for instances the user created by hand.
    """
    from .full_pack import curseforge_list, configured_curseforge_root
    listing=curseforge_list()
    try:
        data=json.loads(listing.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):
        data=[]
    result=[];seen=set();roots={Path.home()/'curseforge/minecraft/Instances'}
    configured=configured_curseforge_root(listing)
    if configured:roots.add(configured)
    def add(x,path):
        result.append(dict(name=x.get('name') or path.name,path=path,projectID=int(x.get('projectID') or 0),
                           fileID=int(x.get('fileID') or 0),gameVersion=x.get('gameVersion') or ''))
        seen.add(str(path).rstrip('\\/').casefold())
    for x in data if isinstance(data,list) else []:
        try:
            path=Path(x['installPath']);roots.add(path.parent)
            if is_instance(path):add(x,path)
        except (KeyError,TypeError,ValueError,OSError):
            continue
    # CurseForge writes that list some time after a modpack finishes installing (seen: not within
    # 90 seconds), so a modpack it just installed is found from the instance's own record instead.
    for root in roots:
        try:children=list(root.iterdir()) if root.is_dir() else []
        except OSError:continue
        for path in children:
            if str(path).rstrip('\\/').casefold() in seen:continue
            try:
                x=json.loads((path/'minecraftinstance.json').read_text(encoding='utf-8-sig'))
                if isinstance(x,dict) and is_instance(path):add(x,path)
            except (OSError,ValueError,TypeError):
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


MOD_ID = re.compile(r"""(?m)^\s*modId\s*=\s*["']([^"']+)["']""")


def declared_mod_ids(toml):
    """The mod ids a mods.toml declares in its [[mods]] tables. The modId lines under
    [[dependencies.x]] name other mods it needs (often optional ones that are not installed)."""
    try:
        import tomllib
        return [str(m['modId']) for m in tomllib.loads(toml).get('mods') or [] if isinstance(m,dict) and m.get('modId')]
    except (ValueError,TypeError,KeyError,AttributeError):
        ids=[];section=''
        for line in toml.splitlines():
            head=re.match(r'\s*\[\[?\s*([^\]]+?)\s*\]\]?',line)
            if head:section=head[1]
            elif section=='mods':ids+=MOD_ID.findall(line)
        return ids


def version_key(text):
    """A version string as numbers to compare (5.6.2 > 5.5.4, 1.10 > 1.9); words are left out."""
    return tuple(int(n) for n in re.findall(r'\d+',text or ''))


def older_copies(instance, jars):
    """Mod files the game does not load because a newer copy of the same mod sits beside them.

    Forge and NeoForge keep the most recent version when two files declare the same mod id
    (UniqueModListBuilder), so only that copy's text is shown. Translating both wrote the two copies' wording
    into the same language file in turn, and every run changed it again (Elemental Awakening has IMBlocker
    5.5.4 and 5.6.2). The version is the mods.toml one, the jar manifest's when the toml leaves it to the jar,
    else the file name's.
    """
    copies=collections.defaultdict(list)
    for jar in sorted(jars):
        try:
            with zipfile.ZipFile(contained(instance,jar)) as z:
                names=set(z.namelist())
                toml=next((z.read(n).decode('utf-8','replace') for n in ('META-INF/neoforge.mods.toml','META-INF/mods.toml') if n in names),'')
                ids=declared_mod_ids(toml) if toml else []
                if not ids:continue
                version=re.search(r"""(?m)^\s*version\s*=\s*["']([^"']+)["']""",toml)
                version=version[1] if version else ''
                if not version_key(version) and 'META-INF/MANIFEST.MF' in names:
                    m=re.search(r'(?m)^Implementation-Version:\s*(\S+)',z.read('META-INF/MANIFEST.MF').decode('utf-8','replace'))
                    version=m[1] if m else ''
        except (OSError,zipfile.BadZipFile,ValueError):continue
        copies[ids[0]].append((version_key(version) or version_key(Path(jar).stem),jar))
    return {jar for found in copies.values() if len(found)>1 for _,jar in sorted(found)[:-1]}


def present_mods(z, depth=0):
    """Namespaces whose text the game can show: a mod the jar declares, or one it holds language files
    or world generation for. Textures or recipes added for another mod (compatibility files) do not
    make that mod installed."""
    names=z.namelist();found=set()
    for name in names:
        m=re.match(r'assets/([^/]+)/lang/[^/]+\.(?:json|lang)$|data/([^/]+)/worldgen/',name)
        if m:found.add(m[1] or m[2])
    for meta in ('META-INF/neoforge.mods.toml','META-INF/mods.toml'):
        if meta in names:found|=set(declared_mod_ids(z.read(meta).decode('utf-8','replace')))
    if 'fabric.mod.json' in names:
        # strict=False: some hold raw line breaks inside strings (Cobblemon Additions), which Fabric accepts.
        try:found.add(str(json.loads(z.read('fabric.mod.json').decode('utf-8-sig'),strict=False)['id']))
        except (ValueError,KeyError,TypeError):pass
    if depth<2:
        for name in names:
            if not name.lower().endswith('.jar'):continue
            try:
                with zipfile.ZipFile(io.BytesIO(z.read(name))) as inner:found|=present_mods(inner,depth+1)
            except (zipfile.BadZipFile,OSError,RuntimeError):continue
    return found


# scan-10: lone surrogates mended (v0.17.0 left cached errors in place)
# scan-11: strings of language-file generators (LanguageProvider) are marked; Mixin targets are kept
# scan-12: plain Chinese literals (plain_literal) are marked for an in-place Simplified-to-Traditional conversion
# scan-13: a jar's installed mods are its [[mods]] ids only, not the mods it lists as dependencies
# scan-14: language rows of a mod drawing with its own font without Chinese glyphs are marked (no_chinese_font)
# scan-18: words data packs show as written (structures, functions, loot tables: embedded_text)
# scan-17: program text followed through helper methods and fields (JarFlow); keys a mod's program asks for (extra_keys)
# scan-19: keys data files name (data_keys), FancyMenu English, shader packs, bestiary/codex/inline books, more quest
#          formats (DATA_TEXT_FORMATS), resource text no reader covers (unsupported_assets)
# scan-20: data sentence keys retain their exact JSON position for independent coverage checks
# scan-21: VillagerConfig trades and plain-string set_name / set_lore, REI custom group names, owo rich language listed
# scan-22: Supplementaries flute song names are not listed as unsupported data (only a key and a file name)
# scan-23: book pages the author wrote out only in Simplified Chinese follow the Chinese pages (cn_shape)
# scan-24: owo rich language pieces are rows (rich); resource-read text files (RESOURCE_TEXTS); single-word data keys; Konkrete locals
# scan-25: a Chinese book shape only for paragraphs the English has no place for; stand-in English kept for coverage
SCAN_CACHE_VERSION = 'scan-25'


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
            audit.installed_namespaces|=set(data['namespaces']);audit.present_mods|=set(data['mods']);audit.cache_hits+=1
            audit.mixin_targets|=set(data['mixin']);audit.registry.extend(data['registry']);audit.extra_keys.extend(data['extra_keys'])
            return key
        except (OSError,ValueError,KeyError):path.unlink(missing_ok=True)
    marks=(len(audit.rows),len(audit.files),len(audit.errors),len(audit.repairs),len(audit.registry),len(audit.extra_keys))
    before=collections.Counter(audit.counts)
    targets=set(audit.mixin_targets);audit.mixin_targets=set()
    audit.archive(p,label)
    mixin=audit.mixin_targets;audit.mixin_targets=targets|mixin
    namespaces=set();mods=set()
    if Path(label).parts[0] in ('mods','datapacks'):
        try:
            with zipfile.ZipFile(p) as z:
                namespaces=asset_namespaces(z)
                mods=present_mods(z) if Path(label).parts[0]=='mods' else namespaces  # a datapack declares no mod
        except (OSError,zipfile.BadZipFile):pass
    audit.installed_namespaces|=namespaces;audit.present_mods|=mods
    if path:
        delta=collections.Counter(audit.counts);delta.subtract(before)
        data=dict(rows=audit.rows[marks[0]:],files=audit.files[marks[1]:],errors=audit.errors[marks[2]:],
                  repairs=audit.repairs[marks[3]:],counts={k:v for k,v in delta.items() if v},namespaces=sorted(namespaces),mods=sorted(mods),
                  mixin=sorted(mixin),registry=audit.registry[marks[4]:],extra_keys=audit.extra_keys[marks[5]:])
        try:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(gzip.compress(json.dumps(data,ensure_ascii=False).encode('utf-8'),5))
        except OSError:pass
    return key


def generated_copy(path):
    """A mod file a loader made on this computer from another one in mods/ (Sinytra Connector's
    mods/.connector/*_mapped_*.jar): the original holds the same text, and other computers make their own."""
    return any(part.startswith('.') for part in PurePosixPath(path).parts[:-1])


# Resource packs the Paxi mod loads (VEFV2.7.1 keeps its translation packs there, among them a compass structure
# translation in Simplified Chinese for 1,901 structures). Read as references only: they are the modpack author's files.
PAXI_PACKS = 'config/paxi/resourcepacks'
# "[地牢浮现之时]飞艇(Small Blimp)": a translation pack's mod name in front and the English after; the name is in between.
DECORATED_NAME = re.compile(r'^\s*(?:\[[^\]]{1,40}\]\s*)?(.+?)\s*(?:[(（]([^()（）]*[A-Za-z][^()（）]*)[)）])?\s*$')


def plain_name(key, text, english=None):
    """A biome, structure or dimension name from a translation pack without the decoration around it ("[模組]名稱(English)"),
    its number written as the English writes it (縈風教堂_0 → 縈風教堂 0). None when the English it is tagged with is
    another name: the compass pack translated only the last part of some (Ice Maze Common is tagged (Common), 常見)."""
    if not REGISTRY_KEY.match(key or '') or not isinstance(text,str):return text
    m=DECORATED_NAME.match(text)
    if not m or not HAN.search(m[1]):return text
    if m[2] and isinstance(english,str):
        words=lambda s:sorted(re.findall(r'[a-z0-9]+',s.casefold()))
        if words(m[2])!=words(english) and not same_place(m[2],english):return None
    return re.sub(r'_(\d+)$',r' \1',m[1])


def scan(instance, report, notify, cancelled, cache=None, details='compressed'):
    audit = Audit(report/'audit',{});audit.cache_hits=0;used=set()
    audit.source_hashes={}
    archives=[]
    # shaderpacks/: a shader pack's option names (shaders/lang/*.lang), which Iris and Oculus show in the game's language.
    for folder in ('mods','resourcepacks','datapacks','config/openloader',PAXI_PACKS,'shaderpacks')+CONTENT_PACK_FOLDERS:
        for p in (instance/folder).rglob('*'):
            if p.suffix.lower() in ('.jar','.zip') and p.is_file() and not generated_copy(p.relative_to(instance).as_posix()):
                contained(instance,p.relative_to(instance).as_posix())
                archives.append(p)
    audit.installed_namespaces={'minecraft','realms','c','forge','neoforge','fabric'}
    audit.present_mods=set(audit.installed_namespaces)
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
    if kubejs.is_dir():
        audit.installed_namespaces|={p.name for p in kubejs.iterdir() if p.is_dir()}
        audit.present_mods|={p.name for p in kubejs.iterdir() if p.is_dir()}
    notify(42,'掃描任務、設定與腳本','正在檢查外部文字和程式字串候選')
    for folder in LOOSE_FOLDERS+CONTENT_PACK_FOLDERS:
        for p in (instance/folder).rglob('*'):
            if p.is_file() and p.suffix.lower() not in ('.zip','.jar'):
                contained(instance,p.relative_to(instance).as_posix())
                audit.source_hashes[p.relative_to(instance).as_posix()]=file_hash(p)
    audit.loose(instance)
    audit.missing_keys()  # keys a mod's program asks for that its language files miss
    audit.missing_names(audit.present_mods)  # biome, structure and dimension names no language file has
    # A reader finding two strings in a file does not prove it covered the rest.
    # Independent enumeration is diagnostic only: it grants no write or AI permissions.
    from . import text_inventory
    notify(44,'檢查文字涵蓋範圍','核對尚未產生條目的文字位置，包含短名稱與按鈕')
    inventory=text_inventory.reconcile(text_inventory.collect(instance,cancelled,
        lambda name:notify(44,'檢查文字涵蓋範圍',name),
        cache=cache/'text-inventory' if cache else None,source_hashes=audit.source_hashes),audit.rows)
    audit.text_inventory=inventory
    with gzip.open(report/'text-inventory.json.gz','wt',encoding='utf-8',compresslevel=3) as f:
        json.dump(inventory if details!='summary' else {k:v for k,v in inventory.items() if k!='candidates'},
                  f,ensure_ascii=True)
    for item in inventory['candidates']:
        if item['state']!='uncovered':continue
        audit.add(item['source'],item['key'],None,item['text'],kind='unsupported_config_text')
        audit.rows[-1]['inventory_gap']=True
        audit.counts['inventory_uncovered']+=1
    for r in audit.rows:
        # Files read outside the folders above (Audit.unscanned) are written too: record them so a change is noticed.
        name=r['source'].removeprefix('instance!/')
        if '!/' not in name and name not in audit.source_hashes and (instance/name).is_file():
            audit.source_hashes[name]=file_hash(contained(instance,name))
    # The report keeps every row it needs in session.json; the scan's own lists are for diagnosis.
    audit.finish(details=details,quiet=True)
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
                    '一鍵流程會自動檢查並套用合格譯文；不需逐筆人工確認，檔案檢查不代表遊戲內實測。'])
    def publish():
        write_json(report/'session.json',result)
        checkpoint(result)
    publish()
    try:
        audit=scan(instance,report,notify,cancelled,scan_cache(home,instance))
    except Exception as exc:
        result.update(status='cancelled' if isinstance(exc,InterruptedError) else 'blocked')
        result['errors'].append(['掃描',explain_error(exc)])
        publish()
        return result
    result['audit_counts']=dict(audit.counts)
    result['source_hashes']=audit.source_hashes
    result['text_inventory']={k:v for k,v in audit.text_inventory.items() if k!='candidates'}
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
        result.update(status='cancelled' if isinstance(exc,InterruptedError) else 'blocked',errors=result['errors']+[['參考庫預檢',explain_error(exc)]])
        publish()
        return result
    result['rows']=[]
    result['status']='matching'
    # The translation resource pack written earlier: what the game shows for the mod rows it covers.
    OWN_PACK=RESOURCE_PACK_FILE+'!/';pack_text={}
    for r in audit.rows:
        if r['source'].startswith(OWN_PACK) and r['kind'] in ('language','book','inline_lang') and isinstance(r['current'],str):
            pack_text[(r['source'][len(OWN_PACK):],r['key'])]=r['current']
    # Data files a mod shows as written (DATA_TEXT): the game reads the copy highest up, OpenLoader's packs above
    # the datapacks folder above the mods; the other copies are not shown. Our data pack is above them all, so its
    # copy is what the game shows, as long as it was built from the original that is there now.
    OWN_DATA=tuple(f+'!/' for f in DATA_PACK_FILES);data_reader={}
    for r in audit.rows:
        if r['kind']!='data_text' or r['source'].startswith(OWN_DATA):continue
        rank=(0 if 'config/openloader/' in r['source'] else 1 if r['source'].removeprefix('instance!/').startswith('datapacks/') else 2,r['source'])
        resource=data_resource(r)
        if resource and (resource not in data_reader or rank<data_reader[resource]):data_reader[resource]=rank
    data_reader={k:v[1] for k,v in data_reader.items()}
    data_loader=reads_data_packs(instance);data_files,data_records=read_data_pack(instance);data_shown={}
    for resource,source in data_reader.items() if data_loader else ():
        record=data_records.get(resource)
        if not isinstance(record,dict) or record.get('source')!=source or resource not in data_files:continue
        raw=data_original(instance,source)
        if raw is None or hashlib.sha256(raw).hexdigest()!=record.get('sha256'):continue  # the mod changed: built again
        try:data_shown[resource]=parse(data_files[resource])
        except ValueError:continue
    curseforge=is_curseforge(instance);mixin=getattr(audit,'mixin_targets',set())
    # Kept in the report so a later 'retry apply' still knows which program text must not be rewritten.
    result['mixin_targets']=sorted({class_name(r) for r in audit.rows if r['kind']=='class_display' or r.get('plain_literal')}&mixin)
    result['image_menus']=image_menus(instance)
    instance_cn={}
    for r in audit.rows:
        if r['kind']!='language' or not isinstance(r['zh_cn'],str): continue
        m=re.search(r'assets/([^/]+)/lang/',r['source'])
        if m and (r['source'].startswith('instance!/kubejs/assets/') or r['source'].startswith(('config/openloader/',PAXI_PACKS+'/'))):
            instance_cn.setdefault((m[1],r['key']),[]).append((r['source'],r['zh_cn']))
            # Language keys are global: a compass translation pack names every mod's structures in its own file.
            named=REGISTRY_KEY.match(r['key']) and r['key'].split('.')[1]
            if named and named!=m[1]:instance_cn.setdefault((named,r['key']),[]).append((r['source'],r['zh_cn']))
    # Every row of a key reads this list in the same order (the modpack's own KubeJS text first), its own
    # file included; leaving the own file out made two files each take the other's wording.
    for found in instance_cn.values():found.sort(key=lambda x:not x[0].startswith('instance!/kubejs/'))
    # Translation resource packs installed in this modpack (often community work) come before
    # online references; zh_tw is used as-is and zh_cn is converted to Taiwan wording.
    instance_rp_tw={};instance_rp_cn={}
    for r in audit.rows:
        m=re.search(r'assets/([^/]+)/lang/',r['source'])
        if r['kind']!='language' or not m or not re.match(r'(?:instance!/)?resourcepacks/',r['source']) or r['source'].startswith(OWN_PACK):continue
        if isinstance(r['current'],str) and HAN.search(r['current']):
            instance_rp_tw.setdefault((m[1],r['key']),[]).append((r['source'],r['current']))
        if isinstance(r['zh_cn'],str) and HAN.search(r['zh_cn']):
            instance_rp_cn.setdefault((m[1],r['key']),[]).append((r['source'],r['zh_cn']))
    # Text of embedded (jar-in-jar) libraries is applied as KubeJS assets, which the game shows instead
    # of the library's own file; that is the text currently in effect for those rows.
    kubejs_tw={}
    for r in audit.rows:
        m=re.match(r'instance!/kubejs/assets/([^/]+)/lang/',r['source'])
        if m and r['kind']=='language' and isinstance(r['current'],str):kubejs_tw[(m[1],r['key'])]=r['current']
    counts=collections.Counter()
    memory=TranslationMemory(home);ai_memory=AiMemory(home);user_terms=UserGlossary(home);provenance=Provenance(home,instance);special=collections.Counter()
    # The mods' own English, to notice strings a modpack renamed through KubeJS or resource packs.
    name_terms={}  # English name -> (trust rank, Chinese); given to AI so sentences use the same names
    mod_en={};main_copy=set();screen_keys=set();lang_text=set()
    tw_lines=collections.Counter();tw_chinese=collections.Counter()  # how much of each mod's own zh_tw is Chinese (author_kept)
    # Strings some mod's program holds: a file no reader covers may hold one a mod compares with or looks up.
    program_text={r['current'].strip() for r in audit.rows if r['kind'] in ('class_candidate','class_display') and isinstance(r['current'],str)}
    file_names={}  # the modpack's file names, read once when a config string names a file (original_file_name)
    for r in audit.rows:
        if r['kind']=='language' and '/lang/' in r['source'] and not SERVER_LANG.search(r['source'].split('!/')[-1]):screen_keys.add(r['key'])
        if r['kind']=='language' and r['source'].startswith('mods/'):
            lang_text.update((r['source'].rsplit('!/',1)[0],v.strip()) for v in (r['en'],r['zh_cn'],r['current']) if isinstance(v,str))
        if r['kind']=='language' and r['source'].startswith('mods/') and r['source'].split('!/')[-1].startswith('assets/'):
            main_copy.add((r['source'].split('!/')[0],lang_namespace(r['source']),r['key']))
        m=re.search(r'assets/([^/]+)/lang/',r['source'])
        if m and r['kind']=='language' and r['source'].startswith('mods/') and isinstance(r['en'],str):
            mod_en.setdefault((m[1],r['key']),r['en'])
        if r['kind']=='language' and r['source'].startswith('mods/') and isinstance(r['current'],str):
            tw_lines[r['source']]+=1;tw_chinese[r['source']]+=bool(HAN.search(r['current']))
    index_names=numbered_names(audit.rows)  # Wine Fox 2 is 「冰霜」酒狐: the number is not dropped
    ref_kinds=(result.get('references') or {}).get('sources') or ['tw','cn']
    vanilla=next((ref for n,ref in enumerate(refs) if n<len(ref_kinds) and ref_kinds[n]=='vanilla'),None)
    # Without any scanned mod jar there is nothing to compare against, so nothing is skipped.
    installed=getattr(audit,'installed_namespaces',None) if any(r['source'].startswith('mods/') for r in audit.rows) else None
    present=getattr(audit,'present_mods',None) if installed is not None else None
    last_publish=time.monotonic();decided=[]
    older=older_copies(instance,{r['source'].split('!/')[0] for r in audit.rows
                                 if r['source'].startswith('mods/') and r['kind'] in ('language','book')})
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
        if r['source'].startswith(OWN_PACK):continue  # our own output; its text is what the mod rows below show
        if r['kind']=='data_text':
            if r['source'].startswith(OWN_DATA):continue  # our data pack; its text is what the rows of the original show
            resource=data_resource(r)
            if data_reader.get(resource)!=r['source']:
                counts['data_overridden']+=1;continue  # a copy below another one: the game never shows it
            result['rows'].append(data_text_row(r,data_shown.get(resource),data_loader,provenance,memory,ai_memory))
            counts['data_text']+=1;continue
        if r['kind'] in ('language','book') and r['source'].split('!/')[0] in older:
            counts['older_mod_copy']+=1;continue  # the game loads the newer copy of this mod (older_copies)
        if (r['kind']=='language' and r['source'].startswith('mods/') and not r['source'].split('!/')[-1].startswith('assets/')
                and not SERVER_LANG.search(r['source'].split('!/')[-1])  # counted as server_lang below
                and (r['source'].split('!/')[0],lang_namespace(r['source']),r['key']) in main_copy):
            # A second copy inside the mod (e.g. legacy_pack/assets/...) of text its main assets/ also has:
            # the game shows the main copy, and both would go to the same place in the translation pack.
            counts['duplicate_copy']+=1;continue
        if r['kind']=='language' and r['key'] in screen_keys and SERVER_LANG.search(r['source'].split('!/')[-1]):
            # Forge reads data/<mod>/lang/ on the server, and only its en_us (LanguageHook.loadLanguagesOnServer);
            # the screen shows the same key from assets/<mod>/lang/, which is translated there. A zh_tw here is
            # never read, so it is neither a gap nor something to write.
            counts['server_lang']+=1;continue
        if r['source'].startswith('mods/') and r['kind'] in ('language','book','inline_lang'):
            title=book_title(r)  # a book's name or landing text: the pack holds it as a language entry
            shown=pack_text.get(title if title else (pack_resource(target_for(r)[1]),r['key']),r['current'])
            if shown is not None:r=dict(r,current=shown,own_tw=r['current'])
        # Non-language candidates are retained explicitly rather than reclassifying IDs as text.
        if r['kind']=='class_display' and managed(curseforge,r) and r.get('tooltip_in_language'):
            # The config screen shows the mod's language entry for this comment, which is a row of its own;
            # counting the class copy too would list text the game already shows from the language file.
            counts['tooltip_in_language']+=1;continue
        if r['kind']=='embedded_text':
            decided.append(embedded_row(r,curseforge,provenance,memory,ai_memory));counts['embedded_text']+=1;continue
        if literal_conversion(r,curseforge,provenance,lang_text):
            # Simplified Chinese written straight into a mod's program (Age of Mythology's 巫法师): where the
            # launcher does not put the original back, its characters are converted in place. Only the
            # characters change, and a literal the mod compares with stays as it is (plain_strings).
            r=dict(r,kind='class_display',display_use='程式裡的簡體中文（只轉成台灣繁體）',literal=True)
        if r['kind']=='class_display':
            original=r['current'];previous=provenance.lookup(r)
            # Config comments shown through the resource pack leave the class English; what the pack holds tells
            # whether an earlier run already wrote this line.
            in_pack=managed(curseforge,r) and r.get('tooltips') and not previous and provenance.entries.get(provenance.key(r))
            if in_pack and in_pack.get('original')==original and any(
                    tooltip_part(pack_text.get((resource,key)),part,parts)==in_pack.get('text') for key,part,parts,resource in r['tooltips']):
                previous=in_pack
            if class_name(r) in mixin and not (managed(curseforge,r) and r.get('tooltips')):
                # Another mod's Mixin changes this class when the game starts and may look for this exact text
                # (RevelationFix in The Foll); text written into it by v0.18.0 goes back to the original.
                if previous and previous is not in_pack and previous.get('origin')!='keep_original' and previous.get('original') \
                        and previous.get('text')==original and previous['original']!=original:
                    decided.append(dict(slim(r),proposed=previous['original'],origin='keep_original',evidence=r.get('display_use',''),
                                        issue=HELD_MIXIN+'；先前寫入的譯文已改回原文',supported=True,reviewed=False,changed=True))
                else:
                    decided.append(dict(slim(r),proposed=original,origin='untranslated' if not HAN.search(original) else 'existing_zh_tw',
                                        evidence=r.get('display_use',''),issue=HELD_MIXIN,supported=False,reviewed=False,changed=False))
                counts['mixin_target']+=1;continue
            reason=keep_original_reason(original,r['key'],'') if not HAN.search(original) else ''
            memory_value=memory.lookup(r['source'],r['key'],original)
            value=original;origin='untranslated';issue='';extra={}
            if previous is in_pack and previous:
                value=previous['text'];origin=previous['origin'];issue=previous.get('issue','')
                extra=dict(installed=True,recovered=True,ai_model=previous.get('model'))
            elif previous:
                origin=previous['origin'];issue=previous.get('issue','');extra=dict(installed=True,recovered=True,ai_model=previous.get('model'),en_ref=previous.get('original'))
            elif memory_value and fits(original,memory_value,True):
                value=memory_value;origin='translation_memory';extra=dict(own_lines=True) if not validate_text(original,memory_value) else {}
            elif reason:origin='keep_original'
            elif HAN.search(original):
                value=to_taiwan(original) if has_simplified(original) else original
                origin='existing_zh_tw' if value==original else 'same_source_zh_cn'
            else:
                earlier=ai_memory.lookup(r['source'],r['key'],original)
                if earlier and earlier.get('keep'):
                    origin='keep_original';issue=earlier.get('reason') or 'AI 判斷保留原文'
                elif earlier and validate_text(original,earlier['text']) and not number_doubt(original,earlier['text']):
                    value=earlier['text'];origin='ai_translation';extra=reuse_marks(earlier)
            # In a CurseForge modpack a changed mod file is replaced by the original when the game starts,
            # so program text there is listed with the reason instead of being translated for nothing.
            worded=taiwan_wording(value)
            if origin not in USER_ORIGINS+('keep_original','untranslated') and worded!=value and validate_text(original,worded):
                # The same Taiwan wording as language files (AI wrote 惡魂 for Ghast); text written earlier is corrected once.
                value=worded;extra.pop('installed',None);issue=(issue+'；' if issue else '')+'已把大陸用語改為台灣用語，請核對'
            # Config comments that config screens look up in the language files go into the translation pack instead.
            writable=not managed(curseforge,r) or origin in ('keep_original',) or extra.get('installed') or bool(r.get('tooltips'))
            decided.append(dict(slim(r),proposed=value,origin=origin,evidence=r.get('display_use',''),
                                issue=(r.get('tooltip_note') if not writable else '') or issue or ('等待 AI 補翻（已確認為'+r.get('display_use','玩家文字')+'）' if origin=='untranslated' and writable
                                                else '寫在模組程式裡的文字：CurseForge 啟動遊戲時會把改過的模組檔換回原版，無法保留翻譯' if not writable else ''),
                                supported=bool(writable),reviewed=False,changed=value!=original,**extra))
            continue
        if r.get('kind') in LOOSE_TEXT_KINDS and isinstance(r.get('current'),str) and FILE_NAME.search(r['current']):
            # A file name, not text (Paxi's resourcepack_load_order.json lists packs by name): converting it breaks the
            # link to the file. v0.17-v0.26 converted such names; one that no file has any more is put back.
            restored=original_file_name(instance,r['current'],file_names)
            if restored:
                result['rows'].append(dict(slim(r),proposed=restored,origin='keep_original',evidence='檔名，不是顯示文字',
                                           issue=f'先前版本把檔名轉成繁體，和實際的檔案「{restored}」對不上，已改回原本的檔名',
                                           supported=True,reviewed=False,changed=True))
                counts['file_name_restored']+=1;continue
            result['rows'].append(dict(slim(r),proposed=r['current'],origin='not_display',issue='程式內部字串：檔名，不是顯示文字',
                                       supported=False,reviewed=False,changed=False))
            counts['not_display']+=1;continue
        if r.get('unverified') and convertible(r) and r['current'].strip() in program_text:
            result['rows'].append(dict(slim(r),proposed=r['current'],origin='untranslated',supported=False,reviewed=False,changed=False,
                                       issue='程式還不認得的檔案；模組程式裡也有同一句，可能拿來比對，改了可能讓模組出錯，所以不改'))
            counts['unverified_program_text']+=1;continue
        if convertible(r):
            # Chinese written straight into config and quest files (The Foll's quests): Simplified is converted
            # to Taiwan wording in the file itself; Traditional is what the game already shows.
            original=r['current'];previous=provenance.lookup(r)
            # Text this program wrote is never converted again: a second pass turned 前仆後繼 into 前僕後繼.
            if has_simplified(original) and not previous:
                value=taiwan_wording(to_taiwan(original))
                if validate_text(original,value):
                    result['rows'].append(dict(slim(r),proposed=value,origin='same_source_zh_cn',evidence='loose_s2t',
                                               issue='',supported=True,reviewed=False,changed=value!=original))
                    counts['loose_s2t']+=1;continue
            else:
                origin,extra=(previous['origin'],dict(installed=True,recovered=True)) if previous else ('existing_zh_tw',{})
                value=original;issue=previous.get('issue','') if previous else ''
                if previous and origin not in USER_ORIGINS:
                    # Written by an earlier version before a conversion rule existed (擊殺 3 只殭屍 → 隻): corrected once.
                    worded=taiwan_wording(original)
                    if worded!=original and validate_text(original,worded):
                        value=worded;extra={};issue=(issue+'；' if issue else '')+'已修正轉換用字，請核對'
                result['rows'].append(dict(slim(r),proposed=value,origin=origin,evidence='loose_s2t' if previous else '',
                                           issue=issue,supported=True,reviewed=False,changed=value!=original,**extra))
                counts['loose_tw']+=1;continue
        if r['kind'] not in ('language','book','inline_lang'):
            if r['kind']=='unsupported_config_text':
                value=r['current'] or ''
                kept=next((why for pattern,why in KEEP_ENGLISH_FORMATS if pattern.search(r['source'])),None)
                if kept:
                    # Checked in the mod's program: Chinese would show as boxes there (see KEEP_ENGLISH_FORMATS).
                    result['rows'].append(dict(slim(r),proposed=value,origin='keep_original',evidence=kept,issue='無需翻譯：'+kept,
                                               supported=False,reviewed=False,changed=False))
                    counts['kept_english_format']+=1;continue
                result['rows'].append(dict(slim(r),proposed=value,origin='untranslated',
                                           issue='這個設定檔含有可能顯示給玩家的文字，但檔案格式尚未支援；已列出避免漏掉，暫不修改',
                                           supported=False,reviewed=False,changed=False))
                counts['unsupported_config_text']+=1;continue
            if r['flags']:
                value=r['current'] or r['en'] or '';copy=in_language_file(r,value,lang_text)
                hidden=(internal_reason(value) or ('只用在錯誤訊息或記錄檔' if r.get('developer_use') else '')
                        or ('產生語系檔用的工具程式；遊戲顯示的是模組附的語系檔，那份已另外翻譯' if r.get('language_generator') else '')
                        or ('模組附的語系檔裡有同一句；遊戲顯示的是語系檔那句，那份已另外翻譯' if copy else ''))
                # Obvious identifiers, code and log lines are set aside so 待查 lists what may really be shown.
                result['rows'].append(dict(slim(r),proposed=value,origin='not_display' if hidden else 'untranslated',
                                           issue='程式內部字串：'+hidden if hidden else '無法確定遊戲會不會顯示這句；它也可能是程式拿來比對的名稱，改了可能讓模組出錯，所以先不修改、不送 AI',
                                           supported=False,reviewed=False,changed=False,**({'language_copy':True} if copy else {})))
                counts['not_display' if hidden else 'context_candidate']+=1
            continue
        ns=memory_scope(r)
        if r['source'].startswith(PAXI_PACKS+'/'):
            counts['reference_only']+=1;continue  # read for its translations (instance_cn); the modpack author's file stays as it is
        if r['source'].count('!/')>=2 and (ns,r['key']) in kubejs_tw:r=dict(r,current=kubejs_tw[(ns,r['key'])])
        # Text that exists only in Chinese (a bundled CFPA pack, KubeJS zh_cn) is checked against the
        # installed mod's English for the same key. With no English anywhere, nothing counts as matching.
        english=r['en'] if isinstance(r['en'],str) else mod_en.get((ns,r['key'])) if ns else None
        borrowed=english if not isinstance(r['en'],str) else None
        original=english if isinstance(english,str) else r['zh_cn'] or r['current'] or ''
        if installed is not None and ns and TRANSLATION_PACK.match(r['source']) and (ns not in installed or (present is not None and ns not in present)):
            # Bundled translation packs (e.g. a whole CFPA pack via OpenLoader) cover mods this
            # modpack does not have; the game never shows those strings. Another mod's compatibility
            # textures or recipes for that mod do not make it installed.
            counts['not_installed']+=1;continue
        ref=KEY_MOD_REFERENCE.match(r['key'])
        ref=ref and (ref[1] or ref[2])
        if installed is not None and ref and ref not in (ns,'minecraft') and ref not in installed:
            # e.g. Traveler's Titles names for biomes of mods that are not installed.
            counts['not_installed']+=1;continue
        if r.get('no_chinese_font') and isinstance(english,str):
            # Readable English beats a row of boxes; Chinese an earlier run wrote goes back to the English once.
            back=isinstance(r['current'],str) and bool(HAN.search(r['current']))
            why=NO_CHINESE_FONT.format(r['no_chinese_font'].split('!/')[-1])
            decided.append(dict(slim(r),proposed=english,origin='keep_original',evidence=why,
                                issue='先前寫入的中文已改回英文：'+why if back else '',
                                supported=True,reviewed=False,changed=back))
            counts['no_chinese_font']+=1;continue
        own=r.get('own_tw',r['current'])
        if (r['kind']=='language' and r['source'].startswith('mods/') and isinstance(english,str)
                and tw_chinese[r['source']]*2>=tw_lines[r['source']] and author_kept(english,own,r['zh_cn'])
                and not memory.lookup(ns,r['key'],original)):  # what the user confirmed still comes first
            # The mod's translators kept an abbreviation in English on purpose (Cobblemon's zh_tw: Lv., HP, PP). AI's 等級
            # did not fit the box drawn for "Lv.2"; what an earlier run wrote goes back to the author's text once.
            decided.append(dict(slim(r),proposed=own,origin='keep_original',evidence=KEPT_BY_AUTHOR,issue='',
                                supported=True,reviewed=False,changed=own!=r['current']))
            counts['kept_by_author']+=1;continue
        # Source order: most accurate Taiwan wording first (see README 翻譯邏輯 / AGENTS.md).
        # Decisions the user made → people-written zh_tw (reference packs whose English matches this
        # version, the modpack's zh_tw packs, the mod's own zh_tw) → Mojang's official names →
        # converted zh_cn (modpack, same mod, CFPA) → unverified candidates → glossary → AI later.
        existing=r['current'] if isinstance(r['current'],str) and not has_simplified(r['current']) else None
        human_tw=[];converted_cn=[];stale_tw=[];cross=[]
        if ns:
            for n,ref in enumerate(refs):
                kind=ref_kinds[n] if n<len(ref_kinds) else 'reference'
                if kind=='vanilla':continue
                if kind in HUMAN_TW_KINDS:
                    value,matches=pick_reference(ref,ns,r['key'],english)
                    # Only a confirmed match counts; "unknown" (no English to compare) is not a match.
                    if matches is True:human_tw.append(('reference_pack_or_cfpa',value,'reference:'+kind))
                    else:stale_tw.append(('stale_reference' if matches is False else 'unverified_reference',value,'reference:'+kind))
                elif kind.startswith('cn-'):cross.append(('cross_version_reference',ref.get(ns,{}).get(r['key']),'reference:'+kind))
                else:converted_cn.append(('reference_pack_or_cfpa',ref.get(ns,{}).get(r['key']),'reference:'+kind))
        # What the user decided for the mod's English also holds for the files that override it in game;
        # confirmations made before v0.8.0 were kept under the Chinese the row was read from.
        asked=[original]+([r['zh_cn']] if borrowed and r['zh_cn'] else [])
        options=[('translation_memory',next((v for v in (memory.lookup(ns,r['key'],o) for o in asked) if v),None),'translation_memory.json'),
                 ('user_glossary',next((v for v in (user_terms.lookup(o) for o in asked) if v),None),'user_glossary.json')]
        options+=human_tw
        options+=[('instance_resourcepack',v,p) for p,v in instance_rp_tw.get((ns,r['key']),[]) if p!=r['source']]
        own=r.get('own_tw')
        if isinstance(own,str) and isinstance(existing,str) and own!=existing and re.sub(r'\s','',own)==re.sub(r'\s','',existing) and not has_simplified(own):
            # The pack holds the mod's own Chinese broken into the English line count by an earlier version
            # (魚肉鮮嫩麻 / 辣超入味); the author's line breaks come back.
            existing=own
        vanilla_name=re.fullmatch(r'structure\.minecraft\.([a-z0-9_]+)',r['key'])
        if vanilla_name and VANILLA_STRUCTURE_NAMES.get(vanilla_name[1]):
            # The game's own structures under the official zh_tw names, above a compass mod's own zh_tw (Explorer's
            # Compass 1.4.0 calls the taiga village 大河村 and the ocean monument 海底廢墟).
            options.append(('official_vanilla',VANILLA_STRUCTURE_NAMES[vanilla_name[1]],'Minecraft 官方 zh_tw 地圖與進度的結構名稱'))
        # Text this program wrote from an AI answer or a doubtful reference is not the mod's own zh_tw: it keeps that
        # place in the order, so a source found later (the modpack's compass translation pack) still comes first.
        ours=provenance.lookup(r) if isinstance(existing,str) and existing==r['current'] else None
        late=bool(ours and ours.get('origin') in LATE_ORIGINS)
        # A compass mod's zh_tw also names other mods' structures (Explorer's Compass 1.4.0: 小汽艇 for Small Blimp): that is
        # not the mod's own translation of itself, and the modpack's own compass translation pack comes first.
        named=REGISTRY_KEY.match(r['key']) and r['key'].split('.')[1]
        late=late or bool(named and named not in (ns,'minecraft') and isinstance(existing,str))
        if not late:options.append(('existing_zh_tw',existing,r['source']))
        if vanilla:
            options.append(('official_vanilla',vanilla['minecraft'].get(r['key']) if ns=='minecraft' else None,'Minecraft 官方 zh_tw'))
            # Whole-text official names only for name keys: a generic word such as "Red" may be a
            # mod's own name (a dragon colour) and must not become the vanilla 紅色.
            if NAME_KEY.match(r['key']):
                options.append(('official_vanilla',vanilla['__terms__'].get(original.strip().casefold()),'Minecraft 官方 zh_tw 譯名'))
        options+=[('same_source_zh_cn' if p==r['source'] else 'instance_zh_cn',plain_name(r['key'],v,english),p) for p,v in instance_cn.get((ns,r['key']),[])]
        options+=[('same_source_zh_cn' if p==r['source'] else 'instance_zh_cn',v,p) for p,v in instance_rp_cn.get((ns,r['key']),[])]
        options.append(('same_source_zh_cn',r['zh_cn'],r['source']))
        if isinstance(english,str) and has_simplified(english):
            # The "English" file itself holds simplified Chinese (modpack authors do this in quest files).
            options.append(('same_source_zh_cn',english,r['source']))
        options+=converted_cn
        options+=stale_tw
        options+=cross
        term=MINECRAFT_GLOSSARY.get(original.lower())
        if term and vanilla:term=vanilla['__terms__'].get(original.strip().casefold(),term)  # Mojang's own name wins
        options.append(('glossary',term,'MINECRAFT_GLOSSARY'))
        if existing is None and isinstance(r['current'],str):
            # A zh_tw that still contains simplified characters is only a last-resort candidate.
            options.append(('existing_zh_tw',to_taiwan(r['current']),r['source']+'（原含簡體，已轉繁）'))
        earlier=ai_memory.lookup(ns,r['key'],original) if isinstance(english,str) else None
        if earlier and not earlier.get('keep'):options.append(('ai_memory',earlier['text'],'ai_memory.json'))
        if late:options.append(('existing_zh_tw',existing,r['source']))  # what was written before, when nothing else is found
        renamed=(not r['source'].startswith('mods/') and isinstance(r['en'],str)
                 and mod_en.get((ns,r['key'])) not in (None,r['en']))
        if renamed:
            # The modpack renamed this text (e.g. a KubeJS item rename); sources tied only to the key
            # still describe the mod's original English and would bring the old name back.
            options=[o for o in options if o[0] in ('translation_memory','user_glossary','existing_zh_tw','glossary')
                     or (o[0]=='same_source_zh_cn' and o[2]==r['source'])
                     or (o[0]=='reference_pack_or_cfpa' and o[2] in ('reference:tw','reference:para'))]
            special['renamed']+=1
        value=original; origin='untranslated'; evidence=''; issue='缺少可用中文來源'
        # Converted or other-version Chinese that changes the numbers of the English original waits for
        # a source that keeps them, and is used (and listed for checking) only when none does. The
        # user's own decisions are not checked, and Traditional Chinese written for this version keeps
        # its place and is only listed.
        ready=[];doubt=''
        for name,candidate,source in options:
            if not isinstance(candidate,str) or not HAN.search(candidate):continue
            # A stray Cyrillic or Greek letter the English does not have is a broken translation (Explorer's
            # Compass 1.4.0 zh_tw: Д被破壞的傳送門叢林); the next source is used, else AI.
            if name not in USER_ORIGINS and FOREIGN_LETTER.search(candidate) and not FOREIGN_LETTER.search(original):continue
            text=to_taiwan(candidate) if name in ('same_source_zh_cn','instance_zh_cn') else candidate
            # Chinese often needs fewer lines than the English. Chinese written by people keeps its own line
            # breaks; only AI's are laid out again (they were asked for the English line count).
            numbered=index_placeholders(original,text)
            own_lines=name!='ai_memory' and not validate_text(original,numbered) and same_format(original,numbered)
            text=numbered if own_lines else repair(original,text)
            if not fits(original,text,own_lines):continue
            written_tw=(name in ('existing_zh_tw','instance_resourcepack','official_vanilla')
                        or (name=='reference_pack_or_cfpa' and source in ('reference:tw','reference:para')))
            note='' if name in ('translation_memory','user_glossary') or (
                name in ('same_source_zh_cn','instance_zh_cn','existing_zh_tw') and (r['source'],r['key']) in index_names) else number_doubt(english,text)
            ready.append((bool(note) and not written_tw,name,text,source,note,own_lines))
            if not ready[-1][0]:break
        own_lines=False
        if ready:
            _,origin,value,evidence,doubt,own_lines=min(ready,key=lambda x:x[0])  # the first that does not wait, else the first
        reused=origin=='ai_memory'
        if reused:origin='ai_translation';evidence='ChatGPT/Codex: '+str(earlier.get('model') or '')+'（沿用先前的補譯）'
        if ready:
            issue=('' if origin in ('existing_zh_tw','translation_memory','user_glossary','official_vanilla','instance_resourcepack')
                   or (origin=='reference_pack_or_cfpa' and evidence in ('reference:tw','reference:para'))
                   else '參考譯文對應的英文與目前版本不同，需核對' if origin=='stale_reference'
                   else '參考譯文沒有英文可以比對，版本未確認，需核對' if origin=='unverified_reference'
                   else '跨版本參考：來自其他 Minecraft 版本的 CFPA，需核對版本差異' if origin=='cross_version_reference'
                   else 'AI 補譯（沿用先前翻過的同一句），尚未人工校對。' if reused
                   else '簡中轉繁：需校對台灣用語、版本語意與名稱')
        if origin=='unverified_reference':origin='stale_reference'  # listed with the other references that need a look
        if origin=='official_vanilla' and vanilla_name and isinstance(r['current'],str) and HAN.search(r['current']) and r['current']!=value:
            issue=f'模組自帶的繁中「{r["current"]}」不是官方名稱，已改用官方譯名'
        extra=dict(en_ref=borrowed,own_lines=own_lines or None)
        prior=provenance.lookup(r) if origin=='existing_zh_tw' and value==r['current'] else None
        if prior and prior['origin']!='existing_zh_tw':
            # Our own earlier output: keep its real source and doubts instead of calling it mod zh_tw,
            # and leave its wording as it was applied.
            origin=prior['origin'];evidence=prior['evidence'];issue=prior['issue']
            extra.update(recovered=True,installed=True,unified_from=prior.get('unified_from'),ai_model=prior.get('model'))
            special['recovered']+=1
            for name,candidate,_ in options:
                # An earlier version broke this Chinese into the English line count, mid-word at times
                # (聊天 / 室頭貼繪 / 製的位置); the source's own line breaks come back, written once.
                text=to_taiwan(candidate) if name in ('same_source_zh_cn','instance_zh_cn') and isinstance(candidate,str) else candidate
                if (origin not in USER_ORIGINS and isinstance(text,str) and text.count('\n')<value.count('\n')
                        and re.sub(r'\s','',text)==re.sub(r'\s','',value) and same_format(original,text)):
                    value=text;own_lines=True;extra['own_lines']=True;extra.pop('installed')
                    issue=(issue+'；' if issue else '')+'已改回原文的換行';break
            if origin not in USER_ORIGINS and taiwan_wording(value)!=value and fits(original,taiwan_wording(value),own_lines):
                # Written by an earlier version before a wording rule existed (下界 → 地獄): corrected once and
                # written again; the corrected text is what later runs find, so they change nothing.
                value=taiwan_wording(value);extra.pop('installed');issue=(issue+'；' if issue else '')+'已把大陸用語改為台灣用語，請核對'
        elif origin=='existing_zh_tw' and existing is None:
            issue='既有繁中含簡體字，已轉為台灣繁體，請核對'
        elif origin=='existing_zh_tw' and taiwan_wording(value)!=value and fits(original,taiwan_wording(value),own_lines):
            value=taiwan_wording(value);issue='既有繁中已把大陸用語改為台灣用語，請核對'
        elif (origin not in USER_ORIGINS and origin not in ('official_vanilla','untranslated','keep_original')
              and taiwan_wording(value)!=value and fits(original,taiwan_wording(value),own_lines)):
            # Reference packs are people-written but not always in Taiwan wording (cloth-config's 設置 replaced
            # the mod's own correct 設定); the same unambiguous replacements apply to them.
            value=taiwan_wording(value);issue=(issue+'；' if issue else '')+'已把大陸用語改為台灣用語，請核對'
        reason=keep_original_reason(original,r['key'],ns) if origin=='untranslated' else ''
        if origin=='untranslated' and not reason and earlier and earlier.get('keep'):
            reason=earlier.get('reason') or 'AI 判斷保留原文'  # AI said so in an earlier run; not asked again
        if reason:
            # Parameters, key names and similar strings stay as-is; they are neither gaps nor AI work.
            origin='keep_original';evidence=reason;issue=''
            if r['en'] is None and r['current'] is None:issue='無需翻譯：'+evidence  # no en_us fallback in game
        supported=(r['kind']=='language' or bool(re.search(r'/(?:en_us|zh_tw)(?:_0)?/',r['source'])) or bool(book_title(r))
                   or bool(r.get('resource_text')))  # read through the resource manager whatever the language (RESOURCE_TEXTS)
        if r['kind']=='inline_lang':
            supported=reads_inline_zh_tw(r['source'])
            if not supported:issue=INLINE_UNVERIFIED  # written only where the mod is known to read zh_tw
        changed=value!=r['current'] and origin!='untranslated' and (origin!='keep_original' or bool(issue))
        # A number that differs from the English is listed even when the text stays as the mod wrote it.
        if doubt and not extra.get('recovered') and (changed or origin!='untranslated'):issue=(issue+'；' if issue else '')+doubt
        if '數值和原文不同' in (issue or ''):extra['number_doubt']=True  # also kept by text applied earlier
        if r.get('format_fixed') and '遊戲看不懂' not in (issue or ''):
            issue=FORMAT_FIXED_NOTE.format('、'.join(r['format_fixed']))+('；'+issue if issue else '')
        if reused:extra.update(reuse_marks(earlier))
        if ((NAME_KEY.match(r['key']) or r['key'].startswith('structure.')) and isinstance(r['en'],str) and 2<len(r['en'].strip())<=40 and HAN.search(value)
                and origin not in ('untranslated','keep_original','ai_translation')):
            rank=trust_rank(dict(origin=origin,evidence=evidence));en=r['en'].strip()
            if en not in name_terms or rank<name_terms[en][0]:name_terms[en]=(rank,value.strip())
        # Rows with nothing to change are decided too: another file's row for the same key may follow them.
        decided.append(dict(slim(r),proposed=value,origin=origin,evidence=evidence,issue=issue,
                            supported=supported,reviewed=False,changed=changed,renamed=renamed or None,
                            **{k:v for k,v in extra.items() if v is not None}))
    special['plural_names']=singular_names(decided)
    special['same_key']=unify_same_key(decided)
    special['repeated_names']=repeated_names(decided)
    special['name_doubts']=name_doubts(decided,ai_memory,map_biome_names(vanilla))
    for r in decided:
        # Names given to AI as they now read: the map's biome words in, names still in doubt out.
        en=(r.get('en') or '').strip() if isinstance(r.get('en'),str) else ''
        if en in name_terms and REGISTRY_KEY.match(r['key']):
            if r.get('name_doubt'):name_terms.pop(en)
            elif r.get('map_word'):name_terms[en]=(name_terms[en][0],r['proposed'].strip())
    listed=lambda row:bool(row['changed'] or row['issue'] or row['origin']=='keep_original')  # keep rows stay visible under 無需翻譯
    # A file whose text needs no change is listed too when another file's row for the same key is: naming
    # things alike or a correction by the user then reaches every file, and the game shows the result.
    beside={id(row) for group in same_key_groups(decided).values() if len(group)>1 and any(listed(r) for r in group) for row in group}
    already=0
    for row in decided:
        counts[row['origin']]+=1
        if listed(row) or id(row) in beside:result['rows'].append(row)
        elif row.get('supported') or row.get('kind')=='class_display':already+=1  # shown in Chinese already, nothing to do
    result['already_chinese']=already  # for the completion rate: these rows are not kept in the report
    show_language_copies(result['rows'],decided)
    result['rate_before']=coverage(result,before=True)['rate']  # what the game showed before this run
    # The map's biome names go to AI too (Swamp → 沼澤), below every name this modpack gives itself.
    result['map_biomes']=map_biome_names(vanilla)  # names AI writes later are checked against the map too (check_ai_names)
    known={en.casefold() for en in name_terms}
    biome_terms={en.title():zh for en,zh in map_biome_names(vanilla).items() if en not in known and en not in PLAIN_BIOME_WORDS}
    try:write_json(report/'name_terms.json',{**biome_terms,**{en:zh for en,(_,zh) in name_terms.items()}})
    except OSError:pass
    result.update(source_counts=dict(counts),status='needs_review',api=0,ai_translation=0,
                  recovered_count=special['recovered'],renamed_count=special['renamed'],same_key_count=special['same_key'])
    for name,expected in result['source_hashes'].items():
        if file_hash(contained(instance,name))!=expected:
            result['status']='blocked';result['errors'].append([name,'掃描途中檔案有變動（遊戲或啟動器可能正在更新），請稍後重新按「一鍵完整翻譯並套用」。'])
            break
    publish()
    notify(100,'來源整理完成','尚未套用；合格譯文可由一鍵流程自動檢查與套用。')
    return result


# Rows whose text sits in a mod file this modpack cannot write when CurseForge puts the file back.
HELD_KINDS = ('class_display','embedded_text')


def embedded_row(r, curseforge, provenance, memory, ai_memory):
    """The report row for words a data pack shows as written (embedded_text): an NPC's name or shop categories, a
    sign, a book, a function's chat message. They are changed in the file itself, string by string. Text written by
    an earlier run is recognised by its provenance (the original English is kept there, en_ref)."""
    route=write_route(r,curseforge);writable=route=='file'
    current=r['current'];previous=provenance.lookup(r)
    if previous:
        original=previous.get('original') or current
        worded=taiwan_wording(current) if previous['origin'] not in USER_ORIGINS else current
        changed=worded!=current and validate_text(original,worded)
        return dict(slim(r),en_ref=original,proposed=worded if changed else current,origin=previous['origin'],
                    evidence=previous.get('evidence',''),issue=(previous.get('issue','')+'；已修正轉換用字，請核對' if changed else previous.get('issue','')),
                    supported=writable,reviewed=False,changed=changed,installed=not changed,recovered=True,ai_model=previous.get('model'))
    scope=memory_scope(r);mine=memory.lookup(scope,r['key'],current);extra={}
    value=current;origin='untranslated';evidence='';issue=''
    if mine and fits(current,mine,True):value=mine;origin='translation_memory';evidence='translation_memory.json'
    elif HAN.search(current):
        converted=taiwan_wording(to_taiwan(current))
        if has_simplified(current) and validate_text(current,converted):value=converted;origin='same_source_zh_cn';evidence='data_s2t'
        else:origin='existing_zh_tw'
    else:
        reason=keep_original_reason(current,r['key'],'') if not embedded_text.text_spans(current) else ''
        earlier=ai_memory.lookup(scope,r['key'],current)
        if reason or (earlier and earlier.get('keep')):origin='keep_original';evidence=reason or earlier.get('reason') or 'AI 判斷保留原文'
        elif earlier and validate_text(current,earlier['text']) and not number_doubt(current,earlier['text']):
            value=earlier['text'];origin='ai_translation';evidence='ChatGPT/Codex: '+str(earlier.get('model') or '')+'（沿用先前的補譯）'
            issue='AI 補譯（沿用先前翻過的同一句），尚未人工校對。';extra.update(reuse_marks(earlier))
        else:issue='缺少可用中文來源'
    if not writable and origin!='keep_original':issue=route
    return dict(slim(r),proposed=value,origin=origin,evidence=evidence,issue=issue,supported=writable,reviewed=False,
                changed=value!=current and origin!='untranslated',**extra)


def data_text_row(r, shown, loader, provenance, memory, ai_memory):
    """The report row for one string of a data file a mod shows as written (DATA_TEXT).

    mod_text is the string in the original file; current is what the game shows now, which is the translation
    data pack's copy when there is one. Chinese is converted to Taiwan wording (there is no English to compare
    with); English waits for a confirmed translation, an earlier AI one, or AI. Text written by an earlier run
    is recognised by its provenance and is not written again.
    """
    mod_text=r['current'] if r['current'] is not None else r['en']
    on_screen=at(shown,json.loads(r['key'])) if shown is not None else None
    r=dict(slim(r),mod_text=mod_text,current=on_screen if on_screen is not None else r['current'])
    extra={} if loader else dict(no_data_pack=True)
    previous=provenance.lookup(r) if on_screen is not None else None
    if previous:
        worded=taiwan_wording(r['current']) if previous['origin'] not in USER_ORIGINS else r['current']
        if worded!=r['current'] and validate_text(mod_text,worded):
            # Written before a conversion rule existed (擊殺 3 只殭屍 → 隻): corrected once, then recognised again.
            return dict(r,proposed=worded,origin=previous['origin'],evidence=previous.get('evidence',''),
                        issue=(previous.get('issue','')+'；' if previous.get('issue') else '')+'已修正轉換用字，請核對',
                        supported=True,reviewed=False,changed=True,ai_model=previous.get('model'),**extra)
        return dict(r,proposed=r['current'],origin=previous['origin'],evidence=previous.get('evidence',''),issue=previous.get('issue',''),
                    supported=True,reviewed=False,changed=False,installed=True,recovered=True,ai_model=previous.get('model'),**extra)
    scope=memory_scope(r);mine=memory.lookup(scope,r['key'],mod_text)
    value=mod_text;origin='untranslated';evidence='';issue=''
    if mine and fits(mod_text,mine,True):value=mine;origin='translation_memory';evidence='translation_memory.json'
    elif HAN.search(mod_text):
        converted=taiwan_wording(to_taiwan(mod_text))
        if has_simplified(mod_text) and validate_text(mod_text,converted):value=converted;origin='same_source_zh_cn';evidence='data_s2t'
        else:origin='existing_zh_tw'
    else:
        reason=keep_original_reason(mod_text,r['key'],'')
        earlier=ai_memory.lookup(scope,r['key'],mod_text)
        if reason or (earlier and earlier.get('keep')):
            origin='keep_original';evidence=reason or earlier.get('reason') or 'AI 判斷保留原文'
        elif earlier and validate_text(mod_text,earlier['text']) and not number_doubt(mod_text,earlier['text']):
            value=earlier['text'];origin='ai_translation';evidence='ChatGPT/Codex: '+str(earlier.get('model') or '')+'（沿用先前的補譯）'
            issue='AI 補譯（沿用先前翻過的同一句），尚未人工校對。';extra.update(reuse_marks(earlier))
        elif isinstance(on_screen,str) and HAN.search(on_screen):value=on_screen;origin='existing_zh_tw'
        else:issue='缺少可用中文來源'
    if not loader and origin!='keep_original':issue=HELD_NO_DATAPACK
    return dict(r,proposed=value,origin=origin,evidence=evidence,issue=issue,supported=True,reviewed=False,
                changed=value!=r['current'] and origin!='untranslated',**extra)


def prepare_to_apply(session):
    """What every write is preceded by: one wording per key and per name, then the automatic checks."""
    session['same_key_count']=session.get('same_key_count',0)+unify_same_key(session['rows'])
    unify_suggested_terms(session)
    # Naming things alike reaches every file of a key; this is the check that it did.
    session['same_key_count']+=unify_same_key(session['rows'])
    conflicts=tooltip_conflicts(session['rows']) if session.get('instance') and is_curseforge(session['instance']) else set()
    for row in session['rows']:
        if not row.get('tooltips'):continue
        issue=(row.get('issue') or '').replace('；'+HELD_TOOLTIP_CONFLICT,'').replace(HELD_TOOLTIP_CONFLICT,'')
        if any((row['source'].split('!/')[0],key,resource) in conflicts for key,_,_,resource in row['tooltips']):
            issue=(issue+'；' if issue else '')+HELD_TOOLTIP_CONFLICT
        row['issue']=issue
    return auto_confirm_safe(session)


def full_translation(instance, home, model, notify, cancelled=lambda:False, checkpoint=lambda _:None, options=None):
    """One button: translate from the sources and write at once, then let AI fill in what is left.

    The sources take a few minutes and AI takes far longer, so the game is in Chinese after the first
    write and AI's translations follow as a second, smaller write. A write that the game or another
    program blocked is tried again at the end, and the report is kept whatever happens.

    options: set_language (switch options.txt to zh_tw, backed up like every other file). Mod text is
    always written to the translation resource pack (see build_pack).
    Progress is reported for the whole job: sources 0-50, first write 50-72, AI 72-90, second write 90-100.
    """
    def part(low,high):
        return lambda value,title,detail='':notify(low+int((high-low)*max(0,min(100,value))/100),title,detail)
    result=plan(instance,home,part(0,50),cancelled,checkpoint=checkpoint)
    result.update(options or {})
    if result['status'] in ('blocked','cancelled'):return result
    blocked=None

    def write(low,high):
        """Write what is ready; returns why it could not be written, else None."""
        nonlocal result
        prepare_to_apply(result)
        if not applicable_count(result):return None  # nothing that can be written in this modpack
        result['status']='ready_to_apply'
        write_json(Path(result['report'])/'session.json',result);checkpoint(result)
        try:result=apply_session(result,home,part(low,high))
        except GameRunningError as exc:return dict(status='awaiting_game',apply_error=str(exc))
        except Exception as exc:return dict(status='apply_failed',apply_error=explain_error(exc))
        result.pop('apply_error',None)
        return None

    try:
        blocked=write(50,72)
        first=result.get('installed_count',0);asked=False
        if model and not cancelled():
            from . import codex_bridge as ai
            asked=True
            note=f'（先前的 {first:,} 筆已經寫入遊戲）' if first else ''
            def told(low,high):
                waiting=part(low,high)
                return lambda value,title,detail='':waiting(value,title,detail+note if title in ('AI 補翻中','AI 核對疑點中') else detail)
            if ai.pending_rows(result):
                result=ai.supplement(result,home,model,told(72,84),cancelled,checkpoint=checkpoint)
            else:
                result.update(ai_status='skipped',ai_message='沒有需要 AI 補翻的語系缺漏。')
            # Doubts are checked only when the account got through the gaps; a paused account stays paused.
            if result.get('ai_status')!='paused' and not cancelled() and ai.doubt_rows(result):
                result=ai.review(result,home,model,told(84,90),cancelled,checkpoint=checkpoint)
        elif not model:
            result.update(ai_status='skipped',ai_message='未連接 AI；缺少中文來源的文字保留原文。')
        if cancelled():
            # What was written stays written and can be restored; AI's finished rows wait in the report.
            if not first:result['status']='cancelled'
        elif asked:
            # AI pausing (quota) only leaves its remaining rows untranslated; everything already
            # translated is still applied, and the rest can be supplemented later from the report.
            blocked=write(90,100)
        if not blocked and result['status']=='ready_to_apply':result['status']='needs_review'
    except Exception as exc:
        blocked=dict(status='apply_failed',apply_error=explain_error(exc))
    if blocked:result.update(blocked)
    write_json(Path(result['report'])/'session.json',result)
    checkpoint(result)
    return result


_MOD_NAMES = {}


def clean_file_name(name):
    """'Jadens-Nether-Expansion-2.4.0-BETA.7.jar' -> 'Jadens Nether Expansion'."""
    stem=re.sub(r'\.(jar|zip)$','',name,flags=re.I)
    stem=re.sub(r'[-_+ ](?:neo)?(?:forge|fabric|quilt|mc|v)?[-_+ ]?\d[\w.+-]*$','',stem,flags=re.I)
    stem=re.sub(r'[-_+](?:neo)?(?:forge|fabric|quilt)$','',stem,flags=re.I)
    return re.sub(r'[-_]+',' ',stem).strip() or name


def mod_display_name(instance, outer):
    """The mod's own display name from its metadata, falling back to a cleaned file name."""
    key=(str(instance),outer)
    if key in _MOD_NAMES:return _MOD_NAMES[key]
    name=None
    try:
        with zipfile.ZipFile(contained(Path(instance),outer)) as z:
            names=set(z.namelist())
            for meta in ('META-INF/neoforge.mods.toml','META-INF/mods.toml'):
                if meta in names:
                    m=re.search(r'(?m)^\s*displayName\s*=\s*"([^"]+)"',z.read(meta).decode('utf-8','replace'))
                    if m:name=m[1];break
            if not name and 'fabric.mod.json' in names:
                name=json.loads(z.read('fabric.mod.json').decode('utf-8-sig')).get('name')
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,AttributeError):pass
    _MOD_NAMES[key]=name=str(name or clean_file_name(outer.split('/')[-1]))
    return name


def module_label(instance, row):
    """Where a row's text lives, as a file the player can find in the modpack folder.

    'Jadens-Nether-Expansion-2.4.0-BETA.7.jar · netherexp'; the mod's display name is kept for
    the tooltip (mod_display_name) because two jars can share one.
    """
    source=row.get('source','');parts=source.split('!/')
    m=re.search(r'assets/([^/]+)/',source);ns=m[1] if m else ''
    outer=parts[0]
    if outer=='instance':
        path=parts[1] if len(parts)>1 else ''
        where='/'.join(path.split('/')[:3]) if path.startswith('kubejs/') else path
    elif len(parts)>2:where=parts[1].split('/')[-1]+'（在 '+outer.split('/')[-1]+' 裡）'
    else:where=outer.split('/')[-1]
    return where+(' · '+ns if ns and ns not in where else '')


TRANSLATED_CATEGORIES = ('mine','tw_ref','mod_tw','official','s2t','version_ref','ai','other')
UNTRANSLATED_CATEGORIES = ('missing','held','unshown','context','keep')
CATEGORY_NAMES = {'mine':'你確認的','tw_ref':'台灣參考庫','mod_tw':'模組／整合包繁中','official':'官方譯名與術語',
                  's2t':'簡中轉繁','version_ref':'版本待確認的參考','ai':'AI 補譯','other':'其他',
                  'missing':'缺少中文來源','held':'無法寫入（遊戲中是英文）','unshown':'寫入後遊戲讀不到','context':'無法確定是否顯示','keep':'無需翻譯'}


# Language files in a data folder (mods' data/<mod>/lang/, datapacks): see plan(), which skips them.
SERVER_LANG = re.compile(r'(?:^|/)data/[^/]+/lang/[^/]+$', re.I)


def still_english(r):
    """Nothing was translated: no source at all, or the text is the original as it was. A translated line that
    holds no Chinese (a code fragment such as othermod"]) after its line was split) is translated."""
    if r.get('origin')=='untranslated':return True
    proposed=r.get('proposed') or ''
    return not HAN.search(proposed) and proposed.strip()==str(original_of(r)).strip()


def held_english(r):
    """Player text inside a mod's program that this modpack cannot write: the game shows it in English.
    Text the program already holds in Chinese is shown in Chinese and is not counted here."""
    if r.get('kind') not in HELD_KINDS or r.get('supported'):return False
    return still_english(r) or bool(r.get('changed')) or not HAN.search(r.get('current') or '')


def row_state(r, curseforge=False):
    """What the game shows for one row, the single judgement both the start page (coverage) and the report
    filters (row_category) are built on, so their numbers always add up the same way:
    None (not counted: needs no translation, or not matched yet), 'candidate' (use not proven), 'done'
    (shown in Chinese), 'missing' (no Chinese source), 'unwritable' (translated or not, the game keeps showing
    English: program text CurseForge puts back, or a place no file of ours reaches), 'unconfirmed' (written,
    but the file the game reads does not hold it) or 'waiting' (translated, not written yet).
    """
    if r.get('origin') in ('keep_original','not_display','pending'):return None
    if r.get('unverified'):return 'candidate'  # written where no mod was checked to read it: not counted either way
    held=r.get('kind') in HELD_KINDS and not r.get('supported')
    if held:return 'unwritable' if held_english(r) else 'done'  # else the program already shows it in Chinese
    if not r.get('supported'):return 'candidate'
    if still_english(r):return 'missing'
    if not r.get('changed') or (r.get('installed') and r.get('shown') is not False):return 'done'
    if r.get('installed'):return 'unconfirmed'
    if write_route(r,curseforge) not in WRITTEN_ROUTES:return 'unwritable'
    return 'waiting'


def row_category(r, curseforge=False):
    """Report grouping: translated (by how) or untranslated (by why). Every row the start page counts as
    still English for a reason of its own (row_state) is listed under that reason, never under a source."""
    o=r.get('origin')
    if o=='pending':return 'pending'
    state=row_state(r,curseforge)
    if state is None:return 'keep'
    if state=='candidate':return 'context'
    if state=='unwritable':return 'held'
    if state=='missing':return 'missing'
    if state=='unconfirmed':return 'unshown'
    if r.get('kind') in HELD_KINDS and not r.get('supported'):return 'mod_tw'  # already Chinese in the program
    if o in ('translation_memory','user_glossary','manual'):return 'mine'
    if o=='reference_pack_or_cfpa':return 'tw_ref' if r.get('evidence') in ('reference:tw','reference:para') else 's2t'
    if o in ('existing_zh_tw','instance_resourcepack'):return 'mod_tw'
    if o in ('official_vanilla','glossary'):return 'official'
    if o in ('same_source_zh_cn','instance_zh_cn'):return 's2t'
    if o=='ai_translation':return 'ai'
    if o in ('stale_reference','cross_version_reference'):return 'version_ref'
    return 'other'


def session_curseforge(session):
    return is_curseforge(session['instance']) if session.get('instance') else False


def categories(session):
    """row_category of every row of a report, in order."""
    curseforge=session_curseforge(session)
    return [row_category(r,curseforge) for r in session.get('rows',[])]


def coverage(session, before=False):
    """How much of the player text this program knows about the game shows in Chinese, counted the same way
    every time. Text that needs no translation is left out of both sides; program and config strings whose use
    is unproven are counted apart (`candidates`), since nobody knows whether the game shows them.

    A written row counts as done only when reading the game's files back gave its text (`shown`, see
    check_shown); rows the scan found in Chinese already count as they are. With before=True it is what the
    game showed when this run scanned it: a line counts when its text on disk (`current`) was Chinese.
    """
    rows=session.get('rows',[]);curseforge=session_curseforge(session)
    c=collections.Counter(done=session.get('already_chinese',0),total=session.get('already_chinese',0))
    for r in rows:
        state=row_state(r,curseforge)
        if state is None:continue
        if state=='candidate':
            c['candidates']+=1;continue
        c['total']+=1
        if before:
            c['done' if r.get('shown_before',HAN.search(r.get('current') or '')) else 'missing']+=1;continue
        c[state]+=1
    c['rate']=(c['done']/c['total']) if c['total'] else None
    return dict(c)


def check_shown(instance, rows):
    """Read back, from the files the game reads, the text of each row just written; mark rows['shown'].

    Mod text is read from the translation resource pack (which must be switched on in options.txt), other
    text from its own file. Program text is read back from the actual class constant.
    Returns how many rows the files do not hold.
    """
    instance=Path(instance);files={};missing=0;places=collections.defaultdict(list);curseforge=is_curseforge(instance)
    options=instance/'options.txt'
    pack_on=RESOURCE_PACK_ID in (enabled_packs(options.read_text(encoding='utf-8')) or []) if options.is_file() else False
    pack,_=read_resource_pack(instance)

    def load(where,raw,name):
        if where in files:return files[where]
        try:
            if raw is None:data=None
            elif name.endswith('.snbt'):data=quest_file(raw)
            elif name.endswith('.json'):data=parse(raw)
            elif name.endswith(('.lang','.local')):data=lang_table(raw.decode('utf-8-sig'),name)
            else:data=raw.decode('utf-8-sig')
        except (ValueError,UnicodeError):data=None
        files[where]=data;return data

    for r in rows:
        if r.get('kind')=='class_display' and r.get('tooltips') and write_route(r,curseforge)=='pack':
            # A config comment written as '<key>.tooltip': every key it went to must hold this line.
            found=[]
            for key,part,parts,resource in r['tooltips']:
                data=load(('pack',resource),pack.get(resource),resource) if pack_on else None
                found.append(isinstance(data,dict) and tooltip_part(data.get(key),part,parts)==r['proposed'])
            r['shown']=any(found);missing+=not r['shown'];continue
        if r.get('kind')=='class_display':
            from .class_text import ClassFile
            try:
                path,entry=target_for(r);where=('class',path,entry)
                if where not in files:files[where]=ClassFile(read_archive_entry(instance,path,entry)).utf
                r['shown']=files[where].get(int(r['key']))==r['proposed']
            except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile):r['shown']=False
            missing+=not r['shown'];continue
        if r.get('kind')=='embedded_text':
            # Written into the data-pack file itself: that file's unit at this place now reads so.
            path,entry=target_for(r);where=('embedded',path,entry)
            if where not in files:
                try:
                    raw=read_archive_entry(instance,path,entry) if entry else contained(instance,path).read_bytes()
                    files[where]=dict(embedded_text.units(entry or path,raw)) if raw is not None else {}
                except (OSError,ValueError,KeyError,zipfile.BadZipFile):files[where]={}
            r['shown']=embedded_text.reads_as(files[where].get(r['key']),r['proposed']);missing+=not r['shown'];continue
        if r.get('kind')=='data_text':
            # Shown when the translation data pack holds it and OpenLoader loads that pack (see DATA_PACK_FILE).
            if 'datapack' not in files:files['datapack']=read_data_pack(instance)[0] if reads_data_packs(instance) else {}
            resource=data_resource(r)
            if ('data',resource) not in files:
                try:files[('data',resource)]=parse(files['datapack'][resource]) if resource in files['datapack'] else None
                except ValueError:files[('data',resource)]=None
            try:r['shown']=files[('data',resource)] is not None and at(files[('data',resource)],json.loads(r['key']))==r['proposed']
            except (ValueError,TypeError):r['shown']=False
            missing+=not r['shown'];continue
        if convertible(r):
            # Config and quest strings converted in place: the string at that place (JSON: any string) now reads so.
            path=r['source']
            if PurePosixPath(path).suffix.casefold() in BINARY_CONFIG_SUFFIXES:
                try:
                    if ('binary',path) not in files:
                        files[('binary',path)]=parse_binary_nbt(contained(instance,path).read_bytes())
                    r['shown']=at(files[('binary',path)],json.loads(r['key']))==r['proposed']
                except (OSError,ValueError,KeyError,IndexError,TypeError,UnicodeError):r['shown']=False
                missing+=not r['shown'];continue
            if ('literals',path) not in files:
                try:
                    raw=contained(instance,path).read_bytes()
                    files[('literals',path)]=list(string_literals(raw.decode('utf-8-sig'),PurePosixPath(path).suffix.casefold(),path))
                except (OSError,ValueError,UnicodeError):files[('literals',path)]=[]
            literals=files[('literals',path)]
            if re.fullmatch(r'\d+:\d+',r['key']):
                place=tuple(map(int,r['key'].split(':')))
                r['shown']=any((n,i)==place and v==r['proposed'] for n,i,v,_,_,_ in literals)
            else:r['shown']=any(v==r['proposed'] and not is_key for _,_,v,is_key,_,_ in literals)
            missing+=not r['shown'];continue
        path,entry=target_for(r);where=None;route=write_route(r,False);title=book_title(r) if route=='pack' else None
        try:
            if route=='pack':
                name=title[0] if title else pack_resource(entry);where=('pack',name);data=load(where,pack.get(name),name) if pack_on else None
            elif entry is None:
                p=contained(instance,path);name=path;where=('file',path)
                data=files[where] if where in files else load(where,p.read_bytes() if p.is_file() else None,path)
            else:
                name=entry.split('!/')[-1];where=('archive',path,entry)
                data=files[where] if where in files else load(where,read_archive_entry(instance,path,entry),name)
        except (OSError,ValueError,KeyError,zipfile.BadZipFile):data=None
        if isinstance(data,str):text=data
        elif not isinstance(data,dict):text=None
        elif title:text=data.get(title[1])
        elif r.get('kind')=='book':text=data if r['key']=='text' else at(data,json.loads(r['key']))
        elif r.get('kind')=='inline_lang':
            node=node_at(data,json.loads(r['key']));text=node.get(inline_field(r['source'],node)) if isinstance(node,dict) else None
        elif r.get('rich'):
            key,*part=json.loads(r['key']);text=at(data.get(key),part) if isinstance(data.get(key),(dict,list)) else None
        else:text=data.get(r['key'])
        r['shown']=text==r['proposed'];r.pop('shown_other',None)
        if where is None:missing+=not r['shown']
        else:places[(where,title[1] if title else r['key'])].append((r,text))
    for found in places.values():
        # Two mods can ship the same file (Goety's book pages in two jars); the pack holds one of them and the
        # game shows that one at this place. The other row is shown in Chinese too, by its twin's wording.
        if any(r['shown'] for r,_ in found):
            for r,text in found:
                if not r['shown'] and isinstance(text,str) and HAN.search(text):r['shown']=True;r['shown_other']=True
        missing+=sum(not r['shown'] for r,_ in found)
    return missing


def rate_text(rate):
    """97.3% — rounded down, so 100% only when every counted line is Chinese."""
    if rate is None:return '—'
    return f'{int(rate*1000)/10:.1f}%'


HOME_CARDS = ('中文化完成率','還缺中文')


def completion_notes(session):
    """Surface unfinished scope without requiring the player to inspect individual rows."""
    rows=session.get('rows',[]);info=session.get('text_inventory') or {}
    notes=[]
    unsupported={r['source'] for r in rows if r.get('kind')=='unsupported_config_text'}
    if unsupported:notes.append(f'另有 {len(unsupported):,} 個檔案或資料夾含尚未支援的文字；仍可能在遊戲中看到原文。')
    if info.get('errors'):notes.append(f"有 {len(info['errors']):,} 項文字檢查沒讀完，這部分尚未確認。")
    doubts=sum(needs_check(r) for r in rows)
    if doubts:notes.append(f'還有 {doubts:,} 筆具體翻譯疑點，尚未解決；詳情已保存在報告。')
    if session.get('errors'):notes.append('本次有部分操作未完成，已完成的結果與原因保存在報告。')
    return notes


def home_cards(session):
    """The start page: two numbers where 100% / 0 means every player line found is Chinese, and one line on
    what this run wrote. {'cards': [(number, explanation)] in HOME_CARDS order, 'written': text}.

    How many lines a run wrote says nothing about English left over (a second run usually writes none),
    so it is a note under the progress, never one of the headline numbers.
    """
    cov=coverage(session);wrote=session.get('installed_count',0);before=session.get('rate_before')
    now=rate_text(cov['rate'])
    if session.get('status') in ('scanning','references','matching',None) or before is None or cov['rate'] is None:written=''
    elif wrote and rate_text(before)!=now:written=f'這次從 {rate_text(before)} 提升到 {now}。'
    elif wrote:written=f'完成率維持 {now}；這次改寫了部分譯文（可在「備份與還原」復原）。'
    else:written=f'和翻譯前一樣是 {now}，這次沒有修改任何遊戲檔案。'
    notes=completion_notes(session)
    warning={'warning':'這次仍有未完成內容，不能視為整包翻完。\n'+'\n'.join(notes)} if notes else {}
    if notes:written+='\n'+'\n'.join(notes)
    written=written.strip()
    if not cov['total']:
        return dict(cards=[('—','尚無可計算的已辨識玩家文字')]*2,written=written,**warning)
    english=cov['total']-cov['done']
    rate=(f"已辨識範圍中 {cov['done']:,}／{cov['total']:,} 句在檔案裡已是中文；尚非遊戲畫面實測"
          +(f"；另有 {cov['candidates']:,} 條程式字串無法確認是否顯示，未計入" if cov.get('candidates') else ''))
    parts=[]
    if cov.get('missing'):parts.append(f"{cov['missing']:,} 句找不到中文來源"+('（可勾選 AI 補翻）' if not session.get('ai_translation') else ''))
    if cov.get('waiting'):parts.append(f"{cov['waiting']:,} 句已翻好、還沒寫入（列在已翻譯的分類裡）")
    if cov.get('unwritable'):parts.append(f"{cov['unwritable']:,} 句無法寫入，遊戲中是英文（多半寫在模組程式裡，CurseForge 會換回改過的模組）")
    if cov.get('unconfirmed'):parts.append(f"{cov['unconfirmed']:,} 句寫入後在遊戲檔案裡讀不到")
    left='、'.join(parts) if english else '找得到的玩家文字都已是中文'
    return dict(cards=[(rate_text(cov['rate']),rate),(f'{english:,}',left)],written=written,**warning)


def applicable_count(session):
    """Rows the report can apply now: confirmed ones plus everything that passes the automatic checks.
    Rows that cannot be written in this modpack (see write_route) are reported apart, not as waiting."""
    curseforge=is_curseforge(session['instance']) if session.get('instance') else False
    tooltips=tooltip_texts(session.get('rows',[]))
    return sum(bool(r.get('supported') and r.get('changed') and not r.get('installed') and r.get('origin')!='untranslated'
                    and (r.get('reviewed') or row_fits(r))
                    and write_route(r,curseforge) in WRITTEN_ROUTES
                    and (not (managed(curseforge,r) and r.get('kind')=='class_display' and r.get('tooltips')) or any(
                        (r['source'].split('!/')[0],key,resource) in tooltips for key,_,_,resource in r['tooltips'])))
               for r in session.get('rows',[]))


def auto_confirm_safe(session):
    """Approve validated player-text candidates for the one-click workflow.

    This is deliberately not labelled ``manual``: provenance stays attached to
    every row, while the structural checks already performed by plan/AI are
    recorded as the reason the user did not need to review thousands of rows.
    """
    count = 0
    for row in session.get('rows', []):
        if (row.get('supported') and row.get('changed') and row.get('origin') != 'untranslated'
                and not row.get('installed') and not row.get('reviewed') and row_fits(row)):
            row['reviewed'] = True
            row['review_method'] = 'auto_validated_one_click'
            row['auto_review_reason'] = '已完成來源比對與格式檢查；具體疑點另外列出，不代表人工或遊戲內驗收'
            count += 1
    session['auto_confirmed_count'] = count
    session['automatic_apply_notice'] = ('已自動套用通過格式與來源檢查的玩家文字；'
                                         'AI／參考庫來源仍保留，未宣稱人工逐筆校對。')
    write_json(Path(session['report']) / 'session.json', session)
    return session


def target_for(row):
    # Loose config files are recorded by their path alone (config/x.json), without an archive part.
    outer,path=row['source'].split('!/',1) if '!/' in row['source'] else ('instance',row['source'])
    if row.get('kind','language')=='language':  # reports from early versions had language rows only
        path=re.sub(r'/(?:en_us|zh_cn|zh_tw)\.(json|lang|snbt|local)$',r'/zh_tw.\1',path,flags=re.I)
    else:
        path=re.sub(r'/en_us(_0)?/',r'/zh_tw\1/',path,flags=re.I)  # _0: Ice and Fire's bestiary (lang/bestiary/en_us_0/)
    if outer=='instance':return path,None
    return outer,path


def quest_file(raw):
    """A quest language file being written, as flat rows (key and key[index]); {} when it does not exist yet."""
    return quest_lang.flatten(quest_lang.parse(raw.decode('utf-8-sig'))) if raw else {}


def quest_content(instance, name, raw, flat):
    """The zh_tw quest file: the English file's layout with this batch's lines and what zh_tw already held."""
    english=quest_lang.parse(contained(instance,re.sub(r'zh_tw\.snbt$','en_us.snbt',name,flags=re.I)).read_bytes().decode('utf-8-sig'))
    try:existing=quest_lang.parse(raw.decode('utf-8-sig')) if raw else {}
    except ValueError:existing={}  # an unreadable zh_tw the scan recorded as broken is rebuilt from the English
    return quest_lang.dump(flat,english,existing)


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
        # Known dedicated servers must not block an unrelated client instance; a server running in the modpack's own
        # folder was caught by its working folder above. fabric-server-launch.jar is what 建立伺服器 writes into run.bat
        # for Fabric (server_pack), started with relative paths only.
        if re.search(r'--launchtarget\s+\S*server\b|net\.minecraft\.server\.main|fabricserverlauncher|fabric-server-launch(?:er)?\.jar\b|server\.jar\b',lower) and target not in lower:
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


# Written by versions before 0.10.0 when KubeJS was absent; still recognised as ours, never as a player's mod.
PACK_MOD_FILE = 'mods/mctranslator_zh_tw.jar'


def is_nested(row):
    return row['source'].count('!/')>=2


def read_archive_entry(instance, outer, entry):
    """Read an entry of a mod jar; 'inner.jar!/path' reaches into jar-in-jar libraries."""
    with zipfile.ZipFile(contained(instance,outer)) as z:
        if '!/' not in entry:return z.read(entry) if entry in z.namelist() else None
        inner,rest=entry.split('!/',1)
        with zipfile.ZipFile(io.BytesIO(z.read(inner))) as nested:
            return nested.read(rest) if rest in nested.namelist() else None


RESOURCE_PACK_FILE = 'resourcepacks/MCTranslator-zh_tw.zip'
RESOURCE_PACK_ID = 'file/MCTranslator-zh_tw.zip'
MOD_RESOURCES = 'mod_resources'  # NeoForge/Forge: every mod's own assets as one pack
PACK_SOURCES = 'mctranslator.json'  # inside the pack: which mod file (and SHA-256) each translated file belongs to
# Resource pack format per Minecraft version (first version with that format).
PACK_FORMATS = [((1,6),1),((1,9),2),((1,11),3),((1,13),4),((1,15),5),((1,16,2),6),((1,17),7),((1,18),8),((1,19),9),
                ((1,19,3),12),((1,19,4),13),((1,20),15),((1,20,2),18),((1,20,3),22),((1,20,5),32),((1,21),34),
                ((1,21,2),42),((1,21,4),46),((1,21,5),55),((1,21,6),63),((1,21,7),64)]


def pack_format(version, formats=PACK_FORMATS, unknown=34):
    """The resource pack format (or data pack format, with DATA_PACK_FORMATS) for a Minecraft version like
    '1.21.1'; `unknown` when the version is not known."""
    try:wanted=tuple(int(x) for x in re.findall(r'\d+',str(version))[:3])
    except ValueError:wanted=()
    if len(wanted)<2:return unknown
    return max((f for v,f in formats if v<=wanted),default=unknown)


def pack_metadata(instance):
    from .desktop_references import minecraft_version
    fmt=pack_format(minecraft_version(instance))
    pack=dict(pack_format=fmt,description='MC Translator 繁體中文翻譯（自動產生，只含翻譯文字）')
    if fmt>=18:pack['supported_formats']=dict(min_inclusive=fmt,max_inclusive=fmt)  # 1.20.2+ reads this
    return json.dumps(dict(pack=pack),ensure_ascii=False,indent=2)


LOOSE_TEXT_KINDS = ('config','snbt_display_array','script_candidate','binary_config_candidate')
# scripts/: CraftTweaker; vaultpatcher/modules/: the words VaultPatcher puts in place of a class's own (pair values only).
LOOSE_TEXT_ROOTS = ('config/','defaultconfigs/','kubejs/','scripts/','tacz/','tlm_custom_pack/','vaultpatcher/modules/')
LOOSE_TEXT_SUFFIXES = ('.json','.snbt','.toml','.txt','.js','.zs','.cfg','.yaml','.yml','.properties','.data','.cache')
BINARY_CONFIG_SUFFIXES = ('.data','.cache')
NOT_THIS_LANGUAGE = {'lang','langs','i18n','locale','locales','.archive-unpack'}


def other_language_file(path):
    """A file holding another language's text (YSM's lang/zh_cn.json, WorldEdit's unpacked zh-CN/strings.json):
    its Simplified Chinese is that language, not something to convert."""
    parts=PurePosixPath(path).parts
    for part in parts[:-1]+(PurePosixPath(path).stem,):
        if part.casefold() in NOT_THIS_LANGUAGE:return True
        if re.fullmatch(r'[a-z]{2,3}[_-][a-z]{2,4}',part,re.I) and part.casefold().replace('-','_')!='zh_tw':return True
    return False


FILE_NAME = re.compile(r'\.(?:zip|jar|json5?|png|jpe?g|gif|webp|txt|mcmeta|ogg|wav|mp3|nbt|snbt|toml|js|zs|cfg|properties|dat|lang|ttf|otf'
                       r'|mcfunction|schem|schematic|litematic|mcpack|mrpack)\s*$',re.I)
NOT_NAMED_HERE = ('saves','logs','crash-reports','backups','screenshots','.cache','cache','local')


def original_file_name(instance, name, cache):
    """The name of a file in the modpack that `name` is its Taiwan-converted form of, when no file is called `name`
    itself; '' otherwise. `cache` holds the modpack's file names between calls."""
    if 'names' not in cache:
        names=set()
        for top in Path(instance).iterdir() if Path(instance).is_dir() else ():
            if top.name.casefold() in NOT_NAMED_HERE:continue
            names.add(top.name)
            if top.is_dir():
                for _,dirs,files in os.walk(top):
                    names.update(dirs);names.update(files)
        cache['names']=names
        cache['converted']={}
        for n in names:
            if HAN.search(n) and has_simplified(n):
                for converted in (to_taiwan(n),taiwan_wording(to_taiwan(n))):cache['converted'].setdefault(converted,n)
    stripped=name.strip()
    if stripped in cache['names']:return ''
    original=cache['converted'].get(stripped)
    return name.replace(stripped,original) if original else ''


def convertible(row):
    """A string in a config, quest, KubeJS or CraftTweaker script file (not a key) whose Chinese is converted in place to
    Taiwan wording. Scripts count only for their Chinese: English in them stays a candidate for checking."""
    source=row.get('source') or ''
    # unverified: a file no reader covers (Audit.unverified_literals); converted, but not counted as shown.
    return (row.get('kind') in LOOSE_TEXT_KINDS and '!/' not in source and not source.startswith('saves/')
            and (source.startswith(LOOSE_TEXT_ROOTS) or bool(row.get('unverified')))
            and source.endswith(LOOSE_TEXT_SUFFIXES) and not other_language_file(source)
            and isinstance(row.get('current'),str) and bool(HAN.search(row['current'])))


def vaultpatcher_cache(instance, name, before, after, records=()):
    """Records removing VaultPatcher's cached classes for the module entries whose words changed.

    VaultPatcher 1.5.2 (core.cache.ClassCache.updated) reuses vaultpatcher/cache/<class>.class for as long as the mod's
    own class is unchanged (debug_mode.use_cache, on by default), so a converted module would still show the old words.
    Without the cache it patches the class from the module again at the next start and writes a new cache."""
    try:old,new=parse(before),parse(after)
    except ValueError:return []
    if not isinstance(old,list) or not isinstance(new,list) or len(old)!=len(new):return []
    classes=set()
    for a,b in zip(old,new):
        if a!=b and isinstance(b,dict):
            target=b.get('target_class')
            classes|={c for c in (target if isinstance(target,list) else [target]) if isinstance(c,str) and c.strip()}
    taken={r['file'].casefold() for r in records};found=[]
    for c in sorted(classes):
        for suffix in ('.class','.class.sha256'):
            rel='vaultpatcher/cache/'+c.strip().strip('/').replace('.','/')+suffix
            try:path=contained(instance,rel)
            except ValueError:continue
            if path.is_file() and rel.casefold() not in taken:
                taken.add(rel.casefold());found.append(dict(file=rel,before=file_hash(path),after=None,reviewed=True,verified=True))
    return found


def rewrite_literals(raw, name, rows):
    """The file with each row's string replaced by its translation; everything else stays byte for byte.

    Rows keyed "line:index" (SNBT, TOML, TXT) name one string; JSON rows (keyed by their path) are found by
    their text, every non-key occurrence of it. Returns None when a row's string is no longer there.
    """
    suffix=PurePosixPath(name).suffix.casefold()
    if suffix in BINARY_CONFIG_SUFFIXES:
        try:
            replacements={tuple(json.loads(r['key'])):(r['current'],r['proposed']) for r in rows}
            if len(replacements)!=len(rows):return None
            return rewrite_binary_nbt(raw,replacements)
        except (KeyError,TypeError,ValueError,UnicodeError):return None
    bom=raw.startswith(b'\xef\xbb\xbf')
    text=raw[3 if bom else 0:].decode('utf-8')
    escaped=suffix in ('.json','.snbt','.json5')
    unquoted=suffix in ('.cfg','.properties') or bool(FANCYMENU.search(name)) or (suffix=='.txt' and plain_text(text))
    by_place={};by_text={};found=set()
    for r in rows:
        if re.fullmatch(r'\d+:\d+',r['key']):by_place[tuple(map(int,r['key'].split(':')))]=r
        else:by_text.setdefault(r['current'],[]).append(r)
    edits=[]
    for lineno,i,value,is_key,start,end in string_literals(text,suffix,name):
        r=by_place.get((lineno,i))
        if r is not None and value!=r['current']:return None
        # The same text twice in a JSON file is two rows with one translation (one per place in the file).
        same=[r] if r is not None else by_text.get(value,[]) if not is_key else []
        if not same:continue
        r=same[0];literal=text[start:end]
        new=(json.dumps(r['proposed'],ensure_ascii=literal.isascii()) if escaped
             else r['proposed'] if unquoted  # .cfg, .properties and FancyMenu values carry no quotes
             else literal[0]+r['proposed']+literal[-1])
        edits.append((start,end,new));found.update(id(x) for x in same)
    if len(found)<len(rows):return None
    for start,end,new in sorted(edits,reverse=True):text=text[:start]+new+text[end:]
    return (b'\xef\xbb\xbf' if bom else b'')+text.encode('utf-8')


class CurseForgeFiles(frozenset):
    """The mod files CurseForge installed in an instance (lower-case names); always true as a flag."""
    def __bool__(self):return True


def is_curseforge(instance):
    """CurseForge re-downloads every mod file it finds changed when the game starts, so text written
    into mod files there is lost; minecraftinstance.json marks an instance it manages.

    It can only put back files it installed itself (installedAddons): a jar the player added by hand has
    no download to restore (The Foll: ageofmythology, torchesbecomesunlight). Returns False, True when the
    record cannot be read (every file is then treated as CurseForge's), or the names of its files.
    """
    record=Path(instance)/'minecraftinstance.json'
    if not record.is_file():return False
    try:
        data=json.loads(record.read_text(encoding='utf-8-sig'))
        names=set()
        for addon in data['installedAddons']:
            f=addon.get('installedFile') or {}
            names|={str(f[k]).casefold() for k in ('fileName','fileNameOnDisk') if f.get(k)}
        return CurseForgeFiles(names)
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return True


def class_name(row):
    """The internal name (a/b/C) of the class a program-text row is in; inner classes count as their outer class."""
    inner=(row.get('source') or '').split('!/')[-1]
    return inner[:-6].split('$')[0] if inner.endswith('.class') else ''


def managed(curseforge, row):
    """Whether CurseForge would put back the mod file this row is written into (see is_curseforge)."""
    if not curseforge or curseforge is True:return bool(curseforge)
    path=target_for(row)[0] or ''
    return not path.startswith('mods/') or Path(path.split('!/')[0]).name.casefold() in curseforge


def pack_resource(entry):
    """Where a mod's resource goes in the translation resource pack: its path from assets/ on, else ''.

    Mods can carry a second copy of their text for older game versions (kaleidoscope_cookery keeps one in
    legacy_pack/assets/...); both are the same resource for the game, so both map to the same pack file.

    A mod's data/<mod>/lang/ file (Lenient Death through the bundled Server Translations API) goes to assets/<mod>/lang/:
    the game looks the key up in the resource packs' language files first and uses the data copy only when they lack
    it (Server Translations API 2.3.1 SystemDelegatedLanguage.get, vanilla before server translations), and a key
    sent to the player keeps its key, the server's text being only a fallback (TranslatableTextContentMixin).
    """
    inner=(entry or '').split('!/')[-1]
    m=re.match(r'(?:[^/]+/)*?(assets/.+)$',inner)
    if m:return m[1]
    m=re.fullmatch(r'data/([a-z0-9_.\-]+)/lang/([a-z]{2,3}_[a-z]{2,3}\.json)',inner)
    return f'assets/{m[1]}/lang/{m[2]}' if m else ''


HELD_CURSEFORGE = '是寫在模組程式裡的文字；CurseForge 啟動遊戲時會把改過的模組檔換回原版，寫入也會被洗掉，所以沒有寫入'
HELD_CURSEFORGE_DATA = '在模組檔裡、不是資源包能覆蓋的語系檔或書本；CurseForge 啟動遊戲時會把改過的模組檔換回原版，寫入也會被洗掉，所以沒有寫入'
HELD_MIXIN = '另一個模組會在遊戲啟動時修改這段程式，可能要找這句原文；改了可能讓遊戲無法啟動，所以沒有寫入'
HELD_OLD_REPORT = '這份報告是舊版程式產生的，還不知道哪些程式會被其他模組修改；請重新按「一鍵完整翻譯並套用」再寫入程式文字'
HELD_NESTED = '在內嵌函式庫的資料檔裡，資源包無法覆蓋，也不能安全改寫，所以沒有寫入'


HELD_TOOLTIP_PARTS = '是一段多行設定說明的其中一行；同一段還有其他行沒翻好，整段翻好才一起寫入'
HELD_TOOLTIP_CONFLICT = '同一設定語系鍵有不同譯文，為避免互相覆蓋，需先確認一致的譯文'


def tooltip_conflicts(rows):
    values=collections.defaultdict(lambda:collections.defaultdict(set));lengths=collections.defaultdict(set)
    for r in rows:
        if r.get('kind')!='class_display':continue
        for key,part,parts,resource in r.get('tooltips') or ():
            target=(r['source'].split('!/')[0],key,resource)
            values[target][part].add(r.get('proposed'));lengths[target].add(parts)
    return {target for target,lines in values.items() if len(lengths[target])!=1 or any(len(v)!=1 for v in lines.values())}


def tooltip_part(text, part, parts):
    """Line `part` of a config comment the pack holds joined from `parts` strings; None when it does not fit."""
    if not isinstance(text,str):return None
    lines=text.split('\n') if parts>1 else [text]
    return lines[part] if len(lines)==parts else None


def tooltip_texts(rows):
    """{(mod file, tooltip key, pack resource): comment text} for config comments whose every line is translated.

    A comment given as several strings is one tooltip, its lines joined by newlines (as the config builder
    joins them), so a key is written only when all its lines have Chinese.
    """
    groups=collections.defaultdict(dict)
    for r in rows:
        if r.get('kind')!='class_display':continue
        for key,part,parts,resource in r.get('tooltips') or ():
            groups[(r['source'].split('!/')[0],key,resource,parts)][part]=r
    texts={};conflicts=tooltip_conflicts(rows)
    for (jar,key,resource,parts),lines in groups.items():
        if (jar,key,resource) in conflicts:continue
        if len(lines)!=parts or any(r.get('origin')=='untranslated' or not r.get('supported') for r in lines.values()):continue
        if not any(HAN.search(r.get('proposed') or '') for r in lines.values()):continue
        texts[(jar,key,resource)]='\n'.join(lines[i]['proposed'] for i in range(parts))
    return texts


BOOK_SETTINGS = re.compile(r'(?:^|/)data/([a-z0-9_.\-]+)/patchouli_books/[^/]+/book\.json$')


def book_title(row):
    """(pack language file, key) for a Patchouli book's name or landing text written out in its book.json; else None.

    Patchouli shows both through Component.translatable (GuiBookLanding, checked in Patchouli 1.20.1-84), so the
    English sentence itself works as a language key: an entry keyed by it in the translation resource pack
    shows the Chinese, and the book.json in the mod's data folder (which no resource pack reaches) stays as it is.
    """
    source=row.get('source') or ''
    if (row.get('kind')!='book' or not isinstance(row.get('en'),str) or row.get('key') not in ('["name"]','["landing_text"]')
            or not source.startswith('mods/')):
        return None
    m=BOOK_SETTINGS.search(source.split('!/')[-1])
    return (f'assets/{m[1]}/lang/zh_tw.json',row['en']) if m else None


# Text a mod reads from data packs and shows as written (Whispering Quests' quests, see full_translation_audit.DATA_TEXT):
# a copy of each such file with the translation goes into a data pack of ours that OpenLoader puts above the mods.
# OpenLoader 19.0.5 (Forge 1.20.1, checked in its OpenLoaderRepositorySource) adds every pack in config/openloader/data
# as required, at Pack.Position.TOP and to existing worlds too; packs are ordered by name, so ours is named to come
# last, above the modpack's own OpenLoader packs. The mod files stay untouched, so CurseForge has nothing to put back.
# OpenLoader 21.1.5 (NeoForge 1.21.1, Tensura) reads config/openloader/packs instead (OpenLoaderRepositorySource:
# "openloader/packs", a pack with data/ is a data pack, PackSelectionConfig(required, TOP)), and load_data_packs in
# config/openloader/options.json switches it off; data_pack_file picks the folder the installed OpenLoader reads.
DATA_PACK_FILE = 'config/openloader/data/zz-MCTranslator-zh_tw.zip'
DATA_PACK_FILE_21 = 'config/openloader/packs/zz-MCTranslator-zh_tw.zip'
DATA_PACK_FILES = (DATA_PACK_FILE, DATA_PACK_FILE_21)
DATA_PACK_FORMATS = [((1,13),4),((1,15),5),((1,16,2),6),((1,17),7),((1,18),8),((1,18,2),9),((1,19),10),((1,19,4),12),
                     ((1,20),15),((1,20,2),18),((1,20,3),26),((1,20,5),41),((1,21),48),((1,21,2),57),((1,21,4),61),
                     ((1,21,5),71),((1,21,6),80),((1,21,7),81)]
HELD_NO_DATAPACK = ('在模組的資料檔裡，只能用資料包蓋過；這個整合包沒有讓每個世界自動讀取資料包的 OpenLoader，'
                    '所以沒有寫入')
WRITTEN_ROUTES = ('pack','file','datapack')


def data_resource(row):
    """Where a data_text row's file is in a data pack (data/<mod>/<kind>/...json), else ''. The last data/ folder of
    the path counts: OpenLoader keeps a pack as config/openloader/data/<pack>/data/<mod>/..."""
    if row.get('kind')!='data_text':return ''
    parts=(row.get('source') or '').split('!/')[-1].split('/')
    starts=[i for i,p in enumerate(parts) if p=='data' and len(parts)-i>=4]
    return '/'.join(parts[starts[-1]:]) if starts and parts[-1].endswith('.json') else ''


def data_pack_file(instance):
    """The translation data pack's place for the OpenLoader installed: config/openloader/data (OpenLoader 19) or,
    where only config/openloader/packs exists, that folder (OpenLoader 21); see DATA_PACK_FILE."""
    instance=Path(instance)
    if not (instance/'config/openloader/data').is_dir() and (instance/'config/openloader/packs').is_dir():return DATA_PACK_FILE_21
    return DATA_PACK_FILE


def reads_data_packs(instance):
    """Whether OpenLoader loads data packs from the folder data_pack_file names, for every world."""
    instance=Path(instance)
    try:
        options=json.loads((instance/'config/openloader/advanced_options.json').read_text(encoding='utf-8-sig'))
        enabled=options.get('dataPacks',{}).get('enabled',True) is not False
    except (OSError,ValueError,AttributeError):enabled=True
    try:  # OpenLoader 21: {"load_data_packs": {"value": false}} switches data packs off
        newer=json.loads((instance/'config/openloader/options.json').read_text(encoding='utf-8-sig'))
        enabled=enabled and (newer.get('load_data_packs') or {}).get('value',True) is not False
    except (OSError,ValueError,AttributeError):pass
    try:loader=any(p.name.casefold().startswith('openloader') for p in (instance/'mods').glob('*.jar'))
    except OSError:loader=False
    return enabled and loader and (instance/data_pack_file(instance)).parent.is_dir()


def read_data_pack(instance):
    """(files, records) of the translation data pack this program made earlier; empty when there is none.
    records: {resource: {source, sha256 of the original file, texts: {key: [original, translation]}}}."""
    path=Path(instance)/data_pack_file(instance)
    if not path.is_file():return {},{}
    try:
        with zipfile.ZipFile(path) as z:
            files={n:z.read(n) for n in z.namelist() if re.fullmatch(r'data/[a-z0-9_.\-]+/.+\.json',n)}
            records=json.loads(z.read(PACK_SOURCES).decode('utf-8')).get('files',{}) if PACK_SOURCES in z.namelist() else {}
    except (OSError,ValueError,zipfile.BadZipFile):return {},{}
    return files,(records if isinstance(records,dict) else {})


def data_original(instance, source):
    """The bytes of the file a data_text row was read from (in a mod file, a pack or loose); None when it is gone."""
    path,entry=target_for(dict(source=source,kind='data_text'))
    try:
        if entry is None:
            p=contained(instance,path);return p.read_bytes() if p.is_file() else None
        return read_archive_entry(instance,path,entry) if contained(instance,path).is_file() else None
    except (OSError,KeyError,zipfile.BadZipFile):return None


def set_at(value, path, text):
    for k in path[:-1]:value=value[k]
    value[path[-1]]=text


def build_data_pack(instance, home, staged, rows):
    """Stage the translation data pack: each file of a translated data_text row, copied from the file the game reads
    with the translated strings in place. Every file is built again from its original each time, so a mod update
    (new rewards, coordinates) is never hidden under an old copy; text the original no longer holds is dropped."""
    files,records=read_data_pack(instance)
    batch=collections.defaultdict(list)
    for r in rows:batch[data_resource(r)].append(r)
    built={};kept={}
    for resource in sorted(set(records)|set(batch)):
        record=records.get(resource) if isinstance(records.get(resource),dict) else {}
        source=batch[resource][0]['source'] if batch.get(resource) else record.get('source')
        raw=data_original(instance,source) if isinstance(source,str) else None
        if raw is None:
            if batch.get(resource):raise changed_since_scan(home,instance,source)
            continue  # the mod (or that version of it) is gone: its copy is no longer needed
        base=parse(raw);texts={}
        if record.get('source')==source:
            for key,pair in (record.get('texts') or {}).items():
                try:
                    if isinstance(pair,list) and len(pair)==2 and at(base,json.loads(key))==pair[0]:texts[key]=pair
                except (ValueError,TypeError):continue
        for r in batch.get(resource,()):
            if at(base,json.loads(r['key']))!=r['mod_text']:raise changed_since_scan(home,instance,source)
            texts[r['key']]=[r['mod_text'],r['proposed']]
        texts={k:v for k,v in texts.items() if v[0]!=v[1]}
        if not texts:continue
        for key,(_,text) in texts.items():set_at(base,json.loads(key),text)
        built[resource]=json.dumps(base,ensure_ascii=False,indent=2).encode('utf-8')
        kept[resource]=dict(source=source,sha256=hashlib.sha256(raw).hexdigest(),texts=dict(sorted(texts.items())))
    pack_file=data_pack_file(instance)
    src=Path(instance)/pack_file;before=file_hash(src) if src.exists() else None
    if not built:
        return [dict(file=pack_file,before=before,after=None,reviewed=True,verified=True)] if before else []
    from .desktop_references import minecraft_version
    fmt=pack_format(minecraft_version(instance),DATA_PACK_FORMATS,15)
    meta=dict(pack_format=fmt,description='MC Translator 繁體中文翻譯（自動產生，只改任務等文字）')
    if fmt>=18:meta['supported_formats']=dict(min_inclusive=fmt,max_inclusive=fmt)
    dst=contained(staged,pack_file);dst.parent.mkdir(parents=True,exist_ok=True)
    stamp=(2020,1,1,0,0,0)
    with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
        def put(name,data):w.writestr(zipfile.ZipInfo(name,stamp),data,zipfile.ZIP_DEFLATED)
        put('pack.mcmeta',json.dumps(dict(pack=meta),ensure_ascii=False,indent=2))
        put(PACK_SOURCES,json.dumps(dict(format=1,files=kept),ensure_ascii=False,indent=2,sort_keys=True))
        for name,content in sorted(built.items()):put(name,content)
    after=file_hash(dst)
    if before==after:
        dst.unlink();return []
    return [dict(file=pack_file,before=before,after=after,reviewed=True,verified=True)]


def write_route(row, curseforge):
    """'pack' (the translation resource pack), 'file' (the file itself), 'datapack' (the translation data pack),
    or why the row is not written.

    Language files and book pages of mods go into the resource pack, so the mods stay untouched.
    Text inside a mod's program (class) or its data folder cannot be put in a resource pack; it is
    written into the mod file only where the launcher does not put the original back. The exception is a
    config comment that config screens look up in the language files (row['tooltips']): under CurseForge
    it goes into the pack as that key. Data files a known mod shows as written go into the data pack.
    """
    if row.get('kind')=='data_text':return HELD_NO_DATAPACK if row.get('no_data_pack') else 'datapack'
    path,entry=target_for(row)
    if entry is None or not path.startswith('mods/'):return 'file'
    if book_title(row) or (row.get('kind')!='class_display' and pack_resource(entry)):return 'pack'
    curseforge=managed(curseforge,row)
    if curseforge and row.get('kind')=='class_display' and row.get('tooltips') and not is_nested(row):return 'pack'
    if curseforge:return HELD_CURSEFORGE if row.get('kind')=='class_display' else HELD_CURSEFORGE_DATA
    if is_nested(row):return HELD_NESTED
    return 'file'


def read_resource_pack(instance):
    """(files, sources) of the translation resource pack this program made earlier; empty when there is none."""
    path=Path(instance)/RESOURCE_PACK_FILE
    if not path.is_file():return {},{}
    with zipfile.ZipFile(path) as z:
        files={n:z.read(n) for n in z.namelist() if n.startswith('assets/')}
        try:sources=json.loads(z.read(PACK_SOURCES).decode('utf-8')).get('sources',{}) if PACK_SOURCES in z.namelist() else {}
        except ValueError:sources={}
    return files,sources


def build_pack(instance, staged, pack_rows, session, notify, pack_base=None):
    """Stage the text of mod files as one resource pack instead of rewriting the mods.

    CurseForge puts back the original of any mod file that changed, so translations written into
    mods disappear the next time the game starts. A resource pack in resourcepacks/ is left alone,
    and the game shows its zh_tw above the mods' own. Each language file in it carries the mod's own
    zh_tw, the earlier pack content and this batch, so it is complete on its own. The pack records
    which mod file (and its SHA-256) each file translates, for sharing and for noticing mod updates.
    """
    resources=collections.defaultdict(list)
    for outer,entry,row in pack_rows:
        resources[pack_resource(entry)].append((outer,entry,row))
    existing,sources=read_resource_pack(instance) if pack_base is None else pack_base
    repaired={n for _,n,*_ in session.get('repairs',[])}
    built={};hashes={}
    for i,(resource,items) in enumerate(sorted(resources.items())):
        if i%50==0:notify(int(40*i/max(1,len(resources))),'整理翻譯資源包',resource)
        # The mod's main copy (assets/ at the top of the file) is what the game uses; it is read first and written last.
        items=sorted(items,key=lambda item:item[1].split('!/')[-1].startswith('assets/'),reverse=True)
        outer,entry,first=items[0];rows=[row for *_,row in reversed(items)]
        previous=existing.get(resource)
        mine=sources.get(resource) if isinstance(sources.get(resource),dict) else {}
        mine={jar:h for jar,h in mine.items() if not generated_copy(jar)}  # recorded by versions before 0.21.0
        for jar in {o for o,*_ in items}:
            if jar not in hashes:hashes[jar]=file_hash(contained(instance,jar))
            mine[jar]=hashes[jar]
        sources[resource]=mine
        if first['kind']=='book' and first['key']=='text':
            built[resource]=first['proposed'].encode('utf-8');continue
        own=read_archive_entry(instance,outer,entry)
        try:data=parse(own) if own and resource.endswith('.json') else dict(l.split('=',1) for l in own.decode('utf-8-sig').splitlines() if '=' in l and not l.startswith('#')) if own else {}
        except ValueError:
            if entry.split('!/')[-1] not in repaired:raise  # a zh_tw the scan already found broken is rebuilt
            data={}
        if first['kind']=='book' and not own:
            data=parse(read_archive_entry(instance,outer,first['source'].split('!/',1)[1]))  # English structure
        if previous:
            before=parse(previous) if resource.endswith('.json') else dict(l.split('=',1) for l in previous.decode('utf-8-sig').splitlines() if '=' in l)
            data=before if first['kind'] in ('book','inline_lang') else {**data,**before}
        if first['kind']=='book' and first.get('cn_shape'):
            # A page the author wrote out only in Simplified Chinese (Audit cn_shape): built on the Chinese page, every
            # paragraph from this run's decision, so an earlier copy shaped like the short English page is replaced.
            inner=first['source'].split('!/',1)[1]
            data=parse(read_archive_entry(instance,outer,re.sub(r'/en_us/','/zh_cn/',inner,count=1)))
            # Paragraphs already in Chinese in the pack copy and unchanged this run are not in the session (counted as
            # already Chinese): they keep that copy's words, so no Simplified paragraph of the base is left behind.
            def overlay(node,old):
                for k,v in (node.items() if isinstance(node,dict) else enumerate(node) if isinstance(node,list) else ()):
                    try:prior=old[k]
                    except (KeyError,IndexError,TypeError):continue
                    if isinstance(v,str) and isinstance(prior,str) and HAN.search(prior):node[k]=prior
                    else:overlay(v,prior)
            if previous:overlay(data,parse(previous))
            rows=[r for r in session['rows'] if r['source']==first['source'] and r['kind']=='book']
        for r in rows:
            if r['kind']=='language' and r.get('rich'):
                # owo-lib rich value: the English component with this piece's words replaced (colours kept).
                key,*path=json.loads(r['key'])
                if not isinstance(data.get(key),(dict,list)):data[key]=copy.deepcopy(r['rich_en'])
                node=data[key]
                for part in path[:-1]:node=node[part]
                node[path[-1]]=r['proposed'];continue
            if r['kind']=='language':data[r['key']]=r['proposed'];continue
            if r['kind']=='inline_lang':
                node=node_at(data,json.loads(r['key']));node[inline_field(r['source'],node)]=r['proposed'];continue  # beside en_us
            if r.get('tooltip_key'):data[r['tooltip_key']]=r['tooltip_text'];continue  # a config comment, see tooltip_texts
            keys=json.loads(r['key']);node=data
            for key in keys[:-1]:node=node[key]
            node[keys[-1]]=r['proposed']
        built[resource]=(json.dumps(data,ensure_ascii=False,indent=2) if resource.endswith('.json')
                         else '\n'.join(f'{k}={v}' for k,v in data.items())+'\n').encode('utf-8')
    session['pack_target']='resourcepack'
    return stage_resource_pack(instance,staged,{**existing,**built},sources)


def stage_resource_pack(instance, staged, files, sources):
    """Write the translation resource pack into the staging folder; [] when it would equal the one in place."""
    dst=contained(staged,RESOURCE_PACK_FILE);dst.parent.mkdir(parents=True,exist_ok=True)
    # Fixed timestamps and order: the same translations always give the same file, so a rerun writes nothing.
    stamp=(2020,1,1,0,0,0)
    with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
        def put(name,data):w.writestr(zipfile.ZipInfo(name,stamp),data,zipfile.ZIP_DEFLATED)
        put('pack.mcmeta',pack_metadata(instance))
        put(PACK_SOURCES,json.dumps(dict(format=1,sources={k:sources[k] for k in sorted(sources)}),ensure_ascii=False,indent=2,sort_keys=True))
        for name,content in sorted(files.items()):put(name,content)
    src=Path(instance)/RESOURCE_PACK_FILE
    before=file_hash(src) if src.exists() else None
    after=file_hash(dst)
    if before==after:
        dst.unlink();return []
    return [dict(file=RESOURCE_PACK_FILE,before=before,after=after,reviewed=True,verified=True)]


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
                # Some valid game jars have overlapping central-directory sizes only on empty directory
                # entries (celestial_forge 1.1.7). Java accepts them and every real file is readable; copying
                # the directory as empty avoids Python's false "possible zip bomb" without weakening checks
                # for overlapping file data.
                w.writestr(copy.copy(info),b'' if info.is_dir() else z.read(info.filename))
        for n,b in modified.items():
            # Retain entry metadata; new entries get a fixed timestamp. The same text
            # recipe and original archive must produce the same result on both computers.
            info=copy.copy(z.getinfo(n)) if n in z.namelist() else zipfile.ZipInfo(n,(2020,1,1,0,0,0))
            w.writestr(info,b)
    with zipfile.ZipFile(dst) as check:
        if check.testzip():raise ValueError('ZIP 完整性驗證失敗：'+label)
        for n in z.namelist():
            if n not in modified and not n.endswith('/') and not is_jar_signature_file(n) and check.read(n)!=z.read(n):
                raise ValueError('非翻譯內容被改動：'+n)


def with_option(text, name, value):
    """options.txt text with `name:value`, replacing the line when there is one."""
    if re.search(rf'(?m)^{name}:',text):return re.sub(rf'(?m)^{name}:.*$',lambda _:f'{name}:{value}',text)
    return text+('' if not text or text.endswith('\n') else '\n')+f'{name}:{value}\n'


def enabled_packs(text):
    """The resourcePacks list of options.txt; None when the line is missing or unreadable."""
    m=re.search(r'(?m)^resourcePacks:(.*)$',text)
    try:packs=json.loads(m[1]) if m else None
    except ValueError:return None
    return packs if isinstance(packs,list) and all(isinstance(p,str) for p in packs) else None


PACK_ID = re.compile(r'(?!openloader/)[a-z0-9_.\-]+[:/][a-z0-9_.\-/]+')


def game_added_packs(instance):
    """Resource packs the game enables on its own, which it puts above every pack options.txt names.

    OpenLoader 19 (Forge 1.20.1) enables everything in config/openloader/resources as "resources/<name>".
    Other mods' packs (Fragmentum's "generated/fragmentum_layer") are read from the game's last log: the ids
    it loaded above every pack the list named. Ids the log could not spell (Windows writes it in the system
    code page, so Simplified Chinese names come out as ?) are left out.
    """
    instance=Path(instance);found=[]
    folder=instance/'config/openloader/resources'
    try:
        enabled=json.loads((instance/'config/openloader/advanced_options.json').read_text(encoding='utf-8-sig')).get('resourcePacks',{}).get('enabled',True) is not False
    except (OSError,ValueError,AttributeError):enabled=True
    if enabled and folder.is_dir() and any(p.name.casefold().startswith('openloader') for p in (instance/'mods').glob('*.jar')):
        found+=[f'resources/{p.name}' for p in sorted(folder.iterdir(),key=lambda p:p.name.casefold())
                if p.is_dir() or p.suffix.casefold()=='.zip']
    try:raw=(instance/'logs/latest.log').read_bytes()[-4*1024*1024:]
    except OSError:raw=b''
    lines=[l for l in raw.split(b'\n') if b'Reloading ResourceManager: ' in l]
    if lines:
        text=lines[-1].split(b'Reloading ResourceManager: ',1)[1].rstrip(b'\r')
        try:loaded=text.decode('utf-8').split(', ')
        except UnicodeDecodeError:loaded=text.decode('utf-8','replace').split(', ')
        try:listed=enabled_packs((instance/'options.txt').read_text(encoding='utf-8')) or []
        except OSError:listed=[]
        named=set(listed)-set(found)
        last=max((i for i,p in enumerate(loaded) if p in named),default=None)
        if last is not None:
            # Only plain ids: KubeJS's built-in packs log a display name with commas and stay where they are,
            # and NeoForge OpenLoader logs a full path.
            found+=[p for p in loaded[last+1:] if p not in named and p not in found and PACK_ID.fullmatch(p)]
    return found


def options_record(instance, staged, set_language=False, enable_pack=False):
    """Stage options.txt so the game opens in Traditional Chinese (when asked) and uses the translation
    resource pack, placed last so it is above every other pack. None when nothing needs to change."""
    src=instance/'options.txt';text=src.read_text(encoding='utf-8') if src.exists() else '';new=text
    if set_language:new=with_option(new,'lang','zh_tw')
    if enable_pack:
        packs=enabled_packs(new)
        if packs is None and re.search(r'(?m)^resourcePacks:',new):
            raise ValueError('遊戲設定檔 options.txt 的資源包清單格式看不懂，沒有自動啟用翻譯資源包。'
                             '請開遊戲在「資源包」裡啟用「MCTranslator-zh_tw」並移到最上面；其他譯文已保存。')
        packs=[p for p in (packs if packs is not None else ['vanilla']) if p!=RESOURCE_PACK_ID]
        # Forge/NeoForge add the mods' own resources (mod_resources) at the top when the list does not name
        # them, above this pack, so a mod's own zh_tw that is still English (Explorer's Compass) would win.
        # Naming it keeps it below; the game drops the name where no such pack exists (Fabric).
        if MOD_RESOURCES not in packs:packs.append(MOD_RESOURCES)
        # Same for packs the game turns on by itself (OpenLoader's folder, packs a mod generates): when the
        # list does not name them they go on top of it, above this pack (seen in The Foll: a dog zh_tw won).
        packs+=[p for p in game_added_packs(instance) if p not in packs]
        packs.append(RESOURCE_PACK_ID)
        new=with_option(new,'resourcePacks',json.dumps(packs,ensure_ascii=False,separators=(',',':')))
    if new==text:return None
    dst=staged/'options.txt';dst.write_text(new,encoding='utf-8')
    return dict(file='options.txt',before=file_hash(src) if src.exists() else None,after=file_hash(dst),reviewed=True,verified=True)


DEFAULT_OPTIONS_FILE = 'config/defaultoptions-common.toml'


def toml_array_end(text, start):
    """Index of the `]` closing the TOML array whose `[` is at `start` (quoted `]` skipped); None if unclosed."""
    quote=None;i=start+1
    while i<len(text):
        c=text[i]
        if quote:
            if c=='\\' and quote=='"':i+=1
            elif c==quote:quote=None
        elif c in '"\'':quote=c
        elif c=='#':
            i=text.find('\n',i)
            if i<0:return None
        elif c==']':return i
        i+=1
    return None


def default_packs_record(instance, staged):
    """Keep the translation pack on when Default Options applies the pack's preset list.

    Default Options (BlayTheNinth, 21.1 DefaultResourcePacksHandler.loadDefaults) replaces the selected resource
    packs with defaultResourcePacks the first time the game starts (defaultoptions.journal.json has no
    "resource-packs" yet), so a translation pack switched on in options.txt before that start is switched off
    again (seen in COBBLEVERSE). Adding it at the end of the list keeps it on top. None when nothing changes.
    """
    import tomllib
    src=instance/DEFAULT_OPTIONS_FILE
    try:text=src.read_text(encoding='utf-8');packs=tomllib.loads(text).get('defaultResourcePacks')
    except (OSError,ValueError):return None
    if not packs or not isinstance(packs,list) or RESOURCE_PACK_ID in packs:return None
    m=re.search(r'(?m)^[ \t]*defaultResourcePacks[ \t]*=[ \t]*\[',text)
    end=toml_array_end(text,m.end()-1) if m else None
    if end is None:return None
    head=text[:end].rstrip()
    new=head+('' if head.endswith((',','[')) else ',')+json.dumps(RESOURCE_PACK_ID)+' '+text[end:]
    try:
        if tomllib.loads(new).get('defaultResourcePacks')!=packs+[RESOURCE_PACK_ID]:return None
    except ValueError:return None
    dst=staged/DEFAULT_OPTIONS_FILE;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(new,encoding='utf-8')
    return dict(file=DEFAULT_OPTIONS_FILE,before=file_hash(src),after=file_hash(dst),reviewed=True,verified=True)


SPACE_MARGIN = 300*1024*1024
INTERRUPTED = ('backed_up','rollback_incomplete','restoring')


def require_space(instance, home, files):
    """Stop before anything is written when the drives cannot hold the work: a staged copy and a
    backup of every file to be changed (beside the program) and the rewritten files (in the modpack)."""
    sizes=[p.stat().st_size for p in (contained(instance,f) for f in files) if p.is_file()]
    needs={}
    for folder,amount in ((home,2*sum(sizes)),(instance,max(sizes,default=0))):
        drive=Path(folder).resolve().anchor or str(Path(folder).resolve())
        needs[drive]=needs.get(drive,0)+amount
    for drive,amount in needs.items():
        free=shutil.disk_usage(drive).free
        if free<amount+SPACE_MARGIN:
            raise ValueError(f'硬碟空間不足：這次套用需要約 {(amount+SPACE_MARGIN)//1048576:,} MB，{drive} 只剩 {free//1048576:,} MB。'
                             '請清出空間後按「重試套用」；譯文已保存，遊戲檔案沒有修改。')


def interrupted_batches(home, instance=None):
    """Batches whose writing or restoring stopped half-way (crash, power cut), newest first."""
    found=[]
    for p in sorted((Path(home)/'output').glob('*/原始備份/*/_備份紀錄/manifest.json'),reverse=True):
        try:
            record=json.loads(p.read_text(encoding='utf-8'))
            if record.get('status') in INTERRUPTED and (instance is None or Path(record['instance']).resolve()==Path(instance).resolve()):
                found.append((p.parents[1],record))
        except (OSError,ValueError,KeyError):continue
    return found


def changed_sources(session):
    """The first scanned file that no longer matches the scan and was not written by this batch itself, else ''."""
    ours={}
    for earlier in session.get('backups') or ([session['backup']] if session.get('backup') else []):
        try:ours.update({f['file']:f['after'] for f in json.loads((Path(earlier)/'_備份紀錄/manifest.json').read_text(encoding='utf-8'))['files']})
        except (OSError,ValueError,KeyError):pass
    for name,expected in session.get('source_hashes',{}).items():
        now=file_hash(contained(Path(session['instance']),name))
        if now!=expected and now!=ours.get(name):return name
    return ''


def changed_since_scan(home, instance, what):
    """Why a file no longer matches the scan, as the error to raise: a write that was cut short, or a later change."""
    if interrupted_batches(home,instance):
        return ValueError('上一次套用或還原中途中斷，模組包裡可能只寫入了一部分。'
                          '請先到「備份與還原」還原標示「中斷」的那一批，再回來按「重試套用」。')
    return ValueError('模組包的檔案在掃描後有變動（可能是啟動器更新或手動修改），請重新按「一鍵完整翻譯並套用」：'+what)


def waiting_note(notify, percent=80, stage='備份與套用'):
    """Tells the player why a write is taking long: another program is reading the file just written."""
    return lambda name:notify(percent,stage,f'「{name}」正被其他程式讀取（常見是啟動器或防毒掃描），稍等後自動再試')


def apply_session(session, home, notify):
    """Back up and write this batch. The staged copies are working files and are removed afterwards,
    whether the batch was written or stopped; the backup and its record are what is kept."""
    work=[]
    try:return stage_and_apply(session,home,notify,work)
    finally:
        for folder in work:shutil.rmtree(folder,ignore_errors=True)


def stage_and_apply(session, home, notify, work, stage_only=False, pack_base=None):
    instance=Path(session['instance']); report=Path(session['report'])
    ready=[r for r in session['rows'] if r.get('reviewed') and r.get('supported') and r.get('changed') and not r.get('installed')]
    curseforge=is_curseforge(instance);routes={id(r):write_route(r,curseforge) for r in ready}
    tooltips=tooltip_texts(session['rows']);conflicts=tooltip_conflicts(session['rows'])
    for r in ready:
        if routes[id(r)]=='pack' and r['kind']=='class_display' and not any(
                (r['source'].split('!/')[0],key,resource) in tooltips for key,_,_,resource in r['tooltips']):
            routes[id(r)]=HELD_TOOLTIP_CONFLICT if any(
                (r['source'].split('!/')[0],key,resource) in conflicts for key,_,_,resource in r['tooltips']) else HELD_TOOLTIP_PARTS
    # Program text is rewritten only with this run's knowledge of other mods' Mixins (reports from v0.18.0
    # and earlier have none; their program text waits for a new scan).
    patched=session.get('mixin_targets')
    for r in ready:
        if r['kind']=='class_display' and routes[id(r)]=='file' and r.get('origin')!='keep_original' and (
                patched is None or class_name(r) in patched):
            routes[id(r)]=HELD_MIXIN if patched is not None else HELD_OLD_REPORT
    selected=[r for r in ready if routes[id(r)] in WRITTEN_ROUTES]
    held=collections.Counter(routes[id(r)] for r in ready if routes[id(r)] not in WRITTEN_ROUTES)
    if not selected:
        raise ValueError('這一批沒有尚未套用的譯文。'+('（'+'；'.join(f'{n:,} 筆{why}' for why,n in held.items())+'）' if held else ''))
    if session.get('status')=='blocked':raise ValueError('此批次預檢未通過，不能套用。')
    if session.get('status')=='restored':raise ValueError('這一批已還原，請重新翻譯建立新的一批。')
    notify(1,'確認遊戲已關閉',f'準備把 {len(selected):,} 筆譯文寫入 {instance.name}')
    ensure_game_closed(instance)
    notify(3,'檢查原檔是否變動','比對掃描時記錄的檔案雜湊')
    # A batch may be applied in parts (e.g. an older version wrote only confirmed rows). Files this batch
    # already wrote are accepted at the hash that earlier write left; anything else must be unchanged.
    changed=changed_sources(session)
    if changed:raise changed_since_scan(home,instance,changed)
    changes=collections.defaultdict(list);pack_rows=[];data_rows=[]
    for row in selected:
        if not row_fits(row):raise ValueError('譯文格式或參數不一致：'+row['key'])
        path,entry=target_for(row); contained(instance,path)
        if routes[id(row)]=='datapack':data_rows.append(row);continue
        if routes[id(row)]=='pack' and row['kind']=='class_display':
            for key,_,_,resource in row['tooltips']:
                if (path,key,resource) in tooltips:pack_rows.append((path,resource,dict(row,tooltip_key=key,tooltip_text=tooltips[(path,key,resource)])))
            continue
        if routes[id(row)]=='pack' and book_title(row):
            resource,key=book_title(row);pack_rows.append((path,resource,dict(row,kind='language',key=key)));continue
        if routes[id(row)]=='pack':pack_rows.append((path,entry,row));continue
        changes[path].append((entry,row))
    require_space(instance,home,list(changes))
    staged=report/'staged'
    if staged.exists():
        staged=report/('staged-'+uuid.uuid4().hex[:8])
    staged.mkdir();work.append(staged)
    records=build_pack(instance,staged,pack_rows,session,notify,pack_base) if pack_rows else []
    if data_rows:records+=build_data_pack(instance,home,staged,data_rows)
    changed_classes=[]
    for i,(path,edits) in enumerate(changes.items()):
        notify(int(70*i/len(changes)),'驗證並準備套用',path)
        src=contained(instance,path); dst=contained(staged,path)
        before=file_hash(src)
        # A KubeJS language file can receive both the modpack's own KubeJS rows and embedded-library rows
        # staged by build_pack; build on that staged file so one merged file is written, not two.
        merged=dst.is_file() and any(r['file']==path for r in records)
        try:on_disk=parse(src.read_bytes()) if merged and src.exists() and path.endswith('.json') else {}
        except ValueError:on_disk={}
        by_entry=collections.defaultdict(list)
        for entry,row in edits:by_entry[entry].append(row)
        z=zipfile.ZipFile(src) if any(entry is not None for entry in by_entry) else None
        flow=None
        try:
            modified={}
            for entry,rows in by_entry.items():
                raw=(z.read(entry) if z and entry in z.namelist() else dst.read_bytes() if merged
                     else src.read_bytes() if not z and src.exists() else None)
                name=entry or path
                # Strings converted in place are written last, onto whatever the other rows made of the file.
                literal_rows=[r for r in rows if convertible(r)];rows=[r for r in rows if not convertible(r)]
                is_text=bool(rows) and rows[0]['kind']=='book' and rows[0]['key']=='text'
                if not rows:
                    content=raw
                elif rows[0]['kind']=='embedded_text':
                    content=embedded_text.rewrite(name,raw,{r['key']:(r['current'],r['proposed']) for r in rows})
                elif rows[0]['kind']=='class_display':
                    from .class_text import rewrite, JarFlow
                    if flow is None:flow=JarFlow.of_zip(z)  # the same proof as the scan: helpers and fields of this file
                    content=rewrite(raw,rows,flow)
                    changed_classes.append(content)
                elif is_text:
                    content=rows[0]['proposed'].encode('utf-8')
                else:
                    try:
                        data=(quest_file(raw) if name.endswith('.snbt') else parse(raw) if raw and name.endswith('.json')
                              else lang_table(raw.decode('utf-8-sig'),name) if raw else {})
                    except ValueError:
                        # Only zh_tw files the scan already recorded as unreadable may be rebuilt.
                        if not any(l==path and n==name or entry is None and path.endswith(n) for l,n,*_ in session.get('repairs',[])):raise
                        data={}
                    # Missing book target needs the English structure, never an empty object.
                    if not raw and rows[0]['kind']=='book':
                        sourcepath=rows[0]['source'].split('!/',1)[1]
                        data=parse(z.read(sourcepath) if z else contained(instance,sourcepath).read_bytes())
                    for r in rows:
                        if r['kind']=='language' and r.get('rich'):
                            key,*part=json.loads(r['key']);held=(on_disk if merged else data).get(key)
                            if (at(held,part) if isinstance(held,(dict,list)) else None)!=r['current']:
                                raise changed_since_scan(home,instance,path+' / '+key)
                            if not isinstance(data.get(key),(dict,list)):data[key]=copy.deepcopy(r['rich_en'])
                            node=data[key]
                            for step in part[:-1]:node=node[step]
                            node[part[-1]]=r['proposed']
                        elif r['kind']=='language':
                            # Compare with the file as it is on disk, not with library text merged in above.
                            on_file=(on_disk if merged else data).get(r['key'])
                            # A quest file this batch created earlier holds the English wherever no Chinese was
                            # known yet; that English is what a later write (AI's translation) replaces.
                            if on_file!=r['current'] and not (r['current'] is None and name.endswith('.snbt') and on_file==r.get('en')):
                                raise changed_since_scan(home,instance,path+' / '+r['key'])
                            data[r['key']]=r['proposed']
                        elif r['kind']=='inline_lang':
                            node=data
                            for key in json.loads(r['key']):node=node[key]
                            field=inline_field(r['source'],node)
                            if node.get(field)!=r['current']:raise changed_since_scan(home,instance,path)
                            node[field]=r['proposed']
                        else:
                            keys=json.loads(r['key']);node=data
                            for key in keys[:-1]:node=node[key]
                            # A book page this batch created earlier holds the English wherever no Chinese was
                            # known yet; that English is what a later write (AI's translation) replaces.
                            if raw and node[keys[-1]]!=r['current'] and not (r['current'] is None and node[keys[-1]]==r.get('en')):
                                raise changed_since_scan(home,instance,path)
                            node[keys[-1]]=r['proposed']
                    content=(quest_content(instance,name,raw,data) if name.endswith('.snbt')
                             else json.dumps(data,ensure_ascii=False,indent=2) if name.endswith('.json') else '\n'.join(f'{k}={v}' for k,v in data.items())+'\n').encode('utf-8')
                if literal_rows:
                    # Line-keyed strings are only ever alone in their file (SNBT/TOML/TXT have no other writer here).
                    content=rewrite_literals(content,name,literal_rows) if content else None
                    if content is None:raise changed_since_scan(home,instance,path)
                modified[entry]=content
            dst.parent.mkdir(parents=True,exist_ok=True)
            if z:rewrite_archive(z,dst,modified,path)
            else:dst.write_bytes(modified[None])
        finally:
            if z:z.close()
        if merged:records=[dict(r,after=file_hash(dst)) if r['file']==path else r for r in records]
        else:records.append(dict(file=path,before=before,after=file_hash(dst),reviewed=True,verified=True))
    for r in [r for r in records if VAULTPATCHER_MODULE.match(r['file']) and r.get('after')]:
        records+=vaultpatcher_cache(instance,r['file'],contained(instance,r['file']).read_bytes(),(staged/r['file']).read_bytes(),records)
    if changed_classes:
        from .class_text import check_java
        notify(71,'檢查程式文字',f'用 Java 解析 {len(changed_classes):,} 個修改過的 class，確認格式完整')
        check_java(changed_classes)
    uses_pack=any(r['file']==RESOURCE_PACK_FILE for r in records) or (instance/RESOURCE_PACK_FILE).is_file()
    try:record=options_record(instance,staged,session.get('set_language'),uses_pack)
    except ValueError as exc:
        # The translations are still written; only switching the pack on is left to the player.
        record=options_record(instance,staged,session.get('set_language'),False);session['errors'].append(['啟用翻譯資源包',str(exc)])
    if record:records.append(record)
    if uses_pack and (record:=default_packs_record(instance,staged)):records.append(record)
    jars=[staged/r['file'] for r in records if r['file'].endswith('.jar')]
    if jars:
        notify(72,'檢查模組檔完整性',f'用 Java 檢查 {len(jars):,} 個修改過的模組檔，可能需要一兩分鐘')
        vr=VerifyResult();check_java_zipfs(jars,vr)
        if not vr.ok:raise ValueError('Java 驗證未通過：'+'; '.join(vr.errors))
    if stage_only:
        # Sharing reuses the live scanner's routes and every normal format / Java check.
        # The caller keeps these working files until one combined, reversible deployment.
        return dict(staged=staged,records=records,rows=selected,held=dict(held))
    notify(80,'備份與套用','先保存所有原檔，再寫入已校對文字')
    ensure_game_closed(instance)
    # Nothing on disk differs (the resource pack already holds exactly this text): nothing to back up or write.
    backup=apply_reviewed(instance,staged,records,home/'output',waiting_note(notify)) if records else None
    for row in selected:row['installed']=True
    # Written is not the same as shown: read every line back from the files the game reads.
    notify(90,'讀回核對寫入內容','重新讀取翻譯資源包與原檔核對譯文；這不是遊戲畫面實測')
    session['shown_mismatch']=check_shown(instance,selected)
    try:Provenance(home,instance).record(selected);record_translated(home,instance)
    except OSError as exc:session['errors'].append(['來源紀錄',str(exc)])
    backups=(session.get('backups') or ([session['backup']] if session.get('backup') else []))+([str(backup)] if backup else [])
    session.update(status='installed',backup=str(backup) if backup else session.get('backup'),backups=backups,
                   installed_count=session.get('installed_count',0)+len(selected),
                   held_back=dict(held),resource_pack=RESOURCE_PACK_FILE if uses_pack else None,
                   language_set=bool(session.get('set_language')))  # options.txt changed now or already zh_tw
    write_json(report/'session.json',session)
    notify(92,'重新掃描實際遊戲資料','檢查套用後的語系與還沒處理的項目')
    try:
        after=scan(instance,report/'after',lambda *_:None,lambda:False,scan_cache(home,instance),details='summary')
        session['after_counts']=dict(after.counts)
        session['text_inventory']={k:v for k,v in after.text_inventory.items() if k!='candidates'}
    except Exception as exc:
        session['errors'].append(['套用後稽核',explain_error(exc)])
    write_json(report/'session.json',session)
    notify(100,'已套用已校對的文字',f'{len(selected):,} 筆；其他還沒處理的內容仍保留在報告')
    return session


RESTORABLE = ('installed',)+INTERRUPTED


def newer_batch_holding(backup, instance, file, current):
    """The later batch whose result for `file` is what is on disk now, as its folder name, else ''."""
    for manifest in sorted(backup.parent.glob('*/_備份紀錄/manifest.json'),reverse=True):
        if manifest.parents[1].name<=backup.name:break
        try:
            record=json.loads(manifest.read_text(encoding='utf-8'))
            if record.get('status') in RESTORABLE and Path(record['instance']).resolve()==instance and any(
                    f['file']==file and f['after']==current for f in record['files']):
                return manifest.parents[1].name
        except (OSError,ValueError,KeyError):continue
    return ''


def restore_backup(backup: Path, expected_instance: Path):
    """Put back the files one batch changed.

    A batch whose writing or restoring was cut short (crash, power cut) can be restored too: each
    file is either still original (left alone) or exactly what the batch wrote (put back). Anything
    else was changed later, so nothing is touched.
    """
    backup=backup.resolve()
    journal=backup/'_備份紀錄/manifest.json'
    record=json.loads(journal.read_text(encoding='utf-8'))
    instance=Path(record['instance']).resolve()
    if instance!=expected_instance.resolve():raise ValueError('備份不屬於目前選擇的模組包。')
    if record['status'] not in RESTORABLE:
        raise ValueError({'restored':'這一批已經還原過了。','rolled_back':'這一批套用失敗時已自動復原，遊戲檔案不需要還原。',
                          'backing_up':'這一批在備份階段就中斷，遊戲檔案沒有被修改，不需要還原。'}
                         .get(record['status'],'這份備份不是可還原的已套用批次。'))
    ensure_game_closed(instance)
    seen=set();todo=[]
    for row in record['files']:
        path=contained(instance,row['file']);source=contained(backup,row['file'])
        if str(path).casefold() in seen:raise ValueError('備份清冊包含重複路徑。')
        seen.add(str(path).casefold())
        now=file_hash(path)
        if now==row['before']:continue  # never written, or already put back before the interruption
        if now!=row['after']:
            newer=newer_batch_holding(backup,instance,row['file'],now)
            if newer:raise ValueError(f'這個檔案後來又被較新的一批翻譯（{newer[:15]}）修改，請先還原較新的那一批，再還原這一批：'+row['file'])
            raise ValueError('檔案後來有修改，已停止還原以免覆蓋：'+row['file'])
        if row['before'] is not None and file_hash(source)!=row['before']:raise ValueError('備份內容不符：'+row['file'])
        todo.append(row)
    # Persist each restored item so an interrupted restore is diagnosable.
    record.update(status='restoring',restored_files=list(record.get('restored_files') or []))
    write_json(journal,record)
    for row in todo:
        path=contained(instance,row['file'])
        if file_hash(path)!=row['after']:raise ValueError('還原途中檔案被修改：'+row['file'])
        if row['before'] is None:when_free(path.unlink,path.name)
        else:atomic_copy(contained(backup,row['file']),path)
        if when_free(lambda:file_hash(path),path.name)!=row['before']:raise ValueError('還原後雜湊不符：'+row['file'])
        record['restored_files'].append(row['file']);write_json(journal,record)
    record['status']='restored';write_json(journal,record)
    return dict(record,backup_path=str(backup))


INSIDE_MODPACK = ('mods','config','kubejs','defaultconfigs','resourcepacks','datapacks','saves','shaderpacks','scripts','logs',
                  'tacz','tlm_custom_pack')


def resolve_instance(chosen):
    """(modpack root, note for the user) for the folder the user picked or pasted.

    A folder inside a modpack (mods, config…) is corrected to the modpack itself; a folder that holds
    several modpacks, a drive or the user's home folder is refused with what to pick instead.
    """
    text=str(chosen or '').strip()
    if len(text)>=2 and text[0]==text[-1] and text[0] in ('"',"'"):text=text[1:-1].strip()
    if not text:raise ValueError('請先選擇模組包資料夾。')
    folder=Path(text)
    if not folder.exists():raise ValueError('找不到這個資料夾，可能已被移動或改名：\n'+text)
    note=''
    if folder.is_file():
        folder=folder.parent;note='你選的是檔案，已改用它所在的資料夾。'
    folder=folder.resolve()
    if folder.name.casefold() in INSIDE_MODPACK and is_instance(folder.parent):
        note=f'你選的是模組包裡的「{folder.name}」，已改用模組包本身。';folder=folder.parent
    if folder==Path(folder.anchor) or folder==Path.home().resolve():
        raise ValueError('請選擇模組包自己的資料夾，不要選整個磁碟或使用者資料夾。')
    if is_instance(folder):return folder,note
    inside={}
    try:
        for child in sorted(folder.iterdir()):
            game=next((c for c in (child,child/'.minecraft',child/'minecraft') if child.is_dir() and is_instance(c)),None)
            if game:inside[child.name]=game
    except OSError:pass
    if len(inside)==1:
        name,game=next(iter(inside.items()))
        return game,f'你選的是外層資料夾，已改用裡面唯一的模組包「{name}」。'
    if inside:
        raise ValueError(f'這個資料夾裡有 {len(inside)} 個模組包（'+'、'.join(list(inside)[:4])+('…' if len(inside)>4 else '')
                         +'），請選擇其中一個模組包，而不是外層資料夾。')
    raise ValueError('這裡不像模組包資料夾。模組包的根資料夾裡應該有 mods、config 或 kubejs。')
