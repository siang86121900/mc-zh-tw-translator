"""Safeguards: interrupted writes, disk space, picking the wrong folder, plain errors, reference
lookups that survive GitHub's query allowance, number and character-form checks, patch limits."""
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from mc_zh_tw_translator import desktop_jobs as jobs, desktop_references as references, patches, updater
from mc_zh_tw_translator.desktop_jobs import plan, apply_session, restore_backup


class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.instance=root/'測試模組包';self.home=root/'app'
        self.lang=self.instance/'kubejs/assets/demo/lang';self.lang.mkdir(parents=True)
        (self.instance/'manifest.json').write_text('{"minecraft":{"version":"1.21.1"}}',encoding='utf-8')

    def write(self,en,cn=None,tw=None):
        (self.lang/'en_us.json').write_text(json.dumps(en),encoding='utf-8')
        if cn is not None:(self.lang/'zh_cn.json').write_text(json.dumps(cn,ensure_ascii=False),encoding='utf-8')
        if tw is not None:(self.lang/'zh_tw.json').write_text(json.dumps(tw,ensure_ascii=False),encoding='utf-8')

    def make_plan(self,references=None):
        return plan(self.instance,self.home,lambda *_:None,references=references or ([{},{}],{'sources':['tw','cn']}))

    def applied(self,keys=None):
        result=self.make_plan()
        for r in result['rows']:
            if r['supported'] and r['changed'] and (keys is None or r['key'] in keys):r['reviewed']=True
        with patch.object(jobs,'ensure_game_closed'):return apply_session(result,self.home,lambda *_:None)


