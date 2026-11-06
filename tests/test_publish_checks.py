import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import publish_checks as checks, desktop_jobs as jobs, full_pack
from mc_zh_tw_translator.deployment import apply_reviewed, file_hash


class PublishChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.instance = self.root/'instance'
        (self.instance/'mods').mkdir(parents=True)
        self.staged = self.root/'staged'
        self.staged.mkdir()

    def archive(self, rel, files, root=None):
        p = (root or self.instance)/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, 'w') as z:
            for name, value in files.items():
                z.writestr(name, value)
        return p

    def configure(self, root=None):
        p = (root or self.instance)/'config/tooltipoverhaul/custom_frames.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'frames': [{'texture': 'tooltipoverhaul:textures/overlay/wr_common_frame.png'}]}), encoding='utf-8')

    def art(self, root=None):
        return self.archive('resourcepacks/材質 包.zip', {'assets/tooltipoverhaul/textures/overlay/wr_common_frame.png': b'image'}, root)

    def ysm(self, root=None, text='original'):
        return self.archive('mods/改名.jar', {'META-INF/mods.toml': '[[mods]]\nmodId="yes_steve_model"\n', 'assets/yes_steve_model/lang/en_us.json': '{}', 'text': text}, root)

    def test_missing_art_blocks_instead_of_silently_disabling_it(self):
        self.configure()
        with self.assertRaisesRegex(ValueError, 'wr_common_frame'):
            checks.required_packs(self.instance)
        self.assertFalse((self.instance/'options.txt').exists())

    def test_resolves_renamed_art_and_keeps_options_and_priority(self):
        self.configure(); self.art()
        required = checks.required_packs(self.instance)
        original = 'lang:en_us\nkey_key.jump:key.keyboard.space\nresourcePacks:["vanilla","file/personal.zip","file/MCTranslator-zh_tw.zip"]\n'
        merged = checks.merge_options(original, required)
        self.assertEqual(jobs.enabled_packs(merged), ['vanilla', 'file/personal.zip', 'file/材質 包.zip', jobs.RESOURCE_PACK_ID])
        self.assertIn('key_key.jump:key.keyboard.space', merged)
        self.assertIn('lang:en_us', merged)
        self.assertEqual(checks.merge_options(merged, required), merged)

    def test_staged_update_resolves_new_art_but_never_uses_a_deleted_pack(self):
        self.configure(self.staged); self.art(self.staged)
        self.assertEqual(checks.required_packs(self.instance, self.staged), ['file/材質 包.zip'])
        with self.assertRaisesRegex(ValueError, '缺少圖片'):
            checks.required_packs(self.instance, self.staged, ['resourcepacks/材質 包.zip'])

    def test_mod_assets_need_no_extra_pack(self):
        self.configure()
        self.archive('mods/art.jar', {'assets/tooltipoverhaul/textures/overlay/wr_common_frame.png': b'image'})
        self.assertEqual(checks.required_packs(self.instance), [])

    def test_broken_config_and_conflicting_art_are_reported(self):
        self.configure(); self.art()
        self.archive('resourcepacks/other.zip', {'assets/tooltipoverhaul/textures/overlay/wr_common_frame.png': b'image2'})
        with self.assertRaisesRegex(ValueError, '多個資源包'):
            checks.required_packs(self.instance)
        (self.instance/'config/tooltipoverhaul/custom_frames.json').write_text('{bad', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '設定讀取失敗'):
            checks.required_packs(self.instance)

    def test_bad_options_not_overwritten(self):
        with self.assertRaisesRegex(ValueError, '清單格式'):
            checks.merge_options('resourcePacks:broken\n', ['file/art.zip'])

    def test_removed_config_and_unsafe_texture_paths_are_not_used(self):
        self.configure()
        self.assertEqual(checks.required_packs(self.instance, removed=['config/tooltipoverhaul/custom_frames.json']), [])
        config=self.instance/'config/tooltipoverhaul/custom_frames.json'
        config.write_text('{"texture":"tooltipoverhaul:../secret.png"}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'路徑不合理'):
            checks.required_packs(self.instance)

    def test_translation_remains_above_existing_personal_packs(self):
        text='resourcePacks:["vanilla","file/MCTranslator-zh_tw.zip","file/personal.zip"]\n'
        self.assertEqual(jobs.enabled_packs(checks.merge_options(text,['file/art.zip'])),
                         ['vanilla','file/personal.zip','file/art.zip',jobs.RESOURCE_PACK_ID])

    def test_renamed_ysm_requires_official_hash_even_with_no_launcher_metadata(self):
        p = self.ysm()
        before = p.read_bytes()
        self.assertTrue(checks.protected(p))
        with self.assertRaisesRegex(ValueError, '校驗碼'):
            checks.check_ysm(self.instance)
        with patch.object(checks, 'YSM_SHA512', {hashlib.sha512(before).hexdigest()}):
            checks.check_ysm(self.instance)
        self.assertEqual(p.read_bytes(), before)

    def test_deployment_refuses_modified_ysm_before_any_backup_or_write(self):
        p = self.ysm(); q = self.ysm(self.staged, 'translated')
        with patch.object(checks, 'YSM_SHA512', {hashlib.sha512(p.read_bytes()).hexdigest()}):
            with self.assertRaisesRegex(ValueError, '校驗碼'):
                apply_reviewed(self.instance, self.staged, [dict(file='mods/改名.jar', before=file_hash(p), after=file_hash(q), reviewed=True, verified=True)], self.root/'output')
        self.assertFalse((self.root/'output').exists())
        self.assertNotEqual(p.read_bytes(), q.read_bytes())

    def test_generated_options_include_art_without_modifying_owner(self):
        self.configure(); self.art()
        original = 'lang:en_us\nresourcePacks:["vanilla"]\n'
        p = self.instance/'options.txt'; p.write_text(original, encoding='utf-8')
        generated = full_pack.generated_options(self.instance).decode('utf-8')
        self.assertIn('file/材質 包.zip', jobs.enabled_packs(generated))
        self.assertEqual(p.read_text(encoding='utf-8'), original)

    def test_options_apply_rerun_and_restore_are_byte_exact(self):
        self.configure(); self.art()
        original = b'lang:en_us\nresourcePacks:["vanilla","file/personal.zip"]\nkey_key.jump:key.keyboard.space\n'
        options = self.instance/'options.txt'; options.write_bytes(original)
        required = checks.required_packs(self.instance)
        record = jobs.options_record(self.instance, self.staged, False, True, required)
        backup = apply_reviewed(self.instance, self.staged, [record], self.root/'output')
        self.assertIn('file/材質 包.zip', jobs.enabled_packs(options.read_text(encoding='utf-8')))
        self.assertIsNone(jobs.options_record(self.instance, self.staged, False, True, required))
        jobs.restore_backup(backup, self.instance)
        self.assertEqual(options.read_bytes(), original)
