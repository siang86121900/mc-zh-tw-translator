"""Display-only proofs and actual Java/class/ZIP write-and-restore regression checks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from mc_zh_tw_translator import class_text, desktop_jobs as jobs, codex_bridge as ai


class ClassTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name); source = Path(__file__).parent/'fixtures/class_text'
        javac = shutil.which('javac')
        if not javac:raise unittest.SkipTest('JDK needed to compile regression fixture')
        subprocess.run([javac,'--release','8','-encoding','UTF-8','-d',str(root)]+[str(p) for p in source.rglob('*.java')],check=True,capture_output=True)
        cls.raw=(root/'Sample.class').read_bytes()

    def test_only_proven_uses_and_all_shared_uses(self):
        cf,safe=class_text.proven_strings(self.raw)
        texts={s for s,_ in safe.values()}
        self.assertEqual(len(texts),5)
        self.assertIn('If true, shows food values while holding SHIFT',texts)
        self.assertIn('First configuration comment',texts)
        self.assertIn('Welcome to the world',texts)
        self.assertNotIn('Shared with unsafe comparison',texts)
        self.assertNotIn('Not a display setting',texts)
        self.assertNotIn('Public shared string must stay',texts)
        self.assertNotIn('This is a log message',texts)

    def test_modified_utf8_and_only_expected_bytes_change(self):
        cf,safe=class_text.proven_strings(self.raw)
        key=next(k for k,(s,_) in safe.items() if 'emoji' in s)
        text='保留控制字元 \x01 與星星 🌟'
        rows=[dict(key=str(key),current=safe[key][0],proposed=text)]
        changed=class_text.rewrite(self.raw,rows); checked=class_text.ClassFile(changed)
        self.assertEqual(checked.utf[key],text)
        self.assertEqual(changed[checked.tail:],self.raw[cf.tail:])
        for k,(start,end) in cf.spans.items():
            if k!=key:
                a,b=checked.spans[k];self.assertEqual(changed[a:b],self.raw[start:end])
        class_text.check_java([changed])
        self.assertEqual(class_text.decode_mutf(class_text.encode_mutf('零\x00🌟')), '零\x00🌟')
        with self.assertRaisesRegex(ValueError,'控制字元'):
            class_text.rewrite(self.raw,[dict(rows[0],proposed='控制字元遺失')])

    def test_unsafe_or_changed_source_cannot_be_written(self):
        cf,safe=class_text.proven_strings(self.raw)
        key=next(k for k,s in cf.utf.items() if s=='Shared with unsafe comparison')
        with self.assertRaisesRegex(ValueError,'用途或原文'):
            class_text.rewrite(self.raw,[dict(key=str(key),current=cf.utf[key],proposed='不准改')])
        key=next(iter(safe))
        with self.assertRaisesRegex(ValueError,'用途或原文'):
            class_text.rewrite(self.raw,[dict(key=str(key),current='stale',proposed='不准改')])

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_ai_apply_rerun_restore_and_pack_mode(self,_):
        for mode in ('jar','pack'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);instance=root/'instance';home=root/'app';mods=instance/'mods';mods.mkdir(parents=True)
                jar=mods/'sample.jar'
                with zipfile.ZipFile(jar,'w') as z:
                    z.writestr('Sample.class',self.raw)
                    z.writestr('assets/sample/lang/en_us.json','{}')
                before=jar.read_bytes()
                session=jobs.plan(instance,home,lambda *_:None,references=([{},{}],{'sources':['tw','cn']}))
                session['apply_mode']=mode
                rows=[r for _,r in ai.pending_rows(session) if r['kind']=='class_display']
                self.assertEqual(len(rows),5)
                row=next(r for r in rows if r['current'].startswith('If true'))
                sent=[]
                class Client:
                    def __init__(self,*_):pass
                    def __enter__(self):return self
                    def __exit__(self,*_):pass
                    def models(self):return [dict(model='test-model')]
                    def translate(self,payload,*_):
                        sent.extend(payload)
                        return dict(translations=[dict(id=r['id'],translation='啟用時，按住 SHIFT 顯示食物數值' if r['text'].startswith('If true') else r['text'],note='test') for r in payload])
                ai.supplement(session,home,'test-model',lambda *_:None,client_factory=Client)
                self.assertEqual(session['ai_status'],'completed')
                self.assertEqual(len(sent),5)
                self.assertTrue(all(p['context'] in ('設定說明','玩家顯示文字') for p in sent))
                jobs.prepare_to_apply(session)
                done=jobs.apply_session(session,home,lambda *_:None)
                with zipfile.ZipFile(jar) as z:
                    cf=class_text.ClassFile(z.read('Sample.class'))
                    self.assertEqual(cf.utf[int(row['key'])],row['proposed'])
                again=jobs.plan(instance,home,lambda *_:None,references=([{},{}],{'sources':['tw','cn']}))
                restored=next(r for r in again['rows'] if r['source']==row['source'] and r['key']==row['key'])
                self.assertEqual(restored['origin'],'ai_translation');self.assertTrue(restored['installed'])
                self.assertEqual(jobs.original_of(restored),'If true, shows food values while holding SHIFT')
                self.assertFalse(restored['changed']);self.assertEqual(jobs.applicable_count(again),0)
                self.assertNotIn(restored,[r for _,r in ai.pending_rows(again)])
                jobs.restore_backup(Path(done['backup']),instance)
                self.assertEqual(before,jar.read_bytes())
                third=jobs.plan(instance,home,lambda *_:None,references=([{},{}],{'sources':['tw','cn']}))
                reused=next(r for r in third['rows'] if r['source']==row['source'] and r['key']==row['key'])
                self.assertTrue(reused['ai_reused']);self.assertEqual(reused['proposed'],row['proposed'])

    def test_control_characters_rejected_before_ai_adoption(self):
        row=dict(current='Text \x01',key='1',source='mods/a.jar!/A.class')
        self.assertFalse(ai.adopt({},row,row['current'],dict(translation='文字',note=''),'test',jobs))

    def test_existing_traditional_with_key_name_is_not_sent_to_ai(self):
        _,safe=class_text.proven_strings(self.raw)
        key=next(k for k,(s,_) in safe.items() if s.startswith('If true'))
        raw=class_text.rewrite(self.raw,[dict(key=str(key),current=safe[key][0],proposed='按住 SHIFT 顯示食物數值')])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);mods=root/'instance/mods';mods.mkdir(parents=True)
            with zipfile.ZipFile(mods/'sample.jar','w') as z:z.writestr('Sample.class',raw)
            session=jobs.plan(root/'instance',root/'app',lambda *_:None,references=([{},{}],{'sources':['tw','cn']}))
            self.assertNotIn('按住 SHIFT 顯示食物數值',[jobs.original_of(r) for _,r in ai.pending_rows(session)])
            self.assertEqual(jobs.applicable_count(session),0)


if __name__=='__main__':unittest.main()
