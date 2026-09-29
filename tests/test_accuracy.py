"""What makes later translations more accurate: AI checking doubts, reusing earlier AI work,
and confirming many rows at once."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import codex_bridge as ai, desktop_jobs as jobs
from mc_zh_tw_translator.desktop_jobs import plan, apply_session, full_translation


class FakeClient:
    """Translates by table and reviews by table; records what was sent."""
    sent=[];fixes={};translations={}
    def __init__(self,*_):pass
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def models(self):return [dict(model='account-model',defaultReasoningEffort='low')]
    def translate(self,payload,model,glossary=None):
        self.sent.append(('translate',payload))
        return dict(translations=[dict(id=r['id'],translation=self.translations.get(r['text'],r['text']),note='') for r in payload])
    def review(self,payload,model,glossary=None):
        self.sent.append(('review',payload))
        return dict(translations=[dict(id=r['id'],verdict='fix' if r['text'] in self.fixes else 'ok',
                                       translation=self.fixes.get(r['text'],r['candidate']),note='依原文') for r in payload])


class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'app';self.instance=self.pack('第一包')
        FakeClient.sent=[];FakeClient.fixes={};FakeClient.translations={}

    def pack(self,name,en=None,cn=None):
        instance=self.root/name;lang=instance/'kubejs/assets/demo/lang';lang.mkdir(parents=True)
        (instance/'manifest.json').write_text('{"minecraft":{"version":"1.21.1"}}',encoding='utf-8')
        (lang/'en_us.json').write_text(json.dumps(en or {'a':'Gains 20 experience','b':'Lasts 3 seconds','c':'Plain text','d':'Unknown thing'}),encoding='utf-8')
        (lang/'zh_cn.json').write_text(json.dumps(cn or {'a':'获得 10 点经验','b':'持续 3 秒','c':'普通文字'},ensure_ascii=False),encoding='utf-8')
        return instance

    def make_plan(self,instance=None,references=None):
        return plan(instance or self.instance,self.home,lambda *_:None,references=references or ([{},{}],{'sources':['tw','cn']}))

    def written(self,instance=None):
        return json.loads(((instance or self.instance)/'kubejs/assets/demo/lang/zh_tw.json').read_text(encoding='utf-8'))


class AiReviewTests(Base):
    def review(self,session):
        return ai.review(session,self.home,'account-model',lambda *_:None,client_factory=FakeClient)

    def test_only_concrete_doubts_are_sent_and_each_verdict_is_recorded(self):
        (self.instance/'kubejs/assets/demo/lang/en_us.json').write_text(json.dumps(
            {'a':'Gains 20 experience','b':'Costs 5 gems','c':'Plain text','e':'Lasts 7 seconds'}),encoding='utf-8')
        (self.instance/'kubejs/assets/demo/lang/zh_cn.json').write_text(json.dumps(
            {'a':'获得 10 点经验','b':'花费 8 颗宝石','c':'普通文字','e':'持续 9 秒'},ensure_ascii=False),encoding='utf-8')
        session=self.make_plan();rows={r['key']:r for r in session['rows']}
        self.assertEqual(sorted(r['key'] for _,r in ai.doubt_rows(session)),['a','b','e'])
        FakeClient.fixes={'Gains 20 experience':'獲得 20 點經驗','Lasts 7 seconds':'持續 70 秒'}  # the second fix is wrong itself
        done=self.review(session)
        self.assertEqual([k for k,_ in FakeClient.sent],['review'])
        sent=FakeClient.sent[0][1]
        self.assertEqual({r['text'] for r in sent},{'Gains 20 experience','Costs 5 gems','Lasts 7 seconds'})
        self.assertEqual(set(sent[0]),{'id','text','candidate','doubt','key','source'})  # nothing else leaves the computer
        # rewritten: an AI translation that remembers what it replaced
        self.assertEqual((rows['a']['origin'],rows['a']['proposed'],rows['a']['previous_origin'],rows['a']['previous_proposed']),
                         ('ai_translation','獲得 20 點經驗','same_source_zh_cn','獲得 10 點經驗'))
        self.assertTrue(jobs.needs_check(rows['a']));self.assertFalse(rows['a'].get('number_doubt'))
        # found correct: the source stays, the review is noted beside it, and it leaves the check list
        self.assertEqual((rows['b']['origin'],rows['b']['ai_review']['verdict'],rows['b']['proposed']),('same_source_zh_cn','ok','花費 8 顆寶石'))
        self.assertFalse(jobs.needs_check(rows['b']))
        # a rewrite that changes the number again is not used and the row stays listed
        self.assertEqual((rows['e']['ai_review']['verdict'],rows['e']['proposed']),('rejected','持續 9 秒'))
        self.assertTrue(jobs.needs_check(rows['e']))
        self.assertNotIn('ai_review',rows['c'])
        self.assertEqual((done['ai_review_status'],done['ai_checked']),('completed',1))
        self.assertEqual(ai.doubt_rows(done),[])  # nothing is sent twice

    def test_confirmed_rows_are_never_sent(self):
        session=self.make_plan()
        for r in session['rows']:
            if r['key']=='a':r.update(reviewed=True,review_method='user_confirmed_in_ui')
        self.assertEqual(ai.doubt_rows(session),[])
        with self.assertRaisesRegex(ai.BridgeError,'沒有需要 AI 核對'):self.review(session)
        self.assertEqual(FakeClient.sent,[])

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_rewrite_of_applied_text_waits_to_be_applied_again(self,_):
        session=self.make_plan()
        for r in session['rows']:
            if r['supported'] and r['changed']:r['reviewed']=True
        session=apply_session(session,self.home,lambda *_:None)
        self.assertEqual(self.written()['a'],'獲得 10 點經驗')
        FakeClient.fixes={'Gains 20 experience':'獲得 20 點經驗'}
        session=self.review(session);row=next(r for r in session['rows'] if r['key']=='a')
        self.assertEqual((row['installed'],row['current'],row['changed']),(False,'獲得 10 點經驗',True))
        self.assertEqual(jobs.applicable_count(session),1)
        self.assertEqual(self.written()['a'],'獲得 10 點經驗')  # AI never writes game files itself
        jobs.auto_confirm_safe(session);apply_session(session,self.home,lambda *_:None)
        self.assertEqual(self.written()['a'],'獲得 20 點經驗')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    @patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{'sources':['tw','cn']}))
    def test_one_click_fills_gaps_then_checks_doubts(self,*_):
        FakeClient.translations={'Unknown thing':'未知的東西'};FakeClient.fixes={'Gains 20 experience':'獲得 20 點經驗'}
        supplement,review=ai.supplement,ai.review
        with patch.object(ai,'supplement',lambda *a,**k:supplement(*a,client_factory=FakeClient,**k)),              patch.object(ai,'review',lambda *a,**k:review(*a,client_factory=FakeClient,**k)):
            result=full_translation(self.instance,self.home,'account-model',lambda *_:None)
        self.assertEqual([k for k,_ in FakeClient.sent],['translate','review'])
        self.assertEqual((result['status'],result['ai_status'],result['ai_review_status']),('installed','completed','completed'))
        self.assertEqual(self.written(),{'a':'獲得 20 點經驗','b':'持續 3 秒','c':'普通文字','d':'未知的東西'})

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_gaps_can_be_filled_after_the_batch_was_applied(self,_):
        session=self.make_plan()
        for r in session['rows']:
            if r['supported'] and r['changed']:r['reviewed']=True
        session=apply_session(session,self.home,lambda *_:None)
        FakeClient.translations={'Unknown thing':'未知的東西'}
        session=ai.supplement(session,self.home,'account-model',lambda *_:None,client_factory=FakeClient)
        self.assertEqual(session['ai_status'],'completed');self.assertNotIn('d',self.written())
        jobs.auto_confirm_safe(session);apply_session(session,self.home,lambda *_:None)
        self.assertEqual(self.written()['d'],'未知的東西')


class AiMemoryTests(Base):
    def test_same_sentence_in_another_modpack_is_not_paid_for_twice(self):
        FakeClient.translations={'Unknown thing':'未知的東西'}
        first=ai.supplement(self.make_plan(),self.home,'account-model',lambda *_:None,client_factory=FakeClient)
        self.assertEqual(first['ai_translation'],1)
        second=self.pack('第二包',{'d':'Unknown thing','x':'Another unknown','c':'Plain text'},{'c':'普通文字'})
        rows={r['key']:r for r in self.make_plan(second)['rows']}
        self.assertEqual((rows['d']['origin'],rows['d']['proposed'],rows['d']['ai_reused']),('ai_translation','未知的東西',True))
        self.assertIn('沿用',rows['d']['issue']);self.assertEqual(rows['d']['ai_model'],'account-model')
        self.assertTrue(jobs.needs_check(dict(rows['d'],changed=True)))  # still AI work: listed for checking
        self.assertEqual(rows['x']['origin'],'untranslated')
        self.assertEqual([r['key'] for _,r in ai.pending_rows(dict(rows=list(rows.values())))],['x'])

    def test_every_other_source_comes_before_earlier_ai_work(self):
        jobs.AiMemory(self.home).remember_many([dict(source='instance!/kubejs/assets/demo/lang/en_us.json',key='c',en='Plain text',
                                                     kind='language',proposed='AI 的說法')],'account-model')
        rows={r['key']:r for r in self.make_plan()['rows']}
        self.assertEqual((rows['c']['origin'],rows['c']['proposed']),('same_source_zh_cn','普通文字'))
        changed=self.pack('第三包',{'c':'Plain text, reworded'},{'z':'无关'})
        self.assertEqual({r['key']:r for r in self.make_plan(changed)['rows']}['c']['origin'],'untranslated')  # other English, no reuse


class ConfirmManyTests(Base):
    def test_batch_can_be_undone_and_gives_back_what_it_replaced(self):
        memory=jobs.TranslationMemory(self.home);memory.remember('demo','a','Alpha','舊的確認','s')
        memory.remember_many([('demo','a','Alpha','新的確認','s'),('demo','b','Beta','乙','s')],batch='batch-1')
        self.assertEqual((jobs.TranslationMemory(self.home).lookup('demo','a','Alpha'),memory.lookup('demo','b','Beta')),('新的確認','乙'))
        self.assertEqual(jobs.TranslationMemory(self.home).forget_batch('batch-1'),2)
        again=jobs.TranslationMemory(self.home)
        self.assertEqual((again.lookup('demo','a','Alpha'),again.lookup('demo','b','Beta')),('舊的確認',None))

    def test_report_confirms_what_is_listed_and_can_take_it_back(self):
        from PySide6.QtWidgets import QApplication, QMessageBox
        from mc_zh_tw_translator.desktop import MainWindow
        app=QApplication.instance() or QApplication([])
        window=MainWindow(self.home);window.session=self.make_plan();window.navigate(1)
        window.search.setText('seconds');window.reset_table()
        self.assertEqual(window.confirm_all_btn.text(),'確認目前列出的全部（1 筆）')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes) as ask,patch.object(QMessageBox,'information'):
            window.confirm_listed()
        self.assertIn('1 筆',ask.call_args[0][2])
        rows={r['key']:r for r in window.session['rows']}
        self.assertEqual((rows['b']['review_method'],rows['a'].get('review_method')),('user_confirmed_batch',None))
        self.assertEqual(jobs.TranslationMemory(self.home).lookup('demo','b','Lasts 3 seconds'),'持續 3 秒')
        self.assertFalse(window.undo_confirm_btn.isHidden())
        # The next modpack uses the confirmed text first.
        other=self.pack('第四包',{'b':'Lasts 3 seconds'},{'b':'别的说法 3 秒'})
        self.assertEqual({r['key']:r for r in self.make_plan(other)['rows']}['b']['origin'],'translation_memory')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(QMessageBox,'information'):
            window.undo_confirm_listed()
        self.assertIsNone(jobs.TranslationMemory(self.home).lookup('demo','b','Lasts 3 seconds'))
        self.assertIsNone(rows['b']['review_method']);self.assertTrue(window.undo_confirm_btn.isHidden())
        window.search.setText('');window.set_filter('all')
        with patch.object(QMessageBox,'question',return_value=QMessageBox.No) as ask:window.confirm_listed()
        self.assertIn('3 筆',ask.call_args[0][2])  # gaps and kept-as-is rows are never part of it
        self.assertIsNone(jobs.TranslationMemory(self.home).lookup('demo','c','Plain text'))  # declined: nothing saved
        window.close()


if __name__=='__main__':unittest.main()
