"""CurseForge builds of Solo Quests checked against their declared dependencies."""

import json
import tomllib
import zipfile
from pathlib import Path

from .deployment import file_hash
from .imblocker import jar_ids, numbers, pack_loader
from .sweeper import mod_jars

PROJECT = 1644371
MOD_ID = 'ftb_solo_quests'
PAGE = 'https://www.curseforge.com/minecraft/mc-mods/solo-quests'
NAME = 'Solo Quests（專用伺服器可各自解任務、手動同步）'

# File IDs, byte counts and SHA-256 of the three official 1.1.2 builds.
FILES = {
    ('forge', '1.20.1'): (8614618, 41328, 'ecf1d7d5946c648ad1d6d1c612f4b00eb1eaa817bf2a6286497bf0aee4014b25'),
    ('fabric', '1.21.1'): (8614634, 47059, 'fb8196a302cfbbaa47cc1d9361b3b790d1772ffbc42e296326d4b04f9293fd2a'),
    ('neoforge', '1.21.1'): (8614631, 47019, '4f1a26a111c0cd40f6db2c309454d016454520fc8eb6a022555178a49ac739c7'),
}
# What players see of 1.1.2 (the three builds have the same eight English keys and only zh_cn): the quest screen's
# sync buttons and the server command replies, in Taiwan wording. Written into the translation resource pack of
# every published modpack that adds the mod (AGENTS.md: added mods are published in Traditional Chinese).
LANG = 'assets/ftb_solo_quests/lang/zh_tw.json'
ZH_TW = {
    'ftb_solo_quests.gui.team_sync.tooltip.sync_available': '從隊友同步這個任務的進度',
    'ftb_solo_quests.gui.team_sync.tooltip.no_sync_available': '還沒有隊友完成這個任務',
    'ftb_solo_quests.gui.team_sync_all.tooltip': '從隊友同步所有任務進度',
    'ftb_solo_quests.command.migrate.done': '任務進度已移轉，詳情請查看紀錄。重新啟動伺服器後生效。',
    'ftb_solo_quests.command.status.no_data': '找不到 FTB Quests 的資料夾',
    'ftb_solo_quests.command.status.pending_count': '待移轉的隊伍存檔數：%s',
    'ftb_solo_quests.command.status.migrated_count': '已移轉的隊伍存檔數：%s',
    'ftb_solo_quests.command.status.list_failed': '無法列出資料夾內容：%s',
}


# The English they translate: a later build that changes a line falls back to the usual sources (desktop_jobs.plan).
EN = {
    'ftb_solo_quests.gui.team_sync.tooltip.sync_available': 'Sync this quest progress',
    'ftb_solo_quests.gui.team_sync.tooltip.no_sync_available': 'No teammate has completed this quest',
    'ftb_solo_quests.gui.team_sync_all.tooltip': 'Sync all quests with team',
    'ftb_solo_quests.command.migrate.done': 'Migration done, see log (in-memory data is not reloaded; restart to apply)',
    'ftb_solo_quests.command.status.no_data': 'No ftbquests data directory',
    'ftb_solo_quests.command.status.pending_count': 'Pending party saves: %s',
    'ftb_solo_quests.command.status.migrated_count': 'Migrated: %s',
    'ftb_solo_quests.command.status.list_failed': 'Failed to list directory: %s',
}


def wording(key: str, english) -> str | None:
    """This program's Chinese for one Solo Quests line, when the English is the one it was written for."""
    return ZH_TW.get(key) if EN.get(key) == english else None


def lang_bytes() -> bytes:
    return json.dumps(ZH_TW, ensure_ascii=False, indent=2).encode('utf-8')


