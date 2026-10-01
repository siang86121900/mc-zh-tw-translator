"""Translation patches: share a finished modpack translation and apply it to someone else's copy.

A patch holds translation text only, never mod code or whole mod jars:
- for a mod jar or resource-pack zip, just the language/book entries that were changed or added,
  together with the SHA-256 of the untranslated archive they belong to;
- for a loose file (KubeJS assets, quests, config), the translated file and the SHA-256 of the
  file it replaced (or null when it was new).

Applying only touches files whose current content is exactly the untranslated version the patch
was made from, so a different mod version is skipped instead of being overwritten. Every write
goes through apply_reviewed (backup, hash checks, rollback), so it can be restored like any batch.

Mods the translator added to the modpack through CurseForge are named in the patch (project, file,
size and SHA-256), never carried in it: the receiver's copy is downloaded from CurseForge itself and
must match that SHA-256 before it is put into the mods folder.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from . import desktop_jobs as jobs
from .deployment import apply_reviewed, contained, file_hash
from .translator import is_jar_signature_file
from .updater import REPOSITORY, VERSION, release_url
from .verifier import VerifyResult, check_java_zipfs

PATCH_FORMAT = 'mctranslator-patch-1'
CATALOG_URL = f'https://raw.githubusercontent.com/{REPOSITORY}/translations/index.json'
# Text resources only: a shared patch must never carry code, scripts or binaries.
TEXT_SUFFIXES = ('.json', '.lang', '.txt', '.md', '.snbt')
ARCHIVE_SUFFIXES = ('.jar', '.zip')
LOOSE_ROOTS = ('kubejs/assets/', 'kubejs/data/', 'config/', 'defaultconfigs/', 'resourcepacks/', 'datapacks/', 'patchouli_books/')
ARCHIVE_ROOTS = ('mods/', 'resourcepacks/', 'datapacks/', 'config/openloader/')
# The only things a translation writes: a Traditional Chinese language file, or a page of a zh_tw book.
# English files, recipes, loot tables, settings and scripts can therefore never come from a patch.
TRANSLATED = re.compile(r'(?:^|/)lang/zh_tw\.(?:json|lang)$|/zh_tw/[^/].*\.(?:json|txt|md|snbt)$|^config/ftbquests/quests/lang/zh_tw\.snbt$')
MAX_PATCH_SIZE = 200*1024*1024
MAX_ENTRY_SIZE = 64*1024*1024       # one translated file, unpacked
MAX_UNPACKED_SIZE = 1024*1024*1024  # the whole patch, unpacked
# Added mods come from CurseForge's own file servers and nowhere else.
CURSEFORGE_FILES = ('edge.forgecdn.net','mediafilez.forgecdn.net')
MAX_MOD_SIZE = 300*1024*1024
MAX_ADDED_MODS = 60
MOD_FILE_NAME = re.compile(r'[^\\/:*?"<>|\x00-\x1f]{1,180}\.jar',re.I)
ATTEMPTS = 3
ATTRIBUTION = """MC Translator 繁體中文翻譯補丁

這個補丁只包含翻譯文字，不含任何模組程式或模組檔案。請先安裝同一版本的模組包，
再用 MC Translator 的「已翻譯整合包」頁套用。

譯文可能引用以下社群翻譯，依其授權（CC BY-NC-SA 4.0）以相同授權免費分享、不得商用：
- CFPA Minecraft Mod Language Package  https://github.com/CFPAOrg/Minecraft-Mod-Language-Package
- TeamKugimiya ModsTranslationPack       https://github.com/TeamKugimiya/ModsTranslationPack
- TeamKugimiya ParaTranslationPack       https://github.com/TeamKugimiya/ParaTranslationPack
Minecraft 原版譯名版權屬於 Mojang；各模組文字版權屬於原作者。
"""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_path(value: str) -> str:
    """A relative POSIX path with no traversal, drive or empty parts."""
    value=str(value).replace('\\','/')
    p=PurePosixPath(value)
    if not value or p.is_absolute() or re.match(r'^[a-zA-Z]:',value) or any(x in ('','.','..') for x in value.split('/')):
        raise ValueError('補丁路徑不安全：'+value)
    return value


def allowed_file(file: str, archive: bool) -> bool:
    lower=file.casefold()
    if archive:return lower.startswith(ARCHIVE_ROOTS) and lower.endswith(ARCHIVE_SUFFIXES)
    return lower.startswith(LOOSE_ROOTS) and lower.endswith(TEXT_SUFFIXES) and bool(TRANSLATED.search(lower))


def allowed_entry(name: str) -> bool:
    lower=name.casefold()
    return lower.endswith(TEXT_SUFFIXES) and bool(TRANSLATED.search(lower))


def instance_identity(instance: Path) -> dict:
    """Which modpack and version a folder holds, from CurseForge's files when present."""
    identity=dict(name=instance.name,projectID=0,fileID=0,gameVersion='',version='',date='',recommendedRam=0)
    try:
        x=json.loads((instance/'minecraftinstance.json').read_text(encoding='utf-8-sig'))
        identity.update(name=x.get('name') or instance.name,projectID=int(x.get('projectID') or 0),
                        fileID=int(x.get('fileID') or 0),gameVersion=x.get('gameVersion') or '',
                        date=str(x.get('fileDate') or '')[:10])  # release date of the installed modpack version
    except (OSError,ValueError,TypeError):pass
    try:
        m=json.loads((instance/'manifest.json').read_text(encoding='utf-8-sig'))
        identity['version']=str(m.get('version') or '')
        if identity['name']==instance.name and m.get('name'):identity['name']=m['name']
        identity['gameVersion']=identity['gameVersion'] or (m.get('minecraft') or {}).get('version','')
        identity['recommendedRam']=ram_mb((m.get('minecraft') or {}).get('recommendedRam'))
    except (OSError,ValueError,TypeError,AttributeError):pass
    return identity


