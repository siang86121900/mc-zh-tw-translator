"""IMBlocker before every translation and install: kept when the modpack has it, otherwise the listed
CurseForge file for its Minecraft version and loader, checked and restorable."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import imblocker, patches
from mc_zh_tw_translator.desktop_jobs import restore_backup

from test_install import Served, put


def jar(path,mod_id,kind='forge'):
    with zipfile.ZipFile(path,'w') as z:
        if kind=='fabric':put(z,'fabric.mod.json',json.dumps({'id':mod_id}))
        else:put(z,'META-INF/neoforge.mods.toml' if kind=='neoforge' else 'META-INF/mods.toml',f'modLoader="javafml"\n[[mods]]\nmodId="{mod_id}"\n')
        put(z,mod_id+'/Main.class',b'\xca\xfe\xba\xbe')
    return path


def pack(root,mc='1.20.1',loader='forge-47.3.0'):
    (root/'mods').mkdir(parents=True)
    (root/'manifest.json').write_text(json.dumps({'minecraft':{'version':mc,'modLoaders':[{'id':loader,'primary':True}]}}),encoding='utf-8')
    jar(root/'mods/other.jar','other')
    return root


class ImblockerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'app'

    def chosen(self,mc,loader,folder='p'):
        mod,why=imblocker.choose(pack(self.root/folder,mc,loader))
        return mod['fileName'] if mod else why

    def test_file_for_each_version_and_loader(self):
        self.assertEqual(self.chosen('1.20.1','forge-47.3.0','a'),'IMBlocker-5.6.2.1-forge+1.17-1.20.4.jar')
        self.assertEqual(self.chosen('1.20.1','neoforge-47.1.106','b'),'IMBlocker-5.6.2.1-forge+1.17-1.20.4.jar')  # NeoForge 1.20.1 loads Forge mods
        self.assertEqual(self.chosen('1.21.1','neoforge-21.1.77','c'),'IMBlocker-5.6.2.1-neoforge+1.20.6-1.21.8.jar')
        self.assertEqual(self.chosen('1.16.5','forge-36.2.39','d'),'IMBlocker-5.6.2.1-forge+1.16.5.jar')
        self.assertEqual(self.chosen('1.21.1','fabric-0.16.0','e'),'IMBlocker-5.6.2.1-fabric+1.17-1.21.8.jar')
        self.assertIn('沒有支援 Minecraft 1.12.2',self.chosen('1.12.2','forge-14.23.5','f'))
        self.assertIn('Quilt',self.chosen('1.20.1','quilt-0.26.0','g'))
        # the newer Fabric line needs Fabric API: without it the game would not start
        self.assertIn('Fabric API',self.chosen('1.21.10','fabric-0.17.0','h'))
        jar(self.root/'h/mods/fabric-api.jar','fabric-api','fabric')
        self.assertEqual(imblocker.choose(self.root/'h')[0]['fileName'],'IMBlocker-6.2.2-fabric+1.21.9-1.21.11.jar')

    def test_loader_from_other_records_and_from_the_mods(self):
        prism=self.root/'prism/.minecraft';(prism/'mods').mkdir(parents=True)
        (prism.parent/'mmc-pack.json').write_text(json.dumps({'components':[{'uid':'net.minecraft','version':'1.21.1'},{'uid':'net.neoforged','version':'21.1.1'}]}),encoding='utf-8')
        self.assertEqual(imblocker.pack_loader(prism),('neoforge','1.21.1'))
        bare=self.root/'bare';(bare/'mods').mkdir(parents=True)
        (bare/'minecraftinstance.json').write_text(json.dumps({'gameVersion':'1.20.1'}),encoding='utf-8')
        for i in range(3):jar(bare/f'mods/m{i}.jar',f'm{i}')
        self.assertEqual(imblocker.pack_loader(bare),('forge','1.20.1'))

    def test_listed_files_go_only_to_curseforge_file_servers(self):
        for entry in imblocker.FILES:
            mod=imblocker.mod_file(entry)
            self.assertEqual(patches.file_url(mod),mod['url'])
            self.assertTrue(patches.MOD_FILE_NAME.fullmatch(mod['fileName']))
            self.assertRegex(mod['sha256'],'^[0-9a-f]{64}$')
        self.assertEqual(imblocker.mod_file(imblocker.FILES[4])['url'],
                         'https://mediafilez.forgecdn.net/files/8863/57/IMBlocker-6.2.2-neoforge%2B1.21.9-1.21.11.jar')

    def test_present_or_switched_off_is_left_alone(self):
        p=pack(self.root/'p');jar(p/'mods/input-helper.jar','imblocker')  # renamed: found by its mod id
        server=Served({})
        result=imblocker.ensure(p,self.home,session=server)
        self.assertEqual((result['state'],result['file'],server.asked),('present','input-helper.jar',[]))
        (p/'mods/input-helper.jar').rename(p/'mods/input-helper.jar.disabled')
        result=imblocker.ensure(p,self.home,session=server)
        self.assertEqual((result['state'],server.asked),('disabled',[]))
        self.assertFalse((p/'mods/input-helper.jar').exists())

    def fake_listing(self):
        """The real list with the Forge 1.20.1 file replaced by a small jar this test can serve."""
        data=jar(self.root/'served.jar','imblocker').read_bytes()
        entry=('forge',(1,17),(1,20,4),False,9033569,'IMBlocker-test-forge.jar',len(data),hashlib.sha256(data).hexdigest())
        url=imblocker.mod_file(entry)['url']
        return data,url,patch.object(imblocker,'FILES',(entry,))

    def test_missing_mod_is_installed_checked_and_restorable(self):
        p=pack(self.root/'p');data,url,listing=self.fake_listing();untouched=(p/'mods/other.jar').read_bytes()
        with listing,patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            server=Served({url:data});result=imblocker.ensure(p,self.home,session=server,pause=lambda _:None)
            self.assertEqual((result['state'],server.asked),('installed',[url]))
            self.assertEqual((p/'mods/IMBlocker-test-forge.jar').read_bytes(),data)
            self.assertIn('備份與還原',result['line'])
            again=imblocker.ensure(p,self.home,session=Served({}))
        self.assertEqual(again['state'],'present')
        restore_backup(Path(result['backup']),p)
        self.assertFalse((p/'mods/IMBlocker-test-forge.jar').exists())
        self.assertEqual((p/'mods/other.jar').read_bytes(),untouched)

    def test_a_failed_or_wrong_download_never_stops_the_rest(self):
        p=pack(self.root/'p');data,url,listing=self.fake_listing()
        with listing,patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            for served in ({},{url:data+b'x'}):
                result=imblocker.ensure(p,self.home,session=Served(served),pause=lambda _:None)
                self.assertEqual(result['state'],'failed');self.assertIn('沒有安裝',result['line'])
                self.assertNotIn('404',result['line'].split('（技術細節')[0])
                self.assertEqual(sorted(x.name for x in (p/'mods').iterdir()),['other.jar'])
        bare=self.root/'bare';(bare/'mods').mkdir(parents=True)
        self.assertEqual(imblocker.ensure(bare,self.home,session=Served({}))['state'],'unsupported')

    def test_one_click_translation_checks_before_scanning(self):
        from mc_zh_tw_translator import desktop_jobs as jobs
        order=[]
        with patch.object(imblocker,'ensure',side_effect=lambda *a,**k:order.append('imblocker') or dict(state='installed',line='已安裝')),\
             patch.object(jobs,'plan',side_effect=lambda *a,**k:order.append('scan') or dict(status='blocked')):
            result=jobs.full_translation(self.root,self.home,None,lambda *_:None)
        self.assertEqual(order,['imblocker','scan']);self.assertEqual(result['imblocker']['state'],'installed')

    def test_a_shared_patch_does_not_list_it_as_left_out(self):
        data,_,listing=self.fake_listing();path=self.root/'IMBlocker-test-forge.jar';path.write_bytes(data)
        with listing,patch.dict(imblocker.KNOWN,{hashlib.sha256(data).hexdigest():len(data)}):
            self.assertTrue(imblocker.listed(path))
        self.assertFalse(imblocker.listed(jar(self.root/'x.jar','imblocker')))


if __name__=='__main__':
    unittest.main()
