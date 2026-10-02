"""Publish an exported translation patch to the in-app 「已翻譯整合包」 catalog.

The catalog is the `translations` branch of this repository:
    index.json                         list shown in the app
    packs/<projectID>/<file>.zip       the patches themselves

Each modpack version is a separate entry, so players on an older version keep the matching
translation. Publishing the same modpack version again replaces that entry.

A modpack without a CurseForge project (copied in from another launcher) is shared whole instead
(--full): it is packed with full_pack.build, moved into the owner's Google Drive folder (Google Drive
for desktop uploads it), downloaded once anonymously to prove players can get it, and only then listed.

Usage (publishing is public; only run it when the owner asked to publish this patch):
    python scripts/publish_translation.py <patch.zip> --translator 名稱 [--notes 說明] [--ram MB] [--dry-run]
    python scripts/publish_translation.py <modpack folder> --home <MCTranslatorData> --translator 名稱
    python scripts/publish_translation.py <modpack folder> --full --drive-folder "G:\\我的雲端硬碟\\Minecraft_mod" --translator 名稱
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mc_zh_tw_translator import full_pack  # noqa: E402
from mc_zh_tw_translator.patches import export_patch, read_patch  # noqa: E402
from mc_zh_tw_translator.updater import REPOSITORY  # noqa: E402

BRANCH = 'translations'
RAW = f'https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/'
ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8').stdout


def update_catalog(entry, same, message, files=(), dry_run=False):
    """Replace the catalog entries `same` picks with `entry` (revision counted on) and push.

    `files` are (source, relative path) pairs added to the branch; files of replaced entries are removed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)/'catalog'
        exists = subprocess.run(['git', 'ls-remote', '--exit-code', '--heads', 'origin', BRANCH], cwd=ROOT, capture_output=True).returncode == 0
        if exists:
            git('fetch', 'origin', BRANCH, cwd=ROOT)
            git('worktree', 'add', '--detach', str(work), f'origin/{BRANCH}', cwd=ROOT)
        else:
            git('worktree', 'add', '--detach', str(work), cwd=ROOT)
            git('checkout', '--orphan', BRANCH, cwd=work)
            git('rm', '-rf', '--quiet', '.', cwd=work)
        try:
            index_file = work/'index.json'
            index = json.loads(index_file.read_text(encoding='utf-8')) if index_file.exists() else {'packs': []}
            replaced = [p for p in index['packs'] if same(p)]
            index['packs'] = [p for p in index['packs'] if p not in replaced]
            for old in replaced:
                url = old.get('url') or ''
                if url.startswith(RAW) and (work/url[len(RAW):]).exists():
                    git('rm', '--quiet', url[len(RAW):], cwd=work)
            # revision counts re-publishes of the same modpack version.
            entry = dict(entry, revision=max([int(p.get('revision') or 1) for p in replaced] or [0])+1)
            if not entry.get('notes') and replaced:  # a re-publish without new notes keeps the card's introduction
                entry['notes'] = replaced[-1].get('notes', '')
            index['packs'].append(entry)
            index['packs'].sort(key=lambda p: (p['name'].casefold(), p['updated']))
            for source, relative in files:
                (work/relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, work/relative)
                git('add', relative, cwd=work)
            index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            git('add', 'index.json', cwd=work)
            action = '更新' if replaced else '新增'
            git('commit', '--quiet', '-m', f'{action}{message}', cwd=work)
            if dry_run:
                print(json.dumps(entry, ensure_ascii=False, indent=2))
                print('dry-run：未推送。')
            else:
                git('push', 'origin', f'HEAD:refs/heads/{BRANCH}', cwd=work)
                print(f'已{action}：{message}')
        finally:
            git('worktree', 'remove', '--force', str(work), cwd=ROOT)
            if not exists:  # the orphan checkout made a local branch; the remote one is the catalog
                subprocess.run(['git', 'branch', '-D', BRANCH], cwd=ROOT, capture_output=True)


def drive_file_id(name: str, size: int):
    """The Google Drive ID of an uploaded file, from Google Drive for desktop's own records; None until uploaded."""
    base = Path(os.environ['LOCALAPPDATA'])/'Google/DriveFS'
    for account in base.glob('*/metadata_sqlite_db'):
        with tempfile.TemporaryDirectory() as tmp:
            # Copied (with its write-ahead log) so the running Drive app is never locked or changed.
            for suffix in ('', '-wal', '-shm'):
                src = Path(str(account)+suffix)
                if src.exists():
                    shutil.copyfile(src, Path(tmp)/('db'+suffix))
            db = sqlite3.connect(Path(tmp)/'db')
            try:
                rows = db.execute('select id, file_size from items where local_title=? and is_folder=0 and trashed=0',
                                  (name,)).fetchall()
            finally:
                db.close()
        for file_id, file_size in rows:
            if file_size == size and full_pack.DRIVE_ID.fullmatch(file_id) and not file_id.startswith('local'):
                return file_id
    return None


