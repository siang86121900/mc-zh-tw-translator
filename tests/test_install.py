"""One button for a player who has nothing yet: CurseForge installs the modpack, then the translation goes on."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import patches
from mc_zh_tw_translator import desktop_jobs as jobs
from mc_zh_tw_translator.desktop_jobs import plan, apply_session


def put(z,name,data):
    """An entry with a fixed date: two jars made a moment apart must be the same file, byte for byte."""
    z.writestr(zipfile.ZipInfo(name,(2026,1,1,0,0,0)),data)


def make_instance(instance):
    lang=instance/'kubejs/assets/demo/lang';lang.mkdir(parents=True)
    (lang/'en_us.json').write_text(json.dumps({'demo.hello':'Hello %s'}),encoding='utf-8')
    (lang/'zh_cn.json').write_text(json.dumps({'demo.hello':'你好 %s'}),encoding='utf-8')
    (lang/'zh_tw.json').write_text(json.dumps({'demo.old':'舊'},ensure_ascii=False),encoding='utf-8')
    (instance/'manifest.json').write_text(json.dumps({'minecraft':{'version':'1.21.1'},'name':'Demo Pack','version':'1.0'}),encoding='utf-8')
    (instance/'minecraftinstance.json').write_text(json.dumps({'name':'Demo Pack','projectID':123,'fileID':456,'gameVersion':'1.21.1'}),encoding='utf-8')
    (instance/'mods').mkdir()
    with zipfile.ZipFile(instance/'mods/real.jar','w') as z:
        put(z,'real/Main.class',b'\xca\xfe\xba\xbe')
        put(z,'assets/real/lang/en_us.json',json.dumps({'real.a':'Real'}))
        put(z,'assets/real/lang/zh_cn.json',json.dumps({'real.a':'真实'},ensure_ascii=False))
    return instance


def mod_jar(path,namespace,text):
    with zipfile.ZipFile(path,'w') as z:
        put(z,'META-INF/neoforge.mods.toml',f'modLoader="javafml"\n[[mods]]\nmodId="{namespace}"\n')
        put(z,namespace+'/Main.class',b'\xca\xfe\xba\xbe')
        put(z,f'assets/{namespace}/lang/en_us.json',json.dumps({namespace+'.a':text}))
        put(z,f'assets/{namespace}/lang/zh_cn.json',json.dumps({namespace+'.a':'输入法'},ensure_ascii=False))
    return path


def addon(project,file,name,size,**more):
    return dict(addonID=project,name=name.split('.')[0],webSiteURL='https://www.curseforge.com/minecraft/mc-mods/'+name.split('.')[0],
                categorySection=dict(path='mods'),allowModDistribution=True,
                installedFile=dict(id=file,fileName=name,fileLength=size,downloadUrl=f'https://edge.forgecdn.net/files/{file//1000}/{file%1000}/{name}'),**more)


def curseforge_record(instance,addons,official=((1,10),)):
    (instance/'minecraftinstance.json').write_text(json.dumps(dict(
        name='Demo Pack',projectID=123,fileID=456,gameVersion='1.21.1',installedAddons=addons,
        manifest=dict(files=[dict(projectID=p,fileID=f,required=True) for p,f in official]))),encoding='utf-8')


class Served:
    """Stands in for CurseForge's file server; records what was asked for."""
    def __init__(self,files,moved=None):self.files=files;self.asked=[];self.moved=moved;self.failures=0
    def get(self,url,**_):
        self.asked.append(url);server=self
        class Response:
            status_code=200 if url in server.files else 404
            def __enter__(inner):return inner
            def __exit__(inner,*_):pass
            def raise_for_status(inner):
                if inner.status_code>=400:
                    import requests
                    raise requests.HTTPError(f'{inner.status_code} Client Error: Not Found for url: {url}',response=inner)
            def iter_content(inner,size):
                data=server.files[url]
                return (data[i:i+size] for i in range(0,len(data),size))
        response=Response();response.url=self.moved or url
        if self.failures:
            import requests
            self.failures-=1;raise requests.ConnectionError('connection reset')
        return response


