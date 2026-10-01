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
        cls.config=(root/'ConfigSample.class').read_bytes();cls.main=(root/'ModMain.class').read_bytes()
        cls.dev=(root/'DevSample.class').read_bytes()
        cls.mixin_raw=(root/'SampleMixin.class').read_bytes()

    def test_log_and_exception_text_is_told_apart_from_player_text(self):
        cf=class_text.ClassFile(self.dev);found={cf.utf[i] for i in class_text.developer_strings(self.dev)}
        self.assertEqual(found,{'Loaded the config file from disk','Could not parse the entry {}','Registry object was not present here'})
        # Also shown to the player in one place: still a candidate to check, not set aside.
        self.assertNotIn('Welcome back to the world',found);self.assertNotIn('Shown to every single player',found)

    def test_config_comments_link_to_their_tooltip_keys(self):
        cf,safe=class_text.proven_strings(self.config);tips=class_text.config_tooltips(self.config)
        found={safe[k][0]:v for k,v in tips.items()}
        self.assertEqual(found['Shows the saturation bar'],[('name','showSaturation',0,1)])
        self.assertEqual(found['Uses the mod key'],[('key','sample.config.alpha',0,1)])
        self.assertEqual(found['First line of help'],[('name','twoLines',0,2)])
        self.assertEqual(found['Second line of help'],[('name','twoLines',1,2)])
        # A section comment and a value whose name is computed are not linked to any key.
        self.assertNotIn('Section about food',found);self.assertNotIn('Name is not a constant',found)

    def test_shared_tooltip_conflicts_and_existing_language_are_not_overwritten(self):
        from full_translation_audit import exclude_tooltip_conflicts
        def row(text,part=0,parts=1):
            return dict(source='mods/sample.jar!/A.class',key=text,kind='class_display',current=text,
                        tooltips=[['sample.help.tooltip',part,parts,'assets/sample/lang/zh_tw.json']])
        for rows in ([row('First meaning'),row('Other meaning')],
                     [row('First line',0,2),row('Second line',1,2),row('First line')]):
            exclude_tooltip_conflicts(rows)
            self.assertTrue(all(not r.get('tooltips') for r in rows))
            self.assertTrue(all('原文不同' in r['tooltip_note'] for r in rows))
        rows=[row('Comment'),dict(source='mods/sample.jar!/assets/sample/lang/en_us.json',key='sample.help.tooltip',kind='language')]
        exclude_tooltip_conflicts(rows)
        self.assertNotIn('tooltips',rows[0]);self.assertIn('語系條目',rows[0]['tooltip_note']);self.assertTrue(rows[0]['tooltip_in_language'])
        rows=[row('Same comment'),row('Same comment')]
        exclude_tooltip_conflicts(rows)
        self.assertTrue(all(r.get('tooltips') for r in rows))
        for r,text in zip(rows,['第一個譯法','第二個譯法']):r.update(proposed=text,supported=True,origin='ai_translation')
        self.assertEqual(jobs.tooltip_texts(rows),{})
        with tempfile.TemporaryDirectory() as folder:
            instance=Path(folder);(instance/'minecraftinstance.json').write_text('{}')
            for r in rows:r.update(changed=True,reviewed=True)
            self.assertEqual(jobs.applicable_count(dict(instance=str(instance),rows=rows)),0)
        rows[1]['proposed']=rows[0]['proposed']
        self.assertEqual(list(jobs.tooltip_texts(rows).values()),['第一個譯法'])

    def test_same_comment_in_two_classes_gets_one_wording(self):
        # L_Ender's Cataclysm defines "Range Cap" in two config classes; AI worded the copies differently.
        tip=[['cataclysm.range_cap.tooltip',0,1,'assets/cataclysm/lang/zh_tw.json']]
        rows=[dict(source=f'mods/c.jar!/{name}.class',key='9',kind='class_display',current='Range Cap',en=None,
                   proposed=text,origin='ai_translation',supported=True,changed=True,tooltips=tip)
              for name,text in (('A','範圍上限'),('B','射程上限'))]
        rows.append(dict(rows[0],source='mods/c.jar!/C.class',proposed='我確認的說法',origin='manual'))
        self.assertEqual(jobs.tooltip_texts(rows),{})
        rows.pop()
        self.assertEqual(jobs.unify_same_key(rows),1)
        self.assertEqual({r['proposed'] for r in rows},{'範圍上限'})
        self.assertEqual(list(jobs.tooltip_texts(rows).values()),['範圍上限'])
        # What the user confirmed is never replaced: the other copy takes the confirmed wording.
        rows[1].update(proposed='我確認的說法',origin='manual')
        self.assertEqual(jobs.unify_same_key(rows),1);self.assertEqual(rows[1]['proposed'],'我確認的說法')

    def test_comment_the_screen_shows_from_the_language_file_is_not_counted_twice(self):
        # AppleSkin ships '<key>.tooltip' in its own en_us/zh_tw: the screen shows that, not the class comment.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instance=self.config_instance(root,lang={'sample.configuration.showSaturation.tooltip':'顯示飽和度條'})
            session=jobs.plan(instance,root/'app',lambda *_:None,references=([{},{}],{'sources':['tw','cn']}))
            texts=[r['current'] for r in session['rows'] if r['kind']=='class_display']
            self.assertNotIn('Shows the saturation bar',texts);self.assertIn('Uses the mod key',texts)
            self.assertEqual(jobs.coverage(session).get('unwritable',0),2)  # only the section and the computed name

    def test_strings_of_a_language_file_generator_are_not_left_to_check(self):
        # torchesbecomesunlight: ZhCnProvider holds 驮兽肉 for building zh_cn.json; the game reads the json.
        gen=(Path(self.tmp.name)/'LangGen.class').read_bytes()
        for ships_lang in (True,False):
            with tempfile.TemporaryDirectory() as folder:
                instance=Path(folder)/'instance';(instance/'mods').mkdir(parents=True)
                with zipfile.ZipFile(instance/'mods/sample.jar','w') as z:
                    z.writestr('LangGen.class',gen)
                    z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="sample"\n')
                    if ships_lang:
                        z.writestr('assets/sample/lang/en_us.json',json.dumps({'item.sample.meat':'Burden Beast Meat'}))
                        z.writestr('assets/sample/lang/zh_cn.json',json.dumps({'item.sample.meat':'驮兽肉'},ensure_ascii=False))
                session=jobs.plan(instance,Path(folder)/'app',lambda *_:None,references=([{},{}],{'sources':['tw','cn']}))
                rows=[r for r in session['rows'] if r['kind']=='class_candidate' and r['current'] in ('驮兽肉','纠察队弯刀')]
                self.assertEqual(len(rows),2)
                states={jobs.row_state(r) for r in rows}
                # Without the mod's own language file nothing proves where the game reads it: still listed.
                self.assertEqual(states,{None} if ships_lang else {'candidate'},ships_lang)
                if ships_lang:
                    self.assertTrue(all('產生語系檔' in r['issue'] for r in rows))
                    self.assertEqual(next(r for r in session['rows'] if r['key']=='item.sample.meat' and r['kind']=='language')['proposed'],'馱獸肉')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_text_another_mods_mixin_changes_is_never_rewritten(self,_):
        # The Foll: RevelationFix's Mixin looks for one GoetyRevelation config comment; once it was translated
        # the game stopped loading. Text in a class a Mixin targets stays as it is, and v0.18.0's goes back.
        mixin=(Path(self.tmp.name)/'SampleMixin.class').read_bytes()
        refs=([{},{}],{'sources':['tw','cn']})
        answers={'If true, shows food values while holding SHIFT':'啟用時，按住 SHIFT 顯示食物數值'}
        everything={s:s for s,_ in class_text.proven_strings(self.raw)[1].values()}  # the rest kept as it is
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instance=root/'instance';home=root/'app';mods=instance/'mods';mods.mkdir(parents=True)
            with zipfile.ZipFile(mods/'sample.jar','w') as z:
                z.writestr('Sample.class',self.raw);z.writestr('assets/sample/lang/en_us.json','{}')
            # what v0.18.0 did: the comment was written into the class
            session=jobs.plan(instance,home,lambda *_:None,references=refs)
            ai.supplement(session,home,'test-model',lambda *_:None,client_factory=self.client(dict(everything,**answers)))
            jobs.prepare_to_apply(session);jobs.apply_session(session,home,lambda *_:None)
            with zipfile.ZipFile(mods/'sample.jar') as z:self.assertNotEqual(z.read('Sample.class'),self.raw)
            old=json.loads(json.dumps(session))
            # the fix mod, in a jar of its own
            with zipfile.ZipFile(mods/'fix.jar','w') as z:z.writestr('SampleMixin.class',mixin)
            session=jobs.plan(instance,home,lambda *_:None,references=refs)
            self.assertEqual(session['mixin_targets'],['Sample'])
            rows=[r for r in session['rows'] if r['kind']=='class_display']
            back=[r for r in rows if r['changed']]
            self.assertEqual([(r['proposed'],r['origin']) for r in back],[('If true, shows food values while holding SHIFT','keep_original')])
            self.assertTrue(all(jobs.HELD_MIXIN in r['issue'] for r in rows))
            self.assertFalse([r for r in rows if r['supported'] and not r['changed']])
            self.assertFalse([r for _,r in ai.pending_rows(session) if r['kind']=='class_display'])  # never sent to AI
            jobs.prepare_to_apply(session);jobs.apply_session(session,home,lambda *_:None)
            with zipfile.ZipFile(mods/'sample.jar') as z:self.assertEqual(z.read('Sample.class'),self.raw)  # the original again
            again=jobs.plan(instance,home,lambda *_:None,references=refs)
            self.assertFalse([r for r in again['rows'] if r['kind']=='class_display' and r['changed']])  # and it stays so
            # A report made before this version knows no Mixins: retrying it writes no program text.
            old.pop('mixin_targets',None)
            for r in old['rows']:r.update(installed=False)  # as if it had never been written
            with self.assertRaisesRegex(ValueError,'舊版程式產生'):jobs.apply_session(old,home,lambda *_:None)
            with zipfile.ZipFile(mods/'sample.jar') as z:self.assertEqual(z.read('Sample.class'),self.raw)

    def config_instance(self, root, screen=True, lang=None):
        instance=root/'instance';mods=instance/'mods';mods.mkdir(parents=True)
        (instance/'minecraftinstance.json').write_text('{}',encoding='utf-8')  # CurseForge puts changed mods back
        with zipfile.ZipFile(mods/'sample.jar','w') as z:
            z.writestr('ConfigSample.class',self.config)
            if screen:z.writestr('ModMain.class',self.main)
            z.writestr('META-INF/neoforge.mods.toml','modLoader="javafml"\n[[mods]]\nmodId="sample"\n[[dependencies.sample]]\nmodId="neoforge"\n')
            english={'item.sample.x':'Thing',**{k:'Shows the saturation bar' for k in lang or {}}}
            z.writestr('assets/sample/lang/en_us.json',json.dumps(english))
            z.writestr('assets/sample/lang/zh_tw.json',json.dumps({'item.sample.x':'東西',**(lang or {})},ensure_ascii=False))
        return instance

    CHINESE={'Shows the saturation bar':'顯示飽和度條','Uses the mod key':'使用模組語系鍵','First line of help':'說明第一行',
             'Second line of help':'說明第二行','Section about food':'食物相關設定','Name is not a constant':'名稱不是常數'}

    def client(self, answers):
        class Client:
            def __init__(self,*_):pass
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def models(self):return [dict(model='test-model')]
            def translate(self,payload,*_):
                return dict(translations=[dict(id=r['id'],translation=answers[r['text']],note='test') for r in payload if r['text'] in answers])
        return Client

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_curseforge_config_comments_go_to_the_translation_pack(self,_):
        refs=([{},{}],{'sources':['tw','cn']})
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instance=self.config_instance(root);home=root/'app';jar=instance/'mods/sample.jar'
            before=jar.read_bytes()
            session=jobs.plan(instance,home,lambda *_:None,references=refs)
            rows={r['current']:r for r in session['rows'] if r['kind']=='class_display'}
            self.assertEqual(rows['Shows the saturation bar']['tooltips'],[['sample.configuration.showSaturation.tooltip',0,1,'assets/sample/lang/zh_tw.json']])
            self.assertEqual(rows['Uses the mod key']['tooltips'],[['sample.config.alpha.tooltip',0,1,'assets/sample/lang/zh_tw.json']])
            self.assertTrue(rows['Shows the saturation bar']['supported'])
            self.assertFalse(rows['Section about food']['supported'])  # still held: CurseForge would undo a class change
            self.assertEqual(jobs.row_category(rows['Section about food']),'held')
            ai.supplement(session,home,'test-model',lambda *_:None,client_factory=self.client(self.CHINESE))
            jobs.prepare_to_apply(session)
            done=jobs.apply_session(session,home,lambda *_:None)
            self.assertEqual(before,jar.read_bytes())  # the mod itself is never changed
            with zipfile.ZipFile(instance/jobs.RESOURCE_PACK_FILE) as z:
                lang=json.loads(z.read('assets/sample/lang/zh_tw.json'))
            self.assertEqual(lang['sample.configuration.showSaturation.tooltip'],'顯示飽和度條')
            self.assertEqual(lang['sample.config.alpha.tooltip'],'使用模組語系鍵')
            self.assertEqual(lang['sample.configuration.twoLines.tooltip'],'說明第一行\n說明第二行')
            self.assertEqual(lang['item.sample.x'],'東西')  # the mod's own zh_tw stays in the pack's copy
            written=[r for r in session['rows'] if r.get('tooltips') and r.get('installed')]
            self.assertEqual(len(written),4);self.assertTrue(all(r['shown'] for r in written))
            self.assertEqual(session['shown_mismatch'],0)
            # A rerun recognises what the pack holds and writes nothing.
            again=jobs.plan(instance,home,lambda *_:None,references=refs)
            back={r['current']:r for r in again['rows'] if r['kind']=='class_display'}
            self.assertTrue(back['Shows the saturation bar']['installed']);self.assertEqual(back['Shows the saturation bar']['proposed'],'顯示飽和度條')
            self.assertEqual(back['Shows the saturation bar']['origin'],'ai_translation')
            self.assertEqual(jobs.applicable_count(again),0)
            self.assertNotIn(back['Shows the saturation bar'],[r for _,r in ai.pending_rows(again)])
            jobs.restore_backup(Path(done['backup']),instance)
            self.assertFalse((instance/jobs.RESOURCE_PACK_FILE).exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_tooltip_needs_the_screen_or_a_key_and_every_line(self,_):
        refs=([{},{}],{'sources':['tw','cn']})
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instance=self.config_instance(root,screen=False);home=root/'app'
            session=jobs.plan(instance,home,lambda *_:None,references=refs)
            rows={r['current']:r for r in session['rows'] if r['kind']=='class_display'}
            # Without NeoForge's config screen only the mod's own key is looked up (Configured does the same).
            self.assertNotIn('tooltips',rows['Shows the saturation bar']);self.assertFalse(rows['Shows the saturation bar']['supported'])
            self.assertIn('tooltips',rows['Uses the mod key'])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);instance=self.config_instance(root);home=root/'app'
            session=jobs.plan(instance,home,lambda *_:None,references=refs)
            ai.supplement(session,home,'test-model',lambda *_:None,client_factory=self.client(self.CHINESE))
            second=next(r for r in session['rows'] if r['current']=='Second line of help')
            second.update(origin='untranslated',proposed=second['current'],changed=False)
            jobs.prepare_to_apply(session)
            jobs.apply_session(session,home,lambda *_:None)
            with zipfile.ZipFile(instance/jobs.RESOURCE_PACK_FILE) as z:
                lang=json.loads(z.read('assets/sample/lang/zh_tw.json'))
            self.assertNotIn('sample.configuration.twoLines.tooltip',lang)  # half a comment is not written
            first=next(r for r in session['rows'] if r['current']=='First line of help')
            self.assertFalse(first.get('installed'));self.assertEqual(session['held_back'],{jobs.HELD_TOOLTIP_PARTS:1})

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
