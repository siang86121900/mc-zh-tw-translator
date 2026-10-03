"""Quests a mod reads from data packs and shows as written (Whispering Quests): the translation is a data pack
OpenLoader puts above the mods, built again from the original each time, and restorable."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import desktop_jobs as jobs
from mc_zh_tw_translator.desktop_jobs import plan, apply_session, restore_backup

QUEST = 'data/demo/whisperingquests/tasks/main/find_irena.json'
CHAPTER = 'data/demo/whisperingquests/chapters/tutorial.json'
ENGLISH = 'data/demo/whisperingquests/tasks/side/english.json'


def quest(x=1007):
    return {'id': 'demo:main/find_irena', 'title': '§e寻找伊蕾娜§r', 'short_description': '前往魔法协会寻找伊蕾娜',
            'description': '根据守卫提供的坐标前往魔法协会。\n\n选择【开始追踪】即可显示坐标标记。',
            'icon': 'whisperingquests:textures/gui/quest_icon.png',
            'objectives': [{'type': 'location', 'id': 'reach', 'text': '前往坐标位置', 'position': {'x': x, 'y': 90, 'z': 104}},
                           {'type': 'dialogue', 'id': 'talk', 'text': '与伊蕾娜交谈'}],
            'rewards': [{'type': 'choice', 'pool_name': '职业属性果实', 'count': 1}]}


class DataPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.instance = root/'元素覺醒'; self.home = root/'app'
        (self.instance/'mods').mkdir(parents=True)
        (self.instance/'manifest.json').write_text('{"minecraft":{"version":"1.20.1"}}', encoding='utf-8')
        (self.instance/'options.txt').write_text('lang:zh_tw\n', encoding='utf-8')
        with zipfile.ZipFile(self.instance/'mods/OpenLoader-Forge-1.20.1-19.0.5.jar', 'w') as z:
            z.writestr('META-INF/mods.toml', 'modLoader="javafml"\n[[mods]]\nmodId="openloader"\n')
        (self.instance/'config/openloader/data').mkdir(parents=True)
        self.jar = self.instance/'mods/ysjxmodel-1.0.0.jar'; self.write_mod()

    def write_mod(self, x=1007):
        with zipfile.ZipFile(self.jar, 'w') as z:
            z.writestr('META-INF/mods.toml', 'modLoader="javafml"\n[[mods]]\nmodId="demo"\n')
            z.writestr(QUEST, json.dumps(quest(x), ensure_ascii=False, indent=2))
            z.writestr(CHAPTER, json.dumps({'id': 'demo:chapters/tutorial', 'title': '第五章 · 二轮世界与末地',
                                            'description': '调查二轮世界的魔王级生命信号。'}, ensure_ascii=False))
            z.writestr(ENGLISH, json.dumps({'title': 'Find the lost scroll', 'objectives': [{'id': 'a', 'text': 'Talk to the librarian'}]}))

    def make_plan(self):
        return plan(self.instance, self.home, lambda *_: None, references=([{}, {}], {'tested': True}))

    def confirm_all(self, result):
        for r in result['rows']:
            if r['supported'] and r['changed']: r['reviewed'] = True
        return result

    def pack(self):
        with zipfile.ZipFile(self.instance/jobs.DATA_PACK_FILE) as z:
            return {n: z.read(n) for n in z.namelist()}

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_quests_go_into_a_data_pack_that_a_rerun_recognises_and_restore_removes(self, _):
        before = self.jar.read_bytes()
        result = self.make_plan()
        rows = {(r['source'].split('!/')[-1], r['key']): r for r in result['rows'] if r['kind'] == 'data_text'}
        title = rows[(QUEST, '["title"]')]
        self.assertEqual((title['proposed'], title['origin'], title['supported']), ('§e尋找伊蕾娜§r', 'same_source_zh_cn', True))
        self.assertEqual(rows[(QUEST, '["rewards", 0, "pool_name"]')]['proposed'], '職業屬性果實')
        self.assertEqual(rows[(CHAPTER, '["title"]')]['proposed'], '第五章 · 二輪世界與終界')  # Mojang's Taiwan name for The End
        self.assertNotIn((QUEST, '["icon"]'), rows)  # an identifier, not text
        english = rows[(ENGLISH, '["title"]')]
        self.assertEqual((english['origin'], english['supported'], english['changed']), ('untranslated', True, False))
        self.assertEqual(jobs.row_state(english), 'missing')  # still English on screen, counted as a gap

        done = apply_session(self.confirm_all(result), self.home, lambda *_: None)
        self.assertEqual(self.jar.read_bytes(), before)  # the mod is never changed: CurseForge has nothing to put back
        files = self.pack()
        self.assertEqual(json.loads(files['pack.mcmeta'])['pack']['pack_format'], 15)  # data pack format of 1.20.1
        copy = json.loads(files[QUEST])
        self.assertEqual(copy['title'], '§e尋找伊蕾娜§r')
        self.assertEqual(copy['description'], '根據守衛提供的座標前往魔法協會。\n\n選擇【開始追蹤】即可顯示座標標記。')
        self.assertEqual(copy['objectives'][0]['position'], {'x': 1007, 'y': 90, 'z': 104})  # everything else as the mod has it
        self.assertEqual(copy['icon'], 'whisperingquests:textures/gui/quest_icon.png')
        self.assertNotIn(ENGLISH, files)  # nothing translated there: the mod's own copy is left to show
        self.assertEqual(done['shown_mismatch'], 0)

        again = self.make_plan()
        data = [r for r in again['rows'] if r['kind'] == 'data_text']
        self.assertFalse([r for r in data if r['changed'] and not r.get('installed')])  # a rerun writes nothing
        self.assertEqual(next(r for r in data if r['key'] == '["title"]' and QUEST in r['source'])['origin'], 'same_source_zh_cn')
        self.assertFalse(any(r['source'].startswith(jobs.DATA_PACK_FILE) for r in again['rows']))

        restore_backup(Path(done['backup']), self.instance)
        self.assertFalse((self.instance/jobs.DATA_PACK_FILE).exists())
        self.assertEqual(self.jar.read_bytes(), before)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_a_mod_update_is_never_hidden_under_an_old_copy(self, _):
        apply_session(self.confirm_all(self.make_plan()), self.home, lambda *_: None)
        self.write_mod(x=2000)  # the quest moved; its text is the same
        result = self.make_plan()
        title = next(r for r in result['rows'] if r['kind'] == 'data_text' and QUEST in r['source'] and r['key'] == '["title"]')
        self.assertTrue(title['changed'])  # the copy in the pack was made from the old file
        apply_session(self.confirm_all(result), self.home, lambda *_: None)
        copy = json.loads(self.pack()[QUEST])
        self.assertEqual(copy['objectives'][0]['position']['x'], 2000)
        self.assertEqual(copy['title'], '§e尋找伊蕾娜§r')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_ai_translation_of_english_quests_goes_into_the_pack(self, _):
        result = self.make_plan()
        row = next(r for r in result['rows'] if r['kind'] == 'data_text' and ENGLISH in r['source'] and r['key'] == '["title"]')
        row.update(proposed='尋找遺失的卷軸', origin='ai_translation', changed=True)
        apply_session(self.confirm_all(result), self.home, lambda *_: None)
        self.assertEqual(json.loads(self.pack()[ENGLISH])['title'], '尋找遺失的卷軸')
        again = next(r for r in self.make_plan()['rows'] if r['kind'] == 'data_text' and ENGLISH in r['source'] and r['key'] == '["title"]')
        self.assertEqual((again['origin'], again['changed'], again['current']), ('ai_translation', False, '尋找遺失的卷軸'))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_text_written_before_a_conversion_rule_is_corrected_once(self, _):
        # 擊殺 3 只殭屍 was written by v0.25.0, before the counter rule (只 → 隻) existed: a rerun corrects it once.
        q = quest(); q['objectives'][1]['text'] = '击杀 3 只僵尸'
        with zipfile.ZipFile(self.jar, 'a') as z:
            z.writestr('data/demo/whisperingquests/tasks/main/kill.json', json.dumps(q, ensure_ascii=False))
        loose = self.instance/'config/demo/text.json'; loose.parent.mkdir(parents=True)
        loose.write_text(json.dumps({'title': '击杀 3 只僵尸'}, ensure_ascii=False), encoding='utf-8')
        with patch('mc_zh_tw_translator.desktop_references.SLIPS', []):  # the rules of v0.25.0, roughly
            apply_session(self.confirm_all(self.make_plan()), self.home, lambda *_: None)
        self.assertIn('擊殺 3 只殭屍', json.loads(self.pack()['data/demo/whisperingquests/tasks/main/kill.json'])['objectives'][1]['text'])
        self.assertIn('只', loose.read_text(encoding='utf-8'))
        result = self.make_plan()
        fixed = [r for r in result['rows'] if r.get('changed') and not r.get('installed')]
        self.assertEqual(sorted(r['proposed'] for r in fixed if '殭屍' in r['proposed']), ['擊殺 3 隻殭屍', '擊殺 3 隻殭屍'])
        self.assertTrue(all('已修正轉換用字' in r['issue'] and not jobs.needs_check(r) for r in fixed if '殭屍' in r['proposed']))
        apply_session(self.confirm_all(result), self.home, lambda *_: None)
        self.assertEqual(json.loads(self.pack()['data/demo/whisperingquests/tasks/main/kill.json'])['objectives'][1]['text'], '擊殺 3 隻殭屍')
        self.assertEqual(json.loads(loose.read_text(encoding='utf-8'))['title'], '擊殺 3 隻殭屍')
        self.assertFalse([r for r in self.make_plan()['rows'] if r.get('changed') and not r.get('installed')])  # once only

    def test_the_modpacks_own_openloader_copy_is_the_one_translated(self):
        loose = self.instance/'config/openloader/data/modpack'/QUEST; loose.parent.mkdir(parents=True)
        changed = dict(quest(), title='§e寻找伊蕾娜（改）§r')
        loose.write_text(json.dumps(changed, ensure_ascii=False), encoding='utf-8')
        result = self.make_plan()
        titles = [r for r in result['rows'] if r['kind'] == 'data_text' and QUEST in r['source'] and r['key'] == '["title"]']
        self.assertEqual([r['source'] for r in titles], ['instance!/config/openloader/data/modpack/'+QUEST])
        self.assertEqual(titles[0]['proposed'], '§e尋找伊蕾娜（改）§r')
        self.assertTrue(result['source_counts']['data_overridden'])
        self.assertFalse([r for r in result['rows'] if r['kind'] == 'config' and 'whisperingquests' in r['source']])  # not read twice

    def test_without_openloader_nothing_is_written_and_the_reason_is_given(self):
        (self.instance/'mods/OpenLoader-Forge-1.20.1-19.0.5.jar').unlink()
        result = self.make_plan()
        title = next(r for r in result['rows'] if r['kind'] == 'data_text' and r['key'] == '["title"]' and QUEST in r['source'])
        self.assertEqual(title['issue'], jobs.HELD_NO_DATAPACK)
        self.assertEqual(jobs.row_state(title), 'unwritable')
        self.assertEqual(jobs.applicable_count(result), 0)

    def test_unknown_data_text_in_a_mod_is_listed_not_lost(self):
        with zipfile.ZipFile(self.instance/'mods/other.jar', 'w') as z:
            z.writestr('META-INF/mods.toml', 'modLoader="javafml"\n[[mods]]\nmodId="other"\n')
            for i in range(3):
                z.writestr(f'data/other/dialogue/talk{i}.json', json.dumps({'description': '和寻路者第一次相遇的对话'}, ensure_ascii=False))
            z.writestr('data/other/tags/damage_type/magic.json', json.dumps({'__comment': '可判断是否魔法的类型', 'values': []}, ensure_ascii=False))
            z.writestr('data/other/recipes/a.json', json.dumps({'type': 'minecraft:crafting_shaped'}))
        result = self.make_plan()
        listed = [r for r in result['rows'] if r['kind'] == 'unsupported_config_text']
        self.assertEqual([r['source'] for r in listed], ['mods/other.jar!/data/other/dialogue/'])
        self.assertIn('3 個資料檔', listed[0]['current'])
        self.assertTrue(jobs.unsupported_note(result))


if __name__ == '__main__':
    unittest.main()
