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

    def one_click(self,notify=lambda *_:None,cancelled=lambda:False):
        supplement,review=ai.supplement,ai.review
        with patch.object(ai,'supplement',lambda *a,**k:supplement(*a,client_factory=FakeClient,**k)),\
             patch.object(ai,'review',lambda *a,**k:review(*a,client_factory=FakeClient,**k)),\
             patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{'sources':['tw','cn']})):
            return full_translation(self.instance,self.home,'account-model',notify,cancelled)

    def batches(self):
        return sorted((self.home/'output').glob('*/原始備份/*/_備份紀錄/manifest.json'))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_one_click_writes_what_the_sources_give_before_ai_starts(self,_):
        FakeClient.translations={'Unknown thing':'未知的東西'};seen=[]
        class Watching(FakeClient):
            def translate(inner,payload,model,glossary=None):
                seen.append(dict(self.written()));return FakeClient.translate(inner,payload,model,glossary)
        supplement,review=ai.supplement,ai.review;progress=[]
        with patch.object(ai,'supplement',lambda *a,**k:supplement(*a,client_factory=Watching,**k)),\
             patch.object(ai,'review',lambda *a,**k:review(*a,client_factory=FakeClient,**k)),\
             patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{'sources':['tw','cn']})):
            result=full_translation(self.instance,self.home,'account-model',lambda value,title,detail='':progress.append((value,title,detail)))
        # The game already had the converted text while AI was still being asked.
        self.assertEqual(seen,[{'a':'獲得 10 點經驗','b':'持續 3 秒','c':'普通文字'}])
        self.assertEqual(self.written()['d'],'未知的東西')
        self.assertEqual((result['status'],result['installed_count'],len(self.batches())),('installed',4,2))
        self.assertTrue(all(r.get('installed') for r in result['rows'] if r['changed'] and r['supported']))
        values=[v for v,*_ in progress]
        self.assertEqual(values,sorted(values));self.assertEqual(values[-1],100)  # the bar never runs backwards
        self.assertTrue(any('已經寫入遊戲' in detail for _,title,detail in progress if title=='AI 補翻中'))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_ai_can_finish_a_book_page_the_first_write_created(self,_):
        import zipfile
        (self.instance/'mods').mkdir()
        page=lambda name,text:json.dumps(dict(name=name,pages=[dict(type='text',text=text)]),ensure_ascii=False)
        with zipfile.ZipFile(self.instance/'mods/real.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="real"\n')
            z.writestr('assets/real/lang/en_us.json','{}')
            z.writestr('assets/real/patchouli_books/guide/en_us/entries/a.json',page('Alpha','Unknown thing'))
            z.writestr('assets/real/patchouli_books/guide/zh_cn/entries/a.json',page('阿尔法','Unknown thing'))
        FakeClient.translations={'Unknown thing':'未知的東西'}
        result=self.one_click()
        self.assertEqual((result['status'],result.get('apply_error'),len(self.batches())),('installed',None,2))
        with zipfile.ZipFile(self.instance/'mods/real.jar') as z:
            written=json.loads(z.read('assets/real/patchouli_books/guide/zh_tw/entries/a.json'))
        self.assertEqual((written['name'],written['pages'][0]['text']),('阿爾法','未知的東西'))

    def test_a_write_the_game_blocked_is_tried_again_after_ai(self):
        FakeClient.translations={'Unknown thing':'未知的東西'};calls=[]
        def closed(instance):
            calls.append(1)
            if len(calls)==1:raise jobs.GameRunningError('遊戲正在執行')
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed',closed):
            result=self.one_click()
        self.assertEqual((result['status'],result['installed_count'],len(self.batches())),('installed',4,1))
        self.assertNotIn('apply_error',result)
        self.assertEqual(self.written()['d'],'未知的東西')

    def test_a_game_that_stays_open_keeps_everything_for_a_later_retry(self):
        FakeClient.translations={'Unknown thing':'未知的東西'}
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed',side_effect=jobs.GameRunningError('遊戲正在執行')):
            result=self.one_click()
        self.assertEqual((result['status'],result['installed_count'],result['ai_status']),('awaiting_game',0,'completed'))
        self.assertFalse((self.instance/'kubejs/assets/demo/lang/zh_tw.json').exists())
        self.assertEqual(jobs.applicable_count(result),4)
        with patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed'):
            jobs.prepare_to_apply(result);apply_session(result,self.home,lambda *_:None)
        self.assertEqual(self.written()['d'],'未知的東西')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_stopping_during_ai_keeps_what_was_written(self,_):
        FakeClient.translations={'Unknown thing':'未知的東西'};stop=[]
        class Stopping(FakeClient):
            def translate(inner,payload,model,glossary=None):
                stop.append(1);return FakeClient.translate(inner,payload,model,glossary)
        supplement=ai.supplement
        with patch.object(ai,'supplement',lambda *a,**k:supplement(*a,client_factory=Stopping,**k)),\
             patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{'sources':['tw','cn']})):
            result=full_translation(self.instance,self.home,'account-model',lambda *_:None,lambda:bool(stop))
        self.assertEqual((result['status'],result['installed_count'],len(self.batches())),('installed',3,1))
        self.assertNotIn('d',self.written())
        self.assertEqual(jobs.applicable_count(result),1)  # AI's finished row waits in the report

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


