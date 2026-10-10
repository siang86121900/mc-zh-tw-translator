"""Opt-in GitHub Release updates. Never download or install during a check."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

VERSION='0.36.1'
REPOSITORY='siang86121900/mc-zh-tw-translator'
ASSET_NAME='MCTranslator.exe'


def version_tuple(value):
    m=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',value or '')
    if not m:raise ValueError('版本格式不支援：'+str(value))
    return tuple(map(int,m.groups()))


def check_without_query_service(session):
    """The newest release found by following the public release page, for when GitHub's query
    service has used up its hourly allowance. The download is verified the same way."""
    headers={'User-Agent':f'MCTranslator/{VERSION}'};base=f'https://github.com/{REPOSITORY}/releases'
    response=session.get(base+'/latest',timeout=(10,25),headers=headers,allow_redirects=False)
    m=re.search(r'/releases/tag/(v\d+\.\d+\.\d+)$',response.headers.get('Location') or '')
    if not m:return dict(status='unavailable',message='目前還沒有可下載的公開更新；請稍後再按「檢查更新」。')
    latest=m[1]
    if version_tuple(latest)<=version_tuple(VERSION):
        return dict(status='current',version=VERSION,message='目前已是最新版本。')
    url=f'{base}/download/{latest}/{ASSET_NAME}'
    size=session.head(url,timeout=(10,25),headers=headers,allow_redirects=True)
    size.raise_for_status()
    notes=session.get(f'https://raw.githubusercontent.com/{REPOSITORY}/{latest}/docs/release-notes/{latest}.md',timeout=(10,25),headers=headers)
    return dict(status='available',version=latest,notes=notes.text if notes.status_code==200 and notes.text.strip() else '此版本未提供更新說明。',
                url=url,size=int(size.headers['Content-Length']),sha256=None,checksum_url=f'{base}/download/{latest}/SHA256SUMS.txt')


def check_update(session=None):
    session=session or requests.Session()
    response=session.get(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',timeout=(10,25),
                         headers={'User-Agent':f'MCTranslator/{VERSION}'})
    if response.status_code in (403,429):return check_without_query_service(session)
    if response.status_code==404:
        return dict(status='unavailable',message='目前還沒有可下載的公開更新；請稍後再按「檢查更新」。')
    response.raise_for_status()
    release=response.json()
    latest=release['tag_name']
    if version_tuple(latest)<=version_tuple(VERSION):
        return dict(status='current',version=VERSION,message='目前已是最新版本。')
    asset=next((a for a in release.get('assets',[]) if a['name']==ASSET_NAME),None)
    checksum=next((a for a in release.get('assets',[]) if a['name']=='SHA256SUMS.txt'),None)
    if not asset:raise ValueError('新版本尚未附上 Windows EXE，請稍後再檢查。')
    digest=asset.get('digest','') or ''
    if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest) and not checksum:
        raise ValueError('發布版本缺少 SHA-256 校驗資訊，無法安全更新。')
    return dict(status='available',version=latest,notes=release.get('body') or '此版本未提供更新說明。',
                url=asset['browser_download_url'],size=asset['size'],
                sha256=digest.split(':',1)[1].lower() if digest.startswith('sha256:') else None,
                checksum_url=checksum['browser_download_url'] if checksum else None)


def release_url(url):
    p=urlparse(url)
    if p.scheme!='https' or p.netloc!='github.com' or not p.path.startswith('/'+REPOSITORY+'/releases/download/'):
        raise ValueError('更新網址不屬於指定的 GitHub 專案。')
    return url


def download_update(info, home, progress, session=None):
    session=session or requests.Session()
    expected=info.get('sha256')
    if not expected:
        r=session.get(release_url(info['checksum_url']),timeout=(10,30));r.raise_for_status()
        for line in r.text.splitlines():
            m=re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?MCTranslator\.exe',line.strip())
            if m:expected=m[1].lower();break
    if not expected or not re.fullmatch('[a-f0-9]{64}',expected):raise ValueError('無法取得有效的 SHA-256 校驗碼。')
    if not 0<int(info['size'])<500*1024*1024:raise ValueError('更新檔案大小不在允許範圍內。')
    folder=home/'updates'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    path=folder/ASSET_NAME
    h=hashlib.sha256();received=0
    try:
        with session.get(release_url(info['url']),stream=True,timeout=(15,60)) as response:
            response.raise_for_status()
            with path.open('xb') as f:
                for block in response.iter_content(1024*1024):
                    received+=len(block)
                    if received>info['size']:raise ValueError('下載大小超過發布資料，已停止。')
                    h.update(block);f.write(block)
                    progress(int(received*100/max(1,info['size'])))
        if received!=info['size'] or h.hexdigest()!=expected:raise ValueError('更新檔校驗失敗，原程式不會被替換。')
        with path.open('rb') as f:
            if f.read(2)!=b'MZ':raise ValueError('更新檔不是有效的 Windows 執行檔。')
        return path,expected
    except Exception:
        path.unlink(missing_ok=True)
        raise


def launch_update(downloaded, expected, home):
    if not getattr(sys,'frozen',False):raise ValueError('原始碼執行模式不能自我更新，請使用 EXE。')
    ticket=downloaded.parent/'update.json'
    ticket.write_text(json.dumps(dict(target=str(Path(sys.executable).resolve()),sha256=expected,
                                      pid=os.getpid(),home=str(home)),ensure_ascii=False),encoding='utf-8')
    subprocess.Popen([str(downloaded),'--apply-update',str(ticket)],
                     creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS,close_fds=True)


def clean_leftovers(home, executable=None):
    """Remove what earlier updates left behind: downloaded installers and all but the newest old EXE.

    The newest old EXE stays so the last update can be undone by hand. Files still in use (the
    update helper may be finishing) are left for the next start.
    """
    try:
        for folder in (Path(home)/'updates').iterdir():
            if folder.is_dir() and time.time()-folder.stat().st_mtime>600:shutil.rmtree(folder,ignore_errors=True)
    except OSError:pass
    if executable is None:
        if not getattr(sys,'frozen',False):return  # running from source: there is no EXE to tidy
        executable=sys.executable
    executable=Path(executable)
    try:
        old=sorted(executable.parent.glob(executable.name+'.previous-*'),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in old[1:]+list(executable.parent.glob(executable.name+'.failed-*')):
            try:path.unlink()
            except OSError:pass
    except OSError:pass


def apply_update(ticket_path):
    """Executed by the downloaded EXE after explicit confirmation in the old app."""
    import ctypes
    ticket_path=Path(ticket_path).resolve()
    ticket=json.loads(ticket_path.read_text(encoding='utf-8'))
    source=Path(sys.executable).resolve();target=Path(ticket['target']).resolve();home=Path(ticket['home']).resolve()
    if source==target or source.parent!=ticket_path.parent or not source.is_relative_to(home/'updates'):
        raise ValueError('更新暫存路徑不符。')
    if target.suffix.lower()!='.exe' or not target.exists():raise ValueError('原程式不存在。')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=ticket['sha256']:raise ValueError('執行前更新檔校驗失敗。')
    k=ctypes.windll.kernel32
    k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p
    k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];k.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=k.OpenProcess(0x00100000,False,int(ticket['pid']))
    if handle:
        try:
            if k.WaitForSingleObject(handle,120000)!=0:raise RuntimeError('原程式未關閉，更新已停止。')
        finally:k.CloseHandle(handle)
    time.sleep(1)
    previous=target.with_name(target.name+'.previous-'+uuid.uuid4().hex[:8])
    temp=target.with_name(target.name+'.update-'+uuid.uuid4().hex[:8])
    try:
        shutil.copy2(source,temp)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=ticket['sha256']:raise ValueError('寫入後校驗失敗。')
        # One-file EXEs have a bootloader parent that can release its file a moment later.
        for attempt in range(30):
            try:
                target.replace(previous)
                break
            except PermissionError:
                if attempt==29:raise
                time.sleep(.5)
        try:temp.replace(target)
        except Exception:
            previous.replace(target);raise
        ticket.update(status='installed',previous=str(previous))
        ticket_path.write_text(json.dumps(ticket,ensure_ascii=False,indent=2),encoding='utf-8')
        # Tell Explorer this single EXE changed; do not delete the user's icon cache.
        ctypes.windll.shell32.SHChangeNotify(0x2000,0x0005,ctypes.c_wchar_p(str(target)),None)
        subprocess.Popen([str(target)],creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
    except Exception as exc:
        if previous.exists():
            try:
                if target.exists():target.replace(target.with_name(target.name+'.failed-'+uuid.uuid4().hex[:8]))
                previous.replace(target)
            except OSError:pass
        ticket.update(status='failed',error=str(exc))
        ticket_path.write_text(json.dumps(ticket,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    finally:temp.unlink(missing_ok=True)