def ram_mb(value) -> int:
    """A memory size in MB from a modpack manifest or the catalog; 0 when missing or implausible."""
    try:value=int(value or 0)
    except (TypeError,ValueError):return 0
    return value if 512<=value<=256*1024 else 0


def gb(mb: int) -> str:
    return f'{mb/1024:.0f}' if mb>=10*1024 or mb%1024==0 else f'{mb/1024:.1f}'


def memory_advice(recommended: int, total: int = 0, record: dict | None = None) -> dict:
    """What to tell a player about memory: the modpack author's figure, whether this computer has room, how to set it.

    The program only explains; CurseForge's own settings are never changed (the player sets them there).
    Labels are CurseForge's own English ones (its app has no Chinese), checked in its app.asar.
    """
    if not recommended:return {}
    line=f'建議分給遊戲約 {gb(recommended)} GB 記憶體（整合包作者建議 {recommended:,} MB）。'
    warning=''
    if total and recommended>=total:
        warning=f'你的電腦只有約 {gb(total)} GB 記憶體，比建議的還少，這個整合包可能開不起來或很卡。'
    elif total and (recommended>total*0.75 or total-recommended<6*1024):
        # CurseForge itself warns above 75%; Windows and a browser alone take several GB of what is left.
        warning=(f'你的電腦共約 {gb(total)} GB，分給遊戲 {gb(recommended)} GB 後剩下不多；'
                 '玩的時候請先關掉瀏覽器等其他程式。')
    record=record or {}
    try:current=int(record.get('allocatedMemory') or 0) if record.get('isMemoryOverride') else 0
    except (TypeError,ValueError):current=0
    now=(f'這個整合包目前在 CurseForge 設定為 {gb(current)} GB'+('，比建議少。' if current<recommended-256 else '。')
         if current else '')
    steps=('調整方式（CurseForge 的選項是英文）：\n'
           '1. 在 CurseForge 的「My Modpacks」對這個整合包按右鍵，選「Profile Options」。\n'
           '2. 找到「Memory Settings」，選「Recommended by Author」（照整合包作者的建議）；'
           f'或選「Custom RAM Allocation」，把記憶體拉到約 {gb(recommended)} GB。\n'
           '3. 關掉視窗後重新開遊戲就會生效。\n\n'
           '本程式不會修改 CurseForge 的設定，需要你自己調整。')
    return dict(line=line,warning=warning,now=now,steps=steps)


def curseforge_record(instance: Path):
    """CurseForge's own record of a modpack folder, or {} when it has none."""
    try:
        data=json.loads((Path(instance)/'minecraftinstance.json').read_text(encoding='utf-8-sig'))
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def modpack_projects(instance: Path, record=None):
    """CurseForge project numbers of the mods the modpack itself brings, or None when that is unknown."""
    record=curseforge_record(instance) if record is None else record
    manifest=record.get('manifest') if isinstance(record.get('manifest'),dict) else None
    if not manifest:
        try:manifest=json.loads((Path(instance)/'manifest.json').read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):return None
    try:return {int(f['projectID']):int(f['fileID']) for f in manifest.get('files') or []} or None
    except (KeyError,TypeError,ValueError,AttributeError):return None


def file_url(mod):
    """Where CurseForge serves this file; an address outside its file servers is never used."""
    url=mod.get('url')
    if isinstance(url,str):
        p=urlparse(url)
        if p.scheme=='https' and p.netloc in CURSEFORGE_FILES and p.path.startswith('/files/') and not p.query and not p.fragment:return url
        raise ValueError('模組下載網址不是 CurseForge 的檔案伺服器：'+str(mod.get('fileName')))
    return None


def checked_mod(mod):
    """One added mod as read from a patch, with every field checked; raises on anything unexpected."""
    if not isinstance(mod,dict):raise ValueError('補丁的加裝模組資料格式錯誤。')
    name=mod.get('fileName')
    if not isinstance(name,str) or not MOD_FILE_NAME.fullmatch(name) or name.startswith('.') or '..' in name:
        raise ValueError('補丁的加裝模組檔名不安全：'+str(name)[:80])
    try:project=int(mod['projectID']);file=int(mod['fileID']);size=int(mod['size'])
    except (KeyError,TypeError,ValueError):raise ValueError('補丁的加裝模組資料不完整：'+name)
    if project<=0 or file<=0 or not 0<size<=MAX_MOD_SIZE:raise ValueError('補丁的加裝模組資料不合理：'+name)
    if not re.fullmatch('[0-9a-f]{64}',str(mod.get('sha256'))):raise ValueError('補丁的加裝模組缺少校驗碼：'+name)
    page=mod.get('page') if isinstance(mod.get('page'),str) and mod['page'].startswith('https://www.curseforge.com/') else ''
    return dict(projectID=project,fileID=file,fileName=name,size=size,sha256=mod['sha256'],url=file_url(mod),
                name=str(mod.get('name') or name)[:120],page=page[:300])