class InterruptedWriteTests(Base):
    def journal(self,backup,**changes):
        path=Path(backup)/'_備份紀錄/manifest.json';record=json.loads(path.read_text(encoding='utf-8'))
        record.update(changes);path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8');return path

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_batch_cut_short_while_writing_can_be_restored(self,_):
        self.write({'a':'Alpha','b':'Beta'},{'a':'阿尔法','b':'贝塔'})
        extra=self.instance/'kubejs/assets/other/lang';extra.mkdir(parents=True)
        (extra/'en_us.json').write_text('{"c":"Gamma"}',encoding='utf-8');(extra/'zh_cn.json').write_text('{"c":"伽玛"}',encoding='utf-8')
        done=self.applied()
        (extra/'zh_tw.json').unlink()  # the power went out before this file was written
        journal=self.journal(done['backup'],status='backed_up')
        self.assertEqual([b.name for b,_ in jobs.interrupted_batches(self.home,self.instance)],[Path(done['backup']).name])
        restore_backup(Path(done['backup']),self.instance)
        self.assertFalse((self.lang/'zh_tw.json').exists());self.assertFalse((extra/'zh_tw.json').exists())
        self.assertEqual(json.loads(journal.read_text(encoding='utf-8'))['status'],'restored')
        self.assertEqual(jobs.interrupted_batches(self.home),[])

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_restore_cut_short_continues_and_never_overwrites_later_edits(self,_):
        self.write({'a':'Alpha'},{'a':'阿尔法'})
        done=self.applied();self.journal(done['backup'],status='restoring',restored_files=[])
        (self.lang/'zh_tw.json').write_text('edited by the player',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'後來有修改'):restore_backup(Path(done['backup']),self.instance)
        self.assertEqual((self.lang/'zh_tw.json').read_text(encoding='utf-8'),'edited by the player')

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_batches_that_left_nothing_behind_explain_why_they_cannot_be_restored(self,_):
        self.write({'a':'Alpha'},{'a':'阿尔法'})
        done=self.applied()
        for status,words in (('backing_up','沒有被修改'),('rolled_back','已自動復原'),('restored','已經還原過')):
            self.journal(done['backup'],status=status)
            with self.assertRaisesRegex(ValueError,words):restore_backup(Path(done['backup']),self.instance)
        self.assertTrue((self.lang/'zh_tw.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_older_batch_names_the_newer_batch_that_must_be_restored_first(self,_):
        self.write({'a':'Alpha','b':'Beta'},{'a':'阿尔法','b':'贝塔'})
        first=self.applied({'a'});time.sleep(.01);second=self.applied({'b'})
        with self.assertRaisesRegex(ValueError,'請先還原較新的那一批') as caught:restore_backup(Path(first['backup']),self.instance)
        self.assertIn(Path(second['backup']).name[:15],str(caught.exception))
        restore_backup(Path(second['backup']),self.instance);restore_backup(Path(first['backup']),self.instance)
        self.assertFalse((self.lang/'zh_tw.json').exists())

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_retry_after_a_cut_short_write_points_to_the_backup_page(self,_):
        self.write({'a':'Alpha','b':'Beta'},{'a':'阿尔法','b':'贝塔'})
        result=self.make_plan()
        for r in result['rows']:r['reviewed']=True
        waiting=json.loads(json.dumps(result))
        done=apply_session(result,self.home,lambda *_:None);self.journal(done['backup'],status='backed_up')
        with self.assertRaisesRegex(ValueError,'中途中斷'):apply_session(waiting,self.home,lambda *_:None)


class SpaceAndStagingTests(Base):
    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_full_disk_stops_before_anything_is_written(self,_):
        self.write({'a':'Alpha'},{'a':'阿尔法'},{'z':'既有'})
        result=self.make_plan()
        for r in result['rows']:r['reviewed']=True
        with patch('shutil.disk_usage',return_value=Mock(free=10*1024*1024)):
            with self.assertRaisesRegex(ValueError,'硬碟空間不足'):apply_session(result,self.home,lambda *_:None)
        self.assertEqual(json.loads((self.lang/'zh_tw.json').read_text(encoding='utf-8')),{'z':'既有'})
        self.assertFalse(list((self.home/'output').glob('*/原始備份/*')))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_working_copies_are_removed_and_the_report_stays_small(self,_):
        self.write({'a':'Alpha'},{'a':'阿尔法'})
        done=self.applied();report=Path(done['report'])
        self.assertFalse(list(report.glob('staged*')))
        self.assertTrue((Path(done['backup'])/'_備份紀錄/manifest.json').exists())
        self.assertEqual(sorted(p.name for p in (report/'audit').iterdir()),['files.jsonl.gz','strings.jsonl.gz','summary.json'])
        self.assertEqual([p.name for p in (report/'after/audit').iterdir()],['summary.json'])

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_failed_write_also_removes_working_copies(self,_):
        self.write({'a':'Alpha'},{'a':'阿尔法'})
        result=self.make_plan()
        for r in result['rows']:r['reviewed']=True
        with patch.object(jobs,'apply_reviewed',side_effect=PermissionError(13,'denied','zh_tw.json')):
            with self.assertRaises(PermissionError):apply_session(result,self.home,lambda *_:None)
        self.assertFalse(list(Path(result['report']).glob('staged*')))


class FolderChoiceTests(Base):
    def test_folder_inside_a_modpack_is_corrected_to_the_modpack(self):
        (self.instance/'mods').mkdir();(self.instance/'kubejs/config').mkdir()
        for inside in ('mods','kubejs'):
            folder,note=jobs.resolve_instance(f'"{self.instance/inside}"')
            self.assertEqual(folder,self.instance.resolve());self.assertIn(inside,note)
        folder,note=jobs.resolve_instance(str(self.instance/'manifest.json'))
        self.assertEqual(folder,self.instance.resolve());self.assertIn('檔案',note)
        self.assertEqual(jobs.resolve_instance(str(self.instance)),(self.instance.resolve(),''))

    def test_wrong_folders_say_what_to_pick_instead(self):
        root=Path(self.temp.name)
        folder,note=jobs.resolve_instance(str(root))  # the only modpack inside is an obvious choice
        self.assertEqual(folder,self.instance.resolve());self.assertIn('唯一的模組包',note)
        (root/'second/.minecraft/mods').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'有 2 個模組包'):jobs.resolve_instance(str(root))
        with self.assertRaisesRegex(ValueError,'找不到這個資料夾'):jobs.resolve_instance(str(root/'gone'))
        with self.assertRaisesRegex(ValueError,'請先選擇'):jobs.resolve_instance('  ')
        empty=root/'empty';empty.mkdir()
        with self.assertRaisesRegex(ValueError,'不像模組包'):jobs.resolve_instance(str(empty))
        with self.assertRaisesRegex(ValueError,'整個磁碟或使用者資料夾'):jobs.resolve_instance(Path(root.anchor))


class PlainErrorTests(unittest.TestCase):
    def test_common_failures_are_explained_with_the_next_step(self):
        explain=jobs.explain_error
        self.assertIn('正被其他程式使用',explain(PermissionError(13,'Access is denied','C:/pack/mods/a.jar')))
        self.assertIn('a.jar',explain(PermissionError(13,'Access is denied','C:/pack/mods/a.jar')))
        self.assertIn('硬碟空間不足',explain(OSError(28,'No space left on device')))
        self.assertIn('已損壞',explain(zipfile.BadZipFile('File is not a zip file')))
        self.assertIn('可能已被移動',explain(FileNotFoundError(2,'No such file','C:/pack/x.json')))
        self.assertIn('無法連上網路',explain(requests.ConnectionError('dns')))
        self.assertIn('技術細節',explain(KeyError('rows')))
        # Messages this program wrote for players are passed on unchanged.
        self.assertEqual(explain(ValueError('這一批沒有尚未套用的譯文。')),'這一批沒有尚未套用的譯文。')
        self.assertEqual(explain(jobs.GameRunningError('請關閉遊戲')),'請關閉遊戲')

    def test_used_up_query_allowance_says_when_it_returns(self):
        reply=Mock(status_code=403,headers={'X-RateLimit-Remaining':'0','X-RateLimit-Reset':str(int(time.time())+600)})
        with self.assertRaises(references.RateLimited) as caught:references.rate_limited(reply)
        self.assertRegex(str(caught.exception),'約 (9|10) 分鐘後恢復')
        self.assertIn('查詢次數暫時用完',jobs.explain_error(caught.exception))
        references.rate_limited(Mock(status_code=403,headers={}))  # any other refusal is not mistaken for it


def pack(files):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        for name,data in files.items():z.writestr(name,json.dumps(data,ensure_ascii=False))
    return raw.getvalue()


class FakeGitHub:
    """GitHub as the reference lookup sees it; `broken` lists URL fragments that fail."""
    def __init__(self,broken=(),limited=False):
        self.broken=tuple(broken);self.limited=limited;self.headers={};self.calls=[];self.failures=0
        self.tw=pack({'assets/demo/lang/zh_tw.json':{'a':'甲'},'assets/demo/lang/en_us.json':{'a':'A'}})
        self.cn=pack({'assets/demo/lang/zh_cn.json':{'a':'设置工作台'}})
    def reply(self,url,status=200,content=b'',headers=None,data=None):
        r=Mock(status_code=status,headers=dict(headers or {}))
        r.__enter__=lambda s:r;r.__exit__=lambda *a:False
        r.iter_content=lambda size:[content] if content else []
        r.json=lambda:data
        def check():
            if status>=400:raise requests.HTTPError(str(status),response=r)
        r.raise_for_status=check
        return r
    def get(self,url,**_):
        self.calls.append(url)
        if any(b in url for b in self.broken):raise requests.ConnectionError('down')
        if 'api.github.com' in url:
            if self.limited:return self.reply(url,403,headers={'X-RateLimit-Remaining':'0','X-RateLimit-Reset':str(int(time.time())+1200)})
            if '/commits/main' in url:return self.reply(url,content=json.dumps({'sha':'b'*40}).encode())
            return self.reply(url,content=json.dumps({'assets':[dict(name='Minecraft-Mod-Language-Modpack-1-21.zip',id=7,updated_at='2026-09-29T00:00:00Z',
                                                                     browser_download_url='https://github.com/CFPAOrg/x/releases/download/autobuild/cn.zip')]}).encode())
        if 'info/refs' in url:return self.reply(url,content=b'001e# service=git-upload-pack\n0000003f'+b'a'*40+b' refs/heads/main\n0000')
        if 'codeload.github.com' in url:return self.reply(url,content=self.tw)
        if 'releases/download' in url:return self.reply(url,content=self.cn)
        return self.reply(url,404)
    def head(self,url,**_):
        self.calls.append('HEAD '+url)
        if any(b in url for b in self.broken):raise requests.ConnectionError('down')
        if url.endswith('Modpack-1-21.zip'):return self.reply(url,headers={'ETag':'"abc"','Last-Modified':'Tue, 29 Sep 2026 01:41:02 GMT','Content-Length':'10'})
        return self.reply(url,404)


class ReferenceLookupTests(Base):
    def refresh(self,github):
        cache=self.home/'cache';cache.mkdir(parents=True,exist_ok=True);(cache/'tw-old.zip').write_bytes(b'old')
        with patch.object(references.requests,'Session',return_value=github),patch.object(references,'official_vanilla',return_value={}), \
             patch.object(references.time,'sleep'):
            return references.refresh(self.instance,cache,lambda _:None,lambda:False)

    def test_latest_versions_are_confirmed_without_the_query_service(self):
        github=FakeGitHub(limited=True)
        dbs,info=self.refresh(github)
        self.assertEqual(info['ref_commit'],'a'*40);self.assertEqual(info['cfpa_updated'],'Tue, 29 Sep 2026 01:41:02 GMT')
        self.assertFalse(any('api.github.com' in c for c in github.calls))
        self.assertEqual(set(info['confirmed_by'].values()),{'git','download'})
        self.assertEqual(dbs[1]['demo']['a'],'設定工作台')  # Taiwan wording and Taiwan character forms
        self.assertFalse((self.home/'cache/tw-old.zip').exists())  # superseded downloads are removed
        self.assertEqual(len(list((self.home/'cache').glob('tw-*.zip'))),1)

    def test_query_service_is_the_second_choice(self):
        github=FakeGitHub(broken=('info/refs','releases/download/autobuild/Minecraft-Mod-Language-Modpack'))
        with patch.object(references,'ATTEMPTS',1):dbs,info=self.refresh(github)
        self.assertEqual(info['ref_commit'],'b'*40);self.assertEqual(info['cfpa_updated'],'2026-09-29T00:00:00Z')
        self.assertIn('api',info['confirmed_by'].values())

    def test_both_ways_failing_stops_with_a_plain_reason(self):
        github=FakeGitHub(broken=('info/refs',),limited=True)
        with patch.object(references,'ATTEMPTS',1),self.assertRaises(ValueError) as caught:self.refresh(github)
        self.assertIn('無法確認參考庫是不是最新版',str(caught.exception));self.assertIn('分鐘後恢復',str(caught.exception))
        self.assertIn('沒有修改',str(caught.exception))

    def test_dropped_connection_is_retried_a_limited_number_of_times(self):
        github=FakeGitHub();real=github.get;state=dict(left=2)
        def flaky(url,**kw):
            if 'info/refs' in url and 'ModsTranslationPack' in url and state['left']:
                state['left']-=1;raise requests.ConnectionError('reset')
            return real(url,**kw)
        github.get=flaky
        dbs,info=self.refresh(github)
        self.assertEqual((info['ref_commit'],state['left'],info['confirmed_by']['繁中參考庫']),('a'*40,0,'git'))

    def test_version_is_found_for_other_launchers_and_from_the_mods(self):
        root=Path(self.temp.name)
        prism=root/'prism/.minecraft';(prism/'mods').mkdir(parents=True)
        (root/'prism/mmc-pack.json').write_text(json.dumps(dict(components=[dict(uid='net.minecraft',version='1.20.1')])),encoding='utf-8')
        self.assertEqual(references.detect_version(prism),('1.20.1','mmc-pack.json'))
        modrinth=root/'mr';(modrinth/'mods').mkdir(parents=True)
        (modrinth/'profile.json').write_text(json.dumps(dict(metadata=dict(game_version='1.19.2'))),encoding='utf-8')
        self.assertEqual(references.minecraft_version(modrinth),'1.19.2')
        bare=root/'bare';(bare/'mods').mkdir(parents=True)
        toml='[[dependencies.{0}]]\nmodId="neoforge"\nversionRange="[21.1,)"\n[[dependencies.{0}]]\nmodId="minecraft"\nversionRange="{1}"\n'
        for name,wanted in (('a','[1.21,1.22)'),('b','[1.21.1,)'),('c','[1.20.1,1.21)')):
            with zipfile.ZipFile(bare/f'mods/{name}.jar','w') as z:z.writestr('META-INF/neoforge.mods.toml',toml.format(name,wanted))
        with zipfile.ZipFile(bare/'mods/d.jar','w') as z:z.writestr('fabric.mod.json',json.dumps(dict(id='d',depends=dict(minecraft='>=1.21.1'))))
        version,how=references.detect_version(bare)
        self.assertEqual(version,'1.21.1');self.assertIn('推測',how)
        self.assertEqual(references.detect_version(root/'app'),('',''))


class QualityTests(Base):
    def rows(self,references=None):
        return {r['key']:r for r in self.make_plan(references)['rows']}

    def test_changed_number_waits_for_a_source_that_keeps_it(self):
        self.write({'a':'Gains 20 experience','b':'Lasts 3 seconds','c':'99 Blue Balloons','d':'Deals 200% damage','e':'Costs %1$s and 5 gems'},
                   {'a':'获得 10 点经验','b':'持续片刻','c':'九十九只蓝气球','d':'造成双倍伤害','e':'花费 %1$s 和 5 颗宝石'})
        cn={'demo':{'a':'獲得 20 點經驗'}}
        rows=self.rows(([{},cn],{'sources':['tw','cn']}))
        self.assertEqual((rows['a']['origin'],rows['a']['proposed']),('reference_pack_or_cfpa','獲得 20 點經驗'))
        self.assertFalse(rows['a'].get('number_doubt'))
        # No source keeps the number: used, and listed for checking with both numbers named.
        self.assertTrue(rows['b']['number_doubt']);self.assertIn('原文 3',rows['b']['issue']);self.assertTrue(jobs.needs_check(dict(rows['b'],changed=True)))
        for key in ('c','d','e'):self.assertFalse(rows[key].get('number_doubt'),key)  # Chinese numerals and parameters are fine
        self.assertEqual(jobs.number_doubt('There is 0 Boss Fights','目前沒有任何首領戰'),'')
        self.assertEqual(jobs.number_doubt('Weighs 13,500 jin','重 13500 斤'),'')
        self.assertIn('譯文 50',jobs.number_doubt('100 slimes vs 1 Gorilla?','你能戰勝 50 隻史萊姆嗎？'))

    def test_traditional_chinese_written_for_this_version_keeps_its_place(self):
        self.write({'a':'Lasts 3 seconds'},{'a':'持续 3 秒'},{'a':'持續片刻'})
        row=self.rows()['a']  # the mod's own zh_tw is not replaced because of a number, only listed (AGENTS.md)
        self.assertEqual((row['origin'],row['proposed'],row['changed']),('existing_zh_tw','持續片刻',False))
        self.assertTrue(row['number_doubt']);self.assertTrue(jobs.needs_check(row))

    def test_taiwan_character_forms_are_not_mistaken_for_simplified(self):
        self.write({'a':'Crafting Table','b':'Bedrock Bed','c':'Interference','d':'Settings'},
                   {'a':'工作台','b':'基岩床','c':'干扰','d':'设置'},{'a':'工作台','b':'基岩床','c':'干擾群峰','d':'设置'})
        rows=self.rows()
        for key in ('a','b','c'):self.assertNotIn(key,rows,key)  # correct zh_tw is left as it is
        self.assertEqual((rows['d']['origin'],rows['d']['proposed']),('same_source_zh_cn','設定'))
        for text in ('工作台','岩漿塊','這裡的床鋪','群系','山峰','干擾','前仆後繼'):self.assertFalse(references.has_simplified(text),text)
        for text in ('设置','游戏','云杉木','干草块'):self.assertTrue(references.has_simplified(text),text)

    def test_converted_text_uses_the_forms_of_official_traditional_chinese(self):
        self.write({'a':'Crafting Table','b':'Mother Rock','c':'Platform Bed'},{'a':'工作台','b':'母岩','c':'平台床'})
        rows=self.rows()
        self.assertEqual([rows[k]['proposed'] for k in 'abc'],['工作台','母岩','平台床'])
        self.assertEqual(references.to_taiwan('岩浆 台阶 群组 这里 为了'),'岩漿 臺階 群組 這裡 為了'.replace('臺','台'))

    def test_numbers_written_with_units_are_the_same_number(self):
        for en,zh in (('Have at least 1 million EP','擁有至少100萬存在值'),('Increase its EP by 10,000','增加 1萬存在值'),
                      ('Range: 10k blocks','範圍：1萬格'),('Costs 2 billion','花費 20 億')):
            self.assertEqual(jobs.number_doubt(en,zh),'',en)
        self.assertIn('原文 1000000',jobs.number_doubt('Have at least 1 million EP','擁有至少 10 萬存在值'))

    def test_conversion_slips_seen_in_real_modpacks_are_corrected(self):
        for cn,tw in (('去皮松木原木','去皮松木原木'),('雪松木板','雪松木板'),('最多只能放一个','最多只能放一個'),('这是只读的','這是唯讀的'),
                      ('干草块','乾草塊'),('发光浆果','發光漿果'),('按键绑定','按鍵綁定'),
                      # the same characters where the other reading is the right one
                      ('一只能飞的鸟','一隻能飛的鳥'),('三只羊','三隻羊'),('松开按键','鬆開按鍵'),('放松一下','放鬆一下'),('蛇发女妖','蛇髮女妖')):
            self.assertEqual(references.to_taiwan(cn),tw,cn)
        for text in ('剝皮松木原木','最多只能','按鍵綁定','乾草塊'):self.assertFalse(references.has_simplified(text),text)

    def test_characters_the_converter_kept_simplified_are_corrected(self):
        # The Foll quests and books: the converter's word list saw a queen (蜂后, 妖后), a name (于禁, 子云)
        # or a word split by a line break, and left simplified characters in the Taiwan text.
        for cn,tw in (('变成蜜蜂后，获得飞行能力','變成蜜蜂後，獲得飛行能力'),('想办法弄死巫妖后，其','想辦法弄死巫妖後，其'),
                      ('装备空间撕裂球后，在平行世界','裝備空間撕裂球後，在平行世界'),('生成于海洋','生成於海洋'),
                      ('于禁书卷轴的解读之中','於禁書卷軸的解讀之中'),('孢子云','孢子雲'),('改变小范\r\n围内','改變小範\r\n圍內'),
                      # the queens and sayings that are right as they are
                      ('切叶蚁后：哭泣','切葉蟻后：哭泣'),('若没有蚁后，蚁丘','若沒有蟻后，蟻丘'),('皇后','皇后'),('人云亦云','人云亦云')):
            self.assertEqual(references.to_taiwan(cn),tw,cn);self.assertFalse(references.has_simplified(tw),cn)
        # 输出端口: players' slang for what deals the damage, never a computer port; next to machines, the output side.
        self.assertEqual(references.to_taiwan('变身技能的巨型火球是优质输出端口'),'變身技能的巨型火球是優質輸出手段')
        self.assertEqual(references.to_taiwan('介绍一下这个流派输出端口——对单高伤技能'),'介紹一下這個流派輸出手段——對單高傷技能')
        self.assertEqual(references.to_taiwan('机器的物品输出端口在右侧，输入端口在左侧'),'機器的物品輸出端在右側，輸入端在左側')
        # Text applied by an earlier version is corrected the same way (once, listed for checking).
        self.assertEqual(jobs.taiwan_wording('魔法箭會提供魔法系前期一個很不錯的輸出埠'),'魔法箭會提供魔法系前期一個很不錯的輸出手段')

    def test_glossary_follows_official_names(self):
        from mc_zh_tw_translator.translator import MINECRAFT_GLOSSARY as glossary
        self.assertEqual([glossary[k] for k in ('enderman','cobblestone','crafting table','beacon')],['終界使者','鵝卵石','工作台','烽火台'])
        self.assertNotIn('boss',glossary)
        self.write({'gui.demo.a':'Anvil','gui.demo.b':'Boss','demo':'DemoMod Deluxe'})
        vanilla={'minecraft':{},'__terms__':{'anvil':'官方鐵砧'},'__source__':'test'}
        rows=self.rows(([{},{},vanilla],{'sources':['tw','cn','vanilla']}))
        self.assertEqual((rows['gui.demo.a']['origin'],rows['gui.demo.a']['proposed']),('glossary','官方鐵砧'))
        self.assertEqual(rows['gui.demo.b']['origin'],'keep_original')  # written as Boss in official zh_tw too
        self.assertEqual((rows['demo']['origin'],rows['demo']['evidence']),('keep_original','模組名稱'))  # the key is the mod id

    def test_correct_taiwan_words_are_not_rewritten(self):
        for text in ('感謝所有支持者','質量越大，射程越短'):self.assertEqual(jobs.taiwan_wording(text),text)
        self.assertEqual(jobs.taiwan_wording('默認設置'),'預設設定')
        # Taiwan wording that only looks like a mainland word stays: 增加 + 載入, 控制代碼, 數據機, 大數據.
        for text in ('略微增加載入時間','請參閱可用的控制代碼','錯誤代碼 404','數據機','大數據分析'):self.assertEqual(jobs.taiwan_wording(text),text)
        self.assertEqual(jobs.taiwan_wording('正在加載數據'),'正在載入資料')

    def test_ordinary_taiwan_characters_are_not_simplified(self):
        from mc_zh_tw_translator.desktop_references import has_simplified
        # The converter rewrites these into rare variants (喫, 揹, 遊, 祕, 瞭), which made them look simplified.
        for text in ('吃掉一件文物','滾動游標物品','背包','了解','秘密','伙伴','公里','栗子','斗篷','准許','皇后','干擾'):
            self.assertFalse(has_simplified(text),text)
        for text in ('虚空石','類别','永恒','云杉木','之后','设置'):self.assertTrue(has_simplified(text),text)

    def test_minecraft_names_use_taiwan_official_wording(self):
        from mc_zh_tw_translator.desktop_references import to_taiwan
        cases={'探索所有下界生物群系':'探索所有地獄生態域','生成于海洋群系':'生成於海洋生態域','已演奏群系列表':'已演奏生態域列表',
               '族群系统':'族群系統','用下界合金锭升级':'用獄髓錠升級','末影人':'終界使者','腐化末地':'腐化終界',
               '恶魂刷怪蛋':'地獄幽靈生怪蛋','潜影盒':'界伏盒','幽匿感测体':'伏聆振測器','监守者':'伏守者','凋灵骷髅':'凋零骷髏'}
        for cn,tw in cases.items():self.assertEqual(to_taiwan(cn),tw,cn)
        # Ordinary words, bounds and a mod's own keeper stay as they are.
        for cn,tw in (('力量','力量'),('橡木楼梯','橡木樓梯'),('中毒','中毒')):self.assertEqual(to_taiwan(cn),tw,cn)
        self.assertEqual(to_taiwan('数值的上下界'),'數值的上下界');self.assertEqual(to_taiwan('地牢监守者'),'地牢監守者')
        self.assertEqual(jobs.taiwan_wording('下界合金碎片粒'),'獄髓碎片粒')
        self.assertEqual(jobs.taiwan_wording('下界合金鍾'),'獄髓鐘');self.assertEqual(jobs.taiwan_wording('強化鍾石劍'),'強化鐘石劍')
        self.assertEqual(jobs.taiwan_wording('情有獨鍾，鍾愛一生'),'情有獨鍾，鍾愛一生')

    def test_internet_slang_and_kaomoji_need_no_translation(self):
        for text in ('ww','www','Ciallo～(∠・ω< )⌒★'):self.assertTrue(jobs.keep_original_reason(text),text)
        for text in ('Weather cleared','wow','Set the time to Daytime'):self.assertEqual(jobs.keep_original_reason(text),'',text)

    def test_start_page_and_report_count_the_same_rows(self):
        # A translated line that holds no Chinese (a code fragment) is translated on both; Chinese the program
        # already holds is not counted as English that CurseForge puts back.
        fragment=dict(kind='language',supported=True,origin='ai_translation',en='othermod"])',current='othermod"])',proposed='othermod"]）',changed=True,installed=True,shown=True)
        chinese=dict(kind='class_display',supported=False,origin='existing_zh_tw',current='反転共鳴',proposed='反転共鳴',changed=False)
        english=dict(kind='class_display',supported=False,origin='ai_translation',current='Weather cleared',proposed='天氣已轉晴',changed=True)
        session=dict(rows=[fragment,chinese,english])
        self.assertEqual([jobs.row_category(r) for r in session['rows']],['ai','mod_tw','held'])
        c=jobs.coverage(session);self.assertEqual((c.get('missing',0),c.get('unwritable',0),c['done']),(0,1,2))

    def test_travelers_titles_own_commands_are_not_taken_for_a_missing_mod(self):
        self.assertIsNone(jobs.KEY_MOD_REFERENCE.match('travelerstitles.commands.biometitle.invalid'))
        self.assertEqual(jobs.KEY_MOD_REFERENCE.match('travelerstitles.bracken.dormis')[2],'bracken')

    def test_other_version_and_official_names_are_labelled(self):
        self.write({'block.demo.oak':'Oak Log','item.demo.red':'Red','gui.demo.red':'Red','item.demo.old':'Old Thing'})
        vanilla={'minecraft':{},'__terms__':{'oak log':'橡木原木','red':'紅色'},'__source__':'test'}
        older={'demo':{'item.demo.old':'舊東西'}}
        rows=self.rows(([{},{},older,vanilla],{'sources':['tw','cn','cn-1-20','vanilla']}))
        self.assertEqual((rows['block.demo.oak']['origin'],rows['block.demo.oak']['proposed']),('official_vanilla','橡木原木'))
        self.assertEqual(rows['item.demo.red']['origin'],'official_vanilla')
        self.assertEqual(rows['gui.demo.red']['origin'],'untranslated')  # a general word is not a vanilla name
        old=rows['item.demo.old']
        self.assertEqual(old['origin'],'cross_version_reference');self.assertIn('跨版本',old['issue'])
        self.assertTrue(jobs.needs_check(old))

    @patch('mc_zh_tw_translator.desktop_jobs.ensure_game_closed')
    def test_second_run_finds_nothing_left_to_write(self,_):
        (self.instance/'mods').mkdir();inner=io.BytesIO()
        with zipfile.ZipFile(inner,'w') as z:
            z.writestr('assets/lib/lang/en_us.json',json.dumps({'lib.a':'Library','lib.b':'Supporters'}))
            z.writestr('assets/lib/lang/zh_cn.json',json.dumps({'lib.a':'函数库','lib.b':'支持者'},ensure_ascii=False))
        with zipfile.ZipFile(self.instance/'mods/real.jar','w') as z:
            z.writestr('assets/real/lang/en_us.json',json.dumps({'real.a':'Thanks to all supporters'}))
            z.writestr('assets/real/lang/zh_cn.json',json.dumps({'real.a':'感谢所有支持者'},ensure_ascii=False))
            z.writestr('META-INF/jarjar/lib.jar',inner.getvalue())
        (self.instance/'mods/kubejs-neoforge.jar').write_bytes(b'')
        self.write({'a':'Alpha'},{'a':'阿尔法'})
        first=self.applied()
        self.assertEqual(first['installed_count'],4)
        again=self.make_plan()
        self.assertEqual([r['key'] for r in again['rows'] if r['changed'] and r['supported']],[])
        self.assertEqual(jobs.applicable_count(again),0)
        kept={r['key']:r for r in again['rows'] if r.get('recovered')}
        self.assertEqual(kept['lib.a']['origin'],'same_source_zh_cn')  # still labelled by its real source


class PatchLimitTests(Base):
    def make(self,entries,files=None,payload=None):
        path=Path(self.temp.name)/'patch.zip'
        manifest=dict(format=patches.PATCH_FORMAT,modpack={},files=files if files is not None else
                      [dict(file='mods/a.jar',archive=True,before='0'*64,size=1,entries={n:patches.sha256(b'{}') for n in entries})])
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json',json.dumps(manifest))
            for n in entries:z.writestr('payload/mods/a.jar/'+n,b'{}')
            for n,data in (payload or {}).items():z.writestr(n,data)
        return path

    def test_patch_may_only_carry_traditional_chinese_text(self):
        for entry in ('assets/a/lang/zh_tw.json','legacy_pack/assets/a/lang/zh_tw.lang','assets/a/patchouli_books/b/zh_tw/entries/x.json'):
            z,_=patches.read_patch(self.make([entry]));z.close()
        for entry in ('assets/a/lang/en_us.json','assets/a/lang/zh_cn.json','data/a/recipes/x.json','data/a/loot_tables/zh_tw.json',
                      'assets/a/zh_tw/script.js','a/b.class','assets/a/lang/zh_tw.json/../x.json'):
            with self.assertRaises(ValueError,msg=entry):patches.read_patch(self.make([entry]))
        loose=lambda name:[dict(file=name,archive=False,before=None,after=patches.sha256(b'x'))]
        z,_=patches.read_patch(self.make([],loose('config/openloader/x/assets/a/lang/zh_tw.json'),{'payload/config/openloader/x/assets/a/lang/zh_tw.json':b'x'}));z.close()
        for name in ('config/sodium-options.json','kubejs/data/a/recipes/zh_tw.json','options.txt','config/a/lang/en_us.json'):
            with self.assertRaisesRegex(ValueError,'不允許',msg=name):patches.read_patch(self.make([],loose(name),{'payload/'+name:b'x'}))

    def test_patch_that_unpacks_too_large_is_refused_before_unpacking(self):
        path=self.make(['assets/a/lang/zh_tw.json'],payload={'payload/filler.txt':b'0'*2048})
        with patch.object(patches,'MAX_ENTRY_SIZE',1024),self.assertRaisesRegex(ValueError,'超過上限'):patches.read_patch(path)
        with patch.object(patches,'MAX_UNPACKED_SIZE',1024),self.assertRaisesRegex(ValueError,'超過上限'):patches.read_patch(path)


class UpdateTests(unittest.TestCase):
    def github(self,tag):
        client=Mock()
        def get(url,**kw):
            if 'api.github.com' in url:return Mock(status_code=403,headers={'X-RateLimit-Remaining':'0'})
            if url.endswith('/releases/latest'):return Mock(status_code=302,headers={'Location':f'https://github.com/{updater.REPOSITORY}/releases/tag/{tag}'})
            return Mock(status_code=200,text='這一版修正了問題。')
        client.get=get;client.head=lambda url,**kw:Mock(status_code=200,headers={'Content-Length':'4096'},raise_for_status=lambda:None)
        return client

    def test_update_is_still_found_when_the_query_allowance_is_used_up(self):
        info=updater.check_update(self.github('v99.0.0'))
        self.assertEqual((info['status'],info['version'],info['size'],info['sha256']),('available','v99.0.0',4096,None))
        self.assertEqual(updater.release_url(info['url']),info['url']);self.assertEqual(updater.release_url(info['checksum_url']),info['checksum_url'])
        self.assertEqual(info['notes'],'這一版修正了問題。')  # the checksum file is still required before installing
        self.assertEqual(updater.check_update(self.github('v'+updater.VERSION))['status'],'current')

    def test_only_the_newest_old_program_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);exe=root/'MCTranslator.exe';exe.write_bytes(b'MZ');home=root/'MCTranslatorData'
            for n,name in enumerate(('previous-aaa','previous-bbb','previous-ccc','failed-ddd')):
                old=root/(exe.name+'.'+name);old.write_bytes(b'MZ')
                import os;os.utime(old,(1000+n,1000+n))
            stale=home/'updates/old';stale.mkdir(parents=True);(stale/'MCTranslator.exe').write_bytes(b'MZ')
            import os;os.utime(stale,(1000,1000))
            fresh=home/'updates/now';fresh.mkdir()
            updater.clean_leftovers(home,exe)
            self.assertEqual(sorted(p.name for p in root.glob('MCTranslator.exe*')),['MCTranslator.exe','MCTranslator.exe.previous-ccc'])
            self.assertFalse(stale.exists());self.assertTrue(fresh.exists())

    def test_update_helper_refuses_a_ticket_from_another_place(self):
        with tempfile.TemporaryDirectory() as d:
            ticket=Path(d)/'update.json';target=Path(d)/'MCTranslator.exe';target.write_bytes(b'MZ')
            ticket.write_text(json.dumps(dict(target=str(target),sha256='0'*64,pid=1,home=str(Path(d)/'home'))),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'更新暫存路徑不符'):updater.apply_update(ticket)
            self.assertEqual(target.read_bytes(),b'MZ')


if __name__=='__main__':unittest.main()
