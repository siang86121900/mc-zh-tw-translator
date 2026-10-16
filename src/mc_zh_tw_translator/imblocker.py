"""IMBlocker (CurseForge project 483760): turns the Windows input method off while playing and back on
in chat, signs and book pages, so Chinese can be typed without switching by hand.

Before every translation and every install of a translated modpack, a modpack without it gets the file
CurseForge serves for its Minecraft version and loader (使用者 2026-10-16). The files are listed here with
the size and SHA-256 checked when this list was written, so the download goes through the same check as
every added mod (patches.download_mod): only from CurseForge's file servers, and only when it is the very
file listed. A modpack that already has it, enabled or switched off by the player, is left alone.
"""
from __future__ import annotations

import json
import re
import time
import zipfile
from pathlib import Path

from . import desktop_jobs as jobs
from .deployment import file_hash

MOD_ID = 'imblocker'
NAME = 'IMBlocker'
PAGE = 'https://www.curseforge.com/minecraft/mc-mods/imblocker'
PROJECT = 483760
WHAT = 'IMBlocker（打字時自動切換中文輸入法的模組）'

# (loader, lowest Minecraft, highest Minecraft, needs Fabric API, file id, file name, size, SHA-256);
# taken from CurseForge 2026-10-16, the newest release of each line, each file downloaded and checked.
FILES = (
    ('forge', (1, 16, 5), (1, 16, 5), False, 9033601, 'IMBlocker-5.6.2.1-forge+1.16.5.jar', 179971,
     '517902eaaaac91a0923b9597c4f9eb6ed868ced9caf407828dd9a5685bc350ea'),
    ('forge', (1, 17), (1, 20, 4), False, 9033569, 'IMBlocker-5.6.2.1-forge+1.17-1.20.4.jar', 232400,
     'd429017d6ad053acf6bccbb77750c9da398826a4782bda91cc3e142cb9e33c2a'),
    ('neoforge', (1, 20, 6), (1, 21, 8), False, 9033584, 'IMBlocker-5.6.2.1-neoforge+1.20.6-1.21.8.jar', 225646,
     'e41dc09209a527b839e79080b9103e138aafc850ae81c8274c306e639e9c623a'),
    ('fabric', (1, 17), (1, 21, 8), False, 9033568, 'IMBlocker-5.6.2.1-fabric+1.17-1.21.8.jar', 229044,
     '60ba9e56a1fc196f6d94e26619ffc1f24c54930929700fd4d4ac0919ac7f1c22'),
    ('neoforge', (1, 21, 9), (1, 21, 11), False, 8863057, 'IMBlocker-6.2.2-neoforge+1.21.9-1.21.11.jar', 175962,
     '869ccae1f0f9c7a2f2874314fc6a06b99d6252cea69bd37567977eaebe7c4f81'),
    ('fabric', (1, 21, 9), (1, 21, 11), True, 8863056, 'IMBlocker-6.2.2-fabric+1.21.9-1.21.11.jar', 182105,
     '236b70ac2cf4d49b31a956ca331c029bc9f01237b1724ac3b61854c960b93e42'),
    ('neoforge', (26, 1), (26, 3), False, 8903634, 'IMBlocker-7.3.2-neoforge-26.1+.jar', 186994,
     '4d0764235876e220b41399b322d1881d45406cf1e16f1ade068b5e1ade4dbad4'),
    ('fabric', (26, 1), (26, 3), True, 8903623, 'IMBlocker-7.3.2-fabric-26.1+.jar', 183555,
     'eec3b4f3f148fed93099b3cc437d49f2b157e753a47a03079a85bde956ea3017'),
)
KNOWN = {f[7]: f[6] for f in FILES}
GAME_VERSION = re.compile(r'\d+\.\d+(?:\.\d+)?')
# Launcher records name the loader: manifest/CurseForge 'forge-47.3.0', Prism component uids, Modrinth 'neoforge'.
LOADER_NAME = re.compile(r'(neoforge|forge|fabric|quilt)\b', re.I)
PRISM_LOADERS = {'net.neoforged': 'neoforge', 'net.minecraftforge': 'forge',
                 'net.fabricmc.fabric-loader': 'fabric', 'org.quiltmc.quilt-loader': 'quilt'}


