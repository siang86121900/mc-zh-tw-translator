"""Published world backups: conflict checks, consent, local Chinese and safe restore."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mc_zh_tw_translator import backup_mod as b, desktop_jobs as jobs, patches
from mc_zh_tw_translator.class_text import ClassFile
from test_imblocker import jar, pack
from test_install import Served
import test_patches


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.home=self.root/'app'
        self.closed=patch.object(jobs,'ensure_game_closed');self.closed.start();self.addCleanup(self.closed.stop)

    def deps(self, p):
        for name,version in [('architectury','9.2.14'),('polylib','2000.0.3')]:
            with zipfile.ZipFile(p/f'mods/{name}.jar','w') as z:
                z.writestr('META-INF/mods.toml',f'[[mods]]\nmodId="{name}"\nversion="{version}"\n')

    def listing(self):
        javac=shutil.which('javac')
        if not javac:self.skipTest('需要 JDK 建立隔離測試模組')
        source=self.root/'Notice.java'
        source.write_text('public final class Notice { public static String notice(int n) { return "Backup finished in "+n; } }')
        subprocess.run([javac,'--release','17',str(source)],check=True,capture_output=True,timeout=45)
        raw=(self.root/'Notice.class').read_bytes()
        edits={'Notice.class':(hashlib.sha256(raw).hexdigest(),{'Backup finished in \x01':'世界備份完成，耗時 \x01'})}
        original=jar(self.root/'served.jar',b.MOD_ID)
        with zipfile.ZipFile(original,'a') as z:z.writestr('Notice.class',raw)
        data=original.read_bytes();entry=('forge',(1,20),(1,20,1),4834403,'backup-test.jar',len(data),hashlib.sha256(data).hexdigest())
        listing=patch.multiple(b,CLASS_EDITS=edits,FILES=(entry,),KNOWN={entry[6]:entry[5]},LOCALIZED_SHA='')
        listing.start();self.addCleanup(listing.stop)
        translated=self.root/'translated.jar';b.stage_chinese_jar(original,translated)
        sha=hashlib.sha256(translated.read_bytes()).hexdigest()
        localized=patch.object(b,'LOCALIZED_SHA',sha);localized.start();self.addCleanup(localized.stop)
        return data,b.mod_file(entry)['url']

    def test_approved_defaults_and_dependencies(self):
        self.assertEqual((b.CONFIG_VALUES['backup_cron'],b.CONFIG_VALUES['max_backups'],b.CONFIG_VALUES['minimum_free_space']),('0 */30 * * * ?',5,10000))
        self.assertTrue(b.CONFIG_VALUES['only_if_players_been_online'])
        self.assertFalse(b.CONFIG_VALUES['notify_op_only'])
        self.assertFalse(b.CONFIG_VALUES['do_not_notify'])
        self.assertFalse(b.CONFIG_VALUES['free_space_if_needed'])
        for loader in ('forge-47.3.0','neoforge-47.1.106'):
            p=pack(self.root/loader,loader=loader)
            self.assertIn('architectury',b.choose(p)[1]);self.deps(p)
            self.assertEqual(b.choose(p)[0]['fileID'],4834403)
        self.assertIsNone(b.choose(pack(self.root/'new','1.21.1','neoforge-21.1.1'))[0])

    def test_other_backup_disabled_and_settings_are_preserved(self):
        p=pack(self.root/'p');jar(p/'mods/renamed.jar','simplebackups')
        self.assertEqual(b.ensure(p,self.home,session=Served({}))['state'],'other_backup')
        (p/'mods/renamed.jar').rename(p/'mods/renamed.jar.disabled')
        (p/'config').mkdir();(p/'config/textile_backup.json').write_text('{}')
        self.assertIn('textile_backup',b.other_backup(p))
        jar(p/'mods/x.jar.disabled',b.MOD_ID)
        self.assertEqual(b.ensure(p,self.home,session=Served({}))['state'],'disabled')
        self.assertFalse((p/b.CONFIG).exists())

    def test_unknown_existing_version_does_not_change_any_file(self):
        p=pack(self.root/'p');jar(p/'mods/backup.jar',b.MOD_ID)
        (p/'config').mkdir();(p/b.CONFIG).write_text('custom')
        result=b.ensure(p,self.home,session=Served({}))
        self.assertEqual(result['state'],'failed');self.assertIn('尚未核對',result['line'])
        self.assertEqual((p/b.CONFIG).read_text(),'custom')
        self.assertFalse((p/jobs.RESOURCE_PACK_FILE).exists())

    def test_install_chinese_rerun_and_restore(self):
        data,url=self.listing();p=pack(self.root/'p');self.deps(p)
        server=Served({url:data})
        result=b.ensure(p,self.home,session=server,pause=lambda _:None)
        self.assertEqual(result['state'],'installed',result)
        self.assertEqual(server.asked,[url])
        self.assertEqual((p/b.CONFIG).read_bytes(),b.CONFIG_TEXT)
        with zipfile.ZipFile(p/'mods/backup-test.jar') as z:
            vals=ClassFile(z.read('Notice.class')).utf.values()
            self.assertIn('世界備份完成，耗時 \x01',vals)
        with zipfile.ZipFile(p/jobs.RESOURCE_PACK_FILE) as z:
            self.assertEqual(json.loads(z.read(b.LANG)),b.LANG_TEXT)
        self.assertIn(jobs.RESOURCE_PACK_ID,jobs.enabled_packs((p/'options.txt').read_text()))
        again=b.ensure(p,self.home,session=Served({}))
        self.assertEqual((again['state'],again['config_backup']),('present',None),again)
        jobs.restore_backup(Path(result['config_backup']),p)
        self.assertEqual((p/'mods/backup-test.jar').read_bytes(),data)
        jobs.restore_backup(Path(result['backup']),p)
        self.assertFalse((p/'mods/backup-test.jar').exists());self.assertFalse((p/b.CONFIG).exists())

    def test_existing_config_is_byte_preserved_and_mixin_prevents_install(self):
        data,url=self.listing();p=pack(self.root/'p');self.deps(p)
        (p/'config').mkdir();(p/b.CONFIG).write_bytes(b'// owner\r\n{"max_backups":12}\r\n')
        original=(p/b.CONFIG).read_bytes()
        with patch.object(b,'mixin_conflict',return_value='other.jar'),patch.object(patches,'install_mods') as install:
            result=b.ensure(p,self.home,session=Served({}))
            self.assertEqual(result['state'],'unsupported');install.assert_not_called()
        result=b.ensure(p,self.home,session=Served({url:data}),pause=lambda _:None)
        self.assertEqual(result['state'],'installed',result)
        self.assertEqual((p/b.CONFIG).read_bytes(),original)

    def test_modified_class_or_parameters_are_rejected(self):
        self.listing();raw=(self.root/'Notice.class').read_bytes()
        expected,edits=b.CLASS_EDITS['Notice.class']
        with self.assertRaises(ValueError):b.rewrite_class(raw+b'!',expected,edits)
        with self.assertRaises(ValueError):b.rewrite_class(raw,expected,{'Backup finished in \x01':'備份完成'})

    def test_publish_dry_run_and_explicit_opt_out_do_not_install(self):
        import publish_translation as pub
        p=pack(self.root/'p')
        args=SimpleNamespace(no_backup_mod=False,home=self.home,dry_run=True)
        with patch.object(b,'ensure') as ensure:
            pub.add_backup_mod(args,p);args.no_backup_mod=True;args.dry_run=False;pub.add_backup_mod(args,p)
            ensure.assert_not_called()


class SharedBackupTests(unittest.TestCase):
    setUp=BackupTests.setUp
    deps=BackupTests.deps
    listing=BackupTests.listing
    def test_patch_installs_locally_only_with_consent(self):
        test_patches.PatchTests.setUp(self)
        for p in (self.translator,self.friend):
            manifest=json.loads((p/'manifest.json').read_text())
            manifest['minecraft']={'version':'1.20.1','modLoaders':[{'id':'forge-47.3.0','primary':True}]}
            (p/'manifest.json').write_text(json.dumps(manifest))
            record=json.loads((p/'minecraftinstance.json').read_text());record['installedAddons']=[];record['gameVersion']='1.20.1'
            (p/'minecraftinstance.json').write_text(json.dumps(record))
        with patch('mc_zh_tw_translator.imblocker.ensure',return_value=dict(state='unsupported',line='')):
            test_patches.PatchTests.translate(self)
            data,url=self.listing();self.deps(self.translator);self.deps(self.friend)
            first=b.ensure(self.translator,self.home,session=Served({url:data}),pause=lambda _:None)
            self.assertEqual(first['state'],'installed',first)
            out=patches.export_patch(self.translator,self.home)
            with zipfile.ZipFile(out['path']) as z:
                manifest=json.loads(z.read('manifest.json'))
                self.assertTrue(manifest['backup_mod'])
                self.assertEqual(manifest['minimum_app_version'],'0.42.1')
                self.assertFalse(any(n.endswith('.class') for n in z.namelist()))
                self.assertFalse(any(x['file']=='mods/backup-test.jar' for x in manifest['required_mods']))
                self.assertFalse(any(x['file']==b.CONFIG for x in manifest['files']))
                self.assertFalse(any(x.get('fileName')=='backup-test.jar' for x in manifest['left_out_mods']))
            home=self.root/'friend-app'
            declined=patches.apply_patch(self.friend,Path(out['path']),home)
            self.assertIsNone(declined['backup_mod']);self.assertFalse((self.friend/'mods/backup-test.jar').exists())
            result=patches.apply_patch(self.friend,Path(out['path']),home,add_mods=True,session=Served({url:data}))
            self.assertEqual(result['backup_mod']['state'],'installed',result['backup_mod'])
            self.assertEqual((self.friend/b.CONFIG).read_bytes(),b.CONFIG_TEXT)


if __name__=='__main__':unittest.main()
