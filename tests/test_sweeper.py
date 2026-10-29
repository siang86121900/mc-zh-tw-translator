"""Sweeper Maid on published modpacks (使用者 2026-10-29): added only when nothing in the modpack already
clears dropped items, with Taiwanese chat messages, restorable, and installed by the receiver's own app."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib
import json
import re
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import patches, sweeper
from mc_zh_tw_translator.desktop_jobs import restore_backup

from test_imblocker import jar, pack
from test_install import Served
import test_patches


def setUpModule():
    stub=patch('mc_zh_tw_translator.imblocker.ensure',return_value=dict(state='unsupported',line=''))
    stub.start();unittest.addModuleCleanup(stub.stop)


# The English values Forge writes for 1.1.2 (SMCommonConfig), to compare placeholders against.
ENGLISH={
    'OVERLOAD_MESSAGE':'[Sweeper Maid]: The number of dropped items in the region ($1, $2) is too large, with a total of $3 items!',
    'MESSAGE_BEFORE_SWEEP_15_30_60':"[Sweeper Maid]: I'll sweep the floor in $1 seconds!",
    'MESSAGE_BEFORE_SWEEP_1_10':"[Sweeper Maid]: I'll sweep the floor in $1 seconds!",
    'MESSAGE_AFTER_SWEEP':'[Sweeper Maid]: $1 dropped items, $2 unnecessary entities and $3 blacklist items are cleaned during this sweeping.',
    'MESSAGE_WRONG_DUSTBIN':'[Sweeper Maid]: Wrong dustbin.',
    'DUSTBIN_NAME':'Dustbin ',
    'CHAT_MESSAGE_AFTER_SWEEP':"[Sweeper Maid]: Anything's missing? Let's checkout the dustbin:",
}


def fake_listing(root,loader='forge',low=(1,20),high=(1,20,1)):
    """The real list with its file replaced by a small jar this test can serve."""
    data=jar(root/'served.jar','sweeper_maid').read_bytes()
    entry=(loader,low,high,7867270,'sweeper_maid-test.jar',len(data),hashlib.sha256(data).hexdigest())
    return data,sweeper.mod_file(entry)['url'],patch.multiple(sweeper,FILES=(entry,),KNOWN={entry[6]:entry[5]})


def datapack(p):
    (p/'datapacks').mkdir()
    with zipfile.ZipFile(p/'datapacks/c.zip','w') as z:
        z.writestr('data/c/functions/clear.mcfunction','kill @e[type=item,distance=..999]')


class SweeperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'app'

    def test_only_the_1_20_1_forge_file(self):
        self.assertEqual(sweeper.choose(pack(self.root/'a'))[0]['fileName'],'sweeper_maid-1.1.2.jar')
        self.assertEqual(sweeper.choose(pack(self.root/'b',loader='neoforge-47.1.106'))[0]['fileName'],'sweeper_maid-1.1.2.jar')
        for folder,mc,loader in (('c','1.21.1','neoforge-21.1.77'),('d','1.20.1','fabric-0.16.0'),('e','1.19.2','forge-43.2.0')):
            mod,why=sweeper.choose(pack(self.root/folder,mc,loader))
            self.assertIsNone(mod);self.assertIn('1.20.1',why)
        mod=sweeper.mod_file(sweeper.FILES[0])
        self.assertEqual((mod['url'],patches.file_url(mod)),('https://mediafilez.forgecdn.net/files/7867/270/sweeper_maid-1.1.2.jar',)*2)

    def test_something_that_already_clears_items_is_found(self):
        cases={'mod':lambda p:jar(p/'mods/cl.jar','clearlag'),
               'renamed':lambda p:jar(p/'mods/x.jar','fsweep'),
               'config':lambda p:(p/'config').mkdir() or (p/'config/sweeper-common.toml').write_text('',encoding='utf-8'),
               'kubejs':lambda p:(p/'kubejs/server_scripts').mkdir(parents=True) or
                        (p/'kubejs/server_scripts/c.js').write_text("server.runCommandSilent('kill @e[type=minecraft:item]')",encoding='utf-8'),
               'datapack':datapack}
        for name,make in cases.items():
            p=pack(self.root/name);make(p)
            self.assertTrue(sweeper.cleaner(p),name)
        quiet=pack(self.root/'quiet')
        jar(quiet/'mods/edge.jar','sweepingedge');jar(quiet/'mods/off.jar.disabled','clearlag')
        (quiet/'config/attributefix').mkdir(parents=True);(quiet/'config/attributefix/player.sweeping_damage_ratio.json').write_text('{}')
        (quiet/'config/ArrowCleanUp.toml').write_text('',encoding='utf-8')  # stuck arrows only (Craft to Exile 2)
        (quiet/'kubejs/server_scripts').mkdir(parents=True);(quiet/'kubejs/server_scripts/b.js').write_text('entity.kill()',encoding='utf-8')
        self.assertEqual(sweeper.cleaner(quiet),'')

    def test_config_keeps_every_setting_and_placeholder(self):
        values=tomllib.loads(sweeper.CONFIG_TEXT.decode('utf-8'))['sweeper_maid-common-config']
        self.assertEqual((values['ITEM_SWEEP_INTERVAL'],values['DUSTBIN_COUNT'],values['PERMISSION_LEVEL_DUSTBIN']),(600,8,0))
        for key,english in ENGLISH.items():
            self.assertEqual(re.findall(r'\$\d',values[key]),re.findall(r'\$\d',english),key)
            self.assertRegex(values[key],'[一-鿿]',key)
        self.assertTrue(values['DUSTBIN_NAME'].endswith(' '))  # the number follows the name

    def test_a_pack_with_its_own_cleaner_gets_nothing(self):
        p=pack(self.root/'p');jar(p/'mods/cl.jar','clearlag')
        with patch.object(patches,'install_mods') as install:
            result=sweeper.ensure(p,self.home,session=Served({}))
        install.assert_not_called()
        self.assertEqual(result['state'],'cleaner');self.assertIn('cl.jar',result['line'])
        self.assertFalse((p/sweeper.CONFIG).exists())

    def test_missing_mod_is_installed_with_chinese_messages_and_restorable(self):
        p=pack(self.root/'p');data,url,listing=fake_listing(self.root)
        with listing,patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            server=Served({url:data});result=sweeper.ensure(p,self.home,session=server,pause=lambda _:None)
            self.assertEqual((result['state'],server.asked),('installed',[url]))
            self.assertEqual((p/'mods/sweeper_maid-test.jar').read_bytes(),data)
            self.assertEqual((p/sweeper.CONFIG).read_bytes(),sweeper.CONFIG_TEXT)
            self.assertIn('/sweepermaid dustbin',result['line'])
            again=sweeper.ensure(p,self.home,session=Served({}))
        self.assertEqual((again['state'],again['config_backup']),('present',None))
        restore_backup(Path(result['config_backup']),p);restore_backup(Path(result['backup']),p)
        self.assertFalse((p/'mods/sweeper_maid-test.jar').exists());self.assertFalse((p/sweeper.CONFIG).exists())

    def test_present_or_switched_off_keeps_the_owners_settings(self):
        p=pack(self.root/'p');jar(p/'mods/maid.jar','sweeper_maid')
        (p/'config').mkdir();(p/sweeper.CONFIG).write_text('ITEM_SWEEP_INTERVAL = 1200\n',encoding='utf-8')
        result=sweeper.ensure(p,self.home,session=Served({}))
        self.assertEqual(result['state'],'present')
        self.assertEqual((p/sweeper.CONFIG).read_text(encoding='utf-8'),'ITEM_SWEEP_INTERVAL = 1200\n')
        (p/'mods/maid.jar').rename(p/'mods/maid.jar.disabled')
        self.assertEqual(sweeper.ensure(p,self.home,session=Served({}))['state'],'disabled')


@patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
class SharedSweeperTests(unittest.TestCase):
    """The published patch asks the receiver's app to add the same file; it is never left out or required."""
    def setUp(self):
        test_patches.PatchTests.setUp(self)  # same translator and friend copies of one pack

    def translate(self):
        return test_patches.PatchTests.translate(self)

    def test_receiver_installs_it_and_the_patch_stays_complete(self,_):
        self.translate()
        data,url,listing=fake_listing(Path(self.temp.name),'neoforge',(1,21),(1,21,1))
        with listing:
            first=sweeper.ensure(self.translator,self.home,session=Served({url:data}),pause=lambda _:None)
            self.assertEqual(first['state'],'installed')
            out=patches.export_patch(self.translator,self.home)
            with zipfile.ZipFile(out['path']) as z:manifest=json.loads(z.read('manifest.json'))
            self.assertTrue(manifest['sweeper'])
            self.assertEqual((manifest['sharing_status'],manifest['left_out_mods'],manifest['minimum_app_version']),('ready',[],'0.41.0'))
            self.assertNotIn('mods/sweeper_maid-test.jar',[m['file'] for m in manifest['required_mods']])
            self.assertFalse(any(f['file'] in (sweeper.CONFIG,'mods/sweeper_maid-test.jar') for f in manifest['files']))
            friend_home=Path(self.temp.name)/'friend-app'
            declined=patches.apply_patch(self.friend,Path(out['path']),friend_home)
            self.assertIsNone(declined['sweeper']);self.assertFalse((self.friend/'mods/sweeper_maid-test.jar').exists())
            server=Served({url:data})
            result=patches.apply_patch(self.friend,Path(out['path']),friend_home,add_mods=True,session=server)
        self.assertEqual(result['sweeper']['state'],'installed')
        self.assertEqual((self.friend/sweeper.CONFIG).read_bytes(),sweeper.CONFIG_TEXT)



if __name__=='__main__':
    unittest.main()
