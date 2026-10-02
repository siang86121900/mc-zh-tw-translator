"""Back up and apply an explicitly reviewed, hash-bound translation batch.

Content review and format/JAR verification must precede this operation. This
module is the file deployment boundary, not a translation or review engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path, PureWindowsPath


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def contained(root: Path, relative: str) -> Path:
    win = PureWindowsPath(relative)
    parts = relative.replace('\\', '/').split('/')
    if not relative or win.drive or win.root or any(p in ('', '.', '..') or ':' in p for p in parts):
        raise ValueError(f'Unsafe relative path: {relative}')
    path = root.joinpath(*parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes root: {relative}')
    current = root
    for part in parts:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError(f'Linked deployment path: {relative}')
    return path


# A launcher that watches the mods folder or an antivirus scan opens a file the moment it is written,
# and Windows then refuses to rename or delete it for a moment. Waiting and trying again is the remedy.
WAITS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 3, 3, 3, 3, 5, 5, 5)
WORK_FILE = re.compile(r'\.translation-[a-z0-9_]{8}')


def when_free(action, name, on_wait=None):
    """Run a file operation, waiting while another program briefly holds the file."""
    for wait in WAITS:
        try:
            return action()
        except PermissionError:
            if on_wait:
                on_wait(name)
            time.sleep(wait)
    return action()


def remove_work_file(tmp: Path) -> None:
    try:
        when_free(lambda: tmp.unlink(missing_ok=True), tmp.name)
    except OSError:
        pass  # still held; clear_work_files removes it before the next batch is written


def clear_work_files(folder: Path) -> None:
    """Remove working copies an earlier write could not delete; nothing else in the folder is touched."""
    try:
        found = [p for p in folder.iterdir() if WORK_FILE.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    except OSError:
        return
    for tmp in found:
        try:
            tmp.unlink()
        except OSError:
            pass


def atomic_copy(source: Path, destination: Path, on_wait=None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.translation-', delete=False) as f:
        tmp = Path(f.name)
    try:
        when_free(lambda: shutil.copy2(source, tmp), destination.name, on_wait)
        if when_free(lambda: file_hash(tmp), destination.name, on_wait) != file_hash(source):
            raise RuntimeError(f'Copy verification failed: {source}')
        try:
            when_free(lambda: os.replace(tmp, destination), destination.name, on_wait)
        except PermissionError as exc:
            # Name the file the player knows, not the working copy.
            raise PermissionError(exc.errno, exc.strerror, str(destination), getattr(exc, 'winerror', None)) from exc
    finally:
        remove_work_file(tmp)


def apply_reviewed(instance: Path, staged: Path, records: list[dict], output_root: Path, on_wait=None) -> Path:
    """Apply exact reviewed files; all originals are backed up before any write.

    Each record requires file, before (SHA-256 or null), after (SHA-256, or null
    to remove a file that is backed up first), reviewed=True and verified=True.
    The caller supplies actual review and verification evidence and must check
    game state before deploying JARs.
    """
    instance, staged, output_root = (p.resolve() for p in (instance, staged, output_root))
    if not instance.is_dir() or not staged.is_dir() or not records:
        raise ValueError('Existing instance, staging directory and nonempty manifest required')
    for other in (staged, output_root):
        if instance.is_relative_to(other) or other.is_relative_to(instance):
            raise ValueError('Instance must not overlap staging or backup root')
    paths, seen = [], set()
    for row in records:
        if row.get('reviewed') is not True or row.get('verified') is not True:
            raise ValueError('Unreviewed or unverified file in deployment manifest')
        target = contained(instance, row['file'])
        source = contained(staged, row['file'])
        key = str(target).casefold()
        if key in seen:
            raise ValueError(f'同一個檔案被排了兩次寫入，已停止，沒有修改任何檔案：{row["file"]}')
        seen.add(key)
        if row.get('after') is None:
            if row.get('before') is None:
                raise ValueError(f'要移除的檔案沒有校驗碼，已停止：{row["file"]}')
        elif not source.is_file() or file_hash(source) != row['after']:
            raise ValueError(f'準備寫入的內容在檢查後被改動，已停止：{row["file"]}')
        if 'before' not in row or file_hash(target) != row['before']:
            raise ValueError(f'整合包裡的檔案在翻譯後被改動（可能是遊戲或啟動器更新），已停止，請重新翻譯：{row["file"]}')
        paths.append((row, source, target))

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + uuid.uuid4().hex[:8]
    backup = output_root/instance.name/'原始備份'/stamp
    if backup.is_relative_to(staged) or staged.is_relative_to(backup):
        raise ValueError('Backup and staging paths must not overlap')
    backup.mkdir(parents=True, exist_ok=False)
    metadata = backup/'_備份紀錄'
    metadata.mkdir()
    journal = dict(instance=str(instance), staged=str(staged), status='backing_up', files=records,
                   new_files=[r['file'] for r in records if r['before'] is None])

    def save():
        (metadata/'manifest.json').write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    # Reserve metadata names to prevent collision with original user files.
    if any(r['file'].replace('\\','/').split('/')[0].casefold() == '_備份紀錄' for r in records):
        raise ValueError('Reserved backup metadata directory')
    for row, source, target in paths:
        if row['before'] is not None:
            saved = contained(backup, row['file'])
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
            if file_hash(saved) != row['before']:
                raise RuntimeError(f'備份檢查失敗，已停止，沒有修改任何檔案：{row["file"]}')
    journal['status'] = 'backed_up'
    save()
    for folder in {target.parent for _, _, target in paths}:
        clear_work_files(folder)
    applied = []
    try:
        for row, source, target in paths:
            if (row['after'] is not None and file_hash(source) != row['after']) or file_hash(target) != row['before']:
                raise RuntimeError(f'寫入途中檔案被其他程式改動，已還原本批修改：{row["file"]}')
            if row['after'] is None:
                when_free(target.unlink, target.name, on_wait)
            else:
                atomic_copy(source, target, on_wait)
            applied.append((row, target))
            if when_free(lambda: file_hash(target), target.name, on_wait) != row['after']:
                raise RuntimeError(f'寫入後檢查不符，已還原本批修改：{row["file"]}')
        journal['status'] = 'installed'
        save()
    except Exception as exc:
        failures = []
        for row, target in reversed(applied):
            try:
                if file_hash(target) != row['after']:
                    raise RuntimeError('Target changed again; retained for inspection')
                if row['before'] is None:
                    when_free(target.unlink, target.name)
                else:
                    atomic_copy(contained(backup, row['file']), target)
            except Exception as rollback_error:
                failures.append(dict(file=row['file'], error=str(rollback_error)))
        journal.update(status='rollback_incomplete' if failures else 'rolled_back', error=str(exc), rollback_errors=failures)
        save()
        raise
    return backup