class RepeatedTextTests(Base):
    """The same text in the same file is asked once, so it costs less and is worded the same way."""
    def supplement(self,session):
        return ai.supplement(session,self.home,'account-model',lambda *_:None,client_factory=FakeClient)

    def test_same_text_in_one_file_is_sent_once_and_shared(self):
        instance=self.pack('重複包',{'form.a':'base form','form.b':'base form','form.c':'base form','other':'Unknown thing'},{'z':'无关'})
        FakeClient.translations={'base form':'基礎形態','Unknown thing':'未知的東西'}
        session=self.supplement(self.make_plan(instance));rows={r['key']:r for r in session['rows']}
        sent=[r['text'] for kind,payload in FakeClient.sent for r in payload]
        self.assertEqual(sorted(sent),['Unknown thing','base form'])
        self.assertEqual({rows[k]['proposed'] for k in ('form.a','form.b','form.c')},{'基礎形態'})
        self.assertEqual({rows[k]['origin'] for k in ('form.a','form.b','form.c')},{'ai_translation'})
        self.assertNotIn('相同的原文',rows['form.a']['issue']);self.assertIn('相同的原文',rows['form.b']['issue'])
        self.assertEqual((session['ai_status'],session['ai_translation']),('completed',4))
        self.assertEqual(ai.pending_rows(session),[])
        self.assertFalse(any(r.get('reviewed') for r in rows.values()))  # shared answers are still AI work to check
        # Each key is remembered, so the next modpack reuses all three without asking.
        again=self.pack('重複包二',{'form.a':'base form','form.c':'base form'},{'z':'无关'})
        reused={r['key']:r for r in self.make_plan(again)['rows']}
        self.assertEqual((reused['form.a']['proposed'],reused['form.c']['ai_reused']),('基礎形態',True))

    def test_same_text_in_another_mod_is_asked_separately(self):
        instance=self.pack('兩個模組',{'a':'Odd gadget'},{'z':'无关'})
        other=instance/'kubejs/assets/second/lang';other.mkdir(parents=True)
        (other/'en_us.json').write_text(json.dumps({'a':'Odd gadget'}),encoding='utf-8')
        FakeClient.translations={'Odd gadget':'怪東西'}
        session=self.supplement(self.make_plan(instance))
        sent=[(r['text'],r['source']) for kind,payload in FakeClient.sent for r in payload]
        self.assertEqual(len(sent),2);self.assertEqual(len({source for _,source in sent}),2)
        self.assertEqual(session['ai_translation'],2)

    def test_rejected_answer_is_not_used_for_the_repeats_either(self):
        instance=self.pack('數值包',{'a':'Costs 5 gems','b':'Costs 5 gems'},{'z':'无关'})
        FakeClient.translations={'Costs 5 gems':'花費 8 顆寶石'}
        session=self.supplement(self.make_plan(instance));rows={r['key']:r for r in session['rows']}
        for key in ('a','b'):
            self.assertEqual(rows[key]['origin'],'untranslated');self.assertIn('改動了數值',rows[key]['issue'])
            self.assertEqual(rows[key]['ai_rejected']['text'],'花費 8 顆寶石')
        self.assertEqual((session['ai_translation'],ai.pending_rows(session)),(0,[]))
        # Asked once more in the same run, then left alone.
        self.assertEqual([r['text'] for kind,payload in FakeClient.sent for r in payload],['Costs 5 gems','Costs 5 gems'])


