import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
from PySide6.QtTest import QTest
from mc_zh_tw_translator.desktop import MainWindow
from mc_zh_tw_translator import patches


class DesktopUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_still_to_do_counts_only_player_text_without_chinese(self):
        from mc_zh_tw_translator.desktop import Worker
        seen=[];worker=Worker(lambda _:None);worker.checkpoint.connect(seen.append)
        rows=[dict(origin='untranslated',supported=True,proposed='Hello'),dict(origin='untranslated',supported=False,proposed='x y z'),  # a program string candidate
              dict(origin='not_display',supported=False),dict(origin='same_source_zh_cn',supported=True,changed=True,installed=True,shown=True,proposed='你好')]
        worker.publish(dict(rows=rows,already_chinese=2,installed_count=1,status='installed',rate_before=.5))
        view=json.loads(seen[0])['preview_cards'];cards=view['cards']
        self.assertEqual([number for number,_ in cards],['75.0%','1']);self.assertEqual(view['written'],'這次從 50.0% 提升到 75.0%。')
        self.assertIn('3／4 句',cards[0][1]);self.assertIn('1 條程式字串',cards[0][1]);self.assertIn('找不到中文來源',cards[1][1])

    def test_background_plan_reports_real_rows_and_reenables_controls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);home=root/'app';home.mkdir();instance=root/'sample'
            lang=instance/'kubejs/assets/demo/lang';lang.mkdir(parents=True)
            (lang/'en_us.json').write_text('{"demo.test":"Hello"}',encoding='utf-8')
            (lang/'zh_cn.json').write_text('{"demo.test":"你好"}',encoding='utf-8')
            window=MainWindow(home);window.path.setText(str(instance))
            with patch('mc_zh_tw_translator.desktop_jobs.refresh',return_value=([{},{}],{})):
                window.start_job()
                self.assertFalse(window.choose.isEnabled())
                # A greyed-out button shows the plain arrow, not the hand, so it does not look clickable.
                self.assertEqual(window.choose.cursor().shape(),Qt.ArrowCursor)
                for _ in range(500):
                    self.app.processEvents();time.sleep(.02)
                    if not window.busy:break
                if window.busy:
                    window.worker.cancelled=True;window.worker.wait(10000);self.app.processEvents()
            self.assertFalse(window.busy)
            self.assertIsNotNone(window.session)
            self.assertEqual(window.session['rows'][0]['proposed'],'你好')
            # Translated but not written yet: the game still shows English, so nothing counts as done.
            self.assertEqual([n.text() for n in window.stats],['0.0%','1'])
            self.assertIn('還沒寫入',window.stat_notes[1].text())
            self.assertTrue(window.choose.isEnabled());self.assertEqual(window.choose.cursor().shape(),Qt.PointingHandCursor)
            window.navigate(1);self.assertEqual(window.table.rowCount(),1)
            self.assertFalse((lang/'zh_tw.json').exists())
            window.close()

    def test_update_check_shows_unavailable_and_never_enables_install(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            with patch('mc_zh_tw_translator.updater.check_update',return_value=dict(status='unavailable',message='尚未發布版本')):
                window.check_updates()
                for _ in range(500):
                    self.app.processEvents();time.sleep(.02)
                    if not window.busy:break
            self.assertEqual(window.update_status.text(),'尚未發布版本')
            self.assertFalse(window.install_btn.isEnabled());window.close()

    def test_path_can_be_pasted_and_theme_can_be_switched(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            pasted='"'+str(Path(d)/'instance')+'"'
            window.path.setText(pasted)
            self.assertFalse(window.path.isReadOnly())
            self.assertEqual(str(window.instance_path()),str(Path(d)/'instance'))
            self.assertIn('#F8F8F8', QApplication.instance().styleSheet())
            window.toggle_theme()
            self.assertEqual(window.settings.value('theme'),'dark')
            self.assertIn('#16181C', QApplication.instance().styleSheet())
            window.toggle_theme()
            self.assertEqual(window.settings.value('theme'),'light')
            window.close()

    def test_checkpoint_visible_before_finished_and_recovers_on_restart(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);report=home/'output/demo/報告/batch';report.mkdir(parents=True)
            data=dict(instance=d,report=str(report),status='awaiting_game',source_counts={},errors=[],rows=[
                dict(source='instance!/kubejs/assets/demo/lang/en_us.json',key='hello',en='Hello',
                     proposed='你好',origin='same_source_zh_cn',supported=True,reviewed=True,changed=True)])
            (report/'session.json').write_text(json.dumps(data),encoding='utf-8')
            window=MainWindow(home)
            self.assertEqual(window.table.rowCount(),1)
            self.assertIn('重試套用',window.apply_btn.text())
            window.receive_checkpoint(json.dumps(data))
            self.assertIn('Hello',window.activity.toPlainText())
            self.assertIn('譯文已保存',window.report_summary.text())
            window.close()

    def test_startup_update_prompts_without_download_or_blocking_translation(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            with patch('mc_zh_tw_translator.updater.check_update',return_value=dict(status='available',version='v9.0.0')),patch('mc_zh_tw_translator.updater.download_update') as download:
                window.check_updates_on_start()
                for _ in range(100):
                    self.app.processEvents();time.sleep(.01)
                    if not window.update_worker:break
                self.assertIn('有新版',window.navs[3].text())
                self.assertFalse(window.update_badge.isHidden())
                self.assertTrue(window.full_start.isEnabled());download.assert_not_called()
            window.close()

    def test_ai_model_choice_and_declined_consent_never_start_job(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            info=dict(account=dict(type='chatgpt',planType='plus'),warning='',quota=[],models=[
                dict(model='available-a',displayName='模型 A',isDefault=True),dict(model='available-b',displayName='模型 B')])
            window.ai_connected(info)
            self.assertEqual(window.ai_models.count(),2);window.ai_models.setCurrentIndex(1)
            self.assertEqual(window.settings.value('ai_model'),'available-b')
            window.ai_connected(info);self.assertEqual(window.ai_models.currentData()['model'],'available-b')
            window.session=dict(rows=[dict(origin='untranslated',supported=True)],report=d)
            with patch.object(QMessageBox,'question',return_value=QMessageBox.No),patch.object(window,'run_worker') as run:
                window.ai_supplement();run.assert_not_called()
            self.assertEqual(window.pages.count(),7);window.close()

    def test_suggested_model_is_the_default_until_the_user_picks_one(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            window.settings.setValue('ai_model','top')  # saved automatically by v0.5.0 and older, not a choice
            info=dict(account=dict(type='chatgpt',planType='plus'),warning='',quota=[],model_quota={},models=[
                dict(model='top',displayName='Top',isDefault=True,description='Frontier intelligence for the most demanding work.'),
                dict(model='fast',displayName='Fast',description='Fast and affordable model for easier tasks.'),
                dict(model='new',displayName='New',description='Something not seen before.')])
            window.ai_connected(info)
            self.assertEqual(window.ai_models.currentData()['model'],'fast')
            self.assertEqual(window.ai_models.currentText(),'Fast（建議）')
            self.assertIn('建議使用「Fast」',window.ai_recommend.text())
            self.assertIn('快速、省額度',window.ai_model_detail.text())
            self.assertEqual(window.settings.value('ai_model'),'top')  # showing the suggestion is not a choice
            self.assertEqual([window.ai_compare.item(i,0).text() for i in range(3)],['Top（官方預設）','Fast（建議）','New'])
            self.assertEqual(window.ai_compare.item(0,1).text(),'最高階模型，適合最困難的工作。')
            self.assertIn('Frontier intelligence',window.ai_compare.item(0,1).toolTip())
            self.assertEqual(window.ai_compare.item(2,1).text(),'Something not seen before.')
            window.ai_models.setCurrentIndex(0)  # the user picks another model
            window.ai_connected(info);self.assertEqual(window.ai_models.currentData()['model'],'top')
            window.ai_connected(dict(info,model_quota={'fast':dict(remaining=0)},models=info['models'][1:]))
            self.assertEqual(window.ai_models.currentData()['model'],'new')  # pick gone, suggestion used up
            window.close()

    def test_ai_guard_warning_stops_before_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            window.ai_connected(dict(account=dict(type='chatgpt'),models=[dict(model='x')],quota=[],warning='未知額度'))
            window.session=dict(rows=[],report=d)
            with patch.object(QMessageBox,'warning') as warning,patch.object(window,'run_worker') as run:
                window.ai_supplement();warning.assert_called_once();run.assert_not_called()
            window.close()

    def test_connected_account_hides_setup_buttons_and_enables_ai_option(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            self.assertTrue(window.use_ai.isEnabled())  # preference is always clickable
            window.use_ai.setChecked(False);self.assertIn('不使用 AI',window.ai_hint.text())
            window.use_ai.setChecked(True);self.assertIn('尚未連接',window.ai_hint.text())
            with patch('mc_zh_tw_translator.codex_bridge.find_runtime',return_value=Path(d)/'codex.exe'):
                window.ai_connected(dict(account=dict(email='a@b.c',planType='plus'),warning='',quota=[],models=[dict(model='m',isDefault=True)]))
                self.assertTrue(window.ai_install_btn.isHidden());self.assertTrue(window.ai_login_btn.isHidden())
                self.assertFalse(window.ai_logout_btn.isHidden());self.assertTrue(window.use_ai.isEnabled())
                window.ai_connected(dict(account=dict(email='a@b.c'),warning='帳號已達用量限制',quota=[],models=[dict(model='m')]))
                self.assertTrue(window.use_ai.isEnabled());self.assertIn('用量限制',window.ai_hint.text())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes) as ask,patch.object(window,'run_worker') as run:
                    (Path(d)/"pack/mods").mkdir(parents=True);window.path.setText(str(Path(d)/"pack"));window.full_translation_job()
                    self.assertIn('AI 目前無法使用',ask.call_args[0][2])  # checked box never sends to an over-limit account
                    run.assert_called_once()
            window.close()

    def test_no_translation_rows_leave_missing_filter_and_page_size_applies(self):
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d))
            row=lambda text:dict(source='mods/a.jar!/assets/a/lang/en_us.json',key=text,en=text,proposed=text,origin='untranslated',supported=True,reviewed=False,changed=False)
            session=dict(report=d,status='needs_review',errors=[],source_counts={'untranslated':63},rows=[row('%s'),row('VI'),row('Shift'),row('NBT')]+[row(f'Ghost Chicken {i}') for i in range(60)])
            window.use_session(session);window.set_filter('missing')
            window.page_size.setCurrentIndex(window.page_size.findData(50))
            self.assertEqual(window.table.rowCount(),50);self.assertIn('共 60 筆',window.page_label.text())
            window.set_filter('keep');self.assertEqual(window.table.rowCount(),4)
            window.close()

    def test_confirmed_but_unapplied_report_offers_apply_without_retranslating(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);report=home/'output/demo/報告/old';report.mkdir(parents=True)
            row=dict(source='instance!/kubejs/assets/demo/lang/en_us.json',key='k',en='Hi',proposed='嗨',origin='same_source_zh_cn',
                     supported=True,reviewed=True,changed=True,review_method='auto_validated_one_click')
            (report/'session.json').write_text(json.dumps(dict(instance=d,report=str(report),status='needs_review',errors=[],source_counts={},rows=[row])),encoding='utf-8')
            window=MainWindow(home)
            self.assertIn('備份並套用譯文（1 筆',window.apply_btn.text())
            self.assertIn('還沒寫入模組包',window.report_summary.text())
            window.close()

    def test_history_label_is_readable_and_start_page_starts_compact(self):
        from mc_zh_tw_translator.desktop import history_label
        from mc_zh_tw_translator import desktop_jobs as jobs
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/'output/Pack/報告/20260928-235851-36c382';report.mkdir(parents=True)
            row=dict(source='s',key='k',en='Hi',proposed='嗨',origin='same_source_zh_cn',supported=True,reviewed=True,changed=True)
            jobs.write_json(report/'session.json',dict(report=str(report),status='needs_review',rows=[row]*3))
            self.assertEqual(history_label(report/'session.json'),'Pack　·　9/28 23:58　·　未套用　·　3 筆')
            window=MainWindow(Path(d))
            self.assertTrue(window.activity.isHidden());self.assertTrue(window.progress.isHidden())
            window.set_start_expanded(True);self.assertFalse(window.activity.isHidden())
            window.close()

    def test_terms_page_unifies_conflicts_and_apply_options_follow_checkboxes(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);report=home/'output/demo/報告/b';report.mkdir(parents=True)
            row=lambda zh:dict(source='mods/a.jar!/assets/a/lang/en_us.json',key='entity.a.direwolf',en='Direwolf',proposed=zh,origin='same_source_zh_cn',
                               supported=True,reviewed=False,changed=True,current=None,kind='language')
            (report/'session.json').write_text(json.dumps(dict(instance=d,report=str(report),status='needs_review',errors=[],source_counts={},
                                                              rows=[row('恐狼'),row('牙狼族')])),encoding='utf-8')
            window=MainWindow(home);window.navigate(5)
            self.assertEqual(window.conflicts.rowCount(),1)
            with patch.object(QMessageBox,'information'):window.unify_term('Direwolf','恐狼')
            self.assertEqual({r['proposed'] for r in window.session['rows']},{'恐狼'})
            self.assertEqual(window.term_table.rowCount(),1);self.assertEqual(window.conflicts.rowCount(),0)
            self.assertFalse(window.set_language.isChecked())  # optional, off unless the user ticks it
            window.close()

    def test_closing_during_background_check_quits_once_it_finishes(self):
        from mc_zh_tw_translator.desktop import Worker
        with tempfile.TemporaryDirectory() as d:
            window=MainWindow(Path(d));window.show()
            window.start_background(lambda w:time.sleep(.3),lambda _:None)
            with patch.object(QApplication,'quit') as quit_app:
                window.close();self.assertFalse(window.isVisible());quit_app.assert_not_called()
                for _ in range(300):
                    self.app.processEvents();time.sleep(.01)
                    if quit_app.called:break
                quit_app.assert_called_once()

    def test_report_applies_checked_rows_without_row_by_row_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);report=home/'output/demo/報告/b';report.mkdir(parents=True)
            row=lambda key,zh,**kw:dict(dict(source='mods/a.jar!/assets/a/lang/en_us.json',key=key,en='Hello %s',proposed=zh,origin='same_source_zh_cn',
                                         supported=True,reviewed=False,changed=True,current=None,kind='language'),**kw)
            rows=[row('a.one','你好 %s'),row('a.two','你好',),row('a.three','哈囉 %s',reviewed=True,review_method='user_confirmed_in_ui')]
            (report/'session.json').write_text(json.dumps(dict(instance=d,report=str(report),status='needs_review',errors=[],source_counts={},rows=rows)),encoding='utf-8')
            window=MainWindow(home);self.assertIn('2 筆',window.apply_btn.text())  # '你好' lost its %s, so it is not counted
            captured={}
            def fake_apply(session,home,notify):captured.update({r['key']:(r['reviewed'],r.get('review_method')) for r in session['rows']});return dict(session,status='installed')
            with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes),patch.object(QMessageBox,'information'),\
                 patch('mc_zh_tw_translator.desktop_jobs.apply_session',side_effect=fake_apply):
                window.apply_job()
                for _ in range(200):
                    self.app.processEvents();time.sleep(.01)
                    if not window.busy:break
            self.assertEqual(captured['a.one'],(True,'auto_validated_one_click'))
            self.assertEqual(captured['a.two'][0],False)
            self.assertEqual(captured['a.three'],(True,'user_confirmed_in_ui'))
            window.close()

    def test_shared_page_lists_catalog_with_install_status(self):
        with tempfile.TemporaryDirectory() as d:
            pack=dict(name='Demo',projectID=7,fileID=8,version='1.0',gameVersion='1.21.1',translator='我',updated='2026-09-29',
                      notes='',url='https://github.com/x',sha256='a'*64,size=1,modpackDate='2026-09-18',revision=2)
            mine=[dict(name='Demo',path=Path(d),projectID=7,fileID=8,gameVersion='1.21.1')]
            with patch('mc_zh_tw_translator.patches.fetch_catalog',return_value=[pack]),\
                 patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=mine):
                window=MainWindow(Path(d));window.navigate(6)
                for _ in range(200):
                    self.app.processEvents();time.sleep(.01)
                    if window.catalog:break
            self.assertTrue(window.navs[6].isChecked())
            self.assertEqual(window.catalog[0]['status'],'exact')
            self.assertEqual(window.catalog_box.count(),1);self.assertEqual([b.text() for b in window.pack_buttons],['安裝翻譯','建立伺服器'])
            window.close()

    def test_updated_translation_number_goes_once_the_page_is_seen(self):
        with tempfile.TemporaryDirectory() as d:
            pack=dict(name='Demo',projectID=7,fileID=8,version='1.0',gameVersion='1.21.1',translator='我',updated='2026-09-29',
                      notes='',url='https://github.com/x',sha256='a'*64,size=1,modpackDate='2026-09-18',revision=2)
            mine=[dict(name='Demo',path=Path(d),projectID=7,fileID=8,gameVersion='1.21.1')]
            applied={str(Path(d).resolve()).casefold():dict(sha256='b'*64,fileID=8)}
            with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=mine),\
                 patch('mc_zh_tw_translator.patches.applied_patches',return_value=applied):
                window=MainWindow(Path(d));window.catalog_loaded([pack])
                self.assertEqual(window.catalog[0]['status'],'update')
                self.assertEqual(window.navs[6].text(),'已翻譯整合包（1）')
                window.navigate(6)
                self.assertEqual(window.navs[6].text(),'已翻譯整合包')
                window.catalog_loaded([pack])  # read again later: still seen
                self.assertEqual(window.navs[6].text(),'已翻譯整合包')
                self.assertEqual(window.catalog[0]['status'],'update')
            window.close()

    def test_newer_whole_modpack_is_updated_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            pack=patches.full_entry(dict(kind='full',name='Foll v0.4.0',driveId='C'*33,sha256='b'*64,size=10))
            mine={'x':dict(path=d,name='Foll v0.3.0',sha256='a'*64)}
            with patch('mc_zh_tw_translator.full_pack.installed',return_value=mine),\
                 patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=[]):
                window=MainWindow(Path(d));window.catalog_loaded([pack])
            self.assertEqual(window.catalog[0]['status'],'full_update')
            self.assertEqual([b.text() for b in window.pack_buttons][:2],['更新整合包','另外安裝一份'])
            window.close()

    def test_whole_modpack_card_offers_one_install_button(self):
        with tempfile.TemporaryDirectory() as d:
            pack=patches.full_entry(dict(kind='full',name='Foll',version='0.3.0',driveId='C'*33,sha256='b'*64,size=800*1024**2,totalSize=2*1024**3))
            with patch('mc_zh_tw_translator.patches.fetch_catalog',return_value=[pack]),\
                 patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=[]):
                window=MainWindow(Path(d));window.navigate(6)
                for _ in range(200):
                    self.app.processEvents();time.sleep(.01)
                    if window.catalog:break
            self.assertEqual(window.catalog[0]['status'],'full')
            self.assertEqual([b.text() for b in window.pack_buttons],['安裝'])
            texts=' '.join(w.text() for w in window.catalog_box.itemAt(0).widget().findChildren(QLabel))
            self.assertIn('不在 CurseForge 上',texts);self.assertIn('0.8 GB',texts)
            self.assertNotIn('未標示',texts)
            window.close()

if __name__=='__main__':unittest.main()
