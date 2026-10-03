import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_embedded_text as embedded_fixture
import test_data_pack as quest_fixture
from mc_zh_tw_translator import desktop_jobs as jobs, patches, shared_text


@patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
class SharedTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.sender=root/'sender';self.friend=root/'friend';self.home=root/'app';self.friend_home=root/'friend-app'
        (self.sender/'mods').mkdir(parents=True)
        (self.sender/'config/openloader/data').mkdir(parents=True)
        (self.sender/'manifest.json').write_text('{"minecraft":{"version":"1.20.1"}}',encoding='utf-8')
        with zipfile.ZipFile(self.sender/'mods/openloader.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="openloader"\n')
        with zipfile.ZipFile(self.sender/'mods/demo.jar','w') as z:
            z.writestr('META-INF/mods.toml','modLoader="javafml"\n[[mods]]\nmodId="demo"\n')
            z.writestr(quest_fixture.QUEST,json.dumps(quest_fixture.quest(),ensure_ascii=False))
        (self.sender/'datapacks').mkdir()
        with zipfile.ZipFile(self.sender/'datapacks/world.zip','w') as z:
            z.writestr('pack.mcmeta','{"pack":{"pack_format":15,"description":"fixture"}}')
            z.writestr('data/demo/structures/shop.nbt',embedded_fixture.nbt({'entities':[{'nbt':{'CustomName':'"Shop Keeper"'}}]}))
            z.writestr('data/demo/functions/hello.mcfunction','tellraw @a {"text":"Welcome back"}\n')
        menu=self.sender/'config/fancymenu/customization/menu.txt';menu.parent.mkdir(parents=True)
        menu.write_text('type = fancymenu_layout\n\ncustomization {\n  label = Start Game\n  hoverlabel = Click to play\n}\n',encoding='utf-8')
        shader=self.sender/'shaderpacks/Test Shader/shaders/lang';shader.mkdir(parents=True)
        (shader/'en_us.lang').write_text('option.sun=Sun Brightness\n',encoding='utf-8')
        (shader/'zh_cn.lang').write_text('option.sun=太阳亮度\n',encoding='utf-8')
        shutil.copytree(self.sender,self.friend)

    def translate(self):
        session=jobs.plan(self.sender,self.home,lambda *_:None,references=([{},{}],{'fixture':True}))
        answers={'Start Game':'開始遊戲','Click to play':'點擊開始遊玩','Shop Keeper':'商店店員','Welcome back':'歡迎回來'}
        for row in session['rows']:
            original=jobs.original_of(row)
            if row.get('supported') and original in answers:
                row.update(proposed=answers[original],origin='ai_translation',changed=True)
            elif row.get('supported') and original=='{"text":"Welcome back"}':
                row.update(proposed='{"text":"歡迎回來"}',origin='ai_translation',changed=True)
            if row.get('supported') and row.get('changed'):row['reviewed']=True
        session['set_language']=True
        return jobs.apply_session(session,self.home,lambda *_:None)

    def test_text_only_recipes_install_same_words_repeat_without_writes_and_restore(self,_):
        before={p.relative_to(self.friend).as_posix():p.read_bytes() for p in self.friend.rglob('*') if p.is_file()}
        self.translate();out=patches.export_patch(self.sender,self.home)
        z,m=patches.read_patch(Path(out['path']));names=z.namelist();z.close()
        self.assertEqual(m['format'],shared_text.FORMAT)
        self.assertTrue({'data_text','embedded_text'}<={u['kind'] for u in m['text_units']})
        self.assertFalse(any(n.endswith(('.class','.nbt','.jar','.mcfunction')) for n in names))
        self.assertFalse(any(n.startswith('payload/config/fancymenu') or jobs.DATA_PACK_FILE in n for n in names))
        with patch.object(jobs,'refresh',side_effect=AssertionError('安裝不得重選翻譯來源')):
            done=patches.apply_patch(self.friend,Path(out['path']),self.friend_home,set_language=True)
        self.assertEqual(done['consistency'],'matched',done)
        self.assertFalse(done['sender_omitted']);self.assertFalse(done['readback_mismatch'])
        for file in ('config/fancymenu/customization/menu.txt','datapacks/world.zip','shaderpacks/Test Shader/shaders/lang/zh_tw.lang',jobs.DATA_PACK_FILE):
            self.assertEqual((self.sender/file).read_bytes(),(self.friend/file).read_bytes(),file)
        again=patches.apply_patch(self.friend,Path(out['path']),self.friend_home,set_language=True)
        self.assertFalse(again['applied'],again)
        self.assertIsNone(again['backup']);self.assertEqual(again['consistency'],'matched',again)
        # An installed recipe keeps its original text, so a receiver can later export it too.
        shared_again=patches.export_patch(self.friend,self.friend_home)
        z,m2=patches.read_patch(Path(shared_again['path']));z.close()
        self.assertTrue(any(u['kind']=='data_text' for u in m2['text_units']))
        jobs.restore_backup(Path(done['backup']),self.friend)
        self.assertEqual({p.relative_to(self.friend).as_posix():p.read_bytes() for p in self.friend.rglob('*') if p.is_file()},before)

    def test_missing_module_and_changed_original_are_reported_as_partial(self,_):
        self.translate();out=patches.export_patch(self.sender,self.home)
        (self.friend/'mods/demo.jar').unlink()
        changed=self.friend/'config/fancymenu/customization/menu.txt'
        changed.write_text('customization {\n  label = Play Again\n}\n',encoding='utf-8')
        done=patches.apply_patch(self.friend,Path(out['path']),self.friend_home,set_language=True)
        self.assertEqual(done['consistency'],'partial')
        self.assertIn('mods/demo.jar',done['missing_mods'])
        self.assertTrue(done['skipped']);self.assertIn('Play Again',changed.read_text(encoding='utf-8'))

    def test_external_data_cannot_grant_write_permission_or_change_machine_values(self,_):
        self.translate();out=patches.export_patch(self.sender,self.home)
        z,m=patches.read_patch(Path(out['path']));contents={n:z.read(n) for n in z.namelist()};z.close()
        unit=next(u for u in m['text_units'] if u['kind']=='data_text')
        unit.update(key='["id"]',original='demo:main/find_irena',current='demo:main/find_irena',text='demo:main/broken')
        bad=Path(self.tmp.name)/'bad.zip'
        with zipfile.ZipFile(bad,'w') as w:
            for name,data in contents.items():w.writestr(name,json.dumps(m,ensure_ascii=False) if name=='manifest.json' else data)
        done=patches.apply_patch(self.friend,bad,self.friend_home,set_language=True)
        self.assertEqual(done['consistency'],'partial')
        self.assertTrue(any(s.get('key')=='["id"]' for s in done['skipped']))
        with zipfile.ZipFile(self.friend/jobs.DATA_PACK_FILE) as w:self.assertEqual(json.loads(w.read(quest_fixture.QUEST))['id'],'demo:main/find_irena')
        unit['source']='saves/world/data/test.json'
        with self.assertRaises(ValueError):shared_text.validate([unit],patches.clean_path)

    def test_sender_omission_stays_visible_and_saves_are_untouched(self,_):
        saves=self.friend/'saves/world/region';saves.mkdir(parents=True)
        (saves/'r.0.0.mca').write_bytes(b'existing NPC and progress fixture')
        self.translate();out=patches.export_patch(self.sender,self.home)
        z,m=patches.read_patch(Path(out['path']));contents={n:z.read(n) for n in z.namelist()};z.close()
        m['skipped']=[dict(file='example.txt',reason='用途尚未確認')]
        m['sharing_status']='partial'
        modified=Path(self.tmp.name)/'partial.zip'
        with zipfile.ZipFile(modified,'w') as w:
            for name,data in contents.items():w.writestr(name,json.dumps(m,ensure_ascii=False) if name=='manifest.json' else data)
        done=patches.apply_patch(self.friend,modified,self.friend_home,set_language=True)
        self.assertEqual(done['consistency'],'partial');self.assertEqual(done['sender_omitted'],m['skipped'])
        self.assertIn('存檔',done['save_note'])
        self.assertEqual((saves/'r.0.0.mca').read_bytes(),b'existing NPC and progress fixture')

    def test_applied_history_without_matching_file_text_is_not_shared(self,_):
        self.translate()
        reports=self.home/'output'/self.sender.name/'報告'
        changed=None
        for path in reports.glob('*/session.json'):
            session=json.loads(path.read_text(encoding='utf-8'))
            row=next((r for r in session['rows'] if r['kind']=='embedded_text' and r.get('installed') and r.get('changed')),None)
            if row:
                row['proposed']='另一位店員';changed=row
                path.write_text(json.dumps(session,ensure_ascii=False),encoding='utf-8');break
        self.assertIsNotNone(changed)
        out=patches.export_patch(self.sender,self.home)
        z,m=patches.read_patch(Path(out['path']));z.close()
        self.assertEqual(m['sharing_status'],'partial')
        self.assertTrue(any(e['source']==changed['source'] and e['key']==changed['key'] and '實際讀取' in e['reason'] for e in m['text_omissions']))
        self.assertFalse(any(u['source']==changed['source'] and u['key']==changed['key'] for u in m['text_units']))
        done=patches.apply_patch(self.friend,Path(out['path']),self.friend_home)
        self.assertEqual(done['consistency'],'partial')
        self.assertTrue(done['sender_text_omissions'])

    def test_a_claimed_result_hash_cannot_bypass_the_original_version_check(self,_):
        self.translate();out=patches.export_patch(self.sender,self.home)
        z,m=patches.read_patch(Path(out['path']));contents={n:z.read(n) for n in z.namelist()};z.close()
        unit=next(u for u in m['text_units'] if 'fancymenu' in u['source'])
        file=shared_text.source_file(unit['source']);real_hash=unit['requires'][file]
        unit['requires'][file]='1'*64;unit['source_after']=real_hash
        m['source_hash_aliases']={u['source_after']:h for u in m['text_units'] for h in u['requires'].values() if u['source_after']!=h}
        bad=Path(self.tmp.name)/'fake-result.zip'
        with zipfile.ZipFile(bad,'w') as w:
            for name,data in contents.items():w.writestr(name,json.dumps(m,ensure_ascii=False) if name=='manifest.json' else data)
        done=patches.apply_patch(self.friend,bad,self.friend_home,set_language=True)
        self.assertTrue(any(s.get('key')==unit['key'] for s in done['skipped']))
        self.assertEqual(done['consistency'],'partial')

    def test_proven_class_constants_share_no_bytecode_and_are_checked_on_receiver(self,_):
        compiler=shutil.which('javac')
        if not compiler:self.skipTest('JDK required for the real class fixture')
        root=Path(self.tmp.name)/'compiled';root.mkdir()
        fixtures=Path(__file__).parent/'fixtures/class_text'
        subprocess.run([compiler,'--release','8','-encoding','UTF-8','-d',str(root)]+[str(p) for p in fixtures.rglob('*.java')],check=True,capture_output=True)
        jar=self.sender/'mods/help.jar'
        with zipfile.ZipFile(jar,'w') as z:
            z.writestr('fabric.mod.json','{"schemaVersion":1,"id":"help"}')
            for name in ('ItemHelp','ItemHelp$1','ItemHelp$Tip'):z.writestr(name+'.class',(root/(name+'.class')).read_bytes())
        shutil.copyfile(jar,self.friend/'mods/help.jar');original=jar.read_bytes()
        self.translate()
        session=jobs.plan(self.sender,self.home,lambda *_:None,references=([{},{}],{'fixture':True}))
        for row in session['rows']:
            if row['kind']=='class_display' and row['current']=='Required' and row['supported']:
                row.update(proposed='必要',origin='ai_translation',changed=True,reviewed=True)
        session['set_language']=True;jobs.apply_session(session,self.home,lambda *_:None)
        out=patches.export_patch(self.sender,self.home)
        z,m=patches.read_patch(Path(out['path']));self.assertFalse(any(n.endswith('.class') for n in z.namelist()));z.close()
        self.assertTrue(any(u['kind']=='class_display' for u in m['text_units']))
        done=patches.apply_patch(self.friend,Path(out['path']),self.friend_home,set_language=True)
        self.assertEqual(done['consistency'],'matched',done)
        self.assertEqual(jar.read_bytes(),(self.friend/'mods/help.jar').read_bytes())
        again=patches.apply_patch(self.friend,Path(out['path']),self.friend_home,set_language=True)
        self.assertFalse(again['applied'],again)
        jobs.restore_backup(Path(done['backup']),self.friend)
        self.assertEqual((self.friend/'mods/help.jar').read_bytes(),original)
        (self.friend/'minecraftinstance.json').write_text(json.dumps({'installedAddons':[{'installedFile':{'fileName':'help.jar'}}]}),encoding='utf-8')
        managed=patches.apply_patch(self.friend,Path(out['path']),self.friend_home,set_language=True)
        self.assertEqual(managed['consistency'],'partial')
        self.assertTrue(any('help.jar' in s['file'] for s in managed['skipped']))
        self.assertEqual((self.friend/'mods/help.jar').read_bytes(),original)
