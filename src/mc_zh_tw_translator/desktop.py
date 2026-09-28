"""Native Windows desktop app, styled after the user's Agent Task Board."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSettings, QLockFile
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QColor, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QLineEdit, QFileDialog, QStackedWidget, QProgressBar,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QTextEdit, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QCheckBox,
    QScrollArea, QSizePolicy, QListView, QPlainTextEdit)

from . import desktop_jobs as jobs
from . import updater
from . import codex_bridge as ai

LIGHT_STYLE='''
QWidget { font-size: 14px; color: #363533; }
QMainWindow, #page, QDialog { background: #F8F8F8; }
#header, #sidebar, #card { background: #FFFFFF; }
#header { border-bottom: 1px solid #E4E4E3; }
#sidebar { border-right: 1px solid #E4E4E3; }
#card { border: 1px solid #E1E3E6; border-radius: 8px; }
QLabel { background: transparent; }
QLabel#title { font-size: 18px; font-weight: 700; }
QLabel#brand { color: #278AFC; font-size: 16px; font-weight: 700; }
QLabel#sub { color: #5F6670; font-size: 13px; }
QLabel#section { font-size: 13px; font-weight: 700; }
QLabel#number { font-size: 24px; font-weight: 700; }
QLabel#pill { color: #176FCC; background: #EBF4FF; border-radius: 10px; padding: 3px 8px; font-size: 12px; }
QPushButton { background: #FFFFFF; color: #2B2B2B; border: 1px solid #D9DDE2; border-radius: 7px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { border-color: #278AFC; color: #278AFC; }
QPushButton:disabled { color: #A7ACB4; background: #F3F4F5; border-color: #E4E7EB; }
QPushButton#primary { color: #FFFFFF; background: #278AFC; border: 1px solid #278AFC; }
QPushButton#primary:hover { background: #167BEE; }
QPushButton#primary:disabled { background: #B5D6FB; border-color: #B5D6FB; color: white; }
QPushButton#nav { text-align: left; border: none; border-radius: 7px; background: transparent; padding: 12px 16px; color: #6E737C; }
QPushButton#nav:checked { color: #278AFC; background: #EAF3FE; }
QLineEdit, QComboBox { background: #FFFFFF; color: #2B2B2B; border: 1px solid #DADEE4; border-radius: 6px; padding: 10px; }
QLineEdit:focus, QComboBox:focus { border-color: #278AFC; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #2B2B2B; selection-background-color: #EAF3FE; selection-color: #167BEE; border: 1px solid #DADEE4; }
QProgressBar { border: none; border-radius: 4px; background: #EAF0F6; height: 8px; text-align: center; }
QProgressBar::chunk { background: #278AFC; border-radius: 4px; }
QTableWidget { background: #FFFFFF; color: #2B2B2B; border: 1px solid #E1E3E6; border-radius: 7px; gridline-color: #F0F1F3; selection-background-color: #EAF3FE; selection-color: #2B2B2B; }
QHeaderView::section { background: #F4F6F8; color: #2B2B2B; padding: 10px; border: none; border-bottom: 1px solid #E1E3E6; font-weight: 600; font-size: 12px; }
QTextEdit, QPlainTextEdit, QListWidget { background: #FFFFFF; color: #2B2B2B; border: 1px solid #E1E3E6; border-radius: 7px; padding: 8px; }
QListWidget::item { padding: 12px; border-bottom: 1px solid #F0F1F3; }
QListWidget::item:selected { color: #278AFC; background: #EAF3FE; }
QCheckBox { color: #363533; }
QToolTip { background: #363533; color: #FFFFFF; border: 1px solid #777C84; }
'''

DARK_STYLE='''
QWidget { font-size: 14px; color: #F0F3F6; }
QMainWindow, #page, QDialog { background: #171A1F; }
#header, #sidebar, #card { background: #20252D; }
#header { border-bottom: 1px solid #343B46; }
#sidebar { border-right: 1px solid #343B46; }
#card { border: 1px solid #343B46; border-radius: 8px; }
QLabel { background: transparent; }
QLabel#title { font-size: 18px; font-weight: 700; color: #F5F7FA; }
QLabel#brand { color: #65B5FF; font-size: 16px; font-weight: 700; }
QLabel#sub { color: #AAB4C1; font-size: 13px; }
QLabel#section { font-size: 13px; font-weight: 700; color: #F0F4F8; }
QLabel#number { font-size: 24px; font-weight: 700; color: #F5F7FA; }
QLabel#pill { color: #8BCBFF; background: #173A5F; border-radius: 10px; padding: 3px 8px; font-size: 12px; }
QPushButton { background: #252B34; color: #E8EDF3; border: 1px solid #46505E; border-radius: 7px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { border-color: #65B5FF; color: #A9D9FF; }
QPushButton:disabled { color: #687383; background: #20252D; border-color: #343B46; }
QPushButton#primary { color: #FFFFFF; background: #278AFC; border: 1px solid #278AFC; }
QPushButton#primary:hover { background: #4BA3FF; }
QPushButton#primary:disabled { background: #315B83; border-color: #315B83; color: #B8C7D6; }
QPushButton#nav { text-align: left; border: none; border-radius: 7px; background: transparent; padding: 12px 16px; color: #AAB4C1; }
QPushButton#nav:checked { color: #8BCBFF; background: #173A5F; }
QLineEdit, QComboBox { background: #252B34; color: #E8EDF3; border: 1px solid #46505E; border-radius: 6px; padding: 10px; }
QLineEdit:focus, QComboBox:focus { border-color: #65B5FF; }
QComboBox QAbstractItemView { background: #20252D; color: #E8EDF3; selection-background-color: #285781; selection-color: #FFFFFF; border: 1px solid #46505E; }
QProgressBar { border: none; border-radius: 4px; background: #303946; height: 8px; text-align: center; }
QProgressBar::chunk { background: #278AFC; border-radius: 4px; }
QTableWidget { background: #20252D; color: #E8EDF3; border: 1px solid #343B46; border-radius: 7px; gridline-color: #303743; selection-background-color: #285781; selection-color: #FFFFFF; }
QHeaderView::section { background: #2A313B; color: #E8EDF3; padding: 10px; border: none; border-bottom: 1px solid #46505E; font-weight: 600; font-size: 12px; }
QTextEdit, QPlainTextEdit, QListWidget { background: #20252D; color: #E8EDF3; border: 1px solid #343B46; border-radius: 7px; padding: 8px; }
QListWidget::item { padding: 12px; border-bottom: 1px solid #303743; }
QListWidget::item:selected { color: #A9D9FF; background: #285781; }
QCheckBox { color: #E8EDF3; }
QToolTip { background: #F5F7FA; color: #171A1F; border: 1px solid #65B5FF; }
'''


COMMON_STYLE='''
QScrollArea { border: none; background: transparent; }
QComboBox { padding: 7px 30px 7px 10px; min-height: 22px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(__ARROW__); width: 12px; height: 12px; }
QComboBox QAbstractItemView::item { min-height: 32px; padding: 2px 8px; }
QPushButton { padding: 7px 12px; }
QPushButton#nav { padding: 10px 12px; }
QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar::handle:vertical { background: #8995A5; min-height: 28px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
'''


def label(text='',kind=None):
    widget=QLabel(text);widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    widget.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred);widget.setMinimumWidth(0)
    if kind=='pill':
        widget.setWordWrap(False);widget.setSizePolicy(QSizePolicy.Maximum,QSizePolicy.Fixed)
    if kind:widget.setObjectName(kind)
    return widget


def button(text,fn=None,primary=False):
    b=QPushButton(text);b.setCursor(Qt.PointingHandCursor)
    if primary:b.setObjectName('primary')
    if fn:b.clicked.connect(fn)
    return b


def card():
    frame=QFrame();frame.setObjectName('card')
    layout=QVBoxLayout(frame);layout.setContentsMargins(16,14,16,14);layout.setSpacing(10)
    return frame,layout


def open_path(path):
    if Path(path).exists():QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))


def bundled_path(relative):
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    return base/relative


class Worker(QThread):
    progress=Signal(int,str,str)
    login_url=Signal(str)
    result=Signal(object)
    checkpoint=Signal(str)
    failed=Signal(str)
    def __init__(self,operation):
        super().__init__();self.operation=operation;self.cancelled=False
    def run(self):
        try:self.result.emit(self.operation(self))
        except Exception as exc:
            logging.exception('Background operation failed')
            self.failed.emit(str(exc))
    def publish(self,session):
        # JSON crosses the thread boundary as an immutable snapshot.
        rows=session.get('rows',[])
        preview=dict(session,rows=rows[-200:],preview_total=len(rows),is_preview=True,
                     preview_changed=sum(bool(r.get('changed') and r.get('supported')) for r in rows),
                     preview_pending=sum(r.get('origin') in ('untranslated','pending') for r in rows))
        preview.pop('source_hashes',None)
        self.checkpoint.emit(json.dumps(preview,ensure_ascii=False))


class ReviewDialog(QDialog):
    def __init__(self,row,parent):
        super().__init__(parent);self.row=row
        self.setWindowTitle('校對翻譯');self.resize(760,650)
        box=QVBoxLayout(self);box.setSpacing(12)
        box.addWidget(label(row['key'],'section'))
        path=label(row['source'],'sub');path.setTextInteractionFlags(Qt.TextSelectableByMouse);box.addWidget(path)
        box.addWidget(label('原文'))
        original=QTextEdit();original.setPlainText(row.get('en') or row.get('zh_cn') or row.get('current') or '')
        original.setReadOnly(True);original.setMaximumHeight(155);box.addWidget(original)
        box.addWidget(label('繁體中文譯文'))
        self.value=QTextEdit();self.value.setPlainText(row['proposed']);box.addWidget(self.value)
        box.addWidget(label('來源：'+jobs.SOURCE_NAMES.get(row['origin'],row['origin'])+'　'+row.get('issue',''),'sub'))
        self.check=QCheckBox('我已核對語意、名稱、數值及操作條件');box.addWidget(self.check)
        actions=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Save).setText('確認這筆')
        actions.button(QDialogButtonBox.Cancel).setText('取消')
        actions.accepted.connect(self.accept_review);actions.rejected.connect(self.reject);box.addWidget(actions)
        if not row['supported'] or row.get('installed'):
            self.value.setReadOnly(True);self.check.setEnabled(False)
            actions.button(QDialogButtonBox.Save).setEnabled(False)
            box.addWidget(label('此項為已套用文字或需追查程式用途的候選，不能在此直接修改。','sub'))
    def accept_review(self):
        if not self.check.isChecked():
            QMessageBox.information(self,'請先校對','核對完成後，請勾選確認欄位。');return
        text=self.value.toPlainText()
        original=self.row.get('en') or self.row.get('zh_cn') or self.row.get('current') or ''
        if not jobs.validate_text(original,text):
            QMessageBox.warning(self,'格式不符','請保留原文的參數、格式碼及換行數量。');return
        if text!=self.row['proposed']:
            self.row['previous_origin']=self.row['origin'];self.row['origin']='manual'
        self.row.update(proposed=text,reviewed=True,changed=text!=self.row.get('current'),review_method='user_confirmed_in_ui')
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self,home):
        super().__init__();self.home=home;self.session=None;self.worker=None;self.busy=False;self.mode='';self.page_index=0;self.update_info=None;self.ai_info=None
        self.settings=QSettings(str(home/'settings.ini'),QSettings.IniFormat)
        self.preview_seen=set();self.started_at=0;self.last_activity=0;self.update_worker=None
        self.dark_theme=str(self.settings.value('theme','light')).lower()=='dark'
        self.setWindowTitle('模組包中文化 · MC Translator');self.resize(1120,800);self.setMinimumSize(880,600)
        icon_file=bundled_path('assets/mc-translator.ico')
        if icon_file.exists():self.setWindowIcon(QIcon(str(icon_file)))
        else:
            icon=QPixmap(64,64);icon.fill(QColor('#278AFC'))
            painter=QPainter(icon);painter.setPen(QColor('white'));painter.setFont(QFont('Microsoft JhengHei UI',30,QFont.Bold));painter.drawText(icon.rect(),Qt.AlignCenter,'譯');painter.end();self.setWindowIcon(QIcon(icon))
        root=QWidget();self.setCentralWidget(root);shell=QVBoxLayout(root);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        header=QFrame();header.setObjectName('header');header.setFixedHeight(52)
        top=QHBoxLayout(header);top.setContentsMargins(24,0,24,0)
        brand=label('MC  /  模組包中文化','brand');brand.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred)
        top.addWidget(brand);top.addStretch()
        self.update_badge=button('有新版本',lambda:self.navigate(3));self.update_badge.hide();top.addWidget(self.update_badge)
        self.theme_btn=button('亮色模式' if self.dark_theme else '深色模式',self.toggle_theme)
        self.theme_btn.setToolTip('切換介面顏色；設定會自動記住')
        top.addWidget(self.theme_btn);top.addSpacing(10);top.addWidget(label('v'+updater.VERSION,'pill'));shell.addWidget(header)
        body=QHBoxLayout();body.setSpacing(0);shell.addLayout(body,1)
        sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(176)
        nav=QVBoxLayout(sidebar);nav.setContentsMargins(12,18,12,16);nav.setSpacing(6)
        nav.addWidget(label('工作空間','sub'));nav.addSpacing(10)
        self.navs=[]
        for i,text in enumerate(('開始翻譯','翻譯報告','備份與還原','程式更新','AI 帳號與模型')):
            b=button(text,lambda checked=False,n=i:self.navigate(n));b.setObjectName('nav');b.setCheckable(True);nav.addWidget(b);self.navs.append(b)
        nav.addStretch();nav.addWidget(label('繁體中文 / 台灣\nAI 補翻需同意傳送文字','sub'));body.addWidget(sidebar)
        self.pages=QStackedWidget();body.addWidget(self.pages,1)
        self.make_start();self.make_report();self.make_backups();self.make_updates();self.make_ai();self.navigate(0)
        self.refresh_history();self.refresh_backups()
        self.path.setText(self.settings.value('instance',''))
        for combo in self.findChildren(QComboBox):
            view=QListView();view.setUniformItemSizes(True);combo.setView(view)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10);combo.setMaxVisibleItems(10)
        self.apply_theme()
        self.clock=QTimer(self);self.clock.timeout.connect(self.tick_progress);self.clock.start(1000)
        self.restore_latest_report()

    def page(self,title,subtitle):
        page=QWidget();page.setObjectName('page')
        layout=QVBoxLayout(page);layout.setContentsMargins(20,18,20,18);layout.setSpacing(12)
        layout.addWidget(label(title,'title'));layout.addWidget(label(subtitle,'sub'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pages.addWidget(scroll);return layout

    def make_start(self):
        box=self.page('翻譯工作台','選擇模組包，掃描、翻譯、備份與套用一次完成。')
        f,b=card();b.addWidget(label('模組包資料夾','section'))
        b.addWidget(label('選擇包含 mods、config 或 kubejs 的資料夾。','sub'))
        row=QHBoxLayout();self.path=QLineEdit();self.path.setPlaceholderText('可直接貼上資料夾路徑，或按「選擇資料夾」');self.path.setReadOnly(False)
        self.path.setToolTip('可從檔案總管複製路徑後直接貼上；貼上後按一鍵翻譯即可。')
        self.path.textChanged.connect(lambda value:self.settings.setValue('instance',value.strip().strip('"')))
        self.choose=button('選擇資料夾',self.choose_folder);row.addWidget(self.path,1);row.addWidget(self.choose);b.addLayout(row)
        actions=QHBoxLayout();self.full_start=button('一鍵完整翻譯並套用',self.full_translation_job,True);self.cancel=button('停止',self.cancel_job);self.cancel.setEnabled(False)
        actions.addWidget(self.full_start);actions.addWidget(self.cancel);actions.addStretch();b.addLayout(actions);box.addWidget(f)
        stats=QHBoxLayout();self.stats=[]
        for title,sub in (('已產生譯文','可在報告查看來源'),('仍待處理','缺少來源或需查用途'),('已套用','已備份並寫回資料夾')):
            f,b=card();b.addWidget(label(title,'sub'));n=label('—','number');self.stats.append(n);b.addWidget(n);b.addWidget(label(sub,'sub'));stats.addWidget(f)
        box.addLayout(stats)
        f,b=card();head=QHBoxLayout();head.addWidget(label('處理進度','section'));head.addStretch();self.status=label('等待開始','pill');head.addWidget(self.status);b.addLayout(head)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setTextVisible(False);b.addWidget(self.progress)
        self.progress.setFixedHeight(6)
        self.step=label('準備好了，先選擇你的模組包。');self.detail=label('原始檔會在套用前備份，翻譯報告直接顯示在程式裡。','sub');b.addWidget(self.step);b.addWidget(self.detail)
        self.elapsed=label('掃描會自動執行，不需要另外操作。','sub');b.addWidget(self.elapsed)
        self.report_link=button('查看翻譯報告',lambda:self.navigate(1));b.addWidget(self.report_link,alignment=Qt.AlignLeft);box.addWidget(f)
        head=QHBoxLayout();head.addWidget(label('即時處理紀錄','section'));head.addStretch();box.addLayout(head)
        self.activity=QPlainTextEdit();self.activity.setReadOnly(True);self.activity.setMinimumHeight(130)
        self.activity.setMaximumBlockCount(300);self.activity.setPlaceholderText('開始後會列出目前處理的檔案、下載進度，以及最新產生的原文 → 譯文。')
        box.addWidget(self.activity,1)
        box.addWidget(label('優先使用模組包中文與參考庫；選用 AI 補翻會消耗你原本的 Codex 額度。','sub'))

    def make_report(self):
        box=self.page('翻譯報告','隨處理進度保存；即使停止或尚未套用，也能查看已產生的內容。')
        row=QHBoxLayout();self.history=QComboBox();self.history.setMinimumWidth(280);self.history.activated.connect(self.load_history)
        row.addWidget(self.history,1);row.addWidget(button('重新整理',self.refresh_history));self.folder_btn=button('開啟報告資料夾',self.open_report);row.addWidget(self.folder_btn);box.addLayout(row)
        self.report_summary=label('尚未有翻譯紀錄。完成掃描後，這裡會顯示實際結果。');box.addWidget(self.report_summary)
        self.filter=QComboBox();self.filter.addItems(['需要校對','缺少中文來源','待查程式與設定','已確認／已套用','全部','AI 補譯'])
        self.filter.setCurrentIndex(4)
        self.filter.currentIndexChanged.connect(self.reset_table)
        self.search=QLineEdit();self.search.setPlaceholderText('搜尋模組、文字或語系鍵');self.search.textChanged.connect(self.reset_table)
        r=QHBoxLayout();r.addWidget(self.filter);r.addWidget(self.search,1);box.addLayout(r)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['原文 / 語系鍵','建議譯文','來源','狀態'])
        self.table.setMinimumHeight(210);self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide();self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.table.setColumnWidth(2,120);self.table.setColumnWidth(3,110);self.table.cellDoubleClicked.connect(self.review_row);box.addWidget(self.table,1)
        nav=QHBoxLayout();self.prev=button('上一頁',lambda:self.turn_page(-1));self.next=button('下一頁',lambda:self.turn_page(1));self.page_label=label('0 筆','sub')
        nav.addWidget(self.prev);nav.addWidget(self.next);nav.addWidget(self.page_label);nav.addStretch();box.addLayout(nav)
        actions=QHBoxLayout();self.review_btn=button('查看並校對',self.review_current);self.apply_btn=button('備份並套用已確認譯文',self.apply_job,True)
        self.ai_run_btn=button('AI 補翻缺漏',self.ai_supplement)
        actions.addWidget(self.review_btn);actions.addWidget(self.ai_run_btn);actions.addStretch();box.addLayout(actions)
        box.addWidget(self.apply_btn,alignment=Qt.AlignRight)
        box.addWidget(label('一般使用者可直接使用「一鍵完整翻譯並套用」；這裡保留逐筆查看、來源和例外報告，方便進階修訂。','sub'))

    def make_backups(self):
        box=self.page('備份與還原','每次套用都保留原檔。還原前會檢查後續修改，避免蓋掉你的檔案。')
        self.backups=QListWidget();box.addWidget(self.backups,1)
        row=QHBoxLayout();row.addWidget(button('重新整理',self.refresh_backups));row.addWidget(button('開啟備份資料夾',self.open_backup));row.addStretch()
        self.restore_btn=button('還原選取批次',self.restore_job);row.addWidget(self.restore_btn);box.addLayout(row)
        box.addWidget(label('只還原該批修改的檔案，並移除該批新增的翻譯檔。若檔案之後有變更，會先停止並說明。','sub'))

    def make_updates(self):
        box=self.page('程式更新','開啟時自動檢查新版本，下載與安裝由你決定。')
        f,b=card();row=QHBoxLayout();row.addWidget(label('MC Translator','section'));row.addStretch();row.addWidget(label('v'+updater.VERSION,'pill'));b.addLayout(row)
        b.addWidget(label('檢查更新 → 閱讀更新內容 → 決定是否下載與安裝','sub'))
        self.update_status=label('尚未檢查更新。');b.addWidget(self.update_status)
        r=QHBoxLayout();self.check_btn=button('檢查更新',self.check_updates,True);self.install_btn=button('下載並安裝更新',self.install_update);self.install_btn.setEnabled(False)
        r.addWidget(self.check_btn);r.addWidget(self.install_btn);r.addStretch();b.addLayout(r);box.addWidget(f)
        self.release_notes=QTextEdit();self.release_notes.setReadOnly(True);self.release_notes.setPlaceholderText('有新版本時，更新說明會顯示在這裡。');box.addWidget(self.release_notes,1)
        self.auto_update=QCheckBox('開啟程式時檢查更新（不自動下載）')
        self.auto_update.setChecked(str(self.settings.value('check_updates_on_start','true')).lower()=='true')
        self.auto_update.toggled.connect(lambda value:self.settings.setValue('check_updates_on_start','true' if value else 'false'))
        box.addWidget(self.auto_update)
        self.update_progress=QProgressBar();self.update_progress.setValue(0);box.addWidget(self.update_progress)
        box.addWidget(label('更新只替換程式本身，翻譯資料、備份與設定都會保留。公開版本會由 GitHub 自動提供給所有使用者。','sub'))

    def navigate(self,index):
        self.pages.setCurrentIndex(index)
        for i,b in enumerate(self.navs):b.setChecked(i==index)
        if index==1:self.fill_table()
        if index==2:self.refresh_backups()

    def apply_theme(self):
        style=(DARK_STYLE if self.dark_theme else LIGHT_STYLE)+COMMON_STYLE.replace('__ARROW__',bundled_path('assets/chevron.svg').as_posix())
        QApplication.instance().setStyleSheet(style)
        self.theme_btn.setText('亮色模式' if self.dark_theme else '深色模式')
        self.settings.setValue('theme','dark' if self.dark_theme else 'light')
        QApplication.processEvents()

    def toggle_theme(self):
        if self.busy:return
        self.dark_theme=not self.dark_theme
        self.apply_theme()

    def make_ai(self):
        box=self.page('AI 帳號與模型','選用功能。不登入也能使用參考庫翻譯。')
        f,b=card();b.addWidget(label('使用你原本的 Codex 額度','section'))
        b.addWidget(label(ai.NOTICE));b.addWidget(label(ai.PRIVACY,'sub'));box.addWidget(f)
        f,b=card();self.ai_status=label('尚未連接 ChatGPT。登入只在官方網頁完成。');b.addWidget(self.ai_status)
        row=QHBoxLayout();self.ai_install_btn=button('安裝官方元件',self.install_ai_runtime)
        self.ai_login_btn=button('連接 ChatGPT',self.login_ai,True);self.ai_refresh_btn=button('重新整理',self.refresh_ai)
        self.ai_logout_btn=button('登出',self.logout_ai)
        for widget in (self.ai_install_btn,self.ai_login_btn,self.ai_refresh_btn,self.ai_logout_btn):row.addWidget(widget)
        b.addLayout(row);self.ai_quota=label('額度尚未確認。不會使用 API key 或自動購買點數。','sub');b.addWidget(self.ai_quota);box.addWidget(f)
        f,b=card();b.addWidget(label('補翻模型','section'))
        self.ai_models=QComboBox();self.ai_models.setPlaceholderText('登入後載入帳號可用模型');b.addWidget(self.ai_models)
        self.ai_model_detail=label('模型會影響上下文與術語判斷，較強不代表保證正確；目前沒有本專案的模型品質排行榜。','sub');b.addWidget(self.ai_model_detail)
        self.ai_models.currentIndexChanged.connect(self.select_ai_model)
        b.addWidget(label('只列官方回傳的可用模型，使用該模型建議的推理設定。若模型不可用會停止，不偷偷換模型。','sub'))
        b.addWidget(button('前往翻譯報告補翻缺漏',lambda:self.navigate(1)),alignment=Qt.AlignLeft);box.addWidget(f)
        self.ai_stop_btn=button('停止登入／補翻',self.cancel_job);self.ai_stop_btn.setEnabled(False);box.addWidget(self.ai_stop_btn,alignment=Qt.AlignLeft)
        box.addStretch()

    def select_ai_model(self,*_):
        model=self.ai_models.currentData()
        if model:
            self.settings.setValue('ai_model',model['model'])
            self.ai_model_detail.setText((model.get('description') or model['model'])+'\n不同模型可能消耗不同額度；譯文仍需校對。')

    def ai_operation(self,action,w):
        with ai.CodexClient(self.home,lambda:w.cancelled) as client:
            if action=='login':return client.login(w.login_url.emit)
            if action=='logout':client.call('account/logout');return dict(account=None,models=[],quota=[],warning='已登出本程式的 ChatGPT 連接。')
            return client.catalog()

    def install_ai_runtime(self):
        if QMessageBox.question(self,'安裝官方 Codex 元件','將從 OpenAI 官方 GitHub 下載並校驗 Windows 元件（約數百 MB）。\n只安裝到本程式資料夾，不會登入或消耗模型額度。是否繼續？')!=QMessageBox.Yes:return
        self.run_worker('ai_install',lambda w:ai.install_runtime(self.home,w.progress.emit,lambda:w.cancelled),lambda _:self.ai_status.setText('官方元件已安裝，請按「連接 ChatGPT」。'))

    def login_ai(self):
        if not ai.find_runtime(self.home):
            QMessageBox.information(self,'先安裝官方元件','請按「安裝官方元件」，完成後再連接 ChatGPT。');return
        if QMessageBox.question(self,'連接前請確認',ai.NOTICE+'\n\n'+ai.PRIVACY+'\n\n登入本身不啟動翻譯。是否開啟官方登入頁？')!=QMessageBox.Yes:return
        self.ai_status.setText('等待官方網頁登入，最長 5 分鐘；可按停止。')
        self.run_worker('ai_login',lambda w:self.ai_operation('login',w),self.ai_connected)

    def open_ai_login(self,url):
        try:
            ai.validate_login_url(url)
            if not QDesktopServices.openUrl(QUrl(url)):raise ValueError('無法開啟預設瀏覽器，請檢查系統設定後重試。')
        except Exception as exc:
            self.worker.cancelled=True;self.on_error(str(exc))

    def refresh_ai(self):self.run_worker('ai_refresh',lambda w:self.ai_operation('refresh',w),self.ai_connected)
    def logout_ai(self):self.run_worker('ai_logout',lambda w:self.ai_operation('logout',w),self.ai_connected)

    def ai_connected(self,result):
        self.ai_info=result;account=result.get('account');saved=self.settings.value('ai_model','')
        self.ai_models.blockSignals(True);self.ai_models.clear();default_index=0
        for i,model in enumerate(result.get('models',[])):
            self.ai_models.addItem(model.get('displayName') or model['model'],model)
            if model.get('isDefault'):default_index=i
        chosen=next((i for i in range(self.ai_models.count()) if self.ai_models.itemData(i)['model']==saved),default_index)
        if self.ai_models.count():self.ai_models.setCurrentIndex(chosen)
        self.ai_models.blockSignals(False);self.select_ai_model()
        self.ai_status.setText(('已連接 '+str(account.get('email') or 'ChatGPT')+' · '+str(account.get('planType') or '未知方案')) if account else '尚未連接 ChatGPT。')
        self.ai_quota.setText(result.get('warning') or '　'.join(f"{q['minutes'] or '?'} 分鐘視窗剩餘 {q['remaining']:g}%" for q in result.get('quota',[])))

    def ai_supplement(self):
        if not self.session:
            QMessageBox.information(self,'先掃描模組包','請先開始翻譯並完成參考來源比對。');return
        model=self.ai_models.currentData()
        if not self.ai_info or not self.ai_info.get('account') or not model:
            self.navigate(4);QMessageBox.information(self,'先連接帳號','請登入 ChatGPT、確認額度並選擇補翻模型。');return
        if self.ai_info.get('warning'):
            QMessageBox.warning(self,'暫不補翻',self.ai_info['warning']+'\n可按重新整理再次確認。');return
        count=len(ai.pending_rows(self.session))
        if not count:QMessageBox.information(self,'沒有可補翻缺漏','已完成的 AI 候選不會重送；待查程式與設定不會交給 AI 直接修改。');return
        if QMessageBox.question(self,'使用原方案額度補翻？',f'模型：{model["model"]}\n待補翻：{count} 筆（分批處理）\n\n'+ai.NOTICE+'\n\n'+ai.PRIVACY)!=QMessageBox.Yes:return
        self.run_worker('ai_translate',lambda w:ai.supplement(self.session,self.home,model['model'],w.progress.emit,lambda:w.cancelled,checkpoint=w.publish),self.ai_done)

    def ai_done(self,result):
        self.job_done(result);self.ai_status.setText(result['ai_message']);self.navigate(1)
        if result.get('ai_status')=='paused':QMessageBox.information(self,'AI 補翻已暫停',result['ai_message'])

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'選擇模組包根資料夾',self.path.text() or str(Path.home()))
        if path:self.path.setText(path);self.settings.setValue('instance',path)

    def instance_path(self):
        value=str(self.path.text() or '').strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
            value=value[1:-1].strip()
        return Path(value)

    def run_worker(self,mode,operation,done):
        if self.busy:return
        self.busy=True;self.mode=mode
        self.started_at=self.last_activity=time.monotonic()
        for b in (self.path,self.full_start,self.choose,self.apply_btn,self.restore_btn,self.check_btn,self.install_btn,self.review_btn,self.ai_install_btn,self.ai_login_btn,self.ai_refresh_btn,self.ai_logout_btn,self.ai_run_btn,self.ai_models):b.setEnabled(False)
        self.history.setEnabled(False);self.cancel.setEnabled(mode in ('plan','full_translate','ai_translate','ai_login','ai_install'));self.ai_stop_btn.setEnabled(mode in ('ai_translate','ai_login','ai_install'))
        self.worker=Worker(operation)
        self.worker.progress.connect(self.on_progress)
        self.worker.checkpoint.connect(self.receive_checkpoint)
        self.worker.login_url.connect(self.open_ai_login)
        self.worker.result.connect(done);self.worker.failed.connect(self.on_error);self.worker.finished.connect(self.finish_worker);self.worker.start()

    def finish_worker(self):
        self.busy=False
        self.progress.setRange(0,100)
        for b in (self.path,self.full_start,self.choose,self.apply_btn,self.restore_btn,self.check_btn,self.review_btn,self.ai_install_btn,self.ai_login_btn,self.ai_refresh_btn,self.ai_logout_btn,self.ai_run_btn,self.ai_models):b.setEnabled(True)
        self.history.setEnabled(True);self.cancel.setEnabled(False);self.ai_stop_btn.setEnabled(False)
        self.install_btn.setEnabled(bool(self.update_info and self.update_info.get('status')=='available'))

    def on_progress(self,value,title,detail):
        self.last_activity=time.monotonic()
        if self.mode=='full_translate':
            # Overall stages never show 100% at the end of source matching.
            if title=='來源整理完成':value=65
            elif title.startswith('AI'):value=65+int(value*.10)
            elif title in ('驗證並準備套用','備份與套用','重新掃描實際遊戲資料','已套用已校對的文字'):value=75+int(value*.25)
            else:value=int(value*.65)
        if title in ('更新參考庫','AI 補翻中'):self.progress.setRange(0,0)
        else:self.progress.setRange(0,100)
        self.progress.setValue(value);self.step.setText(title);self.detail.setText(detail);self.status.setText('處理中')
        self.cancel.setEnabled(self.mode in ('plan','full_translate','ai_translate','ai_login','ai_install') and title not in ('驗證並準備套用','備份與套用','重新掃描實際遊戲資料','已套用已校對的文字'))
        self.append_activity(title+' · '+detail)
        if self.mode.startswith('ai_'):self.ai_status.setText(title+'：'+detail)

    def append_activity(self,text):
        line=time.strftime('%H:%M:%S')+'  '+str(text).replace('\n',' ')
        self.activity.appendPlainText(line)

    def tick_progress(self):
        if not self.busy:return
        elapsed=int(time.monotonic()-self.started_at);idle=int(time.monotonic()-self.last_activity)
        text=f'已執行 {elapsed//60:02d}:{elapsed%60:02d}'
        if idle>=15:text+=f' · {idle} 秒未收到新進度，仍在等待目前步驟回應'
        self.elapsed.setText(text)

    def receive_checkpoint(self,payload):
        result=json.loads(payload)
        if not self.session or self.session['report']!=result['report']:
            self.activity.clear();self.page_index=0;self.preview_seen=set()
        self.session=result
        fresh=[]
        for row in result.get('rows',[]):
            key=(row['source'],row['key'],row.get('proposed'))
            if row.get('changed') and key not in getattr(self,'preview_seen',set()):
                fresh.append(row)
                self.preview_seen.add(key)
        for row in fresh[-5:]:
            self.append_activity(f"{jobs.SOURCE_NAMES.get(row['origin'],row['origin'])} · {(row.get('en') or row.get('zh_cn') or row['key'])[:65]} → {row['proposed'][:80]}（尚未套用）")
        if len(fresh)>5:self.append_activity(f'另有 {len(fresh)-5:,} 筆譯文，完整內容請看翻譯報告。')
        self.update_stats();self.refresh_history();self.fill_table()

    def restore_latest_report(self):
        candidates=list((self.home/'output').glob('*/報告/*/session.json'))
        if not candidates:return
        path=max(candidates,key=lambda p:p.stat().st_mtime)
        try:
            self.session=json.loads(path.read_text(encoding='utf-8'))
            self.update_stats();self.refresh_history();self.fill_table()
        except (ValueError,OSError,KeyError):logging.exception('Cannot restore last report')

    def on_error(self,text):
        if self.mode in ('check_update','download_update'):self.update_status.setText('更新未完成：'+text)
        elif self.mode.startswith('ai_'):self.ai_status.setText(text)
        else:
            self.status.setText('需要處理');self.detail.setText(text)
            if self.session and self.mode=='apply':
                self.session.update(status='apply_failed',apply_error=text)
                jobs.write_json(Path(self.session['report'])/'session.json',self.session)
                self.update_stats();self.fill_table()
        QMessageBox.warning(self,'需要處理',text)

    def start_job(self):
        if not self.path.text().strip():self.choose_folder()
        if not self.path.text().strip():return
        instance=self.instance_path();self.progress.setValue(0);self.status.setText('處理中')
        self.run_worker('plan',lambda w:jobs.plan(instance,self.home,w.progress.emit,lambda:w.cancelled,checkpoint=w.publish),self.job_done)

    def full_translation_job(self):
        if not self.path.text().strip(): self.choose_folder()
        if not self.path.text().strip(): return
        model=self.ai_models.currentData() if self.ai_info and self.ai_info.get('account') else None
        if self.ai_info and self.ai_info.get('warning'):
            QMessageBox.warning(self,'AI 額度尚未確認',self.ai_info['warning']+'\n可先使用免費來源，或重新整理 AI 額度後再試。')
            return
        ai_line=('會使用模型「'+model['model']+'」補翻缺漏，消耗你原本 ChatGPT 的 Codex 額度。'
                 if model else '目前沒有連接 AI，會先套用免費來源；缺少可靠來源的文字會留在報告。')
        prompt=('這會掃描整個模組包、翻譯可辨識的玩家文字、建立備份並直接套用。\n'
                +ai_line+'\n\n遊戲必須先關閉；圖片文字、硬編碼程式和無法確認的特殊格式會列入報告。\n是否繼續？')
        if QMessageBox.question(self,'一鍵完整翻譯',prompt)!=QMessageBox.Yes:return
        instance=self.instance_path();self.progress.setValue(0);self.status.setText('處理中')
        self.run_worker('full_translate',lambda w:self.full_translation_operation(instance,model,w),self.full_translation_done)

    def full_translation_operation(self,instance,model,w):
        return jobs.full_translation(instance,self.home,model['model'] if model else None,w.progress.emit,lambda:w.cancelled,w.publish)

    def full_translation_done(self,result):
        self.job_done(result);self.navigate(1)
        applied=result.get('installed_count',0)
        leftovers=sum(r.get('origin')=='untranslated' for r in result.get('rows',[]))
        if result['status']=='installed':
            QMessageBox.information(self,'本次處理完成',f'已套用 {applied:,} 筆。\n仍待處理 {leftovers:,} 筆，請查看報告。')
        elif result['status']=='awaiting_game':
            QMessageBox.information(self,'譯文已保存，等待套用',result['apply_error'])

    def cancel_job(self):
        if self.worker and self.mode in ('plan','full_translate','ai_translate','ai_login','ai_install'):
            self.worker.cancelled=True;self.cancel.setEnabled(False);self.ai_stop_btn.setEnabled(False);self.detail.setText('正在停止，已送出的 AI 請求可能已消耗額度…')

    def job_done(self,result):
        self.session=result
        names={'installed':'已套用部分','blocked':'需要處理','awaiting_game':'等待關閉遊戲','apply_failed':'套用未完成','cancelled':'已停止'}
        self.status.setText(names.get(result['status'],'可查看報告'))
        self.progress.setRange(0,100)
        if result['status']=='installed':self.progress.setValue(100)
        self.update_stats()
        self.refresh_history();self.refresh_backups();self.fill_table()
        if result['status']=='blocked':self.detail.setText(str(result['errors'][-1][-1]))
        elif result.get('apply_error'):self.detail.setText(result['apply_error'])
        self.step.setText(self.status.text());self.append_activity(self.status.text())

    def update_stats(self):
        rows=self.session['rows'];self.stats[0].setText(f"{self.session.get('preview_changed',sum(bool(r['changed'] and r['supported']) for r in rows)):,}")
        self.stats[1].setText(f"{self.session.get('preview_pending',sum(r['origin'] in ('untranslated','pending') for r in rows)):,}");self.stats[2].setText(f"{self.session.get('installed_count',0):,}")
        self.apply_btn.setText('重試套用（不重新翻譯）' if self.session['status'] in ('awaiting_game','apply_failed','ready_to_apply') else '備份並套用已確認譯文')

    def refresh_history(self):
        current=self.session['report'] if self.session else None
        self.history.clear();self.history.addItem('選擇本機翻譯紀錄',None)
        for p in sorted((self.home/'output').glob('*/報告/*/session.json'),reverse=True)[:100]:
            self.history.addItem(p.parents[2].name+' / '+p.parent.name,str(p))
            if str(p.parent)==current:self.history.setCurrentIndex(self.history.count()-1)

    def load_history(self,index):
        path=self.history.itemData(index)
        if path:
            try:self.session=json.loads(Path(path).read_text(encoding='utf-8'));self.page_index=0;self.fill_table()
            except Exception as exc:QMessageBox.warning(self,'無法讀取紀錄',str(exc))

    def reset_table(self,*_):self.page_index=0;self.fill_table()
    def turn_page(self,direction):self.page_index=max(0,self.page_index+direction);self.fill_table()

    def fill_table(self):
        if not self.session:
            self.table.setRowCount(0);return
        rows=self.session['rows'];mode=self.filter.currentIndex();query=self.search.text().strip().casefold()
        def match(r):
            if query and query not in (r['source']+' '+r['key']+' '+str(r.get('en') or r.get('current') or '')+' '+r['proposed']).casefold():return False
            if mode==0:return r['supported'] and r['changed'] and not r['reviewed']
            if mode==1:return r['supported'] and r['origin']=='untranslated'
            if mode==2:return not r['supported']
            if mode==3:return r['reviewed'] or r.get('installed')
            if mode==5:return r['origin']=='ai_translation' or r.get('previous_origin')=='ai_translation'
            return True
        filtered=[r for r in rows if match(r)];self.page_index=min(self.page_index,max(0,(len(filtered)-1)//100))
        self.visible_rows=filtered[self.page_index*100:(self.page_index+1)*100]
        self.table.setRowCount(len(self.visible_rows))
        for i,r in enumerate(self.visible_rows):
            state='已套用' if r.get('installed') else '待套用' if r.get('review_method')=='auto_validated_one_click' else '已確認' if r['reviewed'] else '比對中' if r['origin']=='pending' else '待校對' if r['supported'] and r['changed'] else '待查'
            for j,text in enumerate((r.get('en') or r.get('zh_cn') or r.get('current') or r['key'],r['proposed'],jobs.SOURCE_NAMES.get(r['origin'],r['origin']),state)):
                item=QTableWidgetItem(str(text).replace('\n',' ')[:130]);item.setToolTip(str(text));self.table.setItem(i,j,item)
            self.table.setRowHeight(i,44)
        self.page_label.setText(f'共 {len(filtered):,} 筆 · 第 {self.page_index+1} / {max(1,(len(filtered)+99)//100)} 頁')
        self.prev.setEnabled(self.page_index>0);self.next.setEnabled((self.page_index+1)*100<len(filtered))
        counts=self.session.get('source_counts',{})
        summary='　'.join(f'{jobs.SOURCE_NAMES.get(k,k)} {v:,}' for k,v in counts.items())
        errors=self.session.get('errors',[])
        stages={'scanning':'掃描中，找到的文字稍後會列在這裡。','references':'掃描已完成，正在更新參考庫；下方暫列原文。','matching':'正在比對中文來源，譯文陸續加入。','awaiting_game':'譯文已保存。關閉相關遊戲後，按右下方重試套用。','cancelled':'已停止；已保存的內容仍可查看。','apply_failed':'套用未完成；譯文已保存。','blocked':'此批次無法繼續，請查看下方原因。'}
        message=stages.get(self.session['status'],'本次已產生的譯文與待處理項目如下。')
        if self.session.get('is_preview'):message+=f"\n已記錄 {self.session['preview_total']:,} 筆，處理中先預覽最近 200 筆；結束後載入完整報告。"
        self.report_summary.setText(message+f"\n已套用 {self.session.get('installed_count',0):,} 筆 · AI {self.session.get('ai_translation',0):,} 筆 · 額外付費 API 0 筆\n"+summary+(('\n需要處理：'+str(errors[0])) if errors else '')+('\n'+self.session['apply_error'] if self.session.get('apply_error') else ''))

    def review_current(self):self.review_row(self.table.currentRow(),0)
    def review_row(self,index,column=0):
        if self.busy or not self.session or index<0 or index>=len(getattr(self,'visible_rows',[])):return
        dialog=ReviewDialog(self.visible_rows[index],self)
        if dialog.exec()==QDialog.Accepted:
            jobs.write_json(Path(self.session['report'])/'session.json',self.session);self.fill_table()

    def apply_job(self):
        if not self.session:return
        count=sum(bool(r.get('reviewed') and r.get('changed') and r.get('supported') and not r.get('installed')) for r in self.session['rows'])
        if not count:QMessageBox.information(self,'先校對譯文','請在報告中雙擊譯文，核對後按「確認這筆」。');return
        if QMessageBox.question(self,'備份並套用',f'將備份原檔，並套用 {count} 筆已確認譯文到：\n{self.session["instance"]}\n\n請先關閉此模組包的遊戲。是否繼續？')!=QMessageBox.Yes:return
        self.navigate(0);self.run_worker('apply',lambda w:jobs.apply_session(self.session,self.home,w.progress.emit),self.job_done)

    def open_report(self):
        if self.session:open_path(self.session['report'])

    def refresh_backups(self):
        self.backups.clear()
        for p in sorted((self.home/'output').glob('*/原始備份/*/_備份紀錄/manifest.json'),reverse=True):
            try:
                data=json.loads(p.read_text(encoding='utf-8'))
                state={'installed':'可還原','restored':'已還原','restoring':'還原中斷','backed_up':'已備份','rolled_back':'已復原失敗操作'}.get(data['status'],data['status'])
                item=QListWidgetItem(f"{Path(data['instance']).name}   ·   {state}\n{p.parents[1].name}　{len(data['files'])} 個檔案")
                item.setData(Qt.UserRole,(str(p.parents[1]),data));self.backups.addItem(item)
            except (ValueError,KeyError,OSError):continue

    def open_backup(self):
        item=self.backups.currentItem()
        if item:open_path(item.data(Qt.UserRole)[0])

    def restore_job(self):
        item=self.backups.currentItem()
        if not item:return
        backup,data=item.data(Qt.UserRole)
        if QMessageBox.question(self,'還原這一批翻譯？',f"將還原 {len(data['files'])} 個檔案：\n{data['instance']}\n\n本批新增的翻譯檔也會移除；有後續修改時會停止。")!=QMessageBox.Yes:return
        self.run_worker('restore',lambda w:jobs.restore_backup(Path(backup),Path(data['instance'])),self.restore_done)
    def restore_done(self,result):
        if self.session and self.session.get('backup')==result['backup_path']:
            self.session['status']='restored';self.session['installed_count']=0
            for row in self.session['rows']:
                if row.get('installed'):row['installed']=False;row['reviewed']=False
            jobs.write_json(Path(self.session['report'])/'session.json',self.session)
            self.stats[2].setText('0');self.status.setText('已還原');self.fill_table()
        self.refresh_backups();QMessageBox.information(self,'已還原','原檔已還原，本批新增翻譯檔已移除。備份仍保留。')

    def check_updates(self):
        self.update_status.setText('正在檢查 GitHub 正式版本…')
        self.run_worker('check_update',lambda w:updater.check_update(),self.update_checked)

    def check_updates_on_start(self):
        if not self.auto_update.isChecked() or self.update_worker:return
        self.update_worker=Worker(lambda w:updater.check_update())
        self.update_worker.result.connect(self.update_checked)
        self.update_worker.failed.connect(lambda _:self.update_status.setText('暫時無法連線檢查更新，可稍後再試。'))
        self.update_worker.finished.connect(self.startup_check_finished)
        self.update_worker.start()

    def startup_check_finished(self):
        self.update_worker.deleteLater();self.update_worker=None

    def update_checked(self,info):
        self.update_info=info
        self.update_status.setText('有新版本 '+info['version'] if info['status']=='available' else info['message'])
        self.release_notes.setPlainText(info.get('notes',''))
        available=info['status']=='available'
        self.navs[3].setText('程式更新 · 有新版' if available else '程式更新')
        self.update_badge.setText('新版本 '+info.get('version',''));self.update_badge.setVisible(available)
        self.install_btn.setEnabled(available and not self.busy)
    def install_update(self):
        if not self.update_info or self.update_info['status']!='available':return
        if not getattr(sys,'frozen',False):QMessageBox.information(self,'原始碼模式','請在打包後的 EXE 使用程式更新。');return
        if QMessageBox.question(self,'下載並安裝更新',f"更新到 {self.update_info['version']}？\n下載後會校驗、關閉程式並重新啟動。備份、報告和設定都會保留。")!=QMessageBox.Yes:return
        self.run_worker('download_update',lambda w:updater.download_update(self.update_info,self.home,lambda p:w.progress.emit(p,'下載更新','')),self.update_downloaded)
        self.worker.progress.connect(lambda p,*_:self.update_progress.setValue(p))
    def update_downloaded(self,result):
        try:
            updater.launch_update(result[0],result[1],self.home)
            self.worker.finished.connect(QApplication.instance().quit)
            self.update_status.setText('校驗完成，準備重新啟動…')
        except Exception as exc:self.on_error(str(exc))

    def closeEvent(self,event):
        if self.busy:
            QMessageBox.information(self,'工作仍在進行','請等待目前工作完成。掃描工作可先按「停止」，套用與更新期間請勿關閉。');event.ignore()
        elif self.update_worker and self.update_worker.isRunning():
            # Defer destruction until the bounded HTTP request returns; never kill QThread.
            self.hide();self.update_worker.finished.connect(self.close);event.ignore()
        else:event.accept()


def app_home():
    base=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
    try:
        home=base/'MCTranslatorData';home.mkdir(exist_ok=True)
        test=home/'.writable';test.write_text('ok');test.unlink();return home
    except OSError:
        home=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MCTranslator'
        home.mkdir(parents=True,exist_ok=True);return home


def main():
    if '--apply-update' in sys.argv:
        try:updater.apply_update(sys.argv[sys.argv.index('--apply-update')+1])
        except Exception as exc:
            if os.name=='nt':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None,'更新失敗，請重新開啟原程式。\n'+str(exc),'MC Translator',0x10)
        return
    if os.name=='nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MCTranslator.Desktop')
    app=QApplication(sys.argv)
    fonts=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for filename in ('segoeui.ttf','msjh.ttc','msjhbd.ttc'):
        if (fonts/filename).exists():QFontDatabase.addApplicationFont(str(fonts/filename))
    font=QFont();font.setFamilies(['Segoe UI','Microsoft JhengHei UI','Microsoft JhengHei'])
    font.setPointSize(10);font.setStyleHint(QFont.SansSerif);font.setHintingPreference(QFont.PreferFullHinting)
    app.setFont(font);app.setStyle('Fusion')
    home=app_home();logging.basicConfig(filename=home/'application.log',encoding='utf-8',level=logging.INFO)
    lock=QLockFile(str(home/'application.lock'))
    if not lock.tryLock(50):QMessageBox.information(None,'程式已開啟','請切換到已開啟的 MC Translator 視窗。');return
    window=MainWindow(home);window.show()
    smoke_dest=sys.argv[sys.argv.index('--smoke-test')+1] if '--smoke-test' in sys.argv else os.environ.get('MC_TRANSLATOR_SMOKE_DEST')
    if smoke_dest:
        dest=Path(smoke_dest);dest.mkdir(parents=True,exist_ok=True)
        def capture():
            window.grab().save(str(dest/'desktop.png'))
            window.navigate(3);app.processEvents();window.grab().save(str(dest/'updates.png'))
            window.navigate(4);app.processEvents();window.grab().save(str(dest/'ai.png'))
            (dest/'smoke.json').write_text(json.dumps(dict(version=updater.VERSION,window=window.windowTitle(),tabs=window.pages.count(),frozen=bool(getattr(sys,'frozen',False)))),encoding='utf-8')
            app.quit()
        QTimer.singleShot(800,capture)
    else:QTimer.singleShot(1800,window.check_updates_on_start)
    app.exec();lock.unlock()


if __name__=='__main__':main()
