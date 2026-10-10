import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mc_zh_tw_translator.desktop_jobs import (plan, apply_session, restore_backup, validate_text,
    full_translation, GameRunningError, game_process_blocker)
from mc_zh_tw_translator.desktop_references import minecraft_version
from mc_zh_tw_translator.updater import check_update, download_update, version_tuple


OPTIONS = 'fov:0.0\nlang:en_us\nresourcePacks:["vanilla","fabric"]\n'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.instance=root/'測試模組包';self.home=root/'app'
        self.lang=self.instance/'kubejs/assets/demo/lang';self.lang.mkdir(parents=True)
        (self.lang/'en_us.json').write_text(json.dumps({'demo.hello':'Hello %s','demo.missing':'Unknown text'}),encoding='utf-8')
        (self.lang/'zh_cn.json').write_text(json.dumps({'demo.hello':'你好 %s'}),encoding='utf-8')
        (self.instance/'manifest.json').write_text('{"minecraft":{"version":"1.21.1"}}',encoding='utf-8')

    def make_plan(self):return plan(self.instance,self.home,lambda *_:None,references=([{},{}],{'tested':True}))

    def test_installed_translation_resourcepack_is_a_source(self):
        import zipfile
        rp=self.instance/'resourcepacks';rp.mkdir()
        with zipfile.ZipFile(rp/'community-zh_tw.zip','w') as z:
            z.writestr('pack.mcmeta','{"pack":{"pack_format":34,"description":"x"}}')
            z.writestr('assets/demo/lang/zh_tw.json',json.dumps({'demo.missing':'未知文字'}))
        row=next(r for r in self.make_plan()['rows'] if r['key']=='demo.missing' and r['source'].startswith('instance!/kubejs'))
        self.assertEqual((row['origin'],row['proposed']),('instance_resourcepack','未知文字'))

    def test_translation_pack_entries_for_uninstalled_mods_are_skipped(self):
        import zipfile
        (self.instance/'mods').mkdir()
        import io
        nested=io.BytesIO()
        with zipfile.ZipFile(nested,'w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="lib"\n')
            z.writestr('assets/lib/textures/a.png','x')
        with zipfile.ZipFile(self.instance/'mods/real.jar','w') as z:
            # An optional dependency the jar also carries compatibility textures for: still not installed.
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="real"\n'
                       '[[dependencies.real]]\nmodId="optional_dep"\ntype="optional"\n')
            z.writestr('assets/optional_dep/textures/c.png','x')
            z.writestr('assets/real/lang/en_us.json',json.dumps({'real.a':'Real'}))
            z.writestr('assets/compat/textures/b.png','x');z.writestr('data/compat/recipes/b.json','{}')  # files for a mod that is absent
            z.writestr('META-INF/jarjar/lib.jar',nested.getvalue())  # jar-in-jar library counts as installed
        packs=self.instance/'config/openloader/packs';packs.mkdir(parents=True)
        with zipfile.ZipFile(packs/'cfpa.zip','w') as z:
            z.writestr('assets/ghost/lang/en_us.json',json.dumps({'ghost.a':'Ghost'}))
            z.writestr('assets/real/lang/en_us.json',json.dumps({'real.b':'Real B'}))
            z.writestr('assets/lib/lang/en_us.json',json.dumps({'lib.a':'Library'}))
            z.writestr('assets/compat/lang/en_us.json',json.dumps({'compat.a':'Absent mod'}))
            z.writestr('assets/optional_dep/lang/en_us.json',json.dumps({'optional_dep.a':'Not installed'}))
        result=self.make_plan()
        self.assertFalse(any(x in r['source'] for r in result['rows'] for x in ('ghost','compat','optional_dep')))
        self.assertTrue(any(r['key']=='real.b' for r in result['rows']))
        self.assertTrue(any(r['key']=='lib.a' for r in result['rows']))
        self.assertEqual(result['source_counts']['not_installed'],3)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_two_copies_of_a_mod_use_the_newer_ones_text_and_a_rerun_writes_nothing(self,_):
        import zipfile
        from mc_zh_tw_translator import desktop_jobs as jobs
        (self.instance/'mods').mkdir();(self.instance/'options.txt').write_text('lang:zh_tw\n',encoding='utf-8')
        for jar,version,en,cn in (('IMBlocker-5.5.4.jar','5.5.4','[Experimental] Enable IME','[实验性功能] 启用输入法'),
                                  ('IMBlocker-5.6.2.jar','${file.jarVersion}','Enable IME','启用输入法')):
            with zipfile.ZipFile(self.instance/'mods'/jar,'w') as z:
                z.writestr('META-INF/mods.toml',f'modLoader="javafml"\n[[mods]]\nmodId="imblocker"\nversion="{version}"\n')
                z.writestr('META-INF/MANIFEST.MF','Manifest-Version: 1.0\nImplementation-Version: 5.6.2\n')
                z.writestr('assets/imblocker/lang/en_us.json',json.dumps({'imblocker.ime':en}))
                z.writestr('assets/imblocker/lang/zh_cn.json',json.dumps({'imblocker.ime':cn},ensure_ascii=False))
        result=self.make_plan()
        rows=[r for r in result['rows'] if r['key']=='imblocker.ime']
        self.assertEqual([r['source'].split('!/')[0] for r in rows],['mods/IMBlocker-5.6.2.jar'])
        done=apply_session(self.confirm_all(result),self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            self.assertEqual(json.loads(z.read('assets/imblocker/lang/zh_tw.json'))['imblocker.ime'],'啟用輸入法')
        self.assertEqual(done['shown_mismatch'],0)
        self.assertFalse([r for r in self.make_plan()['rows'] if r.get('changed') and not r.get('installed')])

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_biome_and_structure_names_no_language_file_has_are_translated(self,_):
        # VEFV2.7.1: the compasses showed biome.jellyfishing.ghostly_graveyard and "Abandoned Mine", since the mods
        # define them in data but never wrote their name keys; the keys go into the translation resource pack.
        import zipfile
        (self.instance/'mods').mkdir();(self.instance/'options.txt').write_text(OPTIONS,encoding='utf-8')
        with zipfile.ZipFile(self.instance/'mods/jellyfishing.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="jf"\n')
            z.writestr('assets/jf/lang/en_us.json',json.dumps({'item.jf.net':'Net','biome.jf.known':'Known Place'}))
            for path in ('worldgen/biome/ghostly_graveyard','worldgen/biome/known','worldgen/structure/abandoned_mine',
                         'worldgen/structure_set/abandoned_structures','dimension/lamp_shadow_world','tags/worldgen/biome/is_spooky'):
                z.writestr(f'data/jf/{path}.json','{}')
        result=self.make_plan()
        names={r['key']:r for r in result['rows'] if r.get('name_from_id')}
        self.assertEqual({k:r['en'] for k,r in names.items()},{'biome.jf.ghostly_graveyard':'Ghostly Graveyard','structure.jf.abandoned_mine':'Abandoned Mine',
                                                             'structure.jf.abandoned_structures':'Abandoned Structures','dimension.jf.lamp_shadow_world':'Lamp Shadow World'})
        row=names['biome.jf.ghostly_graveyard']
        self.assertEqual((row['origin'],row['supported']),('untranslated',True))  # a gap, left to AI with the others
        row.update(proposed='幽靈墓園',origin='ai_translation',changed=True,reviewed=True)
        apply_session(result,self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            self.assertEqual(json.loads(z.read('assets/jf/lang/zh_tw.json'))['biome.jf.ghostly_graveyard'],'幽靈墓園')
        again=next(r for r in self.make_plan()['rows'] if r['key']=='biome.jf.ghostly_graveyard')
        self.assertEqual((again['current'],again['changed']),('幽靈墓園',False))  # the pack's entry is what the game shows

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_compass_names_of_the_games_own_structures(self,_):
        # VEFV2.7.1 with Explorer's Compass: Trek's minecraft:pillager_outpost_dark_forest and the game's groups
        # (Villages, Pillager Outposts) showed in English, the compass's own zh_tw had 大河村 and Д被破壞的傳送門叢林,
        # and [Let's Do] Bakery's bakery structure was kept in English as the mod's name.
        import zipfile
        (self.instance/'mods').mkdir();(self.instance/'options.txt').write_text(OPTIONS,encoding='utf-8')
        with zipfile.ZipFile(self.instance/'mods/explorerscompass.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="explorerscompass"\n')
            z.writestr('assets/explorerscompass/lang/en_us.json',json.dumps({
                'item.explorerscompass.explorerscompass':"Explorer's Compass",'structure.minecraft.village_taiga':'Taiga Village',
                'structure.minecraft.ruined_portal_jungle':'Ruined Portal Jungle','structure.minecraft.pillager_outpost':'Pillager Outpost'}))
            z.writestr('assets/explorerscompass/lang/zh_tw.json',json.dumps({
                'item.explorerscompass.explorerscompass':'探險家指南針','structure.minecraft.village_taiga':'大河村',
                'structure.minecraft.ruined_portal_jungle':'Д被破壞的傳送門叢林','structure.minecraft.pillager_outpost':'掠奪者前哨站'},ensure_ascii=False))
        with zipfile.ZipFile(self.instance/'mods/trek.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="trek"\n')
            for path in ('worldgen/structure/pillager_outpost_dark_forest','worldgen/structure_set/pillager_outposts'):
                z.writestr(f'data/minecraft/{path}.json','{}')
        with zipfile.ZipFile(self.instance/'mods/bakery.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="bakery"\n')
            z.writestr('assets/bakery/lang/en_us.json',json.dumps({'item.bakery.bread':'Bread'}))
            z.writestr('data/bakery/worldgen/structure/bakery.json','{}')
        result=self.make_plan()
        rows={r['key']:r for r in result['rows']}
        outpost=rows['structure.minecraft.pillager_outpost_dark_forest']
        self.assertEqual((outpost['en'],outpost['origin'],outpost['source']),
                         ('Pillager Outpost Dark Forest','untranslated','mods/explorerscompass.jar!/assets/explorerscompass/lang/en_us.json'))
        self.assertEqual((rows['structure.minecraft.villages']['proposed'],rows['structure.minecraft.villages']['origin']),('村莊','official_vanilla'))
        group=rows['structure.minecraft.pillager_outposts']  # a group is named like the structure it holds
        self.assertEqual((group['en'],group['proposed'],group['plural_of']),('Pillager Outposts','掠奪者前哨站','structure.minecraft.pillager_outpost'))
        taiga=rows['structure.minecraft.village_taiga']
        self.assertEqual((taiga['proposed'],taiga['origin'],taiga['changed']),('針葉林村莊','official_vanilla',True))
        self.assertIn('大河村',taiga['issue'])
        self.assertEqual(rows['structure.minecraft.ruined_portal_jungle']['origin'],'untranslated')  # broken text is no source
        self.assertEqual((rows['structure.bakery.bakery']['en'],rows['structure.bakery.bakery']['origin']),('Bakery','untranslated'))
        self.assertNotIn('structure.minecraft.trek',rows)
        for r in result['rows']:
            if r['origin']=='untranslated':r.update(proposed='某個名稱',origin='ai_translation',changed=True)
            r['reviewed']=True
        apply_session(result,self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            pack=json.loads(z.read('assets/explorerscompass/lang/zh_tw.json'))
        self.assertEqual((pack['structure.minecraft.village_taiga'],pack['structure.minecraft.villages'],pack['item.explorerscompass.explorerscompass']),
                         ('針葉林村莊','村莊','探險家指南針'))
        self.assertFalse([r for r in self.make_plan()['rows'] if r.get('changed') and not r.get('installed')])  # a rerun writes nothing

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_without_a_compass_the_games_structures_get_no_rows(self,_):
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/trek.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="trek"\n')
            z.writestr('assets/trek/lang/en_us.json',json.dumps({'item.trek.map':'Map'}))
            z.writestr('data/minecraft/worldgen/structure/pillager_outpost_forest.json','{}')
        self.assertFalse([r for r in self.make_plan()['rows'] if r['key'].startswith('structure.minecraft.')])

    def test_other_languages_and_model_credits_are_not_book_text(self):
        # Alex's Caves keeps a Toki Pona copy of its book in books/tok/; block models in a books/ folder carry
        # "credit": "Made with Blockbench". Neither is English for the player to read.
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/caves.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="caves"\n')
            z.writestr('assets/caves/books/en_us/root.txt','Welcome to the caves below.')
            z.writestr('assets/caves/books/tok/root.txt','o kama pona tawa lupa a.')
            z.writestr('assets/caves/models/block/books/book.json',json.dumps({'credit':'Made with Blockbench','textures':{}}))
        sources={r['source'].split('!/')[-1] for r in self.make_plan()['rows'] if r['kind']=='book'}
        self.assertEqual(sources,{'assets/caves/books/en_us/root.txt'})

    def test_broken_optional_chinese_and_nontext_json_do_not_block_translation(self):
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/patchouli-like.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="sample"\n')
            z.writestr('assets/sample/lang/en_us.json',json.dumps({'sample.title':'Readable English'}))
            z.writestr('assets/sample/lang/zh_cn.json','{"sample.title":"损坏" "missing_comma":true}')
        data=self.instance/'config/openloader/data/pack/data/sample/affixes';data.mkdir(parents=True)
        (data/'combat.json').write_text('{"values":{"rare":{"min":1},}, "types":["bow"]}}',encoding='utf-8')

        result=self.make_plan()
        row=next(r for r in result['rows'] if r['key']=='sample.title')
        self.assertEqual((row['proposed'],row['origin'],row['supported']),('Readable English','untranslated',True))
        self.assertFalse(result['errors'])
        self.assertEqual(result['audit_counts']['broken_zh_cn_skipped'],1)
        self.assertEqual(result['audit_counts']['invalid_nontext_json_skipped'],1)

    def test_empty_book_page_is_not_an_error(self):
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/monsters.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="sample"\n')
            z.writestr('assets/sample/lang/en_us.json',json.dumps({'sample.title':'Readable English'}))
            z.writestr('assets/sample/guidebook/habitats/empty.json','')
            z.writestr('assets/sample/guidebook/habitats/full.json',json.dumps({'title':'Deep Caves'}))

        result=self.make_plan()
        self.assertFalse(result['errors'])
        self.assertEqual(result['audit_counts']['empty_book_skipped'],1)
        self.assertTrue(any(r['current']=='Deep Caves' or r.get('en')=='Deep Caves' for r in result['rows']))

    def test_broken_json_message_is_plain_chinese(self):
        from mc_zh_tw_translator.desktop_jobs import describe_error
        line=describe_error(['mods/a.jar','assets/a/guidebook/x.json','Expecting value: line 1 column 1 (char 0)'])
        self.assertTrue(line.startswith('a.jar：檔案本身格式錯誤'))
        self.assertIn('技術細節',line)

    def test_only_actionable_errors_are_red(self):
        from mc_zh_tw_translator.desktop_jobs import broken_source_file
        self.assertTrue(broken_source_file(['mods/a.jar','x.json','Expecting value: line 1 column 1 (char 0)']))
        self.assertTrue(broken_source_file(['mods/a.jar','x.json','Invalid \\escape: line 2 column 5 (char 9)']))
        # Our own scanner failing is still shown: the text may be on screen and unscanned.
        self.assertFalse(broken_source_file(['mods/a.jar',{},"'utf-8' codec can't encode character"]))
        self.assertFalse(broken_source_file(['mods/a.jar','class extraction: bad constant pool']))
        # Dungeon Now Loading 2.2 ships four structure files whose gzip data does not unpack: a note, not a red line.
        self.assertTrue(broken_source_file(['mods/dnl.jar','embedded text: CRC check failed']))
        self.assertTrue(broken_source_file(['mods/dnl.jar','embedded text: Error -3 while decompressing data: invalid literal/lengths set']))
        from mc_zh_tw_translator.desktop_jobs import inventory_note, broken_inventory_file
        damaged=dict(source='mods/dnl.jar!/data/d/structures/a.nbt',reason='x',detail='BadGzipFile: CRC check failed')
        malformed=dict(source='mods/v.jar!/data/v/loot_tables/a.json',reason='x',detail='JSONDecodeError: Extra data: line 129 column 1 (char 3179)')
        unread=dict(source='mods/big.jar!/data/b/structures/huge.nbt',reason='檔案大小超過盤點範圍，沒有讀取',detail='')
        self.assertTrue(broken_inventory_file(damaged) and broken_inventory_file(malformed));self.assertFalse(broken_inventory_file(unread))
        self.assertEqual(inventory_note(dict(text_inventory=dict(errors=[damaged,malformed]))),'')
        self.assertIn('有 1 項文字涵蓋檢查未完成',inventory_note(dict(text_inventory=dict(errors=[damaged,unread]))))

    def make_mod(self, nested=True):
        import io, zipfile
        (self.instance/'mods').mkdir(exist_ok=True)
        inner=io.BytesIO()
        with zipfile.ZipFile(inner,'w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="lib"\n')
            z.writestr('assets/lib/lang/en_us.json',json.dumps({'lib.a':'Library'}))
            z.writestr('assets/lib/lang/zh_cn.json',json.dumps({'lib.a':'函数库'}))
        with zipfile.ZipFile(self.instance/'mods/real.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="real"\n')
            z.writestr('assets/real/lang/en_us.json',json.dumps({'real.a':'Real','real.b':'Keep me'}))
            z.writestr('assets/real/lang/zh_cn.json',json.dumps({'real.a':'真实'}))
            z.writestr('assets/real/lang/zh_tw.json',json.dumps({'real.b':'保留我'}))
            if nested:z.writestr('META-INF/jarjar/lib.jar',inner.getvalue())
        return self.instance/'mods/real.jar'

    def confirm_all(self, result):
        for r in result['rows']:
            if r['supported'] and r['changed']:r['reviewed']=True
        return result

    def pack(self):
        import zipfile
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            return {n:z.read(n) for n in z.namelist()}

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_mod_text_goes_to_a_resource_pack_that_is_switched_on_and_restores(self,_):
        jar=self.make_mod();before=jar.read_bytes()
        (self.instance/'options.txt').write_text(OPTIONS,encoding='utf-8')
        result=self.confirm_all(self.make_plan());result.update(set_language=True)
        done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual(jar.read_bytes(),before)  # CurseForge would put a changed mod back; the mod stays untouched
        files=self.pack()
        self.assertEqual(json.loads(files['assets/real/lang/zh_tw.json']),{'real.a':'真實','real.b':'保留我'})  # mod's own zh_tw kept
        self.assertEqual(json.loads(files['assets/lib/lang/zh_tw.json']),{'lib.a':'函式庫'})  # embedded library text too
        self.assertEqual(json.loads(files['pack.mcmeta'])['pack']['pack_format'],34)
        sources=json.loads(files['mctranslator.json'])['sources']
        self.assertEqual(list(sources['assets/real/lang/zh_tw.json']),['mods/real.jar'])
        options=(self.instance/'options.txt').read_text(encoding='utf-8')
        self.assertIn('lang:zh_tw',options);self.assertIn('resourcePacks:["vanilla","fabric","mod_resources","file/MCTranslator-zh_tw.zip"]',options)
        self.assertTrue(done['language_set']);self.assertEqual(done['resource_pack'],'resourcepacks/MCTranslator-zh_tw.zip')
        restore_backup(Path(done['backup']),self.instance)
        self.assertFalse((self.instance/'resourcepacks/MCTranslator-zh_tw.zip').exists())
        self.assertEqual((self.instance/'options.txt').read_text(encoding='utf-8'),OPTIONS)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_second_run_sees_the_resource_pack_and_writes_nothing(self,_):
        self.make_mod()
        apply_session(self.confirm_all(self.make_plan()),self.home,lambda *_:None)
        again=self.make_plan()
        rows=[r for r in again['rows'] if r['source'].startswith('mods/')]
        self.assertTrue(rows)
        self.assertFalse([r['key'] for r in rows if r['changed']])  # the pack's text is what the game shows
        self.assertEqual({r['origin'] for r in rows if r['key']=='real.a'},{'same_source_zh_cn'})  # label kept
        self.assertFalse(any(r['source'].startswith('resourcepacks/MCTranslator') for r in again['rows']))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_a_second_copy_of_text_inside_a_mod_does_not_fight_the_main_copy(self,_):
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/cook.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="cook"\n')
            z.writestr('assets/cook/lang/en_us.json',json.dumps({'cook.a':'Sashimi','cook.b':'Tea'}))
            z.writestr('assets/cook/lang/zh_cn.json',json.dumps({'cook.a':'刺身','cook.b':'茶'},ensure_ascii=False))
            # kaleidoscope_cookery keeps an older copy of its text for other game versions
            z.writestr('legacy_pack/assets/cook/lang/en_us.json',json.dumps({'cook.a':'Old sashimi','cook.c':'Old only'}))
            z.writestr('legacy_pack/assets/cook/lang/zh_cn.json',json.dumps({'cook.a':'旧刺身','cook.c':'只有旧版'},ensure_ascii=False))
        result=self.confirm_all(self.make_plan())
        self.assertEqual(result['source_counts']['duplicate_copy'],1)
        apply_session(result,self.home,lambda *_:None)
        self.assertEqual(json.loads(self.pack()['assets/cook/lang/zh_tw.json']),{'cook.a':'刺身','cook.b':'茶','cook.c':'只有舊版'})
        again=self.make_plan()
        self.assertFalse([r['key'] for r in again['rows'] if r['source'].startswith('mods/') and r['changed']])

    def test_a_broken_emoji_in_a_mods_chinese_file_skips_only_that_line(self):
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/travel.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="travel"\n')
            z.writestr('assets/travel/lang/en_us.json','{"travel.bat": "\\uD83E\\uDD87 Darkness: %s", "travel.sword": "Sword"}')
            # TravelOptics 6.3.0 ships "\uD810E\uDD87": half an emoji, which used to fail the whole file
            z.writestr('assets/travel/lang/zh_cn.json','{"travel.bat": "\\uD810E\\uDD87黑暗能量: %s", "travel.sword": "剑"}'.encode('utf-8'))
        result=self.make_plan()
        self.assertFalse(result.get('errors'),result.get('errors'))
        rows={r['key']:r for r in result['rows'] if r['source'].startswith('mods/')}
        self.assertEqual(rows['travel.sword']['proposed'],'劍')  # the rest of the file is still used
        self.assertNotIn('�',rows['travel.bat'].get('proposed') or '')  # the broken line is not written
        json.dumps(result,ensure_ascii=False).encode('utf-8')  # and the report can be saved
        from mc_zh_tw_translator.desktop_jobs import describe_error
        line=describe_error(['mods/travel.jar',{},"'utf-8' codec can't encode character '\\ud810' in position 90: surrogates not allowed"])
        self.assertTrue(line.startswith('travel.jar：裡面有無法辨識的文字編碼，這個檔案的文字這次沒有掃描'),line)

    def test_server_language_files_in_a_data_folder_are_not_player_text(self):
        import zipfile
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/claims.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="claims"\n')
            z.writestr('assets/claims/lang/en_us.json',json.dumps({'claims.a':'Claim'}))
            z.writestr('assets/claims/lang/zh_cn.json',json.dumps({'claims.a':'领地'},ensure_ascii=False))
            # Forge reads only en_us from data/<mod>/lang (for the server); the screen uses assets/
            z.writestr('data/claims/lang/en_us.json',json.dumps({'claims.a':'Claim','claims.server_only':'Only here'}))
        result=self.make_plan()
        self.assertEqual(result['source_counts']['server_lang'],1)
        self.assertFalse([r for r in result['rows'] if r['key']=='claims.a' and '/data/' in r['source']])
        self.assertTrue([r for r in result['rows'] if r['key']=='claims.server_only'])  # not on screen elsewhere: still listed

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_a_book_page_two_mods_ship_counts_as_shown_by_the_one_the_game_reads(self,_):
        import zipfile
        from mc_zh_tw_translator import desktop_jobs as jobs
        (self.instance/'mods').mkdir()
        (self.instance/'options.txt').write_text('lang:zh_tw\n',encoding='utf-8')
        page='assets/goety/patchouli_books/brew/{}/entries/a.json'
        for jar,en,cn in (('goety.jar','Catalysts change brews.','催化剂改变药水。'),('addon.jar','Catalysts change brews!','催化剂会改变药水！')):
            with zipfile.ZipFile(self.instance/'mods'/jar,'w') as z:
                z.writestr('META-INF/neoforge.mods.toml',f'modLoader="javafml"\n[[mods]]\nmodId="{jar[:-4]}"\n')
                z.writestr(page.format('en_us'),json.dumps({'pages':[{'text':en}]}))
                z.writestr(page.format('zh_cn'),json.dumps({'pages':[{'text':cn}]},ensure_ascii=False))
        done=apply_session(self.confirm_all(self.make_plan()),self.home,lambda *_:None)
        rows=[r for r in done['rows'] if 'patchouli' in r['source']]
        self.assertEqual(len(rows),2)
        self.assertEqual(done['shown_mismatch'],0)  # the pack holds one of the two; the game shows Chinese there
        self.assertEqual(sum(bool(r.get('shown_other')) for r in rows),1)
        self.assertFalse(jobs.coverage(done).get('unconfirmed'))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_a_page_written_out_only_in_simplified_chinese_keeps_all_its_paragraphs(self,_):
        # Jerotes Village's Second Round World guide: zh_cn has 9 paragraphs, en_us a single unrelated one. The
        # Traditional copy was shaped like the English and dropped 8 paragraphs (Elemental Awakening 2026-10-05).
        import zipfile
        (self.instance/'mods').mkdir()
        (self.instance/'options.txt').write_text('lang:zh_tw\n',encoding='utf-8')
        page='assets/jv/patchouli_books/guide/{}/entries/cold.json'
        # First translated while both copies had one page (an earlier version wrote the pack shaped like the English):
        # paragraphs already Chinese there and unchanged are not in the next run's rows, and must not fall back to Simplified.
        with zipfile.ZipFile(self.instance/'mods/jv.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="jv"\n')
            z.writestr(page.format('en_us'),json.dumps({'name':'Bitter Cold','pages':[{'type':'patchouli:text','text':'Take a deep breath first.'}]}))
            z.writestr(page.format('zh_cn'),json.dumps({'name':'苦寒之地','pages':[{'type':'patchouli:text','text':'作为最寒冷的群系'}]},ensure_ascii=False))
        apply_session(self.confirm_all(self.make_plan()),self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'mods/jv.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="jv"\n')
            z.writestr(page.format('en_us'),json.dumps({'name':'Bitter Cold','pages':[{'type':'patchouli:text','text':'Take a deep breath first.'}]}))
            z.writestr(page.format('zh_cn'),json.dumps({'name':'苦寒之地','pages':[{'type':'patchouli:text','text':'作为最寒冷的群系'},
                {'type':'patchouli:text','text':'漫兽并不分布于这里'},{'type':'patchouli:spotlight','title':'苦寒摇铃','text':'用来驱逐雪怪'}]},ensure_ascii=False))
        done=apply_session(self.confirm_all(self.make_plan()),self.home,lambda *_:None)
        self.assertEqual(done['shown_mismatch'],0)
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            tw=json.loads(z.read(page.format('zh_tw')))
        self.assertEqual(tw['name'],'苦寒之地')
        self.assertEqual([p.get('text') for p in tw['pages']],['作為最寒冷的生態域','漫獸並不分佈於這裡','用來驅逐雪怪'])
        self.assertEqual((tw['pages'][2]['type'],tw['pages'][2]['title']),('patchouli:spotlight','苦寒搖鈴'))
        again=self.make_plan()
        self.assertFalse([r for r in again['rows'] if 'patchouli' in r['source'] and r.get('changed') and not r.get('installed')])
        # Ice and Fire's Tinkers book: the Chinese copy wrote the id field in Chinese ("modifier": "霜冻"). The English has a
        # place for it, so the English shape stays and the id is never replaced.
        tinkers='assets/jv/book/{}/modifiers/frost.json'
        with zipfile.ZipFile(self.instance/'mods/jv.jar','a') as z:
            z.writestr(tinkers.format('en_us'),json.dumps({'modifier':'frost','text':[{'text':'A coating of ice blood'}],'effects':['Freezes enemies']}))
            z.writestr(tinkers.format('zh_cn'),json.dumps({'modifier':'霜冻','text':[{'text':'涂满冰龙血'}],'effects':['冻结敌人']},ensure_ascii=False))
        rows=[r for r in self.make_plan()['rows'] if r['source'].endswith('modifiers/frost.json')]
        self.assertTrue(rows);self.assertFalse([r for r in rows if r.get('cn_shape') or r['key']=='["modifier"]'])

    def test_chinese_written_in_the_english_file_is_converted_at_once(self):
        lang=self.instance/'config/ftbquests/quests/lang';lang.mkdir(parents=True)
        (lang/'en_us.snbt').write_text('{\n\tquest.A.title: "食人魔萨满"\n}\n',encoding='utf-8')
        row=next(r for r in self.make_plan()['rows'] if r['key']=='quest.A.title')
        self.assertEqual((row['proposed'],row['origin']),('食人魔薩滿','same_source_zh_cn'))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_completion_rate_counts_only_what_the_game_files_really_hold(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        self.make_mod(nested=False)
        (self.instance/'options.txt').write_text('lang:zh_tw\n',encoding='utf-8')
        result=self.make_plan()
        before=jobs.coverage(result)
        self.assertEqual(before['done'],before['already'] if 'already' in before else before['done'])
        done=apply_session(self.confirm_all(result),self.home,lambda *_:None)
        self.assertEqual(done['shown_mismatch'],0)
        cov=jobs.coverage(done)
        # real.b was already Chinese; real.a and demo.hello were written and read back; demo.missing has no source
        self.assertEqual((cov['total'],cov['done'],cov['missing']),(4,3,1))
        view=jobs.home_cards(done);cards=view['cards']
        self.assertEqual([n for n,_ in cards],['75.0%','1'])
        self.assertIn('找不到中文來源',cards[1][1])
        self.assertEqual(view['written'],'這次從 25.0% 提升到 75.0%。')  # before: only real.b was Chinese in the game
        # the player switched the pack off: the mod line is not shown any more and is not counted as done
        (self.instance/'options.txt').write_text('lang:zh_tw\nresourcePacks:["vanilla"]\n',encoding='utf-8')
        rows=[r for r in done['rows'] if r.get('installed')]
        self.assertEqual(jobs.check_shown(self.instance,rows),1)
        self.assertEqual(jobs.coverage(done)['unconfirmed'],1)

    def test_nothing_written_is_explained_by_whether_english_is_left(self):
        from mc_zh_tw_translator.desktop_jobs import home_cards
        # "還缺中文 0" is what says the translation is finished; how much a run wrote is only a note
        finished=dict(rows=[],already_chinese=10,installed_count=0,status='needs_review',rate_before=1.0)
        self.assertEqual(home_cards(finished),dict(cards=[('100.0%','已辨識範圍中 10／10 句在檔案裡已是中文；尚非遊戲畫面實測'),('0','找得到的玩家文字都已是中文')],
                                                   written='和翻譯前一樣是 100.0%，這次沒有修改任何遊戲檔案。'))
        left=dict(rows=[dict(origin='untranslated',supported=True,proposed='Hello')],already_chinese=10,installed_count=0,status='needs_review',rate_before=10/11)
        self.assertEqual([n for n,_ in home_cards(left)['cards']],['90.9%','1'])  # rounded down: 100% only when nothing is left

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_text_written_in_several_languages_gets_taiwan_chinese_beside_it(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        scripts=self.instance/'config/ponderer/scripts';scripts.mkdir(parents=True)
        scene=dict(id='ponderer:alchemy_furnace',title={'en_us':'New Scene','zh_cn':'炼丹炉的介绍'},scenes=[dict(steps=[
            dict(type='idle',duration=10),
            # the modpack author cut the English short; the Simplified Chinese is complete
            dict(type='text',duration=60,text={'zh_cn':'炼丹的材料摆放位置需要一样','en_us':'The placement of the alchemy ing'})])])
        (scripts/'alchemy_furnace.json').write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf-8')
        other=self.instance/'config/othermod';other.mkdir(parents=True)
        (other/'x.json').write_text(json.dumps({'tip':{'en_us':'Hello','zh_cn':'你好'}},ensure_ascii=False),encoding='utf-8')
        result=self.make_plan()
        rows={(r['source'],r['key']):r for r in result['rows'] if r.get('kind')=='inline_lang'}
        text=rows[('config/ponderer/scripts/alchemy_furnace.json','["scenes", 0, "steps", 1, "text"]')]
        self.assertEqual((text['proposed'],text['origin'],text['supported']),('煉丹的材料擺放位置需要一樣','same_source_zh_cn',True))
        unknown=rows[('config/othermod/x.json','["tip"]')]
        self.assertFalse(unknown['supported']);self.assertEqual(unknown['issue'],jobs.INLINE_UNVERIFIED)
        done=apply_session(self.confirm_all(result),self.home,lambda *_:None)
        written=json.loads((scripts/'alchemy_furnace.json').read_text(encoding='utf-8'))
        self.assertEqual(written['scenes'][0]['steps'][1]['text'],
                         {'zh_cn':'炼丹的材料摆放位置需要一样','en_us':'The placement of the alchemy ing','zh_tw':'煉丹的材料擺放位置需要一樣'})
        self.assertEqual(written['title']['zh_tw'],'煉丹爐的介紹')
        self.assertEqual(written['scenes'][0]['steps'][0],dict(type='idle',duration=10))  # nothing else changes
        self.assertEqual(json.loads((other/'x.json').read_text(encoding='utf-8')),{'tip':{'en_us':'Hello','zh_cn':'你好'}})
        self.assertEqual(done['shown_mismatch'],0)
        again=self.make_plan()
        self.assertFalse([r['key'] for r in again['rows'] if r.get('kind')=='inline_lang' and r['changed'] and r['supported']])
        restore_backup(Path(done['backup']),self.instance)
        self.assertEqual(json.loads((scripts/'alchemy_furnace.json').read_text(encoding='utf-8')),scene)

    def test_language_switch_alone_leaves_resource_packs_alone(self):
        from mc_zh_tw_translator.desktop_jobs import options_record
        (self.instance/'options.txt').write_text('lang:en_us\n',encoding='utf-8')
        staged=Path(self.temp.name)/'staged';staged.mkdir()
        self.assertIsNone(options_record(self.instance,staged,False,False))
        options_record(self.instance,staged,False,True)
        self.assertEqual((staged/'options.txt').read_text(encoding='utf-8'),'lang:en_us\nresourcePacks:["vanilla","mod_resources","file/MCTranslator-zh_tw.zip"]\n')
        # A list the game saved with the mods' resources above this pack (Explorer's Compass stayed English)
        (self.instance/'options.txt').write_text('resourcePacks:["fabric","file/MCTranslator-zh_tw.zip","mod_resources"]\n',encoding='utf-8')
        options_record(self.instance,staged,False,True)
        self.assertEqual((staged/'options.txt').read_text(encoding='utf-8'),'resourcePacks:["fabric","mod_resources","file/MCTranslator-zh_tw.zip"]\n')
        (self.instance/'options.txt').write_text((staged/'options.txt').read_text(encoding='utf-8'),encoding='utf-8')
        self.assertIsNone(options_record(self.instance,staged,False,True))  # already in order: nothing to write
        (self.instance/'options.txt').write_text('resourcePacks:[broken\n',encoding='utf-8')
        with self.assertRaises(ValueError):options_record(self.instance,staged,False,True)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_server_translations_text_goes_to_the_translation_pack(self,_):
        import zipfile
        from mc_zh_tw_translator.desktop_jobs import RESOURCE_PACK_FILE, prepare_to_apply, applicable_count
        # Lenient Death keeps its text in data/lenientdeath/lang/ (Server Translations API); the game looks the key up
        # in the resource packs first, so the translation goes to assets/lenientdeath/lang/zh_tw.json in our pack.
        (self.instance/'mods').mkdir();jar=self.instance/'mods/lenientdeath.jar'
        (self.instance/'minecraftinstance.json').write_text('{}',encoding='utf-8')  # CurseForge: the mod file stays as it is
        with zipfile.ZipFile(jar,'w') as z:
            z.writestr('fabric.mod.json','{"schemaVersion":1,"id":"lenientdeath"}')
            z.writestr('data/lenientdeath/lang/en_us.json',json.dumps({'lenientdeath.command.done':'Items restored'}))
            z.writestr('data/lenientdeath/lang/zh_cn.json',json.dumps({'lenientdeath.command.done':'物品已恢复'},ensure_ascii=False))
        before=jar.read_bytes()
        session=self.make_plan()
        row=next(r for r in session['rows'] if r['key']=='lenientdeath.command.done')
        self.assertEqual((row['proposed'],row['supported']),('物品已恢復',True))
        prepare_to_apply(session);done=apply_session(session,self.home,lambda *_:None)
        self.assertEqual(jar.read_bytes(),before)
        with zipfile.ZipFile(self.instance/RESOURCE_PACK_FILE) as z:
            self.assertEqual(json.loads(z.read('assets/lenientdeath/lang/zh_tw.json')),{'lenientdeath.command.done':'物品已恢復'})
        self.assertTrue(next(r for r in session['rows'] if r['key']=='lenientdeath.command.done')['shown'])
        self.assertEqual(applicable_count(self.make_plan()),0)  # a rerun writes nothing
        restore_backup(Path(done['backup']),self.instance)
        self.assertFalse((self.instance/RESOURCE_PACK_FILE).exists())

    def test_default_options_preset_keeps_the_translation_pack(self):
        import tomllib
        from mc_zh_tw_translator.desktop_jobs import default_packs_record, DEFAULT_OPTIONS_FILE
        # COBBLEVERSE: Default Options replaced the pack list on the first start, dropping the translation
        config=self.instance/DEFAULT_OPTIONS_FILE;config.parent.mkdir(parents=True,exist_ok=True)
        text=('\n# Resource pack IDs to have enabled by default on the first run.\n'
              'defaultResourcePacks = [ "vanilla","fabric","file/COBBLEVERSE RP [CF].zip" ]\n\nlockDifficulty = false\n')
        config.write_text(text,encoding='utf-8')
        staged=Path(self.temp.name)/'staged';staged.mkdir()
        record=default_packs_record(self.instance,staged)
        new=(staged/DEFAULT_OPTIONS_FILE).read_text(encoding='utf-8')
        self.assertEqual(tomllib.loads(new)['defaultResourcePacks'],['vanilla','fabric','file/COBBLEVERSE RP [CF].zip','file/MCTranslator-zh_tw.zip'])
        self.assertEqual(new.replace(',"file/MCTranslator-zh_tw.zip"',''),text)  # nothing else changed
        self.assertEqual(record['file'],DEFAULT_OPTIONS_FILE)
        config.write_text(new,encoding='utf-8')
        self.assertIsNone(default_packs_record(self.instance,staged))  # already there: nothing to write
        for other in ('defaultResourcePacks = []\n','lockDifficulty = false\n','defaultResourcePacks = [ "a",\n'):
            config.write_text(other,encoding='utf-8')
            self.assertIsNone(default_packs_record(self.instance,staged))  # no preset or unreadable: left alone

    def test_packs_the_game_turns_on_itself_go_below_the_translation(self):
        from mc_zh_tw_translator.desktop_jobs import options_record
        # The Foll: OpenLoader 19 and Fragmentum put their packs above the list when it does not name them
        (self.instance/'mods').mkdir();(self.instance/'mods/OpenLoader-Forge-1.20.1-19.0.4.jar').write_bytes(b'')
        (self.instance/'config/openloader/resources').mkdir(parents=True)
        for name in ('早早汉化补充包.zip','dog-compat.zip','notes.txt'):(self.instance/'config/openloader/resources'/name).write_bytes(b'')
        (self.instance/'logs').mkdir()
        loaded=['vanilla','mod_resources','KubeJS Resource Pack [assets]','file/old.zip','file/MCTranslator-zh_tw.zip',
                'generated/fragmentum_layer','resources/dog-compat.zip','resources/??汉化补充包.zip','KubeJS Virtual Resource Pack [Last, assets]']
        (self.instance/'logs/latest.log').write_bytes(('[15:34:27] [Render thread/INFO]: Reloading ResourceManager: '+', '.join(loaded)+'\r\n').encode('cp950','replace'))
        (self.instance/'options.txt').write_text('resourcePacks:["vanilla","mod_resources","file/old.zip","file/MCTranslator-zh_tw.zip"]\n',encoding='utf-8')
        staged=Path(self.temp.name)/'staged';staged.mkdir()
        options_record(self.instance,staged,False,True)
        self.assertEqual((staged/'options.txt').read_text(encoding='utf-8'),
                         'resourcePacks:["vanilla","mod_resources","file/old.zip","resources/dog-compat.zip","resources/早早汉化补充包.zip",'
                         '"generated/fragmentum_layer","file/MCTranslator-zh_tw.zip"]\n')
        # once the list names them (the player moved the pack up), nothing changes
        (self.instance/'options.txt').write_text((staged/'options.txt').read_text(encoding='utf-8'),encoding='utf-8')
        self.assertIsNone(options_record(self.instance,staged,False,True))
        # OpenLoader switched off for resource packs: its folder is not a pack source (the log alone still counts)
        (self.instance/'config/openloader/advanced_options.json').write_text('{"resourcePacks":{"enabled":false}}',encoding='utf-8')
        (self.instance/'options.txt').write_text('resourcePacks:["vanilla","mod_resources","file/old.zip"]\n',encoding='utf-8')
        options_record(self.instance,staged,False,True)
        self.assertNotIn('早早',(staged/'options.txt').read_text(encoding='utf-8'))

    def test_program_text_is_not_written_where_curseforge_puts_mods_back(self):
        from mc_zh_tw_translator.desktop_jobs import write_route, HELD_CURSEFORGE, pack_format
        cls=dict(source='mods/a.jar!/a/B.class',key='3',kind='class_display')
        lang=dict(source='mods/a.jar!/assets/a/lang/en_us.json',key='k',kind='language')
        loose=dict(source='instance!/kubejs/assets/a/lang/en_us.json',key='k',kind='language')
        self.assertEqual([write_route(r,True) for r in (cls,lang,loose)],[HELD_CURSEFORGE,'pack','file'])
        self.assertEqual(write_route(cls,False),'file')
        self.assertEqual((pack_format('1.20.1'),pack_format('1.21.1'),pack_format('1.12.2'),pack_format('')),(15,34,3,34))

    def test_curseforge_only_puts_back_the_mod_files_it_installed(self):
        from mc_zh_tw_translator.desktop_jobs import write_route, is_curseforge, HELD_CURSEFORGE
        self.assertIs(is_curseforge(self.instance),False)
        # The Foll: a profile made in CurseForge, with mods the player added by hand
        (self.instance/'minecraftinstance.json').write_text(json.dumps({'installedAddons':[
            {'installedFile':{'fileName':'goety-2.5.jar','fileNameOnDisk':'goety-2.5.jar'}}]}),encoding='utf-8')
        cf=is_curseforge(self.instance);self.assertTrue(cf)
        tracked=dict(source='mods/goety-2.5.jar!/a/B.class',key='3',kind='class_display')
        by_hand=dict(source='mods/ageofmythology-0.3.0-all.jar!/a/B.class',key='3',kind='class_display')
        self.assertEqual((write_route(tracked,cf),write_route(by_hand,cf)),(HELD_CURSEFORGE,'file'))
        (self.instance/'minecraftinstance.json').write_text('{broken',encoding='utf-8')
        self.assertEqual(write_route(by_hand,is_curseforge(self.instance)),HELD_CURSEFORGE)  # unreadable: hold every file

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_file_names_in_config_are_not_converted_and_broken_ones_are_put_back(self,_):
        # VEFV2.7.1: Paxi's resourcepack_load_order.json names packs by file name; v0.17-v0.26 converted
        # 探险者指南针结构汉化 v3.1.zip to Traditional, so the order no longer named the file.
        import zipfile
        from mc_zh_tw_translator import desktop_jobs as jobs
        packs=self.instance/'config/paxi/resourcepacks';packs.mkdir(parents=True)
        for name in ('探险者指南针结构汉化 v3.1.zip','彩虹像素☆禁用树.zip'):
            with zipfile.ZipFile(packs/name,'w') as z:z.writestr('pack.mcmeta','{}')
        order=self.instance/'config/paxi/resourcepack_load_order.json'
        original='{\n  "loadOrder": [\n    "探險者指南針結構漢化 v3.1.zip",\n    "彩虹像素☆禁用树.zip"\n  ]\n}\n'
        order.write_text(original,encoding='utf-8')
        result=self.make_plan()
        rows={r['current']:r for r in result['rows'] if r['source']=='config/paxi/resourcepack_load_order.json'}
        broken=rows['探險者指南針結構漢化 v3.1.zip']
        self.assertEqual((broken['proposed'],broken['changed']),('探险者指南针结构汉化 v3.1.zip',True))
        self.assertEqual((rows['彩虹像素☆禁用树.zip']['origin'],rows['彩虹像素☆禁用树.zip']['changed']),('not_display',False))
        jobs.auto_confirm_safe(result)
        apply_session(result,self.home,lambda *_:None)
        self.assertEqual(order.read_text(encoding='utf-8'),original.replace('探險者指南針結構漢化','探险者指南针结构汉化'))
        self.assertFalse([r for r in self.make_plan()['rows'] if r.get('changed') and not r.get('installed')])  # a rerun writes nothing

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_simplified_chinese_in_quest_and_config_files_becomes_taiwan_wording(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        chapters=self.instance/'config/ftbquests/quests/chapters';chapters.mkdir(parents=True)
        quest=('{\n\tid: "0EE944EA56F99BC9"\n\ttitle: "第二章：乌鸦"\n\tquests: [{\n\t\tdescription: [\n'
               '\t\t\t"&a2.1章节&r的任务可以&a同时进行&r。"\n\t\t\t""\n\t\t\t"{image:a.png}"\n\t\t]\n'
               '\t\tsubtitle: "击杀巫法系生物"\n\t\ttitle: "吸引无数人前仆后继，也让巨龙成长"\n\t\ttasks: [{ id: "1", item: "minecraft:stone", count: 64L }]\n\t}]\n}\n')
        (chapters/'0EE944EA56F99BC9.snbt').write_text(quest,encoding='utf-8')
        backup=self.instance/'config/ftbquests/quests-backup/chapters';backup.mkdir(parents=True)
        (backup/'0EE944EA56F99BC9.snbt').write_text(quest,encoding='utf-8')  # never read by the game
        cfg=self.instance/'config/aom';cfg.mkdir(parents=True)
        (cfg/'events.json').write_text('{\n  "_comment": ["修改后需要重启游戏"],\n  "names": {"乌鸦": "乌鸦之王"},\n  "title": "乌鸦之王",\n  "id": "aom:crow"\n}\n',encoding='utf-8')
        scripts=self.instance/'kubejs/client_scripts';scripts.mkdir(parents=True)
        script="ItemEvents.tooltip(e => {\n  // 注释\n  e.add('aom:crow', Text.of('乌鸦的羽毛'))\n  let names = { '乌鸦': 1 }\n  e.add('aom:x', ok ? '开启' : '关闭')\n})\n"
        (scripts/'tips.js').write_text(script,encoding='utf-8')
        (cfg/'client.toml').write_text('# 注释：不用改\ntitle = "显示设置"\nid = \'aom:x\'\n',encoding='utf-8')
        (self.instance/'config/ysm/lang').mkdir(parents=True)
        (self.instance/'config/ysm/lang/zh_cn.json').write_text('{"tips": "为你而生"}',encoding='utf-8')  # that language's own file
        before={p:p.read_bytes() for p in (chapters/'0EE944EA56F99BC9.snbt',cfg/'events.json',cfg/'client.toml',scripts/'tips.js')}
        result=self.make_plan()
        rows=[r for r in result['rows'] if r['source'].startswith('config/')]
        self.assertFalse([r for r in rows if 'quests-backup' in r['source'] or 'ysm/lang' in r['source']])
        self.assertFalse([r for r in rows if not jobs.convertible(r) and jobs.row_state(r)=='candidate' and jobs.HAN.search(r['current'] or '')])
        jobs.auto_confirm_safe(result)
        done=apply_session(result,self.home,lambda *_:None)
        text=(chapters/'0EE944EA56F99BC9.snbt').read_text(encoding='utf-8')
        self.assertEqual(text,quest.replace('乌鸦','烏鴉').replace('章节','章節').replace('任务','任務').replace('同时进行','同時進行')
                         .replace('击杀巫法系生物','擊殺巫法系生物').replace('吸引无数人前仆后继，也让巨龙成长','吸引無數人前仆後繼，也讓巨龍成長'))
        # only the strings changed; layout, numbers and codes kept
        self.assertEqual((cfg/'events.json').read_text(encoding='utf-8'),
                         '{\n  "_comment": ["修改後需要重啟遊戲"],\n  "names": {"乌鸦": "烏鴉之王"},\n  "title": "烏鴉之王",\n  "id": "aom:crow"\n}\n')  # keys stay
        self.assertEqual((scripts/'tips.js').read_text(encoding='utf-8'),
                         script.replace("'乌鸦的羽毛'","'烏鴉的羽毛'").replace("'开启'","'開啟'").replace("'关闭'","'關閉'"))  # the object key stays
        self.assertEqual((cfg/'client.toml').read_text(encoding='utf-8'),'# 注释：不用改\ntitle = "顯示設定"\nid = \'aom:x\'\n')
        self.assertEqual((backup/'0EE944EA56F99BC9.snbt').read_text(encoding='utf-8'),quest)
        self.assertEqual((self.instance/'config/ysm/lang/zh_cn.json').read_text(encoding='utf-8'),'{"tips": "为你而生"}')
        applied=[r for r in done['rows'] if jobs.convertible(r) and r.get('installed')]
        self.assertTrue(applied and all(r['shown'] for r in applied),[(r['key'],r.get('shown')) for r in applied])
        # a second run writes nothing and keeps the label
        again=self.make_plan()
        loose=[r for r in again['rows'] if jobs.convertible(r)]
        self.assertFalse([r for r in loose if r['changed']])
        self.assertTrue(all(r['origin']=='same_source_zh_cn' and r.get('installed') for r in loose),[(r['key'],r['origin']) for r in loose])
        self.assertTrue(all(jobs.row_state(r)=='done' for r in loose))
        restore_backup(Path(done['backup']),self.instance)
        self.assertEqual({p:p.read_bytes() for p in before},before)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_crafttweaker_scripts_cfg_yaml_and_gun_packs_are_converted_in_place(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        scripts=self.instance/'scripts';scripts.mkdir()
        zs=('#priority 10\n// 注释：灵魂\n/* 说明\n   "块注释"\n*/\n'
            '<item:bhc:soul_heart_canister>.addTooltip("\\u00A7e魂心容器需灵魂项链佩戴，详见礼装章节");\n'
            'val names = {"灵魂": 1} as int[string];\n<item:a:b>.addTooltip("Plain English tip");\n')
        (scripts/'bhc.zs').write_text(zs,encoding='utf-8')
        cfg=self.instance/'config/apotheosis';cfg.mkdir(parents=True)
        names='# 名字\nnames {\n    S:"Names" <\n        双子座\n        Aries\n     >\n    S:title=狮子座\n}\n'
        (cfg/'names.cfg').write_text(names,encoding='utf-8')
        (self.instance/'config/fix.yaml').write_text('# 修改后需重启\nlabels:\n  attack: "攻击属性: "\n  id: "a:b"\n',encoding='utf-8')
        gun=self.instance/'tacz/[绝对彼方] pack';(gun/'assets/ocle/lang').mkdir(parents=True);(gun/'assets/ocle/display').mkdir(parents=True)
        (gun/'assets/ocle/lang/en_us.json').write_text(json.dumps({'ocle.gun.a.name':'Rifle'}),encoding='utf-8')
        (gun/'assets/ocle/lang/zh_cn.json').write_text(json.dumps({'ocle.gun.a.name':'步枪'},ensure_ascii=False),encoding='utf-8')
        (gun/'assets/ocle/lang/ja_jp.json').write_text(json.dumps({'ocle.gun.a.name':'ライフル'},ensure_ascii=False),encoding='utf-8')
        display='{"text_show": {"a": {"text": "天际军科|"}}, "identifier": "geometry.四叶十字"}'
        (gun/'assets/ocle/display/a.json').write_text(display,encoding='utf-8')
        before={p:p.read_bytes() for p in (scripts/'bhc.zs',cfg/'names.cfg',self.instance/'config/fix.yaml',gun/'assets/ocle/display/a.json')}
        result=self.make_plan()
        tip=next(r for r in result['rows'] if r['source']=='scripts/bhc.zs' and '魂心' in (r['current'] or ''))
        self.assertTrue(jobs.convertible(tip))
        gaps=[r for r in result['rows'] if r['kind']=='unsupported_config_text']
        self.assertEqual([(r['source'],r['current']) for r in gaps],[('config/apotheosis/names.cfg','Aries')])
        jobs.auto_confirm_safe(result)
        done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual((scripts/'bhc.zs').read_text(encoding='utf-8'),
                         zs.replace('"\\u00A7e魂心容器需灵魂项链佩戴，详见礼装章节"','"\\u00A7e魂心容器需靈魂項鍊佩戴，詳見禮裝章節"'))  # comments and keys stay
        self.assertEqual((cfg/'names.cfg').read_text(encoding='utf-8'),names.replace('双子座','雙子座').replace('狮子座','獅子座'))
        self.assertEqual((self.instance/'config/fix.yaml').read_text(encoding='utf-8'),'# 修改后需重启\nlabels:\n  attack: "攻擊屬性: "\n  id: "a:b"\n')
        self.assertEqual(json.loads((gun/'assets/ocle/lang/zh_tw.json').read_text(encoding='utf-8')),{'ocle.gun.a.name':'步槍'})
        self.assertEqual((gun/'assets/ocle/display/a.json').read_text(encoding='utf-8'),display.replace('天际军科','天際軍科'))
        self.assertEqual(done['shown_mismatch'],0)
        again=self.make_plan()
        self.assertFalse([r for r in again['rows'] if r.get('changed') and not r.get('installed') and jobs.HAN.search(r.get('current') or '')])
        restore_backup(Path(done['backup']),self.instance)
        self.assertEqual({p:p.read_bytes() for p in before},before)
        self.assertFalse((gun/'assets/ocle/lang/zh_tw.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_vaultpatcher_words_and_kubejs_template_text_are_converted_and_the_cache_is_cleared(self,_):
        # Elemental Awakening 2026-10-04: VaultPatcher modules swap a class's English for the author's Simplified
        # Chinese (未鉴定。), and a KubeJS tooltip was a template literal (`§9八系法术强度 +${group.bonus}%`); both
        # stayed Simplified. VaultPatcher also reuses its cached classes, so the cache of a changed module goes.
        from mc_zh_tw_translator import desktop_jobs as jobs
        modules=self.instance/'vaultpatcher/modules';modules.mkdir(parents=True)
        module=[{'name':'blades.jar','desc':'VP模块文件','mods':'blades.jar','authors':'someone','dynamic':False,'i18n':False},
                {'target_class':['com/blades/items/Ashes'],'pairs':[{'key':'Unidentified.','value':'未鉴定。'},
                                                                    {'key':'鉴定','value':'鉴定'}],'info':{'method':''}},
                {'target_class':['com/blades/Other'],'pairs':[{'key':'Hello','value':'Hello'}],'info':{'method':''}}]
        text=json.dumps(module,ensure_ascii=False,indent=2)
        (modules/'blades.json').write_text(text,encoding='utf-8')
        cache=self.instance/'vaultpatcher/cache/com/blades/items';cache.mkdir(parents=True)
        (cache/'Ashes.class').write_bytes(b'\xca\xfe\xba\xbe\x00\x00\x00\x34 \xe6\x9c\xaa\xe9\x89\xb4\xe5\xae\x9a')
        (cache/'Ashes.class.sha256').write_text('0'*64,encoding='utf-8')
        other=self.instance/'vaultpatcher/cache/com/blades/Other.class';other.write_bytes(b'\xca\xfe\xba\xbe')
        js=self.instance/'kubejs/client_scripts/food.js';js.parent.mkdir(parents=True,exist_ok=True)
        script="ItemEvents.tooltip(event => {\n  event.add(`kubejs:${id}`, [Text.blue(`§9八系法术强度 +${group.bonus}%`), Text.gray('食用后')])\n})\n"
        js.write_text(script,encoding='utf-8')
        kept={p:p.read_bytes() for p in (modules/'blades.json',cache/'Ashes.class',cache/'Ashes.class.sha256',js,other)}
        result=self.make_plan()
        rows=[r for r in result['rows'] if r['source'].startswith('vaultpatcher/')]
        # Only values are text: a key (the class's own words) and a value that is also some pair's key stay as they are.
        self.assertEqual([(r['key'],r['current']) for r in rows],[('[1, "pairs", 0, "value"]','未鉴定。')])
        self.assertTrue(jobs.convertible(rows[0]))
        jobs.auto_confirm_safe(result)
        done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual(json.loads((modules/'blades.json').read_text(encoding='utf-8'))[1]['pairs'],
                         [{'key':'Unidentified.','value':'未鑑定。'},{'key':'鉴定','value':'鉴定'}])
        self.assertEqual((modules/'blades.json').read_text(encoding='utf-8'),text.replace('"未鉴定。"','"未鑑定。"'))
        self.assertFalse((cache/'Ashes.class').exists());self.assertFalse((cache/'Ashes.class.sha256').exists())
        self.assertTrue(other.exists())  # its module entry did not change
        self.assertEqual(js.read_text(encoding='utf-8'),script.replace('八系法术强度','八系法術強度').replace('食用后','食用後'))
        self.assertEqual(done['shown_mismatch'],0)
        # VaultPatcher writes a new cache at the next start; that is never text of its own, and nothing is written again.
        cache.mkdir(parents=True,exist_ok=True);(cache/'Ashes.class').write_bytes(b'\xca\xfe\xba\xbe \xe6\x9c\xaa\xe9\x91\x91')
        again=self.make_plan()
        self.assertFalse([r for r in again['rows'] if r['source'].startswith('vaultpatcher/cache/')])
        self.assertFalse([r for r in again['rows'] if r.get('changed') and not r.get('installed') and jobs.HAN.search(r.get('current') or '')])
        (cache/'Ashes.class').unlink()
        restore_backup(Path(done['backup']),self.instance)
        self.assertEqual({p:p.read_bytes() for p in kept},kept)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_fancymenu_buttons_and_kubejs_window_title_are_converted_in_place(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        menu=self.instance/'config/fancymenu/customization';menu.mkdir(parents=True)
        layout=('type = fancymenu_layout\n\nlayout-meta {\n  identifier = 开始界面\n}\n\ncustomization {\n'
                '  action = addbutton\n  label = &e开始游戏\n  hoverlabel = "进入世界"\n  description = 请作者喝一杯%n%谢谢\n'
                '  source = [source:local]/config/fancymenu/assets/a.png\n}\n')
        (menu/'title_screen_layout.txt').write_text(layout,encoding='utf-8')
        props=self.instance/'kubejs/config';props.mkdir(parents=True)
        (props/'client.properties').write_text('#KubeJS Client Properties\nbackgroundColor=2E3440\ntitle=元素觉醒\n',encoding='utf-8')
        note=self.instance/'config/ymktn';note.mkdir(parents=True)
        welcome='## 当前版本说明\n## Current Version Notes\n\n本整合包目前还在持续更新中！  \nThis modpack is still updated.\n'
        (note/'welcome.txt').write_text(welcome,encoding='utf-8')
        (note/'notice.txt').write_text('该目录会在每次游戏启动时清空！\n',encoding='utf-8')  # a note for people, recreated by the mod
        (note/'blacklist.txt').write_text('# 黑名单说明\nwine_fox\n',encoding='utf-8')  # Chinese only in comments: a settings file
        before={p:p.read_bytes() for p in (menu/'title_screen_layout.txt',props/'client.properties',note/'welcome.txt',note/'notice.txt')}
        result=self.make_plan()
        gaps=[r for r in result['rows'] if r['kind']=='unsupported_config_text']
        self.assertEqual([(r['source'],r['current']) for r in gaps],[('config/ymktn/welcome.txt','This modpack is still updated.')])
        unverified={r['source'] for r in result['rows'] if r.get('unverified')}
        self.assertEqual(unverified,{'config/ymktn/welcome.txt'})  # FancyMenu and KubeJS are known readers
        jobs.auto_confirm_safe(result);done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual((menu/'title_screen_layout.txt').read_text(encoding='utf-8'),
                         layout.replace('&e开始游戏','&e開始遊戲').replace('"进入世界"','"進入世界"').replace('请作者喝一杯%n%谢谢','請作者喝一杯%n%謝謝'))
        self.assertEqual((props/'client.properties').read_text(encoding='utf-8'),'#KubeJS Client Properties\nbackgroundColor=2E3440\ntitle=元素覺醒\n')
        self.assertEqual((note/'welcome.txt').read_text(encoding='utf-8'),
                         welcome.replace('当前版本说明','當前版本說明').replace('本整合包目前还在持续更新中！','本整合包目前還在持續更新中！'))
        self.assertEqual((note/'notice.txt').read_text(encoding='utf-8'),'该目录会在每次游戏启动时清空！\n')
        self.assertEqual((note/'blacklist.txt').read_text(encoding='utf-8'),'# 黑名单说明\nwine_fox\n')
        self.assertEqual(done['shown_mismatch'],0)
        self.assertFalse([r for r in self.make_plan()['rows'] if r.get('changed') and not r.get('installed')])
        restore_backup(Path(done['backup']),self.instance)
        self.assertEqual({p:p.read_bytes() for p in before},before)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_text_in_a_folder_no_reader_covers_is_converted_or_listed_not_lost(self,_):
        import zipfile
        from mc_zh_tw_translator import desktop_jobs as jobs
        other=self.instance/'mystery_mod';(other/'lang').mkdir(parents=True)
        quests='{"title": "龙之试炼", "id": "a", "model": "geometry.四叶十字", "tip": "开启传送门"}'
        (other/'hints.json').write_text('{"hint": "开启传送门，需要钥匙。"}',encoding='utf-8')  # a sentence under an unknown field
        (other/'quests.json').write_text(quests,encoding='utf-8')
        (other/'lang/en_us.json').write_text('{"a.trial": "Dragon trial", "a.cn": "Only Chinese"}',encoding='utf-8')
        (other/'lang/zh_cn.json').write_text('{"a.cn": "只有简中"}',encoding='utf-8')
        (other/'lang/ja_jp.json').write_text('{"a": "竜の試練"}',encoding='utf-8')  # another language
        (other/'readme.txt').write_text('作者的说明',encoding='utf-8')
        (other/'page.xml').write_text('<page>龙之试炼</page>\n',encoding='utf-8')  # Chinese outside quotes: listed
        (other/'names.yaml').write_text('boss: "暗影龙"\n',encoding='utf-8')
        (self.instance/'logs').mkdir();(self.instance/'logs/latest.log').write_text('载入完成',encoding='utf-8')
        world=self.instance/'saves/w/data';world.mkdir(parents=True);(world/'shop.json').write_text('{"title": "商店分类"}',encoding='utf-8')
        # A mod whose program holds the same Chinese: it may compare with it, so that string stays.
        (self.instance/'mods').mkdir()
        with zipfile.ZipFile(self.instance/'mods/boss.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="boss"\n')
            z.writestr('a/Boss.class',b'\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x03\x01\x00\x09'+'暗影龙'.encode('utf-8')+b'\x01\x00\x01x')
        before={p:p.read_bytes() for p in (other/'quests.json',other/'names.yaml',world/'shop.json')}
        result=self.make_plan()
        red=sorted(r['source'] for r in result['rows'] if r['kind']=='unsupported_config_text')
        self.assertEqual(red,['mystery_mod/hints.json','mystery_mod/page.xml'])
        self.assertIn('有 2 個檔案',jobs.unsupported_note(result));self.assertIn('page.xml',jobs.unsupported_note(result))
        unverified=[r for r in result['rows'] if r.get('unverified')]
        self.assertTrue(unverified and all(jobs.row_state(r)=='candidate' for r in unverified))  # never counted
        self.assertFalse([r for r in result['rows'] if r['source'].startswith('saves/')])
        jobs.auto_confirm_safe(result);done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual((other/'quests.json').read_text(encoding='utf-8'),quests.replace('龙之试炼','龍之試煉'))  # model name and tip stay
        self.assertEqual((other/'names.yaml').read_text(encoding='utf-8'),'boss: "暗影龙"\n')
        self.assertEqual(json.loads((other/'lang/zh_tw.json').read_text(encoding='utf-8')),{'a.cn':'只有簡中'})
        self.assertEqual((world/'shop.json').read_text(encoding='utf-8'),'{"title": "商店分类"}')
        self.assertIn('2 句簡體轉成繁體或補上繁中語系檔',jobs.unverified_note(done))
        self.assertEqual(jobs.unsupported_note(dict(rows=[])),'')
        again=self.make_plan()
        self.assertFalse([r for r in again['rows'] if r.get('changed') and not r.get('installed')])
        restore_backup(Path(done['backup']),self.instance)
        self.assertEqual({p:p.read_bytes() for p in before},before);self.assertFalse((other/'lang/zh_tw.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_patchouli_book_name_and_landing_text_go_into_the_pack_as_language_entries(self,_):
        import zipfile
        from mc_zh_tw_translator import desktop_jobs as jobs
        (self.instance/'mods').mkdir()
        (self.instance/'options.txt').write_text('lang:zh_tw\n',encoding='utf-8')
        landing='A Guide to weapon crafting.$(br2)(Entries created with help)'
        with zipfile.ZipFile(self.instance/'mods/simplyswords.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="simplyswords"\n')
            z.writestr('assets/simplyswords/lang/en_us.json',json.dumps({'item.simplyswords.a':'Sword'}))
            z.writestr('data/simplyswords/patchouli_books/runic_grimoire/book.json',
                       json.dumps({'name':'Runic Grimoire','landing_text':landing,'model':'simplyswords:book'}))
        # CurseForge would put a changed jar back: the pack is the only place this text can go.
        (self.instance/'minecraftinstance.json').write_text(json.dumps({'installedAddons':[
            {'installedFile':{'fileName':'simplyswords.jar','fileNameOnDisk':'simplyswords.jar'}}]}),encoding='utf-8')
        result=self.make_plan()
        book=[r for r in result['rows'] if r['source'].endswith('book.json')]
        self.assertEqual(sorted(r['key'] for r in book),['["landing_text"]','["name"]'])
        cf=jobs.is_curseforge(self.instance)
        self.assertTrue(all(jobs.write_route(r,cf)=='pack' and r['supported'] for r in book))
        self.assertTrue(all(jobs.row_state(r,cf)=='missing' for r in book))  # a gap AI can fill, not an unknown
        chosen={'["name"]':'符文魔典','["landing_text"]':'武器打造指南。$(br2)（條目由 AI 協助撰寫）'}
        for r in book:r.update(proposed=chosen[r['key']],origin='manual',supported=True,reviewed=True,changed=True)
        done=apply_session(result,self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            lang=json.loads(z.read('assets/simplyswords/lang/zh_tw.json'))
        self.assertEqual((lang['Runic Grimoire'],lang[landing]),(chosen['["name"]'],chosen['["landing_text"]']))
        with zipfile.ZipFile(self.instance/'mods/simplyswords.jar') as z:  # the mod itself untouched
            self.assertEqual(json.loads(z.read('data/simplyswords/patchouli_books/runic_grimoire/book.json'))['name'],'Runic Grimoire')
        rows=[r for r in done['rows'] if r['source'].endswith('book.json')]
        self.assertTrue(all(r.get('installed') and r.get('shown') for r in rows),[(r['key'],r.get('shown')) for r in rows])
        again=[r for r in self.make_plan()['rows'] if r['source'].endswith('book.json')]  # a rerun sees the pack's text
        self.assertEqual(sorted(r['current'] for r in again),sorted(chosen.values()))
        self.assertTrue(all(jobs.row_state(r,cf)=='done' and not r.get('changed') for r in again))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_binary_shop_data_and_cache_are_converted_backed_up_and_read_back(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        from full_translation_audit import parse_binary_nbt
        import struct

        def text(value):
            value=value.encode('utf-8');return struct.pack('>H',len(value))+value
        def named(tag,name,payload):return bytes([tag])+text(name)+payload
        def compound(fields):return b''.join(fields)+b'\0'
        tab=compound([named(8,'title',text('货币兑换')),named(3,'sort',struct.pack('>i',7)),
                      named(8,'icon',text('minecraft:emerald'))])
        entry=compound([named(6,'price',struct.pack('>d',12.5)),named(4,'count',struct.pack('>q',64)),
                        named(8,'item',text('minecraft:diamond')),
                        named(9,'tooltip_list',bytes([8])+struct.pack('>i',1)+text('购买64个钻石'))])
        original=named(10,'',compound([
            named(9,'shop_tabs',bytes([10])+struct.pack('>i',1)+tab),
            named(9,'shop_entries',bytes([10])+struct.pack('>i',1)+entry)]))
        shops=self.instance/'config/SDMShop/shops';cache=self.instance/'config/SDMShop/cache/server-id'
        shops.mkdir(parents=True);cache.mkdir(parents=True)
        files=(shops/'shop.data',cache/'shop.cache')
        for p in files:p.write_bytes(original)
        unknown=self.instance/'config/AnotherShop/catalog.xml';unknown.parent.mkdir(parents=True)
        unknown.write_text('<shop category="Limited Offers">\n  <tab>货币兑换</tab>\n</shop>\n',encoding='utf-8')

        result=self.make_plan()
        rows=[r for r in result['rows'] if r.get('kind')=='binary_config_candidate']
        self.assertEqual({r['source'] for r in rows},{'config/SDMShop/shops/shop.data','config/SDMShop/cache/server-id/shop.cache'})
        self.assertEqual({r['current'] for r in rows},{'货币兑换','购买64个钻石'})
        unsupported=next(r for r in result['rows'] if r.get('kind')=='unsupported_config_text')
        self.assertEqual(unsupported['source'],'config/AnotherShop/catalog.xml')
        self.assertFalse(unsupported['supported']);self.assertIn('格式尚未支援',unsupported['issue'])
        jobs.auto_confirm_safe(result);done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual(done['shown_mismatch'],0)
        for p in files:
            raw=p.read_bytes();data=parse_binary_nbt(raw)
            self.assertEqual(data['shop_tabs'][0],{'title':'貨幣兌換','sort':7,'icon':'minecraft:emerald'})
            self.assertEqual(data['shop_entries'][0],{'price':12.5,'count':64,'item':'minecraft:diamond',
                                                       'tooltip_list':['購買64個鑽石']})
            # Apart from the two length-prefixed UTF-8 string payloads, every byte is identical.
            reverted=raw.replace(text('貨幣兌換'),text('货币兑换')).replace(text('購買64個鑽石'),text('购买64个钻石'))
            self.assertEqual(reverted,original)
        applied=[r for r in done['rows'] if r.get('kind')=='binary_config_candidate' and r.get('installed')]
        self.assertTrue(applied and all(r.get('shown') for r in applied))

        again=self.make_plan();binary=[r for r in again['rows'] if r.get('kind')=='binary_config_candidate']
        self.assertTrue(binary);self.assertFalse([r for r in binary if r.get('changed')])
        self.assertTrue(all(r['origin']=='same_source_zh_cn' and r.get('installed') for r in binary))
        restore_backup(Path(done['backup']),self.instance)
        self.assertTrue(all(p.read_bytes()==original for p in files))

    def test_archive_rewrite_tolerates_overlapping_empty_directory_metadata(self):
        from mc_zh_tw_translator.desktop_jobs import rewrite_archive
        import struct, zipfile
        source=Path(self.temp.name)/'overlap.jar';target=Path(self.temp.name)/'rewritten.jar'
        with zipfile.ZipFile(source,'w') as z:
            z.writestr('META-INF/',b'');z.writestr('assets/demo.txt',b'old');z.writestr('keep.bin',b'keep')
        raw=bytearray(source.read_bytes());central=raw.index(b'PK\x01\x02')
        raw[central+20:central+24]=struct.pack('<I',1000)  # only the empty directory appears to overlap
        source.write_bytes(raw)
        with zipfile.ZipFile(source) as z:
            with self.assertRaises(zipfile.BadZipFile):z.read('META-INF/')
            rewrite_archive(z,target,{'assets/demo.txt':b'new'},'overlap.jar')
        with zipfile.ZipFile(target) as z:
            self.assertEqual((z.read('assets/demo.txt'),z.read('keep.bin')),(b'new',b'keep'))
            self.assertIsNone(z.testzip())

    def test_scan_cache_reuses_unchanged_archives(self):
        from mc_zh_tw_translator import desktop_jobs as jobs
        self.make_mod();first=self.make_plan()
        with patch.object(jobs.Audit,'archive',side_effect=AssertionError('should use cache')):
            second=self.make_plan()
        self.assertEqual(len(first['rows']),len(second['rows']))

    def test_internal_strings_and_user_terms(self):
        from mc_zh_tw_translator.desktop_jobs import internal_reason, UserGlossary, conflicting_terms, apply_term
        for text in ('Loading config for {}','getValue()','com.example.Foo','CONFIG_KEY','x->y'):
            self.assertTrue(internal_reason(text),text)
        self.assertEqual(internal_reason('Right-click to open the menu'),'')
        terms=UserGlossary(self.home);terms.set('Benimaru','紅丸')
        self.assertEqual(UserGlossary(self.home).lookup('benimaru'),'紅丸')
        self.assertEqual(UserGlossary(self.home).terms_in('Benimaru Boss'),{'Benimaru':'紅丸'})
        row=lambda zh,origin='same_source_zh_cn',key='entity.a.direwolf':dict(en='Direwolf',proposed=zh,origin=origin,supported=True,
                                                                              current=None,key=key,source='s')
        session=dict(rows=[row('牙狼族'),row('牙狼族'),dict(row('恐狼','reference_pack_or_cfpa'),evidence='reference:tw'),row('无','same_source_zh_cn','gui.a.none')])
        conflict=conflicting_terms(session)[0]
        self.assertEqual(conflict['suggested'],'恐狼')  # a more trusted source beats a larger count
        self.assertEqual(len(conflicting_terms(session)),1)  # UI words (gui.*) are never listed
        self.assertEqual(apply_term(session,'Direwolf','恐狼'),3)
        self.assertEqual([r['proposed'] for r in session['rows']],['恐狼','恐狼','恐狼','无'])

    def test_source_order_prefers_people_written_taiwan_chinese(self):
        from mc_zh_tw_translator.desktop_jobs import UserGlossary
        (self.lang/'en_us.json').write_text(json.dumps({'demo.a':'Settings','demo.b':'Quality','demo.c':'Mode','demo.d':'Hello %s'}),encoding='utf-8')
        (self.lang/'zh_tw.json').write_text(json.dumps({'demo.a':'設定值','demo.b':'品質'}),encoding='utf-8')
        (self.lang/'zh_cn.json').write_text(json.dumps({'demo.a':'设置','demo.b':'质量','demo.c':'模式','demo.d':'你好 %s'}),encoding='utf-8')
        tw={'demo':{'demo.a':'設定','demo.c':'舊模式'},
            '__pairs__':{'demo':{'demo.a':[('設定','Settings')],'demo.c':[('舊模式','Old Mode')]}}}
        UserGlossary(self.home).set('Hello %s','哈囉 %s')
        result=plan(self.instance,self.home,lambda *_:None,references=([tw,{}],{'sources':['tw','cn']}))
        rows={r['key']:r for r in result['rows']}
        # Reference zh_tw whose English matches this version beats the mod's own zh_tw.
        self.assertEqual((rows['demo.a']['origin'],rows['demo.a']['proposed']),('reference_pack_or_cfpa','設定'))
        self.assertNotIn('demo.b',rows)  # the mod's own correct zh_tw stays as it is
        # Reference zh_tw written for different English only comes after the converted zh_cn.
        self.assertEqual((rows['demo.c']['origin'],rows['demo.c']['proposed']),('same_source_zh_cn','模式'))
        self.assertEqual(rows['demo.d']['origin'],'user_glossary')  # the user's own decision comes first

    def test_source_order_uses_memory_and_rejects_simplified_zh_tw(self):
        from mc_zh_tw_translator.desktop_jobs import TranslationMemory
        (self.lang/'zh_tw.json').write_text(json.dumps({'demo.hello':'你好 %s','demo.missing':'未知设置'}),encoding='utf-8')
        TranslationMemory(self.home).remember('demo','demo.missing','Unknown text','未知的文字','test')
        rows={r['key']:r for r in self.make_plan()['rows']}
        # A correct zh_tw needs no change; a zh_tw with simplified characters yields to memory.
        self.assertNotIn('demo.hello',rows)
        self.assertEqual((rows['demo.missing']['origin'],rows['demo.missing']['proposed']),('translation_memory','未知的文字'))

    def test_discover_instances_from_launcher_and_recent_paths(self):
        from mc_zh_tw_translator.desktop_jobs import discover_instances
        home=Path(self.temp.name)/'home';pack=home/'curseforge/minecraft/Instances/Pack A';(pack/'mods').mkdir(parents=True)
        (home/'curseforge/minecraft/Instances/not-a-pack').mkdir()
        with patch('pathlib.Path.home',return_value=home),patch.dict('os.environ',{'APPDATA':str(home/'none'),'LOCALAPPDATA':str(home/'local')}),patch('mc_zh_tw_translator.full_pack.system_curseforge_data_roots',return_value=[]):
            found=discover_instances([str(self.instance),'C:/missing/path'])
        self.assertEqual([(l,n) for l,n,_ in found],[('最近使用',self.instance.name),('CurseForge','Pack A')])

    def test_keep_original_only_for_unambiguous_strings(self):
        from mc_zh_tw_translator.desktop_jobs import keep_original_reason as keep
        for text in ('%s','%d (%dx)','%1$s HPS','%d FE','VI','64 x 64','Shift','Ctrl + Shift','NBT','https://example.com/a'):
            self.assertTrue(keep(text),text)
        for text in ('Roomopolis','WIP Chicken','Time and Essence','%s Mana','MIX','OK','Click'):
            self.assertEqual(keep(text),'',text)
        self.assertEqual(keep('%s%s/t'),'數值單位')
        for text in ('FE/RF/μI/CF','bar','°C','%dmB','Beta'):self.assertTrue(keep(text),text)
        self.assertEqual(keep('Bar Stool'),'')
        for text in ('Patreon','§lFPS:§r %s','§lGPU:§r %1$s (OpenGL: %2$s)','EP: %s/%s','X: %d / Y: %d / Z: %d','Ctrl Shift %s',
                     'IF (%s)','#name','/jech [profile]','config/inventoryprofilesnext','minecraft:entity.pig','facing=north,half=upper',
                     'dde9f4','En�d'):
            self.assertTrue(keep(text),text)
        self.assertTrue(keep('Friends&Foes','','friendsandfoes'));self.assertTrue(keep('Cloth Config Wiki','','cloth-config2'))
        self.assertTrue(keep('HexaBlu','magic_painting.twilightforest.x.author'))
        for text in ('Not','Mod ID','on/off','Minecraft Logo','Default','Enable BlueMap Support','Inv','Search...'):
            self.assertEqual(keep(text),'',text)
        # Key context: credits, songs, comments and mod names are kept; ordinary player text is not.
        self.assertTrue(keep('Binke - Moonlight','jukebox_song.eternal_starlight.moonlight'))
        self.assertTrue(keep('TohokuAlpha','painting.eternal_starlight.power.author'))
        self.assertTrue(keep('Machinery texts.','_comment.data_tablet'))
        self.assertTrue(keep('Allium cepa','tooltip.productivefarming.onion.latin'))
        self.assertTrue(keep('Abundant Atmosphere','itemGroup.abundant_atmosphere','abundant_atmosphere'))
        self.assertEqual(keep('Bygone Nether','itemGroup.eternalnethertab','eternalnether'),'')
        self.assertEqual(keep('Absolute Zero','painting.eternal_starlight.absolute_zero.title'),'')

    def test_detect_version_and_preserve_parameters(self):
        self.assertEqual(minecraft_version(self.instance),'1.21.1')
        self.assertTrue(validate_text('§aHello %s','§a你好 %s'))
        self.assertFalse(validate_text('§aHello %s','你好 %d'))
        self.assertFalse(validate_text('One\nTwo','一二'))

    def test_plan_does_not_write_instance_or_claim_review(self):
        result=self.make_plan()
        self.assertFalse((self.lang/'zh_tw.json').exists())
        self.assertEqual(result['status'],'needs_review')
        self.assertFalse(any(r['reviewed'] for r in result['rows']))
        self.assertTrue(any(r['origin']=='untranslated' for r in result['rows']))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_apply_only_reviewed_and_restore_new_file(self,_):
        result=self.make_plan()
        row=next(r for r in result['rows'] if r['key']=='demo.hello');row['reviewed']=True
        done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual(json.loads((self.lang/'zh_tw.json').read_text(encoding='utf-8')),{'demo.hello':'你好 %s'})
        self.assertEqual(done['installed_count'],1)
        restore_backup(Path(done['backup']),self.instance)
        self.assertFalse((self.lang/'zh_tw.json').exists())
        self.assertTrue((self.lang/'en_us.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_malformed_mod_zh_tw_is_rebuilt_and_parameters_are_not_gaps(self,_):
        import zipfile
        mods=self.instance/'mods';mods.mkdir()
        with zipfile.ZipFile(mods/'lights.jar','w') as z:
            z.writestr('assets/lights/lang/en_us.json',json.dumps({'a.mode':'Mode','a.fmt':'%s','a.key':'Shift'}))
            z.writestr('assets/lights/lang/zh_cn.json',json.dumps({'a.mode':'模式'}))
            z.writestr('assets/lights/lang/zh_tw.json','{\n "a.mode": "模式"\n "a.fmt": "%s"\n}')  # missing comma
        result=self.make_plan()
        self.assertEqual(result['errors'],[]);self.assertEqual(len(result['repairs']),1)
        rows={r['key']:r for r in result['rows'] if r['source'].startswith('mods/')}
        self.assertEqual(rows['a.mode']['proposed'],'模式')
        # Kept as-is: listed under 無需翻譯, never counted as missing and never written.
        for key in ('a.fmt','a.key'):
            self.assertEqual(rows[key]['origin'],'keep_original');self.assertFalse(rows[key]['changed'])
        self.assertGreaterEqual(result['source_counts'].get('keep_original',0),2)
        rows['a.mode']['reviewed']=True
        apply_session(result,self.home,lambda *_:None)
        # The resource pack holds a readable zh_tw above the mod's broken one; the mod itself is left as it was.
        self.assertEqual(json.loads(self.pack()['assets/lights/lang/zh_tw.json']),{'a.mode':'模式'})

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_mod_font_without_chinese_keeps_english(self,_):
        # Essential draws its screens with a font of English characters only; Chinese shows as boxes.
        import zipfile
        mods=self.instance/'mods';mods.mkdir()
        with zipfile.ZipFile(mods/'essential.jar','w') as z:
            z.writestr('assets/essential/lang/en_us.json',json.dumps({'e.friends':'Friends','e.group':'Group Created'}))
            z.writestr('assets/essential/lang/zh_cn.json',json.dumps({'e.friends':'好友'}))
            z.writestr('assets/essential/lang/zh_tw.json',json.dumps({'e.group':'已建立群組'}))  # e.g. written by an earlier run
            ascii_font={'atlas':{'width':1},'glyphs':[{'unicode':c} for c in range(32,127)]}
            z.writestr('fonts/Minecraft-Regular.json',json.dumps(ascii_font))
        with zipfile.ZipFile(mods/'lights.jar','w') as z:  # a font with Chinese glyphs changes nothing
            z.writestr('assets/lights/lang/en_us.json',json.dumps({'l.on':'On'}))
            z.writestr('assets/lights/lang/zh_cn.json',json.dumps({'l.on':'开'}))
            z.writestr('fonts/Round.json',json.dumps({'atlas':{},'glyphs':[{'unicode':65},{'unicode':0x958B}]}))
        result=self.make_plan()
        rows={r['key']:r for r in result['rows'] if r['source'].startswith('mods/')}
        self.assertEqual(rows['e.friends']['origin'],'keep_original');self.assertFalse(rows['e.friends']['changed'])
        self.assertEqual(rows['e.friends']['proposed'],'Friends')
        self.assertTrue(rows['e.group']['changed']);self.assertEqual(rows['e.group']['proposed'],'Group Created')
        self.assertIn('改回英文',rows['e.group']['issue'])
        self.assertIn('fonts/Minecraft-Regular.json',rows['e.friends']['evidence'])
        self.assertEqual(rows['l.on']['proposed'],'開')
        for row in result['rows']:row['reviewed']=True
        apply_session(result,self.home,lambda *_:None)
        self.assertEqual(json.loads(self.pack()['assets/essential/lang/zh_tw.json'])['e.group'],'Group Created')
        again=self.make_plan()
        self.assertFalse(any(r['changed'] for r in again['rows'] if r['source'].startswith('mods/')))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_abbreviation_kept_by_mod_translators_stays(self,_):
        # Cobblemon's zh_tw keeps "Lv." like the Taiwan games; AI's 等級 did not fit the box drawn for "Lv.2".
        import zipfile
        from mc_zh_tw_translator.desktop_jobs import author_kept, KEPT_BY_AUTHOR
        mods=self.instance/'mods';mods.mkdir()
        en={'ui.lv':'Lv.','ui.lv.n':'Lv.%1$s','ui.hp':'HP','ui.done':'Done','ui.ok':'OK','ui.name':'Party'}
        with zipfile.ZipFile(mods/'cobble.jar','w') as z:
            z.writestr('assets/cobble/lang/en_us.json',json.dumps(en))
            z.writestr('assets/cobble/lang/zh_cn.json',json.dumps({'ui.lv':'Lv.','ui.lv.n':'Lv.%1$s','ui.hp':'HP','ui.done':'Done',
                                                                  'ui.ok':'确定','ui.name':'队伍'}))
            z.writestr('assets/cobble/lang/zh_tw.json',json.dumps({'ui.lv':'Lv. ','ui.lv.n':'Lv.%1$s','ui.hp':'HP','ui.done':'Done',
                                                                  'ui.ok':'OK','ui.name':'隊伍','ui.a':'一','ui.b':'二','ui.c':'三','ui.d':'四','ui.e':'五','ui.f':'六'}))
        with zipfile.ZipFile(mods/'copy.jar','w') as z:  # a zh_tw that is only a copy of the English keeps nothing
            z.writestr('assets/copy/lang/en_us.json',json.dumps({'c.hp':'HP','c.go':'Go now'}))
            z.writestr('assets/copy/lang/zh_cn.json',json.dumps({'c.hp':'HP','c.go':'现在走'}))
            z.writestr('assets/copy/lang/zh_tw.json',json.dumps({'c.hp':'HP','c.go':'Go now'}))
        result=self.make_plan()
        rows={r['key']:r for r in result['rows'] if r['source'].startswith('mods/')}
        for key in ('ui.lv','ui.lv.n','ui.hp'):
            self.assertEqual(rows[key]['origin'],'keep_original',key);self.assertFalse(rows[key]['changed'],key)
        self.assertEqual(rows['ui.lv']['proposed'],'Lv. ')
        self.assertNotEqual(rows['ui.done']['origin'],'keep_original')  # a word both translators left is still translated
        self.assertNotEqual(rows['ui.ok']['origin'],'keep_original')  # zh_cn has Chinese: not kept by both
        self.assertNotEqual(rows['c.hp'].get('evidence'),KEPT_BY_AUTHOR)
        self.assertTrue(author_kept('%s mB','%s mB','%s mB'));self.assertTrue(author_kept('IV','IV','IV'))
        for word in ('Fox','Sand','Done'):self.assertFalse(author_kept(word,word,word),word)
        self.assertFalse(author_kept('HP','HP',None))
        # An earlier run's 等級 in the translation pack goes back to the author's Lv. once.
        (self.instance/'resourcepacks').mkdir(exist_ok=True)
        with zipfile.ZipFile(self.instance/'resourcepacks/MCTranslator-zh_tw.zip','w') as z:
            z.writestr('assets/cobble/lang/zh_tw.json',json.dumps({'ui.lv':'等級','ui.name':'隊伍'}))
        again={r['key']:r for r in self.make_plan()['rows'] if r['source'].startswith('mods/')}
        self.assertEqual((again['ui.lv']['origin'],again['ui.lv']['proposed']),('keep_original','Lv. '))
        self.assertTrue(again['ui.lv']['changed'])
        session=self.make_plan()
        for row in session['rows']:row['reviewed']=True
        apply_session(session,self.home,lambda *_:None)
        self.assertEqual(json.loads(self.pack()['assets/cobble/lang/zh_tw.json'])['ui.lv'],'Lv. ')
        self.assertFalse(any(r['changed'] for r in self.make_plan()['rows'] if r['key'].startswith('ui.lv')))

    def test_menu_buttons_drawn_as_pictures_are_explained(self):
        from mc_zh_tw_translator.desktop_jobs import image_menus, image_text_note
        layouts=self.instance/'config/fancymenu/customization';layouts.mkdir(parents=True)
        (layouts/'labels.txt').write_text('element {\n  label = 開始遊戲\n  backgroundnormal = [source:local]config/fancymenu/buttons/plain.png\n}\n',encoding='utf-8')
        self.assertEqual(image_menus(self.instance),[])  # a picture behind a text label: the label is translated
        (layouts/'main.txt').write_text('element {\n  source = [source:local]config/fancymenu/assets/menu/fall/buttons/main_single.png\n}\n',encoding='utf-8')
        self.assertEqual(image_menus(self.instance),['main.txt'])
        self.assertIn('圖片',image_text_note(dict(image_menus=['main.txt'])));self.assertEqual(image_text_note({}),'')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_changed_source_refuses_apply(self,_):
        result=self.make_plan()
        next(r for r in result['rows'] if r['key']=='demo.hello')['reviewed']=True
        (self.lang/'en_us.json').write_text('{"demo.hello":"Changed %s"}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'掃描後有變動'):apply_session(result,self.home,lambda *_:None)
        self.assertFalse((self.lang/'zh_tw.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_restore_refuses_user_changes(self,_):
        result=self.make_plan();next(r for r in result['rows'] if r['key']=='demo.hello')['reviewed']=True
        done=apply_session(result,self.home,lambda *_:None)
        (self.lang/'zh_tw.json').write_text('user edit',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'後來有修改'):restore_backup(Path(done['backup']),self.instance)
        self.assertEqual((self.lang/'zh_tw.json').read_text(),'user edit')

    @patch('mc_zh_tw_translator.desktop_jobs.refresh',side_effect=ValueError('offline'))
    def test_preflight_failure_is_blocked(self,_):
        result=plan(self.instance,self.home,lambda *_:None)
        self.assertEqual(result['status'],'blocked')
        self.assertTrue((Path(result['report'])/'session.json').exists())
        self.assertTrue(result['rows'])

    @patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{}))
    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed',side_effect=GameRunningError('close game'))
    def test_one_click_block_keeps_report_and_can_retry(self,guard,_):
        snapshots=[]
        result=full_translation(self.instance,self.home,None,lambda *_:None,
                                checkpoint=lambda s:snapshots.append(json.loads(json.dumps(s))))
        self.assertEqual(result['status'],'awaiting_game')
        self.assertTrue(result['rows']);self.assertFalse((self.lang/'zh_tw.json').exists())
        self.assertEqual(snapshots[0]['status'],'scanning')
        self.assertTrue(any(s['status']=='references' and s['rows'] for s in snapshots))
        saved=json.loads((Path(result['report'])/'session.json').read_text(encoding='utf-8'))
        guard.side_effect=None
        apply_session(saved,self.home,lambda *_:None)
        self.assertTrue((self.lang/'zh_tw.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{}))
    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_ai_pause_still_applies_everything_else(self,*_):
        def paused(session,*args,**kwargs):
            session.update(ai_status='paused',ai_message='quota');return session
        with patch('mc_zh_tw_translator.codex_bridge.pending_rows',return_value=[1]),\
             patch('mc_zh_tw_translator.codex_bridge.supplement',side_effect=paused):
            result=full_translation(self.instance,self.home,'some-model',lambda *_:None)
        self.assertEqual((result['status'],result['ai_status']),('installed','paused'))
        self.assertEqual(json.loads((self.lang/'zh_tw.json').read_text(encoding='utf-8'))['demo.hello'],'你好 %s')

    @patch('mc_zh_tw_translator.desktop_jobs.refresh',side_effect=InterruptedError('stopped'))
    def test_cancel_during_preflight_keeps_scan_without_applying(self,_):
        result=full_translation(self.instance,self.home,None,lambda *_:None)
        self.assertEqual(result['status'],'cancelled');self.assertTrue(result['rows'])
        self.assertFalse((self.lang/'zh_tw.json').exists())

    def test_server_and_other_absolute_game_dir_do_not_block(self):
        instance=Path('C:/Games/Pack')
        for command in ('java cpw.mods.bootstraplauncher.BootstrapLauncher --launchTarget forgeserver',
                        'java net.minecraft.client.main.Main --gameDir "C:/Games/Other Pack"'):
            self.assertIsNone(game_process_blocker(instance,[dict(ProcessId=10,CommandLine=command)]))
        for command in ('java minecraft --gameDir "C:/Games/Pack"','java modlauncher',None):
            self.assertIn('10',game_process_blocker(instance,[dict(ProcessId=10,CommandLine=command)]))
        forge=dict(ProcessId=10,CommandLine='java @libraries/net/minecraftforge/forge/1.20.1/win_args.txt',
                   cwd='C:/Servers/Vanilla',server_target=True)
        self.assertIsNone(game_process_blocker(instance,[forge]))
        forge['cwd']=str(instance)
        self.assertIsNotNone(game_process_blocker(instance,[forge]))
        # The Fabric server 建立伺服器 makes (run.bat: -jar fabric-server-launch.jar) in its own folder.
        fabric=dict(ProcessId=10,CommandLine='java.exe @user_jvm_args.txt -jar fabric-server-launch.jar',cwd='C:/Servers/Pack')
        self.assertIsNone(game_process_blocker(instance,[fabric]))
        fabric['cwd']=str(instance)
        self.assertIsNotNone(game_process_blocker(instance,[fabric]))


class UpdateTests(unittest.TestCase):
    def test_version_order(self):
        self.assertGreater(version_tuple('v0.10.0'),version_tuple('0.9.9'))
        with self.assertRaises(ValueError):version_tuple('latest')

    def test_check_only_does_not_download(self):
        client=Mock();reply=Mock(status_code=200)
        reply.json.return_value=dict(tag_name='v9.0.0',body='New',assets=[dict(name='MCTranslator.exe',size=100,digest='sha256:'+'a'*64,browser_download_url='https://github.com/siang86121900/mc-zh-tw-translator/releases/download/v9.0.0/MCTranslator.exe')])
        client.get.return_value=reply
        info=check_update(client)
        self.assertEqual(info['status'],'available');self.assertEqual(client.get.call_count,1)

    def test_missing_release_not_claimed_latest(self):
        client=Mock();client.get.return_value.status_code=404
        self.assertEqual(check_update(client)['status'],'unavailable')

    def test_reject_unsigned_metadata(self):
        client=Mock();reply=Mock(status_code=200)
        reply.json.return_value=dict(tag_name='v9.0.0',assets=[dict(name='MCTranslator.exe',size=100,browser_download_url='https://github.com/file')])
        client.get.return_value=reply
        with self.assertRaisesRegex(ValueError,'SHA-256'):check_update(client)

    def test_bad_hash_removes_download_not_original(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);original=home/'MCTranslator.exe';original.write_bytes(b'MZ original')
            client=Mock();response=Mock();response.iter_content.return_value=[b'MZ corrupt']
            client.get.return_value.__enter__=Mock(return_value=response);client.get.return_value.__exit__=Mock(return_value=False)
            info=dict(sha256='a'*64,size=len(b'MZ corrupt'),url='https://github.com/siang86121900/mc-zh-tw-translator/releases/download/v9.0.0/MCTranslator.exe')
            with self.assertRaisesRegex(ValueError,'校驗失敗'):download_update(info,home,lambda _:None,client)
            self.assertEqual(original.read_bytes(),b'MZ original')
            self.assertFalse(list((home/'updates').rglob('*.exe')))

    def test_valid_hash_is_required_before_return(self):
        with tempfile.TemporaryDirectory() as directory:
            payload=b'MZ valid';client=Mock();response=Mock();response.iter_content.return_value=[payload]
            client.get.return_value.__enter__=Mock(return_value=response);client.get.return_value.__exit__=Mock(return_value=False)
            info=dict(sha256=hashlib.sha256(payload).hexdigest(),size=len(payload),url='https://github.com/siang86121900/mc-zh-tw-translator/releases/download/v9.0.0/MCTranslator.exe')
            p,h=download_update(info,Path(directory),lambda _:None,client)
            self.assertEqual(p.read_bytes(),payload);self.assertEqual(h,info['sha256'])

if __name__=='__main__':unittest.main()