def added_mods(instance: Path, originals=None):
    """(mods, left_out): what the owner added through CurseForge on top of the modpack.

    `originals` maps a translated file to the SHA-256 it had before translation; the receiver
    downloads the untranslated file, so that is the hash that counts. A mod is left out, with the
    reason, when it cannot be given to someone else safely.
    """
    instance=Path(instance);record=curseforge_record(instance);official=modpack_projects(instance,record)
    addons=record.get('installedAddons') if isinstance(record.get('installedAddons'),list) else []
    if official is None:
        return [],([dict(name='加裝的模組',reason='找不到整合包原本的模組清單，無法分辨哪些是後來加裝的')] if addons else [])
    mods=[];left=[];known=set()
    for addon in addons:
        try:
            installed=addon['installedFile'];project=int(addon['addonID']);file=int(installed['id'])
            name=str(installed.get('fileNameOnDisk') or installed['fileName']);label=str(addon.get('name') or name)
        except (KeyError,TypeError,ValueError):continue
        known.add(name.casefold())
        if project in official:
            if official[project]!=file and (instance/'mods'/name).is_file():
                left.append(dict(name=label,reason='整合包原有的模組被換成別的版本；對方保留整合包的版本，這個模組的翻譯會略過'))
            continue
        if ((addon.get('categorySection') or {}).get('path') or 'mods')!='mods' or not name.lower().endswith('.jar'):continue
        path=instance/'mods'/name
        if not path.is_file():continue  # disabled or removed
        relative='mods/'+name;digest=(originals or {}).get(relative) or file_hash(path)
        try:
            mod=checked_mod(dict(projectID=project,fileID=file,fileName=name,size=installed.get('fileLength'),sha256=digest,
                                 url=installed.get('downloadUrl') or None,name=label,page=addon.get('webSiteURL')))
        except ValueError as exc:
            left.append(dict(name=label,reason=str(exc)));continue
        if not (originals or {}).get(relative) and path.stat().st_size!=mod['size']:
            left.append(dict(name=label,reason='檔案和 CurseForge 記錄的大小不同（可能被修改過），不分享'));continue
        if addon.get('allowModDistribution') is False:mod['url']=None  # the author lets only CurseForge itself install it
        mods.append(mod)
    try:
        for p in sorted((instance/'mods').iterdir()):
            if p.is_file() and p.suffix.lower()=='.jar' and p.name.casefold() not in known and 'mods/'+p.name!=jobs.PACK_MOD_FILE:
                left.append(dict(name=p.name,reason='不是從 CurseForge 安裝的模組，對方無法自動下載'))
    except OSError:pass
    if len(mods)>MAX_ADDED_MODS:
        left+=[dict(name=m['name'],reason=f'加裝的模組超過 {MAX_ADDED_MODS} 個，超出的不分享') for m in mods[MAX_ADDED_MODS:]];mods=mods[:MAX_ADDED_MODS]
    return mods,left


def installed_batches(home: Path, instance: Path):
    """Backups of batches still applied to this instance, oldest first."""
    target=instance.resolve();found=[]
    for p in (home/'output').glob('*/原始備份/*/_備份紀錄/manifest.json'):
        try:
            record=json.loads(p.read_text(encoding='utf-8'))
            if record.get('status')=='installed' and Path(record['instance']).resolve()==target:
                found.append((p.parents[1],record))
        except (OSError,ValueError,KeyError):continue
    return sorted(found,key=lambda x:x[0].name)


def archive_changes(original: bytes, current: bytes, file: str):
    """Entries that translation changed or added; anything else differing means it is not a pure translation."""
    with zipfile.ZipFile(io.BytesIO(original)) as a, zipfile.ZipFile(io.BytesIO(current)) as b:
        before=set(a.namelist());after=set(b.namelist());changed={}
        for name in before-after:
            if not is_jar_signature_file(name):raise ValueError(f'{file} 少了非簽章項目 {name}')
        for name in after:
            data=b.read(name)
            if name in before and a.read(name)==data:continue
            if not allowed_entry(name):raise ValueError(f'{file} 有非翻譯內容變動：{name}')
            changed[name]=data
        return changed


def pack_entries(data: bytes):
    """(entries, requires) of the translation resource pack: each translated file, and for each the mod
    files (with SHA-256) it translates. Files the pack cannot tie to a mod version are not shared."""
    entries={};requires={}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        try:sources=json.loads(z.read(jobs.PACK_SOURCES).decode('utf-8')).get('sources',{})
        except (KeyError,ValueError):sources={}
        for name in z.namelist():
            mods=sources.get(name)
            if not allowed_entry(name) or not isinstance(mods,dict) or not mods:continue
            entries[name]=z.read(name);requires[name]=dict(mods)
    return entries,requires


def mods_by_hash(instance: Path):
    """SHA-256 -> mod file (relative path) for the receiver's mods folder, to find renamed copies."""
    found={}
    folder=Path(instance)/'mods'
    for p in sorted(folder.glob('*.jar')) if folder.is_dir() else []:
        try:found.setdefault(file_hash(p),'mods/'+p.name)
        except OSError:continue
    return found


