import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import codex_bridge as ai


def limits(used=20, credits=False):
    return {'rateLimits': {'primary': {'usedPercent': used, 'windowDurationMins': 300},
                          'credits': {'hasCredits': credits, 'unlimited': False}}}


def row(n):
    return dict(supported=True,origin='untranslated',reviewed=False,changed=False,
                key=f'test.{n}',source='instance!/kubejs/assets/demo/lang/en_us.json',
                en=f'Hello {n}',current=None,proposed=f'Hello {n}',issue='')


class FakeClient:
    calls=[]
    def __init__(self,*_):pass
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def models(self):return [dict(model='account-model',defaultReasoningEffort='medium')]
    def translate(self,payload,model):
        self.calls.append((payload,model))
        return dict(translations=[dict(id=r['id'],translation=r['text'].replace('Hello','你好'),note='名稱待確認') for r in payload])


class CodexBridgeTests(unittest.TestCase):
    def setUp(self):FakeClient.calls=[]

    def test_api_and_unknown_plans_rejected(self):
        for account in (None,{'type':'apiKey'}, {'type':'chatgpt','planType':'business'}, {'type':'chatgpt','planType':'unknown'}):
            with self.assertRaises(ai.BridgeError):ai.quota_guard(account,limits())

    def test_no_extra_credits_or_unknown_quota(self):
        account=dict(type='chatgpt',planType='plus')
        self.assertEqual(ai.quota_guard(account,limits())[0]['remaining'],80)
        for value in ({},limits(90),limits(100),limits(20,True)):
            with self.assertRaises(ai.BridgeError):ai.quota_guard(account,value)
        self.assertTrue(ai.quota_guard(account, {'rateLimits': {'primary': {'usedPercent': 20}}}))
        for used in (None,True,-1,float('nan'),'0'):
            with self.assertRaises(ai.BridgeError):ai.quota_guard(account,limits(used))

    def test_multibucket_does_not_hide_exhausted_model(self):
        value=limits();value['rateLimitsByLimitId']={'codex':limits()['rateLimits'],'other':limits(95)['rateLimits']}
        with self.assertRaises(ai.BridgeError):ai.quota_guard(dict(type='chatgpt',planType='pro'),value)

    def test_other_models_reserved_quota_does_not_block(self):
        # Shape of a real Plus account: Codex quota fine, a reserve for one specific model used up.
        value=limits();reserve=dict(limitId='base_model_inference',limitName='gpt-reserve',normalModelSlug='gpt-5.6-luna',
                                    primary=dict(usedPercent=100,windowDurationMins=10080),secondary=None,credits=None)
        value['rateLimitsByLimitId']={'codex':limits()['rateLimits'],'base_model_inference':reserve}
        account=dict(type='chatgpt',planType='plus')
        self.assertEqual(ai.quota_guard(account,value)[0]['remaining'],80)
        self.assertTrue(ai.quota_guard(account,value,'gpt-6-astra'))
        with self.assertRaises(ai.BridgeError):ai.quota_guard(account,value,'gpt-5.6-luna')  # that model's own reserve
        self.assertEqual(ai.model_quotas(value)['gpt-5.6-luna']['remaining'],0)

    def test_recommended_model_follows_official_description_and_quota(self):
        models=[dict(model='top',description='Frontier intelligence for the most demanding work.',isDefault=True),
                dict(model='old-fast',description='Older fast and efficient model.'),
                dict(model='fast',description='Fast and affordable model for easier tasks.')]
        self.assertEqual(ai.recommended_model(models)[0]['model'],'fast')  # current before older, whatever the order
        used_up={'fast':dict(remaining=0)}
        self.assertEqual(ai.recommended_model(models,used_up)[0]['model'],'old-fast')  # its own quota is gone
        self.assertEqual(ai.recommended_model(models,{'fast':dict(remaining=0),'old-fast':dict(remaining=10)})[0]['model'],'top')
        plain=[dict(model='a'),dict(model='b',isDefault=True)]
        model,reason=ai.recommended_model(plain)
        self.assertEqual(model['model'],'b');self.assertIn('官方預設',reason)  # nothing described as fast
        self.assertEqual(ai.recommended_model([]),(None,''))
        self.assertEqual(ai.recommended_model(plain,{'a':dict(remaining=0),'b':dict(remaining=5)}),(None,''))

    def test_official_description_is_translated_only_when_known(self):
        self.assertEqual(ai.describe_model(dict(description='Fast and affordable model for easier tasks.')),'快速、省額度的模型，適合較簡單的工作。')
        self.assertEqual(ai.describe_model(dict(description=' legacy coding model ')),'舊版的程式模型。')
        self.assertEqual(ai.describe_model(dict(description='A brand new kind of model.')),'A brand new kind of model.')
        self.assertEqual(ai.describe_model(dict(model='x')),'')

    def test_child_cannot_inherit_api_keys_or_auth_proxy(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret','OPENAI_BASE_URL':'https://evil.test','CODEX_AUTH_JSON':'secret','CODEX_HOME':'outside','CODEX_ACCESS_TOKEN':'secret'}):
            env=ai.child_environment(Path('isolated'))
        self.assertNotIn('OPENAI_API_KEY',env);self.assertNotIn('OPENAI_BASE_URL',env)
        self.assertNotIn('CODEX_AUTH_JSON',env);self.assertNotIn('CODEX_ACCESS_TOKEN',env)
        self.assertEqual(env['CODEX_HOME'],str(Path('isolated/codex-account')))

    def test_only_official_login_urls(self):
        ai.validate_login_url('https://auth.openai.com/oauth/authorize?x=1')
        for url in ('http://auth.openai.com/','https://auth.openai.com.evil.test/','https://user@chatgpt.com/','file:///x'):
            with self.assertRaises(ai.BridgeError):ai.validate_login_url(url)

    def session(self,path,count=2):
        return dict(status='needs_review',rows=[row(n) for n in range(count)],report=str(path),errors=[],source_hashes={},source_counts={'untranslated':count})

    def test_model_selection_provenance_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            session=self.session(Path(d));session['rows'][1]['origin']='same_source_zh_cn'
            result=ai.supplement(session,Path(d),'account-model',lambda *_:None,client_factory=FakeClient)
            self.assertEqual(result['ai_status'],'completed');self.assertEqual(result['ai_translation'],1)
            r=result['rows'][0];self.assertEqual(r['ai_model'],'account-model');self.assertFalse(r['reviewed'])
            self.assertEqual(r['origin'],'ai_translation');self.assertEqual(r['proposed'],'你好 0')
            self.assertEqual(len(FakeClient.calls[0][0]),1)
            self.assertEqual(ai.pending_rows(result),[])
            saved=json.loads((Path(d)/'session.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['rows'][0]['ai_model'],'account-model')

    def test_missing_selected_model_never_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d)),Path(d),'missing',lambda *_:None,client_factory=FakeClient)
            self.assertEqual(result['ai_status'],'paused');self.assertEqual(FakeClient.calls,[])

    def test_failed_batch_preserves_previous_batches(self):
        class FailSecond(FakeClient):
            def translate(self,payload,model):
                if self.calls:raise ai.BridgeError('quota stopped')
                return super().translate(payload,model)
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d),ai.BATCH_ROWS+1),Path(d),'account-model',lambda *_:None,client_factory=FailSecond)
            self.assertEqual(result['ai_status'],'paused');self.assertEqual(result['ai_translation'],ai.BATCH_ROWS)
            self.assertIn('再按一次「一鍵完整翻譯並套用」',result['ai_message'])
            self.assertEqual(len(ai.pending_rows(result)),1)

    def test_invalid_row_is_rejected_alone_and_never_reviewed(self):
        class Bad(FakeClient):
            def translate(self,payload,model):
                result=super().translate(payload,model);result['translations'][-1]['translation']='數值被改成 99'
                return result
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d)),Path(d),'account-model',lambda *_:None,client_factory=Bad)
            self.assertEqual(result['ai_status'],'completed')
            rows=result['rows'];self.assertEqual(rows[0]['origin'],'ai_translation')
            self.assertEqual(rows[-1]['origin'],'untranslated');self.assertIn('退回原文',rows[-1]['issue'])
            self.assertFalse(any(r.get('reviewed') for r in rows))
            self.assertEqual(ai.pending_rows(result),[])  # the rejected row is not resent automatically

    def test_duplicate_ids_rejected(self):
        class Bad(FakeClient):
            def translate(self,payload,model):
                result=super().translate(payload,model);result['translations'][1]['id']='0';return result
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d)),Path(d),'account-model',lambda *_:None,client_factory=Bad)
            self.assertEqual(result['ai_status'],'paused');self.assertEqual(len(ai.pending_rows(result)),2)

    def test_cancel_before_turn_spends_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d)),Path(d),'account-model',lambda *_:None,lambda:True,FakeClient)
            self.assertEqual(result['ai_status'],'paused');self.assertEqual(FakeClient.calls,[])

    def test_bad_runtime_digest_never_installed(self):
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'assets':[]}
        class Session:
            def get(self,*args,**kwargs):return Response()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ai.BridgeError):ai.install_runtime(Path(d),lambda *_:None,session=Session())
            self.assertFalse((Path(d)/'runtime/codex.exe').exists())


