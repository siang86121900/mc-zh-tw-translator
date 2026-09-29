import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from mc_zh_tw_translator.desktop import MainWindow


class DesktopUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

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
                for _ in range(500):
                    self.app.processEvents();time.sleep(.02)
                    if not window.busy:break
                if window.busy:
                    window.worker.cancelled=True;window.worker.wait(10000);self.app.processEvents()
            self.assertFalse(window.busy)
            self.assertIsNotNone(window.session)
            self.assertEqual(window.session['rows'][0]['proposed'],'你好')
            self.assertEqual(window.stats[0].text(),'1')
            self.assertTrue(window.choose.isEnabled())
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
                    window.path.setText(d);window.full_translation_job()
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
            self.assertIn('套用這批譯文（1 筆',window.apply_btn.text())
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

    def test_shared_page_lists_catalog_with_install_status(self):
        with tempfile.TemporaryDirectory() as d:
            pack=dict(name='Demo',projectID=7,fileID=8,version='1.0',gameVersion='1.21.1',translator='我',updated='2026-09-29',
                      notes='',url='https://github.com/x',sha256='a'*64,size=1)
            mine=[dict(name='Demo',path=Path(d),projectID=7,fileID=8,gameVersion='1.21.1')]
            with patch('mc_zh_tw_translator.patches.fetch_catalog',return_value=[pack]),\
                 patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances',return_value=mine):
                window=MainWindow(Path(d));window.navigate(6)
                for _ in range(200):
                    self.app.processEvents();time.sleep(.01)
                    if window.catalog:break
            self.assertTrue(window.navs[6].isChecked())
            self.assertEqual(window.catalog[0]['status'],'exact')
            self.assertEqual(window.catalog_list.count(),1)
            window.close()

if __name__=='__main__':unittest.main()