def export_patch(instance: Path, home: Path, notify=lambda *_:None) -> dict:
    """Collect this instance's applied translations into one shareable zip.

    Only files still exactly as the last applied batch left them are exported; a file that was
    restored or edited afterwards is listed as skipped.
    """
    instance=Path(instance).resolve()
    batches=installed_batches(home,instance)
    if not batches:raise ValueError('這個模組包還沒有套用過翻譯，無法匯出。請先完成「一鍵完整翻譯並套用」。')
    files={}
    for backup,record in batches:
        for row in record['files']:
            item=files.setdefault(row['file'],dict(before=row['before'],backup=backup))
            item['after']=row['after']
    identity=instance_identity(instance)
    mods,left_out=added_mods(instance,{file:item['before'] for file,item in files.items() if item['before']})
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    folder=home/'output'/instance.name/'分享';folder.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r'[\\/:*?"<>|]+','_',identity['name']).strip() or 'modpack'
    out=folder/f'{safe}{"-"+identity["version"] if identity["version"] else ""}-繁中翻譯-{stamp}.zip'
    manifest=dict(format=PATCH_FORMAT,app_version=VERSION,created=datetime.now().isoformat(timespec='seconds'),
                  modpack=identity,files=[],added_mods=mods,left_out_mods=left_out)
    skipped=[]
    tmp=out.with_suffix('.partial')
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as w:
            for i,(file,item) in enumerate(sorted(files.items())):
                notify(int(90*i/max(1,len(files))),'整理翻譯補丁',file)
                archive=file.casefold().endswith(ARCHIVE_SUFFIXES)
                path=contained(instance,file)
                if file.casefold()=='options.txt':continue  # personal game setting, never shared
                if not allowed_file(file,archive):skipped.append((file,'不是可分享的翻譯檔'));continue
                if file_hash(path)!=item['after']:skipped.append((file,'套用後又被修改或已還原'));continue
                current=path.read_bytes()
                if file==jobs.RESOURCE_PACK_FILE:
                    entries,requires=pack_entries(current)
                    if not entries:skipped.append((file,'翻譯資源包裡沒有可對應到模組版本的翻譯'));continue
                    for name,data in entries.items():w.writestr(f'payload/{file}/{name}',data)
                    jars={jar for mods in requires.values() for jar in mods}
                    sizes={jar:contained(instance,jar).stat().st_size for jar in sorted(jars) if contained(instance,jar).is_file()}
                    manifest['files'].append(dict(file=file,archive=True,pack=True,before=None,
                                                  entries={n:sha256(d) for n,d in entries.items()},requires=requires,sizes=sizes))
                    continue
                if archive:
                    if item['before'] is None:skipped.append((file,'翻譯新增的整個模組檔不分享'));continue
                    original=contained(item['backup'],file).read_bytes()
                    if sha256(original)!=item['before']:skipped.append((file,'備份內容與清冊不符'));continue
                    try:changed=archive_changes(original,current,file)
                    except (ValueError,zipfile.BadZipFile) as exc:skipped.append((file,str(exc)));continue
                    entries={}
                    for name,data in changed.items():
                        w.writestr(f'payload/{file}/{name}',data);entries[name]=sha256(data)
                    manifest['files'].append(dict(file=file,archive=True,before=item['before'],size=len(original),entries=entries))
                else:
                    w.writestr(f'payload/{file}',current)
                    manifest['files'].append(dict(file=file,archive=False,before=item['before'],after=item['after']))
            if not manifest['files']:raise ValueError('沒有可分享的翻譯檔。'+('；'.join(f'{f}：{r}' for f,r in skipped[:5])))
            manifest['skipped']=[dict(file=f,reason=r) for f,r in skipped]
            w.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            w.writestr('授權與來源.txt',ATTRIBUTION)
            # Per-string sources (AI, converted, reference), so the receiver's report keeps the same labels.
            w.writestr('provenance.json',json.dumps(jobs.Provenance(home,instance).entries,ensure_ascii=False))
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    notify(100,'翻譯補丁已匯出',str(out))
    return dict(path=str(out),files=len(manifest['files']),skipped=manifest['skipped'],modpack=identity,sha256=file_hash(out),size=out.stat().st_size,
                added_mods=mods,left_out_mods=left_out)


def read_patch(path: Path):
    """Open a patch and validate its manifest; the caller closes the returned ZipFile."""
    path=Path(path)
    if path.stat().st_size>MAX_PATCH_SIZE:raise ValueError('補丁檔案過大。')
    z=zipfile.ZipFile(path)
    try:
        manifest=json.loads(z.read('manifest.json').decode('utf-8'))
        if manifest.get('format')!=PATCH_FORMAT:raise ValueError('不是 MC Translator 翻譯補丁，或需要更新程式才能讀取。')
        # Sizes are checked before anything is unpacked, so a small download cannot expand without limit.
        if any(i.file_size>MAX_ENTRY_SIZE for i in z.infolist()) or sum(i.file_size for i in z.infolist())>MAX_UNPACKED_SIZE:
            raise ValueError('補丁解開後的大小超過上限，已拒絕。')
        names=set(z.namelist());seen=set()
        for item in manifest['files']:
            file=clean_path(item['file']);archive=bool(item['archive'])
            if not allowed_file(file,archive):raise ValueError('補丁包含不允許的檔案：'+file)
            if file.casefold() in seen:raise ValueError('補丁包含重複檔案：'+file)
            seen.add(file.casefold())
            for h in [item.get('before'),item.get('after')]+list((item.get('entries') or {}).values()):
                if h is not None and not re.fullmatch('[0-9a-f]{64}',str(h)):raise ValueError('補丁雜湊格式錯誤：'+file)
            if item.get('pack'):
                # The translation resource pack: each file names the mod versions (SHA-256) it belongs to.
                requires=item.get('requires')
                if file!=jobs.RESOURCE_PACK_FILE or not item.get('entries') or not isinstance(requires,dict) or set(requires)!=set(item['entries']):
                    raise ValueError('補丁的翻譯資源包資料不完整。')
                for name,mods in requires.items():
                    if not isinstance(mods,dict) or not mods:raise ValueError('補丁的翻譯資源包資料不完整。')
                    for jar,h in mods.items():
                        jar=clean_path(jar)
                        if not jar.casefold().startswith('mods/') or not jar.casefold().endswith('.jar') or not re.fullmatch('[0-9a-f]{64}',str(h)):
                            raise ValueError('補丁的翻譯資源包資料不合理：'+name)
                sizes=item.get('sizes') or {}
                if not isinstance(sizes,dict) or any(not isinstance(v,int) or isinstance(v,bool) or not 0<v<=MAX_MOD_SIZE for v in sizes.values()):
                    raise ValueError('補丁的翻譯資源包資料不合理。')
                for jar in sizes:clean_path(jar)
            elif archive and not item.get('before'):raise ValueError('補丁項目不完整：'+file)
            if archive:
                if not item.get('entries'):raise ValueError('補丁項目不完整：'+file)
                for name in item['entries']:
                    clean_path(name)
                    if not allowed_entry(name):raise ValueError(f'補丁包含不允許的內容：{file} / {name}')
                    if f'payload/{file}/{name}' not in names:raise ValueError(f'補丁缺少內容：{file} / {name}')
            elif f'payload/{file}' not in names or not item.get('after'):raise ValueError('補丁缺少內容：'+file)
        mods=manifest.get('added_mods') or []
        if not isinstance(mods,list) or len(mods)>MAX_ADDED_MODS:raise ValueError('補丁的加裝模組清單不合理，已拒絕。')
        manifest['added_mods']=[checked_mod(m) for m in mods]
        if len({m['fileName'].casefold() for m in manifest['added_mods']})!=len(mods):raise ValueError('補丁的加裝模組重複，已拒絕。')
        return z,manifest
    except Exception:
        z.close();raise


