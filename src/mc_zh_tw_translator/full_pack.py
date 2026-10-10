"""Whole-modpack sharing for modpacks that have no CurseForge project (copied in from another launcher).

The catalog can only point a patch at a CurseForge modpack version. A modpack without one is shared
whole instead (the owner agreed on 2026-10-02, knowing that this hands out other people's mods):

- the owner's translated modpack is packed into one zip with a content list (every file's path,
  size and SHA-256). Mods CurseForge serves byte for byte are only listed with their CurseForge
  address; everything else is in the zip. Saves, logs, caches, maps and personal settings stay out.
- the zip goes to the owner's Google Drive; the catalog names its file ID, size and SHA-256.
- a player's single "安裝" downloads the zip and the CurseForge mods, builds a new modpack folder,
  checks every file against the content list, and adds the folder to CurseForge's own list
  (MinecraftGameInstance.json) while CurseForge is closed. Any failure removes the new folder and
  puts the list back as it was; no other modpack is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import desktop_jobs as jobs
from . import patches
from . import server_list
from .deployment import contained, file_hash, when_free
from .updater import VERSION

FORMAT = 'mctranslator-fullpack-1'
MANIFEST = 'mctranslator-fullpack.json'
PAYLOAD = 'files/'
# Personal or machine-made content: never shared. Top-level names, compared case-insensitively.
EXCLUDED_DIRS = {'saves', 'logs', 'crash-reports', 'backups', 'simplebackups', 'screenshots', 'xaero', 'journeymap',
                 'voxelmap', 'lightspeed-cache', 'cache', '.cache', 'modernfix', 'local', 'downloads', 'customskinloader',
                 '.curseclient', '.fabric', '.git', 'replay_recordings', 'replay_videos', 'webcache', 'distant_horizons_server_data'}
EXCLUDED_FILES = {'options.txt', 'optionsof.txt', 'optionsshaders.txt', 'minecraftinstance.json', 'servers.dat', 'servers.dat_old',
                  'usercache.json', 'usernamecache.json', 'imgui.ini', 'trashslotsavestate.json', 'patchouli_data.json',
                  'enigmatic_persistence.dat', 'rhino.local.properties', 'launcher_profiles.json', 'realms_persistence.json',
                  'command_history.txt', '.qmenu_opened.marker', '.mixin.out', 'fabricloader.log'}
EXCLUDED_PREFIXES = ('xaerowaypoints_backup', 'hs_err_pid')
EXCLUDED_SUFFIXES = ('.log', '.log.gz', '.tmp', '.partial')
EXCLUDED_NESTED = ('mods/.connector/', 'mods/.index/')
STORED = ('.jar', '.zip', '.png', '.jpg', '.ogg', '.gz', '.rar', '.7z', '.mp3', '.mp4')
# Where the Drive file may be served from.
DRIVE_HOSTS = ('drive.usercontent.google.com', 'drive.google.com')
DRIVE_ID = re.compile(r'[A-Za-z0-9_-]{20,100}')
# baseModLoader names the loader's own files; CurseForge downloads them, so only official addresses pass.
LOADER_HOSTS = ('modloaders.forgecdn.net', 'maven.minecraftforge.net', 'files.minecraftforge.net', 'maven.neoforged.net',
                'libraries.minecraft.net', 'piston-data.mojang.com', 'piston-meta.mojang.com', 'launcher.mojang.com')
MAX_PACK_SIZE = 8*1024**3
MAX_FILES = 200000
MAX_FILE_SIZE = 2*1024**3
MAX_TOTAL_SIZE = 24*1024**3
FOLDER_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# CurseForge's record of a modpack the player created; personal fields (play time, memory, Java
# arguments, picture) keep CurseForge's defaults. Taken from a profile CurseForge itself wrote.
RECORD_TEMPLATE = {
    'isUnlocked': True, 'javaArgsOverride': None, 'lastPlayed': '0001-01-01T00:00:00', 'playedCount': 0, 'timePlayed': 0,
    'manifest': None, 'fileDate': '0001-01-01T00:00:00', 'installedModpack': None, 'projectID': 0, 'fileID': 0,
    'customAuthor': None, 'modpackOverrides': [], 'isMemoryOverride': False, 'allocatedMemory': 4096,
    'profileImagePath': None, 'groupId': None, 'isVanilla': False, 'gameTypeID': 432, 'cachedScans': [], 'isValid': True,
    'isEnabled': True, 'gameVersionFlavor': None, 'gameVersionTypeId': None, 'preferenceAlternateFile': False,
    'preferenceAutoInstallUpdates': False, 'preferenceDeleteOrphanedDependencies': False,
    'preferenceDeleteSavedVariables': False, 'preferenceReleaseType': 1, 'preferenceModdingFolderPath': None,
    'syncProfile': {'PreferenceEnabled': False, 'PreferenceAutoSync': True, 'PreferenceAutoDelete': False,
                    'PreferenceBackupSavedVariables': False, 'GameInstanceGuid': '00000000-0000-0000-0000-000000000000',
                    'SyncProfileID': 0, 'SavedVariablesProfile': None, 'LastSyncDate': '0001-01-01T00:00:00'},
    'installedGamePrerequisites': [], 'wasNameManuallyChanged': False, 'wasGameVersionTypeIdManuallyChanged': False,
    'installedAddons': [],
}
CURSEFORGE_PROCESSES = ('curseforge.exe', 'curse.agent.host.exe')
ATTEMPTS = 3


def excluded(relative: str) -> bool:
    """Whether a path inside the modpack is personal or machine-made, so it is never shared."""
    lower=relative.replace('\\','/').casefold();top=lower.split('/',1)[0];name=lower.rsplit('/',1)[-1]
    if top in EXCLUDED_DIRS or top.startswith(EXCLUDED_PREFIXES):return True
    if '/' not in lower and name in EXCLUDED_FILES:return True
    return name.endswith(EXCLUDED_SUFFIXES) or (lower+'/').startswith(EXCLUDED_NESTED) or name.startswith(EXCLUDED_PREFIXES)


def modpack_files(instance: Path):
    """Relative paths of every file that is shared, sorted; excluded folders are not even entered."""
    found=[]
    for root,dirs,files in os.walk(instance):
        base=Path(root).relative_to(instance).as_posix()
        prefix='' if base=='.' else base+'/'
        dirs[:]=[d for d in dirs if not excluded(prefix+d) and not (Path(root)/d).is_symlink()]
        found+=[prefix+f for f in files if not excluded(prefix+f) and not (Path(root)/f).is_symlink()]
    return sorted(found)


def check_loader(loader) -> dict:
    """CurseForge's loader record (Forge/NeoForge version and its files), with every address checked."""
    if not isinstance(loader,dict) or not isinstance(loader.get('name'),str) or not loader['name']:
        raise ValueError('整合包沒有記錄 Forge／NeoForge 的版本，無法建立設定檔。')
    def walk(value,key=''):
        if isinstance(value,dict):
            for k,v in value.items():walk(v,str(k))
        elif isinstance(value,list):
            for v in value:walk(v,key)
        elif isinstance(value,str):
            if value[:1] in '{[':
                try:return walk(json.loads(value),key)
                except ValueError:pass
            # Address fields are what CurseForge downloads; Forge's own comments (a Patreon link) are not.
            if key.casefold().endswith('url') or key=='mirrorList':
                host=urlparse(value).netloc.casefold() if value else ''
                if value and (urlparse(value).scheme!='https' or host not in LOADER_HOSTS):
                    raise ValueError('整合包的載入器資料指向不明的網址：'+(host or value[:80]))
    walk(loader)
    return loader


