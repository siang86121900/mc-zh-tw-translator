import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator.deployment import apply_reviewed, atomic_copy

def sha(b): return hashlib.sha256(b).hexdigest()

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.instance = self.root/'instance'
        self.output = self.root/'output'
        self.staged = self.output/'candidates'
        self.instance.mkdir()
        self.staged.mkdir(parents=True)

    def record(self, name='lang.json', before=b'original', after=b'translated'):
        if before is not None:
            p = self.instance/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(before)
        p = self.staged/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(after)
        return dict(file=name, before=sha(before) if before is not None else None,
                    after=sha(after), reviewed=True, verified=True)

    def apply(self, rows):
        return apply_reviewed(self.instance, self.staged, rows, self.output)

    def test_backup_original_and_record_new_file(self):
        rows = [self.record('kubejs/a.json'), self.record('kubejs/b.json', None)]
        backup = self.apply(rows)
        self.assertEqual((backup/'kubejs/a.json').read_bytes(), b'original')
        self.assertFalse((backup/'kubejs/b.json').exists())
        manifest = json.loads((backup/'_備份紀錄/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['new_files'], ['kubejs/b.json'])
        self.assertEqual(manifest['status'], 'installed')
        self.assertEqual((self.instance/'kubejs/a.json').read_bytes(), b'translated')

    def test_distinct_backup_on_second_batch(self):
        first = self.apply([self.record()])
        second = self.apply([self.record(before=b'translated', after=b'next')])
        self.assertNotEqual(first, second)
        self.assertEqual((first/'lang.json').read_bytes(), b'original')
        self.assertEqual((second/'lang.json').read_bytes(), b'translated')

    def test_reject_stale_target_before_any_write(self):
        rows = [self.record('a'), self.record('b')]
        (self.instance/'b').write_bytes(b'user edit')
        with self.assertRaises(ValueError): self.apply(rows)
        self.assertEqual((self.instance/'a').read_bytes(), b'original')
        self.assertEqual((self.instance/'b').read_bytes(), b'user edit')

    def test_reject_tampered_candidate(self):
        row = self.record()
        (self.staged/'lang.json').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.apply([row])

    def test_reject_unreviewed_and_unverified(self):
        for key in ('reviewed','verified'):
            row = self.record(); row[key] = False
            with self.assertRaises(ValueError): self.apply([row])

    def test_reject_escape_and_duplicate(self):
        row = self.record()
        for name in ('../outside', 'C:/outside', '/outside', 'x:stream'):
            with self.assertRaises(ValueError): self.apply([dict(row,file=name)])
        with self.assertRaises(ValueError): self.apply([row,row])

    def test_backup_failure_leaves_targets_untouched(self):
        rows = [self.record('a'),self.record('b')]
        with patch('mc_zh_tw_translator.deployment.shutil.copy2', side_effect=OSError('backup failed')):
            with self.assertRaises(OSError): self.apply(rows)
        self.assertEqual((self.instance/'a').read_bytes(),b'original')

    def test_failure_restores_existing_and_removes_only_batch_new_file(self):
        rows = [self.record('a'),self.record('new',None),self.record('b')]
        calls = 0
        def fail_third(source, destination):
            nonlocal calls
            calls += 1
            if calls == 3: raise OSError('simulated failure')
            return atomic_copy(source,destination)
        with patch('mc_zh_tw_translator.deployment.atomic_copy',side_effect=fail_third):
            with self.assertRaises(OSError): self.apply(rows)
        self.assertEqual((self.instance/'a').read_bytes(),b'original')
        self.assertFalse((self.instance/'new').exists())
        self.assertEqual((self.instance/'b').read_bytes(),b'original')
        journals=list(self.output.glob('instance/原始備份/*/_備份紀錄/manifest.json'))
        self.assertEqual(json.loads(journals[0].read_text(encoding='utf-8'))['status'],'rolled_back')

if __name__ == '__main__': unittest.main()
