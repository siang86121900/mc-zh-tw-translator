"""Publish an exported translation patch to the in-app 「現成翻譯」 catalog.

The catalog is the `translations` branch of this repository:
    index.json                         list shown in the app
    packs/<projectID>/<file>.zip       the patches themselves

Each modpack version is a separate entry, so players on an older version keep the matching
translation. Publishing the same modpack version again replaces that entry.

Usage (publishing is public; only run it when the owner asked to publish this patch):
    python scripts/publish_translation.py <patch.zip> --translator 名稱 [--notes 說明] [--dry-run]
    python scripts/publish_translation.py <modpack folder> --home <MCTranslatorData> --translator 名稱
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mc_zh_tw_translator.patches import export_patch, read_patch  # noqa: E402
from mc_zh_tw_translator.updater import REPOSITORY  # noqa: E402

BRANCH = 'translations'
RAW = f'https://raw.githubusercontent.com/{REPOSITORY}/{BRANCH}/'


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8').stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('patch', type=Path, help='exported patch zip, or a modpack folder to export first')
    parser.add_argument('--home', type=Path, help='MCTranslatorData folder holding the backups (with a modpack folder)')
    parser.add_argument('--translator', required=True)
    parser.add_argument('--notes', default='')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.patch.is_dir():
        if not args.home:sys.exit('給整合包資料夾時，請用 --home 指定 MCTranslatorData 資料夾（含套用紀錄）。')
        exported = export_patch(args.patch, args.home)
        for s in exported['skipped']:print('略過：', s['file'], s['reason'])
        args.patch = Path(exported['path'])
        print('已匯出：', args.patch)
    z, manifest = read_patch(args.patch)
    z.close()
    pack = manifest['modpack']
    if not pack.get('projectID') or not pack.get('fileID'):
        sys.exit('這個補丁不是從 CurseForge 整合包匯出的，無法對應版本，請改用檔案分享。')
    data = args.patch.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    name = f"{pack['fileID']}-{digest[:8]}.zip"
    relative = f"packs/{pack['projectID']}/{name}"
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)/'catalog'
        exists = subprocess.run(['git', 'ls-remote', '--exit-code', '--heads', 'origin', BRANCH], cwd=root, capture_output=True).returncode == 0
        if exists:
            git('fetch', 'origin', BRANCH, cwd=root)
            git('worktree', 'add', '--detach', str(work), f'origin/{BRANCH}', cwd=root)
        else:
            git('worktree', 'add', '--detach', str(work), cwd=root)
            git('checkout', '--orphan', BRANCH, cwd=work)
            git('rm', '-rf', '--quiet', '.', cwd=work)
        try:
            index_file = work/'index.json'
            index = json.loads(index_file.read_text(encoding='utf-8')) if index_file.exists() else {'packs': []}
            replaced = [p for p in index['packs'] if p['projectID'] == pack['projectID'] and p['fileID'] == pack['fileID']]
            index['packs'] = [p for p in index['packs'] if p not in replaced]
            for old in replaced:
                old_file = work/old['url'][len(RAW):]
                if old['url'].startswith(RAW) and old_file.exists():
                    git('rm', '--quiet', old['url'][len(RAW):], cwd=work)
            # version/modpackDate describe the modpack itself; revision counts re-publishes of its translation.
            index['packs'].append(dict(name=pack['name'], projectID=pack['projectID'], fileID=pack['fileID'],
                                       version=pack.get('version', ''), modpackDate=pack.get('date', ''),
                                       revision=max([int(p.get('revision') or 1) for p in replaced] or [0])+1,
                                       gameVersion=pack.get('gameVersion', ''),
                                       translator=args.translator, updated=date.today().isoformat(), notes=args.notes,
                                       url=RAW+relative, sha256=digest, size=len(data)))
            index['packs'].sort(key=lambda p: (p['name'].casefold(), p['updated']))
            (work/relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.patch, work/relative)
            index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            git('add', 'index.json', relative, cwd=work)
            action = '更新' if replaced else '新增'
            git('commit', '--quiet', '-m', f"{action}現成翻譯：{pack['name']} {pack.get('version', '')}", cwd=work)
            if args.dry_run:
                print(json.dumps(index['packs'][-1], ensure_ascii=False, indent=2))
                print('dry-run：未推送。')
            else:
                git('push', 'origin', f'HEAD:refs/heads/{BRANCH}', cwd=work)
                print(f"已{action}：{pack['name']} {pack.get('version', '')}（{len(data):,} bytes）")
        finally:
            git('worktree', 'remove', '--force', str(work), cwd=root)
            if not exists:  # the orphan checkout made a local branch; the remote one is the catalog
                subprocess.run(['git', 'branch', '-D', BRANCH], cwd=root, capture_output=True)


if __name__ == '__main__':
    main()