def generated_options(instance: Path) -> bytes:
    """options.txt for players: Traditional Chinese and the owner's resource pack list, nothing personal."""
    try:text=(instance/'options.txt').read_text(encoding='utf-8')
    except (OSError,UnicodeError):text=''
    new=jobs.with_option('','lang','zh_tw')
    packs=jobs.enabled_packs(text)
    if packs:new=jobs.with_option(new,'resourcePacks',json.dumps(packs,ensure_ascii=False,separators=(',',':')))
    return new.encode('utf-8')


def curseforge_mods(instance: Path, record):
    """mods/<file> -> what CurseForge says it serves there (address, size, project, file)."""
    found={}
    for addon in record.get('installedAddons') if isinstance(record.get('installedAddons'),list) else []:
        try:
            installed=addon['installedFile'];name=str(installed.get('fileNameOnDisk') or installed['fileName'])
            url=patches.file_url(dict(url=installed.get('downloadUrl'),fileName=name))
            if not url or not name.lower().endswith('.jar'):continue
            found['mods/'+name]=dict(url=url,size=int(installed['fileLength']),projectID=int(addon['addonID']),
                                     fileID=int(installed['id']),name=str(addon.get('name') or name)[:120])
        except (KeyError,TypeError,ValueError,AttributeError):continue
    return found


def remote_matches(url: str, size: int, digest: str, session, cancelled=lambda:False) -> bool:
    """Whether CurseForge's file at `url` is byte for byte the owner's (size and SHA-256); read and discarded."""
    import requests
    for attempt in range(ATTEMPTS):
        try:
            h=hashlib.sha256();received=0
            with session.get(url,stream=True,timeout=(15,60),headers={'User-Agent':f'MCTranslator/{VERSION}'}) as r:
                if r.status_code==404:return False
                if r.status_code>=500:raise requests.ConnectionError(f'HTTP {r.status_code}')
                r.raise_for_status()
                if urlparse(r.url).netloc not in patches.CURSEFORGE_FILES:return False
                for block in r.iter_content(1024*1024):
                    if cancelled():raise InterruptedError('已停止。')
                    received+=len(block)
                    if received>size:return False
                    h.update(block)
            return received==size and h.hexdigest()==digest
        except (requests.ConnectionError,requests.Timeout):
            if attempt+1==ATTEMPTS:raise
            time.sleep(2*(attempt+1))
    return False


