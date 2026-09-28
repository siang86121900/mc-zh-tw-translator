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
