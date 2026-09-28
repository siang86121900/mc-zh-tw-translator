import json
import os
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
            result=ai.supplement(self.session(Path(d),13),Path(d),'account-model',lambda *_:None,client_factory=FailSecond)
            self.assertEqual(result['ai_status'],'paused');self.assertEqual(result['ai_translation'],12)
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


if __name__=='__main__':unittest.main()