def build(instance: Path, out: Path, notify=lambda *_:None, cancelled=lambda:False, session=None, workers=4) -> dict:
    """Pack the owner's translated modpack into `out`; returns the manifest.

    Refuses a modpack CurseForge knows (it is shared as a translation patch instead).
    """
    import requests
    instance=Path(instance).resolve();out=Path(out);session=session or requests.Session()
    if not jobs.is_instance(instance):raise ValueError('找不到整合包資料夾（需要有 mods、config 或 kubejs）。')
    record=patches.curseforge_record(instance);identity=patches.instance_identity(instance)
    if identity['projectID']:raise ValueError('這個整合包在 CurseForge 上有正式版本，請改用一般的翻譯上架（只分享翻譯）。')
    loader=check_loader(record.get('baseModLoader'))
    files=modpack_files(instance);served=curseforge_mods(instance,record)
    notify(0,'整理整合包檔案',f'{len(files):,} 個檔案')
    entries={}
    for i,rel in enumerate(files):
        if cancelled():raise InterruptedError('已停止，沒有產生壓縮檔。')
        path=instance/rel;entries[rel]=dict(path=rel,size=path.stat().st_size,sha256=file_hash(path))
        if i%200==0:notify(int(30*i/max(1,len(files))),'計算每個檔案的校驗碼',rel)
    # A CurseForge mod is only linked when CurseForge serves exactly the owner's bytes (a translated or
    # replaced jar is not), so a player's download can be checked against the same SHA-256.
    candidates=[(rel,served[rel]) for rel in files if rel in served and entries[rel]['size']==served[rel]['size']]
    done=[0]
    def check(item):
        rel,mod=item
        same=remote_matches(mod['url'],mod['size'],entries[rel]['sha256'],session,cancelled)
        done[0]+=1;notify(30+int(30*done[0]/max(1,len(candidates))),'比對 CurseForge 上的模組',rel)
        return rel,mod,same
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rel,mod,same in pool.map(check,candidates):
            if same:entries[rel].update(source='curseforge',url=mod['url'],projectID=mod['projectID'],fileID=mod['fileID'],name=mod['name'])
    options=generated_options(instance)
    entries['options.txt']=dict(path='options.txt',size=len(options),sha256=hashlib.sha256(options).hexdigest())
    manifest=dict(format=FORMAT,name=identity['name'],version=identity['version'],gameVersion=identity['gameVersion'] or record.get('gameVersion') or '',
                  recommendedRam=identity['recommendedRam'],loader=loader,created=datetime.now().isoformat(timespec='seconds'),
                  program=VERSION,files=[dict(e,source=e.get('source','zip')) for e in entries.values()])
    manifest['totalSize']=sum(e['size'] for e in manifest['files'])
    out.parent.mkdir(parents=True,exist_ok=True);part=out.with_name(out.name+'.partial')
    bundled=[e for e in manifest['files'] if e['source']=='zip']
    try:
        with zipfile.ZipFile(part,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as z:
            for i,e in enumerate(bundled):
                if cancelled():raise InterruptedError('已停止，沒有產生壓縮檔。')
                kind=zipfile.ZIP_STORED if e['path'].casefold().endswith(STORED) else zipfile.ZIP_DEFLATED
                if e['path']=='options.txt':z.writestr(PAYLOAD+'options.txt',options,compress_type=kind)
                else:z.write(instance/e['path'],PAYLOAD+e['path'],compress_type=kind)
                if i%100==0:notify(60+int(40*i/max(1,len(bundled))),'寫入壓縮檔',e['path'])
            z.writestr(MANIFEST,json.dumps(manifest,ensure_ascii=False,indent=1))
        # Every bundled file is read back from the archive and checked against its SHA-256.
        verify_payload(part,read(part),cancelled)
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    notify(100,'壓縮檔已完成',str(out))
    return manifest


def read(path: Path):
    """The manifest of a full-pack zip, every field checked; raises ValueError on anything unexpected."""
    try:z=zipfile.ZipFile(path)
    except (OSError,zipfile.BadZipFile) as exc:raise ValueError('整合包壓縮檔損壞，無法讀取。') from exc
    with z:
        try:
            info=z.getinfo(MANIFEST)
            if info.file_size>256*1024*1024:raise ValueError
            manifest=json.loads(z.read(MANIFEST).decode('utf-8'))
        except (KeyError,ValueError,UnicodeError) as exc:raise ValueError('整合包壓縮檔缺少內容清單。') from exc
        if not isinstance(manifest,dict) or manifest.get('format')!=FORMAT:raise ValueError('整合包壓縮檔的格式不是這個版本能安裝的，請先更新本程式。')
        if not isinstance(manifest.get('name'),str) or not manifest['name'].strip():raise ValueError('整合包壓縮檔沒有名稱。')
        check_loader(manifest.get('loader'))
        files=manifest.get('files')
        if not isinstance(files,list) or not files or len(files)>MAX_FILES:raise ValueError('整合包壓縮檔的內容清單不合理。')
        names={i.filename:i for i in z.infolist()};seen=set();total=0;checked=[]
        for e in files:
            if not isinstance(e,dict):raise ValueError('整合包壓縮檔的內容清單格式錯誤。')
            rel=patches.clean_path(e.get('path'))
            if rel.casefold() in seen or rel.casefold()=='minecraftinstance.json':raise ValueError('整合包壓縮檔的內容清單有重複或不允許的檔案：'+rel)
            seen.add(rel.casefold())
            try:size=int(e['size'])
            except (KeyError,TypeError,ValueError):raise ValueError('整合包壓縮檔的內容清單缺少大小：'+rel)
            if not 0<=size<=MAX_FILE_SIZE or not re.fullmatch('[0-9a-f]{64}',str(e.get('sha256'))):raise ValueError('整合包壓縮檔的內容清單資料不合理：'+rel)
            total+=size;item=dict(path=rel,size=size,sha256=e['sha256'],source=e.get('source'))
            if e.get('source')=='curseforge':
                if not rel.startswith('mods/') or '/' in rel[5:]:raise ValueError('CurseForge 模組只能放在 mods 資料夾：'+rel)
                item.update(patches.checked_mod(dict(projectID=e.get('projectID'),fileID=e.get('fileID'),fileName=rel[5:],size=size,
                                                     sha256=e['sha256'],url=e.get('url'),name=e.get('name'))))
                if not item['url']:raise ValueError('CurseForge 模組缺少下載網址：'+rel)
                item['path']=rel
            elif e.get('source')=='zip':
                stored=names.get(PAYLOAD+rel)
                if stored is None or stored.file_size!=size:raise ValueError('整合包壓縮檔缺少檔案或大小不符：'+rel)
            else:raise ValueError('整合包壓縮檔的內容清單來源不明：'+rel)
            checked.append(item)
        if total>MAX_TOTAL_SIZE:raise ValueError('整合包太大，超過本程式允許的安裝大小。')
        extra=[n for n in names if n!=MANIFEST and not (n.startswith(PAYLOAD) and n[len(PAYLOAD):].casefold() in seen) and not n.endswith('/')]
        if extra:raise ValueError('整合包壓縮檔裡有內容清單沒有列出的檔案：'+extra[0])
    return dict(manifest,files=checked,totalSize=total)


def verify_payload(path: Path, manifest, cancelled=lambda:False):
    """Every file inside the zip hashes to what the content list says."""
    with zipfile.ZipFile(path) as z:
        for e in manifest['files']:
            if e['source']!='zip':continue
            if cancelled():raise InterruptedError('已停止。')
            h=hashlib.sha256()
            with z.open(PAYLOAD+e['path']) as f:
                for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
            if h.hexdigest()!=e['sha256']:raise ValueError('壓縮檔裡的檔案和內容清單不符：'+e['path'])


def drive_url(file_id: str) -> str:
    if not DRIVE_ID.fullmatch(str(file_id)):raise ValueError('雲端檔案位置不正確。')
    return f'https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t'


def drive_host(url: str) -> bool:
    p=urlparse(url)
    return p.scheme=='https' and (p.netloc in DRIVE_HOSTS or p.netloc.endswith('.googleusercontent.com'))


def download(pack, home: Path, progress=lambda _:None, session=None, cancelled=lambda:False, pause=time.sleep) -> Path:
    """The modpack zip from the owner's Google Drive, kept only when its size and SHA-256 match the catalog.

    A broken connection resumes where it stopped. Google answers with a web page instead of the file
    when the file is not shared publicly or has been downloaded too often; that is explained, not saved.
    """
    import requests
    session=session or requests.Session()
    folder=Path(home)/'downloads';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f"{pack['sha256']}.zip";part=folder/f"{pack['sha256']}.zip.partial"
    if path.exists() and path.stat().st_size==pack['size'] and file_hash(path)==pack['sha256']:return path
    problem=None
    for attempt in range(ATTEMPTS+2):
        if cancelled():raise InterruptedError('已停止下載，下次按「安裝」會從中斷的地方接著下載。')
        have=part.stat().st_size if part.exists() else 0
        headers={'User-Agent':f'MCTranslator/{VERSION}'}
        if have:headers['Range']=f'bytes={have}-'
        try:
            with session.get(drive_url(pack['driveId']),stream=True,timeout=(15,60),headers=headers) as r:
                if not all(drive_host(x.url) for x in [*r.history,r]):raise ValueError('下載被轉到 Google 雲端以外的位置，已停止。')
                if r.status_code>=500:raise requests.ConnectionError(f'HTTP {r.status_code}')
                if r.status_code==416:part.unlink(missing_ok=True);continue
                r.raise_for_status()
                if 'text/html' in r.headers.get('Content-Type',''):
                    raise ValueError('Google 雲端現在不讓下載這個檔案：可能是短時間內太多人下載（通常一天內會恢復），'
                                     '或分享者還沒有把檔案設成「知道連結的任何人」。請稍後再按「安裝」；已下載的部分會保留。')
                append=have and r.status_code==206
                with part.open('ab' if append else 'wb') as f:
                    received=have if append else 0
                    for block in r.iter_content(1024*1024):
                        if cancelled():raise InterruptedError('已停止下載，下次按「安裝」會從中斷的地方接著下載。')
                        received+=len(block)
                        if received>pack['size']:raise ValueError('下載到的檔案比目錄記錄的大，已停止。')
                        f.write(block);progress(int(received*100/max(1,pack['size'])))
            if part.stat().st_size<pack['size']:raise requests.ConnectionError('下載沒有完成')
            if file_hash(part)!=pack['sha256']:
                part.unlink(missing_ok=True)
                raise ValueError('下載到的整合包和分享者上傳的不是同一個（校驗不符），沒有安裝。請稍後再試。')
            part.replace(path)
            return path
        except (requests.ConnectionError,requests.Timeout) as exc:
            problem=exc
            pause(min(30,2*(attempt+1)))
    raise RuntimeError('從 Google 雲端下載一直中斷，請確認網路後再按「安裝」；已下載的部分會保留。') from problem


def system_curseforge_data_roots():
    """Local OS/app evidence for relocated data, without searching other Windows accounts."""
    roots=[]
    try:
        import psutil
        for proc in psutil.process_iter(['name','cmdline']):
            try:
                if (proc.info.get('name') or '').casefold() not in CURSEFORGE_PROCESSES:continue
                args=proc.info.get('cmdline') or []
                for i,arg in enumerate(args):
                    value=arg.split('=',1)[1] if arg.startswith('--user-data-dir=') else args[i+1] if arg=='--user-data-dir' and i+1<len(args) else ''
                    path=Path(value.strip('"')) if value else None
                    if path and path.is_absolute():roots.append(path)
            except (psutil.Error,OSError,ValueError):continue
    except (ImportError,OSError):pass
    if os.name=='nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                for name in ('AppData','Local AppData'):
                    try:
                        value,_=winreg.QueryValueEx(key,name)
                        path=Path(os.path.expandvars(value))
                        if path.is_absolute():roots.append(path/'CurseForge')
                    except (OSError,TypeError,ValueError):continue
        except OSError:pass
    return roots


def curseforge_list() -> Path:
    appdata=Path(os.environ.get('APPDATA',Path.home()/'AppData/Roaming'))
    candidates=[appdata,Path.home()/'AppData/Roaming',
                Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))]
    paths=[p/'agent/GameInstances/MinecraftGameInstance.json' for p in system_curseforge_data_roots()]
    paths += [p/'CurseForge/agent/GameInstances/MinecraftGameInstance.json' for p in candidates]
    return next((p for p in paths if p.is_file()),appdata/'CurseForge/agent/GameInstances/MinecraftGameInstance.json')