def with_translation(pack: bytes, mod: dict) -> bytes:
    """The translation resource pack with Solo Quests' zh_tw written, bound to the added jar like the pack's other
    files (mctranslator.json). It replaces a zh_tw converted from the mod's zh_cn (記憶體資料不會過載), so the shared
    pack always carries these lines; a pack that has exactly them is returned as it is."""
    import io
    source = io.BytesIO(pack)
    with zipfile.ZipFile(source) as original:
        if LANG in original.namelist() and original.read(LANG) == lang_bytes():
            return pack
        record = json.loads(original.read('mctranslator.json')) if 'mctranslator.json' in original.namelist() else {}
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as copy:
            for item in original.infolist():
                if item.filename not in ('mctranslator.json', LANG):
                    copy.writestr(item, original.read(item))
            record.setdefault('sources', {})[LANG] = {'mods/' + mod['fileName']: mod['sha256']}
            copy.writestr(zipfile.ZipInfo(LANG, (2020, 1, 1, 0, 0, 0)), lang_bytes(), zipfile.ZIP_DEFLATED)
            copy.writestr(zipfile.ZipInfo('mctranslator.json', (2020, 1, 1, 0, 0, 0)),
                          json.dumps(record, ensure_ascii=False, indent=1).encode('utf-8'), zipfile.ZIP_DEFLATED)
    return out.getvalue()


FORGE_MIN = {'ftbquests': (2001, 4, 0), 'ftblibrary': (2001, 1, 0),
             'ftbteams': (2001, 3, 0), 'architectury': (9, 0, 0)}
NEW_MIN = dict.fromkeys(('ftbquests', 'ftblibrary', 'ftbteams'), (2101, 1, 0)) | {'architectury': (13, 0, 8)}


def declared_versions(path: Path, loader: str) -> dict:
    try:
        with zipfile.ZipFile(path) as jar:
            if loader == 'fabric':
                mod = json.loads(jar.read('fabric.mod.json').decode('utf-8-sig'))
                return {mod_id: numbers(mod['version']) for mod_id in [mod['id'], *mod.get('provides', [])]}
            meta = 'META-INF/neoforge.mods.toml' if loader == 'neoforge' else 'META-INF/mods.toml'
            mods = tomllib.loads(jar.read(meta).decode('utf-8-sig'))['mods']
            versions = {}
            for mod in mods:
                version = mod.get('version', '')
                if version == '${file.jarVersion}':
                    manifest = jar.read('META-INF/MANIFEST.MF').decode('utf-8-sig').replace('\r\n ', '')
                    version = next((line.split(': ', 1)[1] for line in manifest.splitlines()
                                    if line.startswith('Implementation-Version: ')), '')
                versions[mod['modId']] = numbers(version)
            return versions
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
        return {}


def choose(instance: Path, *, include_existing=False) -> tuple[dict | None, str]:
    loader, mc = pack_loader(instance)
    file = FILES.get((loader, mc))
    if not file:
        return None, '這個 Minecraft 版本或模組載入器沒有核對過的 Solo Quests 版本'
    file_id, size, sha256 = file
    versions = {}
    for path, enabled in mod_jars(instance):
        if MOD_ID in jar_ids(path):
            if not (include_existing and enabled and path.stat().st_size == size and file_hash(path) == sha256):
                return None, f'已有 Solo Quests（{path.name}），保留原本的檔案與啟用設定'
            continue
        if enabled:
            versions.update(declared_versions(path, loader))
    minimum = FORGE_MIN if loader == 'forge' else NEW_MIN
    if loader == 'fabric':
        minimum = {**minimum, 'fabric': (0, 102, 1)}
    maximum = {'ftbquests': (2002,), 'ftblibrary': (2002,), 'ftbteams': (2002,),
               'architectury': (10,)} if loader == 'forge' else {}
    missing = [mod_id for mod_id, low in minimum.items()
               if not low <= versions.get(mod_id, ()) < maximum.get(mod_id, (float('inf'),))]
    if missing:
        return None, '缺少相容且啟用的前置模組（' + '、'.join(missing) + '）'
    filename = f'ftb-solo-quests-{mc}-{loader}-1.1.2.jar'
    url = f'https://mediafilez.forgecdn.net/files/{file_id // 1000}/{file_id % 1000}/{filename}'
    return dict(projectID=PROJECT, fileID=file_id, fileName=filename, size=size, sha256=sha256,
                url=url, name=NAME, page=PAGE), ''