def said(thread,rows):
    return dict(method='item/completed',params=dict(threadId=thread,item=dict(type='agentMessage',id='m-'+thread,
                text=json.dumps(dict(translations=rows),ensure_ascii=False))))


def ended(thread,status='completed'):
    return dict(method='turn/completed',params=dict(threadId=thread,turn=dict(id='turn-'+thread,status=status)))


class Wire(ai.CodexClient):
    """The real client over a scripted connection: `plan` lists what arrives after each batch is started."""
    def __init__(self,plan,used=20,refuse_second=False):
        self.messages=queue.Queue();self.events=[];self.sequence=0;self.process=None;self.cancelled=lambda:False
        self.last_quota=None;self.work=Path('.');self.sent=[];self.plan=plan;self.used=used;self.refuse_second=refuse_second
    def count(self,method):return sum(v.get('method')==method for v in self.sent)
    def send(self,value):
        self.sent.append(value);method=value.get('method')
        def reply(result):self.messages.put(dict(id=value['id'],result=result))
        if method=='account/read':reply(dict(account=dict(type='chatgpt',planType='plus')))
        elif method=='account/rateLimits/read':reply(limits(self.used))
        elif method=='thread/start':
            if self.refuse_second and self.count(method)==2:self.messages.put(dict(id=value['id'],error=dict(code=-32000)))
            else:reply(dict(thread=dict(id=f'thread-{self.count(method)}'),model=value['params']['model']))
        elif method=='turn/start':
            thread=value['params']['threadId'];reply(dict(turn=dict(id='turn-'+thread)))
            for event in self.plan.get(thread,[]):self.messages.put(event)