def require_curseforge_list(listing=None) -> Path:
    """Check Minecraft initialization before downloading a whole pack; absence is not proof of no app."""
    path=Path(listing) if listing is not None else curseforge_list()
    if not path.is_file():
        raise ValueError('找不到 CurseForge 的 Minecraft 整合包清單，無法安全登記新的整合包。'
                         '這不代表沒有安裝 CurseForge。請先重新開啟 CurseForge，再回來按「安裝」。'
                         '尚未設定 Minecraft 的玩家才需要進入 Minecraft 頁面完成遊戲資料夾設定。'
                         '若之前已能玩其他整合包仍遇到此訊息，請提供 CurseForge 的 Minecraft 設定畫面，以確認清單實際位置。')
    try:data=json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError,UnicodeError) as exc:
        raise ValueError('CurseForge 的整合包清單格式看不懂，沒有修改。') from exc
    if not isinstance(data,list):raise ValueError('CurseForge 的整合包清單格式看不懂，沒有修改。')
    return path


def curseforge_root(listing: Path) -> Path:
    """Where CurseForge keeps modpack folders: where most listed ones are, else its default."""
    try:data=json.loads(listing.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):data=[]
    counts={}
    for x in data if isinstance(data,list) else []:
        try:path=Path(x['installPath'].rstrip('\\/'))
        except (KeyError,TypeError,AttributeError):continue
        # Only a full path counts: a broken entry ('\\', relative) must never point at the program's own folder.
        if path.is_absolute() and path.parent!=path and path.parent.is_dir() and path.parent.parent!=path.parent:
            counts[path.parent]=counts.get(path.parent,0)+1
    return max(counts,key=counts.get) if counts else Path.home()/'curseforge/minecraft/Instances'


