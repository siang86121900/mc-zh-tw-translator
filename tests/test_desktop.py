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
        with zipfile.ZipFile(nested,'w') as z:z.writestr('assets/lib/textures/a.png','x')
        with zipfile.ZipFile(self.instance/'mods/real.jar','w') as z:
            z.writestr('assets/real/lang/en_us.json',json.dumps({'real.a':'Real'}))
            z.writestr('META-INF/jarjar/lib.jar',nested.getvalue())  # jar-in-jar library counts as installed
        packs=self.instance/'config/openloader/packs';packs.mkdir(parents=True)
        with zipfile.ZipFile(packs/'cfpa.zip','w') as z:
            z.writestr('assets/ghost/lang/en_us.json',json.dumps({'ghost.a':'Ghost'}))
            z.writestr('assets/real/lang/en_us.json',json.dumps({'real.b':'Real B'}))
            z.writestr('assets/lib/lang/en_us.json',json.dumps({'lib.a':'Library'}))
        result=self.make_plan()
        self.assertFalse(any('ghost' in r['source'] for r in result['rows']))
        self.assertTrue(any(r['key']=='real.b' for r in result['rows']))
        self.assertTrue(any(r['key']=='lib.a' for r in result['rows']))
        self.assertEqual(result['source_counts']['not_installed'],1)

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

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_pack_mode_writes_kubejs_without_touching_mods_and_restores(self,_):
        import zipfile
        jar=self.make_mod();before=jar.read_bytes()
        (self.instance/'mods/kubejs-neoforge.jar').write_bytes(b'')  # KubeJS present -> KubeJS assets
        (self.instance/'options.txt').write_text('fov:0.0\nlang:en_us\n',encoding='utf-8')
        result=self.confirm_all(self.make_plan());result.update(apply_mode='pack',set_language=True)
        done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual(jar.read_bytes(),before)  # mod jar untouched
        lang=json.loads((self.instance/'kubejs/assets/real/lang/zh_tw.json').read_text(encoding='utf-8'))
        self.assertEqual(lang,{'real.a':'真實','real.b':'保留我'})  # mod's own zh_tw kept, new key added
        self.assertEqual(json.loads((self.instance/'kubejs/assets/lib/lang/zh_tw.json').read_text(encoding='utf-8')),{'lib.a':'函式庫'})
        self.assertIn('lang:zh_tw',(self.instance/'options.txt').read_text(encoding='utf-8'))
        self.assertTrue(done['language_set'])
        restore_backup(Path(done['backup']),self.instance)
        self.assertFalse((self.instance/'kubejs/assets/real/lang/zh_tw.json').exists())
        self.assertIn('lang:en_us',(self.instance/'options.txt').read_text(encoding='utf-8'))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_pack_mode_without_kubejs_builds_translation_mod(self,_):
        import zipfile, shutil
        shutil.rmtree(self.instance/'kubejs')
        self.make_mod();result=self.confirm_all(self.make_plan());result['apply_mode']='pack'
        apply_session(result,self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'mods/mctranslator_zh_tw.jar') as z:
            toml=z.read('META-INF/neoforge.mods.toml').decode('utf-8')
            self.assertIn('modLoader="lowcodefml"',toml);self.assertIn('modId="real"',toml);self.assertIn('ordering="AFTER"',toml)
            self.assertEqual(json.loads(z.read('assets/real/lang/zh_tw.json'))['real.a'],'真實')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_jar_mode_skips_nested_rows_and_leaves_inner_jar(self,_):
        import zipfile
        self.make_mod();result=self.confirm_all(self.make_plan())
        done=apply_session(result,self.home,lambda *_:None)
        self.assertEqual(done['nested_skipped'],1)
        with zipfile.ZipFile(self.instance/'mods/real.jar') as z:
            self.assertIn('assets/real/lang/zh_tw.json',z.namelist())
            self.assertNotIn('META-INF/jarjar/lib.jar!/assets/lib/lang/zh_tw.json',z.namelist())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_default_mode_writes_mods_and_sends_nested_text_to_kubejs(self,_):
        import zipfile
        self.make_mod();(self.instance/'mods/kubejs-neoforge.jar').write_bytes(b'')
        (self.instance/'options.txt').write_text('lang:en_us\n',encoding='utf-8')
        done=apply_session(self.confirm_all(self.make_plan()),self.home,lambda *_:None)
        with zipfile.ZipFile(self.instance/'mods/real.jar') as z:
            self.assertEqual(json.loads(z.read('assets/real/lang/zh_tw.json'))['real.a'],'真實')  # ordinary text in the mod
        self.assertEqual(json.loads((self.instance/'kubejs/assets/lib/lang/zh_tw.json').read_text(encoding='utf-8')),{'lib.a':'函式庫'})
        self.assertEqual((done['nested_packed'],done['nested_skipped']),(1,0))
        self.assertEqual((self.instance/'options.txt').read_text(encoding='utf-8'),'lang:en_us\n')  # language left to the player

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
        session=dict(rows=[row('牙狼族'),row('牙狼族'),row('恐狼','reference_pack_or_cfpa'),row('无','same_source_zh_cn','gui.a.none')])
        conflict=conflicting_terms(session)[0]
        self.assertEqual(conflict['suggested'],'恐狼')  # a more trusted source beats a larger count
        self.assertEqual(len(conflicting_terms(session)),1)  # UI words (gui.*) are never listed
        self.assertEqual(apply_term(session,'Direwolf','恐狼'),3)
        self.assertEqual([r['proposed'] for r in session['rows']],['恐狼','恐狼','恐狼','无'])

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
        with patch('pathlib.Path.home',return_value=home),patch.dict('os.environ',{'APPDATA':str(home/'none')}):
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
        with zipfile.ZipFile(mods/'lights.jar') as z:
            self.assertEqual(json.loads(z.read('assets/lights/lang/zh_tw.json')),{'a.mode':'模式'})

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_changed_source_refuses_apply(self,_):
        result=self.make_plan()
        next(r for r in result['rows'] if r['key']=='demo.hello')['reviewed']=True
        (self.lang/'en_us.json').write_text('{"demo.hello":"Changed %s"}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'重新掃描'):apply_session(result,self.home,lambda *_:None)
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
