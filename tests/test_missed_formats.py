"""Kinds of player text the 2026-10-03 inventory of seven real modpacks found no reader for: language keys data files
name that no language file has, FancyMenu's English labels, shader option names, Ice and Fire's bestiary, books in
several languages per file, dialogue lines and NPC lines used as language keys, and quest text in data packs. Each is
written where the game reads it, a rerun writes nothing, and a restore puts every file back."""
import gzip
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import desktop_jobs as jobs
from mc_zh_tw_translator import embedded_text
from mc_zh_tw_translator.desktop_jobs import plan, apply_session, restore_backup
from full_translation_audit import Audit, lang_table, mutf8, parse_binary_nbt


def mods_toml(mod):
    return f'modLoader="javafml"\n[[mods]]\nmodId="{mod}"\n'


class MissedFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.instance = root/'測試整合包'; self.home = root/'app'
        (self.instance/'mods').mkdir(parents=True)
        (self.instance/'manifest.json').write_text('{"minecraft":{"version":"1.21.1"}}', encoding='utf-8')
        (self.instance/'options.txt').write_text('lang:zh_tw\nresourcePacks:["vanilla"]\n', encoding='utf-8')

    def jar(self, name, files):
        with zipfile.ZipFile(self.instance/'mods'/name, 'w') as z:
            for n, data in files.items():
                z.writestr(n, data if isinstance(data, (bytes, str)) else json.dumps(data, ensure_ascii=False, indent=2))
        return self.instance/'mods'/name

    def make_plan(self):
        return plan(self.instance, self.home, lambda *_: None, references=([{}, {}], {'tested': True}))

    def translate(self, result, answers):
        """What AI would write for English rows: {English: Chinese}."""
        for r in result['rows']:
            english = r.get('en') if isinstance(r.get('en'), str) else r.get('current')
            if r['supported'] and r['origin'] == 'untranslated' and english in answers:
                r.update(proposed=answers[english], origin='ai_translation', changed=True)
        for r in result['rows']:
            if r['supported'] and r['changed']: r['reviewed'] = True
        return result

    def pack(self):
        with zipfile.ZipFile(self.instance/jobs.RESOURCE_PACK_FILE) as z:
            return {n: z.read(n) for n in z.namelist()}

    def written_nothing(self):
        again = self.make_plan()
        return [r['key'] for r in again['rows'] if r['supported'] and r['changed']]

    # --- language keys named by data files ----------------------------------------------------------------------

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_keys_data_files_name_but_no_language_file_has_go_into_the_pack(self, _):
        loot = {'pools': [{'entries': [{'type': 'minecraft:item', 'name': 'minecraft:shield', 'functions': [
            {'function': 'minecraft:set_name', 'name': {'translate': 'Uranium Tipped Arrow'}},
            {'function': 'minecraft:set_lore', 'lore': [
                {'translate': 'incendium.item.shield.desc1', 'fallback': 'Reacts to attacks with'},
                {'translate': 'demo.known'},  # the mod's language file has it
                {'translate': 'demo.advancement.title'}]}]}]}]}  # neither fallback nor English of its own
        self.jar('incendium.jar', {'META-INF/neoforge.mods.toml': mods_toml('incendium'),
                                   'data/incendium/loot_table/artifact/shield.json': loot,
                                   'assets/incendium/lang/en_us.json': {'demo.known': 'Known'}})
        result = self.make_plan()
        keys = {r['key']: r for r in result['rows'] if r.get('key_from_data')}
        self.assertEqual(set(keys), {'Uranium Tipped Arrow', 'incendium.item.shield.desc1'})
        self.assertEqual(keys['incendium.item.shield.desc1']['en'], 'Reacts to attacks with')
        self.assertEqual(keys['Uranium Tipped Arrow']['source'], 'mods/incendium.jar!/assets/incendium/lang/en_us.json')
        done = apply_session(self.translate(result, {'Uranium Tipped Arrow': '鈾頭箭', 'Reacts to attacks with': '受到攻擊時'}),
                             self.home, lambda *_: None)
        lang = json.loads(self.pack()['assets/incendium/lang/zh_tw.json'])
        self.assertEqual((lang['Uranium Tipped Arrow'], lang['incendium.item.shield.desc1']), ('鈾頭箭', '受到攻擊時'))
        self.assertEqual(done['shown_mismatch'], 0)
        self.assertEqual(self.written_nothing(), [])

    def test_a_data_pack_outside_mods_names_keys_through_a_mod_file(self):
        self.jar('host.jar', {'META-INF/neoforge.mods.toml': mods_toml('host'), 'assets/host/lang/en_us.json': {'host.a': 'A'}})
        folder = self.instance/'config/openloader/data/pack/data/bca/advancement'; folder.mkdir(parents=True)
        (folder/'root.json').write_text(json.dumps({'display': {'title': {'translate': 'Let the Showdown begin'}}}), encoding='utf-8')
        row = next(r for r in self.make_plan()['rows'] if r.get('key_from_data'))
        self.assertEqual(row['source'], 'mods/host.jar!/assets/bca/lang/en_us.json')  # never the data pack file itself

    # --- FancyMenu ----------------------------------------------------------------------------------------------

    LAYOUT = ('type = fancymenu_layout\n\nelement {\n  description = [Ad] Need a server? Get one!\n  label = Start a Server\n'
              '  element_type = custom_button\n}\n\nelement {\n  source = [source:local]/config/fancymenu/assets/a.png\n'
              '  element_type = image\n}\n\nelement {\n  source = %#FF5500%Hold%#% **T** for {"placeholder":"mcversion"}%n%to fix\n'
              '  source_mode = direct\n  element_type = text_v2\n}\n\nelement {\n  label = 開始遊戲\n}\n')

    def test_short_labels_are_listed_and_a_checked_format_says_why_it_stays_english(self):
        labels = {'groups': [{'headerLabel': 'Regional Variation', 'aspectLabels': {'chimera-a': 'Chimera A'}}]}
        self.jar('scanner.jar', {'fabric.mod.json': {'schemaVersion': 1, 'id': 'better_pokedex_scanner'},
                                 'assets/better_pokedex_scanner/variant_labels/cobblemon.json': labels,
                                 'assets/other_mod/labels/a.json': labels})
        rows = {r['source'].split('!/')[-1]: r for r in self.make_plan()['rows'] if r['kind'] == 'unsupported_config_text'}
        kept = rows['assets/better_pokedex_scanner/variant_labels/']
        self.assertEqual(kept['origin'], 'keep_original'); self.assertIn('Better Pokédex Scanner', kept['issue'])
        self.assertEqual(rows['assets/other_mod/labels/']['origin'], 'untranslated')  # unknown formats stay red

    def test_rich_language_values_are_listed_not_dropped(self):
        # owo-lib: a value may be a text component; such rows used to vanish without a red line in the report.
        self.jar('owo.jar', {'fabric.mod.json': {'schemaVersion': 1, 'id': 'owo'},
                             'assets/owo/lang/en_us.json': {'text.owo.select_hint': {'text': 'Shift-click to select multiple', 'color': 'gray'},
                                                            'text.owo.save': 'Save'}})
        rows = self.make_plan()['rows']
        listed = [r for r in rows if r['kind'] == 'unsupported_config_text' and r['key'] == 'rich_language']
        self.assertEqual(len(listed), 1); self.assertIn('Shift-click to select multiple', listed[0]['current'])
        self.assertTrue(any(r['key'] == 'text.owo.save' and r['kind'] == 'language' for r in rows))  # plain values as before

    def test_fancymenu_units_are_shown_words_only(self):
        units = dict(embedded_text.units('config/fancymenu/customization/menu.txt', self.LAYOUT.encode()))
        self.assertEqual(sorted(units.values()), sorted(['[Ad] Need a server? Get one!', 'Start a Server', '開始遊戲',
                                                         '%#FF5500%Hold%#% **T** for {"placeholder":"mcversion"}%n%to fix']))
        key = next(k for k, v in units.items() if v.startswith('%#FF'))
        with self.assertRaises(ValueError):  # a translation that drops a colour code or the placeholder is refused
            embedded_text.rewrite('config/fancymenu/customization/menu.txt', self.LAYOUT.encode(), {key: (units[key], '按住 T 修正')})
        self.assertFalse(jobs.same_format(units[key], '按住 T 修正'))
        self.assertTrue(jobs.same_format(units[key], '%#FF5500%按住%#% **T** 兩秒{"placeholder":"mcversion"}%n%即可修正'))
        # Pixelmon: a placeholder's own source (…/update.json) does not make the shown line a file path.
        version = ('element {\n  source = |||%n%Installed Pixelmon: {"placeholder":"modversion","values":{"modid":"pixelmon"}}%n%'
                   'Latest Pixelmon: {"placeholder":"json","values":{"json_path":".promos","source":"https://reforged.gg/forge/update.json"}}%n%|||\n'
                   '  source_mode = direct\n}\nelement {\n  source = /config/fancymenu/assets/text.txt\n  source_mode = resource\n}\n')
        found = list(dict(embedded_text.units('config/fancymenu/customization/v.txt', version.encode())).values())
        self.assertEqual(len(found), 1); self.assertIn('Installed Pixelmon', found[0])

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_fancymenu_english_labels_are_translated_in_place(self, _):
        folder = self.instance/'config/fancymenu/customization'; folder.mkdir(parents=True)
        (folder/'menu.txt').write_bytes(self.LAYOUT.encode()); before = (folder/'menu.txt').read_bytes()
        result = self.make_plan()
        done = apply_session(self.translate(result, {'Start a Server': '架設伺服器', '[Ad] Need a server? Get one!': '[廣告] 需要伺服器嗎？'}),
                             self.home, lambda *_: None)
        text = (folder/'menu.txt').read_text(encoding='utf-8')
        self.assertIn('  label = 架設伺服器\n', text); self.assertIn('  description = [廣告] 需要伺服器嗎？\n', text)
        self.assertIn('[source:local]/config/fancymenu/assets/a.png', text)  # an image path is never text
        self.assertEqual(self.written_nothing(), [])
        restore_backup(Path(done['backup']), self.instance)
        self.assertEqual((folder/'menu.txt').read_bytes(), before)

    # --- shader packs -------------------------------------------------------------------------------------------

    def test_shader_language_files_are_properties(self):
        text = '# comment\n  ! another\nprofile.low                 = §e低\noption.A=Shadow Light\nnot a pair\n'
        self.assertEqual(lang_table(text, 'shaders/lang/zh_CN.lang'), {'profile.low': '§e低', 'option.A': 'Shadow Light'})
        self.assertEqual(lang_table('a = b\n', 'assets/x/lang/en_us.lang'), {'a ': ' b'})  # Minecraft's own .lang as before

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_shader_option_names_get_a_zh_tw_file_beside_the_others(self, _):
        packs = self.instance/'shaderpacks'; packs.mkdir()
        with zipfile.ZipFile(packs/'Photon.zip', 'w') as z:
            z.writestr('shaders/lang/en_US.lang', 'profile.low     = §eLow\noption.FOG = Fog Settings\n')
            z.writestr('shaders/lang/zh_CN.lang', 'profile.low     = §e低\n')
            z.writestr('shaders/final.fsh', 'void main(){}')
        before = (packs/'Photon.zip').read_bytes()
        result = self.make_plan()
        done = apply_session(self.translate(result, {'Fog Settings': '霧氣設定'}), self.home, lambda *_: None)
        with zipfile.ZipFile(packs/'Photon.zip') as z:
            written = lang_table(z.read('shaders/lang/zh_tw.lang').decode('utf-8'), 'shaders/lang/zh_tw.lang')
            self.assertEqual(z.read('shaders/final.fsh'), b'void main(){}')
        self.assertEqual(written, {'profile.low': '§e低', 'option.FOG': '霧氣設定'})
        self.assertEqual(done['shown_mismatch'], 0)
        self.assertEqual(self.written_nothing(), [])
        restore_backup(Path(done['backup']), self.instance)
        self.assertEqual((packs/'Photon.zip').read_bytes(), before)

    # --- books in formats of their own --------------------------------------------------------------------------

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_bestiary_codex_and_several_language_books_go_into_the_pack(self, _):
        self.jar('iceandfire.jar', {'META-INF/neoforge.mods.toml': mods_toml('iceandfire'),
                                    'assets/iceandfire/lang/bestiary/en_us_0/alchemy_0.txt': 'After harvesting dragon\nblood',
                                    'assets/iceandfire/lang/bestiary/zh_cn_0/alchemy_0.txt': '收集龙血\n之后'})
        self.jar('saintsdragons.jar', {'META-INF/mods.toml': mods_toml('saintsdragons'),
                                       'assets/saintsdragons/codex/en_us/ecology/a.txt': 'Dragons dwell here.',
                                       'assets/saintsdragons/codex/zh_cn/ecology/a.txt': '龙栖息于此。'})
        chronicle = {'title': {'en_us': 'Escaping', 'ja_jp': '脱出'}, 'icon': 'chronodawn:portal'}
        wiki = {'entries': [{'id': 'a', 'name': {'zh_cn': '黑暗转化', 'en_us': 'Darkness'}, 'category': {'en': 'Raw', 'zh': '生肉类'}}]}
        self.jar('chronodawn.jar', {'META-INF/neoforge.mods.toml': mods_toml('chronodawn'),
                                    'assets/chronodawn/chronicle/entries/escaping.json': chronicle})
        self.jar('wiki.jar', {'META-INF/neoforge.mods.toml': mods_toml('foxablazeaqzl_wiki'),
                              'assets/foxablazeaqzl_wiki/wiki/skill_descriptions.json': wiki})
        result = self.make_plan()
        done = apply_session(self.translate(result, {'Escaping': '逃離'}), self.home, lambda *_: None)
        files = self.pack()
        self.assertEqual(files['assets/iceandfire/lang/bestiary/zh_tw_0/alchemy_0.txt'].decode('utf-8'), '收集龍血\n之後')
        self.assertEqual(files['assets/saintsdragons/codex/zh_tw/ecology/a.txt'].decode('utf-8'), '龍棲息於此。')
        book = json.loads(files['assets/chronodawn/chronicle/entries/escaping.json'])
        self.assertEqual(book, {'title': {'en_us': 'Escaping', 'ja_jp': '脱出', 'zh_tw': '逃離'}, 'icon': 'chronodawn:portal'})
        page = json.loads(files['assets/foxablazeaqzl_wiki/wiki/skill_descriptions.json'])['entries'][0]
        # The wiki shows its zh_cn (or zh) text for every Chinese language: that field becomes Taiwan wording.
        self.assertEqual((page['name'], page['category']), ({'zh_cn': '黑暗轉化', 'en_us': 'Darkness'}, {'en': 'Raw', 'zh': '生肉類'}))
        self.assertEqual(done['shown_mismatch'], 0)
        self.assertEqual(self.written_nothing(), [])

    # --- text used as a language key ------------------------------------------------------------------------------

    def test_dialogue_and_npc_lines_used_as_language_keys(self):
        self.jar('pixelmon.jar', {'META-INF/neoforge.mods.toml': mods_toml('pixelmon'),
                                  'data/pixelmon/pixelmon/npc/preset/girl.json': {'results': [
                                      {'title': 'pixelmon.npc.dialogue.battle', 'message': "Let's see what you've got!",
                                       'type': 'pixelmon:open_dialogue'},
                                      {'type': 'pixelmon:open_paged_dialogue', 'title': "Night's Watchman",
                                       'pages': ['Boosts a stat by 10%.', 'Stay a while.']}]},
                                  'assets/pixelmon/lang/en_us.json': {'pixelmon.npc.dialogue.battle': 'Battle'}})
        self.jar('additions.jar', {'META-INF/mods.toml': mods_toml('cobblemon_additions'),
                                   'data/cobblemon/dialogues/nurse.json': {'pages': [
                                       {'id': 'a', 'lines': ['Welcome to the Pokemon Center!'], 'input': 'q.dialogue.close();',
                                        'options': [{'text': 'Yes', 'value': 'yes', 'action': 'q.dialogue.close();'}]}]}})
        self.jar('apotheosis.jar', {'META-INF/mods.toml': mods_toml('apotheosis'),
                                    'data/apotheosis/minibosses/craig.json': {'name': 'Craig the Eternal',
                                                                               'gear': [{'name': 'Some Gear Set'}]}})
        keys = {r['key'] for r in self.make_plan()['rows'] if r.get('key_sentence')}
        self.assertEqual(keys, {"Let's see what you've got!", "Night's Watchman", 'Stay a while.',
                                'Welcome to the Pokemon Center!', 'Yes', 'Craig the Eternal'})

    # --- quest text read from data packs ---------------------------------------------------------------------------

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_more_quest_formats_go_into_the_data_pack(self, _):
        with zipfile.ZipFile(self.instance/'mods/OpenLoader.jar', 'w') as z:
            z.writestr('META-INF/neoforge.mods.toml', mods_toml('openloader'))
        (self.instance/'config/openloader/data').mkdir(parents=True)
        self.jar('stextras.jar', {'META-INF/neoforge.mods.toml': mods_toml('stextras'),
                                  'data/stextras/st_quests/daily/kill_moth.json': {'name': 'Kill Hell Moth', 'creator': 'kill', 'amount': 5}})
        self.jar('monsterexpansion.jar', {'META-INF/mods.toml': mods_toml('monsterexpansion'),
                                          'data/monsterexpansion/monsterology/ignathos.json': {
                                              'monster_ref': 'monsterexpansion:ignathos', 'title': '纵火破坏者', 'type': 'Avian'}})
        result = self.make_plan()
        rows = {(r['source'].split('!/')[-1], r['key']): r for r in result['rows'] if r['kind'] == 'data_text'}
        self.assertEqual(set(rows), {('data/stextras/st_quests/daily/kill_moth.json', '["name"]'),
                                     ('data/monsterexpansion/monsterology/ignathos.json', '["title"]'),
                                     ('data/monsterexpansion/monsterology/ignathos.json', '["type"]')})
        done = apply_session(self.translate(result, {'Kill Hell Moth': '擊殺地獄飛蛾', 'Avian': '鳥類'}), self.home, lambda *_: None)
        with zipfile.ZipFile(self.instance/jobs.DATA_PACK_FILE) as z:
            quest = json.loads(z.read('data/stextras/st_quests/daily/kill_moth.json'))
            guide = json.loads(z.read('data/monsterexpansion/monsterology/ignathos.json'))
        self.assertEqual(quest, {'name': '擊殺地獄飛蛾', 'creator': 'kill', 'amount': 5})
        self.assertEqual((guide['title'], guide['type'], guide['monster_ref']), ('縱火破壞者', '鳥類', 'monsterexpansion:ignathos'))
        self.assertEqual(self.written_nothing(), [])
        restore_backup(Path(done['backup']), self.instance)
        self.assertFalse((self.instance/jobs.DATA_PACK_FILE).exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_openloader_21_reads_the_data_pack_from_its_packs_folder(self, _):
        with zipfile.ZipFile(self.instance/'mods/OpenLoader-neoforge-1.21.1-21.1.5.jar', 'w') as z:
            z.writestr('META-INF/neoforge.mods.toml', mods_toml('openloader'))
        (self.instance/'config/openloader/packs').mkdir(parents=True)
        options = {'load_data_packs': {'value': True}}
        (self.instance/'config/openloader/options.json').write_text(json.dumps(options), encoding='utf-8')
        self.jar('tno.jar', {'META-INF/neoforge.mods.toml': mods_toml('tensura_tno'),
                             'data/stextras/st_quests/race/fox.json': {'quests': [{'name': '召唤物击杀Boss', 'amount': 1}]}})
        self.assertEqual(jobs.data_pack_file(self.instance), jobs.DATA_PACK_FILE_21)
        result = self.make_plan()
        done = apply_session(self.translate(result, {}), self.home, lambda *_: None)
        with zipfile.ZipFile(self.instance/jobs.DATA_PACK_FILE_21) as z:
            self.assertEqual(json.loads(z.read('data/stextras/st_quests/race/fox.json'))['quests'][0]['name'], '召喚物擊殺Boss')
        self.assertFalse((self.instance/jobs.DATA_PACK_FILE).exists())
        self.assertEqual(done['shown_mismatch'], 0)
        self.assertEqual(self.written_nothing(), [])
        restore_backup(Path(done['backup']), self.instance)
        self.assertFalse((self.instance/jobs.DATA_PACK_FILE_21).exists())
        # Data packs switched off in OpenLoader 21's options: nothing is written, and the report says why.
        options['load_data_packs']['value'] = False
        (self.instance/'config/openloader/options.json').write_text(json.dumps(options), encoding='utf-8')
        self.assertFalse(jobs.reads_data_packs(self.instance))

    # --- the inventory built into the scan ------------------------------------------------------------------------

    def test_resource_text_no_reader_covers_is_listed(self):
        a = Audit(Path(self.temp.name)/'audit', {})
        names = {'assets/beyond/info_text/text.txt': b'Summon System Overview\nContracts are used to summon companions.',
                 'assets/beyond/models/item/x.json': b'{"credit": "Made with Blockbench by someone nice"}',
                 'assets/beyond/notes/zh_cn/a.txt': '这是简体中文的说明文字'.encode(),  # another language's copy
                 'assets/beyond/lang/en_us.json': b'{"beyond.a": "Some words for a key"}'}
        a.collection('mods/beyond.jar', set(names), names.__getitem__)
        a.unsupported_assets('mods/beyond.jar', set(names), names.__getitem__, 0)
        listed = [r['source'] for r in a.rows if r['kind'] == 'unsupported_config_text']
        self.assertEqual(listed, ['mods/beyond.jar!/assets/beyond/info_text/'])

    def test_text_drawn_in_a_font_without_chinese_stays_english_with_the_reason(self):
        self.jar('beyond.jar', {'META-INF/neoforge.mods.toml': mods_toml('beyond_gacha_c'),
                                'assets/beyond_gacha_c/info_text/text.txt': 'Summon System Overview\nContracts are used to summon.',
                                'data/beyond_gacha_c/quests/a.json': {'name': 'Sub Kill Slime Hunter Group'}})
        result = self.make_plan()
        rows = [r for r in result['rows'] if r['kind'] == 'unsupported_config_text']
        self.assertEqual(sorted(r['source'] for r in rows), ['mods/beyond.jar!/assets/beyond_gacha_c/info_text/',
                                                             'mods/beyond.jar!/data/beyond_gacha_c/quests/'])
        self.assertTrue(all(r['origin'] == 'keep_original' and '方框' in r['issue'] for r in rows))
        self.assertEqual(jobs.unsupported_note(result), '')  # not a red line: checked, kept on purpose
        self.assertTrue(all(jobs.row_category(r) == 'keep' for r in rows))

    def test_nbt_strings_are_modified_utf8(self):
        emoji = '😀'.encode('utf-16-le')
        halves = [int.from_bytes(emoji[i:i+2], 'little') for i in (0, 2)]
        encoded = b''.join(chr(h).encode('utf-8', 'surrogatepass') for h in halves)
        self.assertEqual(mutf8(encoded + b'\xc0\x80a'), '😀\x00a')
        name = b'Name'; value = encoded
        nbt = b'\x0a\x00\x00' + b'\x08' + len(name).to_bytes(2, 'big') + name + len(value).to_bytes(2, 'big') + value + b'\x00'
        self.assertEqual(parse_binary_nbt(gzip.compress(nbt)), {'Name': '😀'})


if __name__ == '__main__':
    unittest.main()