def find_archive(instance: Path, item):
    """The instance's copy of a translated archive: same path, else any same-size file with the same hash."""
    path=contained(instance,item['file'])
    if path.is_file() and file_hash(path)==item['before']:return path
    folder=path.parent
    if folder.is_dir():
        for other in folder.iterdir():
            if other!=path and other.is_file() and other.stat().st_size==item.get('size') and file_hash(other)==item['before']:
                return other
    return None


def archive_has(path: Path, z, item) -> bool:
    try:
        with zipfile.ZipFile(path) as a:
            names=set(a.namelist())
            return all(n in names and sha256(a.read(n))==h for n,h in item['entries'].items())
    except (OSError,zipfile.BadZipFile):
        return False


def plan_patch(instance: Path, z, manifest):
    """Decide per file: apply, already translated, or skip (different version or edited)."""
    plan=[];index=None
    for item in manifest['files']:
        path=contained(instance,item['file'])
        if item.get('pack'):
            # Only the files whose mods are exactly the versions they were translated from.
            if index is None:index=mods_by_hash(instance)
            # A mod file counts when any file in the receiver's mods folder has its exact SHA-256 (renamed copies too).
            use=[name for name,mods in item['requires'].items() if all(h in index for h in mods.values())]
            item['use']=use
            have,_=jobs.read_resource_pack(instance)
            # Each mod whose version differs is named, so the result says whose translation was left out.
            for jar in sorted({jar for mods in item['requires'].values() for jar,h in mods.items() if h not in index}):
                there=contained(instance,jar).exists()
                plan.append((dict(file=jar),'skip',contained(instance,jar),'模組版本和翻譯時不同' if there else '找不到這個模組檔（可能是不同版本的模組包）'))
            if not use:continue
            if all(sha256(have.get(n,b''))==item['entries'][n] for n in use):plan.append((item,'already',path,''))
            else:plan.append((item,'apply',path,''))
            continue
        if item['archive']:
            target=find_archive(instance,item)
            if target:plan.append((item,'apply',target,''))
            elif path.is_file() and archive_has(path,z,item):plan.append((item,'already',path,''))
            elif path.exists():plan.append((item,'skip',path,'模組版本和翻譯時不同'))
            else:plan.append((item,'skip',path,'找不到這個模組檔（可能是不同版本的模組包）'))
        else:
            current=file_hash(path) if path.exists() else None
            if current==item['after']:plan.append((item,'already',path,''))
            elif current==item['before']:plan.append((item,'apply',path,''))
            else:plan.append((item,'skip',path,'這個檔案和翻譯時的版本不同' if path.exists() else '原本的檔案不存在'))
    return plan


def mod_states(instance: Path, mods):
    """For each added mod: 'present', 'install', 'other_version' or 'manual'."""
    instance=Path(instance);record=curseforge_record(instance)
    have={}
    for addon in record.get('installedAddons') if isinstance(record.get('installedAddons'),list) else []:
        try:have[int(addon['addonID'])]=str((addon['installedFile'].get('fileNameOnDisk') or addon['installedFile']['fileName']))
        except (KeyError,TypeError,ValueError,AttributeError):continue
    try:sizes={p:p.stat().st_size for p in (instance/'mods').iterdir() if p.is_file()}
    except OSError:sizes={}
    states=[]
    for mod in mods:
        path=instance/'mods'/mod['fileName']
        same=[p for p,size in sizes.items() if size==mod['size'] and file_hash(p)==mod['sha256']]
        if same or path.exists():state='present'  # a file of that name with other content is its translated copy
        elif mod['projectID'] in have and (instance/'mods'/have[mod['projectID']]).exists():state='other_version'
        elif not mod['url']:state='manual'
        else:state='install'
        states.append((mod,state))
    return states


def download_mod(mod, home: Path, progress=lambda _:None, session=None, cancelled=lambda:False, pause=time.sleep) -> Path:
    """One added mod from CurseForge, kept only when its size and SHA-256 are the translator's."""
    import requests
    session=session or requests.Session()
    folder=home/'downloads'/'mods';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(mod['sha256']+'.jar')
    if path.exists() and path.stat().st_size==mod['size'] and file_hash(path)==mod['sha256']:return path
    url=file_url(mod);problem=None
    if not url:raise ValueError('這個模組的作者只開放由 CurseForge 安裝。')
    for attempt in range(ATTEMPTS):
        if cancelled():raise InterruptedError('已停止。')
        part=folder/(uuid.uuid4().hex+'.partial');h=hashlib.sha256();received=0
        try:
            with session.get(url,stream=True,timeout=(15,60),headers={'User-Agent':f'MCTranslator/{VERSION}'}) as response:
                if response.status_code>=500:raise requests.ConnectionError(f'HTTP {response.status_code}')
                response.raise_for_status()
                host=urlparse(response.url).netloc
                if host not in CURSEFORGE_FILES:raise ValueError('下載被轉到 CurseForge 以外的位置，沒有安裝。')
                with part.open('xb') as f:
                    for block in response.iter_content(1024*1024):
                        if cancelled():raise InterruptedError('已停止。')
                        received+=len(block)
                        if received>mod['size']:raise ValueError('下載到的檔案比翻譯者使用的大（校驗不符），沒有安裝。')
                        h.update(block);f.write(block);progress(int(received*100/mod['size']))
            if received!=mod['size'] or h.hexdigest()!=mod['sha256']:
                raise ValueError('下載到的檔案和翻譯者使用的不是同一個（校驗不符），沒有安裝。')
            if not zipfile.is_zipfile(part):raise ValueError('下載到的不是模組檔，沒有安裝。')
            part.replace(path)
            return path
        except (requests.ConnectionError,requests.Timeout) as exc:
            problem=exc
            if attempt+1<ATTEMPTS:pause(2*(attempt+1))
        finally:
            part.unlink(missing_ok=True)
    raise RuntimeError('連不上 CurseForge 的檔案伺服器，請確認網路後再試一次。') from problem


