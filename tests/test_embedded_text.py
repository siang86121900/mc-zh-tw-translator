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


class EmbeddedTextTests(unittest.TestCase):
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
        # English sentences in display fields of data no reader covers (Cobblemon dialogues) are listed in red.
        from full_translation_audit import Audit
        with tempfile.TemporaryDirectory() as folder:
            audit = Audit(Path(folder) / 'audit', {})
            files = {'data/cobblemon/dialogues/intro.json': b'{"pages": [{"lines": [{"text": "Welcome to my humble shop"}]}]}',
                     'data/sample/recipe/a.json': b'{"result": {"name": "Not shown to anyone here"}}'}
            audit.unsupported_data('mods/a.jar', set(files), files.__getitem__)
            listed = [r['source'] for r in audit.rows if r['kind'] == 'unsupported_config_text']
            self.assertEqual(listed, ['mods/a.jar!/data/cobblemon/dialogues/'])

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


if __name__ == '__main__':unittest.main()
