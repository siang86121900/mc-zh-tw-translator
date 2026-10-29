"""Sweeper Maid (CurseForge project 974232, AGPL v3): every 10 minutes it moves dropped items into
dustbins that players open with /sweepermaid dustbin [0-7], so items left on the ground stop slowing the
server down without being lost at once.

Only modpacks the owner publishes get it (使用者 2026-10-29: 「未來要上架的整合包再裝」), and only when
the modpack has nothing of its own that clears dropped items: scripts/publish_translation.py calls
ensure() on the owner's modpack before packing it. A translation patch then asks the receiver's app
to install the same file (manifest 'sweeper'); a whole-pack share carries the jar and its config.

Its chat messages and dustbin name are read from config/sweeper_maid-common.toml (Component.literal,
checked in the 1.1.2 class SMCommonConfig), and the mod writes them in English the first time the game
starts. A modpack without that file gets one with the same settings and Taiwanese wording first.
"""
from __future__ import annotations

import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from . import desktop_jobs as jobs
from .deployment import apply_reviewed, file_hash
from .imblocker import jar_ids, numbers, pack_loader

MOD_ID = 'sweeper_maid'
NAME = 'Sweeper Maid'
PAGE = 'https://www.curseforge.com/minecraft/mc-mods/sweeper-maid'
PROJECT = 974232
WHAT = 'Sweeper Maid（定時把地上的掉落物收進垃圾桶的模組）'
CONFIG = 'config/sweeper_maid-common.toml'

# (loader, lowest Minecraft, highest Minecraft, file id, file name, size, SHA-256); the version the owner
# named (1.1.2), taken from CurseForge 2026-10-29, downloaded and checked. Its mods.toml asks for Forge 47
# (Minecraft 1.20.1); NeoForge for 1.20.1 loads it too (imblocker.choose does the same).
FILES = (
    ('forge', (1, 20), (1, 20, 1), 7867270, 'sweeper_maid-1.1.2.jar', 955805,
     '3e246c3f511bce5fa4ff1876c2052d3f68981b19e7cec3b4c7b7a4ea9fc8e4ae'),
)
KNOWN = {f[6]: f[5] for f in FILES}

# Something else already clears dropped items: a mod or config named for it, or a script or function
# that kills item entities. A wrong match only means Sweeper Maid is not added, so the words are broad,
# but not a mod that clears something else (Craft to Exile 2's ArrowCleanUp only removes stuck arrows).
CLEANER_WORDS = re.compile(r'clear.?lag|lag.?clear|item.?clear|clear.?item|clear.?entit|entity.?clear|'
                           r'item.?clean|clean.?item|sweep(?!ing)|dustbin|garbage|扫地|掃地|清理', re.I)
KILL_ITEMS = re.compile(r'kill\s+@e\[[^\]\n]*type\s*=\s*!?\s*(?:minecraft:)?item\b', re.I)
SCRIPT_FOLDERS = ('kubejs', 'scripts', 'datapacks', 'config/openloader', 'config/paxi', 'global_packs')
SCRIPT_SUFFIXES = ('.js', '.zs', '.mcfunction')
SCRIPT_LIMIT = 4 * 1024 * 1024