def install_mods(instance: Path, mods, home: Path, notify=lambda *_:None, cancelled=lambda:False, session=None, pause=time.sleep) -> dict:
    """Put the translator's added mods into the modpack: downloaded from CurseForge, verified, backed
    up like any batch so that restoring the batch removes them again.

    A mod that cannot be installed never stops the others or the translation; it is reported with
    the reason and what to do.
    """
    instance=Path(instance).resolve()
    result=dict(installed=[],present=[],skipped=[],backup=None)
    states=mod_states(instance,mods);wanted=[m for m,s in states if s=='install']
    reasons={'other_version':'已安裝這個模組的其他版本，沒有更動；這個模組的翻譯會略過',
             'manual':'作者只開放由 CurseForge 安裝，請在 CurseForge 加裝這個模組'}
    for mod,state in states:
        if state=='present':result['present'].append(mod['fileName'])
        elif state!='install':result['skipped'].append(dict(name=mod['name'],file=mod['fileName'],reason=reasons[state],page=mod['page']))
    if not wanted:return result
    needed=sum(m['size'] for m in wanted)
    for folder,times in ((instance,1),(home,2)):
        free=shutil.disk_usage(folder if folder.exists() else folder.parent).free
        if free<needed*times+jobs.SPACE_MARGIN:
            raise ValueError(f'硬碟空間不夠加裝模組（需要約 {(needed*times+jobs.SPACE_MARGIN)//1024//1024:,} MB），沒有修改任何檔案。')
    staged=home/'tmp'/('mods-'+uuid.uuid4().hex[:8]);records=[]
    try:
        for i,mod in enumerate(wanted):
            if cancelled():raise InterruptedError('已停止，沒有加裝任何模組。')
            title=f"下載加裝的模組（{i+1}／{len(wanted)}）"
            notify(int(100*i/len(wanted)),title,mod['name'])
            try:
                source=download_mod(mod,home,lambda v,m=mod,n=i:notify(int(100*(n+v/100)/len(wanted)),title,f"{m['name']} {v}%"),session,cancelled,pause)
            except InterruptedError:raise
            except Exception as exc:
                result['skipped'].append(dict(name=mod['name'],file=mod['fileName'],page=mod['page'],
                                               reason=jobs.explain_error(exc)+' 也可以在 CurseForge 自行加裝這個模組。'));continue
            target=contained(staged,'mods/'+mod['fileName']);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            records.append(dict(file='mods/'+mod['fileName'],before=None,after=mod['sha256'],reviewed=True,verified=True))
            result['installed'].append(mod['fileName'])
        if records:
            vr=VerifyResult();check_java_zipfs([staged/r['file'] for r in records],vr)
            if not vr.ok:raise ValueError('加裝的模組檔沒有通過檢查：'+'; '.join(vr.errors))
            jobs.ensure_game_closed(instance)
            notify(100,'加裝模組','寫入模組資料夾')
            result['backup']=str(apply_reviewed(instance,staged,records,home/'output',jobs.waiting_note(notify,100,'加裝模組')))
        return result
    finally:
        shutil.rmtree(staged,ignore_errors=True)


