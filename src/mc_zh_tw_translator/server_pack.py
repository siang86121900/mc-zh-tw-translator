"""A ready-to-run server folder for a modpack the player already has.

What a player does by hand, done the same way:
1. a new folder next to (never inside) the modpack, with copies of the folders a server reads
   (mods, config, kubejs ...), so the translated quests, settings and scripts come along;
2. the official NeoForge / Forge / Fabric server from the loader's own download site, checked against the
   SHA-256 published next to it;
3. eula.txt only after the player agreed to Minecraft's EULA in the program;
4. the server is started and every mod that stops it (client-only mods) is moved to a side folder,
   with the line of the crash that named it, until the server starts;
5. run.bat with the Java that worked and user_jvm_args.txt with the memory chosen for it.

The player's modpack folder is only read. Mod files are copied from it, never downloaded or shared.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from . import desktop_jobs as jobs
from .updater import VERSION

# What a server reads besides its own files; everything else (saves, resource and shader packs,
# options, screenshots, maps, skins) belongs to the player's game only.
COPY_DIRS = ('mods', 'config', 'defaultconfigs', 'kubejs', 'scripts', 'global_packs', 'datapacks',
             'patchouli_books', 'openloader', 'paxi', 'moonlight-global-datapacks', 'tlm_custom_pack')
REMOVED_DIR = '_已拿掉的模組'
NOTE_FILE = '伺服器說明.txt'
LOADER_HOSTS = ('maven.neoforged.net', 'maven.minecraftforge.net', 'maven.fabricmc.net', 'meta.fabricmc.net')
LOADER_NAMES = {'neoforge': 'NeoForge', 'forge': 'Forge', 'fabric': 'Fabric'}
# Fabric's server installer is one program for every Minecraft version: the newest stable one on Fabric's own
# list, this one when the list cannot be read. Either way it is checked against the SHA-256 on maven.fabricmc.net.
FABRIC_META = 'https://meta.fabricmc.net/v2'
FABRIC_INSTALLER = '1.1.2'
FABRIC_LAUNCHER = 'fabric-server-launch.jar'
MAX_INSTALLER_SIZE = 64*1024*1024
MAX_TRIES = 40
START_TIMEOUT = 20*60          # a first start of a large modpack also builds the world
INSTALL_TIMEOUT = 20*60
STOP_TIMEOUT = 3*60
# Forge 1.20.1 writes its crash report when mods fail to load and may then never exit (The Foll, 2026-10-02:
# java still running 8 minutes after "Crash report saved to"). After the report it gets this long to end by itself.
CRASH_GRACE = 30
CRASHED = re.compile(r'Crash report saved to|crash report has been saved to|LoadingFailedException|Failed to start the minecraft server', re.I)
# Forge: "[Server thread/INFO] [minecraft/DedicatedServer]: Done (12.3s)!"; Fabric: "[Server thread/INFO] (Minecraft) Done (12.3s)!"
DONE = re.compile(r'(?:\]:|\] \([^()\n]*\)) Done \([\d.,]+s\)!')
GAME_PORT = 25565
EULA_URL = 'https://aka.ms/MinecraftEULA'
TRIAL_WORLD = 'mctranslator-trial-world'
INVALID_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class Stopped(RuntimeError):
    """The player pressed stop; the folder so far is kept."""


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r'\d+', str(text))[:3])


def loader_of(instance: Path) -> dict:
    """The modpack's Minecraft version and mod loader, from its manifest or CurseForge's record."""
    instance = Path(instance); ids = []; mc = ''
    try:
        m = json.loads((instance/'manifest.json').read_text(encoding='utf-8-sig'))['minecraft']
        mc = str(m.get('version') or '')
        loaders = m.get('modLoaders') or []
        ids += [str(x.get('id') or '') for x in loaders if x.get('primary')] + [str(x.get('id') or '') for x in loaders]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    try:
        x = json.loads((instance/'minecraftinstance.json').read_text(encoding='utf-8-sig'))
        base = x.get('baseModLoader') or {}
        mc = mc or str(base.get('minecraftVersion') or x.get('gameVersion') or '')
        ids.append(str(base.get('name') or ''))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    for value in ids:
        m = re.fullmatch(r'(neoforge|forge|fabric|quilt)-(.+)', value.strip(), re.I)
        if not m:
            continue
        kind = m[1].lower(); version = m[2]
        if kind == 'quilt':
            raise ValueError('這個整合包使用 Quilt，目前只能建立 NeoForge、Forge 和 Fabric 的伺服器。')
        if kind == 'fabric':
            # CurseForge's own record writes fabric-<loader>-<Minecraft>: fabric-0.18.4-1.21.1.
            tail = re.fullmatch(r'(\d[\w.+]*?)-(\d+\.\d+(?:\.\d+)?)', version)
            if tail and (not mc or tail[2] == mc):
                version, mc = tail[1], mc or tail[2]
        if not mc:
            break
        if kind == 'forge' and version_tuple(mc) < (1, 17):
            raise ValueError(f'Minecraft {mc} 的 Forge 伺服器開法和新版不同，目前還不支援。')
        return dict(kind=kind, version=version, mc=mc)
    raise ValueError('讀不到這個整合包使用的 Minecraft 與 NeoForge／Forge／Fabric 版本，無法建立伺服器。')


def installer_url(loader: dict) -> str:
    v = loader['version']; mc = loader['mc']
    if loader['kind'] == 'fabric':
        i = loader.get('installer') or FABRIC_INSTALLER
        return f'https://maven.fabricmc.net/net/fabricmc/fabric-installer/{i}/fabric-installer-{i}.jar'
    if loader['kind'] == 'neoforge':
        if mc == '1.20.1':  # NeoForge's first release kept Forge's naming
            return f'https://maven.neoforged.net/releases/net/neoforged/forge/1.20.1-{v}/forge-1.20.1-{v}-installer.jar'
        return f'https://maven.neoforged.net/releases/net/neoforged/neoforge/{v}/neoforge-{v}-installer.jar'
    return f'https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{v}/forge-{mc}-{v}-installer.jar'


def java_needed(mc: str) -> int:
    v = version_tuple(mc)
    return 21 if v >= (1, 20, 5) else 17 if v >= (1, 17) else 8


def java_candidates() -> list[Path]:
    """Java on this computer: CurseForge's own copies first (the ones the game already runs on)."""
    home = Path(os.environ.get('USERPROFILE') or Path.home())
    found = list((home/'curseforge'/'minecraft'/'Install'/'java').glob('*/bin/java.exe'))
    if os.environ.get('JAVA_HOME'):
        found.append(Path(os.environ['JAVA_HOME'])/'bin'/'java.exe')
    which = shutil.which('java')
    if which:
        found.append(Path(which))
    for root in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)')):
        if root:
            for vendor in ('Java', 'Eclipse Adoptium', 'Microsoft', 'Zulu', 'BellSoft'):
                found += list((Path(root)/vendor).glob('*/bin/java.exe'))
    unique = []
    for p in found:
        if p.is_file() and p not in unique:
            unique.append(p)
    return unique