def numbers(text) -> tuple:
    return tuple(int(x) for x in re.findall(r'\d+', str(text))[:3])


def mod_file(entry) -> dict:
    """One listed file in the shape patches.install_mods takes."""
    _, _, _, _, file_id, name, size, sha = entry
    digits = str(file_id)
    url = f'https://mediafilez.forgecdn.net/files/{digits[:4]}/{int(digits[4:])}/{name.replace("+", "%2B")}'
    return dict(projectID=PROJECT, fileID=file_id, fileName=name, size=size, sha256=sha, url=url, name=NAME, page=PAGE)


def jar_ids(path: Path) -> set[str]:
    """Mod ids a jar declares (mods.toml, neoforge.mods.toml, fabric.mod.json); empty when unreadable."""
    ids = set()
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            for meta in ('META-INF/neoforge.mods.toml', 'META-INF/mods.toml'):
                if meta in names:
                    ids.update(jobs.declared_mod_ids(z.read(meta).decode('utf-8', 'replace')))
            if 'fabric.mod.json' in names:
                meta = json.loads(z.read('fabric.mod.json').decode('utf-8-sig', 'replace'), strict=False)
                if isinstance(meta, dict):
                    ids.update(x for x in [meta.get('id')]+list(meta.get('provides') or []) if isinstance(x, str))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
        pass
    return ids


def present(instance: Path) -> dict | None:
    """{'file', 'enabled'} when the modpack has IMBlocker, read from the jars themselves (a renamed file
    counts; so does one the player switched off as name.jar.disabled)."""
    mods = Path(instance)/'mods'
    try:
        files = sorted(p for p in mods.iterdir() if p.is_file())
    except OSError:
        return None
    for p in files:
        name = p.name.lower()
        enabled = name.endswith('.jar')
        if not (enabled or (name.endswith('.disabled') and '.jar' in name)):
            continue
        if MOD_ID in jar_ids(p):
            return dict(file=p.name, enabled=enabled)
    return None


def pack_loader(instance: Path) -> tuple[str, str]:
    """(loader, Minecraft version) from the launcher's record; '' for what cannot be read."""
    instance = Path(instance); kind = ''; mc = ''
    def read(path):
        try:
            return json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return {}
    for folder in (instance, instance.parent):
        m = read(folder/'manifest.json').get('minecraft') or {}
        if isinstance(m, dict):
            mc = mc or str(m.get('version') or '')
            loaders = [x for x in m.get('modLoaders') or [] if isinstance(x, dict)]
            for x in sorted(loaders, key=lambda x: not x.get('primary')):
                found = LOADER_NAME.match(str(x.get('id') or ''))
                kind = kind or (found[1].lower() if found else '')
        record = read(folder/'minecraftinstance.json')
        if isinstance(record, dict):
            base = record.get('baseModLoader') if isinstance(record.get('baseModLoader'), dict) else {}
            mc = mc or str(base.get('minecraftVersion') or record.get('gameVersion') or '')
            found = LOADER_NAME.match(str(base.get('name') or ''))
            kind = kind or (found[1].lower() if found else '')
        prism = read(folder/'mmc-pack.json')
        for c in prism.get('components') or [] if isinstance(prism, dict) else []:
            if not isinstance(c, dict):
                continue
            if c.get('uid') == 'net.minecraft':
                mc = mc or str(c.get('version') or '')
            kind = kind or PRISM_LOADERS.get(c.get('uid'), '')
        profile = read(folder/'profile.json')
        meta = profile.get('metadata') if isinstance(profile, dict) else {}
        if isinstance(meta, dict):
            mc = mc or str(meta.get('game_version') or '')
            found = LOADER_NAME.match(str(meta.get('loader') or ''))
            kind = kind or (found[1].lower() if found else '')
    if not GAME_VERSION.fullmatch(mc):
        from .desktop_references import detect_version
        mc = detect_version(instance)[0]
    if not kind:
        kind = loader_from_mods(instance)
    return kind, mc