class RejectedAnswerTests(Base):
    """An AI answer the checks turn down is kept for the user and asked once more, told what was wrong."""
    def supplement(self,session):
        return ai.supplement(session,self.home,'account-model',lambda *_:None,client_factory=FakeClient)

    def test_line_count_is_sent_and_a_wrong_count_is_retried_once_with_the_reason(self):
        instance=self.pack('換行包',{'desc':'Line one.\nLine two.\nLine three.'},{'z':'无关'})
        answers=iter(['第一行。第二行。\n第三行。','第一行。\n第二行。\n第三行。'])
        class Retrying(FakeClient):
            def translate(self,payload,model,glossary=None):
                self.sent.append(('translate',payload))
                return dict(translations=[dict(id=r['id'],translation=next(answers),note='') for r in payload])
        session=ai.supplement(self.make_plan(instance),self.home,'account-model',lambda *_:None,client_factory=Retrying)
        first,second=[payload[0] for _,payload in FakeClient.sent]
        self.assertEqual(first['lines'],'2');self.assertNotIn('previous',first)
        self.assertEqual(second['previous'],'第一行。第二行。\n第三行。');self.assertIn('原文 2 個，上次 1 個',second['problem'])
        row=next(r for r in session['rows'] if r['key']=='desc')
        self.assertEqual((row['origin'],row['proposed'],row['ai_retried']),('ai_translation','第一行。\n第二行。\n第三行。',True))
        self.assertNotIn('ai_rejected',row)

    def test_second_rejection_is_final_and_the_answer_stays_visible(self):
        instance=self.pack('換行包二',{'desc':'One.\nTwo.'},{'z':'无关'})
        FakeClient.translations={'One.\nTwo.':'一。二。'}
        session=self.supplement(self.make_plan(instance));row=next(r for r in session['rows'] if r['key']=='desc')
        self.assertEqual(len(FakeClient.sent),2)
        self.assertEqual((row['origin'],row['ai_rejected']['text'],row['ai_rejected']['reason']),('untranslated','一。二。','format'))
        self.assertIn('已再試一次',row['issue'])
        self.assertEqual(ai.pending_rows(session),[]);self.assertEqual(len(ai.asked_rows(session)),1)

    def test_reports_from_before_the_retry_are_asked_once_more(self):
        instance=self.pack('舊報告',{'a':'Costs 5 gems'},{'z':'无关'})
        session=self.make_plan(instance);row=next(r for r in session['rows'] if r['key']=='a')
        row.update(ai_attempted=True,issue=ai.REJECTED['number'])  # what v0.8 left behind
        self.assertEqual(len(ai.pending_rows(session)),1)
        FakeClient.translations={'Costs 5 gems':'花費 5 顆寶石'}
        session=self.supplement(session);row=next(r for r in session['rows'] if r['key']=='a')
        self.assertEqual(FakeClient.sent[0][1][0]['problem'],'上次的譯文沒有通過檢查：'+ai.REJECTED['number'])
        self.assertEqual((row['origin'],row['proposed']),('ai_translation','花費 5 顆寶石'))

    def test_kept_english_is_not_asked_again(self):
        instance=self.pack('專名包',{'a':'Totemus'},{'z':'无关'})
        session=self.supplement(self.make_plan(instance))  # the fake keeps English it has no entry for
        row=next(r for r in session['rows'] if r['key']=='a')
        self.assertEqual(len(FakeClient.sent),1);self.assertIn('AI 保留原文',row['issue'])
        self.assertEqual(ai.pending_rows(session),[])

    def test_added_or_reordered_numbers(self):
        self.assertTrue(jobs.added_numbers('Costs 5 gems','花費 5 或 10 顆寶石'))
        self.assertEqual(jobs.added_numbers('Level 2 needs 10 XP','需要 10 經驗才到 2 級'),'')
        self.assertEqual(jobs.number_doubt('Level 2 needs 10 XP','需要 10 經驗才到 2 級'),'')
        self.assertEqual(jobs.added_numbers('Stores 10k FE','儲存 1萬 FE'),'')


