import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import publish_translation
from mc_zh_tw_translator import patches, solo_quests


class SoloQuestsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pack = Path(self.temp.name)
        (self.pack/'mods').mkdir()
        (self.pack/'manifest.json').write_text(json.dumps(
            dict(minecraft=dict(version='1.20.1', modLoaders=[dict(id='forge-47.4.0')]))), encoding='utf-8')
        for mod_id, version in [('ftbquests', '2001.4.17'), ('ftblibrary', '2001.2.12'),
                                ('ftbteams', '2001.3.2'), ('architectury', '9.2.14')]:
            self.jar(mod_id+'.jar', mod_id, version)

    def jar(self, filename, mod_id, version):
        with zipfile.ZipFile(self.pack/'mods'/filename, 'w') as jar:
            jar.writestr('META-INF/mods.toml', f'[[mods]]\nmodId="{mod_id}"\nversion="${{file.jarVersion}}"\n')
            jar.writestr('META-INF/MANIFEST.MF', f'Implementation-Version: {version}\r\n')

    def test_install_requires_compatible_enabled_dependencies(self):
        mod, reason = solo_quests.choose(self.pack)
        self.assertFalse(reason)
        self.assertEqual(mod['fileID'], 8614618)
        self.assertEqual(patches.mod_states(self.pack, [mod]), [(mod, 'install')])
        self.jar('ftbquests.jar', 'ftbquests', '2002.0.0')
        self.assertIn('ftbquests', patches.mod_states(self.pack, [mod])[0][1])
        self.jar('renamed.jar.disabled', solo_quests.MOD_ID, '1.0.0')
        self.assertIn('renamed.jar.disabled', solo_quests.choose(self.pack)[1])

    def test_existing_patch_can_add_download_and_preserve_translation_payload(self):
        source, dest = self.pack/'prior.zip', self.pack/'updated.zip'
        manifest = dict(added_mods=[], files=[dict(file='translation')], publish_checks=1)
        with zipfile.ZipFile(source, 'w') as jar:
            jar.writestr('manifest.json', json.dumps(manifest))
            jar.writestr('payload/translation', '測試譯文')
        mod, _ = solo_quests.choose(self.pack)
        publish_translation.with_solo_quests(source, dest, manifest, mod)
        with zipfile.ZipFile(dest) as jar:
            updated = json.loads(jar.read('manifest.json'))
            self.assertEqual(updated['files'][:-1], manifest['files'])
            entry = updated['files'][-1]
            key = publish_translation.SOLO_LANG
            self.assertEqual(entry['requires'][key], {'mods/'+mod['fileName']: mod['sha256']})
            self.assertEqual(json.loads(jar.read('payload/'+entry['file']+'/'+key)), publish_translation.SOLO_ZH_TW)
            self.assertEqual(updated['added_mods'], [mod])
            self.assertEqual(jar.read('payload/translation').decode(), '測試譯文')

    def test_republished_full_pack_card_still_names_the_checked_jar(self):
        # Society 4.2.1 republished whole (2026-11-25): Solo Quests was already in the pack, so it was not added
        # again, and the card would have dropped it although the upload carries it.
        from types import SimpleNamespace
        from unittest import mock
        self.jar('ftb-solo-quests.jar', solo_quests.MOD_ID, '1.1.2')
        jar = self.pack/'mods'/'ftb-solo-quests.jar'
        args = SimpleNamespace(no_solo_quests=False)
        self.assertIsNone(publish_translation.card_solo(args, self.pack))  # a jar that is not the checked file
        (file_id, _size, _sha), = [v for k, v in solo_quests.FILES.items() if k == ('forge', '1.20.1')]
        checked = {('forge', '1.20.1'): (file_id, jar.stat().st_size, solo_quests.file_hash(jar))}
        with mock.patch.dict(solo_quests.FILES, checked):
            self.assertIsNone(solo_quests.choose(self.pack)[0])  # not added a second time
            self.assertEqual(publish_translation.card_solo(args, self.pack)['name'], solo_quests.NAME)
            self.assertIsNone(publish_translation.card_solo(SimpleNamespace(no_solo_quests=True), self.pack))

    def test_full_pack_translation_pack_gets_the_added_mods_chinese(self):
        # Society 4.2.1 was shared whole with Solo Quests added after it was translated: its sync buttons stayed
        # English (Sync this quest progress / Sync all quests with team, 2026-11-25).
        import io
        mod, _ = solo_quests.choose(self.pack)
        source = io.BytesIO()
        with zipfile.ZipFile(source, 'w') as pack:
            pack.writestr('pack.mcmeta', '{}')
            pack.writestr('assets/demo/lang/zh_tw.json', '{"a":"甲"}')
            pack.writestr('mctranslator.json', json.dumps({'format': 1, 'sources': {'assets/demo/lang/zh_tw.json': {'mods/demo.jar': 'x'}}}))
        added = solo_quests.with_translation(source.getvalue(), mod)
        with zipfile.ZipFile(io.BytesIO(added)) as pack:
            self.assertEqual(json.loads(pack.read(solo_quests.LANG)), solo_quests.ZH_TW)
            self.assertEqual(pack.read('assets/demo/lang/zh_tw.json'), '{"a":"甲"}'.encode())
            sources = json.loads(pack.read('mctranslator.json'))['sources']
            self.assertEqual(sources[solo_quests.LANG], {'mods/'+mod['fileName']: mod['sha256']})
            self.assertIn('assets/demo/lang/zh_tw.json', sources)
        self.assertEqual(solo_quests.with_translation(added, mod), added)  # translated in the pack already: left alone
        # No English left but the mod's brand.
        for text in solo_quests.ZH_TW.values():
            self.assertNotRegex(text.replace('FTB Quests', ''), '[A-Za-z]{3,}')