# Same keys, order and values as the file Forge writes for 1.1.2; only the player-visible text differs.
# The wording is Elemental Awakening's own (its author's config, 世界之聲), which the owner picked (2026-10-29).
CONFIG_TEXT = '''
[sweeper_maid-common-config]
\t#If 0, disable item sweeping. If > 0, cool down (in seconds) between two item sweeping.
\t#Range: 0 ~ 360000
\tITEM_SWEEP_INTERVAL = 600
\t#Item overload in a chunk. If exceeded, a warning message will be sent.
\t#Range: 1 ~ 6400000
\tITEM_OVERLOAD_THRESHOLD = 640
\t#Message to be sent when item overload threshold is exceeded. "$1" stands for chunk X position, "$2" stands for chunk Z position, and "$3" stands for item count.
\tOVERLOAD_MESSAGE = "世界之聲：區域（$1，$2）的掉落物過多，共有 $3 個！"
\t#Other entities of types will be killed when cleaning, e.g. arrows. You can also kill mobs or even players by setting this.
\tEXTRA_ENTITY_TYPES = ["minecraft:arrow", "minecraft:spectral_arrow", "oceanworld:drip_ice"]
\t#Items in this list will never be cleaned and will be kept as item entity until it disappear.
\tITEM_WHITELIST = ["minecraft:nether_star", "minecraft:heavy_core"]
\t#Items in this list will be cleaned but not added to the dustbin.
\tITEM_BLACKLIST = ["minecraft:cobblestone", "minecraft:sand"]
\t#What message will be sent to players when there's 15s, 30s and 60s left to sweep. "$1" stands for the remaining time (in seconds).
\tMESSAGE_BEFORE_SWEEP_15_30_60 = "世界之聲：注意！還有 $1 秒就要清理垃圾了"
\t#What message will be sent to players when there's 1s~10s left to sweep. "$1" stands for the remaining time (in seconds).
\tMESSAGE_BEFORE_SWEEP_1_10 = "世界之聲：注意！還有 $1 秒就要清理垃圾了"
\t#What message will be sent to players after a sweep. "$1" stands for the number of killed dropped items, "$2" stands for the number of killed entities, and "$3" stands for the number of blacklisted items.
\tMESSAGE_AFTER_SWEEP = "世界之聲：這次一共清理掉了 $1 個掉落物，$2 個其他實體和 $3 個黑名單物品"
\t#What message will be sent to players when open a wrong dustbin.
\tMESSAGE_WRONG_DUSTBIN = "世界之聲：垃圾桶編號錯誤。"
\t#Name of dustbins.
\tDUSTBIN_NAME = "垃圾桶 "
\t#Count of dustbins
\t#Range: 1 ~ 64
\tDUSTBIN_COUNT = 8
\t#What chat message will be sent to players after a sweep. Command will be appended to the end of the chat message.
\tCHAT_MESSAGE_AFTER_SWEEP = "世界之聲：有物品不見了？可以檢視垃圾桶："
\t#Permission level of a player to open the dustbin.
\t#Range: 0 ~ 4
\tPERMISSION_LEVEL_DUSTBIN = 0
\t#Permission level of a player to clean immediately.
\t#Range: 0 ~ 4
\tPERMISSION_LEVEL_CLEAN = 2

'''.encode('utf-8')


def mod_file(entry) -> dict:
    """One listed file in the shape patches.install_mods takes."""
    _, _, _, file_id, name, size, sha = entry
    digits = str(file_id)
    url = f'https://mediafilez.forgecdn.net/files/{digits[:4]}/{int(digits[4:])}/{name}'
    return dict(projectID=PROJECT, fileID=file_id, fileName=name, size=size, sha256=sha, url=url, name=NAME, page=PAGE)


def mod_jars(instance: Path):
    """(path, enabled) for every mod file, switched-off ones (name.jar.disabled) included."""
    try:
        files = sorted(p for p in (Path(instance)/'mods').iterdir() if p.is_file())
    except OSError:
        return []
    found = []
    for p in files:
        name = p.name.lower()
        if name.endswith('.jar'):
            found.append((p, True))
        elif name.endswith('.disabled') and '.jar' in name:
            found.append((p, False))
    return found


def present(instance: Path) -> dict | None:
    """{'file', 'enabled'} when the modpack has Sweeper Maid, read from the jars themselves."""
    for p, enabled in mod_jars(instance):
        if MOD_ID in jar_ids(p):
            return dict(file=p.name, enabled=enabled)
    return None


def script_files(instance: Path):
    """(relative name, text) of scripts and functions, loose or inside data pack archives."""
    instance = Path(instance)
    for folder in SCRIPT_FOLDERS:
        root = instance/folder
        if not root.is_dir():
            continue
        for p in sorted(root.rglob('*')):
            try:
                if not p.is_file() or p.stat().st_size > SCRIPT_LIMIT * 64:
                    continue
                suffix = p.suffix.lower()
                if suffix in SCRIPT_SUFFIXES and p.stat().st_size <= SCRIPT_LIMIT:
                    yield p.relative_to(instance).as_posix(), p.read_text(encoding='utf-8', errors='replace')
                elif suffix in ('.zip', '.jar') and folder != 'kubejs':
                    with zipfile.ZipFile(p) as z:
                        for info in z.infolist():
                            if info.filename.lower().endswith(SCRIPT_SUFFIXES) and info.file_size <= SCRIPT_LIMIT:
                                yield (p.relative_to(instance).as_posix()+'/'+info.filename,
                                       z.read(info).decode('utf-8', 'replace'))
            except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
                continue


def cleaner(instance: Path) -> str:
    """Why the modpack already clears dropped items ('' when nothing does)."""
    instance = Path(instance)
    for p, enabled in mod_jars(instance):
        if not enabled:
            continue
        ids = jar_ids(p) - {MOD_ID}
        if MOD_ID in jar_ids(p):
            continue
        if any(CLEANER_WORDS.search(x) for x in ids) or (not ids and CLEANER_WORDS.search(p.name)):
            return f'整合包已經有清理用的模組（{p.name}）'
    for folder in ('config', 'defaultconfigs'):
        try:
            names = sorted(p.name for p in (instance/folder).iterdir() if p.is_file())
        except OSError:
            continue
        for name in names:
            if CLEANER_WORDS.search(name) and not name.lower().startswith('sweeper_maid'):
                return f'整合包已經有清理用的設定（{folder}/{name}）'
    for name, text in script_files(instance):
        found = KILL_ITEMS.search(text)
        if found:
            return f'整合包的腳本已經會清掉落物（{name}：{found.group(0)}）'
    return ''


