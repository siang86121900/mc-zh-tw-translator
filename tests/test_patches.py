import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from mc_zh_tw_translator import patches
from mc_zh_tw_translator.desktop_jobs import apply_session, plan, restore_backup


def make_instance(root):
    instance=root
    lang=instance/'kubejs/assets/demo/lang';lang.mkdir(parents=True)
    (lang/'en_us.json').write_text(json.dumps({'demo.hello':'Hello %s'}),encoding='utf-8')
    (lang/'zh_cn.json').write_text(json.dumps({'demo.hello':'你好 %s'}),encoding='utf-8')
    (instance/'manifest.json').write_text(json.dumps({'minecraft':{'version':'1.21.1'},'name':'Demo Pack','version':'1.0'}),encoding='utf-8')
    (instance/'minecraftinstance.json').write_text(json.dumps({'name':'Demo Pack','projectID':123,'fileID':456,'gameVersion':'1.21.1'}),encoding='utf-8')
    (instance/'mods').mkdir()
    with zipfile.ZipFile(instance/'mods/real.jar','w') as z:
        z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="real"\n')
        z.writestr('META-INF/CERT.SF','signature')
        z.writestr('real/Main.class',b'\xca\xfe\xba\xbe')
        z.writestr('assets/real/lang/en_us.json',json.dumps({'real.a':'Real'}))
        z.writestr('assets/real/lang/zh_cn.json',json.dumps({'real.a':'真实'}))
    (instance/'options.txt').write_text('lang:en_us\n',encoding='utf-8')
    return instance


@patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.home=root/'app'
        self.translator=make_instance(root/'translator'/'Demo Pack')
        self.friend=make_instance(root/'friend'/'Demo Pack')  # same pack, untranslated
        self.friend_jar=(self.friend/'mods/real.jar').read_bytes()

    def translate(self):
        session=plan(self.translator,self.home,lambda *_:None,references=([{},{}],{'tested':True}))
        for r in session['rows']:
            if r['supported'] and r['changed']:r['reviewed']=True
        session['set_language']=True
        return apply_session(session,self.home,lambda *_:None)

    def test_export_contains_only_translation_text(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        with zipfile.ZipFile(out['path']) as z:
            names=z.namelist();manifest=json.loads(z.read('manifest.json'))
        self.assertEqual(manifest['modpack']['projectID'],123)
        self.assertIn('payload/resourcepacks/MCTranslator-zh_tw.zip/assets/real/lang/zh_tw.json',names)
        self.assertFalse(any(n.endswith('.class') or 'options.txt' in n for n in names))
        self.assertIn('payload/kubejs/assets/demo/lang/zh_tw.json',names)
        self.assertFalse(any(f['file'].startswith('mods/') for f in manifest['files']))  # mods are never changed or carried
        pack=next(f for f in manifest['files'] if f['file']=='resourcepacks/MCTranslator-zh_tw.zip')
        self.assertEqual(list(pack['entries']),['assets/real/lang/zh_tw.json'])
        self.assertEqual(list(pack['requires']['assets/real/lang/zh_tw.json']),['mods/real.jar'])  # tied to the mod version

    def test_friend_applies_patch_and_can_restore(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        friend_home=Path(self.temp.name)/'friend-app'
        result=patches.apply_patch(self.friend,Path(out['path']),friend_home,set_language=True)
        self.assertEqual(sorted(result['applied']),['kubejs/assets/demo/lang/zh_tw.json','resourcepacks/MCTranslator-zh_tw.zip'])
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),self.friend_jar)  # the friend's mod stays the official file
        with zipfile.ZipFile(self.friend/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            self.assertEqual(json.loads(z.read('assets/real/lang/zh_tw.json'))['real.a'],'真實')
        options=(self.friend/'options.txt').read_text(encoding='utf-8')
        self.assertIn('lang:zh_tw',options);self.assertIn('file/MCTranslator-zh_tw.zip',options)
        again=patches.apply_patch(self.friend,Path(out['path']),friend_home)
        self.assertEqual((again['applied'],sorted(again['already'])),([],['kubejs/assets/demo/lang/zh_tw.json','resourcepacks/MCTranslator-zh_tw.zip']))
        restore_backup(Path(result['backup']),self.friend)
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),self.friend_jar)
        self.assertFalse((self.friend/'resourcepacks/MCTranslator-zh_tw.zip').exists())
        self.assertFalse((self.friend/'kubejs/assets/demo/lang/zh_tw.json').exists())

    def add_converted_files(self,instance):
        menu=instance/'config/fancymenu/customization';menu.mkdir(parents=True)
        (menu/'title_screen_layout.txt').write_text('customization {\n  label = &e开始游戏\n  identifier = 开始\n}\n',encoding='utf-8')
        (instance/'scripts').mkdir()
        (instance/'scripts/tips.zs').write_text('// 注释\n<item:a:b>.addTooltip("\\u00A7e魂心容器需灵魂项链");\nval x = "a";\n',encoding='utf-8')
        (instance/'config/quests.json').write_text('{"title": "龙之试炼", "count": 3}',encoding='utf-8')

    def test_converted_config_and_scripts_travel_as_chinese_only_string_edits(self,_):
        for instance in (self.translator,self.friend):self.add_converted_files(instance)
        before={p:(self.friend/p).read_bytes() for p in ('config/fancymenu/customization/title_screen_layout.txt','scripts/tips.zs','config/quests.json')}
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        with zipfile.ZipFile(out['path']) as z:
            names=z.namelist();manifest=json.loads(z.read('manifest.json'))
        self.assertEqual(manifest['format'],patches.PATCH_FORMAT_LITERALS)
        literal={f['file']:f['literals'] for f in manifest['files'] if 'literals' in f}
        self.assertEqual(sorted(literal),sorted(before))
        self.assertFalse(any(n.startswith(('payload/scripts','payload/config/fancymenu','payload/config/quests')) for n in names))  # never the file
        self.assertEqual(literal['scripts/tips.zs'],[[2,0,'"\\u00A7e魂心容器需灵魂项链"','"\\u00A7e魂心容器需靈魂項鍊"']])
        result=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        for p in before:self.assertEqual((self.friend/p).read_bytes(),(self.translator/p).read_bytes(),p)
        self.assertIn('scripts/tips.zs',result['applied'])
        again=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        self.assertIn('scripts/tips.zs',again['already'])
        restore_backup(Path(result['backup']),self.friend)
        self.assertEqual({p:(self.friend/p).read_bytes() for p in before},before)

    def test_a_changed_config_file_is_skipped_and_a_patch_without_edits_stays_format_1(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        with zipfile.ZipFile(out['path']) as z:self.assertEqual(json.loads(z.read('manifest.json'))['format'],patches.PATCH_FORMAT)
        for instance in (self.translator,self.friend):self.add_converted_files(instance)
        (self.friend/'scripts/tips.zs').write_text('// 改过\n<item:a:b>.addTooltip("\\u00A7e魂心容器需灵魂项链");\n',encoding='utf-8')
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        result=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        self.assertIn('scripts/tips.zs',[s['file'] for s in result['skipped']])
        self.assertIn('灵魂',(self.friend/'scripts/tips.zs').read_text(encoding='utf-8'))

    def test_connector_generated_copies_are_neither_scanned_nor_required(self,_):
        # Sinytra Connector makes mods/.connector/*_mapped_*.jar from a Fabric mod on each computer.
        shutil.copytree(self.translator/'mods',self.translator/'mods/.connector')
        session=plan(self.translator,self.home,lambda *_:None,references=([{},{}],{'tested':True}))
        self.assertFalse([r for r in session['rows'] if '.connector' in r['source']])
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            z.writestr('assets/real/lang/zh_tw.json','{}')
            z.writestr('mctranslator.json',json.dumps({'sources':{'assets/real/lang/zh_tw.json':{
                'mods/.connector/real_mapped.jar':'a'*64,'mods/real.jar':'b'*64}}}))
        entries,requires=patches.pack_entries(data.getvalue())
        self.assertEqual(requires,{'assets/real/lang/zh_tw.json':{'mods/real.jar':'b'*64}})

    def test_a_string_edit_that_changes_anything_but_chinese_is_refused(self,_):
        self.assertTrue(patches.edit_safe('scripts/a.zs','"灵魂"','"靈魂"'))
        self.assertTrue(patches.edit_safe('config/a.json','"\\u7075\\u9b42"','"\\u9748\\u9b42"'))  # escaped Chinese
        for old,new in (('"灵魂"','"靈魂"); evil(); ("'),('"灵魂"','"靈魂\\n"'),('"灵魂 1"','"靈魂 2"'),('"灵魂"','"灵魂"')):
            self.assertFalse(patches.edit_safe('scripts/a.zs',old,new),new)
        bad=Path(self.temp.name)/'bad.zip'
        item=dict(file='scripts/a.zs',archive=False,before='0'*64,after='1'*64,literals=[[1,0,'"灵魂"','"靈魂"); evil(); ("']])
        for item,fmt in ((item,patches.PATCH_FORMAT_LITERALS),(dict(item,literals=[[1,0,'"灵魂"','"靈魂"']]),patches.PATCH_FORMAT),
                         (dict(item,file='saves/w/a.json'),patches.PATCH_FORMAT_LITERALS)):
            with zipfile.ZipFile(bad,'w') as z:z.writestr('manifest.json',json.dumps(dict(format=fmt,files=[item])))
            with self.assertRaises(ValueError):patches.read_patch(bad)

    def test_different_mod_version_is_skipped_not_overwritten(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        with zipfile.ZipFile(self.friend/'mods/real.jar','a') as z:z.writestr('assets/real/new.txt','v2')
        changed=(self.friend/'mods/real.jar').read_bytes()
        result=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        self.assertEqual(result['applied'],['kubejs/assets/demo/lang/zh_tw.json'])
        self.assertEqual([s['file'] for s in result['skipped']],['mods/real.jar'])  # names the mod whose version differs
        self.assertFalse((self.friend/'resourcepacks/MCTranslator-zh_tw.zip').exists())
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),changed)

    def test_renamed_mod_file_is_found_by_hash(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        (self.friend/'mods/real.jar').rename(self.friend/'mods/real-renamed.jar')
        result=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        self.assertIn('resourcepacks/MCTranslator-zh_tw.zip',result['applied'],result)

    def test_patch_with_code_or_traversal_is_rejected(self,_):
        bad=Path(self.temp.name)/'bad.zip'
        for item,payload in ((dict(file='mods/real.jar',archive=True,before='0'*64,size=1,entries={'real/Main.class':'0'*64}),'payload/mods/real.jar/real/Main.class'),
                             (dict(file='../evil.json',archive=False,before=None,after='0'*64),'payload/../evil.json'),
                             (dict(file='kubejs/server_scripts/a.js',archive=False,before=None,after='0'*64),'payload/kubejs/server_scripts/a.js')):
            with zipfile.ZipFile(bad,'w') as z:
                z.writestr('manifest.json',json.dumps(dict(format=patches.PATCH_FORMAT,files=[item])));z.writestr(payload,'x')
            with self.assertRaises(ValueError):patches.read_patch(bad)

    def test_only_the_zh_tw_quest_file_may_be_shared(self,_):
        self.assertTrue(patches.allowed_file('config/ftbquests/quests/lang/zh_tw.snbt',False))
        for other in ('config/ftbquests/quests/lang/en_us.snbt','config/ftbquests/quests/chapters/a.snbt','config/x/lang/zh_tw.snbt'):
            self.assertFalse(patches.allowed_file(other,False),other)

    def test_gun_pack_zh_tw_may_be_shared_but_nothing_else_in_it(self,_):
        self.assertTrue(patches.allowed_file('tacz/[绝对彼方] OCLE/assets/ocle/lang/zh_tw.json',False))
        for other in ('tacz/a/assets/ocle/lang/en_us.json','tacz/a/assets/ocle/display/a.json','tacz/a/scripts/a.lua'):
            self.assertFalse(patches.allowed_file(other,False),other)

    def test_export_skips_files_changed_after_apply(self,_):
        self.translate()
        (self.translator/'kubejs/assets/demo/lang/zh_tw.json').write_text('{}',encoding='utf-8')
        out=patches.export_patch(self.translator,self.home)
        self.assertEqual([s['file'] for s in out['skipped']],['kubejs/assets/demo/lang/zh_tw.json'])

    def test_catalog_matches_installed_instances(self,_):
        response=Mock(status_code=200);response.json.return_value={'packs':[
            dict(name='Demo',projectID=123,fileID=456,url='https://github.com/siang86121900/mc-zh-tw-translator/releases/download/translations/demo.zip',sha256='a'*64,size=10),
            dict(name='Evil',projectID=1,fileID=1,url='https://evil.example/x.zip',sha256='a'*64,size=10)]}
        packs=patches.fetch_catalog(Mock(get=Mock(return_value=response)))
        self.assertEqual([p['name'] for p in packs],['Demo'])
        mine=[dict(name='Demo Pack',path=self.friend,projectID=123,fileID=999,gameVersion='1.21.1')]
        self.assertEqual(patches.match_catalog(packs,mine)[0]['status'],'other_version')
        self.assertEqual(patches.curseforge_install_url(packs[0]),'curseforge://install?addonId=123&fileId=456')
        missing=Mock(status_code=404)
        self.assertEqual(patches.fetch_catalog(Mock(get=Mock(return_value=missing))),[])


    def test_catalog_picks_translation_for_installed_version(self,_):
        base=dict(name='Demo',projectID=7,version='',gameVersion='',translator='',notes='',sha256='a'*64,size=1,
                  url='https://raw.githubusercontent.com/siang86121900/mc-zh-tw-translator/translations/packs/7/x.zip')
        old=dict(base,fileID=1,version='1.0',updated='2026-01-01');new=dict(base,fileID=2,version='2.0',updated='2026-09-01')
        mine=[dict(name='Demo',path=self.friend,projectID=7,fileID=1,gameVersion='')]
        [row]=patches.match_catalog([old,new],mine)
        self.assertEqual((row['version'],row['status'],row['latest'],row['versions']),('1.0','exact',False,2))
        [row]=patches.match_catalog([old,new],[])
        self.assertEqual((row['version'],row['status']),('2.0','not_installed'))
        with self.assertRaises(ValueError):patches.patch_url('https://raw.githubusercontent.com/someone/else/translations/x.zip')
        # Re-publishing the old version's translation later does not make it the "newest" version.
        [row]=patches.match_catalog([dict(old,updated='2026-10-01'),new],[])
        self.assertEqual(row['version'],'2.0')
        [row]=patches.match_catalog([dict(old,updated='2026-10-01'),new],mine)
        self.assertEqual((row['version'],row['latest'],row['newest_version']),('1.0',False,'2.0'))

    def test_catalog_memory_comes_from_catalog_or_installed_manifest(self,_):
        (self.friend/'manifest.json').write_text(json.dumps({'minecraft':{'version':'1.21.1','recommendedRam':12128}}),encoding='utf-8')
        base=dict(name='Demo',projectID=7,fileID=1,version='1.0',gameVersion='',translator='',notes='',sha256='a'*64,size=1,updated='',
                  url='https://raw.githubusercontent.com/siang86121900/mc-zh-tw-translator/translations/packs/7/x.zip')
        mine=[dict(name='Demo',path=self.friend,projectID=7,fileID=1,gameVersion='')]
        self.assertEqual(patches.match_catalog([base],mine)[0]['recommendedRam'],12128)  # older entry without the figure
        self.assertEqual(patches.match_catalog([dict(base,recommendedRam=8192)],mine)[0]['recommendedRam'],8192)
        self.assertEqual(patches.match_catalog([base],[])[0]['recommendedRam'],0)
        self.assertEqual(patches.instance_identity(self.friend)['recommendedRam'],12128)
        response=Mock(status_code=200);response.json.return_value={'packs':[dict(base,recommendedRam='99999999'),dict(base,fileID=2,recommendedRam=6144)]}
        self.assertEqual([p['recommendedRam'] for p in patches.fetch_catalog(Mock(get=Mock(return_value=response)))],[0,6144])

    def test_memory_advice_reads_but_never_sets_curseforge(self,_):
        self.assertEqual(patches.memory_advice(0,16384),{})
        roomy=patches.memory_advice(12128,32768)
        self.assertIn('約 12 GB',roomy['line']);self.assertEqual((roomy['warning'],roomy['now']),('',''))
        self.assertIn('設定檔選項（Profile Options）',roomy['steps']);self.assertIn('作者推薦（Recommended by Author）',roomy['steps']);self.assertIn('不會修改',roomy['steps'])
        self.assertIn('剩下不多',patches.memory_advice(12128,16384)['warning'])  # over 3/4 of the computer, as CurseForge warns
        self.assertIn('可能開不起來',patches.memory_advice(12128,8192)['warning'])
        self.assertEqual(patches.memory_advice(12128,0)['warning'],'')  # unknown total: no guess
        self.assertIn('設定為 6 GB，比建議少',patches.memory_advice(12128,32768,{'isMemoryOverride':True,'allocatedMemory':6144})['now'])
        self.assertEqual(patches.memory_advice(12128,32768,{'isMemoryOverride':False,'allocatedMemory':6144})['now'],'')
        self.assertIn('設定為 12 GB。',patches.memory_advice(12128,32768,{'isMemoryOverride':True,'allocatedMemory':12288})['now'])


    def test_catalog_offers_update_after_translation_is_republished(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        friend_home=Path(self.temp.name)/'friend-app'
        patches.apply_patch(self.friend,Path(out['path']),friend_home)
        pack=dict(name='Demo Pack',projectID=123,fileID=456,version='1.0',gameVersion='',translator='',notes='',updated='2026-09-29',
                  url='https://raw.githubusercontent.com/siang86121900/mc-zh-tw-translator/translations/packs/123/a.zip',sha256=out['sha256'],size=out['size'])
        mine=[dict(name='Demo Pack',path=self.friend,projectID=123,fileID=456,gameVersion='')]
        applied=patches.applied_patches(friend_home)
        self.assertEqual(patches.match_catalog([pack],mine,applied)[0]['status'],'applied')
        self.assertEqual(patches.match_catalog([dict(pack,sha256='b'*64,updated='2026-10-01')],mine,applied)[0]['status'],'update')
        self.assertEqual(patches.match_catalog([pack],mine,{})[0]['status'],'exact')


    def test_rerun_keeps_labels_of_applied_translations_and_patch_carries_them(self,_):
        self.translate()
        again=plan(self.translator,self.home,lambda *_:None,references=([{},{}],{'tested':True}))
        row=next(r for r in again['rows'] if r['key']=='demo.hello')
        self.assertEqual((row['origin'],row.get('recovered'),row.get('installed')),('same_source_zh_cn',True,True))
        self.assertGreaterEqual(again['recovered_count'],2)
        out=patches.export_patch(self.translator,self.home)
        friend_home=Path(self.temp.name)/'friend-app'
        patches.apply_patch(self.friend,Path(out['path']),friend_home)
        theirs=plan(self.friend,friend_home,lambda *_:None,references=([{},{}],{'tested':True}))
        self.assertEqual(next(r for r in theirs['rows'] if r['key']=='demo.hello')['origin'],'same_source_zh_cn')

    def test_modpack_renamed_text_does_not_take_key_only_sources(self,_):
        lang=self.translator/'kubejs/assets/real/lang';lang.mkdir(parents=True)
        (lang/'en_us.json').write_text(json.dumps({'real.a':'Rusty Blade'}),encoding='utf-8')
        cfpa={'real':{'real.a':'真实'}}
        session=plan(self.translator,self.home,lambda *_:None,references=([{},cfpa],{'sources':['tw','cn']}))
        kubejs=next(r for r in session['rows'] if r['key']=='real.a' and r['source'].startswith('instance!/kubejs'))
        self.assertEqual((kubejs['origin'],kubejs.get('renamed')),('untranslated',True))
        self.assertEqual(session['renamed_count'],1)


    def test_batch_applied_in_parts_can_finish_later(self,_):
        from mc_zh_tw_translator.desktop_jobs import auto_confirm_safe
        session=plan(self.translator,self.home,lambda *_:None,references=([{},{}],{'tested':True}))
        jar_row=next(r for r in session['rows'] if r['key']=='real.a')
        jar_row['reviewed']=True  # an older version applied only the rows confirmed by hand
        first=apply_session(session,self.home,lambda *_:None)
        self.assertEqual((first['status'],first['installed_count']),('installed',1))
        auto_confirm_safe(first)  # the report's 備份並套用譯文 now finishes the rest
        done=apply_session(first,self.home,lambda *_:None)
        self.assertEqual(done['installed_count'],2);self.assertEqual(len(done['backups']),2)
        self.assertTrue((self.translator/'kubejs/assets/demo/lang/zh_tw.json').exists())
        with self.assertRaises(ValueError):apply_session(done,self.home,lambda *_:None)  # nothing left

    def test_kubejs_file_shared_by_modpack_and_embedded_library_is_written_once(self,_):
        # Tensura: kubejs/assets/manascore/lang has the modpack's own text, and manascore is also a jar-in-jar.
        inner=io.BytesIO()
        with zipfile.ZipFile(inner,'w') as z:
            z.writestr('assets/lib/lang/en_us.json',json.dumps({'lib.a':'Library'}))
            z.writestr('assets/lib/lang/zh_cn.json',json.dumps({'lib.a':'函数库'}))
            z.writestr('assets/lib/lang/zh_tw.json',json.dumps({'lib.own':'自帶'}))
        with zipfile.ZipFile(self.translator/'mods/host.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="host"\n')
            z.writestr('META-INF/jarjar/lib.jar',inner.getvalue())
        (self.translator/'mods/kubejs-neoforge.jar').write_bytes(b'')
        lang=self.translator/'kubejs/assets/lib/lang'
        lang.mkdir(parents=True)
        (lang/'en_us.json').write_text(json.dumps({'lib.pack':'Pack text'}),encoding='utf-8')
        (lang/'zh_cn.json').write_text(json.dumps({'lib.pack':'整合包文字'}),encoding='utf-8')
        done=self.translate()
        self.assertEqual(done['status'],'installed')
        self.assertEqual(json.loads((lang/'zh_tw.json').read_text(encoding='utf-8')),{'lib.pack':'整合包文字'})
        with zipfile.ZipFile(self.translator/'resourcepacks/MCTranslator-zh_tw.zip') as z:  # the library's own text
            self.assertEqual(json.loads(z.read('assets/lib/lang/zh_tw.json')),{'lib.a':'函式庫','lib.own':'自帶'})

    def test_modpack_update_after_translation_is_noticed(self,_):
        from mc_zh_tw_translator import desktop_jobs as jobs
        self.translate()
        self.assertEqual(jobs.outdated_translations(self.home),[])
        # CurseForge updates the modpack: new fileID/version and the translated jars are replaced.
        (self.translator/'minecraftinstance.json').write_text(json.dumps({'name':'Demo Pack','projectID':123,'fileID':789,'gameVersion':'1.21.1'}),encoding='utf-8')
        (self.translator/'manifest.json').write_text(json.dumps({'name':'Demo Pack','version':'2.0','minecraft':{'version':'1.21.1'}}),encoding='utf-8')
        [found]=jobs.outdated_translations(self.home)
        self.assertEqual((found['old_version'],found['new_version']),('1.0','2.0'))
        jobs.dismiss_outdated(self.home,found['key'],found['fileID'])
        self.assertEqual(jobs.outdated_translations(self.home),[])


class OneClickTests(unittest.TestCase):
    def test_names_in_finds_longest_modpack_names(self):
        from mc_zh_tw_translator.desktop_jobs import names_in
        names={'iron sword':('Iron Sword','鐵劍'),'iron':('Iron','鐵'),'magicule':('Magicule','魔素')}
        self.assertEqual(names_in(names,'Craft an Iron Sword with Magicules and magicule.'),{'Iron Sword':'鐵劍','Magicule':'魔素'})

    def test_report_overview_explains_what_was_not_applied(self):
        from mc_zh_tw_translator.desktop_jobs import report_overview
        rows=[dict(origin='untranslated',supported=True,changed=False),dict(origin='ai_translation',supported=True,changed=True,installed=True),
              dict(origin='same_source_zh_cn',supported=True,changed=True,installed=True)]
        o=report_overview(dict(rows=rows,installed_count=2,backup='x/20260929-120000-000000-abc',ai_translation=1))
        self.assertEqual((o['applied'],o['check'],o['not_applied']),(2,1,[(1,'找不到中文來源')]))

    def test_mainland_wording_in_mod_zh_tw_is_fixed_conservatively(self):
        from mc_zh_tw_translator.desktop_jobs import taiwan_wording
        self.assertEqual(taiwan_wording('傳送門激活物，請添加代碼'),'傳送門啟用物，請新增程式碼')
        self.assertEqual(taiwan_wording('用戶端與用戶'),'用戶端與使用者')
        self.assertEqual(taiwan_wording('設置を保存'),'設置を保存')  # Japanese untouched
        self.assertEqual(taiwan_wording('您沒有適當的權限來編輯此項目。'),'您沒有適當的權限來編輯此項目。')

    def test_inconsistent_names_are_unified_to_suggestion_and_flagged(self):
        from mc_zh_tw_translator.desktop_jobs import unify_suggested_terms, needs_check
        row=lambda zh,origin,evidence='':dict(source='mods/a.jar!/x',key='item.a.palm_log',en='Palm Log',proposed=zh,origin=origin,evidence=evidence,
                                              supported=True,changed=True,current=None,kind='language',issue='')
        rows=[row('棕櫚原木','reference_pack_or_cfpa','reference:tw'),row('棕榈木原木','same_source_zh_cn'),row('棕櫚木原木','same_source_zh_cn')]
        session=dict(rows=rows)
        self.assertEqual(unify_suggested_terms(session),2)
        self.assertEqual({r['proposed'] for r in rows},{'棕櫚原木'})
        self.assertEqual(rows[2]['unified_from'],'棕櫚木原木')
        self.assertEqual([needs_check(r) for r in rows],[False,True,True])


if __name__=='__main__':unittest.main()