class AddedModTests(unittest.TestCase):
    """The translator added a mod through CurseForge; the receiver gets it from CurseForge too."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'app'
        translator=make_instance(self.root/'translator/Demo Pack')
        self.jar=mod_jar(translator/'mods/imblocker-5.jar','imblocker','Input method').read_bytes()
        (translator/'mods/handmade.jar').write_bytes(b'PK\x05\x06'+bytes(18))
        real=(translator/'mods/real.jar').stat().st_size
        curseforge_record(translator,[addon(1,10,'real.jar',real),addon(2,2005,'imblocker-5.jar',len(self.jar))])
        session=plan(translator,self.home,lambda *_:None,references=([{},{}],{'tested':True}))
        for r in session['rows']:
            if r['supported'] and r['changed']:r['reviewed']=True
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):apply_session(session,self.home,lambda *_:None)
        self.translator=translator;self.exported=patches.export_patch(translator,self.home);self.patch=Path(self.exported['path'])
        self.friend=make_instance(self.root/'friend/Demo Pack')
        curseforge_record(self.friend,[addon(1,10,'real.jar',real)])
        self.url='https://edge.forgecdn.net/files/2/5/imblocker-5.jar'
        self.friend_home=self.root/'friend-app'

    def install(self,server,**more):
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            return patches.apply_patch(self.friend,self.patch,self.friend_home,set_language=True,add_mods=True,session=server,**more)

    def rebuilt(self,change):
        """The patch with its manifest edited, as someone tampering with it would."""
        out=self.root/'edited.zip'
        with zipfile.ZipFile(self.patch) as a,zipfile.ZipFile(out,'w') as b:
            for name in a.namelist():
                data=a.read(name)
                if name=='manifest.json':
                    manifest=json.loads(data);change(manifest);data=json.dumps(manifest).encode('utf-8')
                b.writestr(name,data)
        return out

    def test_patch_names_the_added_mod_but_never_carries_it(self):
        z,manifest=patches.read_patch(self.patch)
        with z:names=z.namelist()
        mod,=manifest['added_mods']
        # the mod file itself is never changed by translating, so its hash is the one CurseForge serves
        self.assertEqual((mod['fileName'],mod['projectID'],mod['fileID'],mod['size'],mod['sha256'],mod['url']),
                         ('imblocker-5.jar',2,2005,len(self.jar),patches.sha256(self.jar),self.url))
        self.assertEqual(patches.file_hash(self.translator/'mods/imblocker-5.jar'),mod['sha256'])
        self.assertFalse(any(n.endswith(('.jar','.class')) for n in names))
        self.assertTrue(any(n.startswith('payload/resourcepacks/MCTranslator-zh_tw.zip/assets/imblocker/lang/zh_tw') for n in names))
        left,=self.exported['left_out_mods']
        self.assertEqual(left['name'],'handmade.jar');self.assertIn('不是從 CurseForge 安裝',left['reason'])

    def test_receiver_gets_the_mod_from_curseforge_with_its_translation(self):
        server=Served({self.url:self.jar});seen=[];untouched=(self.friend/'mods/real.jar').read_bytes()
        result=self.install(server,notify=lambda *a:seen.append(a))
        self.assertEqual(server.asked,[self.url])
        self.assertEqual((result['mods']['installed'],result['mods']['skipped']),(['imblocker-5.jar'],[]))
        self.assertIn('resourcepacks/MCTranslator-zh_tw.zip',result['applied']);self.assertEqual(result['skipped'],[])
        with zipfile.ZipFile(self.friend/'resourcepacks/MCTranslator-zh_tw.zip') as z:
            self.assertEqual(json.loads(z.read('assets/imblocker/lang/zh_tw.json'))['imblocker.a'],'輸入法')
        self.assertEqual((self.friend/'mods/imblocker-5.jar').read_bytes(),self.jar)  # the downloaded mod stays as CurseForge serves it
        self.assertTrue(any(title.startswith('下載加裝的模組') for _,title,_ in seen))
        # a second install neither downloads nor writes again
        again=self.install(Served({}))
        self.assertEqual((again['mods']['installed'],again['mods']['present'],again['applied']),([],['imblocker-5.jar'],[]))
        # both writes can be undone; the translation never touches the added mod, so either can go first
        from mc_zh_tw_translator.desktop_jobs import restore_backup
        mods,translation=sorted(Path(b) for b in (result['mods']['backup'],result['backup']))
        restore_backup(mods,self.friend);restore_backup(translation,self.friend)
        self.assertFalse((self.friend/'mods/imblocker-5.jar').exists())
        self.assertFalse((self.friend/'resourcepacks/MCTranslator-zh_tw.zip').exists())
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),untouched)

    def test_another_file_than_the_translators_is_not_installed(self):
        other=mod_jar(self.root/'other.jar','imblocker','Something else').read_bytes()
        for served in (other,self.jar+b'x',self.jar[:-1],b'not a jar at all'):
            result=self.install(Served({self.url:served}))
            self.assertEqual(result['mods']['installed'],[]);self.assertIn('沒有安裝',result['mods']['skipped'][0]['reason'])
            self.assertFalse((self.friend/'mods/imblocker-5.jar').exists())
            self.assertEqual(list((self.friend_home/'downloads/mods').glob('*')),[])
            # the rest of the translation is not held up by it
            self.assertEqual([s['file'] for s in result['skipped']],['mods/imblocker-5.jar'])
            self.assertTrue((self.friend/'kubejs/assets/demo/lang/zh_tw.json').exists())

    def test_download_is_retried_and_a_missing_file_is_explained(self):
        server=Served({self.url:self.jar});server.failures=2
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            result=patches.install_mods(self.friend,patches.read_patch(self.patch)[1]['added_mods'],self.friend_home,session=server,pause=lambda _:None)
        self.assertEqual((result['installed'],len(server.asked)),(['imblocker-5.jar'],3))
        (self.friend/'mods/imblocker-5.jar').unlink();shutil.rmtree(self.friend_home/'downloads')
        server=Served({self.url:self.jar});server.failures=9
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            result=patches.install_mods(self.friend,patches.read_patch(self.patch)[1]['added_mods'],self.friend_home,session=server,pause=lambda _:None)
        self.assertEqual(len(server.asked),3);self.assertIn('請確認網路',result['skipped'][0]['reason'])
        gone=self.install(Served({}))['mods']['skipped'][0]['reason']
        self.assertNotIn('404',gone.split('（技術細節')[0]);self.assertNotIn('Client Error',gone.split('（技術細節')[0])

    def test_only_curseforge_file_servers_are_ever_asked(self):
        for url in ('https://example.com/files/2/5/imblocker-5.jar','http://edge.forgecdn.net/files/2/5/imblocker-5.jar',
                    'https://edge.forgecdn.net.example.com/files/2/5/imblocker-5.jar','https://edge.forgecdn.net/files/2/5/imblocker-5.jar?x=1'):
            edited=self.rebuilt(lambda m:m['added_mods'][0].update(url=url))
            with self.assertRaisesRegex(ValueError,'CurseForge'):patches.read_patch(edited)
        # a download that is sent on to another server is dropped
        result=self.install(Served({self.url:self.jar},moved='https://example.com/imblocker-5.jar'))
        self.assertEqual(result['mods']['installed'],[]);self.assertFalse((self.friend/'mods/imblocker-5.jar').exists())

    def test_unsafe_names_and_sizes_are_refused_before_anything_is_downloaded(self):
        for change in (lambda m:m.update(fileName='../evil.jar'),lambda m:m.update(fileName='sub/evil.jar'),lambda m:m.update(fileName='evil.exe'),
                       lambda m:m.update(fileName='C:evil.jar'),lambda m:m.update(size=patches.MAX_MOD_SIZE+1),lambda m:m.update(size=0),
                       lambda m:m.update(sha256='zz'),lambda m:m.update(projectID='x')):
            edited=self.rebuilt(lambda manifest:change(manifest['added_mods'][0]))
            with self.assertRaises(ValueError):patches.read_patch(edited)
        many=self.rebuilt(lambda m:m.update(added_mods=[dict(m['added_mods'][0],fileName=f'm{i}.jar') for i in range(patches.MAX_ADDED_MODS+1)]))
        with self.assertRaisesRegex(ValueError,'清單不合理'):patches.read_patch(many)
        twice=self.rebuilt(lambda m:m.update(added_mods=m['added_mods']*2))
        with self.assertRaisesRegex(ValueError,'重複'):patches.read_patch(twice)

    def test_a_mod_the_receiver_already_has_in_another_version_is_left_alone(self):
        (self.friend/'mods/imblocker-4.jar').write_bytes(b'older');real=(self.friend/'mods/real.jar').stat().st_size
        curseforge_record(self.friend,[addon(1,10,'real.jar',real),addon(2,1999,'imblocker-4.jar',5)])
        server=Served({self.url:self.jar});result=self.install(server)
        self.assertEqual(server.asked,[]);self.assertIn('其他版本',result['mods']['skipped'][0]['reason'])
        self.assertEqual(sorted(p.name for p in (self.friend/'mods').iterdir()),['imblocker-4.jar','real.jar'])

    def test_a_mod_only_curseforge_may_install_is_named_with_its_page(self):
        record=json.loads((self.translator/'minecraftinstance.json').read_text(encoding='utf-8'))
        record['installedAddons'][1]['allowModDistribution']=False
        (self.translator/'minecraftinstance.json').write_text(json.dumps(record),encoding='utf-8')
        mods,_=patches.added_mods(self.translator,{'mods/imblocker-5.jar':patches.sha256(self.jar)})
        self.assertIsNone(mods[0]['url'])
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            result=patches.install_mods(self.friend,mods,self.friend_home,session=Served({}))
        self.assertEqual((result['skipped'][0]['page'],result['installed']),('https://www.curseforge.com/minecraft/mc-mods/imblocker-5',[]))
        self.assertIn('請在 CurseForge 加裝',result['skipped'][0]['reason'])

    def test_replaced_modpack_mods_and_unknown_modpacks_are_left_out(self):
        real=(self.translator/'mods/real.jar').stat().st_size
        curseforge_record(self.translator,[addon(1,11,'real.jar',real)])  # the modpack's own mod in another version
        mods,left=patches.added_mods(self.translator)
        self.assertEqual(mods,[]);self.assertIn('換成別的版本',left[0]['reason'])
        (self.translator/'minecraftinstance.json').write_text(json.dumps(dict(installedAddons=[addon(2,2005,'imblocker-5.jar',len(self.jar))])),encoding='utf-8')
        (self.translator/'manifest.json').unlink()
        mods,left=patches.added_mods(self.translator)
        self.assertEqual(mods,[]);self.assertIn('無法分辨',left[0]['reason'])

    def test_waiting_for_the_modpack_does_not_wait_for_added_mods(self):
        _,manifest=patches.read_patch(self.patch)
        self.assertEqual(patches.modpack_files_ready(self.friend,manifest),(2,2))

    def test_without_consent_no_mod_is_added(self):
        server=Served({self.url:self.jar})
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            result=patches.apply_patch(self.friend,self.patch,self.friend_home,session=server)
        self.assertEqual((server.asked,result['mods'],result['mods_offered']),([],None,['imblocker-5']))
        self.assertFalse((self.friend/'mods/imblocker-5.jar').exists())

    def test_stopping_a_download_leaves_the_modpack_untouched(self):
        with self.assertRaises(InterruptedError):self.install(Served({self.url:self.jar}),cancelled=lambda:True)
        self.assertFalse((self.friend/'mods/imblocker-5.jar').exists())
        self.assertNotIn('你好',(self.friend/'kubejs/assets/demo/lang/zh_tw.json').read_text(encoding='utf-8'))

    def test_window_asks_before_adding_mods_and_reports_them(self):
        from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
        from mc_zh_tw_translator.desktop import MainWindow
        app=QApplication.instance() or QApplication([])
        entry=dict(name='Demo Pack',projectID=123,fileID=456,version='1.0',gameVersion='1.21.1',translator='我',updated='2026-09-30',
                   modpackDate='2026-09-18',revision=1,notes='',url='https://raw.githubusercontent.com/x',sha256='a'*64,size=1,
                   addedMods=[dict(name='IMBlocker',size=204800)])
        window=MainWindow(self.home)
        found=[dict(name='Demo Pack',path=self.friend,projectID=123,fileID=456,gameVersion='1.21.1')]
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=found):
            window.catalog_loaded([entry])
            shown=' '.join(l.text() for l in window.pages.widget(6).findChildren(type(window.patch_status)))
            self.assertIn('翻譯者另外加裝了 1 個模組：IMBlocker',shown)
            for answer,expected in ((None,None),(True,True)):
                with patch.object(window,'ask_install',return_value=answer) as ask,patch.object(window,'run_worker') as run:
                    window.apply_catalog_patch(window.catalog[0])
                self.assertEqual(ask.call_args[0][2]['addedMods'][0]['name'],'IMBlocker')
                self.assertEqual(run.called,expected is not None)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.No):
            self.assertIsNone(window.ask_install('安裝翻譯','說明',window.catalog[0]))  # closing the dialog is not a yes
        # Memory: the author's figure on the card, the CurseForge steps one button away.
        window.memory_total=8192
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=found):
            window.catalog_loaded([dict(entry,recommendedRam=12128)])
        shown=' '.join(l.text() for l in window.pages.widget(6).findChildren(type(window.patch_status)))
        self.assertIn('約 12 GB',shown);self.assertIn('可能開不起來',shown)
        help_button=next(b for b in window.pages.widget(6).findChildren(QPushButton) if b.text()=='怎麼調整記憶體')
        with patch.object(QMessageBox,'information') as told:help_button.click()
        self.assertIn('Profile Options',told.call_args[0][2])
        # Search appears only once the list is long, and filters by name.
        self.assertTrue(window.catalog_search.isHidden())
        many=[dict(entry,name=f'Pack {i}',projectID=1000+i,fileID=1) for i in range(window.CATALOG_SEARCH_FROM)]
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=[]):window.catalog_loaded(many)
        self.assertFalse(window.catalog_search.isHidden())
        window.catalog_search.setText('pack 3')
        self.assertEqual([f.isHidden() for f,_ in window.catalog_cards].count(False),1)
        window.catalog_search.setText('nothing here')
        self.assertIn('沒有符合',window.patch_status.text())
        window.catalog_search.clear();self.assertEqual(window.patch_status.text(),'')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes) as ask:
            self.assertIs(window.ask_install('安裝翻譯','說明',window.catalog[0]),True)  # one yes also adds the mods
        self.assertIn('會一起加入：IMBlocker',ask.call_args[0][2])
        done=dict(instance=str(self.friend),applied=['a'],already=[],skipped=[],backup='x',language_set=True,notes='',mods_offered=[],
                  mods=dict(installed=['imblocker-5.jar'],present=[],backup='y',
                            skipped=[dict(name='Other',file='o.jar',reason='作者只開放由 CurseForge 安裝，請在 CurseForge 加裝這個模組',page='https://www.curseforge.com/minecraft/mc-mods/other')]))
        with patch.object(QMessageBox,'information') as told,patch.object(window,'refresh_catalog'):window.patch_applied(done)
        text=told.call_args[0][2]
        self.assertIn('已加入翻譯者加裝的 1 個模組：imblocker-5.jar',text);self.assertIn('Other：作者只開放由 CurseForge 安裝',text)
        window.close()


class Clock:
    """Time that moves only when the code under test pauses."""
    def __init__(self):self.now=0;self.steps=[]
    def __call__(self):return self.now
    def pause(self,seconds):
        self.now+=seconds
        if self.steps:self.steps.pop(0)()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'app'
        self.original=make_instance(self.root/'original');translator=make_instance(self.root/'translator/Demo Pack')
        session=plan(translator,self.home,lambda *_:None,references=([{},{}],{'tested':True}))
        for r in session['rows']:
            if r['supported'] and r['changed']:r['reviewed']=True
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):apply_session(session,self.home,lambda *_:None)
        self.patch=Path(patches.export_patch(translator,self.home)['path'])
        z,self.manifest=patches.read_patch(self.patch);z.close()
        self.pack=dict(name='Demo Pack',projectID=123,fileID=456,version='1.0',notes='整合包作者建議記憶體約 12GB，請在 CurseForge 自行設定。')
        self.friend=self.root/'friend/Instances/Demo Pack';self.clock=Clock();self.seen=[]

    def listed(self):
        return [dict(name='Demo Pack',path=self.friend,projectID=123,fileID=456)] if (self.friend/'mods').is_dir() else []

    def wait(self,**limits):
        return patches.wait_for_modpack(self.pack,self.manifest,lambda *a:self.seen.append(a),find=self.listed,
                                        clock=self.clock,pause=self.clock.pause,**limits)

    def test_translation_waits_until_curseforge_has_put_every_file_in_place(self):
        jar=(self.original/'mods/real.jar').read_bytes()
        def folder():(self.friend/'mods').mkdir(parents=True)
        def half():(self.friend/'mods/real.jar').write_bytes(jar[:len(jar)//2])
        def whole():(self.friend/'mods/real.jar').write_bytes(jar)
        def overrides():shutil.copytree(self.original/'kubejs',self.friend/'kubejs')
        self.clock.steps=[lambda:None,folder,half,whole,overrides]
        self.assertEqual(self.wait(),self.friend)
        details=[d for _,_,d in self.seen]
        self.assertIn('請在 CurseForge 的視窗確認安裝',details[0])
        self.assertIn('已就緒 0／2',''.join(details));self.assertIn('已就緒 1／2',''.join(details))
        self.assertTrue(details[-1].startswith('已就緒 2／2'))
        self.assertGreaterEqual(self.clock.now,15+15)  # and nothing changed for a while afterwards
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            result=patches.apply_patch(self.friend,self.patch,self.home,set_language=True)
        self.assertEqual((len(result['applied']),result['skipped'],result['language_set']),(2,[],True))
        self.assertEqual(json.loads((self.friend/'kubejs/assets/demo/lang/zh_tw.json').read_text(encoding='utf-8'))['demo.hello'],'你好 %s')
        self.assertEqual((self.friend/'options.txt').read_text(encoding='utf-8'),'lang:zh_tw\nresourcePacks:["vanilla","mod_resources","file/MCTranslator-zh_tw.zip"]\n')

    def test_half_downloaded_mod_is_never_taken_for_ready(self):
        (self.friend/'mods').mkdir(parents=True);shutil.copytree(self.original/'kubejs',self.friend/'kubejs')
        (self.friend/'mods/real.jar').write_bytes(b'PK-partial')
        self.assertEqual(patches.modpack_files_ready(self.friend,self.manifest),(1,2))
        # CurseForge finished with another version of the mod: go on with what matches after a long quiet time
        self.assertEqual(self.wait(settle=60),self.friend);self.assertGreaterEqual(self.clock.now,60)
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            result=patches.apply_patch(self.friend,self.patch,self.home)
        self.assertEqual(([Path(f).name for f in result['applied']],[s['file'] for s in result['skipped']]),(['zh_tw.json'],['mods/real.jar']))
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),b'PK-partial')

    def test_waiting_can_be_stopped_and_gives_up_after_a_limit(self):
        stop=[]
        with self.assertRaisesRegex(InterruptedError,'按「安裝翻譯」'):
            patches.wait_for_modpack(self.pack,self.manifest,find=self.listed,cancelled=lambda:bool(stop) or stop.append(1),
                                     clock=self.clock,pause=self.clock.pause)
        with self.assertRaisesRegex(ValueError,'還沒有裝好'):self.wait(timeout=30)
        self.assertFalse(self.friend.exists())

    def test_another_version_of_the_modpack_is_not_the_one_waited_for(self):
        (self.friend/'mods').mkdir(parents=True)
        other=lambda:[dict(name='Demo Pack',path=self.friend,projectID=123,fileID=999)]
        with self.assertRaisesRegex(ValueError,'還沒有裝好'):
            patches.wait_for_modpack(self.pack,self.manifest,find=other,timeout=30,clock=self.clock,pause=self.clock.pause)

    def test_a_modpack_curseforge_just_installed_is_found_before_its_list_is_written(self):
        # CurseForge wrote MinecraftGameInstance.json only later; the instance's own record is read meanwhile.
        user=Path(self.home)/'user';appdata=user/'AppData'
        listed=user/'curseforge/minecraft/Instances/Old';fresh=listed.parent/'Demo Pack'
        for folder in (listed,fresh):(folder/'mods').mkdir(parents=True)
        (fresh/'minecraftinstance.json').write_text(json.dumps(dict(name='Demo Pack',projectID=123,fileID=456,gameVersion='1.21.1')),encoding='utf-8')
        (listed.parent/'half-made').mkdir()  # no record and no mods yet: not a modpack
        store=appdata/'CurseForge/agent/GameInstances';store.mkdir(parents=True)
        (store/'MinecraftGameInstance.json').write_text(json.dumps([dict(name='Old',installPath=str(listed),projectID=1,fileID=2)]),encoding='utf-8')
        with patch.dict('os.environ',{'APPDATA':str(appdata)}),patch('pathlib.Path.home',return_value=user):
            found=jobs.curseforge_instances()
            self.assertEqual(sorted((x['name'],x['projectID'],x['fileID']) for x in found),[('Demo Pack',123,456),('Old',1,2)])
            (store/'MinecraftGameInstance.json').unlink()  # someone whose CurseForge never wrote the list
            self.assertEqual([x['name'] for x in jobs.curseforge_instances()],['Demo Pack'])

    def test_modpack_removed_after_the_list_was_read_goes_to_curseforge(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from mc_zh_tw_translator.desktop import MainWindow
        app=QApplication.instance() or QApplication([])
        entry=dict(self.pack,gameVersion='1.21.1',translator='我',updated='2026-09-30',modpackDate='2026-09-18',revision=1,
                   url='https://raw.githubusercontent.com/x',sha256='a'*64,size=1)
        window=MainWindow(self.home)
        found=[dict(name='Demo Pack',path=self.friend,projectID=123,fileID=456,gameVersion='1.21.1')]
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=found):window.catalog_loaded([entry])
        self.assertEqual([b.text() for b in window.pack_buttons],['安裝翻譯'])
        # the player deletes the modpack in CurseForge, then presses the stale button
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=[]), \
             patch.object(window,'install_pack_and_translation') as install,patch.object(QMessageBox,'information') as told:
            window.apply_catalog_patch(window.catalog[0])
            self.assertEqual([b.text() for b in window.pack_buttons],['安裝整合包與翻譯'])
        self.assertEqual(install.call_args[0][0]['projectID'],123);told.assert_not_called()
        # opening the page again matches the installed modpacks again, without going online
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=found), \
             patch.object(window,'refresh_catalog') as online:
            window.navigate(6)
        online.assert_not_called();self.assertEqual([b.text() for b in window.pack_buttons],['安裝翻譯'])
        window.close()

    def test_card_offers_one_button_and_the_result_shows_the_translators_note(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtGui import QDesktopServices
        from mc_zh_tw_translator.desktop import MainWindow
        app=QApplication.instance() or QApplication([])
        entry=dict(self.pack,gameVersion='1.21.1',translator='我',updated='2026-09-30',modpackDate='2026-09-18',revision=1,
                   url='https://raw.githubusercontent.com/x',sha256='a'*64,size=1)
        window=MainWindow(self.home)
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=[]):window.catalog_loaded([entry])
        self.assertEqual([b.text() for b in window.pack_buttons],['安裝整合包與翻譯'])
        # declined: CurseForge is not even opened
        with patch.object(QMessageBox,'question',return_value=QMessageBox.No) as ask,patch.object(QDesktopServices,'openUrl') as opened, \
             patch.object(window,'run_worker') as run:
            window.install_pack_and_translation(window.catalog[0])
        self.assertIn('由 CurseForge 從官方下載',ask.call_args[0][2]);opened.assert_not_called();run.assert_not_called()
        # no CurseForge on this computer: said so, nothing started
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(QDesktopServices,'openUrl',return_value=False), \
             patch.object(QMessageBox,'warning') as warn,patch.object(window,'run_worker') as run:
            window.install_pack_and_translation(window.catalog[0])
        self.assertIn('沒有安裝 CurseForge',warn.call_args[0][2]);run.assert_not_called()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(QDesktopServices,'openUrl',return_value=True) as opened, \
             patch.object(window,'run_worker') as run:
            window.install_pack_and_translation(window.catalog[0])
        self.assertEqual(opened.call_args[0][0].toString(),'curseforge://install?addonId=123&fileId=456')
        self.assertEqual(run.call_args[0][0],'patch_install')
        done=dict(instance=str(self.friend),applied=['a','b'],already=[],skipped=[],backup='x',language_set=True,installed_modpack=True,notes=self.pack['notes'])
        with patch.object(QMessageBox,'information') as told,patch.object(window,'refresh_catalog'):window.patch_applied(done)
        text=told.call_args[0][2]
        self.assertIn('整合包已由 CurseForge 裝好：Demo Pack',text);self.assertIn('建議記憶體約 12GB',text);self.assertIn('已設為繁體中文',text)
        window.close()


if __name__=='__main__':unittest.main()