def java_version(path: Path, run=subprocess.run) -> int:
    """The major version of one java.exe; 0 when it cannot be run."""
    try:
        out = run([str(path), '-version'], capture_output=True, text=True, timeout=30,
                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', (out.stderr or '')+(out.stdout or ''))
    if not m:
        return 0
    return int(m[2] or 0) if m[1] == '1' else int(m[1])


def find_java(mc: str, candidates=None, version=java_version) -> tuple[Path, int]:
    """The Java to run this Minecraft version: the exact major version it needs, else the lowest newer one
    (Minecraft before 1.17 needs exactly Java 8)."""
    need = java_needed(mc)
    found = [(version(p), p) for p in (java_candidates() if candidates is None else candidates)]
    exact = [(v, p) for v, p in found if v == need]
    newer = sorted(((v, p) for v, p in found if v > need and need != 8), key=lambda x: x[0])
    if exact or newer:
        v, p = (exact or newer)[0]
        return p, v
    raise ValueError(f'找不到 Java {need}。Minecraft {mc} 的伺服器需要 Java {need}：請先用 CurseForge 開一次這個整合包的遊戲'
                     f'（CurseForge 會下載它用的 Java），或到 https://adoptium.net 安裝 Java {need} 後再試。')


def server_memory(mod_count: int, total_mb: int, client_mb: int) -> dict:
    """Memory for a server of 1 to 10 players on a computer that also runs the game (and other games).

    Sized by the number of mods; what the game, Windows and another game need is left free first.
    Only a maximum is set, so the server takes memory as it needs it instead of all of it at once.
    """
    base = 4096 if mod_count < 100 else 6144 if mod_count < 200 else 8192
    client = client_mb or 8192
    room = (total_mb - client - 6144) if total_mb else base
    mb = base if room >= base else max(4096, room//1024*1024)
    warning = ''
    if room < base:
        warning = (f'你的電腦共約 {total_mb/1024:.0f} GB 記憶體，同時開遊戲、伺服器和其他遊戲會不夠用，'
                   f'伺服器先設為 {mb//1024} GB；開伺服器時建議少開其他程式。')
    return dict(mb=mb, warning=warning, line=f'伺服器記憶體設為最多 {mb//1024} GB（{mod_count} 個模組、1～10 人遊玩的建議值，'
                                            '只在需要時才佔用，不會一開就全部佔走）。')


def folder_name(name: str) -> str:
    name = INVALID_NAME.sub(' ', name).strip(' .') or 'Modpack'
    return name[:80]+' Server'


def unquote(text: str) -> str:
    """A pasted path without surrounding spaces or quotes ("C:\\...")."""
    text = str(text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
        text = text[1:-1].strip()
    return text


def target_folder(parent: Path, name: str, instance: Path) -> Path:
    """Where the server goes: a new folder named after the modpack inside the folder the player chose."""
    if not str(parent).strip():
        raise ValueError('請選擇或貼上要放伺服器的資料夾。')
    parent = Path(unquote(str(parent)))
    if not parent.is_absolute():
        raise ValueError('請選擇或貼上完整的資料夾位置，例如 C:\\Users\\你的名字\\Desktop\\Minecraft server。')
    if parent.exists() and not parent.is_dir():
        raise ValueError('選到的是檔案，請改選資料夾。')
    instance = Path(instance).resolve(); resolved = parent.resolve()
    if resolved == instance or instance in resolved.parents:
        raise ValueError('不能把伺服器建在整合包資料夾裡面，請選其他位置（例如桌面上的 Minecraft server 資料夾）。')
    if resolved.parent == resolved:
        raise ValueError('請不要直接選整個磁碟，請選一個資料夾（例如桌面上的 Minecraft server 資料夾）。')
    base = folder_name(name); target = resolved/base; n = 2
    while target.exists() and any(target.iterdir()):
        target = resolved/f'{base} ({n})'; n += 1
    return target


def folder_size(path: Path) -> int:
    total = 0
    for p in path.rglob('*'):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def copy_size(instance: Path) -> int:
    return sum(folder_size(instance/d) for d in COPY_DIRS if (instance/d).is_dir())


def copy_instance(instance: Path, server: Path, notify=lambda *_: None, cancelled=lambda: False) -> list[str]:
    copied = []
    present = [d for d in COPY_DIRS if (instance/d).is_dir()]
    for i, d in enumerate(present):
        if cancelled():
            raise Stopped('已停止。')
        notify(5+int(15*i/max(1, len(present))), '複製整合包檔案', d)
        # quests-backup and similar program leftovers are copied too: the server ignores what it does not read.
        shutil.copytree(instance/d, server/d, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('*.partial', '*.tmp'))
        copied.append(d)
    return copied


declared_ids = jobs.declared_mod_ids


def fabric_meta(z: zipfile.ZipFile) -> dict:
    """A Fabric mod's fabric.mod.json ({} when the jar has none or it cannot be read)."""
    try:
        text = z.read('fabric.mod.json').decode('utf-8-sig', 'replace')
    except KeyError:
        return {}
    try:
        meta = json.loads(text, strict=False)
        return meta if isinstance(meta, dict) else {}
    except ValueError:
        m = re.search(r'"id"\s*:\s*"([^"]+)"', text)
        return {'id': m[1]} if m else {}


def fabric_ids(meta: dict) -> list[str]:
    provides = meta.get('provides') if isinstance(meta.get('provides'), list) else []
    return [x for x in [meta.get('id')]+provides if isinstance(x, str) and x]


def mod_ids(mods: Path) -> dict[str, str]:
    """Mod id → jar file name for every jar in a mods folder.

    The mods a Fabric jar carries inside (META-INF/jars, e.g. Fabric API's modules) count as that jar's,
    so "X requires fabric-api-base" points at the jar that carries it."""
    index = {}; bundled = {}
    for jar in sorted(mods.glob('*.jar')):
        try:
            with zipfile.ZipFile(jar) as z:
                names = z.namelist()
                for meta in ('META-INF/neoforge.mods.toml', 'META-INF/mods.toml'):
                    if meta in names:
                        for mod in declared_ids(z.read(meta).decode('utf-8', 'replace')):
                            index.setdefault(mod, jar.name)
                for mod in fabric_ids(fabric_meta(z)):
                    index.setdefault(mod, jar.name)
                for inner in names:
                    if inner.startswith('META-INF/jars/') and inner.endswith('.jar'):
                        try:
                            with zipfile.ZipFile(io.BytesIO(z.read(inner))) as nested:
                                for mod in fabric_ids(fabric_meta(nested)):
                                    bundled.setdefault(mod, jar.name)
                        except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
                            continue
        except (zipfile.BadZipFile, OSError, KeyError):
            continue
    for mod, name in bundled.items():
        index.setdefault(mod, name)
    return index


CLIENT_ONLY = re.compile(r'(?m)^\s*clientSideOnly\s*=\s*true\b')


def declared_client_only(mods: Path) -> list[str]:
    """Jars whose own description says they are for the player's game only
    (clientSideOnly=true in mods.toml, "environment": "client" in fabric.mod.json)."""
    found = []
    for jar in sorted(mods.glob('*.jar')):
        try:
            with zipfile.ZipFile(jar) as z:
                names = z.namelist()
                if any(meta in names and CLIENT_ONLY.search(z.read(meta).decode('utf-8', 'replace'))
                       for meta in ('META-INF/neoforge.mods.toml', 'META-INF/mods.toml')) \
                        or fabric_meta(z).get('environment') == 'client':
                    found.append(jar.name)
        except (zipfile.BadZipFile, OSError, KeyError):
            continue
    return found


ISSUE = re.compile(r'-- Mod loading issue(?: for: (\S+))? --')
MOD_FILE = re.compile(r'Mod [Ff]ile: (.+)')
FAILURE = re.compile(r'Failure message: (.+)')
EXCEPTION = re.compile(r'Exception message: (.+)')
REQUIRES = re.compile(r'Mod (\S+) requires (\S+)')
FAILED_MOD = re.compile(r'\((\w[\w-]*)\) (?:has failed to load|encountered an error)')
INVALID_DIST = re.compile(r'Attempted to load class (\S+) for invalid dist DEDICATED_SERVER')
# A class of the player's game only (screen, keys, sound, rendering) that a server does not have;
# org.lwjgl is the game's window, input and sound library (Sodium's pre-launch check, COBBLEVERSE 2026-10-03).
CLIENT_CLASS = re.compile(r'(?:NoClassDefFoundError|ClassNotFoundException|invalid dist)\S*:?\s+(?:net[/.]minecraft[/.]client[/.]|com[/.]mojang[/.]blaze3d[/.]|org[/.]lwjgl[/.])|invalid dist DEDICATED_SERVER')
# A mod reading its settings for the player's game (a client config, never loaded on a server).
CLIENT_CONFIG = re.compile(r'Cannot get config value before config is loaded')
# A stack frame in a mod jar: ~[particle_effects-1.21.1-NeoForge-1.0.1.jar%23514!/:?]
FRAME_JAR = re.compile(r'~\[([^\[\]/\\]+?\.jar)%23\d+!')
MIXIN_MOD = re.compile(r'Mixin apply for mod (\S+) failed|\] from mod (\S+) failed')


def culprits(text: str, index: dict[str, str], present: set[str]) -> list[dict]:
    """The mods a failed start names, from the crash report and the log.

    Each is dict(file, mod, kind, detail): kind 'client' (it loads the player's screen, keys or sound,
    which a server does not have), 'requires' (it needs mod `needs`), or 'error' (another failure).
    A folder name with Chinese shows as ?? in the report, so the file is also found by its mod id.
    """
    found = {}
    def jar(path, mod):
        name = path.strip().replace('\\', '/').rsplit('/', 1)[-1] if path else ''
        if name in present:
            return name
        return index.get(mod or '') if index.get(mod or '') in present else None
    chunks = re.split(r'(?=-- Mod loading issue|\n\s*Mod File: )', text)
    for chunk in chunks:
        chunk = chunk.split('-- System Details --')[0]
        file_m = MOD_FILE.search(chunk); fail_m = FAILURE.search(chunk)
        if not file_m and not ISSUE.match(chunk.strip()):
            continue
        issue = ISSUE.search(chunk); exc = EXCEPTION.search(chunk)
        failure = fail_m[1].strip() if fail_m else ''
        exception = exc[1].strip() if exc else ''
        req = REQUIRES.search(failure)
        failed = FAILED_MOD.search(failure)
        mod = (issue[1] if issue else '') or (req[1] if req else '') or (failed[1] if failed else '')
        name = jar(file_m[1] if file_m else '', mod)
        if not name and not mod and (not file_m or 'No mod information' in file_m[1]):
            # "Mod file: <No mod information provided>": the first frame of the error in a mod of this modpack.
            # Only then: an issue that names its mod is never pinned on another jar in its stack.
            name = next((j for j in FRAME_JAR.findall(chunk) if j in present), None)
        if not name or name in found:
            continue
        if INVALID_DIST.search(exception) or INVALID_DIST.search(failure) or CLIENT_CLASS.search(failure+' '+exception):
            kind, detail = 'client', exception or failure
        elif CLIENT_CONFIG.search(failure+' '+exception):
            kind, detail = 'client_config', exception or failure
        elif req:
            kind, detail = 'requires', failure
        else:
            kind, detail = 'error', failure+(' '+exception if exception and '<No associated' not in exception else '')
        item = dict(file=name, mod=mod, kind=kind, detail=detail.strip()[:300])
        if req:
            item['needs'] = req[2]
        found[name] = item
    if not found:
        for m in MIXIN_MOD.finditer(text):
            mod = m[1] or m[2]; name = jar('', mod)
            if name and name not in found:
                found[name] = dict(file=name, mod=mod, kind='error', detail=m[0][:300])
    return list(found.values())


# Fabric runs Minecraft under intermediary names (net.minecraft.class_310): a Minecraft class that a server
# cannot find is one of the player's game, whatever its name. "Cannot load class ... in environment type SERVER"
# is Fabric's own refusal of a class marked for the player's game.
FABRIC_CLIENT = re.compile(r'(?:NoClassDefFoundError|ClassNotFoundException)\S*:?\s+(?:net[/.]minecraft[/.](?:client[/.]|class_\d+\b)|com[/.]mojang[/.]blaze3d[/.]|org[/.]lwjgl[/.])'
                           r'|Cannot load class \S+ in environment type SERVER')
FABRIC_ENTRY = re.compile(r"entrypoint (?:stage )?'[\w:-]+'[^\n]*? provided by '([\w.-]+)'")
# "Mod 'Konkrete' (konkrete) 1.0 requires any version of fabric-api, which is missing!"
# "Mod 'A' (a) 1.0 requires version 2.0 or later of mod 'B' (b), but only the wrong version is present: 1.0!"
FABRIC_REQUIRES = re.compile(r"Mod '[^'\n]*' \(([\w.-]+)\) \S+ requires (?:[^\n]*? of )?(?:mod )?(?:'[^'\n]*' \(([\w.-]+)\)|([\w.-]+))")
# Those sentences are in the computer's language (Chinese on the player's computer, COBBLEVERSE 2026-10-03);
# the resolver's own line above them is always English:
# "Reason: [HARD_DEP controlling 19.0.5 {depends searchables @ [>=1.0.1]}, ...]"
FABRIC_REASON = re.compile(r'HARD_DEP(?:_NO_CANDIDATE)? ([\w.-]+) \S+ \{depends ([\w.-]+) @[^}\n]*\}')
# A stack frame in a mod jar as Fabric's log writes it: at knot/x.Y.z(Y.kt:166) ~[Cobblemon-fabric-1.7.3+1.21.1.jar:?]
FABRIC_FRAME = re.compile(r'\[([^\[\]/\\:\n]+?\.jar):')
# The first line of an error with its stack ("java.lang.RuntimeException: ...", "Caused by: ...").
# A normal Fabric start also logs "Error loading class: net/minecraft/class_906 (ClassNotFoundException ...)"
# warnings for mixins aimed at the player's game (COBBLEVERSE 2026-10-03): those are not errors and never read.
ERROR_HEAD = re.compile(r'(?m)^(?:Caused by: )?[\w.$]+(?:Error|Exception): ')


def error_block(text: str, start: int) -> str:
    """One error from its first line: the stack lines and causes under it."""
    lines = text[start:].splitlines()[:400]
    keep = lines[:1]
    for line in lines[1:]:
        if not (line.startswith(('\t', ' ', 'Caused by:')) or ERROR_HEAD.match(line)):
            break
        keep.append(line)
    return '\n'.join(keep)


def fabric_culprits(text: str, index: dict[str, str], present: set[str]) -> list[dict]:
    """culprits() for a Fabric server: the mods named in its log and crash report.

    A mod is 'client' only when the error that names it is a class of the player's game missing on the server."""
    found = {}
    def add(name, mod, kind, detail, needs=''):
        if name and name in present and name not in found:
            found[name] = dict(file=name, mod=mod, kind=kind, detail=detail.strip()[:300])
            if needs:
                found[name]['needs'] = needs
    def jar(mod):
        return index.get(mod or '')
    def named(m, mod):
        client = FABRIC_CLIENT.search(error_block(text, text.rfind('\n', 0, m.start())+1))
        add(jar(mod), mod, 'client' if client else 'error', client[0] if client else m[0])
    for m in FABRIC_REASON.finditer(text):
        add(jar(m[1]), m[1], 'requires', m[0], m[2])
    for m in FABRIC_REQUIRES.finditer(text):
        add(jar(m[1]), m[1], 'requires', m[0], m[2] or m[3])
    for m in FABRIC_ENTRY.finditer(text):
        named(m, m[1])
    for m in MIXIN_MOD.finditer(text):
        named(m, m[1] or m[2])
    if not found:
        # No mod named: the first mod jar in the stack of an error whose cause is a missing class of the player's game.
        for m in ERROR_HEAD.finditer(text):
            if m[0].startswith('Caused by'):
                continue
            block = error_block(text, m.start()); client = FABRIC_CLIENT.search(block)
            if not client:
                continue
            name = next((j for j in FABRIC_FRAME.findall(block) if j in present), None)
            add(name, next((k for k, v in index.items() if v == name), ''), 'client', client[0])
            if found:
                break
    return list(found.values())


def plain_reason(item: dict) -> str:
    if item['kind'] == 'client':
        return '玩家端專用（會用到畫面、按鍵或聲音，伺服器沒有這些，開啟時會當掉）'
    if item['kind'] == 'client_config':
        return '玩家端專用（要讀只有玩家端才有的設定，伺服器上讀不到而當掉）'
    if item['kind'] == 'declared':
        return '模組自己標明只給玩家端用'
    if item['kind'] == 'requires':
        return f"需要已拿掉的「{item.get('needs_file') or item.get('needs')}」才能運作"
    return '在伺服器上載入失敗'


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def set_property(server: Path, key: str, value) -> None:
    path = server/'server.properties'
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines() if path.exists() else []
    lines = [x for x in lines if not x.startswith(key+'=')]+[f'{key}={value}']
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def download_installer(loader: dict, home: Path, notify=lambda *_: None, session=None, cancelled=lambda: False) -> Path:
    """The loader's official installer, kept only when it matches the SHA-256 the download site publishes."""
    import requests
    session = session or requests.Session()
    headers = {'User-Agent': f'MCTranslator/{VERSION}'}
    if loader['kind'] == 'fabric' and not loader.get('installer'):
        loader['installer'] = fabric_installer(loader, session, headers)
    url = installer_url(loader)
    folder = home/'downloads'/'server'; folder.mkdir(parents=True, exist_ok=True)
    problem = None
    for attempt in range(3):
        if cancelled():
            raise Stopped('已停止。')
        part = folder/(uuid.uuid4().hex+'.partial')
        try:
            r = session.get(url+'.sha256', timeout=(15, 60), headers=headers)
            if r.status_code == 404:
                raise ValueError(f"{LOADER_NAMES[loader['kind']]} {loader['version']} 的官方下載找不到，可能是版本太舊或已下架。")
            r.raise_for_status()
            if urlparse(r.url).netloc not in LOADER_HOSTS:
                raise ValueError('校驗碼被轉到官方以外的位置，沒有下載。')
            expected = r.text.strip().split()[0].lower() if r.text.strip() else ''
            if not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ValueError('官方下載網站沒有提供可用的校驗碼，沒有下載。')
            path = folder/(expected+'.jar')
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                return path
            h = hashlib.sha256(); received = 0
            with session.get(url, stream=True, timeout=(15, 60), headers=headers) as response:
                response.raise_for_status()
                if urlparse(response.url).netloc not in LOADER_HOSTS:
                    raise ValueError('下載被轉到官方以外的位置，沒有下載。')
                with part.open('xb') as f:
                    for block in response.iter_content(1024*1024):
                        if cancelled():
                            raise Stopped('已停止。')
                        received += len(block)
                        if received > MAX_INSTALLER_SIZE:
                            raise ValueError('下載到的檔案大得不正常，沒有使用。')
                        h.update(block); f.write(block)
                        notify(22, '下載伺服器安裝程式', f'{received/1024/1024:.1f} MB')
            if h.hexdigest() != expected:
                raise ValueError('下載到的伺服器安裝程式和官方校驗碼不符，沒有使用。')
            if not zipfile.is_zipfile(part):
                raise ValueError('下載到的不是伺服器安裝程式，沒有使用。')
            part.replace(path)
            return path
        except (requests.ConnectionError, requests.Timeout) as exc:
            problem = exc
            if attempt < 2:
                time.sleep(2*(attempt+1))
        finally:
            part.unlink(missing_ok=True)
    raise RuntimeError(f"連不上 {LOADER_NAMES[loader['kind']]} 的官方下載網站，請確認網路後再試一次。") from problem


def fabric_installer(loader: dict, session, headers) -> str:
    """The newest stable Fabric installer on Fabric's own list; first checks that Fabric has this loader for
    this Minecraft version, so a wrong version is said plainly instead of failing inside the installer."""
    import requests
    try:
        status = session.get(f"{FABRIC_META}/versions/loader/{loader['mc']}/{loader['version']}",
                             timeout=(15, 60), headers=headers).status_code
    except requests.RequestException:
        status = 0
    if status in (400, 404):
        raise ValueError(f"Fabric 官方沒有 Minecraft {loader['mc']} 的 Fabric Loader {loader['version']}，無法建立伺服器。")
    try:
        r = session.get(f'{FABRIC_META}/versions/installer', timeout=(15, 60), headers=headers)
        r.raise_for_status()
        for item in r.json():
            version = str(item.get('version') or '')
            if item.get('stable') and re.fullmatch(r'\d+(?:\.\d+){1,3}', version):
                return version
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        pass
    return FABRIC_INSTALLER


def watch(process, deadline, cancelled, stop_flag):
    """Kill the server when the player stops or it takes too long; returns the thread.
    deadline may be a one-item list, so that it can be moved once the server is asked to stop."""
    if not isinstance(deadline, list):
        deadline = [deadline]
    def run():
        while process.poll() is None and not stop_flag.is_set():
            if cancelled() or time.monotonic() > deadline[0]:
                stop_flag.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return
            time.sleep(0.5)
    t = threading.Thread(target=run, daemon=True); t.start(); return t


def install_loader(server: Path, installer: Path, java: Path, notify=lambda *_: None, cancelled=lambda: False,
                   loader: dict | None = None, popen=subprocess.Popen) -> None:
    """Run the official installer in the server folder; it downloads Minecraft's server and libraries.
    NeoForge / Forge: --installServer. Fabric: server -mcversion -loader -downloadMinecraft."""
    target = server/installer.name
    shutil.copy2(installer, target)
    notify(25, '安裝伺服器程式', '從官方下載 Minecraft 伺服器與函式庫，約需 1～5 分鐘')
    command = [str(java), '-jar', target.name, '--installServer']
    if loader and loader['kind'] == 'fabric':
        command = [str(java), '-jar', target.name, 'server', '-dir', '.', '-mcversion', loader['mc'],
                   '-loader', loader['version'], '-downloadMinecraft']
    process = popen(command, cwd=str(server), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    flag = threading.Event(); watch(process, time.monotonic()+INSTALL_TIMEOUT, cancelled, flag)
    tail = []
    for line in process.stdout:
        tail = (tail+[line.rstrip()])[-40:]
    process.wait()
    target.unlink(missing_ok=True)
    if cancelled():
        raise Stopped('已停止。')
    if flag.is_set():
        raise RuntimeError('安裝伺服器程式超過 20 分鐘沒有完成，已停止。請確認網路後再試。')
    if process.returncode != 0 or not args_file(server):
        raise RuntimeError('伺服器程式沒有安裝成功（官方安裝程式回報錯誤），通常是網路中斷。請確認網路後再試。'
                           '\n（技術細節：'+' / '.join(x for x in tail[-3:] if x)[:300]+'）')


def args_file(server: Path) -> str:
    """What starts the server, relative to its folder ('' when not installed): NeoForge / Forge's Windows
    argument file, or Fabric's launcher jar (with the Minecraft server it starts next to it)."""
    found = sorted((server/'libraries').glob('net/*/*/*/win_args.txt'))
    if found:
        return found[-1].relative_to(server).as_posix()
    if (server/FABRIC_LAUNCHER).is_file() and (server/'server.jar').is_file():
        return FABRIC_LAUNCHER
    return ''


def launch_args(args: str) -> list[str]:
    """The Java arguments after user_jvm_args.txt for what args_file() found."""
    return ['-jar', args] if args.endswith('.jar') else ['@'+args]


def short_path(path: Path) -> str:
    """A path a .bat file can hold: the Windows short form when the path has non-English letters."""
    text = str(path)
    if text.isascii():
        return text
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(text, buffer, 1024) and buffer.value.isascii():
            return buffer.value
    except (AttributeError, OSError):
        pass
    return 'java'


def write_launch_files(server: Path, java: Path, memory_mb: int, args: str) -> None:
    # Java reads argument files in the system code page: keep them English only.
    (server/'user_jvm_args.txt').write_text(
        '# Memory and Java options for this server. -Xmx is the most memory the server may use;\n'
        '# change it (for example -Xmx6G) and start the server again.\n'
        f'-Xmx{memory_mb//1024}G\n-XX:+UseG1GC\n-XX:MaxGCPauseMillis=100\n-XX:+ParallelRefProcEnabled\n', encoding='ascii')
    (server/'run.bat').write_text(
        '@echo off\r\ncd /d "%~dp0"\r\n'
        'REM Made by MC Translator. Memory: user_jvm_args.txt. Add nogui after the args file to hide the server window.\r\n'
        f'"{short_path(java)}" @user_jvm_args.txt {" ".join(launch_args(args))} %*\r\npause\r\n', encoding='ascii')


def try_start(server: Path, java: Path, args: str, notify=lambda *_: None, cancelled=lambda: False,
              popen=subprocess.Popen, timeout=START_TIMEOUT) -> dict:
    """Start the server once without its window. ok when it reached 'Done', then it is stopped again."""
    started = time.time()
    process = popen([str(java), '@user_jvm_args.txt', *launch_args(args), 'nogui'], cwd=str(server), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    flag = threading.Event(); deadline = [time.monotonic()+timeout]
    watch(process, deadline, cancelled, flag)
    output = []; ok = False; crashed = False
    # The output is read to the end, also after "stop": a server whose output nobody reads blocks on
    # writing it and never gets to saving the world and stopping.
    for line in process.stdout:
        output.append(line.rstrip()); output = output[-4000:]
        if not ok and DONE.search(line):
            ok = True; deadline[0] = time.monotonic()+STOP_TIMEOUT
            notify(0, '試開伺服器', '已成功開啟，正在存檔並關閉')
            try:
                process.stdin.write('stop\n'); process.stdin.flush()
            except OSError:
                pass
        elif not ok and not crashed and CRASHED.search(line):
            crashed = True; deadline[0] = min(deadline[0], time.monotonic()+CRASH_GRACE)
            notify(0, '試開伺服器', '開啟失敗，正在讀取當機紀錄')
        elif not ok and ('Loading' in line or 'Preparing' in line):
            notify(0, '試開伺服器', line.strip()[-90:])
    process.wait()
    if cancelled():
        raise Stopped('已停止。')
    text = '\n'.join(output)
    for crash in sorted((server/'crash-reports').glob('crash-*.txt')):
        try:
            if crash.stat().st_mtime >= started-1:
                text = crash.read_text(encoding='utf-8', errors='replace')+'\n'+text
        except OSError:
            pass
    # stop_hung: it started, but did not end by itself after "stop" (a mod holding it open) and was closed.
    # A start that failed and was closed after its crash report is a failure to read, not a time-out.
    return dict(ok=ok, text=text, timed_out=flag.is_set() and not ok and not crashed, stop_hung=flag.is_set() and ok, tail=output[-12:])


def move_mod(server: Path, name: str) -> None:
    target = server/REMOVED_DIR; target.mkdir(exist_ok=True)
    (server/'mods'/name).replace(target/name)


def last_error(tail) -> str:
    lines = [x for x in tail if re.search(r'ERROR|Exception|Caused by|FAILED', x)] or list(tail)
    return ' / '.join(x.strip() for x in lines[-3:])[:300]


def build_server(instance: Path, parent: Path, home: Path, notify=lambda *_: None, cancelled=lambda: False,
                 java: Path | None = None, memory_mb: int = 8192, name: str = '',
                 download=download_installer, install=install_loader, start=try_start, max_tries=MAX_TRIES) -> dict:
    """Make the server folder and try it until it starts. The player has agreed to the EULA before this runs."""
    instance = Path(instance); loader = loader_of(instance)
    if java is None:
        java, _ = find_java(loader['mc'])
    server = target_folder(parent, name or instance.name, instance)
    need = int(copy_size(instance)*1.05)+700*1024*1024
    free_at = server.parent if server.parent.exists() else next(p for p in server.parents if p.exists())
    if shutil.disk_usage(free_at).free < need:
        raise RuntimeError(f'硬碟空間不足：伺服器資料夾約需 {need/1024**3:.1f} GB，'
                           f'「{free_at}」所在的磁碟只剩 {shutil.disk_usage(free_at).free/1024**3:.1f} GB。沒有建立任何檔案。')
    server.mkdir(parents=True, exist_ok=True)
    result = dict(folder=str(server), loader=loader, java=str(java), memory_mb=memory_mb, removed=[], tries=0, ok=False)
    copy_instance(instance, server, notify, cancelled)
    for jar_name in declared_client_only(server/'mods'):
        move_mod(server, jar_name)
        result['removed'].append(dict(file=jar_name, mod='', kind='declared',
                                      detail='"environment": "client"' if loader['kind'] == 'fabric' else 'clientSideOnly=true'))
    installer = download(loader, home, notify, cancelled=cancelled)
    install(server, installer, java, notify, cancelled, loader=loader)
    args = args_file(server)
    (server/'eula.txt').write_text(f'# Agreed in MC Translator by the player ({EULA_URL})\neula=true\n', encoding='utf-8')
    # A free port for the trial, so another server already running on this computer does not get in the way.
    set_property(server, 'server-port', free_port())
    # The trial builds a world of its own, removed afterwards: the player's first start makes a fresh,
    # completely saved world instead of one from a trial that may have been closed by force.
    set_property(server, 'level-name', TRIAL_WORLD)
    write_launch_files(server, java, memory_mb, args)
    index = mod_ids(server/'mods')
    removed_mods = {}  # mod id → file, to recognise "X requires Y" caused by a mod taken out here
    for item in result['removed']:
        for mod, file in index.items():
            if file == item['file']:
                removed_mods[mod] = file
    try:
        while result['tries'] < max_tries:
            result['tries'] += 1
            pct = 40+min(50, result['tries']*4); n = result['tries']
            notify(pct, '試開伺服器', f'第 {n} 次啟動，找出伺服器不能用的模組')
            attempt = start(server, java, args, lambda _v, title, detail: notify(pct, title, f'第 {n} 次：{detail}'), cancelled)
            if attempt['ok']:
                result['ok'] = True; result['stop_hung'] = bool(attempt.get('stop_hung'))
                break
            if attempt.get('timed_out'):
                result['problem'] = '伺服器啟動超過 20 分鐘還沒完成，已停止嘗試。'
                break
            present = {p.name for p in (server/'mods').glob('*.jar')}
            found = (fabric_culprits if loader['kind'] == 'fabric' else culprits)(attempt['text'], index, present)
            if not found:
                result['problem'] = ('伺服器開不起來，但當機紀錄沒有指出是哪個模組，程式不敢亂拿。'
                                     '\n（技術細節：'+last_error(attempt.get('tail') or [])+'）')
                break
            # Only what is certainly the player's-game-only part goes: a client-only mod, or a mod that needs
            # one taken out here. Anything else (a script error, a bug in a mod, a library) is the player's call:
            # taking out KubeJS for one broken script would break the whole modpack.
            removable = [x for x in found if x['kind'] in ('client', 'client_config') or (x['kind'] == 'requires' and x.get('needs') in removed_mods)]
            if not removable:
                x = found[0]
                why = (f"需要「{x['needs']}」，但整合包裡本來就沒有它（或版本不對）" if x['kind'] == 'requires'
                       else '載入時出錯，但不是玩家端模組的問題（可能是腳本或模組本身的錯誤）')
                result['problem'] = (f"「{x['file']}」{why}。程式不確定能不能拿掉它，所以停在這裡、沒有拿掉。"
                                     '可以把當機紀錄給整合包作者看，或自己決定是否把它移出 mods 再雙擊 run.bat 試試。'
                                     '\n（技術細節：'+x['detail'][:240]+'）')
                break
            for x in removable:
                if x['kind'] == 'requires':
                    x['needs_file'] = removed_mods.get(x['needs'], '')
                move_mod(server, x['file'])
                result['removed'].append(x)
                for mod, file in index.items():
                    if file == x['file']:
                        removed_mods[mod] = file
        else:
            result['problem'] = f'試了 {max_tries} 次仍開不起來，已停止嘗試。'
    finally:
        set_property(server, 'server-port', GAME_PORT)
        set_property(server, 'level-name', 'world')
        trial = server/TRIAL_WORLD
        if trial.is_dir() and trial.parent == server:
            shutil.rmtree(trial, ignore_errors=True)
        write_note(server, result, instance)
    return result


def write_note(server: Path, result: dict, instance: Path) -> None:
    lines = ['這個伺服器資料夾由 MC Translator 建立。', '',
             '開伺服器：雙擊 run.bat。第一次開啟要等幾分鐘，看到「Done」就可以進遊戲。',
             '關伺服器：在伺服器視窗輸入 stop 後按 Enter（直接關視窗可能讓世界沒存好）。',
             f"記憶體：最多 {result['memory_mb']//1024} GB，要改的話用記事本打開 user_jvm_args.txt，把 -Xmx 後面的數字改掉。",
             f"Java：{result['java']}",
             f'整合包來源：{instance}', '',
             '自己的電腦連線：在遊戲的「多人遊戲 → 新增伺服器」輸入 localhost。',
             '同一個網路（同一台路由器）的朋友：輸入這台電腦的區域網路 IP（例如 192.168.x.x）。',
             '不同地方的朋友：需要在路由器設定連接埠轉發 25565，或使用 Radmin VPN、ZeroTier 這類連線工具；本程式無法代為設定。',
             '朋友要先安裝同一個整合包（同一版本）才能連進來。', '']
    if result['removed']:
        lines.append(f"已拿掉 {len(result['removed'])} 個伺服器不能用的模組，放在「{REMOVED_DIR}」資料夾（沒有刪除，可以放回 mods）：")
        for x in result['removed']:
            lines.append(f"・{x['file']}：{plain_reason(x)}")
            if x.get('detail') and x['kind'] != 'declared':
                lines.append(f"    當機紀錄：{x['detail'][:200]}")
        lines.append('')
    if result.get('problem'):
        lines += ['伺服器還沒有成功開啟：'+result['problem'], '']
    elif result['ok']:
        lines += ['已試開成功（模組載入與建立世界都完成）。試開用的測試世界已移除，第一次開伺服器時會建立全新的世界。',
                  '少數模組要等玩家進遊戲或做到某件事時才會出問題，遇到時請看 crash-reports 資料夾。', '']
        if result.get('stop_hung'):
            lines += ['注意：試開時伺服器存完檔後沒有自己結束（整合包裡某個模組讓它停不下來），程式等了 3 分鐘才關閉。',
                      '你自己關伺服器時，請輸入 stop，等視窗出現「Saving worlds」後再等一下、確定沒有新訊息再關閉視窗。', '']
    lines.append('已同意 Minecraft 使用者授權合約（EULA）：'+EULA_URL)
    (server/NOTE_FILE).write_text('\r\n'.join(lines)+'\r\n', encoding='utf-8-sig')