def curseforge_running() -> bool:
    import psutil
    for process in psutil.process_iter(['name']):
        if (process.info['name'] or '').casefold() in CURSEFORGE_PROCESSES:return True
    return False


def folder_name(name: str) -> str:
    name=FOLDER_NAME.sub('',name).strip().rstrip('. ')[:80].strip()
    return name if name and name.upper() not in ('CON','PRN','AUX','NUL') else 'Modpack'


def new_folder(root: Path, name: str) -> Path:
    base=folder_name(name)
    for n in range(1,1000):
        path=root/(base if n==1 else f'{base} ({n})')
        if not path.exists():return path
    raise ValueError('CurseForge 的整合包資料夾裡同名的資料夾太多了。')


def new_record(manifest, folder: Path) -> dict:
    now=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')+'0Z'
    record=json.loads(json.dumps(RECORD_TEMPLATE))
    record.update(baseModLoader=manifest['loader'],guid=str(uuid.uuid4()),installPath=str(folder)+'\\',name=folder.name,
                  gameVersion=manifest.get('gameVersion') or '',installDate=now,lastPreviousMatchUpdate=now,lastRefreshAttempt=now)
    return record


def register(listing: Path, folder: Path, record: dict, backup_dir: Path):
    """Add one profile to CurseForge's list (CurseForge must be closed). The list is backed up first and
    put back when the result does not read back with the new profile; nothing else in it changes."""
    raw=listing.read_bytes()
    data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,list):raise ValueError('CurseForge 的整合包清單格式看不懂，沒有修改。')
    end=raw.rstrip().rfind(b']')
    if end<0 or raw.rstrip()[-1:]!=b']':raise ValueError('CurseForge 的整合包清單格式看不懂，沒有修改。')
    backup_dir.mkdir(parents=True,exist_ok=True);backup=backup_dir/listing.name
    shutil.copy2(listing,backup)
    if file_hash(backup)!=file_hash(listing):raise ValueError('CurseForge 的整合包清單備份失敗，沒有修改。')
    entry=json.dumps(record,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    (folder/'minecraftinstance.json').write_bytes(entry)
    temp=listing.with_name(listing.name+'.mctranslator')
    temp.write_bytes(raw[:end]+(b',' if data else b'')+entry+raw[end:])
    try:
        os.replace(temp,listing)
        after=json.loads(listing.read_bytes().decode('utf-8-sig'))
        if len(after)!=len(data)+1 or after[-1].get('guid')!=record['guid']:raise ValueError('登記後讀回的內容不對')
    except Exception:
        shutil.copy2(backup,listing)
        raise
    finally:
        temp.unlink(missing_ok=True)
    return backup


def pack_id(name: str) -> str:
    """Which modpack a name stands for across versions: 'The Foll v0.3.0' and 'The Foll v0.4.0' are one."""
    base=re.sub(r'(?:[\s_-]+v?|[\s_-]*)\d+(?:\.\d+)+[a-z]?\s*$','',str(name),flags=re.I).strip()
    return (base or str(name)).casefold()


def installed(home: Path) -> dict:
    try:return json.loads((Path(home)/'full_packs.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def still_installed(home: Path, listing: Path | None = None) -> dict:
    """The installed records CurseForge still lists: deleting a profile there may leave its folder behind.
    When the list cannot be read, the folder alone decides (match_full)."""
    data=installed(home)
    try:text=Path(listing or curseforge_list()).read_text(encoding='utf-8-sig').casefold()
    except OSError:return data
    if not text.lstrip().startswith('['):return data
    return {k:r for k,r in data.items() if not isinstance(r,dict) or not r.get('guid') or str(r['guid']).casefold() in text}


def content_file(home: Path, guid: str) -> Path:
    """The content list (path -> SHA-256) a profile was installed or last updated with; updates compare against it."""
    if not re.fullmatch(r'[0-9a-f-]{36}',str(guid)):raise ValueError('設定檔編號不正確。')
    return Path(home)/'full_packs'/f'{guid}.json'


def remember(home: Path, folder: Path, manifest, package_sha: str, guid: str):
    # Keyed by the resolved path: a short 8.3 name (USERNA~1) and the long one must find the same record.
    home=Path(home);folder=Path(folder).resolve();data=installed(home)
    data[str(folder).casefold()]=dict(path=str(folder),name=manifest['name'],packId=pack_id(manifest['name']),
                                      version=manifest.get('version',''),sha256=package_sha,guid=guid,
                                      installed=datetime.now().isoformat(timespec='seconds'))
    jobs.write_json(home/'full_packs.json',data)
    path=content_file(home,guid);path.parent.mkdir(parents=True,exist_ok=True)
    jobs.write_json(path,{e['path']:e['sha256'] for e in manifest['files']})


def prepare_server(folder, staged, server):
    """Only the card's checked name/address travel; never import a sharer's server list."""
    found=server_list.checked(server)
    if not found:return None,dict(server=None,server_added=False,server_error='')
    result=dict(server=dict(zip(('name','address'),found)),server_added=False,server_error='')
    try:record=server_list.server_record(folder,staged,server,file_hash)
    except (ValueError,OSError) as exc:
        result['server_error']='原有伺服器清單無法安全更新，已保留原樣。'+jobs.explain_error(exc)
        return None,result
    result['server_added']=record is not None
    return record,result


def install(package: Path, home: Path, notify=lambda *_:None, cancelled=lambda:False, session=None, listing=None,
            running=curseforge_running, pause=time.sleep, wait_limit=3600, clock=time.monotonic, server=None) -> dict:
    """Install a full-pack zip as a new CurseForge profile; returns where it went.

    Nothing of the player's is changed except one profile added to CurseForge's list; a failure at any
    step removes the new folder and restores that list.
    """
    import requests
    home=Path(home);session=session or requests.Session()
    manifest=read(package)
    listing=require_curseforge_list(listing)
    root=curseforge_root(listing);root.mkdir(parents=True,exist_ok=True)
    linked=[e for e in manifest['files'] if e['source']=='curseforge']
    need=manifest['totalSize']+jobs.SPACE_MARGIN
    if shutil.disk_usage(root).free<need:
        raise ValueError(f'硬碟空間不夠安裝這個整合包（需要約 {need//1024//1024:,} MB），沒有修改任何檔案。')
    work=root/('.mctranslator-'+uuid.uuid4().hex[:8])
    moved=None;registered=False;sources=[]
    try:
        work.mkdir()
        bundled=[e for e in manifest['files'] if e['source']=='zip']
        with zipfile.ZipFile(package) as z:
            for i,e in enumerate(bundled):
                if cancelled():raise InterruptedError('已停止，沒有建立整合包。')
                target=contained(work,e['path']);target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(PAYLOAD+e['path']) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
                if i%100==0:notify(int(40*i/max(1,len(bundled))),'解開整合包',e['path'])
        for i,e in enumerate(linked):
            if cancelled():raise InterruptedError('已停止，沒有建立整合包。')
            title=f'從 CurseForge 下載模組（{i+1}／{len(linked)}）'
            source=patches.download_mod(e,home,lambda v,n=i:notify(40+int(30*(n+v/100)/max(1,len(linked))),title,e['name']),session,cancelled,pause)
            target=contained(work,e['path']);target.parent.mkdir(parents=True,exist_ok=True)
            # The downloaded copy stays until the install succeeds, so a retry does not download it again.
            try:os.link(source,target)
            except OSError:shutil.copyfile(source,target)
            sources.append(source)
        # The promise to the player: every file is the owner's, checked from disk.
        for i,e in enumerate(manifest['files']):
            if cancelled():raise InterruptedError('已停止，沒有建立整合包。')
            path=contained(work,e['path'])
            if not path.is_file() or path.stat().st_size!=e['size'] or file_hash(path)!=e['sha256']:
                raise ValueError('有檔案和分享者的不同（'+e['path']+'），沒有建立整合包。請再按一次「安裝」。')
            if i%200==0:notify(70+int(25*i/max(1,len(manifest['files']))),'逐檔核對內容',e['path'])
        start=clock()
        while running():
            if cancelled():raise InterruptedError('已停止，沒有建立整合包。')
            if clock()-start>wait_limit:raise ValueError('一直等不到 CurseForge 關閉，沒有建立整合包。關閉 CurseForge 後再按一次「安裝」，已下載的檔案不必重新下載。')
            notify(95,'請關閉 CurseForge','整合包已準備好；CurseForge 開著時無法加入新的設定檔，關閉後會自動繼續（包含右下角的小圖示）')
            pause(3)
        folder=new_folder(root,manifest['name'])
        # Files just written are often opened for a moment by an antivirus scan or the Windows indexer, and Windows
        # then refuses to rename the folder holding them: wait and try again (deployment.when_free).
        when_free(lambda:work.rename(folder),folder.name,lambda name:notify(96,'等待其他程式放開檔案','防毒或索引程式正在檢查剛下載的檔案：'+name))
        moved=folder
        staged=home/'tmp'/('fullserver-'+uuid.uuid4().hex[:8]);staged.mkdir(parents=True)
        try:
            server_record,server_result=prepare_server(folder,staged,server)
            server_backup=None
            if server_record:
                from .deployment import apply_reviewed
                server_backup=str(apply_reviewed(folder,staged,[server_record],home/'output',jobs.waiting_note(notify,96,'加入伺服器')))
        finally:shutil.rmtree(staged,ignore_errors=True)
        record=new_record(manifest,folder)
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
        register(listing,folder,record,home/'output'/folder.name/'CurseForge紀錄備份'/stamp)
        registered=True
        remember(home,folder,manifest,file_hash(Path(package)),record['guid'])
        for source in sources:Path(source).unlink(missing_ok=True)
        notify(100,'整合包已安裝',folder.name)
        return dict(folder=str(folder),name=folder.name,files=len(manifest['files']),downloaded=len(linked),
                    recommendedRam=manifest.get('recommendedRam') or 0,loader=manifest['loader'].get('name',''),
                    backup=server_backup,**server_result)
    except BaseException:
        # Only what this install made is removed: the work folder, or the new folder it became.
        if not registered:
            shutil.rmtree(work,ignore_errors=True)
            if moved:shutil.rmtree(moved,ignore_errors=True)
        raise


def update(package: Path, home: Path, folder: Path, notify=lambda *_:None, cancelled=lambda:False, session=None, pause=time.sleep, server=None) -> dict:
    """Bring an installed profile to a newer upload in place; saves, game options and screenshots stay.

    Compared with the content list it was installed with: a file the new version changed or added is
    written, a file it dropped is removed (only when the player did not change it), and options.txt is
    never touched. Every write and removal is one restorable batch, so 「備份與還原」 can undo the update.
    CurseForge's own records are not touched, so CurseForge may stay open; the game must be closed.
    """
    import requests
    from .deployment import apply_reviewed
    from .verifier import VerifyResult, check_java_zipfs
    home=Path(home);folder=Path(folder).resolve();session=session or requests.Session()
    if not jobs.is_instance(folder):raise ValueError('找不到要更新的整合包資料夾，可能已在 CurseForge 刪除。請改按「安裝」。')
    manifest=read(package)
    record=installed(home).get(str(folder).casefold()) or {}
    try:old=json.loads(content_file(home,record.get('guid','')).read_text(encoding='utf-8'))
    except (OSError,ValueError):old={}  # installed by an older version: nothing is removed, changed files are replaced
    jobs.ensure_game_closed(folder)
    staged=home/'tmp'/('fullupdate-'+uuid.uuid4().hex[:8]);staged.mkdir(parents=True)
    records=[];replaced=[];kept=[];sources=[]
    try:
        todo=[];new_paths=set()
        for e in manifest['files']:
            new_paths.add(e['path'].casefold())
            if e['path'].casefold()=='options.txt':continue  # the player's own settings
            current=file_hash(contained(folder,e['path']))
            if current!=e['sha256']:todo.append((e,current))
        bundled=[(e,c) for e,c in todo if e['source']=='zip'];linked=[(e,c) for e,c in todo if e['source']=='curseforge']
        with zipfile.ZipFile(package) as z:
            for i,(e,_) in enumerate(bundled):
                if cancelled():raise InterruptedError('已停止，整合包沒有更新。')
                target=contained(staged,e['path']);target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(PAYLOAD+e['path']) as src,target.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
                if i%100==0:notify(int(40*i/max(1,len(bundled))),'準備更新的檔案',e['path'])
        for i,(e,_) in enumerate(linked):
            if cancelled():raise InterruptedError('已停止，整合包沒有更新。')
            title=f'從 CurseForge 下載模組（{i+1}／{len(linked)}）'
            source=patches.download_mod(e,home,lambda v,n=i:notify(40+int(30*(n+v/100)/max(1,len(linked))),title,e['name']),session,cancelled,pause)
            target=contained(staged,e['path']);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target);sources.append(source)
        for e,current in todo:
            if file_hash(contained(staged,e['path']))!=e['sha256']:raise ValueError('有檔案和分享者的不同（'+e['path']+'），整合包沒有更新。')
            if current is not None and old and current!=old.get(e['path']):replaced.append(e['path'])  # the player had changed it
            records.append(dict(file=e['path'],before=current,after=e['sha256'],reviewed=True,verified=True))
        for path,sha in sorted(old.items()):
            if path.casefold() in new_paths or path.casefold()=='options.txt':continue
            current=file_hash(contained(folder,path))
            if current is None:continue
            if current==sha:records.append(dict(file=path,before=current,after=None,reviewed=True,verified=True))
            else:kept.append(path)  # dropped by the sharer but changed by the player: left alone
        jars=[contained(staged,r['file']) for r in records if r['after'] and r['file'].casefold().endswith('.jar')]
        if jars:
            vr=VerifyResult();check_java_zipfs(jars,vr)
            if not vr.ok:raise ValueError('更新的模組檔沒有通過檢查：'+'; '.join(vr.errors))
        server_record,server_result=prepare_server(folder,staged,server)
        if server_record:records.append(server_record)
        jobs.require_space(folder,home,[r['file'] for r in records])
        backup=None
        if records:
            notify(85,'備份與更新','先保存要換掉的檔案，再寫入新版本')
            jobs.ensure_game_closed(folder)
            backup=str(apply_reviewed(folder,staged,records,home/'output',jobs.waiting_note(notify,85,'備份與更新')))
        remember(home,folder,manifest,file_hash(Path(package)),record.get('guid') or str(uuid.uuid4()))
        for source in sources:Path(source).unlink(missing_ok=True)
        notify(100,'整合包已更新',folder.name)
        return dict(folder=str(folder),name=folder.name,written=sum(r['after'] is not None for r in records),
                    removed=sum(r['after'] is None for r in records),replaced=replaced,kept=kept,backup=backup,
                    recommendedRam=manifest.get('recommendedRam') or 0,**server_result)
    finally:
        shutil.rmtree(staged,ignore_errors=True)
