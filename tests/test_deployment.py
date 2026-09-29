import hashlib
import json
import os
import tempfile
import threading
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
        def fail_third(source, destination, *rest):
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

    def in_use(self, name):
        return PermissionError(13, 'The process cannot access the file because it is being used by another process', name, 32)

    def test_write_waits_while_another_program_reads_the_new_file(self):
        rows = [self.record('mods/a.jar'), self.record('mods/b.jar')]
        real, calls, waited = os.replace, [], []
        def busy_twice(tmp, destination):
            calls.append(Path(destination).name)
            if calls.count(Path(destination).name) <= 2: raise self.in_use(str(tmp))
            return real(tmp, destination)
        with patch('mc_zh_tw_translator.deployment.os.replace', side_effect=busy_twice),              patch('mc_zh_tw_translator.deployment.time.sleep') as sleep:
            backup = apply_reviewed(self.instance, self.staged, rows, self.output, waited.append)
        self.assertEqual((self.instance/'mods/a.jar').read_bytes(), b'translated')
        self.assertEqual((self.instance/'mods/b.jar').read_bytes(), b'translated')
        self.assertEqual(waited, ['a.jar', 'a.jar', 'b.jar', 'b.jar'])
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(sorted(p.name for p in (self.instance/'mods').iterdir()), ['a.jar', 'b.jar'])
        self.assertEqual(json.loads((backup/'_備份紀錄/manifest.json').read_text(encoding='utf-8'))['status'], 'installed')

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_write_waits_for_a_really_open_file(self):
        rows = [self.record('mods/a.jar')]
        held = (self.instance/'mods/a.jar').open('rb')
        timer = threading.Timer(0.4, held.close)
        timer.start()
        try: self.apply(rows)
        finally: timer.cancel(); held.close()
        self.assertEqual((self.instance/'mods/a.jar').read_bytes(), b'translated')
        self.assertEqual([p.name for p in (self.instance/'mods').iterdir()], ['a.jar'])

    def test_file_held_for_good_is_named_and_the_batch_is_put_back(self):
        rows = [self.record('mods/a.jar'), self.record('mods/new.json', None), self.record('mods/b.jar')]
        real = os.replace
        def held(tmp, destination):
            if Path(destination).name == 'b.jar': raise self.in_use(str(tmp))
            return real(tmp, destination)
        with patch('mc_zh_tw_translator.deployment.os.replace', side_effect=held),              patch('mc_zh_tw_translator.deployment.time.sleep'):
            with self.assertRaises(PermissionError) as caught: self.apply(rows)
        # The message names the mod file, not the working copy beside it.
        self.assertEqual(Path(caught.exception.filename).name, 'b.jar')
        self.assertEqual(caught.exception.winerror if os.name == 'nt' else 32, 32)
        self.assertEqual((self.instance/'mods/a.jar').read_bytes(), b'original')
        self.assertEqual((self.instance/'mods/b.jar').read_bytes(), b'original')
        self.assertEqual(sorted(p.name for p in (self.instance/'mods').iterdir()), ['a.jar', 'b.jar'])
        journals = list(self.output.glob('instance/原始備份/*/_備份紀錄/manifest.json'))
        self.assertEqual(json.loads(journals[0].read_text(encoding='utf-8'))['status'], 'rolled_back')

    def test_working_copy_that_cannot_be_deleted_does_not_hide_the_result(self):
        self.record('mods/a.jar')
        source = self.staged/'mods/a.jar'
        with patch('mc_zh_tw_translator.deployment.Path.unlink', side_effect=self.in_use('working copy')),              patch('mc_zh_tw_translator.deployment.time.sleep'):
            atomic_copy(source, self.instance/'mods/a.jar')
        self.assertEqual((self.instance/'mods/a.jar').read_bytes(), b'translated')

    def test_leftover_working_copy_is_cleared_and_other_files_are_kept(self):
        rows = [self.record('mods/a.jar')]
        (self.instance/'mods/.translation-8rd1s974').write_bytes(b'left by an earlier write')
        (self.instance/'mods/.translation-notes.txt').write_bytes(b'player file')
        (self.instance/'mods/.translation-8rd1s974.jar').write_bytes(b'player file')
        (self.instance/'config').mkdir()
        (self.instance/'config/.translation-abcd1234').write_bytes(b'not a folder this batch writes to')
        self.apply(rows)
        self.assertEqual(sorted(p.name for p in (self.instance/'mods').iterdir()),
                         ['.translation-8rd1s974.jar', '.translation-notes.txt', 'a.jar'])
        self.assertTrue((self.instance/'config/.translation-abcd1234').exists())

if __name__ == '__main__': unittest.main()