def publish_full(args):
    instance = args.patch.resolve()
    folder = args.drive_folder
    if not folder or not folder.is_dir():
        sys.exit('請用 --drive-folder 指定 Google 雲端硬碟電腦版裡要放整合包的資料夾。')
    with tempfile.TemporaryDirectory(dir=args.work) as tmp:
        out = Path(tmp)/'pack.zip'
        shown = [0.0]
        def notify(value, title, detail=''):
            if time.monotonic()-shown[0] >= 10 or value >= 100:
                shown[0] = time.monotonic()
                print(f'{value:3d}% {title} {detail}', flush=True)
        manifest = full_pack.build(instance, out, notify=notify)
        size = out.stat().st_size
        digest = full_pack.file_hash(out)
        linked = sum(e['source'] == 'curseforge' for e in manifest['files'])
        print(f"檔案 {len(manifest['files']):,} 個（{linked:,} 個模組由 CurseForge 下載），壓縮檔 {size/1024**3:.2f} GB")
        name = f"{full_pack.folder_name(manifest['name'])}-{manifest.get('version') or date.today().isoformat()}-繁中-{digest[:8]}.zip"
        target = folder/name
        if not target.exists():
            shutil.copyfile(out, target)
    print('已放進雲端資料夾：', target, flush=True)
    start = time.monotonic()
    while not (file_id := drive_file_id(name, size)):
        if time.monotonic()-start > args.upload_wait:
            sys.exit('等太久還沒上傳完成，請確認 Google 雲端硬碟電腦版正在同步；上傳完成後重新執行同一個指令即可。')
        print('等待 Google 雲端硬碟上傳…', flush=True)
        time.sleep(30)
    print('雲端檔案 ID：', file_id, flush=True)
    entry = dict(kind='full', name=manifest['name'], packId=full_pack.pack_id(manifest['name']), version=manifest.get('version') or '', gameVersion=manifest.get('gameVersion') or '',
                 loader=manifest['loader'].get('name', ''), translator=args.translator, updated=date.today().isoformat(),
                 notes=args.notes, recommendedRam=args.ram or int(manifest.get('recommendedRam') or 0),
                 driveId=file_id, sha256=digest, size=size, totalSize=manifest['totalSize'], files=len(manifest['files']))
    # Players download anonymously; prove that works (and that the bytes are the same) before listing it.
    with tempfile.TemporaryDirectory(dir=args.work) as tmp:
        for attempt in range(20):
            try:
                full_pack.download(entry, Path(tmp), lambda v: None)
                break
            except ValueError as exc:
                if attempt == 19 or '不讓下載' not in str(exc):
                    sys.exit('匿名下載失敗：'+str(exc)+'\n請在雲端硬碟網頁版把資料夾設成「知道連結的任何人都可以檢視」後重新執行。')
                print('Google 還沒開放下載，稍後再試…', flush=True)
                time.sleep(60)
    print('匿名下載並核對校驗碼成功。', flush=True)
    # A new version of the same modpack replaces its card; players then update in place.
    update_catalog(entry, lambda p: p.get('kind') == 'full' and (p.get('packId') or full_pack.pack_id(p['name'])) == entry['packId'],
                   f"整合包：{entry['name']} {entry['version']}", dry_run=args.dry_run)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('patch', type=Path, help='exported patch zip, or a modpack folder to export first')
    parser.add_argument('--home', type=Path, help='MCTranslatorData folder holding the backups (with a modpack folder)')
    parser.add_argument('--translator', required=True)
    parser.add_argument('--notes', default='', help='中文介紹，顯示在卡片上')
    parser.add_argument('--ram', type=int, default=0, help="整合包作者建議的記憶體 MB（預設讀補丁記下的 manifest.json recommendedRam）")
    parser.add_argument('--full', action='store_true', help='沒有 CurseForge 編號的整合包：整包上傳到雲端')
    parser.add_argument('--drive-folder', type=Path, help='--full：Google 雲端硬碟電腦版裡的資料夾')
    parser.add_argument('--work', type=Path, help='--full：打包用的暫存資料夾（預設系統暫存）')
    parser.add_argument('--upload-wait', type=int, default=6*3600, help='--full：等待上傳完成的秒數')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.full:
        publish_full(args)
        return
    if args.patch.is_dir():
        if not args.home:sys.exit('給整合包資料夾時，請用 --home 指定 MCTranslatorData 資料夾（含套用紀錄）。')
        exported = export_patch(args.patch, args.home)
        for s in exported['skipped']:print('略過：', s['file'], s['reason'])
        args.patch = Path(exported['path'])
        print('已匯出：', args.patch)
    z, manifest = read_patch(args.patch)
    z.close()
    pack = manifest['modpack']
    # Mods the owner added through CurseForge: named in the catalog, downloaded by each player from CurseForge.
    for mod in manifest['added_mods']:print('加裝的模組：', mod['name'], mod['fileName'], f"{mod['size']:,} bytes", '' if mod['url'] else '（作者只開放由 CurseForge 安裝，對方需自行加裝）')
    for left in manifest.get('left_out_mods') or []:print('不分享的模組：', left.get('name'), left.get('reason'))
    if not pack.get('projectID') or not pack.get('fileID'):
        sys.exit('這個補丁不是從 CurseForge 整合包匯出的，無法對應版本；整個整合包分享請改用 --full。')
    data = args.patch.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    relative = f"packs/{pack['projectID']}/{pack['fileID']}-{digest[:8]}.zip"
    # version/modpackDate describe the modpack itself; revision counts re-publishes of its translation.
    entry = dict(name=pack['name'], projectID=pack['projectID'], fileID=pack['fileID'],
                 version=pack.get('version', ''), modpackDate=pack.get('date', ''),
                 gameVersion=pack.get('gameVersion', ''),
                 translator=args.translator, updated=date.today().isoformat(), notes=args.notes,
                 recommendedRam=args.ram or int(pack.get('recommendedRam') or 0),
                 addedMods=[dict(name=m['name'], size=m['size']) for m in manifest['added_mods']],
                 url=RAW+relative, sha256=digest, size=len(data))
    update_catalog(entry, lambda p: p.get('projectID') == pack['projectID'] and p.get('fileID') == pack['fileID'],
                   f"已翻譯整合包：{pack['name']} {pack.get('version', '')}", [(args.patch, relative)], args.dry_run)


if __name__ == '__main__':
    main()
