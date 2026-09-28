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
            except (ValueError, UnicodeError):
                continue
    if not result:
        raise ValueError('參考庫中找不到有效語系資料。')
    return result


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
    dbs, hashes = [], {}
    for kind, identity, url, locale in specs:
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        rawpath = cache/f'{kind}-{key}.zip'
        if rawpath.exists():
            raw = rawpath.read_bytes()
        else:
            progress('下載'+('繁中' if kind=='tw' else '簡中')+'參考庫…')
            raw = fetch(url,'下載'+('繁中' if kind=='tw' else '簡中')+'參考庫',binary=True)
        progress('解析'+('繁中' if kind=='tw' else '簡中')+'參考庫…')
        db = build_scoped(raw, locale, progress, cancelled)
        if not rawpath.exists():
            tmp = rawpath.with_suffix('.download')
            tmp.write_bytes(raw)
            tmp.replace(rawpath)
        dbs.append(db)
        hashes[kind] = hashlib.sha256(raw).hexdigest()
    return dbs, dict(checked_at=datetime.now(timezone.utc).isoformat(), minecraft=version,
                     ref_commit=commit['sha'], cfpa_asset=asset_name, cfpa_updated=asset['updated_at'],
                     sha256=hashes, entries=[sum(map(len,x.values())) for x in dbs])