def choose(instance: Path) -> tuple[dict | None, str]:
    """(file to install, '') or (None, why none fits)."""
    kind, mc = pack_loader(instance)
    version = numbers(mc)
    if not kind or not version:
        return None, '讀不到這個整合包的 Minecraft 版本或模組載入器，無法選出合適的版本'
    if kind == 'neoforge' and version < (1, 20, 2):
        kind = 'forge'  # NeoForge for 1.20.1 still loads Forge mods
    for entry in FILES:
        loader, low, high = entry[:3]
        if loader == kind and low <= version <= high:
            return mod_file(entry), ''
    return None, f'{NAME} 1.1.2 只支援 Minecraft 1.20.1（Forge），這個整合包是 {mc}（{kind}）'


def write_config(instance: Path, home: Path, notify=lambda *_: None) -> str | None:
    """Write the Taiwanese config when the modpack has none yet; returns the backup batch, or None."""
    instance = Path(instance).resolve()
    if (instance/CONFIG).exists():
        return None
    staged = Path(home)/'tmp'/('sweeper-'+uuid.uuid4().hex[:8])
    try:
        target = staged/CONFIG
        target.parent.mkdir(parents=True)
        target.write_bytes(CONFIG_TEXT)
        records = [dict(file=CONFIG, before=None, after=file_hash(target), reviewed=True, verified=True)]
        notify(100, '加裝 Sweeper Maid', '寫入繁體中文的清掃訊息')
        return str(apply_reviewed(instance, staged, records, Path(home)/'output', jobs.waiting_note(notify, 100, '加裝 Sweeper Maid')))
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def ensure(instance: Path, home: Path, notify=lambda *_: None, cancelled=lambda: False, session=None,
           pause=time.sleep, check_cleaner=True) -> dict:
    """Install Sweeper Maid when the modpack lacks it and nothing else clears dropped items.

    Never raises for a failure of its own; 'line' says in plain words what happened. 'state' is present,
    disabled, cleaner, installed, unsupported, failed or cancelled; the jar and the config are each a
    restorable batch ('backup', 'config_backup'). A receiver of a patch passes check_cleaner=False: the
    owner already checked the same modpack before publishing it.
    """
    from . import patches
    instance = Path(instance)
    try:
        found = present(instance)
        if found and not found['enabled']:
            return dict(state='disabled', file=found['file'],
                        line=f'{WHAT}在這個整合包裡被停用（{found["file"]}），尊重原本的設定，沒有重新安裝。')
        if found:
            config = write_config(instance, home, notify)
            return dict(state='present', file=found['file'], config_backup=config,
                        line=f'已有 {WHAT}，沒有重複安裝。'+('已補上繁體中文的清掃訊息。' if config else ''))
        if check_cleaner and (why := cleaner(instance)):
            return dict(state='cleaner', line=f'沒有安裝 {WHAT}：{why}，兩個一起清可能會清掉不該清的東西。')
        mod, why = choose(instance)
        if not mod:
            return dict(state='unsupported', line=f'沒有安裝 {WHAT}：{why}。')
        notify(0, '加裝 Sweeper Maid', '從 CurseForge 下載清理掉落物的模組')
        done = patches.install_mods(instance, [mod], home, notify, cancelled, session, pause)
        if not done['installed'] and not done['present']:
            reason = done['skipped'][0]['reason'] if done['skipped'] else '原因不明'
            return dict(state='failed', line=f'沒有安裝 {WHAT}：{reason}')
        config = write_config(instance, home, notify)
        return dict(state='installed' if done['installed'] else 'present', file=mod['fileName'],
                    backup=done['backup'], config_backup=config,
                    line=f'已從 CurseForge 安裝 {WHAT}，每 10 分鐘清一次，清掉的東西可輸入 /sweepermaid dustbin 找回（垃圾桶編號 0～7）；可在「備份與還原」移除。')
    except InterruptedError:
        return dict(state='cancelled', line=f'已停止，沒有安裝 {WHAT}。')
    except Exception as exc:
        return dict(state='failed', line=f'沒有安裝 {WHAT}：{jobs.explain_error(exc)} 其他步驟照常進行。')


def listed(path: Path) -> bool:
    """A jar that is exactly the listed Sweeper Maid file (the receiver of a share installs it on their own)."""
    try:
        return Path(path).stat().st_size in KNOWN.values() and KNOWN.get(file_hash(path)) == Path(path).stat().st_size
    except OSError:
        return False