def loader_from_mods(instance: Path, limit: int = 80) -> str:
    """The loader most mods are written for, when no launcher record says it."""
    counts = {}
    for jar in sorted((Path(instance)/'mods').glob('*.jar'))[:limit]:
        try:
            with zipfile.ZipFile(jar) as z:
                names = set(z.namelist())
        except (OSError, zipfile.BadZipFile):
            continue
        kind = ('neoforge' if 'META-INF/neoforge.mods.toml' in names else 'forge' if 'META-INF/mods.toml' in names
                else 'quilt' if 'quilt.mod.json' in names else 'fabric' if 'fabric.mod.json' in names else '')
        if kind:
            counts[kind] = counts.get(kind, 0)+1
    return max(counts, key=counts.get) if counts else ''


def has_fabric_api(instance: Path) -> bool:
    for jar in (Path(instance)/'mods').glob('*.jar'):
        if jar_ids(jar) & {'fabric-api', 'fabric'}:
            return True
    return False


def choose(instance: Path) -> tuple[dict | None, str]:
    """(file to install, '') or (None, why none fits)."""
    kind, mc = pack_loader(instance)
    version = numbers(mc)
    if not kind or not version:
        return None, '讀不到這個整合包的 Minecraft 版本或模組載入器，無法選出合適的版本'
    if kind == 'quilt':
        return None, '這個整合包使用 Quilt，IMBlocker 沒有 Quilt 專用的版本'
    if kind == 'neoforge' and version < (1, 20, 2):
        kind = 'forge'  # NeoForge for 1.20.1 still loads Forge mods
    for entry in FILES:
        loader, low, high, fabric_api = entry[:4]
        if loader == kind and low <= version <= high:
            if fabric_api and not has_fabric_api(instance):
                return None, '這一版的 IMBlocker 需要 Fabric API，但這個整合包沒有，為了不讓遊戲開不起來沒有安裝'
            return mod_file(entry), ''
    return None, f'IMBlocker 沒有支援 Minecraft {mc}（{kind}）的版本'


def ensure(instance: Path, home: Path, notify=lambda *_: None, cancelled=lambda: False, session=None,
           pause=time.sleep) -> dict:
    """Install IMBlocker when the modpack lacks it. Never raises for a failure of its own: the translation or
    install goes on, and 'line' says in plain words what happened. 'state' is present, disabled, installed,
    unsupported or failed; an install is its own restorable batch ('backup')."""
    from . import patches
    instance = Path(instance)
    try:
        found = present(instance)
        if found:
            if found['enabled']:
                return dict(state='present', file=found['file'], line=f'已有 {WHAT}，沒有重複安裝。')
            return dict(state='disabled', file=found['file'],
                        line=f'{WHAT}在這個整合包裡被停用（{found["file"]}），尊重你的設定，沒有重新安裝。')
        mod, why = choose(instance)
        if not mod:
            return dict(state='unsupported', line=f'沒有安裝 {WHAT}：{why}。')
        notify(0, '加裝 IMBlocker', '從 CurseForge 下載打中文用的輸入法模組')
        done = patches.install_mods(instance, [mod], home, notify, cancelled, session, pause)
        if done['installed']:
            return dict(state='installed', file=mod['fileName'], backup=done['backup'],
                        line=f'已從 CurseForge 安裝 {WHAT}，可在「備份與還原」移除。')
        if done['present']:
            return dict(state='present', file=mod['fileName'], line=f'已有 {WHAT}，沒有重複安裝。')
        reason = done['skipped'][0]['reason'] if done['skipped'] else '原因不明'
        return dict(state='failed', line=f'沒有安裝 {WHAT}：{reason}')
    except InterruptedError:
        return dict(state='cancelled', line=f'已停止，沒有安裝 {WHAT}。')
    except Exception as exc:
        return dict(state='failed', line=f'沒有安裝 {WHAT}：{jobs.explain_error(exc)} 其他步驟照常進行，下次會再試。')


def listed(path: Path) -> bool:
    """A jar that is exactly one of the listed IMBlocker files (the receiver of a share installs it on their own)."""
    try:
        return Path(path).stat().st_size in KNOWN.values() and KNOWN.get(file_hash(path)) == Path(path).stat().st_size
    except OSError:
        return False
