"""Translation patches: share a finished modpack translation and apply it to someone else's copy.

A patch holds translation text only, never mod code or whole mod jars:
- for a mod jar or resource-pack zip, just the language/book entries that were changed or added,
  together with the SHA-256 of the untranslated archive they belong to;
- for a loose file (KubeJS assets, quests, config), the translated file and the SHA-256 of the
  file it replaced (or null when it was new).

Applying only touches files whose current content is exactly the untranslated version the patch
was made from, so a different mod version is skipped instead of being overwritten. Every write
goes through apply_reviewed (backup, hash checks, rollback), so it can be restored like any batch.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
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
TRANSLATED = re.compile(r'(?:^|/)lang/zh_tw\.(?:json|lang)$|/zh_tw/[^/].*\.(?:json|txt|md|snbt)$')
MAX_PATCH_SIZE = 200*1024*1024
MAX_ENTRY_SIZE = 64*1024*1024       # one translated file, unpacked
MAX_UNPACKED_SIZE = 1024*1024*1024  # the whole patch, unpacked
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
    identity=dict(name=instance.name,projectID=0,fileID=0,gameVersion='',version='',date='')
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
    except (OSError,ValueError,TypeError,AttributeError):pass
    return identity


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
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    folder=home/'output'/instance.name/'分享';folder.mkdir(parents=True,exist_ok=True)
    safe=re.sub(r'[\\/:*?"<>|]+','_',identity['name']).strip() or 'modpack'
    out=folder/f'{safe}{"-"+identity["version"] if identity["version"] else ""}-繁中翻譯-{stamp}.zip'
    manifest=dict(format=PATCH_FORMAT,app_version=VERSION,created=datetime.now().isoformat(timespec='seconds'),
                  modpack=identity,files=[])
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
    return dict(path=str(out),files=len(manifest['files']),skipped=manifest['skipped'],modpack=identity,sha256=file_hash(out),size=out.stat().st_size)


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
            if archive:
                if not item.get('before') or not item.get('entries'):raise ValueError('補丁項目不完整：'+file)
                for name in item['entries']:
                    clean_path(name)
                    if not allowed_entry(name):raise ValueError(f'補丁包含不允許的內容：{file} / {name}')
                    if f'payload/{file}/{name}' not in names:raise ValueError(f'補丁缺少內容：{file} / {name}')
            elif f'payload/{file}' not in names or not item.get('after'):raise ValueError('補丁缺少內容：'+file)
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
    plan=[]
    for item in manifest['files']:
        path=contained(instance,item['file'])
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


def apply_patch(instance: Path, patch: Path, home: Path, notify=lambda *_:None, set_language=False) -> dict:
    """Apply a translation patch to an instance; only files matching the patch's original version change."""
    instance=Path(instance).resolve()
    if not jobs.is_instance(instance):raise ValueError('找不到模組包資料夾（需要有 mods、config 或 kubejs）。')
    z,manifest=read_patch(patch)
    staged=home/'tmp'/('patch-'+uuid.uuid4().hex[:8])
    try:
        jobs.ensure_game_closed(instance)
        plan=plan_patch(instance,z,manifest)
        staged.mkdir(parents=True)
        records=[];applied=[]
        todo=[p for p in plan if p[1]=='apply']
        for i,(item,_,target,_) in enumerate(todo):
            notify(int(70*i/max(1,len(todo))),'準備套用翻譯',item['file'])
            relative=target.relative_to(instance).as_posix()
            dst=contained(staged,relative);dst.parent.mkdir(parents=True,exist_ok=True)
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
        if set_language:
            record=jobs.set_language_record(instance,staged)
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
                    language_set=bool(set_language))
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
                              notes=str(x.get('notes') or ''),url=x['url'],sha256=x['sha256'],size=int(x['size'])))
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
        versions.sort(key=lambda p:(p['updated'],p['fileID']),reverse=True)
        mine=[x for x in instances if versions[0]['projectID'] and x['projectID']==versions[0]['projectID']]
        exact=[(p,x) for p in versions for x in mine if x['fileID']==p['fileID']]
        pack,status=(exact[0][0],'exact') if exact else (versions[0],'other_version' if mine else 'not_installed')
        targets=[x for p,x in exact if p is pack] or mine
        if status=='exact':
            # Already applied here? Then it is either current or the published translation was updated.
            done=[(applied or {}).get(str(Path(x['path']).resolve()).casefold()) for x in targets]
            done=[d for d in done if d and d.get('fileID')==pack['fileID']]
            if done:status='applied' if any(d['sha256']==pack['sha256'] for d in done) else 'update'
        rows.append(dict(pack,status=status,instances=targets,versions=len(versions),latest=pack is versions[0],
                         newest_version=versions[0]['version']))
    rows.sort(key=lambda r:({'update':0,'exact':1,'applied':2,'other_version':3}.get(r['status'],4),r['name'].casefold()))
    return rows


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
