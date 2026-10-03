"""Words data packs show as written: structures, functions and loot tables (embedded_text)."""
import gzip
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import embedded_text as et, desktop_jobs as jobs, codex_bridge as ai


def nbt(value, name=''):
    """Gzipped NBT of nested dicts, lists of dicts / strings, ints and strings (test fixture writer)."""
    def s(text):
        b = text.encode('utf-8');return struct.pack('>H', len(b)) + b

    def tag(v):return 10 if isinstance(v, dict) else 9 if isinstance(v, list) else 8 if isinstance(v, str) else 3

    def body(v):
        if isinstance(v, dict):return b''.join(bytes([tag(x)]) + s(k) + body(x) for k, x in v.items()) + b'\0'
        if isinstance(v, list):return bytes([tag(v[0]) if v else 0]) + struct.pack('>i', len(v)) + b''.join(body(x) for x in v)
        if isinstance(v, str):return s(v)
        return struct.pack('>i', v)
    return gzip.compress(b'\x0a' + s(name) + body(value), mtime=0)


SHOP = {'size': [3, 3, 3], 'entities': [{'pos': [1, 1, 1], 'nbt': {
    'id': 'cobbledollars:cobble_merchant', 'CustomName': '"Poké Trader"',
    'CobbleMerchantShop': [{'Category': 'Cobble Balls', 'Offers': [{'Item': 'cobblemon:poke_ball'}]},
                           {'Category': 'Healing Items', 'Offers': [{'Item': 'cobblemon:potion'}]}]}}],
    'blocks': [{'pos': [0, 0, 0], 'nbt': {'id': 'minecraft:sign', 'front_text': {'messages': [
        '"Employees "', '"Only"', '""', '""']}}},
               {'pos': [0, 1, 0], 'nbt': {'id': 'minecraft:command_block',
                                          'Command': 'summon minecraft:villager ~ ~3 ~ {CustomName:\'{"text":"Kanto Map Guide","color":"yellow"}\'}'}}]}
FUNCTION = ('datapack enable "file/x.zip"\n'
            'tellraw @a [{"text":" [IMPORTANT]","color":"dark_red"},{"text":" The world must be reopened.","color":"gold"}]\n'
            'tellraw @a[tag=host] {"text":" No data will be lost.","italic":true}\n'
            'title @s actionbar {"text":"Welcome!"}\n'
            "give @s written_book[written_book_content={pages:['[[\"\",{\"text\":\"Congratulations\",\"bold\":true},\"\\\\n on completing the League\"]]'],title:\"Kanto Book\",author:\"Professor Oak\"}]\n")
LOOT = json.dumps({'pools': [{'entries': [{'type': 'item', 'name': 'minecraft:map', 'functions': [
    {'function': 'minecraft:set_name', 'name': {'text': '§eFirst Gym §c[KANTO]'}},
    {'function': 'minecraft:set_lore', 'lore': [{'text': 'Find the gym leader.'}]}]}]}]}, indent=2, ensure_ascii=False)


TRADES = json.dumps({'tiers': [{'groups': [{'num_to_select': 8.0, 'trades': [{
    'cost_a': {'type': 'minecraft:item', 'name': 'lumymon:onyx_stone'},
    'result': {'type': 'minecraft:item', 'name': 'minecraft:map', 'functions': [
        {'decoration': 'lumymon:ground_gym', 'destination': 'cobbleverse:kanto_brock_gym', 'function': 'minecraft:exploration_map'},
        {'function': 'minecraft:set_name', 'name': "§7Brock's Gym", 'target': 'item_name'},
        {'function': 'minecraft:set_lore', 'lore': ['Leads to the gym.', {'text': 'Pewter City'}]}]}}]}]}]},
    indent=2, ensure_ascii=False)