class SameKeyTests(Base):
    """A modpack can hold one key in the mod, in a bundled language pack and in KubeJS assets."""
    MOD='mods/real.jar!/assets/real/lang/en_us.json'
    PACK='config/openloader/packs/cfpa.zip!/assets/real/lang/zh_cn.json'
    KUBEJS='instance!/kubejs/assets/real/lang/zh_cn.json'

    def layered(self,name,en,mod_cn=None,pack_cn=None,kubejs_cn=None,mod_tw=None):
        import zipfile
        instance=self.root/name;(instance/'mods').mkdir(parents=True)
        (instance/'manifest.json').write_text('{"minecraft":{"version":"1.21.1"}}',encoding='utf-8')
        with zipfile.ZipFile(instance/'mods/real.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="real"\n')
            z.writestr('assets/real/lang/en_us.json',json.dumps(en))
            if mod_cn:z.writestr('assets/real/lang/zh_cn.json',json.dumps(mod_cn,ensure_ascii=False))
            if mod_tw:z.writestr('assets/real/lang/zh_tw.json',json.dumps(mod_tw,ensure_ascii=False))
        if pack_cn:
            packs=instance/'config/openloader/packs';packs.mkdir(parents=True)
            with zipfile.ZipFile(packs/'cfpa.zip','w') as z:
                z.writestr('pack.mcmeta','{"pack":{"pack_format":34,"description":"x"}}')
                z.writestr('assets/real/lang/zh_cn.json',json.dumps(pack_cn,ensure_ascii=False))
        if kubejs_cn:
            lang=instance/'kubejs/assets/real/lang';lang.mkdir(parents=True)
            (lang/'zh_cn.json').write_text(json.dumps(kubejs_cn,ensure_ascii=False),encoding='utf-8')
        return instance

    def rows(self,session):
        return {(r['source'],r['key']):r for r in session['rows']}

    def test_reference_without_english_to_compare_is_not_a_match(self):
        instance=self.layered('比對包',{'a':'Battery Upgrade Tier 1','b':'Fuel Upgrade'},
                              pack_cn={'a':'升级：电池，等级1','b':'升级：燃料','c':'只有中文的句子'})
        tw={'real':{'a':'電池升級 T1','b':'舊的燃料升級','c':'沒有英文的參考'},
            '__pairs__':{'real':{'a':[('電池升級 T1','Battery Upgrade Tier 1')],'b':[('舊的燃料升級','Fuel Booster')]}}}
        rows=self.rows(self.make_plan(instance,([tw,{}],{'sources':['tw','cn']})))
        a=rows[(self.PACK,'a')]
        # The pack has no English of its own; the installed mod's English confirms the reference.
        self.assertEqual((a['origin'],a['proposed'],a['issue'],a['en_ref'],a['en']),
                         ('reference_pack_or_cfpa','電池升級 T1','','Battery Upgrade Tier 1',None))
        self.assertFalse(jobs.needs_check(a))
        # Written for other English: the converted Chinese comes first.
        self.assertEqual((rows[(self.PACK,'b')]['origin'],rows[(self.PACK,'b')]['proposed']),('same_source_zh_cn','升級：燃料'))
        # No English anywhere: the reference is not taken as confirmed.
        self.assertEqual((rows[(self.PACK,'c')]['origin'],rows[(self.PACK,'c')]['proposed']),('same_source_zh_cn','只有中文的句子'))
        self.assertNotIn('en_ref',rows[(self.PACK,'c')])

    def test_unconfirmed_reference_is_used_last_and_listed_for_checking(self):
        instance=self.layered('只有參考',{'x':'Other','gone':'Gone thing'})
        tw={'real':{'gone':'沒有英文的參考'}}  # the reference holds no English for this key
        session=self.make_plan(instance,([tw,{}],{'sources':['tw','cn']}))
        row=next(r for r in session['rows'] if r['key']=='gone')
        self.assertEqual((row['origin'],row['proposed']),('stale_reference','沒有英文的參考'))
        self.assertIn('沒有英文可以比對',row['issue']);self.assertTrue(jobs.needs_check(row))
        self.assertEqual(jobs.row_category(row),'version_ref')

    def test_every_file_of_a_key_gets_the_same_translation(self):
        instance=self.layered('三層包',{'a':'To Wither Or Not','b':'Catacomb'},mod_cn={'a':'生存还是凋零','b':'墓穴'},
                              pack_cn={'a':'生存还是凋零⋯⋯','b':'墓穴'},kubejs_cn={'a':'凋零，还是不凋零','b':'地下墓窟'})
        session=self.make_plan(instance);rows=self.rows(session)
        for key,text in (('a','凋零，還是不凋零'),('b','地下墓窟')):
            found={source:rows[(source,key)]['proposed'] for source in (self.MOD,self.PACK,self.KUBEJS)}
            self.assertEqual(set(found.values()),{text},found)  # the modpack's own wording, in all three
        self.assertEqual(rows[(self.KUBEJS,'a')]['origin'],'same_source_zh_cn')
        self.assertEqual(rows[(self.MOD,'a')]['origin'],'instance_zh_cn')

    def test_people_written_taiwan_chinese_of_the_mod_is_not_hidden_by_an_override(self):
        instance=self.layered('繁中包',{'a':'Settings'},mod_tw={'a':'設定'},pack_cn={'a':'设置选项'})
        session=self.make_plan(instance);rows=self.rows(session)
        self.assertFalse(rows[(self.MOD,'a')]['changed'])  # nothing to change in the mod; listed beside the file that follows it
        pack=rows[(self.PACK,'a')]
        self.assertEqual((pack['proposed'],pack['origin'],pack['same_key_as']),('設定','existing_zh_tw',self.MOD))
        self.assertEqual(session['same_key_count'],1)

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_naming_things_alike_reaches_every_file_and_a_second_run_writes_nothing(self,_):
        import zipfile
        instance=self.layered('統一包',{'item.real.palm_log':'Palm Log','item.real.other':'Other thing'},
                              mod_cn={'item.real.palm_log':'棕榈原木','item.real.other':'其他东西'})
        lang=instance/'kubejs/assets/real/lang';lang.mkdir(parents=True)
        (lang/'zh_tw.json').write_text(json.dumps({'item.real.palm_log':'棕櫚原木'},ensure_ascii=False),encoding='utf-8')
        with zipfile.ZipFile(instance/'mods/trees.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="trees"\n')
            z.writestr('assets/trees/lang/en_us.json',json.dumps({'item.trees.palm_log':'Palm Log'}))
        tw={'trees':{'item.trees.palm_log':'棕櫚木原木'},'__pairs__':{'trees':{'item.trees.palm_log':[('棕櫚木原木','Palm Log')]}}}
        def one_click():
            with patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([tw,{}],{'sources':['tw','cn']})):
                return full_translation(instance,self.home,None,lambda *_:None)
        def in_mod():
            with zipfile.ZipFile(instance/'mods/real.jar') as z:return json.loads(z.read('assets/real/lang/zh_tw.json'))['item.real.palm_log']
        first=one_click()
        in_kubejs=lambda:json.loads((lang/'zh_tw.json').read_text(encoding='utf-8'))['item.real.palm_log']
        # the people-written name of another mod is the most trusted; the mod and the file that overrides it both get it
        self.assertEqual((first['status'],in_mod(),in_kubejs()),('installed','棕櫚木原木','棕櫚木原木'))
        files={p:p.read_bytes() for p in instance.rglob('*') if p.is_file()};batches=len(list((self.home/'output').glob('*/原始備份/*')))
        again=one_click()
        self.assertEqual(jobs.applicable_count(again),0)
        self.assertEqual({p:p.read_bytes() for p in instance.rglob('*') if p.is_file()},files)
        self.assertEqual(len(list((self.home/'output').glob('*/原始備份/*'))),batches)

    def test_what_the_user_confirmed_for_the_mod_also_applies_to_the_override(self):
        instance=self.layered('記憶包',{'a':'Direwolf'},mod_cn={'a':'恐狼'},pack_cn={'a':'冰原狼'})
        jobs.TranslationMemory(self.home).remember('real','a','Direwolf','牙狼','test')
        rows=self.rows(self.make_plan(instance))
        self.assertEqual({rows[(s,'a')]['proposed'] for s in (self.MOD,self.PACK)},{'牙狼'})
        self.assertEqual({rows[(s,'a')]['origin'] for s in (self.MOD,self.PACK)},{'translation_memory'})

    def test_chinese_with_other_parameters_than_the_installed_english_is_refused(self):
        instance=self.layered('參數包',{'a':'Divide by %s?','b':'Costs 5 gems'},pack_cn={'a':'§c除以§f8吗？','b':'花费 8 颗宝石'})
        rows=self.rows(self.make_plan(instance))
        self.assertEqual(rows[(self.PACK,'a')]['origin'],'untranslated')
        # a number that differs from the installed English is listed, as it is for rows with their own English
        self.assertIn('數值和原文不同',rows[(self.PACK,'b')]['issue']);self.assertTrue(jobs.needs_check(rows[(self.PACK,'b')]))

    def test_modpack_renamed_text_keeps_its_own_wording(self):
        instance=self.layered('改名包',{'a':'Iron Sword'},mod_cn={'a':'铁剑'})
        lang=instance/'kubejs/assets/real/lang';lang.mkdir(parents=True)
        (lang/'en_us.json').write_text(json.dumps({'a':'Hero Blade'}),encoding='utf-8')
        (lang/'zh_cn.json').write_text(json.dumps({'a':'英雄之刃'},ensure_ascii=False),encoding='utf-8')
        tw={'real':{'a':'鐵製長劍'},'__pairs__':{'real':{'a':[('鐵製長劍','Iron Sword')]}}}
        rows={(r['source'].split('!/')[0],r['key']):r for r in self.make_plan(instance,([tw,{}],{'sources':['tw','cn']}))['rows']}
        renamed=rows[('instance','a')]
        self.assertEqual((renamed['proposed'],renamed['renamed']),('英雄之刃',True))  # not the name of the mod's English
        self.assertEqual(rows[('mods/real.jar','a')]['proposed'],'鐵製長劍')

    def test_differing_ai_answers_for_one_key_become_one_and_confirmed_rows_stay(self):
        row=lambda source,zh,origin='ai_translation',**more:dict(source=source,key='a',kind='language',en='Odd gadget',current=None,
                                                                  proposed=zh,origin=origin,supported=True,changed=True,reviewed=False,**more)
        rows=[row(self.MOD,'怪東西'),row('instance!/kubejs/assets/real/lang/en_us.json','奇怪的裝置'),
              row('config/openloader/packs/x.zip!/assets/real/lang/en_us.json','第三種')]
        self.assertEqual(jobs.unify_same_key(rows),2)
        self.assertEqual({r['proposed'] for r in rows},{'奇怪的裝置'})  # the file the game reads first
        rows=[row(self.MOD,'怪東西'),row('instance!/kubejs/assets/real/lang/en_us.json','我的譯法','manual',review_method='user_confirmed_in_ui'),
              row('config/openloader/packs/x.zip!/assets/real/lang/en_us.json','另一個我的譯法','manual',review_method='user_confirmed_in_ui')]
        self.assertEqual(jobs.unify_same_key(rows),1)  # the unconfirmed row follows; what the user wrote is never replaced
        self.assertEqual([r['proposed'] for r in rows],['我的譯法','我的譯法','另一個我的譯法'])


if __name__=='__main__':unittest.main()