MODEL=dict(model='account-model',defaultReasoningEffort='low')
FIRST=[dict(id='0',translation='第一批',note='')];SECOND=[dict(id='1',translation='第二批',note='')]
REQUESTS=[([dict(id='0',text='one')],None),([dict(id='1',text='two')],None)]


class SeveralBatchesAtOnceTests(unittest.TestCase):
    def test_each_batch_gets_its_own_reply_and_quota_is_checked_once(self):
        # The first batch's text arrives while the second is still being started; it finishes last.
        wire=Wire({'thread-1':[said('thread-1',FIRST)],'thread-2':[said('thread-2',SECOND),ended('thread-2'),ended('thread-1')]})
        self.assertEqual(wire.translate_many(REQUESTS,MODEL),[dict(translations=FIRST),dict(translations=SECOND)])
        self.assertEqual((wire.count('turn/start'),wire.count('account/rateLimits/read'),wire.count('turn/interrupt')),(2,1,0))
        self.assertEqual(wire.last_quota[0]['remaining'],80)

    def test_one_batch_failing_does_not_throw_away_the_other(self):
        wire=Wire({'thread-2':[ended('thread-1','failed'),said('thread-2',SECOND),ended('thread-2')]})
        first,second=wire.translate_many(REQUESTS,MODEL)
        self.assertIsInstance(first,ai.BridgeError);self.assertIn('未完成',str(first))
        self.assertEqual(second,dict(translations=SECOND))

    def test_a_second_batch_the_service_refuses_is_reported_as_not_sent(self):
        wire=Wire({'thread-1':[said('thread-1',FIRST),ended('thread-1')]},refuse_second=True)
        self.assertEqual(wire.translate_many(REQUESTS,MODEL),[dict(translations=FIRST),None])
        self.assertEqual(wire.count('turn/start'),1)

    def test_quota_running_low_stops_what_is_still_being_written_and_keeps_what_finished(self):
        wire=Wire({'thread-1':[said('thread-1',FIRST),ended('thread-1')],
                   'thread-2':[dict(method='account/rateLimits/updated',params=limits(95))]})
        first,second=wire.translate_many(REQUESTS,MODEL)
        self.assertEqual(first,dict(translations=FIRST))
        self.assertIsInstance(second,ai.BridgeError);self.assertIn('10%',str(second))
        stopped=[v['params'] for v in wire.sent if v.get('method')=='turn/interrupt']
        self.assertEqual(stopped,[dict(threadId='thread-2',turnId='turn-thread-2')])

    def test_quota_already_low_sends_nothing(self):
        wire=Wire({},used=90)
        with self.assertRaises(ai.BridgeError):wire.translate_many(REQUESTS,MODEL)
        self.assertEqual(wire.count('thread/start'),0)

    def test_tool_use_in_any_batch_stops_the_whole_group(self):
        tool=dict(method='item/started',params=dict(threadId='thread-2',item=dict(type='commandExecution',id='x')))
        wire=Wire({'thread-2':[tool]})
        first,second=wire.translate_many(REQUESTS,MODEL)
        self.assertIn('非翻譯功能',str(first));self.assertIs(first,second)
        self.assertEqual(wire.count('turn/interrupt'),2)

    def test_single_request_still_raises_like_before(self):
        wire=Wire({'thread-1':[ended('thread-1','failed')]})
        with self.assertRaises(ai.BridgeError):wire.translate([dict(id='0',text='one')],MODEL)
        good=Wire({'thread-1':[said('thread-1',FIRST),ended('thread-1')]})
        self.assertEqual(good.translate([dict(id='0',text='one')],MODEL),dict(translations=FIRST))