def apply_patch(instance: Path, patch: Path, home: Path, notify=lambda *_:None, set_language=False,
                add_mods=False, cancelled=lambda:False, session=None) -> dict:
    """Apply a translation patch to an instance; only files matching the patch's original version change.

    With add_mods the mods the translator added are installed first, so their translation applies too.
    """
    instance=Path(instance).resolve()
    if not jobs.is_instance(instance):raise ValueError('找不到模組包資料夾（需要有 mods、config 或 kubejs）。')
    z,manifest=read_patch(patch)
    staged=home/'tmp'/('patch-'+uuid.uuid4().hex[:8])
    try:
        jobs.ensure_game_closed(instance)
        mods=install_mods(instance,manifest['added_mods'],home,notify,cancelled,session) if add_mods and manifest['added_mods'] else None
        if cancelled():raise InterruptedError('已停止，翻譯還沒有寫入。'+('加裝的模組已放進模組資料夾，可在「備份與還原」移除。' if mods and mods['installed'] else ''))
        plan=plan_patch(instance,z,manifest)
        staged.mkdir(parents=True)
        records=[];applied=[]
        todo=[p for p in plan if p[1]=='apply']
        for i,(item,_,target,_) in enumerate(todo):
            notify(int(70*i/max(1,len(todo))),'準備套用翻譯',item['file'])
            relative=target.relative_to(instance).as_posix()
            dst=contained(staged,relative);dst.parent.mkdir(parents=True,exist_ok=True)
            if item.get('pack'):
                files,sources=jobs.read_resource_pack(instance)
                for name in item['use']:
                    data=z.read(f'payload/{item["file"]}/{name}')
                    if sha256(data)!=item['entries'][name]:raise ValueError('補丁內容損壞：'+item['file'])
                    if name.endswith('.json') and '/lang/' in name and name in files:
                        # Keep what the receiver's pack already translated for keys the patch does not carry.
                        try:data=json.dumps({**jobs.parse(files[name]),**jobs.parse(data)},ensure_ascii=False,indent=2).encode('utf-8')
                        except ValueError:pass
                    files[name]=data;sources[name]=dict(item['requires'][name])
                staged_records=jobs.stage_resource_pack(instance,staged,files,sources)
                records+=staged_records;applied.append(relative)
                continue
            if item['archive']:
                modified={}
                for name,h in item['entries'].items():
                    data=z.read(f'payload/{item["file"]}/{name}')
                    if sha256(data)!=h:raise ValueError('補丁內容損壞：'+item['file'])
                    modified[name]=data
                with zipfile.ZipFile(target) as src:jobs.rewrite_archive(src,dst,modified,relative)
            else:
                data=z.read(f'payload/{item["file"]}')
                if sha256(data)!=item['after']:raise ValueError('補丁內容損壞：'+item['file'])
                dst.write_bytes(data)
            records.append(dict(file=relative,before=item['before'],after=file_hash(dst),reviewed=True,verified=True))
            applied.append(relative)
        uses_pack=any(r['file']==jobs.RESOURCE_PACK_FILE for r in records) or (instance/jobs.RESOURCE_PACK_FILE).is_file()
        try:record=jobs.options_record(instance,staged,set_language,uses_pack)
        except ValueError:record=jobs.options_record(instance,staged,set_language,False)
        if record:records.append(record)
        jobs.require_space(instance,home,applied)
        backup=None
        if records:
            jars=[staged/r['file'] for r in records if r['file'].casefold().endswith('.jar')]
            if jars:
                vr=VerifyResult();check_java_zipfs(jars,vr)
                if not vr.ok:raise ValueError('Java 驗證未通過：'+'; '.join(vr.errors))
            notify(80,'備份與套用','先保存所有原檔，再寫入翻譯')
            jobs.ensure_game_closed(instance)
            backup=str(apply_reviewed(instance,staged,records,home/'output',jobs.waiting_note(notify)))
        result=dict(instance=str(instance),patch=str(patch),modpack=manifest.get('modpack',{}),backup=backup,applied=applied,
                    already=[p[0]['file'] for p in plan if p[1]=='already'],
                    skipped=[dict(file=p[0]['file'],reason=p[3]) for p in plan if p[1]=='skip'],
                    language_set=bool(set_language),mods=mods,
                    mods_offered=[m['name'] for m in manifest['added_mods']] if mods is None else [])
        record_applied(home,instance,manifest,file_hash(Path(patch)))
        if applied or result_already(plan):jobs.record_translated(home,instance)
        merge_provenance(home,instance,z)
        report=home/'output'/instance.name/'報告'/('補丁-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
        report.mkdir(parents=True,exist_ok=True)
        jobs.write_json(report/'patch_result.json',result)
        notify(100,'翻譯補丁已套用',f'套用 {len(applied)} 個檔案，略過 {len(result["skipped"])} 個')
        return result
    finally:
        z.close()
        shutil.rmtree(staged,ignore_errors=True)


def result_already(plan):
    return any(p[1]=='already' for p in plan)


def merge_provenance(home: Path, instance: Path, z):
    """Adopt the translator's per-string source labels; they only apply where text and English match."""
    try:incoming=json.loads(z.read('provenance.json').decode('utf-8'))
    except (KeyError,ValueError):return
    store=jobs.Provenance(home,instance);fields=('text','en','origin','evidence','issue','unified_from','model')
    for key,e in (incoming.items() if isinstance(incoming,dict) else ()):
        if isinstance(key,str) and isinstance(e,dict) and isinstance(e.get('origin'),str) and isinstance(e.get('text'),str):
            store.entries[key]={f:e.get(f) for f in fields if e.get(f) is None or isinstance(e.get(f),str)}
    store.path.parent.mkdir(parents=True,exist_ok=True);jobs.write_json(store.path,store.entries)


def applied_patches(home: Path) -> dict:
    """Which translation (patch SHA-256) each instance last received, so the catalog can offer updates."""
    try:return json.loads((home/'applied_patches.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def record_applied(home: Path, instance: Path, manifest, digest):
    data=applied_patches(home);pack=manifest.get('modpack') or {}
    data[str(Path(instance).resolve()).casefold()]=dict(sha256=digest,projectID=pack.get('projectID',0),fileID=pack.get('fileID',0),
                                                      version=pack.get('version',''),applied=datetime.now().isoformat(timespec='seconds'))
    jobs.write_json(home/'applied_patches.json',data)


def catalog_url(url: str) -> str:
    p=urlparse(url)
    if p.scheme!='https' or p.netloc!='raw.githubusercontent.com' or not p.path.startswith('/'+REPOSITORY+'/translations/'):
        raise ValueError('目錄網址不屬於指定的 GitHub 專案。')
    return url


def patch_url(url: str) -> str:
    """Patches live on this project's translations branch or its GitHub Releases, nowhere else."""
    try:return catalog_url(url)
    except ValueError:return release_url(url)


def fetch_catalog(session=None):
    """Published translations; an empty list when none have been published yet."""
    import requests
    session=session or requests.Session()
    r=session.get(catalog_url(CATALOG_URL),timeout=(10,25),headers={'User-Agent':f'MCTranslator/{VERSION}'})
    if r.status_code==404:return []
    r.raise_for_status()
    packs=[]
    for x in (r.json() or {}).get('packs',[]):
        try:
            patch_url(x['url'])
            if not re.fullmatch('[0-9a-f]{64}',x['sha256']) or not 0<int(x['size'])<=MAX_PATCH_SIZE:continue
            packs.append(dict(name=str(x['name']),projectID=int(x.get('projectID') or 0),fileID=int(x.get('fileID') or 0),
                              version=str(x.get('version') or ''),gameVersion=str(x.get('gameVersion') or ''),
                              translator=str(x.get('translator') or ''),updated=str(x.get('updated') or ''),
                              modpackDate=str(x.get('modpackDate') or '')[:10],revision=max(1,int(x.get('revision') or 1)),
                              notes=str(x.get('notes') or '')[:600],recommendedRam=ram_mb(x.get('recommendedRam')),url=x['url'],sha256=x['sha256'],size=int(x['size']),
                              addedMods=[dict(name=str(m['name'])[:120],size=int(m['size'])) for m in (x.get('addedMods') or [])[:MAX_ADDED_MODS]
                                         if isinstance(m,dict) and m.get('name') and 0<int(m.get('size') or 0)<=MAX_MOD_SIZE]))
        except (KeyError,TypeError,ValueError):continue
    return packs


def match_catalog(packs, instances, applied=None):
    """One row per modpack: the translation for the version the user has installed, else the newest.

    The catalog keeps every published version, so players on an older modpack version still get the
    translation made for it.
    """
    groups={}
    for pack in packs:groups.setdefault(pack['projectID'] or pack['name'].casefold(),[]).append(pack)
    rows=[]
    for versions in groups.values():
        # Newest modpack version first: CurseForge numbers each upload higher than the last, while the
        # date only says when its translation was last published (an old version can be re-published).
        versions.sort(key=lambda p:(p['fileID'],p['updated']),reverse=True)
        mine=[x for x in instances if versions[0]['projectID'] and x['projectID']==versions[0]['projectID']]
        exact=[(p,x) for p in versions for x in mine if x['fileID']==p['fileID']]
        pack,status=(exact[0][0],'exact') if exact else (versions[0],'other_version' if mine else 'not_installed')
        targets=[x for p,x in exact if p is pack] or mine
        if status=='exact':
            # Already applied here? Then it is either current or the published translation was updated.
            done=[(applied or {}).get(str(Path(x['path']).resolve()).casefold()) for x in targets]
            done=[d for d in done if d and d.get('fileID')==pack['fileID']]
            if done:status='applied' if any(d['sha256']==pack['sha256'] for d in done) else 'update'
        # Older catalog entries lack the memory figure; the installed modpack's own manifest has it.
        ram=pack.get('recommendedRam') or next((r for r in (instance_identity(Path(x['path']))['recommendedRam'] for x in targets) if r),0)
        rows.append(dict(pack,status=status,instances=targets,versions=len(versions),latest=pack is versions[0],
                         newest_version=versions[0]['version'],recommendedRam=ram))
    rows.sort(key=lambda r:({'update':0,'exact':1,'applied':2,'other_version':3}.get(r['status'],4),r['name'].casefold()))
    return rows


def modpack_files_ready(instance: Path, manifest):
    """(present, needed): files this translation belongs to that CurseForge has put in place.

    A mod file counts once it is there at its full size; a file the translation replaces counts
    once it exists. Sizes are compared instead of hashes so that checking every few seconds is cheap.
    """
    present=needed=0;added={'mods/'+m['fileName'].casefold() for m in manifest.get('added_mods') or []}
    for item in manifest['files']:
        if item.get('pack'):
            # The translation resource pack is made here; what must be in place are the mods it translates.
            for jar,size in sorted((item.get('sizes') or {}).items()):
                if jar.casefold() in added:continue
                needed+=1
                try:present+=contained(instance,jar).stat().st_size==size
                except (OSError,ValueError):pass
            continue
        if not item['archive'] and item.get('before') is None:continue  # a file the translation adds
        if item['file'].casefold() in added:continue  # a mod the translator added; it is installed afterwards
        needed+=1
        try:
            size=contained(instance,item['file']).stat().st_size
            if not item['archive'] or size==item.get('size'):present+=1
        except (OSError,ValueError):pass
    return present,needed


def wait_for_modpack(pack, manifest, notify=lambda *_:None, cancelled=lambda:False, find=None,
                     timeout=2700, settle=180, calm=15, clock=time.monotonic, pause=time.sleep) -> Path:
    """Wait while CurseForge installs the modpack a translation was made for; returns its folder.

    The modpack is ready when every file the translation belongs to is in place and nothing has
    changed for `calm` seconds. When the install stops changing for `settle` seconds before that
    (CurseForge finished but some mods differ), the folder is returned as it is: the translation
    is then applied to what matches and the rest is reported as skipped.
    """
    find=find or jobs.curseforge_instances;start=clock();changed=start;seen=None
    while True:
        if cancelled():raise InterruptedError('已停止等待。CurseForge 可以繼續安裝整合包；裝好後回到這一頁按「安裝翻譯」即可。')
        found=[x for x in find() if x['projectID']==pack['projectID'] and x['fileID']==pack['fileID']]
        if found:
            instance=Path(found[0]['path']);present,needed=modpack_files_ready(instance,manifest)
            try:state=(present,sum(1 for _ in (instance/'mods').iterdir()))
            except OSError:state=(present,0)
            if state!=seen:seen=state;changed=clock()
            quiet=clock()-changed
            notify(int(100*present/max(1,needed)),'等待 CurseForge 安裝整合包',f'已就緒 {present:,}／{needed:,} 個要翻譯的檔案')
            if (present==needed and quiet>=calm) or (state[1] and quiet>=settle):return instance
        else:
            notify(0,'等待 CurseForge 安裝整合包','請在 CurseForge 的視窗確認安裝，這裡會自動接著做')
        if clock()-start>timeout:
            raise ValueError('等了很久，CurseForge 還沒有裝好這個整合包。請看一下 CurseForge 的安裝進度；裝好後回到這一頁按「安裝翻譯」即可。')
        pause(3)


def curseforge_install_url(pack) -> str:
    return f'curseforge://install?addonId={int(pack["projectID"])}&fileId={int(pack["fileID"])}'


def download_patch(pack, home: Path, progress=lambda _:None, session=None) -> Path:
    import requests
    session=session or requests.Session()
    folder=home/'downloads';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{pack["sha256"]}.zip'
    if path.exists() and file_hash(path)==pack['sha256']:return path
    part=folder/(uuid.uuid4().hex+'.partial');h=hashlib.sha256();received=0
    try:
        with session.get(patch_url(pack['url']),stream=True,timeout=(15,60)) as response:
            response.raise_for_status()
            with part.open('xb') as f:
                for block in response.iter_content(1024*1024):
                    received+=len(block)
                    if received>pack['size']:raise ValueError('下載大小超過目錄資料，已停止。')
                    h.update(block);f.write(block);progress(int(received*100/max(1,pack['size'])))
        if received!=pack['size'] or h.hexdigest()!=pack['sha256']:raise ValueError('翻譯補丁校驗失敗，未套用。')
        part.replace(path)
        return path
    finally:
        part.unlink(missing_ok=True)
