"""Version-aware, fail-closed reference preflight for the desktop application."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from opencc import OpenCC


def minecraft_version(instance: Path) -> str:
    for filename in ('manifest.json', 'minecraftinstance.json'):
        p = instance/filename
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8-sig'))
            value = data.get('minecraft', {}).get('version') or data.get('gameVersion')
            if isinstance(value, str) and re.fullmatch(r'1\.\d+(?:\.\d+)?', value):
                return value
        except (ValueError, AttributeError):
            continue
    return ''


def build_scoped(raw: bytes, locale: str, progress=lambda _:None, cancelled=lambda:False) -> dict:
    cc = OpenCC('s2twp')
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=sorted(z.namelist())
        for i,name in enumerate(names):
            if i%100==0:
                if cancelled():raise InterruptedError('已停止參考庫整理；掃描報告已保留。')
                progress(f'整理參考庫 {locale}：{i:,} / {len(names):,} 個檔案')
            match = re.search(r'(?:^|/)assets/([^/]+)/lang/'+locale+r'\.json$', name)
            namespace = match[1] if match else None
            if not namespace and locale == 'zh_tw':
                match = re.match(r'(.*/Translation/[^/]+)/([^/]+)/zh_tw.json$', name)
                if match:
                    try:
                        meta = json.loads(z.read(match[1]+'/metadata.json'))
                        namespace = meta.get('contents', {}).get('tiers', {}).get(match[2], {}).get('mod_id', meta.get('mod_id'))
                    except (KeyError, ValueError):
                        continue
            if not namespace:
                continue
            try:
                values = json.loads(z.read(name).decode('utf-8-sig'))
                if not isinstance(values, dict):
                    continue
                result.setdefault(namespace, {}).update({k: cc.convert(v) if locale=='zh_cn' else v
                                                        for k,v in values.items() if isinstance(v,str)})
                if locale == 'zh_tw':
                    # Keep every version folder's (zh_tw, English) pair so matching can pick the translation
                    # whose English equals the installed mod's text instead of whichever folder sorts last.
                    sibling = name[:-len('zh_tw.json')]+'en_us.json'
                    english = json.loads(z.read(sibling).decode('utf-8-sig')) if sibling in names else {}
                    pairs = result.setdefault('__pairs__', {}).setdefault(namespace, {})
                    for k, v in values.items():
                        if isinstance(v, str):
                            pairs.setdefault(k, []).append((v, english.get(k) if isinstance(english, dict) else None))
            except (ValueError, UnicodeError):
                continue
    if not [k for k in result if not k.startswith('__')]:
        raise ValueError('參考庫中找不到有效語系資料。')
    return result


def pick_reference(ref: dict, namespace: str, key: str, english):
    """(translation, English matches current version) for one key of a zh_tw reference pack.

    A version whose English equals the installed text wins; otherwise the newest folder is returned
    as an unverified candidate. Packs without English (CFPA zh_cn) report None for the match flag.
    """
    pairs = ref.get('__pairs__', {}).get(namespace, {}).get(key)
    if not pairs:
        value = ref.get(namespace, {}).get(key)
        return value, None
    if isinstance(english, str):
        for zh, en in pairs:
            if isinstance(en, str) and en.strip() == english.strip():
                return zh, True
        return pairs[-1][0], False
    return pairs[-1][0], None


def refresh(instance: Path, cache: Path, progress, cancelled) -> tuple[list[dict], dict]:
    version = minecraft_version(instance)
    if not version:
        raise ValueError('無法從模組包辨識 Minecraft 版本。請選擇含 manifest.json 或 minecraftinstance.json 的模組包根目錄。')
    family = '-'.join(version.split('.')[:2])
    asset_name = f'Minecraft-Mod-Language-Modpack-{family}.zip'
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'MC-ZH-TW-Desktop/0.1'

    def fetch(url, description, binary=False):
        if cancelled():
            raise InterruptedError('已停止，遊戲原檔未修改。')
        progress(description+'…（連線逾時會保留報告並停止）')
        started=time.monotonic()
        with session.get(url, timeout=(10,20),stream=True) as r:
            r.raise_for_status()
            total=int(r.headers.get('Content-Length',0));chunks=[];received=0;last=0
            for block in r.iter_content(256*1024):
                if cancelled():raise InterruptedError('已停止下載，掃描報告已保留。')
                if time.monotonic()-started>300:raise TimeoutError('參考庫下載超過 5 分鐘，請檢查網路後重試。')
                received+=len(block)
                if received>256*1024*1024:raise ValueError('參考庫超過大小上限，已停止。')
                chunks.append(block)
                if time.monotonic()-last>=.5:
                    suffix=f' / {total/1048576:.1f} MB' if total else ' MB'
                    progress(f'{description}：{received/1048576:.1f}'+suffix)
                    last=time.monotonic()
        raw=b''.join(chunks)
        return raw if binary else json.loads(raw)

    progress('確認最新繁中與簡中參考庫…')
    commit = fetch('https://api.github.com/repos/TeamKugimiya/ModsTranslationPack/commits/main','查詢繁中參考庫最新版')
    release = fetch('https://api.github.com/repos/CFPAOrg/Minecraft-Mod-Language-Package/releases/tags/autobuild','查詢簡中參考庫最新版')
    asset = next((x for x in release['assets'] if x['name']==asset_name), None)
    if not asset:
        raise ValueError(f'最新 CFPA 發布找不到適用 Minecraft {version} 的 {asset_name}，已停止正式翻譯。')
    specs = [('tw', commit['sha'], f"https://codeload.github.com/TeamKugimiya/ModsTranslationPack/zip/{commit['sha']}", 'zh_tw'),
             ('cn', str(asset['id'])+'-'+asset['updated_at'], asset['browser_download_url'], 'zh_cn')]
    dbs, hashes, sources, notes = [], {}, [], []

    def load(kind, identity, url, locale, name):
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        rawpath = cache/f'{kind}-{key}.zip'
        if rawpath.exists():
            raw = rawpath.read_bytes()
        else:
            progress('下載'+name+'…')
            raw = fetch(url,'下載'+name,binary=True)
        progress('解析'+name+'…')
        db = build_scoped(raw, locale, progress, cancelled)
        if not rawpath.exists():
            tmp = rawpath.with_suffix('.download')
            tmp.write_bytes(raw)
            tmp.replace(rawpath)
        dbs.append(db); sources.append(kind)
        hashes[kind] = hashlib.sha256(raw).hexdigest()

    # Primary references must be confirmed latest; failures stop the translation (AGENTS.md).
    for kind, identity, url, locale in specs:
        load(kind, identity, url, locale, '繁中參考庫' if kind=='tw' else '簡中參考庫')
    # Supplementary sources only add coverage; if one is unavailable it is skipped and noted.
    para_commit = None
    try:
        para = fetch('https://api.github.com/repos/TeamKugimiya/ParaTranslationPack/commits/main','查詢 ParaTranslationPack 最新版')
        para_commit = para['sha']
        load('para', para_commit, f'https://codeload.github.com/TeamKugimiya/ParaTranslationPack/zip/{para_commit}', 'zh_tw', 'ParaTranslationPack')
    except InterruptedError:
        raise
    except Exception as exc:
        notes.append('ParaTranslationPack 暫時無法取得：'+str(exc)[:120])
    other = sorted((x for x in release['assets'] if re.fullmatch(r'Minecraft-Mod-Language-Modpack-(\d+-\d+)\.zip', x['name'])
                    and x['name'] != asset_name), key=lambda x: [int(n) for n in re.findall(r'\d+', x['name'])], reverse=True)
    older = [x for x in other if [int(n) for n in re.findall(r'\d+', x['name'])] < [int(n) for n in family.split('-')]][:3]
    for x in older:
        try:
            load('cn-'+re.search(r'(\d+-\d+)', x['name'])[1], str(x['id'])+'-'+x['updated_at'], x['browser_download_url'], 'zh_cn',
                 '跨版本簡中參考庫 '+x['name'])
        except InterruptedError:
            raise
        except Exception as exc:
            notes.append(f"{x['name']} 暫時無法取得：{str(exc)[:120]}")
    vanilla = official_vanilla(version, fetch, cache, progress)
    if vanilla:
        dbs.append(vanilla); sources.append('vanilla')
    else:
        notes.append('找不到官方 Minecraft 繁中語系檔，本次沒有使用官方譯名。')
    return dbs, dict(checked_at=datetime.now(timezone.utc).isoformat(), minecraft=version,
                     ref_commit=commit['sha'], cfpa_asset=asset_name, cfpa_updated=asset['updated_at'],
                     para_commit=para_commit, cross_version_assets=[x['name'] for x in older],
                     vanilla=vanilla.get('__source__') if vanilla else None, sources=sources, notes=notes,
                     sha256=hashes, entries=[sum(len(v) for k,v in x.items() if not k.startswith('__')) for x in dbs])


# Reference packs that are already Traditional Chinese written by people (vs. converted zh_cn).
HUMAN_TW_KINDS = ('tw', 'para')


def launcher_roots() -> list[Path]:
    home = Path.home(); appdata = Path(__import__('os').environ.get('APPDATA', home/'AppData/Roaming'))
    return [home/'curseforge/minecraft/Install', appdata/'.minecraft', appdata/'PrismLauncher', appdata/'ModrinthApp/meta']


def official_vanilla(version: str, fetch, cache: Path, progress) -> dict:
    """Mojang's own zh_tw (and en_us) for this Minecraft version, from a local launcher or Mojang's servers.

    Returned as {'minecraft': {key: zh_tw}, '__terms__': {english text: zh_tw}, '__source__': where}.
    """
    cached = cache/f'vanilla-{version}.json'
    if cached.exists():
        try: return json.loads(cached.read_text(encoding='utf-8'))
        except ValueError: pass
    zh = en = None; source = ''
    for root in launcher_roots():
        try:
            meta = json.loads((root/'versions'/version/f'{version}.json').read_text(encoding='utf-8'))
            index = json.loads((root/'assets/indexes'/f"{meta['assetIndex']['id']}.json").read_text(encoding='utf-8'))
            digest = index['objects']['minecraft/lang/zh_tw.json']['hash']
            zh = json.loads((root/'assets/objects'/digest[:2]/digest).read_text(encoding='utf-8'))
            with zipfile.ZipFile(root/'versions'/version/f'{version}.jar') as z:
                en = json.loads(z.read('assets/minecraft/lang/en_us.json').decode('utf-8'))
            source = str(root); break
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue
    if zh is None:
        try:
            progress('下載官方 Minecraft 繁中語系檔…')
            manifest = fetch('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json', '查詢 Minecraft 版本清單')
            meta = fetch(next(v['url'] for v in manifest['versions'] if v['id'] == version), '查詢 Minecraft 版本資料')
            index = fetch(meta['assetIndex']['url'], '查詢官方資源索引')
            digest = index['objects']['minecraft/lang/zh_tw.json']['hash']
            zh = json.loads(fetch(f'https://resources.download.minecraft.net/{digest[:2]}/{digest}', '下載官方繁中語系檔', binary=True))
            jar = fetch(meta['downloads']['client']['url'], '下載官方英文語系（遊戲本體）', binary=True)
            with zipfile.ZipFile(io.BytesIO(jar)) as z:
                en = json.loads(z.read('assets/minecraft/lang/en_us.json').decode('utf-8'))
            source = 'Mojang 官方伺服器'
        except InterruptedError:
            raise
        except Exception:
            return {}
    terms = {}
    for key, text in en.items():
        # Whole-string names only (items, blocks, mobs, effects...), so short UI words keep their mod context.
        if isinstance(text, str) and isinstance(zh.get(key), str) and re.match(r'(?:block|item|entity|effect|enchantment|biome)\.minecraft\.', key):
            terms.setdefault(text.strip().casefold(), zh[key])
    result = {'minecraft': {k: v for k, v in zh.items() if isinstance(v, str)}, '__terms__': terms, '__source__': source}
    try: cached.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except OSError: pass
    return result
