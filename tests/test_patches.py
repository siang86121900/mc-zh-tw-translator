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
        self.assertIn('payload/mods/real.jar/assets/real/lang/zh_tw.json',names)
        self.assertFalse(any(n.endswith('.class') or 'options.txt' in n for n in names))
        self.assertIn('payload/kubejs/assets/demo/lang/zh_tw.json',names)
        jar=next(f for f in manifest['files'] if f['file']=='mods/real.jar')
        self.assertEqual(list(jar['entries']),['assets/real/lang/zh_tw.json'])

    def test_friend_applies_patch_and_can_restore(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        friend_home=Path(self.temp.name)/'friend-app'
        result=patches.apply_patch(self.friend,Path(out['path']),friend_home,set_language=True)
        self.assertEqual(sorted(result['applied']),['kubejs/assets/demo/lang/zh_tw.json','mods/real.jar'])
        with zipfile.ZipFile(self.friend/'mods/real.jar') as z:
            self.assertEqual(json.loads(z.read('assets/real/lang/zh_tw.json'))['real.a'],'真實')
            self.assertEqual(z.read('real/Main.class'),b'\xca\xfe\xba\xbe')
            self.assertNotIn('META-INF/CERT.SF',z.namelist())
        self.assertIn('lang:zh_tw',(self.friend/'options.txt').read_text(encoding='utf-8'))
        again=patches.apply_patch(self.friend,Path(out['path']),friend_home)
        self.assertEqual((again['applied'],sorted(again['already'])),([],['kubejs/assets/demo/lang/zh_tw.json','mods/real.jar']))
        restore_backup(Path(result['backup']),self.friend)
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),self.friend_jar)
        self.assertFalse((self.friend/'kubejs/assets/demo/lang/zh_tw.json').exists())

    def test_different_mod_version_is_skipped_not_overwritten(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        with zipfile.ZipFile(self.friend/'mods/real.jar','a') as z:z.writestr('assets/real/new.txt','v2')
        changed=(self.friend/'mods/real.jar').read_bytes()
        result=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        self.assertEqual(result['applied'],['kubejs/assets/demo/lang/zh_tw.json'])
        self.assertEqual([s['file'] for s in result['skipped']],['mods/real.jar'])
        self.assertEqual((self.friend/'mods/real.jar').read_bytes(),changed)

    def test_renamed_mod_file_is_found_by_hash(self,_):
        self.translate()
        out=patches.export_patch(self.translator,self.home)
        (self.friend/'mods/real.jar').rename(self.friend/'mods/real-renamed.jar')
        result=patches.apply_patch(self.friend,Path(out['path']),Path(self.temp.name)/'friend-app')
        self.assertIn('mods/real-renamed.jar',result['applied'])

    def test_patch_with_code_or_traversal_is_rejected(self,_):
        bad=Path(self.temp.name)/'bad.zip'
        for item,payload in ((dict(file='mods/real.jar',archive=True,before='0'*64,size=1,entries={'real/Main.class':'0'*64}),'payload/mods/real.jar/real/Main.class'),
                             (dict(file='../evil.json',archive=False,before=None,after='0'*64),'payload/../evil.json'),
                             (dict(file='kubejs/server_scripts/a.js',archive=False,before=None,after='0'*64),'payload/kubejs/server_scripts/a.js')):
            with zipfile.ZipFile(bad,'w') as z:
                z.writestr('manifest.json',json.dumps(dict(format=patches.PATCH_FORMAT,files=[item])));z.writestr(payload,'x')
            with self.assertRaises(ValueError):patches.read_patch(bad)

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


if __name__=='__main__':unittest.main()