class EmbeddedTextTests(unittest.TestCase):
    def test_structure_without_the_gzip_trailer_is_read_and_written(self):
        # Oh The Biomes We've Gone 1.5.11: the gzip stream lacks its 8-byte trailer; the game reads it anyway.
        cut = nbt(SHOP)[:-8]
        found = dict(et.units('data/bwg/structure/shop.nbt', cut))
        self.assertIn('Cobble Balls', found.values())
        key = next(k for k, v in found.items() if v == 'Cobble Balls')
        written = et.rewrite('data/bwg/structure/shop.nbt', cut, {key: ('Cobble Balls', '精靈球')})
        self.assertIn('精靈球', dict(et.units('data/bwg/structure/shop.nbt', written)).values())
        with self.assertRaises((ValueError, struct.error)):  # content that is really cut short still fails
            et.units('data/bwg/structure/shop.nbt', nbt(SHOP)[:-40])

    def test_names_saved_as_bare_words_are_written_back_as_json_strings(self):
        shop = {'entities': [{'pos': [0, 0, 0], 'nbt': {'id': 'cobbledollars:cobble_merchant', 'CustomName': 'Arborist'}}]}
        found = dict(et.units('data/bca/structure/stores/shopkeeper.nbt', nbt(shop)))
        self.assertEqual(list(found.values()), ['Arborist'])
        key = next(iter(found))
        written = et.rewrite('data/bca/structure/stores/shopkeeper.nbt', nbt(shop), {key: ('Arborist', '樹果商人')})
        from full_translation_audit import parse_binary_nbt
        self.assertEqual(parse_binary_nbt(written)['entities'][0]['nbt']['CustomName'], '"樹果商人"')
        self.assertEqual(dict(et.units('data/bca/structure/stores/shopkeeper.nbt', written)), {key: '樹果商人'})
        # CTOV's "[Energy Detector]" looks like a list but is not JSON; Dungeons Arise pages hold several quotes.
        odd = {'blocks': [{'pos': [0, 0, 0], 'nbt': {'CustomName': '[Energy Detector]'}},
                          {'pos': [1, 0, 0], 'nbt': {'Book': {'tag': {'pages': ['"In the treasury of life."\n\n"Let it shine."']}}}}]}
        self.assertEqual(set(dict(et.units('data/ctov/structures/lab.nbt', nbt(odd))).values()),
                         {'[Energy Detector]', '"In the treasury of life."\n\n"Let it shine."'})

    def test_capsule_templates_in_config_are_structures(self):
        self.assertTrue(et.is_file('config/capsule/loot/common/_common_blueprint_discovery.nbt'))
        self.assertTrue(et.is_file('/config/capsule/loot/common/_common_blueprint_discovery.nbt'))  # how the scan asks
        self.assertFalse(et.is_file('config/othermod/loot/a.nbt'))
        self.assertFalse(et.is_file('/mods/x.jar!/config/capsule/loot/a.nbt'))
        self.assertIn('Cobble Balls', dict(et.units('config/capsule/rewards/shop.nbt', nbt(SHOP))).values())

    def test_books_saved_in_the_old_tag_format(self):
        # Pixelmon 9.4.1 boat_pirate.nbt: a lectern book from before 1.20.5, pages as plain text or JSON.
        old = {'blocks': [{'pos': [0, 0, 0], 'nbt': {'id': 'minecraft:lectern', 'Book': {'id': 'minecraft:written_book', 'tag': {
            'title': 'Pirate Secrets', 'author': 'Captain Tauros',
            'pages': ['  - Pirate Secrets -\n A Journal By: Captain Tauros', '{"text":"Greetings, wise adventurer."}']}}}}]}
        found = dict(et.units('data/pixelmon/structure/boats/boat_pirate.nbt', nbt(old)))
        self.assertEqual(set(found.values()), {'Pirate Secrets', 'Captain Tauros', '  - Pirate Secrets -\n A Journal By: Captain Tauros',
                                               'Greetings, wise adventurer.'})
        changes = {k: (v, {'Pirate Secrets': '海盜的祕密', 'Greetings, wise adventurer.': '你好，睿智的冒險者。'}.get(v, v)) for k, v in found.items()}
        written = dict(et.units('x/data/p/structure/b.nbt', et.rewrite('data/pixelmon/structure/boats/boat_pirate.nbt', nbt(old), changes)))
        self.assertIn('海盜的祕密', written.values()); self.assertIn('你好，睿智的冒險者。', written.values())
        self.assertIn('Captain Tauros', written.values())

    def test_plain_string_names_and_lore_of_trades_and_loot_tables(self):
        # VillagerConfig trades (COBBLEVERSE kanto_cartographer) name their maps with a plain string, shown as written.
        found = dict(et.units('data/lumymon/trades/kanto_cartographer.json', TRADES.encode()))
        self.assertEqual(found, {'[0]': 'Pewter City', '["plain", 0]': "§7Brock's Gym", '["plain", 1]': 'Leads to the gym.'})
        # Ids, the map's destination and its decoration are not words.
        self.assertNotIn('minecraft:map', found.values()); self.assertNotIn('cobbleverse:kanto_brock_gym', found.values())
        out = et.rewrite('data/lumymon/trades/kanto_cartographer.json', TRADES.encode(), {
            '["plain", 0]': ("§7Brock's Gym", '§7小剛的道館'), '[0]': ('Pewter City', '尼比市')}).decode()
        self.assertEqual(json.loads(out)['tiers'][0]['groups'][0]['trades'][0]['result']['functions'][1]['name'], '§7小剛的道館')
        self.assertEqual(out.replace('§7小剛的道館', "§7Brock's Gym").replace('尼比市', 'Pewter City'), TRADES)
        with self.assertRaises(ValueError):
            et.rewrite('data/lumymon/trades/kanto_cartographer.json', TRADES.encode(), {'["plain", 0]': ('Old name', '新')})
        # Beautify: an advancement's title and description written as plain strings.
        adv = json.dumps({'display': {'icon': {'item': 'beautify:blinds'}, 'title': 'Blinded by the lights',
                                      'description': {'text': 'Craft blinds'}, 'frame': 'task'}, 'criteria': {'c': {'trigger': 'x'}}})
        self.assertEqual(set(dict(et.units('data/beautify/advancements/progression/blinds.json', adv.encode())).values()),
                         {'Blinded by the lights', 'Craft blinds'})
        # Treasure Bags: the bag's name is a component read with Component.Serializer.
        bag = json.dumps({'displayName': {'text': 'Treasure Bag'}, 'rarity': 'common', 'lootTable': 'treasurebags:bags/default'})
        self.assertEqual(dict(et.units('data/treasurebags/treasurebags_types/default.json', bag.encode())), {'[0]': 'Treasure Bag'})
        # A loot table's own {"text"} pieces keep the keys earlier versions wrote.
        self.assertEqual(dict(et.units('data/x/loot_table/a.json', LOOT.encode())),
                         {'[0]': '§eFirst Gym §c[KANTO]', '[1]': 'Find the gym leader.'})


    def test_units_of_each_kind_and_the_rest_of_the_file_stays(self):
        found = dict(et.units('data/bca/structure/shop.nbt', nbt(SHOP)))
        self.assertEqual(set(found.values()), {'Poké Trader', 'Cobble Balls', 'Healing Items', 'Employees ', 'Only', 'Kanto Map Guide'})
        f = dict(et.units('data/setup/function/hello.mcfunction', FUNCTION.encode()))
        self.assertIn('[{"text":" [IMPORTANT]","color":"dark_red"},{"text":" The world must be reopened.","color":"gold"}]', f.values())
        self.assertIn(' No data will be lost.', f.values());self.assertIn('Welcome!', f.values())
        self.assertIn('Kanto Book', f.values());self.assertIn('Professor Oak', f.values())
        self.assertNotIn('file/x.zip', ''.join(f.values()))  # a command's own arguments are not words
        loot = dict(et.units('data/cobbleverse/loot_table/gym_map.json', LOOT.encode()))
        self.assertEqual(set(loot.values()), {'§eFirst Gym §c[KANTO]', 'Find the gym leader.'})
        # Writing back: only the words change.
        changes = {k: (v, {'Poké Trader': '寶可夢商人', 'Cobble Balls': '精靈球', 'Kanto Map Guide': '關都地圖嚮導'}.get(v, v)) for k, v in found.items()}
        written = et.rewrite('data/bca/structure/shop.nbt', nbt(SHOP), changes)
        from full_translation_audit import parse_binary_nbt
        data = parse_binary_nbt(written)
        self.assertEqual(data['entities'][0]['nbt']['CustomName'], '"寶可夢商人"')
        self.assertEqual(data['entities'][0]['nbt']['CobbleMerchantShop'][0]['Category'], '精靈球')
        self.assertEqual(data['entities'][0]['nbt']['CobbleMerchantShop'][0]['Offers'], [{'Item': 'cobblemon:poke_ball'}])
        self.assertIn('{CustomName:\'{"text":"關都地圖嚮導","color":"yellow"}\'}', data['blocks'][1]['nbt']['Command'])
        book = [k for k, v in f.items() if v.startswith('[["",{"text":"Congratulations"')][0]
        out = et.rewrite('data/x/function/b.mcfunction', FUNCTION.encode(),
                         {book: (f[book], '[["",{"text":"恭喜","bold":true},"\\n 完成聯盟挑戰"]]')}).decode()
        self.assertIn("pages:['[[\"\",{\"text\":\"恭喜\",\"bold\":true},\"\\\\n 完成聯盟挑戰\"]]']", out)
        self.assertEqual(out.replace("恭喜", 'Congratulations').replace('完成聯盟挑戰', 'on completing the League'), FUNCTION)
        with self.assertRaisesRegex(ValueError, '格式'):  # a whole component may only change its words
            et.rewrite('data/x/function/b.mcfunction', FUNCTION.encode(), {book: (f[book], '[{"text":"恭喜"}]')})
        with self.assertRaisesRegex(ValueError, '變動'):
            et.rewrite('data/x/function/b.mcfunction', FUNCTION.encode(), {book: ('stale', '恭喜')})
        loot_key = [k for k, v in loot.items() if v.startswith('§e')][0]
        new = et.rewrite('data/c/loot_table/gym_map.json', LOOT.encode(), {loot_key: (loot[loot_key], '§e第一座道館 §c[關都]')}).decode()
        self.assertEqual(new.replace('§e第一座道館 §c[關都]', '§eFirst Gym §c[KANTO]'), LOOT)

    def test_trainer_names_and_advancement_titles(self):
        # RCT shows a trainer's name as written unless it is {"translatable": key}.
        plain = '{\n  "name": "Ace Trainer Abel",\n  "team": [{"species": "abra", "name": "x"}]\n}'
        literal = '{"name": {"literal": "DummyH77"}, "ai": {}}'
        keyed = '{"name": {"translatable": "trainer.rctmod.abel", "literal": "Abel"}}'
        path = 'data/rctmod/trainers/abel.json'
        self.assertEqual(et.units(path, plain.encode()), [('["name"]', 'Ace Trainer Abel')])
        self.assertEqual(et.units(path, literal.encode()), [('["name"]', 'DummyH77')])
        self.assertEqual(et.units(path, keyed.encode()), [])  # the language file names it
        out = et.rewrite(path, plain.encode(), {'["name"]': ('Ace Trainer Abel', '菁英訓練家亞伯')}).decode()
        self.assertEqual(out, plain.replace('Ace Trainer Abel', '菁英訓練家亞伯'))
        # An advancement written in words (not a key) shows them as written.
        adv = '{"display": {"title": {"text": "Gym Challenger"}, "description": {"translate": "adv.x.desc"}}, "criteria": {}}'
        self.assertEqual([t for _, t in et.units('data/x/advancement/a.json', adv.encode())], ['Gym Challenger'])

    def test_a_data_format_without_a_reader_is_listed(self):
        # English sentences in display fields of data no reader covers (a mod's own quest board) are listed in red;
        # Cobblemon dialogues have a reader since v0.30.0 (DATA_KEY_SENTENCES), so they are not.
        from full_translation_audit import Audit
        with tempfile.TemporaryDirectory() as folder:
            audit = Audit(Path(folder) / 'audit', {})
            files = {'data/questboard/notices/intro.json': b'{"pages": [{"lines": [{"text": "Welcome to my humble shop"}]}]}',
                     'data/cobblemon/dialogues/intro.json': b'{"pages": [{"lines": ["Welcome to the Pokemon Center"]}]}',
                     'data/sample/recipe/a.json': b'{"result": {"name": "Not shown to anyone here"}}'}
            audit.unsupported_data('mods/a.jar', set(files), files.__getitem__)
            listed = [r['source'] for r in audit.rows if r['kind'] == 'unsupported_config_text']
            self.assertEqual(listed, ['mods/a.jar!/data/questboard/notices/'])

    def client(self, answers):
        class Client:
            def __init__(self, *_):pass
            def __enter__(self):return self
            def __exit__(self, *_):pass
            def models(self):return [dict(model='test-model')]
            def translate(self, payload, *_):
                return dict(translations=[dict(id=r['id'], translation=answers.get(r['text'], r['text']), note='test') for r in payload])
        return Client

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_rei_group_names_and_trade_names_are_translated_in_place(self, _):
        refs = ([{}, {}], {'sources': ['tw', 'cn']})
        rei = ('{\n\t"disabledGroups": [],\n\t"customGroups": [\n\t\t{\n\t\t\t"id": "custom:3671dae0",\n\t\t\t"name": "Lights",\n'
               '\t\t\t"stacks": ["{count:1,id:\\"minecraft:light\\"}"]\n\t\t}\n\t]\n}')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); instance = root / 'instance'; home = root / 'app'
            (instance / 'config/roughlyenoughitems').mkdir(parents=True); (instance / 'datapacks').mkdir(); (instance / 'mods').mkdir()
            groups = instance / 'config/roughlyenoughitems/collapsible.json5'; groups.write_text(rei, encoding='utf-8')
            with zipfile.ZipFile(instance / 'datapacks/dp.zip', 'w') as z:
                z.writestr('pack.mcmeta', '{"pack":{"pack_format":48,"description":"x"}}')
                z.writestr('data/lumymon/trades/kanto_cartographer.json', TRADES)
            before = (groups.read_bytes(), (instance / 'datapacks/dp.zip').read_bytes())
            session = jobs.plan(instance, home, lambda *_: None, references=refs)
            sent = {r['current'] for _, r in ai.pending_rows(session)}
            self.assertTrue({'Lights', "§7Brock's Gym", 'Leads to the gym.'} <= sent, sent)
            self.assertFalse({'custom:3671dae0', 'minecraft:map'} & sent)
            ai.supplement(session, home, 'test-model', lambda *_: None, client_factory=self.client(
                {'Lights': '光源', "§7Brock's Gym": '§7小剛的道館', 'Leads to the gym.': '通往道館。', 'Pewter City': '尼比市'}))
            jobs.prepare_to_apply(session)
            done = jobs.apply_session(session, home, lambda *_: None)
            self.assertEqual(session['shown_mismatch'], 0)
            self.assertEqual(json.loads(groups.read_text(encoding='utf-8'))['customGroups'][0]['name'], '光源')
            self.assertEqual(groups.read_text(encoding='utf-8').replace('光源', 'Lights'), rei)  # nothing else moved
            with zipfile.ZipFile(instance / 'datapacks/dp.zip') as z:
                self.assertIn('§7小剛的道館', z.read('data/lumymon/trades/kanto_cartographer.json').decode())
            self.assertEqual(jobs.applicable_count(jobs.plan(instance, home, lambda *_: None, references=refs)), 0)
            jobs.restore_backup(Path(done['backup']), instance)
            self.assertEqual((groups.read_bytes(), (instance / 'datapacks/dp.zip').read_bytes()), before)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_data_pack_words_are_translated_in_place_and_restored(self, _):
        refs = ([{}, {}], {'sources': ['tw', 'cn']})
        answers = {'Poké Trader': '寶可夢商人', 'Cobble Balls': '精靈球', 'Healing Items': '回復道具', 'Employees ': '員工',
                   'Only': '專用', 'Kanto Map Guide': '關都地圖嚮導', ' No data will be lost.': ' 不會遺失任何資料。',
                   'Welcome!': '歡迎！', 'Kanto Book': '關都之書', 'Professor Oak': '大木博士',
                   '§eFirst Gym §c[KANTO]': '§e第一座道館 §c[關都]', 'Find the gym leader.': '找到道館館主。',
                   '[{"text":" [IMPORTANT]","color":"dark_red"},{"text":" The world must be reopened.","color":"gold"}]':
                       '[{"text":" 【重要】","color":"dark_red"},{"text":" 必須重新開啟世界。","color":"gold"}]',
                   '[["",{"text":"Congratulations","bold":true},"\\n on completing the League"]]':
                       '[["",{"text":"恭喜","bold":true},"\\n 完成聯盟挑戰"]]'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); instance = root / 'instance'; home = root / 'app'
            (instance / 'datapacks').mkdir(parents=True); (instance / 'mods').mkdir()
            pack = instance / 'datapacks/modpack-dp.zip'
            with zipfile.ZipFile(pack, 'w') as z:
                z.writestr('pack.mcmeta', '{"pack":{"pack_format":48,"description":"x"}}')
                z.writestr('data/bca/structure/stores/shop.nbt', nbt(SHOP))
                z.writestr('data/setup/function/hello.mcfunction', FUNCTION)
                z.writestr('data/cobbleverse/loot_table/gym_map.json', LOOT)
            # A mod CurseForge puts back: listed as English the game keeps showing, never sent to AI.
            (instance / 'minecraftinstance.json').write_text(json.dumps({'installedAddons': [
                {'installedFile': {'fileName': 'managed.jar'}}]}), encoding='utf-8')
            with zipfile.ZipFile(instance / 'mods/managed.jar', 'w') as z:
                z.writestr('fabric.mod.json', '{"schemaVersion":1,"id":"managed"}')
                z.writestr('data/managed/structure/hut.nbt', nbt({'entities': [{'nbt': {'CustomName': '"Hut Keeper"'}}]}))
            before = pack.read_bytes()
            session = jobs.plan(instance, home, lambda *_: None, references=refs)
            rows = [r for r in session['rows'] if r['kind'] == 'embedded_text']
            held = next(r for r in rows if r['current'] == '"Hut Keeper"' or r['current'] == 'Hut Keeper')
            self.assertFalse(held['supported']); self.assertEqual(jobs.row_state(held, jobs.session_curseforge(session)), 'unwritable')
            sent = [r for _, r in ai.pending_rows(session) if r['kind'] == 'embedded_text']
            self.assertEqual(len(sent), 14); self.assertNotIn(held, sent)
            ai.supplement(session, home, 'test-model', lambda *_: None, client_factory=self.client(answers))
            self.assertFalse([r for r in session['rows'] if r['kind'] == 'embedded_text' and r['supported'] and r['origin'] == 'untranslated'])
            jobs.prepare_to_apply(session)
            done = jobs.apply_session(session, home, lambda *_: None)
            self.assertEqual(session['shown_mismatch'], 0)
            with zipfile.ZipFile(pack) as z:
                shop = dict(et.units('data/bca/structure/stores/shop.nbt', z.read('data/bca/structure/stores/shop.nbt')))
                fn = z.read('data/setup/function/hello.mcfunction').decode()
            self.assertIn('精靈球', shop.values()); self.assertIn('寶可夢商人', shop.values())
            self.assertIn('{"text":" 必須重新開啟世界。","color":"gold"}', fn); self.assertIn('datapack enable "file/x.zip"', fn)
            again = jobs.plan(instance, home, lambda *_: None, references=refs)
            self.assertEqual(jobs.applicable_count(again), 0)  # a rerun recognises what it wrote
            back = next(r for r in again['rows'] if r['kind'] == 'embedded_text' and r['current'] == '精靈球')
            self.assertEqual((back['origin'], back['en_ref']), ('ai_translation', 'Cobble Balls'))
            jobs.restore_backup(Path(done['backup']), instance)
            self.assertEqual(pack.read_bytes(), before)
            # The original pack is back (CurseForge reinstalled it): earlier AI work is reused, nothing goes to AI again.
            reset = jobs.plan(instance, home, lambda *_: None, references=refs)
            shop_row = next(r for r in reset['rows'] if r['kind'] == 'embedded_text' and r['current'] == 'Cobble Balls')
            self.assertEqual((shop_row['origin'], shop_row['proposed'], shop_row.get('ai_reused')), ('ai_translation', '精靈球', True))
            self.assertFalse([r for _, r in ai.pending_rows(reset) if r['kind'] == 'embedded_text'])


if __name__ == '__main__':unittest.main()
