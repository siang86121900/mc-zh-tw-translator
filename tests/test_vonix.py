"""Vonix Guardian on published packs: logger choice, local zh_tw class text, config, sharing."""
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mc_zh_tw_translator import desktop_jobs as jobs, patches, vonix as v
from mc_zh_tw_translator.class_text import ClassFile
from mc_zh_tw_translator.vonix_text import TEXT
from test_imblocker import jar, pack
from test_install import Served
import test_patches


class TextTests(unittest.TestCase):
    def test_every_edit_keeps_arguments_and_is_chinese(self):
        self.assertEqual(set(TEXT), set(v.CLASS_HASHES))
        for name, edits in TEXT.items():
            for english, chinese in edits.items():
                self.assertEqual(re.findall(r'[\x00-\x1f]', english), re.findall(r'[\x00-\x1f]', chinese), (name, english))
                self.assertTrue(chinese.strip() and chinese != english, (name, english))
                self.assertNotRegex(chinese, '[臺巖牀羣峯]')

    def test_inventory_wording_reads_as_gained_or_lost(self):
        # 使用者 2026-11-26：put/took are shared by chests and the player's inventory.
        look = TEXT['network/vonix/guardian/core/command/LookupText.class']
        self.assertEqual((look['put'], look['took']), ('增加', '減少'))

    def test_default_config_is_whole_and_chinese(self):
        data = json.loads(v.config_text())
        self.assertEqual(data['language'], 'zh_tw')
        self.assertEqual(data['database']['type'], 'sqlite')
        self.assertTrue(data['actions']['logContainers'])
        kept = json.loads(v.config_text({'theme': 'red', 'language': 'en_us', 'queue': {'maxSize': 9}}))
        self.assertEqual((kept['theme'], kept['language'], kept['queue']), ('red', 'zh_tw', {'maxSize': 9}))


class VonixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.home = self.root/'app'
        self.closed = patch.object(jobs, 'ensure_game_closed'); self.closed.start(); self.addCleanup(self.closed.stop)

    def compile(self, code, name):
        javac = shutil.which('javac')
        if not javac:
            self.skipTest('需要 JDK 建立隔離測試模組')
        source = self.root/f'{name}.java'; source.write_text(code)
        subprocess.run([javac, '--release', '17', str(source)], check=True, capture_output=True, timeout=45)
        return (self.root/f'{name}.class').read_bytes()

    def listing(self):
        raw = self.compile('public final class Row { public static String row(int n) { return n+"m ago"; } '
                           'public static String verb(boolean b) { return b ? "put" : "took"; } }', 'Row')
        edits = {'Row.class': (hashlib.sha256(raw).hexdigest(), {'\x01m ago': '\x01 分鐘前', 'put': '增加', 'took': '減少'})}
        original = jar(self.root/'served.jar', v.MOD_ID)
        with zipfile.ZipFile(original, 'a') as z:
            z.writestr('Row.class', raw)
        data = original.read_bytes()
        entry = ('forge', (1, 20, 1), (1, 20, 1), 9629497, 'vonix-test.jar', len(data), hashlib.sha256(data).hexdigest())
        listing = patch.multiple(v, CLASS_EDITS=edits, FILES=(entry,), KNOWN={entry[6]: entry[5]}, LOCALIZED_SHA='')
        listing.start(); self.addCleanup(listing.stop)
        translated = self.root/'translated.jar'; v.stage_chinese_jar(original, translated)
        sha = hashlib.sha256(translated.read_bytes()).hexdigest()
        localized = patch.object(v, 'LOCALIZED_SHA', sha); localized.start(); self.addCleanup(localized.stop)
        return data, v.mod_file(entry)['url']

    def test_version_choice(self):
        self.assertEqual(v.choose(pack(self.root/'a'))[0]['fileID'], 9629497)
        self.assertEqual(v.choose(pack(self.root/'b', loader='neoforge-47.1.106'))[0]['fileID'], 9629497)
        self.assertIsNone(v.choose(pack(self.root/'c', '1.21.1', 'neoforge-21.1.1'))[0])

    def test_other_logger_even_disabled_blocks_install(self):
        p = pack(self.root/'p'); jar(p/'mods/indexor.jar.disabled', 'ledger')
        with patch.object(patches, 'install_mods') as install:
            self.assertEqual(v.ensure(p, self.home, session=Served({}))['state'], 'other_logger')
            install.assert_not_called()
        self.assertIn('已停用', v.other_logger(p))

    def test_text_shared_with_a_name_is_refused(self):
        raw = self.compile('public final class Put { public String put() { return "put"; } }', 'Put')
        with self.assertRaises(ValueError):
            v.safe_edits(raw, {'put': '增加'})

    def test_install_chinese_rerun_and_restore(self):
        data, url = self.listing(); p = pack(self.root/'p')
        server = Served({url: data})
        result = v.ensure(p, self.home, session=server, pause=lambda _: None)
        self.assertEqual(result['state'], 'installed', result)
        self.assertEqual(server.asked, [url])
        with zipfile.ZipFile(p/'mods/vonix-test.jar') as z:
            values = set(ClassFile(z.read('Row.class')).utf.values())
        self.assertTrue({'\x01 分鐘前', '增加', '減少'} <= values)
        self.assertEqual(json.loads((p/v.CONFIG).read_text(encoding='utf-8')), json.loads(v.config_text()))
        again = v.ensure(p, self.home, session=Served({}))
        self.assertEqual((again['state'], again['config_backup']), ('present', None), again)
        jobs.restore_backup(Path(result['config_backup']), p)
        self.assertEqual((p/'mods/vonix-test.jar').read_bytes(), data)
        self.assertFalse((p/v.CONFIG).exists())
        jobs.restore_backup(Path(result['backup']), p)
        self.assertFalse((p/'mods/vonix-test.jar').exists())

    def test_existing_config_only_changes_language(self):
        data, url = self.listing(); p = pack(self.root/'p')
        (p/'config/vonixguardian').mkdir(parents=True)
        (p/v.CONFIG).write_text(json.dumps({'theme': 'red', 'language': 'en_us'}), encoding='utf-8')
        result = v.ensure(p, self.home, session=Served({url: data}), pause=lambda _: None)
        self.assertEqual(result['state'], 'installed', result)
        self.assertEqual(json.loads((p/v.CONFIG).read_text(encoding='utf-8')), {'theme': 'red', 'language': 'zh_tw'})

    def test_publish_dry_run_and_explicit_opt_out_do_not_install(self):
        import publish_translation as pub
        p = pack(self.root/'p')
        args = SimpleNamespace(no_vonix=False, home=self.home, dry_run=True)
        with patch.object(v, 'ensure') as ensure:
            pub.add_vonix(args, p); args.no_vonix = True; args.dry_run = False; pub.add_vonix(args, p)
            ensure.assert_not_called()