class Together(FakeClient):
    """A client that can take several batches at once; records how many came in each call."""
    groups=[];refuse=False;fail_second=False;last_quota=None
    def translate_many(self,requests,model):
        self.groups.append(len(requests))
        replies=[self.translate(payload,model) for payload,_ in requests]
        if self.refuse:replies[1:]=[None]*(len(replies)-1);del self.calls[-(len(requests)-1):]
        if self.fail_second:replies[1]=ai.BridgeError('AI 本批未完成')
        return replies


class GroupedSupplementTests(unittest.TestCase):
    def setUp(self):FakeClient.calls=[];Together.groups=[];Together.refuse=Together.fail_second=False;Together.last_quota=None

    def session(self,path,count):
        return dict(status='needs_review',rows=[row(n) for n in range(count)],report=str(path),errors=[],source_hashes={},source_counts={'untranslated':count})

    def sent_ids(self):return [r['id'] for payload,_ in FakeClient.calls for r in payload]

    def test_batches_go_out_two_at_a_time(self):
        with tempfile.TemporaryDirectory() as d:
            seen=[]
            result=ai.supplement(self.session(Path(d),ai.BATCH_ROWS*3+1),Path(d),'account-model',lambda *a:seen.append(a[2]),client_factory=Together)
        self.assertEqual((result['ai_status'],result['ai_translation']),('completed',ai.BATCH_ROWS*3+1))
        self.assertEqual(Together.groups,[2,2]);self.assertIn('同時送 2 批',seen[0])
        self.assertEqual(sorted(self.sent_ids(),key=int),[str(n) for n in range(ai.BATCH_ROWS*3+1)])  # nothing twice, nothing missed

    def test_refused_batch_is_sent_again_alone_and_the_rest_go_one_at_a_time(self):
        Together.refuse=True
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d),ai.BATCH_ROWS*3),Path(d),'account-model',lambda *_:None,client_factory=Together)
        self.assertEqual((result['ai_status'],result['ai_translation']),('completed',ai.BATCH_ROWS*3))
        self.assertEqual(Together.groups,[2])  # after the refusal every batch goes out alone
        self.assertEqual(self.sent_ids(),[str(n) for n in range(ai.BATCH_ROWS*3)])

    def test_failed_batch_in_a_group_keeps_the_finished_one(self):
        Together.fail_second=True
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d),ai.BATCH_ROWS*3),Path(d),'account-model',lambda *_:None,client_factory=Together)
            saved=json.loads((Path(d)/'session.json').read_text(encoding='utf-8'))
        self.assertEqual((result['ai_status'],result['ai_translation']),('paused',ai.BATCH_ROWS))
        self.assertEqual(len(ai.pending_rows(result)),ai.BATCH_ROWS*2)  # the failed and the unsent batch wait for next time
        self.assertEqual(saved['ai_translation'],ai.BATCH_ROWS)

    def test_one_batch_at_a_time_when_quota_is_getting_low(self):
        Together.last_quota=[dict(remaining=60,minutes=10080),dict(remaining=ai.PARALLEL_FLOOR,minutes=300)]
        with tempfile.TemporaryDirectory() as d:
            result=ai.supplement(self.session(Path(d),ai.BATCH_ROWS*2),Path(d),'account-model',lambda *_:None,client_factory=Together)
        self.assertEqual((result['ai_status'],result['ai_translation']),('completed',ai.BATCH_ROWS*2))
        self.assertEqual(Together.groups,[]);self.assertEqual(len(FakeClient.calls),2)


if __name__=='__main__':unittest.main()
