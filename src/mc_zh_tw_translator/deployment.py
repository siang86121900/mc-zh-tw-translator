"""Back up and apply an explicitly reviewed, hash-bound translation batch.

Content review and format/JAR verification must precede this operation. This
module is the file deployment boundary, not a translation or review engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
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


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.translation-', delete=False) as f:
        tmp = Path(f.name)
    try:
        shutil.copy2(source, tmp)
        if file_hash(tmp) != file_hash(source):
            raise RuntimeError(f'Copy verification failed: {source}')
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)


def apply_reviewed(instance: Path, staged: Path, records: list[dict], output_root: Path) -> Path:
    """Apply exact reviewed files; all originals are backed up before any write.

    Each record requires file, before (SHA-256 or null), after (SHA-256),
    reviewed=True and verified=True. The caller supplies actual review and
    verification evidence and must check game state before deploying JARs.
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
            raise ValueError('Duplicate deployment destination')
        seen.add(key)
        if not source.is_file() or file_hash(source) != row['after']:
            raise ValueError(f'Staged content changed: {row["file"]}')
        if 'before' not in row or file_hash(target) != row['before']:
            raise ValueError(f'Instance content changed: {row["file"]}')
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
                raise RuntimeError(f'Backup verification failed: {row["file"]}')
    journal['status'] = 'backed_up'
    save()
    applied = []
    try:
        for row, source, target in paths:
            if file_hash(source) != row['after'] or file_hash(target) != row['before']:
                raise RuntimeError(f'File changed during deployment: {row["file"]}')
            atomic_copy(source, target)
            applied.append((row, target))
            if file_hash(target) != row['after']:
                raise RuntimeError(f'Installed hash mismatch: {row["file"]}')
        journal['status'] = 'installed'
        save()
    except Exception as exc:
        failures = []
        for row, target in reversed(applied):
            try:
                if file_hash(target) != row['after']:
                    raise RuntimeError('Target changed again; retained for inspection')
                if row['before'] is None:
                    target.unlink()
                else:
                    atomic_copy(contained(backup, row['file']), target)
            except Exception as rollback_error:
                failures.append(dict(file=row['file'], error=str(rollback_error)))
        journal.update(status='rollback_incomplete' if failures else 'rolled_back', error=str(exc), rollback_errors=failures)
        save()
        raise
    return backup