class SharedVonixTests(unittest.TestCase):
    setUp = VonixTests.setUp
    compile = VonixTests.compile
    listing = VonixTests.listing

    def test_patch_installs_locally_only_with_consent(self):
        test_patches.PatchTests.setUp(self)
        for p in (self.translator, self.friend):
            manifest = json.loads((p/'manifest.json').read_text())
            manifest['minecraft'] = {'version': '1.20.1', 'modLoaders': [{'id': 'forge-47.3.0', 'primary': True}]}
            (p/'manifest.json').write_text(json.dumps(manifest))
            record = json.loads((p/'minecraftinstance.json').read_text()); record['installedAddons'] = []; record['gameVersion'] = '1.20.1'
            (p/'minecraftinstance.json').write_text(json.dumps(record))
        with patch('mc_zh_tw_translator.imblocker.ensure', return_value=dict(state='unsupported', line='')):
            test_patches.PatchTests.translate(self)
            data, url = self.listing()
            first = v.ensure(self.translator, self.home, session=Served({url: data}), pause=lambda _: None)
            self.assertEqual(first['state'], 'installed', first)
            (self.translator/'vonixguardian.db').write_bytes(b'who took what')
            out = patches.export_patch(self.translator, self.home)
            with zipfile.ZipFile(out['path']) as z:
                manifest = json.loads(z.read('manifest.json'))
                self.assertTrue(manifest['vonix'])
                self.assertEqual(manifest['minimum_app_version'], v.MINIMUM_APP_VERSION)
                self.assertFalse(any(n.endswith(('.class', '.db')) for n in z.namelist()))
                self.assertFalse(any(x['file'] == 'mods/vonix-test.jar' for x in manifest['required_mods']))
                self.assertFalse(any(x['file'] == v.CONFIG for x in manifest['files']))
                self.assertFalse(any(x.get('fileName') == 'vonix-test.jar' for x in manifest['left_out_mods']))
            home = self.root/'friend-app'
            declined = patches.apply_patch(self.friend, Path(out['path']), home)
            self.assertIsNone(declined['vonix']); self.assertFalse((self.friend/'mods/vonix-test.jar').exists())
            result = patches.apply_patch(self.friend, Path(out['path']), home, add_mods=True, session=Served({url: data}))
            self.assertEqual(result['vonix']['state'], 'installed', result['vonix'])
            self.assertEqual(json.loads((self.friend/v.CONFIG).read_text(encoding='utf-8'))['language'], 'zh_tw')


if __name__ == '__main__':
    unittest.main()
