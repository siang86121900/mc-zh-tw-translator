"""Read-only checks for native-protected mods and configured tooltip textures."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

YSM_NOTE = 'YSM 需要保留官方原檔，修改模組內部可能造成 err: 51；語系翻譯改用外部資源包'
# Official Modrinth project 86xjpqqS, 2.6.5 files; metadata checked 2026-11-07.
# No executable download is performed by this check.
YSM_SHA512 = {
    'b5e2445022e6c071b49c7eb312bc2e1628980a615506414a6ced06950999b8f627829cebe848bd8a2dc025c121abfb4286221bb641ad7648b13446e78dc07df3',
    '8d4a4fa4cea96e50f4062ae085bcc80485b9abfd31ad0e3633a4043dd764a62fbb8347f08ea43d6717e66cca894accb9b7a3a7881970e937064e17a68c098faf',
    '75a655fe095565d949aeea5e333f3e1501443b796b250aeabe1ac230c47a99cbac6b7470956b4458f5c982c2cf8a17f170b53e0805b4f4079874fc9975b10dce',
    'c5125c05c9d681ecb38ed7fca4a7915c8af65f90927393b84ab7e0494eda967c3398265c44ac15c2c25188bc2ee16b1311f5cd09848f1d38ad0846d526340ed1',
    'f3b2c5e7a6928582c7af58c1011a7347558af221389d32d3727af93cdf21f8971de634be3ce62a03859f60f6272f767e037b5ae22918d6dcec37548f56664aa7',
    'ed2b5a6fc97df098ef7e731c12f2367ebec2612a2a08b72bb958f508b5802e82858dc406f6b6cc4f99406988aabd6f2bd929a459afd1d101bdd2fdfd125ab1be',
}


def protected(path):
    from .imblocker import jar_ids
    return 'yes_steve_model' in jar_ids(Path(path))


def check_ysm(instance, paths=None):
    """Require a matching official file hash, including renamed jars. Never repair a real instance."""
    instance = Path(instance)
    jars = [p for p in (paths if paths is not None else (instance/'mods').glob('*.jar')) if protected(p)]
    if not jars:
        return
    try:
        record = json.loads((instance/'minecraftinstance.json').read_text(encoding='utf-8-sig'))
        official = {h['value'].lower() for a in record.get('installedAddons', [])
                    for h in (a.get('installedFile') or {}).get('hashes', [])
                    if h.get('type') == 1 and re.fullmatch('[0-9a-fA-F]{40}', str(h.get('value', '')))}
    except (OSError, ValueError, TypeError, AttributeError):
        official = set()
    for path in jars:
        data = path.read_bytes()
        if hashlib.sha512(data).hexdigest() not in YSM_SHA512 and hashlib.sha1(data).hexdigest() not in official:
            raise ValueError(f'{YSM_NOTE}。{path.name} 未通過官方檔案校驗碼核對，沒有上架；請換回官方原檔。若已是官方版本，需先更新程式的核對清單。')


def required_packs(instance, overlay=None, removed=()):
    """Resolve Tooltip Overhaul's literal texture locations against local assets.

    custom_frames.json uses resource locations directly. Missing textures are not text;
    a translation resource pack must never substitute for the original art packs.
    overlay supplies verified staged update files, without touching the live profile.
    """
    instance = Path(instance)
    overlay = Path(overlay) if overlay else None
    removed = {str(p).replace('\\', '/').casefold() for p in removed}
    config = Path('config/tooltipoverhaul/custom_frames.json')
    if config.as_posix().casefold() in removed:
        return []
    source = overlay/config if overlay and (overlay/config).is_file() else instance/config
    if not source.is_file():
        return []
    try:
        data = json.loads(source.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError('提示框材質設定讀取失敗，無法確認圖片是否齊全：'+str(config)) from exc
    textures = set()
    def walk(value):
        if isinstance(value, dict):
            texture = value.get('texture')
            if isinstance(texture, str) and texture.startswith('tooltipoverhaul:'):
                if not re.fullmatch(r'tooltipoverhaul:[a-z0-9_./-]+\.png', texture) or any(
                        part in ('', '.', '..') for part in texture.split(':', 1)[1].split('/')):
                    raise ValueError('提示框圖片路徑不合理：'+texture)
                textures.add('assets/'+texture.replace(':', '/', 1))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(data)
    if not textures:
        return []
    providers = {name: [] for name in textures}
    files = {}
    for root in [instance] + ([overlay] if overlay else []):
        for folder in ('mods', 'resourcepacks'):
            for p in (root/folder).glob('*'):
                files[folder+'/'+p.name] = p
    for rel, path in sorted(files.items()):
        if rel.casefold() in removed:
            continue
        if path.is_dir():
            names = {n for n in textures if (path/n).is_file()}
        elif path.suffix.lower() in ('.zip', '.jar'):
            try:
                with zipfile.ZipFile(path) as z:
                    names = set(z.namelist()) & textures
            except (OSError, zipfile.BadZipFile):
                continue
        else:
            continue
        for name in names:
            providers[name].append('file/'+path.name if rel.startswith('resourcepacks/') else '')
    for name in textures:
        if ('kubejs/'+name).casefold() not in removed and (
                (instance/'kubejs'/name).is_file() or (overlay and (overlay/'kubejs'/name).is_file())):
            providers[name].append('')
    needed = set()
    for name, packs in sorted(providers.items()):
        if not packs:
            raise ValueError('提示框缺少圖片，沒有繼續：'+name+'。請先補齊整合包原本使用的材質包。')
        if '' in packs:
            continue
        if len(packs) != 1:
            raise ValueError('多個資源包提供同一張提示框圖片，需先確認使用哪一份：'+name)
        needed.add(packs[0])
    return sorted(needed)


def merge_options(text, packs):
    from . import desktop_jobs as jobs
    current = jobs.enabled_packs(text)
    if current is None and re.search(r'(?m)^resourcePacks:', text):
        raise ValueError('資源包清單格式看不懂，沒有更動玩家設定。')
    current = current if current is not None else ['vanilla']
    translated = jobs.RESOURCE_PACK_ID in current
    current = [name for name in current if name != jobs.RESOURCE_PACK_ID]
    for name in packs:
        if name not in current:
            current.append(name)
    if translated:
        current.append(jobs.RESOURCE_PACK_ID)
    return jobs.with_option(text, 'resourcePacks', json.dumps(current, ensure_ascii=False, separators=(',', ':')))
