"""Native Windows desktop app, styled after the user's Agent Task Board."""
from __future__ import annotations

import collections
import json
import logging
import os
import re
import sys
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSettings, QLockFile, QSize, QRect, QPoint
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QColor, QPixmap, QPalette
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QLineEdit, QFileDialog, QStackedWidget, QProgressBar,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QTextEdit, QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QCheckBox,
    QScrollArea, QSizePolicy, QListView, QPlainTextEdit, QSystemTrayIcon, QStyledItemDelegate, QStyle, QLayout)

from . import desktop_jobs as jobs
from . import updater
from . import codex_bridge as ai
from . import patches

# Tokens follow ai-agent-team DESIGN.md: one primary blue, neutrals derived from #363533,
# four status colours, 6px cards, 8px buttons, pill badges and filter chips.
THEMES={
    'light':dict(bg='#F8F8F8',surface='#FFFFFF',text='#363533',text80='#5E5D5C',text60='#868583',text40='#AFAEAD',
                 gray='#D7D7D6',line='#EBEBEA',soft='#FAFAFA',primary='#278AFC',primary_hover='#167BEE',primary_bg='#EDF5FF',
                 primary_fade='#A9CFFD',disabled_bg='#F3F3F3',green='#00C37B',orange='#F5A623',red='#E83232',tooltip_bg='#363533',tooltip='#FFFFFF'),
    'dark':dict(bg='#16181C',surface='#1F2228',text='#ECEDEE',text80='#C5C7CB',text60='#9A9EA5',text40='#6C7078',
                gray='#3A3F48',line='#2C3037',soft='#252930',primary='#4A9DFD',primary_hover='#6BB0FF',primary_bg='#1C3350',
                primary_fade='#2F5E93',disabled_bg='#23262C',green='#1DD48F',orange='#F5A623',red='#FF5A5A',tooltip_bg='#ECEDEE',tooltip='#16181C'),
}

STYLE_TEMPLATE='''
QWidget { font-size: 14px; color: {text}; }
QMainWindow, #page, QDialog { background: {bg}; }
#header, #sidebar, #card { background: {surface}; }
#header { border-bottom: 1px solid {gray}; }
#sidebar { border-right: 1px solid {gray}; }
#overview { background: {soft}; border: 1px solid {line}; border-radius: 6px; }
#card { border: 1px solid {gray}; border-radius: 6px; }
#card:hover { border-color: {primary_fade}; }
QLabel { background: transparent; }
QLabel#title { font-size: 18px; font-weight: 700; }
QLabel#brand { color: {primary}; font-size: 15px; font-weight: 700; }
QLabel#sub { color: {text60}; font-size: 12px; }
QLabel#muted { color: {text80}; font-size: 13px; }
QLabel#warn { color: {red}; font-size: 12px; font-weight: 600; }
QLabel#section { font-size: 13px; font-weight: 700; }
QLabel#number { font-size: 26px; font-weight: 700; }
QLabel#pill { border-radius: 10px; padding: 0px 10px; min-height: 22px; max-height: 22px; font-size: 11px; font-weight: 700; color: {primary}; background: {primary_bg}; }
QLabel#pill[state="todo"] { color: {text80}; background: {gray}; }
QLabel#pill[state="progress"] { color: #FFFFFF; background: {orange}; }
QLabel#pill[state="done"] { color: #FFFFFF; background: {green}; }
QLabel#pill[state="blocked"] { color: #FFFFFF; background: {red}; }
QFrame#accent_todo { background: {gray}; border: none; }
QFrame#accent_progress { background: {orange}; border: none; }
QFrame#accent_done { background: {green}; border: none; }
QPushButton { background: {surface}; color: {text}; border: 1px solid {gray}; border-radius: 8px; padding: 8px 16px; font-weight: 600; }
QPushButton:hover { border-color: {primary}; color: {primary}; }
QPushButton:disabled { color: {text40}; background: {disabled_bg}; border-color: {line}; }
QPushButton#primary { color: #FFFFFF; background: {primary}; border: 1px solid {primary}; }
QPushButton#primary:hover { background: {primary_hover}; border-color: {primary_hover}; color: #FFFFFF; }
QPushButton#primary:disabled { background: {primary_fade}; border-color: {primary_fade}; color: #FFFFFF; }
QPushButton#link { border: none; background: transparent; color: {primary}; padding: 2px 0px; text-align: left; }
QPushButton#link:hover { text-decoration: underline; }
QPushButton#iconbtn { padding: 0px; font-size: 16px; border-radius: 16px; color: {text80}; }
QPushButton#iconbtn:hover { color: {primary}; border-color: {primary}; }
QPushButton#nav { text-align: left; border: none; border-radius: 8px; background: transparent; padding: 10px 12px; color: {text80}; font-weight: 600; }
QPushButton#nav:hover { color: {primary}; }
QPushButton#nav:checked { color: {primary}; background: {primary_bg}; }
QPushButton#chip { border: 1.5px solid {gray}; border-radius: 14px; padding: 5px 12px; font-size: 12px; font-weight: 600; color: {text80}; background: {surface}; }
QPushButton#chip:hover { border-color: {primary}; color: {primary}; }
QPushButton#chip:checked { border-color: {primary}; background: {primary}; color: #FFFFFF; }
QLineEdit, QComboBox { background: {surface}; color: {text}; border: 1px solid {gray}; border-radius: 8px; padding: 8px 10px; }
QLineEdit:focus, QComboBox:focus { border-color: {primary}; }
QComboBox { padding: 6px 30px 6px 10px; min-height: 22px; combobox-popup: 0; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(__ARROW__); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: {surface}; color: {text}; border: 1px solid {gray}; padding: 4px; outline: 0px; }
QComboBox QAbstractItemView::item { min-height: 32px; padding: 0px 10px; border-radius: 6px; }
QComboBox QAbstractItemView::item:hover { background: {soft}; color: {text}; }
QComboBox QAbstractItemView::item:selected { background: {primary_bg}; color: {primary}; }
QProgressBar { border: none; border-radius: 3px; background: {line}; text-align: center; }
QProgressBar::chunk { background: {primary}; border-radius: 3px; }
QTableWidget { background: {surface}; color: {text}; border: 1px solid {gray}; border-radius: 6px; gridline-color: {line}; selection-background-color: {primary_bg}; selection-color: {text}; alternate-background-color: {soft}; }
QTableWidget::item { padding: 4px 8px; border-bottom: 1px solid {line}; }
QHeaderView::section { background: {soft}; color: {text80}; padding: 9px 8px; border: none; border-bottom: 1px solid {gray}; font-weight: 700; font-size: 12px; }
QTextEdit, QPlainTextEdit, QListWidget { background: {surface}; color: {text}; border: 1px solid {gray}; border-radius: 6px; padding: 8px; }
QPlainTextEdit#log { font-family: Consolas, "Microsoft JhengHei UI"; font-size: 12px; color: {text80}; }
QListWidget { padding: 6px; outline: 0px; }
QListWidget::item { border: 1px solid {gray}; border-radius: 6px; margin: 4px 2px; background: {surface}; }
QListWidget::item:hover { border-color: {primary_fade}; }
QListWidget::item:selected { border-color: {primary}; background: {primary_bg}; color: {text}; }
QCheckBox { color: {text}; spacing: 8px; }
QCheckBox:disabled { color: {text40}; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1.5px solid {gray}; border-radius: 4px; background: {surface}; }
QCheckBox::indicator:hover { border-color: {primary}; }
QCheckBox::indicator:checked { border-color: {primary}; background: {primary}; image: url(__CHECK__); }
QCheckBox::indicator:disabled { border-color: {line}; background: {disabled_bg}; }
QCheckBox::indicator:checked:disabled { border-color: {primary_fade}; background: {primary_fade}; }
QToolTip { background: {tooltip_bg}; color: {tooltip}; border: none; padding: 4px 6px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar::handle:vertical { background: {text40}; min-height: 28px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
'''

# Table state colours reuse the four DESIGN.md status roles.
STATE_ROLE={'不需更動':'text40','已套用':'green','已套用・建議確認':'orange','待套用':'primary','已確認':'primary','待校對':'orange','比對中':'text60','待查':'text60','無需翻譯':'text40'}


def stylesheet(theme):
    tokens=THEMES[theme]
    return (re.sub(r'\{(\w+)\}',lambda m:tokens.get(m[1],m[0]),STYLE_TEMPLATE)
            .replace('__ARROW__',bundled_path('assets/chevron.svg').as_posix())
            .replace('__CHECK__',bundled_path('assets/check.svg').as_posix()))


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


def set_pill(widget,text,state=''):
    """Status badge: todo / progress / done / blocked, or '' for the neutral info pill."""
    widget.setText(text);widget.setProperty('state',state)
    widget.style().unpolish(widget);widget.style().polish(widget)


class TaskbarProgress:
    """Windows taskbar button progress (ITaskbarList3) via ctypes; silently inert elsewhere."""
    NOPROGRESS,INDETERMINATE,NORMAL,ERROR,PAUSED=0,1,2,4,8
    def __init__(self):
        self.ptr=None
        if os.name!='nt':return
        try:
            import ctypes,uuid
            from ctypes import wintypes
            self.ctypes=ctypes
            ole=ctypes.windll.ole32;ole.CoInitialize(None)
            guid=lambda s:(ctypes.c_byte*16).from_buffer_copy(uuid.UUID(s).bytes_le)
            ptr=ctypes.c_void_p()
            if ole.CoCreateInstance(guid('56FDF344-FD6D-11d0-958A-006097C9A090'),None,1,
                                    guid('ea1afb91-9e28-4b86-90e9-9e9f8a5eee84'),ctypes.byref(ptr))!=0:return
            vtable=ctypes.cast(ctypes.cast(ptr,ctypes.POINTER(ctypes.c_void_p))[0],ctypes.POINTER(ctypes.c_void_p))
            proto=lambda i,*args:ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,*args)(vtable[i])
            self.hr_init=proto(3);self.set_value=proto(9,wintypes.HWND,ctypes.c_ulonglong,ctypes.c_ulonglong)
            self.set_state=proto(10,wintypes.HWND,ctypes.c_int)
            if self.hr_init(ptr)==0:self.ptr=ptr
        except Exception:
            logging.info('Taskbar progress unavailable',exc_info=True)
    def update(self,window,value=None,state=NORMAL):
        if not self.ptr:return
        try:
            hwnd=int(window.winId());self.set_state(self.ptr,hwnd,state)
            if value is not None and state==self.NORMAL:self.set_value(self.ptr,hwnd,max(0,min(100,int(value))),100)
        except Exception:
            logging.info('Taskbar progress update failed',exc_info=True)


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
            self.failed.emit(jobs.explain_error(exc))
    def publish(self,session):
        # JSON crosses the thread boundary as an immutable snapshot.
        rows=session.get('rows',[])
        preview=dict(session,rows=rows[-200:],preview_total=len(rows),is_preview=True,
                     # The cards need every row; the preview carries only the last 200.
                     preview_cards=jobs.home_cards(session))
        preview.pop('source_hashes',None)
        self.checkpoint.emit(json.dumps(preview,ensure_ascii=False))


MODULE_ROLE=Qt.UserRole+1


class OriginalDelegate(QStyledItemDelegate):
    """Original text with its mod namespace underneath in small muted type."""
    def __init__(self,window):
        super().__init__(window);self.window=window
    def paint(self,painter,option,index):
        module=index.data(MODULE_ROLE)
        if not module:return super().paint(painter,option,index)
        self.initStyleOption(option,index);text=option.text;option.text=''
        style=option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem,option,painter,option.widget)
        tokens=THEMES['dark' if self.window.dark_theme else 'light']
        rect=option.rect.adjusted(10,5,-8,-5);painter.save()
        painter.setPen(QColor(tokens['text']));painter.setFont(option.font)
        painter.drawText(rect,Qt.AlignLeft|Qt.AlignTop,option.fontMetrics.elidedText(text,Qt.ElideRight,rect.width()))
        small=QFont(option.font);small.setPointSizeF(max(7.0,option.font.pointSizeF()*0.78));painter.setFont(small)
        painter.setPen(QColor(tokens['text60']));painter.drawText(rect,Qt.AlignLeft|Qt.AlignBottom,module)
        painter.restore()


def stamp_text(name):
    """'20260929-010716-f0aed0' -> '9/29 01:07'; unknown formats pass through."""
    m=re.match(r'(\d{4})(\d{2})(\d{2})-?(\d{2})(\d{2})',name)
    return f'{int(m[2])}/{int(m[3])} {m[4]}:{m[5]}' if m else name


def history_label(session_path):
    """Readable report name: modpack · time · state · count, from the small summary sidecar."""
    parts=[session_path.parents[2].name,stamp_text(session_path.parent.name)]
    try:
        s=json.loads((session_path.parent/'summary.json').read_text(encoding='utf-8'))
        if s.get('status')=='installed':parts+=['已套用',f"{s.get('installed_count',0):,} 筆"]
        elif s.get('pending_apply'):parts+=['未套用',f"{s['pending_apply']:,} 筆"]
        else:parts+=[{'cancelled':'已停止','blocked':'需要處理','restored':'已還原','awaiting_game':'等待關閉遊戲',
                      'apply_failed':'套用未完成'}.get(s.get('status'),'待校對'),f"{s.get('translated',0):,} 筆"]
    except (OSError,ValueError):
        parts.append('舊紀錄')
    return '　·　'.join(parts)


def row_module(row):
    if jobs.lang_namespace(row.get('source','')):return jobs.lang_namespace(row['source'])
    m=re.search(r'assets/([^/]+)/',row.get('source',''))
    return m[1] if m else row.get('source','').split('!')[0]


def row_memory_scope(row):
    return row.get('source','') if row.get('kind')=='class_display' else row_module(row)


class ReviewDialog(QDialog):
    def __init__(self,row,parent):
        super().__init__(parent);self.row=row
        self.setWindowTitle('校對翻譯');self.resize(760,650)
        box=QVBoxLayout(self);box.setSpacing(12)
        session=getattr(parent,'session',None) or {}
        outer=row.get('source','').split('!/')[0]
        shown=jobs.mod_display_name(session.get('instance'),outer) if outer.startswith('mods/') and session.get('instance') else ''
        box.addWidget(label(jobs.module_label(session.get('instance'),row)+(f'　（{shown}）' if shown else ''),'section'))
        box.addWidget(label(row['key'],'muted'))
        path=label(row['source'],'sub');path.setTextInteractionFlags(Qt.TextSelectableByMouse);box.addWidget(path)
        box.addWidget(label('原文'))
        original=QTextEdit();original.setPlainText(jobs.original_of(row))
        original.setReadOnly(True);original.setMaximumHeight(155);box.addWidget(original)
        box.addWidget(label('繁體中文譯文'))
        self.value=QTextEdit();self.value.setPlainText(row['proposed']);box.addWidget(self.value)
        box.addWidget(label('來源：'+jobs.SOURCE_NAMES.get(row['origin'],row['origin'])+'　'+row.get('issue',''),'sub'))
        rejected=row.get('ai_rejected') or {}
        if rejected.get('text') and row['supported'] and not row.get('installed'):
            # The AI answer the checks turned down: a starting point the user can fix, never applied as is.
            box.addWidget(label('AI 的譯文（沒有通過檢查，未採用）'))
            answer=QTextEdit();answer.setPlainText(rejected['text']);answer.setReadOnly(True);answer.setMaximumHeight(130);box.addWidget(answer)
            use=button('拿這句來修改',lambda:self.value.setPlainText(rejected['text']))
            hint=(jobs.format_problem(jobs.original_of(row),rejected['text']).split('\n')[0]
                  if rejected.get('reason')=='format' and not jobs.validate_text(jobs.original_of(row),jobs.repair(jobs.original_of(row),rejected['text']))
                  else '換行位置和參數順序會自動對齊原文，不用自己調' if rejected.get('reason')=='format'
                  else str(rejected.get('detail') or '數字要和原文一樣'))
            line=QHBoxLayout();line.addWidget(use);line.addWidget(label('修改時注意：'+hint,'sub'),1);box.addLayout(line)
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
        original=jobs.original_of(self.row)
        text=jobs.index_placeholders(original,text)  # parameters numbered for Chinese word order
        # What the user typed keeps the user's own line breaks, even when the English has more lines.
        own_lines=not jobs.validate_text(original,text) and jobs.fits(original,text,True)
        if not jobs.fits(original,text,own_lines):
            QMessageBox.warning(self,'格式不符',jobs.format_problem(original,text));return
        if own_lines:self.row['own_lines']=True
        else:self.row.pop('own_lines',None)
        if text!=self.row['proposed']:
            self.row['previous_origin']=self.row['origin'];self.row['origin']='manual'
        self.row.update(proposed=text,reviewed=True,changed=text!=self.row.get('current'),review_method='user_confirmed_in_ui')
        self.accept()


class FlowLayout(QLayout):
    """Widgets in a row that continues on the next line when the window is too narrow."""
    def __init__(self,parent=None,spacing=8):
        super().__init__(parent);self.items=[];self.setSpacing(spacing);self.setContentsMargins(0,0,0,0)
    def addItem(self,item):self.items.append(item)
    def count(self):return len(self.items)
    def itemAt(self,index):return self.items[index] if 0<=index<len(self.items) else None
    def takeAt(self,index):return self.items.pop(index) if 0<=index<len(self.items) else None
    def expandingDirections(self):return Qt.Orientations()
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self.arrange(QRect(0,0,width,0),False)
    def setGeometry(self,rect):
        super().setGeometry(rect);self.arrange(rect,True)
    def sizeHint(self):return self.minimumSize()
    def minimumSize(self):
        size=QSize()
        for item in self.shown():size=size.expandedTo(item.minimumSize())
        return size
    def shown(self):return [i for i in self.items if not i.isEmpty()]
    def arrange(self,rect,move):
        x=rect.x();y=rect.y();line=0
        for item in self.shown():
            hint=item.sizeHint()
            if x>rect.x() and x+hint.width()>rect.right()+1:
                x=rect.x();y+=line+self.spacing();line=0
            if move:item.setGeometry(QRect(QPoint(x,y),hint))
            x+=hint.width()+self.spacing();line=max(line,hint.height())
        return y+line-rect.y()


class MainWindow(QMainWindow):
    def __init__(self,home):
        super().__init__();self.home=home;self.session=None;self.worker=None;self.busy=False;self.mode='';self.page_index=0;self.update_info=None;self.ai_info=None;self.ai_recommended=None
        self.settings=QSettings(str(home/'settings.ini'),QSettings.IniFormat)
        self.preview_seen=set();self.started_at=0;self.last_activity=0;self.update_worker=None
        self.background=[];self.quit_after_worker=False;self.filter_mode='all';self.live_session=False
        self.taskbar=TaskbarProgress();self.tray=None
        self.dark_theme=str(self.settings.value('theme','light')).lower()=='dark'
        self.setWindowTitle('模組包中文化 · MC Translator');self.resize(1120,800);self.setMinimumSize(880,600)
        geometry=self.settings.value('geometry')
        if geometry is not None:self.restoreGeometry(geometry)
        icon_file=bundled_path('assets/mc-translator.ico')
        if icon_file.exists():self.setWindowIcon(QIcon(str(icon_file)))
        else:
            icon=QPixmap(64,64);icon.fill(QColor('#278AFC'))
            painter=QPainter(icon);painter.setPen(QColor('white'));painter.setFont(QFont('Microsoft JhengHei UI',30,QFont.Bold));painter.drawText(icon.rect(),Qt.AlignCenter,'譯');painter.end();self.setWindowIcon(QIcon(icon))
        root=QWidget();self.setCentralWidget(root);shell=QVBoxLayout(root);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        header=QFrame();header.setObjectName('header');header.setFixedHeight(52)
        top=QHBoxLayout(header);top.setContentsMargins(24,0,24,0)
        brand=label('MC  /  模組包中文化','brand');brand.setWordWrap(False);brand.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Preferred)
        top.addWidget(brand);top.addStretch()
        self.update_badge=button('有新版本',lambda:self.navigate(3));self.update_badge.hide();top.addWidget(self.update_badge)
        self.theme_btn=button('',self.toggle_theme);self.theme_btn.setObjectName('iconbtn');self.theme_btn.setFixedSize(36,32)
        top.addWidget(self.theme_btn);top.addSpacing(10);top.addWidget(label('v'+updater.VERSION,'pill'));shell.addWidget(header)
        body=QHBoxLayout();body.setSpacing(0);shell.addLayout(body,1)
        sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(200)
        nav=QVBoxLayout(sidebar);nav.setContentsMargins(12,18,12,16);nav.setSpacing(6)
        nav.addWidget(label('工作空間','sub'));nav.addSpacing(10)
        self.navs=[]
        for i,text in enumerate(('開始翻譯','翻譯報告','備份與還原','程式更新','AI 帳號與模型')):
            b=button(text,lambda checked=False,n=i:self.navigate(n));b.setObjectName('nav');b.setCheckable(True);nav.addWidget(b);self.navs.append(b)
        # Page 5 sits under 翻譯報告 in the sidebar; page indexes of the other pages stay unchanged.
        b=button('譯名與用詞',lambda checked=False:self.navigate(5));b.setObjectName('nav');b.setCheckable(True)
        nav.insertWidget(4,b);self.navs.append(b)
        # Page 6 (shared translations) sits right under 開始翻譯.
        b=button('已翻譯整合包',lambda checked=False:self.navigate(6));b.setObjectName('nav');b.setCheckable(True)
        nav.insertWidget(3,b);self.navs.append(b)
        nav.addStretch();self.side_ai=label('AI 補翻：未連接','sub');nav.addWidget(self.side_ai)
        nav.addWidget(label('繁體中文 / 台灣','sub'));body.addWidget(sidebar)
        self.pages=QStackedWidget();body.addWidget(self.pages,1)
        self.make_start();self.make_report();self.make_backups();self.make_updates();self.make_ai();self.make_terms();self.make_shared();self.navigate(0)
        self.refresh_history();self.refresh_backups()
        self.refresh_instances();self.path.setText(self.settings.value('instance',''))
        for combo in self.findChildren(QComboBox):
            # A translucent popup renders black on real Windows desktops, so the popup stays opaque and
            # takes its colours from the themed application palette (see apply_theme).
            view=QListView();view.setUniformItemSizes(True);combo.setView(view)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10);combo.setMaxVisibleItems(10)
        self.apply_theme();self.update_ai_controls()
        self.clock=QTimer(self);self.clock.timeout.connect(self.tick_progress);self.clock.start(1000)
        self.restore_latest_report();self.check_outdated()

    def page(self,title,subtitle):
        page=QWidget();page.setObjectName('page')
        layout=QVBoxLayout(page);layout.setContentsMargins(20,18,20,18);layout.setSpacing(12)
        layout.addWidget(label(title,'title'));layout.addWidget(label(subtitle,'sub'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pages.addWidget(scroll);return layout

    def make_start(self):
        box=self.page('翻譯工作台','選擇模組包，掃描、翻譯、備份與套用一次完成。')
        # Shown when a translated modpack was updated in its launcher, which replaces the translated files.
        self.outdated_card,self.outdated_box=card();self.outdated_card.hide();box.addWidget(self.outdated_card)
        f,b=card();b.addWidget(label('模組包資料夾','section'))
        b.addWidget(label('從清單選擇偵測到的模組包，或直接貼上包含 mods、config 或 kubejs 的資料夾路徑。','sub'))
        # Editable combo: detected launchers' instances in the list, and free text for any other location.
        row=QHBoxLayout();self.instance_box=QComboBox();self.instance_box.setEditable(True);self.instance_box.setInsertPolicy(QComboBox.NoInsert)
        self.path=self.instance_box.lineEdit();self.path.setPlaceholderText('選擇模組包，或貼上資料夾路徑')
        self.path.setToolTip('清單會列出 CurseForge、Modrinth、Prism 等啟動器的模組包，以及你用過的資料夾。找不到時可直接貼上路徑。')
        self.path.textChanged.connect(lambda value:self.settings.setValue('instance',value.strip().strip('"')))
        self.instance_box.activated.connect(self.pick_instance)
        self.choose=button('選擇資料夾',self.choose_folder);row.addWidget(self.instance_box,1);row.addWidget(self.choose);b.addLayout(row)
        # Reference sources translate first; AI only fills what is still missing, and only when opted in.
        ai_row=QHBoxLayout();self.use_ai=QCheckBox('用 AI 補翻缺漏，並核對有疑點的譯文')
        self.use_ai.setChecked(str(self.settings.value('use_ai','true')).lower()=='true')
        self.use_ai.toggled.connect(lambda value:(self.settings.setValue('use_ai','true' if value else 'false'),self.update_ai_controls()))
        self.ai_connect_link=button('連接 AI 帳號',lambda:self.navigate(4));self.ai_connect_link.setObjectName('link')
        ai_row.addWidget(self.use_ai);ai_row.addWidget(self.ai_connect_link);ai_row.addStretch();b.addLayout(ai_row)
        self.ai_hint=label('','sub');b.addWidget(self.ai_hint)
        # Optional: many modpacks ship with lang:en_us; players may also switch the language themselves.
        self.set_language=QCheckBox('套用後把遊戲語言設為繁體中文（台灣）')
        self.set_language.setToolTip('修改模組包的 options.txt（lang:zh_tw），修改前一樣會備份，可在「備份與還原」復原。')
        self.set_language.setChecked(str(self.settings.value('set_language','false')).lower()=='true')
        self.set_language.toggled.connect(lambda v:self.settings.setValue('set_language','true' if v else 'false'));b.addWidget(self.set_language)
        actions=QHBoxLayout();self.full_start=button('一鍵完整翻譯並套用',self.full_translation_job,True);self.cancel=button('停止',self.cancel_job);self.cancel.setEnabled(False)
        actions.addWidget(self.full_start);actions.addWidget(self.cancel);actions.addStretch();b.addLayout(actions);box.addWidget(f)
        stats=QHBoxLayout();stats.setSpacing(12);self.stats=[];self.stat_notes=[]
        for title,accent in zip(jobs.HOME_CARDS,('done','todo')):
            f,b=card();strip=QFrame();strip.setObjectName('accent_'+accent);strip.setFixedHeight(3);b.insertWidget(0,strip)
            b.addWidget(label(title,'sub'));n=label('—','number');self.stats.append(n);b.addWidget(n)
            note=label('','sub');note.setWordWrap(True);self.stat_notes.append(note);b.addWidget(note);stats.addWidget(f)
        box.addLayout(stats)
        f,b=card();head=QHBoxLayout();head.addWidget(label('處理進度','section'));head.addStretch();self.status=label('等待開始','pill');set_pill(self.status,'等待開始','todo');head.addWidget(self.status);b.addLayout(head)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.setTextVisible(False);b.addWidget(self.progress)
        self.progress.setFixedHeight(6)
        self.step=label('選好模組包後按「一鍵完整翻譯並套用」；原檔會先備份。');self.detail=label('','sub');b.addWidget(self.step);b.addWidget(self.detail)
        self.elapsed=label('','sub');b.addWidget(self.elapsed)
        self.written_note=label('','sub');self.written_note.setWordWrap(True);b.addWidget(self.written_note)
        self.report_link=button('查看翻譯報告',lambda:self.navigate(1));b.addWidget(self.report_link,alignment=Qt.AlignLeft);box.addWidget(f)
        self.activity_head=label('即時處理紀錄','section');box.addWidget(self.activity_head)
        self.activity=QPlainTextEdit();self.activity.setObjectName('log');self.activity.setReadOnly(True);self.activity.setMinimumHeight(130)
        self.activity.setMaximumBlockCount(300)
        box.addWidget(self.activity,1)
        box.addStretch()
        self.set_start_expanded(False)

    def set_start_expanded(self,expanded):
        """Idle start page stays short; progress details and the live log appear once work starts."""
        for widget in (self.progress,self.detail,self.elapsed,self.report_link,self.activity_head,self.activity):
            widget.setVisible(expanded)

    def recent_instances(self):
        """Folders used before. One saved folder is read back as text, not as a list of one."""
        value=self.settings.value('recent_instances',[]) or []
        if isinstance(value,str):value=[value]
        return [p for p in value if isinstance(p,str) and len(p)>3 and Path(p).is_absolute()]

    def refresh_instances(self):
        recent=self.recent_instances()
        current=self.path.text()
        self.instance_box.blockSignals(True);self.instance_box.clear()
        for launcher,name,path in jobs.discover_instances(recent):
            self.instance_box.addItem(f'{name}　·　{launcher}',str(path))
        self.instance_box.setCurrentIndex(-1);self.path.setText(current);self.instance_box.blockSignals(False)

    def pick_instance(self,index):
        path=self.instance_box.itemData(index)
        if path:self.path.setText(path)

    def remember_instance(self,path):
        recent=self.recent_instances()
        recent=[str(path)]+[p for p in recent if p.casefold()!=str(path).casefold()]
        self.settings.setValue('recent_instances',recent[:8]);self.refresh_instances()

    def make_report(self):
        box=self.page('翻譯報告','隨處理進度保存；即使停止或尚未套用，也能查看已產生的內容。')
        row=QHBoxLayout();self.history=QComboBox();self.history.setMinimumWidth(280);self.history.activated.connect(self.load_history)
        row.addWidget(self.history,1);row.addWidget(button('重新整理',self.refresh_history));self.folder_btn=button('開啟報告資料夾',self.open_report);row.addWidget(self.folder_btn);box.addLayout(row)
        f,b=card();head=QHBoxLayout();head.addWidget(label('本次結果','section'));head.addStretch();self.report_state=label('','pill');head.addWidget(self.report_state);b.addLayout(head)
        self.report_summary=label('尚未有翻譯紀錄。完成掃描後，這裡會顯示實際結果。');b.addWidget(self.report_summary)
        # Overview first, the same two numbers as the start page (how much the game shows in Chinese, how much
        # is still English), then what is worth checking and the backup. Sources stay folded.
        grid=QHBoxLayout();grid.setSpacing(12);self.overview={}
        for key,title in (('rate',jobs.HOME_CARDS[0]),('english',jobs.HOME_CARDS[1]),('check','建議確認'),('backup','備份')):
            cell=QFrame();cell.setObjectName('overview');line=QVBoxLayout(cell);line.setContentsMargins(12,10,12,10);line.setSpacing(2)
            line.addWidget(label(title,'sub'));value=label('—','number');line.addWidget(value);detail=label('','sub');line.addWidget(detail);line.addStretch()
            self.overview[key]=(value,detail);grid.addWidget(cell,1)
        b.addLayout(grid)
        self.report_counts=label('','muted');b.addWidget(self.report_counts)
        self.sources_toggle=button('顯示譯文來源明細',self.toggle_sources);self.sources_toggle.setObjectName('link');b.addWidget(self.sources_toggle,alignment=Qt.AlignLeft)
        self.report_sources=label('','sub');self.report_sources.hide();b.addWidget(self.report_sources)
        self.report_errors=label('','warn');self.report_errors.hide();b.addWidget(self.report_errors);box.addWidget(f)
        # Filters, table and buttons are one panel as tall as the window: many rows show at once and the
        # buttons stay in view with them, instead of a short table above four rows of buttons.
        self.list_panel=QWidget();outer=box;box=QVBoxLayout(self.list_panel);box.setContentsMargins(0,0,0,0);box.setSpacing(12)
        outer.addWidget(self.list_panel,1)
        # Two groups: translated (split by how) and untranslated (split by why); each chip shows its count.
        self.chips={};self.chip_names={}
        groups=((None,(('all','全部'),)),
                ('已翻譯',(('translated','全部已翻譯'),('review','建議確認'))+tuple((c,jobs.CATEGORY_NAMES[c]) for c in jobs.TRANSLATED_CATEGORIES)),
                ('未翻譯',tuple((c,jobs.CATEGORY_NAMES[c]) for c in jobs.UNTRANSLATED_CATEGORIES)))
        for title,items in groups:
            line=QHBoxLayout();line.setSpacing(6);chips=FlowLayout(spacing=6)
            if title:
                head=label(title,'sub');head.setFixedWidth(52);line.addWidget(head,0,Qt.AlignTop)
            for mode,text in items:
                chip=button(text,lambda checked=False,m=mode:self.pick_filter(m));chip.setObjectName('chip');chip.setCheckable(True)
                chip.setChecked(mode==self.filter_mode);self.chips[mode]=chip;self.chip_names[mode]=text;chips.addWidget(chip)
            line.addLayout(chips,1);box.addLayout(line)
        self.search=QLineEdit();self.search.setPlaceholderText('搜尋模組、文字或語系鍵')
        # Reports hold ~180k rows; wait for a typing pause instead of refiltering per keystroke.
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(300);self.search_timer.timeout.connect(self.reset_table)
        self.search.textChanged.connect(self.search_timer.start)
        box.addWidget(self.search)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['原文 / 語系鍵','建議譯文','來源','狀態'])
        self.table.setMinimumHeight(220);self.table.setShowGrid(False);self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide();self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft|Qt.AlignVCenter);self.table.horizontalHeader().setHighlightSections(False)
        self.table.setColumnWidth(2,110);self.table.setColumnWidth(3,150);self.table.cellDoubleClicked.connect(self.review_row);box.addWidget(self.table,1)
        self.table.setItemDelegateForColumn(0,OriginalDelegate(self))
        nav=QHBoxLayout();self.prev=button('上一頁',lambda:self.turn_page(-1));self.next=button('下一頁',lambda:self.turn_page(1));self.page_label=label('0 筆','sub');self.page_label.setWordWrap(False)
        self.page_size=QComboBox();self.page_size.setToolTip('每頁顯示筆數')
        for size in (50,100,200,500):self.page_size.addItem(f'每頁 {size} 筆',size)
        saved=int(self.settings.value('page_size',100) or 100)
        self.page_size.setCurrentIndex(max(0,self.page_size.findData(saved)))
        self.page_size.currentIndexChanged.connect(lambda *_:(self.settings.setValue('page_size',self.page_size.currentData()),self.reset_table()))
        nav.addWidget(self.prev);nav.addWidget(self.next);nav.addWidget(self.page_label);nav.addStretch();nav.addWidget(self.page_size);box.addLayout(nav)
        self.review_btn=button('查看並校對',self.review_current);self.apply_btn=button('備份並套用譯文',self.apply_job,True)
        self.ai_run_btn=button('AI 補翻缺漏',self.ai_supplement);self.ai_check_btn=button('AI 核對疑點',self.ai_review)
        # Confirming many rows at once: what is listed now (after filters and search), and a way back.
        self.confirm_all_btn=button('確認目前列出的全部',self.confirm_listed)
        self.confirm_all_btn.setToolTip('把目前列出的譯文記成「你確認的」。之後翻譯任何整合包，同一個模組的同一句會優先用它。')
        self.undo_confirm_btn=button('取消上次整批確認',self.undo_confirm_listed);self.undo_confirm_btn.setObjectName('link')
        # One bar: what to do with the listed rows on the left, writing to the game on the right. The left
        # side wraps onto a second line in a narrow window, so no button is ever cut off.
        actions=QHBoxLayout();actions.setSpacing(12);tools=FlowLayout(spacing=8)
        for b in (self.review_btn,self.confirm_all_btn,self.ai_run_btn,self.ai_check_btn,self.undo_confirm_btn):tools.addWidget(b)
        actions.addLayout(tools,1);actions.addWidget(self.apply_btn,0,Qt.AlignTop|Qt.AlignRight);box.addLayout(actions)
        self.ai_run_hint=label('','sub');self.ai_run_hint.setVisible(False);box.addWidget(self.ai_run_hint)
        box.addWidget(label('雙擊一列可以修正譯文；按「確認這筆」後會記住，下次翻譯自動使用。「建議確認」只列 AI 補譯、版本待確認的參考譯文、數值和原文不同的譯文與自動統一的譯名。','sub'))

    def make_backups(self):
        box=self.page('備份與還原','每次套用都保留原檔。還原前會檢查後續修改，避免蓋掉你的檔案。')
        self.backups=QListWidget();self.backups.setSpacing(2);box.addWidget(self.backups,1)
        self.backups_empty=label('還沒有備份。第一次套用翻譯時，會先把要修改的原檔備份在這裡。','sub');box.addWidget(self.backups_empty)
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
        self.update_progress=QProgressBar();self.update_progress.setValue(0);self.update_progress.setFixedHeight(6);self.update_progress.setTextVisible(False)
        self.update_progress.hide();box.addWidget(self.update_progress)  # shown only while downloading
        box.addWidget(label('更新只替換程式本身，翻譯資料、備份與設定都會保留。公開版本會由 GitHub 自動提供給所有使用者。','sub'))

    def navigate(self,index):
        self.pages.setCurrentIndex(index)
        for i,b in enumerate(self.navs):b.setChecked(i==index)
        if index==1:self.fit_list();self.fill_table()
        if index==2:self.refresh_backups()
        if index==5:self.refresh_terms()
        if index==6 and self.catalog is None:self.refresh_catalog()
        elif index==6:self.mark_catalog_seen()

    def make_shared(self):
        box=self.page('已翻譯整合包','已經翻好的整合包，按一個按鈕就裝好。整合包和翻譯者加裝的模組都從 CurseForge 官方下載，這裡只提供翻譯文字；安裝前會先備份。')
        head=QHBoxLayout();self.patch_status=label('','sub');head.addWidget(self.patch_status,1)
        self.patch_cancel=button('停止等待',self.cancel_install);self.patch_cancel.hide();head.addWidget(self.patch_cancel,0,Qt.AlignTop)
        self.catalog_refresh=button('重新整理',self.refresh_catalog);head.addWidget(self.catalog_refresh,0,Qt.AlignTop);box.addLayout(head)
        self.catalog_box=QVBoxLayout();self.catalog_box.setSpacing(12);box.addLayout(self.catalog_box)
        box.addStretch()
        self.catalog=None;self.pack_buttons=[]

    @staticmethod
    def catalog_key(pack):return f"{pack['projectID'] or pack['name']}:{pack['fileID']}:{pack['sha256'][:12]}"

    def seen_catalog(self):
        value=self.settings.value('seen_catalog',[]) or []
        return set([value] if isinstance(value,str) else value)

    def mark_catalog_seen(self):
        if not self.catalog:return
        self.settings.setValue('seen_catalog',sorted(self.seen_catalog()|{self.catalog_key(p) for p in self.catalog}))
        self.update_catalog_badge(include_new=False)

    def update_catalog_badge(self,include_new=True):
        updates=sum(p['status']=='update' for p in self.catalog or [])
        fresh=sum(bool(p.get('new')) and p['status']!='applied' for p in self.catalog or []) if include_new else 0
        parts=([f'{fresh} 個新上架'] if fresh else [])+([f'{updates} 個有更新'] if updates else [])
        # The sidebar is narrow: one number there, what it counts in the tooltip and on the page itself.
        self.navs[6].setText('已翻譯整合包'+(f'（{fresh+updates}）' if parts else ''))
        self.navs[6].setToolTip('、'.join(parts))

    def clear_catalog(self):
        self.pack_buttons=[]
        while self.catalog_box.count():
            item=self.catalog_box.takeAt(0)
            if item.widget():item.widget().deleteLater()

    def catalog_message(self,title,text):
        self.clear_catalog();f,b=card();b.setContentsMargins(24,28,24,28)
        t=label(title,'section');t.setAlignment(Qt.AlignCenter);b.addWidget(t)
        if text:
            sub=label(text,'sub');sub.setAlignment(Qt.AlignCenter);b.addWidget(sub)
        self.catalog_box.addWidget(f)

    def refresh_catalog(self):
        self.catalog=[];self.catalog_message('正在讀取已翻譯整合包…','')
        self.catalog_refresh.setEnabled(False)
        worker=Worker(lambda w:patches.fetch_catalog())
        worker.result.connect(self.catalog_loaded)
        worker.failed.connect(lambda text:self.catalog_message('暫時無法連線','請確認網路後按「重新整理」。'))
        worker.finished.connect(lambda w=worker:(self.catalog_refresh.setEnabled(True),self.background.remove(w) if w in self.background else None,w.deleteLater()))
        self.background.append(worker);worker.start()

    def catalog_loaded(self,packs):
        self.catalog=patches.match_catalog(packs,jobs.curseforge_instances(),patches.applied_patches(self.home))
        # New = published translations this user has not seen yet; shown until the page is opened.
        seen=self.seen_catalog()
        for pack in self.catalog:pack['new']=self.catalog_key(pack) not in seen
        fresh=[p for p in self.catalog if p['new'] and p['status']!='applied']
        mine=[p for p in fresh if p['status'] in ('exact','update')]
        if mine and self.pages.currentIndex()!=6:
            self.notify_finished('有新的整合包翻譯',f"你電腦上的「{mine[0]['name']}」有可以安裝的翻譯"+(f"，另有 {len(mine)-1} 個" if len(mine)>1 else '')+'。')
        self.update_catalog_badge()
        if self.pages.currentIndex()==6:self.mark_catalog_seen()
        if not self.catalog:
            self.catalog_message('目前還沒有已翻譯整合包','有新的整合包翻譯發布時，會出現在這裡。');return
        self.clear_catalog()
        states={'update':('翻譯有更新','progress'),'exact':('可安裝','progress'),'applied':('已是最新','done'),
                'other_version':('整合包版本不同','todo'),'not_installed':('未安裝整合包','todo')}
        notes={'update':'你安裝後這份翻譯又更新了。',
               'other_version':'你的整合包版本和這份翻譯不同，只會翻譯相同的模組；建議先在 CurseForge 更新整合包。',
               'not_installed':'你的電腦還沒有這個整合包。按下面的按鈕，CurseForge 會下載整合包，裝好後這裡自動裝上翻譯並把語言設成繁體中文。'}
        actions={'update':[('更新翻譯',True,self.apply_catalog_patch)],'exact':[('安裝翻譯',True,self.apply_catalog_patch)],
                 'applied':[('重新安裝',False,self.apply_catalog_patch)],
                 'other_version':[('仍要安裝',False,self.apply_catalog_patch),('用 CurseForge 更新整合包',False,self.install_with_curseforge)],
                 'not_installed':[('安裝整合包與翻譯',True,self.install_pack_and_translation)]}
        for pack in self.catalog:
            f,b=card();top=QHBoxLayout();name=label(pack['name'],'section');name.setWordWrap(True);top.addWidget(name,1)
            if pack.get('new'):
                tag=label('','pill');set_pill(tag,'新','progress');top.addWidget(tag,0,Qt.AlignVCenter)
            pill=label('','pill');set_pill(pill,*states[pack['status']]);top.addWidget(pill,0,Qt.AlignVCenter);b.addLayout(top)
            # The modpack's own version and the translation's revision are different things.
            modpack='　·　'.join(x for x in ('整合包版本 '+(pack['version'] or '未標示')+(f"（{pack['modpackDate']} 發布）" if pack['modpackDate'] else ''),
                                              pack['gameVersion'] and 'Minecraft '+pack['gameVersion']) if x)
            translation='　·　'.join(x for x in (f"翻譯第 {pack['revision']} 版",pack['updated'] and pack['updated'][:10]+' 更新',
                                                  pack['translator'] and '翻譯：'+pack['translator']) if x)
            b.addWidget(label(modpack,'muted'));b.addWidget(label(translation,'sub'))
            newer=(f"整合包已有新版本 {pack['newest_version']} 的翻譯，在 CurseForge 更新整合包後即可安裝。"
                   if pack['status'] in ('exact','applied','update') and not pack['latest'] else '')
            extra=pack.get('addedMods') or []
            added=(f"翻譯者另外加裝了 {len(extra)} 個模組：" +'、'.join(m['name'] for m in extra[:8])+('…' if len(extra)>8 else '')
                   +'。安裝時可以選擇要不要一起加入。') if extra else ''
            for text in (pack['notes'],added,notes.get(pack['status'],''),newer):
                if text:b.addWidget(label(text,'sub'))
            row=QHBoxLayout()
            for text,primary,fn in actions[pack['status']]:
                btn=button(text,lambda checked=False,p=pack,fn=fn:fn(p),primary);btn.setEnabled(not self.busy)
                self.pack_buttons.append(btn);row.addWidget(btn)
            row.addStretch();b.addLayout(row);self.catalog_box.addWidget(f)

    def choose_patch_target(self,projectID,fileID,title):
        """Pick the instance to patch: CurseForge instances of the same modpack first, then any known folder."""
        found=jobs.curseforge_instances()
        same=[x for x in found if projectID and x['projectID']==projectID]
        same.sort(key=lambda x:x['fileID']!=fileID)
        options=[(x['name']+('' if x['fileID']==fileID else '（整合包版本不同）'),x['path']) for x in same]
        if not options:QMessageBox.information(self,title,'找不到這個整合包。請先用 CurseForge 安裝同一個整合包。');return None
        if len(same)==1:return same[0]['path']
        from PySide6.QtWidgets import QInputDialog
        name,ok=QInputDialog.getItem(self,title,'要安裝到哪個整合包？',[n for n,_ in options],0,False)
        return dict(options).get(name) if ok else None

    def ask_install(self,title,text,pack):
        """Ask before installing. Returns None (do nothing), True (also add the translator's mods) or False."""
        mods=pack.get('addedMods') or []
        if not mods:return False if QMessageBox.question(self,title,text+'\n\n是否繼續？')==QMessageBox.Yes else None
        names='、'.join(m['name'] for m in mods[:12])+('…' if len(mods)>12 else '')
        box=QMessageBox(self);box.setIcon(QMessageBox.Question);box.setWindowTitle(title)
        box.setText(text+f"\n\n翻譯者另外加裝了 {len(mods)} 個模組（共 {sum(m['size'] for m in mods)/1024/1024:.1f} MB）：{names}\n"
                    '選擇加入時，本程式從 CurseForge 的官方檔案伺服器下載，確認和翻譯者用的是同一個檔案才放進模組資料夾；'
                    '之後可在「備份與還原」移除。不加入的話，這些模組的翻譯會略過。')
        both=box.addButton('加入模組並安裝翻譯',QMessageBox.AcceptRole);only=box.addButton('只安裝翻譯',QMessageBox.ActionRole)
        box.addButton('取消',QMessageBox.RejectRole);box.setDefaultButton(both)
        box.exec()
        return True if box.clickedButton() is both else False if box.clickedButton() is only else None

    def confirm_patch(self,target,pack,other_version):
        warn='\n\n整合包版本和翻譯時不同：只會翻譯檔案完全相同的模組，其餘略過（不會覆蓋）。' if other_version else ''
        language='，並把遊戲語言設為繁體中文' if self.set_language.isChecked() else ''
        return self.ask_install('安裝翻譯',f"將把「{pack['name']}」的翻譯安裝到{language}：\n{target}\n\n會先備份要修改的原檔，之後可在「備份與還原」復原。請先關閉這個整合包的遊戲。{warn}",pack)

    def apply_catalog_patch(self,pack):
        target=self.choose_patch_target(pack['projectID'],pack['fileID'],'安裝翻譯')
        if not target:return
        identity=patches.instance_identity(Path(target))
        add=self.confirm_patch(target,pack,identity['fileID']!=pack['fileID'])
        if add is None:return
        language=self.set_language.isChecked()
        def operation(w):
            path=patches.download_patch(pack,self.home,lambda v:w.progress.emit(v,'下載翻譯',pack['name']))
            return dict(patches.apply_patch(Path(target),path,self.home,w.progress.emit,set_language=language,add_mods=add,cancelled=lambda:w.cancelled),
                        notes=pack.get('notes',''))
        self.run_worker('patch_apply',operation,self.patch_applied)

    def install_pack_and_translation(self,pack):
        """One button for someone who has nothing yet: CurseForge installs the modpack, then the translation goes on."""
        if self.busy or not pack['projectID']:return
        add=self.ask_install('安裝整合包與翻譯',f"將安裝「{pack['name']}」整合包版本 {pack['version'] or ''}，並裝上繁體中文翻譯。\n\n"
                             '1. CurseForge 會跳出來，請在它的視窗確認安裝（整合包由 CurseForge 從官方下載）。\n'
                             '2. 這裡會等整合包裝好，不用回來按任何按鈕。\n'
                             '3. 裝好後自動裝上翻譯，並把遊戲語言設成繁體中文。\n\n'
                             '下載整合包可能需要幾分鐘到幾十分鐘，請不要關閉本程式。',pack)
        if add is None:return
        if not QDesktopServices.openUrl(QUrl(patches.curseforge_install_url(pack))):
            QMessageBox.warning(self,'找不到 CurseForge','這台電腦沒有安裝 CurseForge，或它沒有接手安裝。請先安裝 CurseForge 並開啟一次，再回來按這個按鈕。');return
        def operation(w):
            path=patches.download_patch(pack,self.home,lambda v:w.progress.emit(v,'下載翻譯',pack['name']))
            z,manifest=patches.read_patch(path);z.close()
            instance=patches.wait_for_modpack(pack,manifest,w.progress.emit,lambda:w.cancelled)
            result=patches.apply_patch(instance,path,self.home,w.progress.emit,set_language=True,add_mods=add,cancelled=lambda:w.cancelled)
            return dict(result,installed_modpack=True,notes=pack.get('notes',''))
        self.run_worker('patch_install',operation,self.patch_applied)

    def cancel_install(self):
        if self.worker and self.mode in ('patch_install','patch_apply'):
            self.worker.cancelled=True;self.patch_cancel.setEnabled(False);self.patch_status.setText('正在停止…')

    def patch_applied(self,result):
        self.refresh_backups();self.refresh_catalog();self.check_outdated()
        lines=[f"已翻譯 {len(result['applied']):,} 個檔案。" if result['applied'] else '沒有需要更新的檔案。']
        if result.get('installed_modpack'):lines.insert(0,'整合包已由 CurseForge 裝好：'+Path(result['instance']).name)
        mods=result.get('mods') or {}
        if mods.get('installed'):lines.append(f"已加入翻譯者加裝的 {len(mods['installed'])} 個模組："+'、'.join(mods['installed'][:8])+('…' if len(mods['installed'])>8 else ''))
        if mods.get('skipped'):
            lines.append(f"{len(mods['skipped'])} 個加裝的模組沒有加入：")
            lines+=['・'+s['name']+'：'+s['reason']+('（'+s['page']+'）' if s.get('page') else '') for s in mods['skipped'][:8]]
        if result.get('mods_offered'):lines.append(f"沒有加入翻譯者加裝的 {len(result['mods_offered'])} 個模組，它們的翻譯已略過。")
        if result['already']:lines.append(f"{len(result['already']):,} 個檔案先前已翻譯。")
        if result['skipped']:
            lines.append(f"略過 {len(result['skipped']):,} 個和翻譯時版本不同的檔案（未修改）：")
            lines+=['・'+s['file'] for s in result['skipped'][:8]]+(['…'] if len(result['skipped'])>8 else [])
        if result['backup']:lines.append('原檔已備份，可在「備份與還原」復原。')
        lines.append('遊戲語言已設為繁體中文（台灣）。' if result['language_set'] else '請在遊戲的「選項 → 語言」選擇繁體中文（台灣）。')
        if result.get('notes'):lines+=['','翻譯者的說明：',result['notes']]
        self.patch_status.setText('');self.notify_finished('翻譯已安裝',lines[0])
        QMessageBox.information(self,'翻譯已安裝','\n'.join(lines))

    def install_with_curseforge(self,pack):
        if not pack['projectID']:return
        QDesktopServices.openUrl(QUrl(patches.curseforge_install_url(pack)))
        QMessageBox.information(self,'用 CurseForge 安裝',f"已請 CurseForge 安裝「{pack['name']}」整合包版本 {pack['version'] or ''}。\n\n如果沒有反應，請在 CurseForge 搜尋這個整合包並安裝同一個版本。"
                                '\n裝好後回到這裡，按「重新整理」再「安裝翻譯」。')

    def make_terms(self):
        box=self.page('譯名與用詞','固定專有名詞的譯法，並統一不同模組間翻得不一樣的詞。')
        f,b=card();b.addWidget(label('自訂譯名','section'))
        b.addWidget(label('整句等於這個英文時直接使用你的譯名；AI 補翻時，句子裡出現的詞也會照用。排在模組自帶中文、參考庫與翻譯記憶之後。','sub'))
        row=QHBoxLayout();self.term_en=QLineEdit();self.term_en.setPlaceholderText('英文，例如 Benimaru')
        self.term_zh=QLineEdit();self.term_zh.setPlaceholderText('譯名，例如 紅丸')
        row.addWidget(self.term_en,1);row.addWidget(self.term_zh,1);row.addWidget(button('新增或更新',self.save_term,True));b.addLayout(row)
        self.term_table=QTableWidget(0,2);self.term_table.setHorizontalHeaderLabels(['英文','譯名'])
        self.term_table.verticalHeader().hide();self.term_table.setShowGrid(False);self.term_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.term_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.term_table.setMinimumHeight(180)
        for c in (0,1):self.term_table.horizontalHeader().setSectionResizeMode(c,QHeaderView.Stretch)
        self.term_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        self.term_table.cellClicked.connect(lambda r,_:(self.term_en.setText(self.term_table.item(r,0).text()),self.term_zh.setText(self.term_table.item(r,1).text())))
        b.addWidget(self.term_table);b.addWidget(button('刪除選取的譯名',self.remove_term),alignment=Qt.AlignLeft);box.addWidget(f)
        f,b=card();head=QHBoxLayout();title=label('用詞不一致（目前報告）','section');title.setWordWrap(False);head.addWidget(title);head.addStretch()
        self.conflict_count=label('','pill');head.addWidget(self.conflict_count);b.addLayout(head)
        b.addWidget(label('只列物品、方塊、生物、效果等「名稱」在不同模組翻得不一樣的情況；按鍵、選單等通用詞在不同情境本來就可能不同，不會列出。'
                          '已依翻譯來源的同一套順序預先選好建議譯法（你確認過的 → 台灣翻譯組人工繁中 → 模組繁中 → 官方譯名 → 簡中轉繁），可直接全部採用，或個別改選。','sub'))
        self.adopt_all_btn=button('全部採用建議',self.adopt_all_terms,True);b.addWidget(self.adopt_all_btn,alignment=Qt.AlignLeft)
        self.conflicts=QTableWidget(0,3);self.conflicts.setHorizontalHeaderLabels(['英文','目前的譯法（次數）','統一為'])
        self.conflicts.verticalHeader().hide();self.conflicts.setShowGrid(False);self.conflicts.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.conflicts.setMinimumHeight(260)
        for c in (0,1):self.conflicts.horizontalHeader().setSectionResizeMode(c,QHeaderView.Stretch)
        self.conflicts.setColumnWidth(2,260);self.conflicts.horizontalHeader().setDefaultAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        b.addWidget(self.conflicts,1);box.addWidget(f,1)

    def refresh_terms(self):
        entries=sorted(jobs.UserGlossary(self.home).entries.values(),key=lambda e:e['en'].casefold())
        self.term_table.setRowCount(len(entries))
        for i,e in enumerate(entries):
            self.term_table.setItem(i,0,QTableWidgetItem(e['en']));self.term_table.setItem(i,1,QTableWidgetItem(e['zh']))
        rows=jobs.conflicting_terms(self.session) if self.session and not self.session.get('is_preview') else []
        set_pill(self.conflict_count,f'{len(rows):,}{"+" if len(rows)>=500 else ""} 組','progress' if rows else 'done')
        self.term_conflicts=rows;self.adopt_all_btn.setEnabled(bool(rows))
        self.conflicts.setRowCount(len(rows))
        for i,item in enumerate(rows):
            self.conflicts.setItem(i,0,QTableWidgetItem(item['en']))
            self.conflicts.setItem(i,1,QTableWidgetItem('、'.join(f'{zh}（{n}）' for zh,n in item['variants'])))
            cell=QWidget();line=QHBoxLayout(cell);line.setContentsMargins(4,2,4,2)
            choice=QComboBox();choice.addItems([zh for zh,_ in item['variants']]);line.addWidget(choice,1)
            choice.setItemText(0,item['suggested']+'（建議）');choice.setItemData(0,item['suggested'])
            line.addWidget(button('統一',lambda checked=False,en=item['en'],tail=item['key_tail'],c=choice:self.unify_term(en,c.currentData() or c.currentText(),tail)))
            self.conflicts.setCellWidget(i,2,cell);self.conflicts.setRowHeight(i,48)

    def save_term(self):
        try:jobs.UserGlossary(self.home).set(self.term_en.text(),self.term_zh.text())
        except ValueError as exc:QMessageBox.information(self,'請填寫完整',str(exc));return
        self.term_en.clear();self.term_zh.clear();self.refresh_terms()

    def remove_term(self):
        row=self.term_table.currentRow()
        if row>=0:jobs.UserGlossary(self.home).remove(self.term_table.item(row,0).text());self.refresh_terms()

    def adopt_all_terms(self):
        rows=getattr(self,'term_conflicts',[])
        if self.busy or not self.session or not rows:return
        if QMessageBox.question(self,'全部採用建議',f'將 {len(rows):,} 個名稱統一為建議譯法，套用到目前報告並記成自訂譯名。\n'
                                '之後到報告頁按套用即可寫入遊戲。是否繼續？')!=QMessageBox.Yes:return
        terms=jobs.UserGlossary(self.home);count=0
        for item in rows:
            terms.entries[item['en'].casefold()]=dict(en=item['en'],zh=item['suggested'])
            count+=jobs.apply_term(self.session,item['en'],item['suggested'],item['key_tail'])
        terms.save();jobs.write_json(Path(self.session['report'])/'session.json',self.session)
        self.refresh_terms();self.fill_table()
        QMessageBox.information(self,'已統一',f'已統一 {len(rows):,} 個名稱，共 {count:,} 筆譯文。\n到報告頁按套用即可寫入遊戲。')

    def unify_term(self,en,zh,key_tail=None):
        if self.busy or not self.session:return
        jobs.UserGlossary(self.home).set(en,zh);count=jobs.apply_term(self.session,en,zh,key_tail)
        jobs.write_json(Path(self.session['report'])/'session.json',self.session)
        self.refresh_terms();self.fill_table()
        QMessageBox.information(self,'已統一',f'「{en}」已統一為「{zh}」，共 {count:,} 筆，並記成自訂譯名。\n到報告頁按套用即可寫入遊戲。')

    def apply_theme(self):
        tokens=THEMES['dark' if self.dark_theme else 'light'];palette=QPalette()
        # Native pieces the style sheet does not reach (popup containers, scroll corners) follow the theme too.
        for role,key in ((QPalette.Window,'surface'),(QPalette.Base,'surface'),(QPalette.AlternateBase,'soft'),
                         (QPalette.Button,'surface'),(QPalette.Text,'text'),(QPalette.WindowText,'text'),
                         (QPalette.ButtonText,'text'),(QPalette.Highlight,'primary_bg'),(QPalette.HighlightedText,'primary'),
                         (QPalette.PlaceholderText,'text40'),(QPalette.Mid,'gray'),(QPalette.Dark,'gray'),(QPalette.Shadow,'gray')):
            palette.setColor(role,QColor(tokens[key]))
        QApplication.instance().setPalette(palette)
        QApplication.instance().setStyleSheet(stylesheet('dark' if self.dark_theme else 'light'))
        if hasattr(self,'table'):self.fill_table()  # state colours come from the theme tokens
        self.theme_btn.setText('☀' if self.dark_theme else '☾')
        self.theme_btn.setToolTip('切換為亮色模式' if self.dark_theme else '切換為深色模式')
        self.settings.setValue('theme','dark' if self.dark_theme else 'light')
        QApplication.processEvents()

    def toggle_theme(self):
        if self.busy:return
        self.dark_theme=not self.dark_theme
        self.apply_theme()

    def make_ai(self):
        box=self.page('AI 帳號與模型','選用功能。不登入也能使用參考庫翻譯。')
        f,b=card();head=QHBoxLayout();head.addWidget(label('ChatGPT 帳號','section'));head.addStretch()
        self.ai_badge=label('','pill');set_pill(self.ai_badge,'未連接','todo');head.addWidget(self.ai_badge);b.addLayout(head)
        self.ai_status=label('尚未連接 ChatGPT。登入只在官方網頁完成。');b.addWidget(self.ai_status)
        self.ai_quota=label('額度尚未確認。不會使用 API key 或自動購買點數。','sub');b.addWidget(self.ai_quota)
        self.ai_progress=QProgressBar();self.ai_progress.setFixedHeight(6);self.ai_progress.setTextVisible(False);self.ai_progress.hide();b.addWidget(self.ai_progress)
        row=QHBoxLayout();self.ai_install_btn=button('安裝官方元件',self.install_ai_runtime,True)
        self.ai_login_btn=button('連接 ChatGPT',self.login_ai,True);self.ai_refresh_btn=button('重新整理額度',self.refresh_ai)
        self.ai_logout_btn=button('登出',self.logout_ai)
        for widget in (self.ai_install_btn,self.ai_login_btn,self.ai_refresh_btn,self.ai_logout_btn):row.addWidget(widget)
        row.addStretch();b.addLayout(row);box.addWidget(f)
        # The full cost/privacy notice matters before connecting; once connected it collapses to one line.
        self.ai_notice_card,b=card();b.addWidget(label('使用你原本的 Codex 額度','section'))
        b.addWidget(label(ai.NOTICE));b.addWidget(label(ai.PRIVACY,'sub'));box.addWidget(self.ai_notice_card)
        self.ai_notice_short=label('補翻消耗原本方案的 Codex 額度（與其他 Codex 工作共用）；只傳送缺漏原文（含已確認用途的設定說明與程式顯示文字）、文字位置與相對路徑。','sub')
        box.addWidget(self.ai_notice_short)
        f,b=card();b.addWidget(label('補翻模型','section'))
        self.ai_models=QComboBox();self.ai_models.setPlaceholderText('登入後載入帳號可用模型');b.addWidget(self.ai_models)
        self.ai_model_detail=label('模型會影響上下文與術語判斷，較強不代表保證正確；目前沒有本專案的模型品質排行榜。','sub');b.addWidget(self.ai_model_detail)
        # Differences shown are only what the official model list and the account's quota report.
        self.ai_compare=QTableWidget(0,4);self.ai_compare.setHorizontalHeaderLabels(['模型','官方說明','推理強度','額度'])
        self.ai_compare.verticalHeader().hide();self.ai_compare.setShowGrid(False);self.ai_compare.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.ai_compare.setSelectionMode(QAbstractItemView.NoSelection)
        # Names, effort and quota keep their own width; the description takes the rest and wraps in a
        # narrow window instead of shrinking to "…".
        for c in (0,2,3):self.ai_compare.horizontalHeader().setSectionResizeMode(c,QHeaderView.ResizeToContents)
        self.ai_compare.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.ai_compare.horizontalHeader().setDefaultAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        # Several columns resize in one layout pass; fit the rows once, after the widths have settled.
        self.compare_timer=QTimer(self);self.compare_timer.setSingleShot(True);self.compare_timer.setInterval(0)
        self.compare_timer.timeout.connect(self.fit_model_compare)
        self.ai_compare.horizontalHeader().sectionResized.connect(lambda *_:self.compare_timer.start())
        self.ai_compare.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.ai_compare.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.ai_compare.hide();b.addWidget(self.ai_compare)
        self.ai_models.currentIndexChanged.connect(self.select_ai_model)
        b.addWidget(label('只列官方回傳的可用模型，使用該模型建議的推理設定。若模型不可用會停止，不偷偷換模型。','sub'))
        # Filled from the account's own model list (see ai_connected); no model name is built in.
        self.ai_recommend=label('','sub');b.addWidget(self.ai_recommend)
        self.ai_model_card=f;box.addWidget(f)
        self.ai_stop_btn=button('停止登入／補翻',self.cancel_job);self.ai_stop_btn.setEnabled(False);box.addWidget(self.ai_stop_btn,alignment=Qt.AlignLeft)
        box.addStretch()

    def ai_connected_now(self):
        return bool(self.ai_info and self.ai_info.get('account'))

    def update_ai_controls(self):
        """Show only the next useful AI action; mirror the state on the start page."""
        if not hasattr(self,'ai_install_btn'):return
        installed=ai.find_runtime(self.home) is not None;connected=self.ai_connected_now()
        warning=(self.ai_info or {}).get('warning','') if connected else ''
        self.ai_install_btn.setVisible(not installed)
        self.ai_login_btn.setVisible(installed and not connected)
        self.ai_refresh_btn.setVisible(connected);self.ai_logout_btn.setVisible(connected)
        self.ai_notice_card.setVisible(not connected);self.ai_notice_short.setVisible(connected)
        self.ai_model_card.setVisible(connected)
        self.ai_quota.setObjectName('warn' if warning else 'sub');self.ai_quota.style().unpolish(self.ai_quota);self.ai_quota.style().polish(self.ai_quota)
        if connected and warning:set_pill(self.ai_badge,'額度不足','blocked')
        elif connected:set_pill(self.ai_badge,'已連接','done')
        else:set_pill(self.ai_badge,'未安裝元件' if not installed else '未連接','todo')
        model=self.ai_models.currentData() if connected else None
        usable=bool(connected and model and not warning)
        # The box is only the user's preference; it stays clickable and AI runs only when also usable.
        self.use_ai.setEnabled(not self.busy);self.ai_connect_link.setVisible(not connected)
        if not self.use_ai.isChecked():hint='不使用 AI：參考來源缺漏的文字會留在報告，之後可在報告頁補翻。'
        elif usable:
            hint=f'會先用模組包中文與參考庫翻譯，只把剩下的缺漏和有疑點的譯文交給「{model.get("displayName") or model["model"]}」；消耗你原本的 Codex 額度。'
        elif connected and warning:hint='AI 暫不可用（'+warning.rstrip('。')+'），這次只用參考來源翻譯；額度恢復後會自動補翻。'
        elif connected:hint='請到「AI 帳號與模型」選擇補翻模型；在那之前只用參考來源翻譯。'
        else:hint='尚未連接 AI，這次只用參考來源翻譯，缺漏留在報告。連接後會自動補翻。'
        self.ai_hint.setText(hint)
        self.side_ai.setText('AI 補翻：'+('額度不足' if warning else '已連接' if connected else '未連接'))

    def probe_ai(self):
        """Read-only account/quota check at startup; consumes no model quota."""
        if not ai.find_runtime(self.home) or self.busy:return
        self.start_background(lambda w:self.ai_operation('refresh',w),self.ai_connected)

    def start_background(self,operation,done):
        worker=Worker(operation);worker.result.connect(done)
        worker.failed.connect(lambda text:logging.info('Background check failed: %s',text))
        worker.finished.connect(lambda w=worker:(self.background.remove(w),w.deleteLater()) if w in self.background else None)
        self.background.append(worker);worker.start();return worker

    EFFORTS={'none':'不推理','minimal':'最低','low':'低','medium':'中','high':'高','xhigh':'很高','max':'最高','ultra':'極高'}

    def model_quota_text(self,model):
        q=((self.ai_info or {}).get('model_quota') or {}).get(model['model'].casefold())
        if not q:return '共用 Codex 額度'
        return f"專屬額度剩 {q['remaining']:g}%"+('（無法使用）' if q['remaining']<=10 else '')

    def is_recommended(self,model):
        return bool(model and self.ai_recommended and model['model']==self.ai_recommended['model'])

    def select_ai_model(self,*_):
        """The user picked a model; only such a choice is remembered over the suggestion."""
        model=self.ai_models.currentData()
        if model:self.settings.setValue('ai_model',model['model']);self.settings.setValue('ai_model_chosen','true')
        self.show_ai_model()

    def show_ai_model(self):
        model=self.ai_models.currentData()
        if model:
            effort=self.EFFORTS.get(model.get('defaultReasoningEffort'),model.get('defaultReasoningEffort') or '官方預設')
            self.ai_model_detail.setText(f"官方說明：{ai.describe_model(model) or model['model']}\n"
                                         f"翻譯時使用官方建議的推理強度「{effort}」；推理越深通常越慢、用量可能越多。{self.model_quota_text(model)}。\n"
                                         '官方沒有提供各模型的翻譯品質或確切耗量數字，譯文仍需校對。')
        self.update_ai_controls()

    def fill_model_compare(self,models):
        self.ai_compare.setRowCount(len(models));self.ai_compare.setVisible(bool(models))
        for i,m in enumerate(models):
            name=(m.get('displayName') or m['model'])+('（建議）' if self.is_recommended(m) else '')+('（官方預設）' if m.get('isDefault') else '')
            effort=self.EFFORTS.get(m.get('defaultReasoningEffort'),m.get('defaultReasoningEffort') or '—')
            described=ai.describe_model(m);official=str(m.get('description') or '').strip()
            for j,text in enumerate((name,described,effort,self.model_quota_text(m))):
                item=QTableWidgetItem(text);item.setToolTip(text);self.ai_compare.setItem(i,j,item)
                if j==1 and described!=official:item.setToolTip(described+'\n官方原文：'+official)
        self.fit_model_compare()

    def fit_model_compare(self):
        """Rows grow with wrapped descriptions and the table shows every model without its own scroll bar."""
        total=self.ai_compare.horizontalHeader().sizeHint().height()+4
        # Measured here because the view's own row hint ignores the style sheet's item padding.
        metrics=self.ai_compare.fontMetrics();width=max(60,self.ai_compare.columnWidth(1)-28)
        for i in range(self.ai_compare.rowCount()):
            item=self.ai_compare.item(i,1)
            text=metrics.boundingRect(0,0,width,10000,Qt.TextWordWrap,item.text() if item else '').height()
            height=max(38,text+18);self.ai_compare.setRowHeight(i,height);total+=height
        self.ai_compare.setFixedHeight(total)

    @staticmethod
    def window_text(q):
        span={300:'5 小時內',10080:'本週'}.get(q.get('minutes'),f"{q.get('minutes') or '?'} 分鐘內")
        return f"{span}剩 {q['remaining']:g}%"

    def ai_operation(self,action,w):
        with ai.CodexClient(self.home,lambda:w.cancelled) as client:
            if action=='login':return client.login(w.login_url.emit)
            if action=='logout':client.call('account/logout');return dict(account=None,models=[],quota=[],warning='已登出本程式的 ChatGPT 連接。')
            return client.catalog()

    def install_ai_runtime(self):
        if QMessageBox.question(self,'安裝官方 Codex 元件','將從 OpenAI 官方 GitHub 下載並校驗 Windows 元件（約數百 MB）。\n只安裝到本程式資料夾，不會登入或消耗模型額度。是否繼續？')!=QMessageBox.Yes:return
        self.run_worker('ai_install',lambda w:ai.install_runtime(self.home,w.progress.emit,lambda:w.cancelled),self.ai_installed)

    def ai_installed(self,_):
        self.ai_status.setText('官方元件已安裝，請按「連接 ChatGPT」。');self.update_ai_controls()

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
        self.ai_info=result;account=result.get('account');models=result.get('models',[])
        # Until v0.5.0 the automatic default was saved like a choice; only a pick made by the user counts.
        saved=self.settings.value('ai_model','') if str(self.settings.value('ai_model_chosen','false')).lower()=='true' else ''
        self.ai_recommended,reason=ai.recommended_model(models,result.get('model_quota'))
        self.ai_models.blockSignals(True);self.ai_models.clear();default_index=0
        for i,model in enumerate(models):
            self.ai_models.addItem((model.get('displayName') or model['model'])+('（建議）' if self.is_recommended(model) else ''),model)
            if self.is_recommended(model):default_index=i
        chosen=next((i for i in range(self.ai_models.count()) if self.ai_models.itemData(i)['model']==saved),default_index)
        if self.ai_models.count():self.ai_models.setCurrentIndex(chosen)
        self.ai_models.blockSignals(False);self.show_ai_model()
        name=self.ai_recommended and (self.ai_recommended.get('displayName') or self.ai_recommended['model'])
        self.ai_recommend.setText(f'建議使用「{name}」：{reason}沒有自己選過模型時，預設就用這個。\n補翻時會顯示依本次實際用量推算的剩餘額度需求。' if name else '')
        self.ai_status.setText(('已連接 '+str(account.get('email') or 'ChatGPT')+' · '+str(account.get('planType') or '未知方案')) if account else '尚未連接 ChatGPT。')
        self.ai_quota.setText(result.get('warning') or 'Codex 額度：'+'　'.join(self.window_text(q) for q in result.get('quota',[])))
        self.fill_model_compare(result.get('models',[]))
        self.update_ai_controls()

    def ai_supplement(self):
        if not self.session:
            QMessageBox.information(self,'先掃描模組包','請先開始翻譯並完成參考來源比對。');return
        model=self.ai_ready()
        if not model:return
        count=len(ai.pending_rows(self.session))
        if not count:QMessageBox.information(self,'沒有可補翻缺漏','已完成的 AI 候選不會重送；待查程式與設定不會交給 AI 直接修改。');return
        if QMessageBox.question(self,'使用原方案額度補翻？',f'模型：{model["model"]}\n待補翻：{count} 筆（分批處理）\n\n'+ai.NOTICE+'\n\n'+ai.PRIVACY)!=QMessageBox.Yes:return
        self.run_worker('ai_translate',lambda w:ai.supplement(self.session,self.home,model['model'],w.progress.emit,lambda:w.cancelled,checkpoint=w.publish),self.ai_done)

    def ai_done(self,result):
        self.job_done(result);self.ai_status.setText(result['ai_message']);self.navigate(1)
        self.notify_finished('AI 補翻已結束',result['ai_message'])
        if result.get('ai_status')=='paused':QMessageBox.information(self,'AI 補翻已暫停',result['ai_message'])

    def ai_ready(self):
        """The chosen model when AI can be used now; otherwise says why and returns None."""
        model=self.ai_models.currentData()
        if not self.ai_info or not self.ai_info.get('account') or not model:
            self.navigate(4);QMessageBox.information(self,'先連接帳號','請登入 ChatGPT、確認額度並選擇補翻模型。');return None
        if self.ai_info.get('warning'):
            QMessageBox.warning(self,'AI 暫時不能用',self.ai_info['warning']+'\n可按重新整理再次確認。');return None
        return model

    def ai_review(self):
        if not self.session or self.session.get('is_preview'):return
        count=len(ai.doubt_rows(self.session))
        if not count:QMessageBox.information(self,'沒有需要核對的疑點','數值不同或版本不同的譯文都已經核對過，或這一批沒有這類疑點。');return
        model=self.ai_ready()
        if not model:return
        if QMessageBox.question(self,'使用原方案額度核對？',f'模型：{model["model"]}\n要核對：{count:,} 筆（數值和原文不同、版本不同的參考譯文）\n\n'
                                'AI 會對照英文原文逐筆判斷：正確的保留原來源並記下已核對；有錯的改寫成 AI 補譯，'
                                '改寫的部分要再按「備份並套用譯文」才會寫入遊戲。\n\n'+ai.NOTICE+'\n\n'+ai.PRIVACY)!=QMessageBox.Yes:return
        self.run_worker('ai_translate',lambda w:ai.review(self.session,self.home,model['model'],w.progress.emit,lambda:w.cancelled,checkpoint=w.publish),self.ai_review_done)

    def ai_review_done(self,result):
        self.job_done(result);self.ai_status.setText(result['ai_review_message']);self.navigate(1)
        self.notify_finished('AI 核對已結束',result['ai_review_message'])
        QMessageBox.information(self,'AI 核對結果',result['ai_review_message'])

    def confirmable(self,row):
        return bool(row.get('supported') and row.get('kind')=='language' and row.get('origin') not in ('untranslated','keep_original','not_display','pending')
                    and not str(row.get('review_method') or '').startswith('user_confirmed') and row_module(row)
                    and jobs.usable(jobs.original_of(row),row.get('proposed')))

    def confirm_listed(self):
        if self.busy or not self.session or self.session.get('is_preview'):return
        rows=[r for r in getattr(self,'listed_rows',[]) if self.confirmable(r)]
        if not rows:QMessageBox.information(self,'沒有可確認的譯文','目前列出的內容沒有尚未確認的譯文。');return
        mods=len({row_module(r) for r in rows})
        wide=('\n\n這次範圍很大。整批確認後，這些譯文的順位會高於社群參考庫；'
              '建議先用上方的篩選或搜尋縮小到一個模組，看過再確認。' if len(rows)>500 or mods>3 else '')
        if QMessageBox.question(self,'確認目前列出的全部',f'把目前列出的 {len(rows):,} 筆譯文（{mods:,} 個模組）記成「你確認的」？\n\n'
                                '之後翻譯任何整合包，遇到同一個模組的同一句會優先使用，也不再列入「建議確認」。'
                                '確認錯了可以按「取消上次整批確認」。'+wide)!=QMessageBox.Yes:return
        batch=Path(self.session['report']).name+'-'+time.strftime('%H%M%S')
        jobs.TranslationMemory(self.home).remember_many(
            [(row_memory_scope(r),r['key'],jobs.original_of(r),r['proposed'],r['source']) for r in rows],batch)
        for r in rows:r.update(reviewed=True,review_method='user_confirmed_batch',confirmed_batch=batch)
        self.settings.setValue('last_confirm_batch',batch)
        jobs.write_json(Path(self.session['report'])/'session.json',self.session);self.fill_table()
        QMessageBox.information(self,'已確認',f'已確認 {len(rows):,} 筆。還沒寫入遊戲的部分，按「備份並套用譯文」即可。')

    def undo_confirm_listed(self):
        batch=str(self.settings.value('last_confirm_batch','') or '')
        if self.busy or not batch:return
        if QMessageBox.question(self,'取消上次整批確認','上次整批確認的譯文會變回「未確認」，之後翻譯不再優先使用它們。已經寫入遊戲的文字不會改變。是否繼續？')!=QMessageBox.Yes:return
        count=jobs.TranslationMemory(self.home).forget_batch(batch)
        for r in (self.session or {}).get('rows',[]):
            if r.get('confirmed_batch')==batch:r.update(review_method=None,confirmed_batch=None,reviewed=bool(r.get('installed')))
        self.settings.setValue('last_confirm_batch','')
        if self.session and not self.session.get('is_preview'):jobs.write_json(Path(self.session['report'])/'session.json',self.session)
        self.fill_table();QMessageBox.information(self,'已取消',f'已取消 {count:,} 筆的確認。')

    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'選擇模組包根資料夾',self.path.text() or str(Path.home()))
        if path:self.path.setText(str(Path(path)));self.settings.setValue('instance',str(Path(path)))

    def instance_path(self):
        value=str(self.path.text() or '').strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
            value=value[1:-1].strip()
        return Path(value)

    def run_worker(self,mode,operation,done):
        if self.busy:return
        if (mode.startswith('ai_') or mode=='full_translate') and any(w.isRunning() for w in self.background):
            # The startup account check owns the Codex process; never run two against one login store.
            QMessageBox.information(self,'正在確認帳號','程式正在背景確認 AI 帳號狀態，請幾秒後再試。');return
        self.busy=True;self.mode=mode
        if mode in ('plan','full_translate','apply','ai_translate'):self.live_session=True;self.set_start_expanded(True)
        self.started_at=self.last_activity=time.monotonic()
        for b in (self.ai_check_btn,self.confirm_all_btn,self.undo_confirm_btn,self.instance_box,self.full_start,self.choose,self.apply_btn,self.restore_btn,self.check_btn,self.install_btn,self.review_btn,self.ai_install_btn,self.ai_login_btn,self.ai_refresh_btn,self.ai_logout_btn,self.ai_run_btn,self.ai_models,self.use_ai,*self.pack_buttons):b.setEnabled(False)
        if mode=='ai_install':self.ai_progress.setValue(0);self.ai_progress.show()
        self.patch_cancel.setVisible(mode in ('patch_install','patch_apply'));self.patch_cancel.setEnabled(True)
        self.patch_cancel.setText('停止等待' if mode=='patch_install' else '停止')
        self.history.setEnabled(False);self.cancel.setEnabled(mode in ('plan','full_translate','ai_translate','ai_login','ai_install'));self.ai_stop_btn.setEnabled(mode in ('ai_translate','ai_login','ai_install'))
        self.worker=Worker(operation)
        self.worker.progress.connect(self.on_progress)
        self.worker.checkpoint.connect(self.receive_checkpoint)
        self.worker.login_url.connect(self.open_ai_login)
        self.worker.result.connect(done);self.worker.failed.connect(self.on_error);self.worker.finished.connect(self.finish_worker);self.worker.start()

    def finish_worker(self):
        self.busy=False
        if self.quit_after_worker:
            # The update helper waits for this process to exit; exit() skips the busy close guard.
            QApplication.exit(0);return
        self.progress.setRange(0,100)
        self.taskbar.update(self,state=TaskbarProgress.NOPROGRESS);self.setWindowTitle('模組包中文化 · MC Translator')
        for b in (self.confirm_all_btn,self.instance_box,self.full_start,self.choose,self.apply_btn,self.restore_btn,self.check_btn,self.review_btn,self.ai_install_btn,self.ai_login_btn,self.ai_refresh_btn,self.ai_logout_btn,self.ai_run_btn,self.ai_models,*self.pack_buttons):b.setEnabled(True)
        self.history.setEnabled(True);self.cancel.setEnabled(False);self.ai_stop_btn.setEnabled(False)
        self.install_btn.setEnabled(bool(self.update_info and self.update_info.get('status')=='available'))
        self.ai_progress.hide();self.patch_cancel.hide();self.update_ai_controls();self.update_ai_button()

    def on_progress(self,value,title,detail):
        self.last_activity=time.monotonic()
        if self.mode in ('ai_install','ai_login','ai_refresh','ai_logout','check_update','download_update'):
            # Account and update chores stay on their own page instead of hijacking the translation progress card.
            if self.mode=='ai_install':self.ai_progress.setValue(value)
            if self.mode.startswith('ai_'):self.ai_status.setText(title+('：'+detail if detail else ''))
            return
        if self.mode.startswith('patch_'):
            self.patch_status.setText(f'{title}：{detail}（{value}%）' if detail else title);return
        # One-click reports progress for the whole job itself (see jobs.full_translation).
        if title in ('更新參考庫','AI 補翻中'):self.progress.setRange(0,0)
        else:self.progress.setRange(0,100)
        self.progress.setValue(value);self.step.setText(title);self.detail.setText(detail);set_pill(self.status,'處理中','progress')
        indeterminate=self.progress.maximum()==0
        self.taskbar.update(self,None if indeterminate else value,TaskbarProgress.INDETERMINATE if indeterminate else TaskbarProgress.NORMAL)
        self.setWindowTitle(('' if indeterminate else f'{value}% · ')+'模組包中文化 · MC Translator')
        self.cancel.setEnabled(self.mode in ('plan','full_translate','ai_translate','ai_login','ai_install') and title not in ('驗證並準備套用','備份與套用','重新掃描實際遊戲資料','已套用已校對的文字'))
        self.append_activity(title+' · '+detail)
        if self.mode.startswith('ai_'):self.ai_status.setText(title+'：'+detail)

    def notify_finished(self,title,message):
        """Tell the user a long job ended even if they switched to another window."""
        QApplication.alert(self)
        if self.isActiveWindow() or not QSystemTrayIcon.isSystemTrayAvailable():return
        if not self.tray:
            self.tray=QSystemTrayIcon(self.windowIcon(),self);self.tray.setToolTip('MC Translator')
            self.tray.messageClicked.connect(lambda:(self.showNormal(),self.raise_(),self.activateWindow()))
        self.tray.show();self.tray.showMessage(title,message,QSystemTrayIcon.Information,8000)

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
            self.append_activity(f"{jobs.SOURCE_NAMES.get(row['origin'],row['origin'])} · {(jobs.original_of(row) or row['key'])[:65]} → {row['proposed'][:80]}（尚未套用）")
        if len(fresh)>5:self.append_activity(f'另有 {len(fresh)-5:,} 筆譯文，完整內容請看翻譯報告。')
        self.update_stats();self.refresh_history();self.fill_table()

    def check_outdated(self):
        while self.outdated_box.count():
            item=self.outdated_box.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    w=item.layout().takeAt(0).widget()
                    if w:w.deleteLater()
        try:found=jobs.outdated_translations(self.home)
        except Exception:logging.exception('Cannot check translated modpacks');found=[]
        try:cut=jobs.interrupted_batches(self.home)
        except Exception:logging.exception('Cannot check interrupted batches');cut=[]
        self.outdated_card.setVisible(bool(found or cut))
        if cut:
            self.outdated_box.addWidget(label('上一次套用或還原沒有做完','section'))
            names='、'.join(sorted({Path(r['instance']).name for _,r in cut}))
            self.outdated_box.addWidget(label(f'「{names}」可能只寫入了一部分（例如中途當機或斷電）。原檔都有備份，'
                                              '請到「備份與還原」選擇標示「中斷」的那一批按還原，之後再重新套用。','sub'))
            self.outdated_box.addWidget(button('前往備份與還原',lambda:self.navigate(2),True),alignment=Qt.AlignLeft)
        if not found:return
        head=label('整合包已更新，翻譯需要重新套用','section');self.outdated_box.addWidget(head)
        for x in found:
            text=label(f"「{x['name']}」已從版本 {x['old_version'] or '（舊版）'} 更新到 {x['new_version'] or '新版'}。"
                       'CurseForge 更新時會換掉模組檔，之前的翻譯可能已被覆蓋。','sub');self.outdated_box.addWidget(text)
            row=QHBoxLayout()
            row.addWidget(button('重新翻譯並套用',lambda checked=False,p=x['path']:self.retranslate(p),True))
            row.addWidget(button('查看已翻譯整合包',lambda:self.navigate(6)))
            row.addWidget(button('略過',lambda checked=False,x=x:(jobs.dismiss_outdated(self.home,x['key'],x['fileID']),self.check_outdated())))
            row.addStretch();self.outdated_box.addLayout(row)

    def retranslate(self,path):
        if self.busy:return
        self.path.setText(path);self.full_translation_job()

    def restore_latest_report(self):
        candidates=list((self.home/'output').glob('*/報告/*/session.json'))
        if not candidates:return
        path=max(candidates,key=lambda p:p.stat().st_mtime)
        try:
            self.use_session(json.loads(path.read_text(encoding='utf-8')))
            self.update_stats();self.refresh_history();self.fill_table()
        except (ValueError,OSError,KeyError):logging.exception('Cannot restore last report')

    def on_error(self,text):
        if self.mode in ('check_update','download_update'):self.update_status.setText('更新未完成：'+text)
        elif self.mode.startswith('ai_'):self.ai_status.setText(text)
        elif self.mode.startswith('patch_'):self.patch_status.setText(text)
        else:
            set_pill(self.status,'需要處理','blocked');self.detail.setText(text)
            if self.session and self.mode=='apply':
                self.session.update(status='apply_failed',apply_error=text)
                jobs.write_json(Path(self.session['report'])/'session.json',self.session)
                self.update_stats();self.fill_table()
        QMessageBox.warning(self,'需要處理',text)

    def checked_instance(self):
        """The modpack folder to work on, corrected when the user picked a folder inside it; None when unusable."""
        if not self.path.text().strip():self.choose_folder()
        if not self.path.text().strip():return None,''
        try:instance,note=jobs.resolve_instance(self.path.text())
        except ValueError as exc:
            QMessageBox.warning(self,'請重新選擇模組包',str(exc));return None,''
        if str(instance)!=self.path.text().strip():self.path.setText(str(instance))
        return instance,note

    def start_job(self):
        instance,_=self.checked_instance()
        if not instance:return
        self.progress.setValue(0);set_pill(self.status,'處理中','progress')
        self.run_worker('plan',lambda w:jobs.plan(instance,self.home,w.progress.emit,lambda:w.cancelled,checkpoint=w.publish),self.job_done)

    def full_translation_job(self):
        instance,note=self.checked_instance()
        if not instance:return
        # AI runs only when the user ticked the option and the account can currently be used.
        usable=self.ai_connected_now() and not (self.ai_info or {}).get('warning')
        model=self.ai_models.currentData() if usable and self.use_ai.isChecked() else None
        if model:
            ai_line=('參考來源能翻的會先寫入遊戲（通常幾分鐘）。之後缺漏的文字交給模型「'+model['model']+'」補翻，'
                     '數值或版本有疑點的譯文也會請它對照英文核對；AI 比較慢，做完再寫入第二次。'
                     '消耗你原本 ChatGPT 的 Codex 額度。\n'+ai.PRIVACY)
        elif self.use_ai.isChecked() and self.ai_connected_now():
            ai_line='AI 目前無法使用（'+((self.ai_info or {}).get('warning') or '尚未選擇模型')+'），這次只使用參考來源；缺漏會留在報告。'
        else:
            ai_line='這次不使用 AI；參考來源缺漏的文字會留在報告，之後可在報告頁補翻。'
        prompt=(f'要翻譯並寫入的模組包：「{instance.name}」\n{instance}\n'+(note+'\n' if note else '')
                +'\n這會掃描整個模組包、翻譯可辨識的玩家文字、建立備份並直接套用。\n'
                +ai_line+'\n\n已確認用途的程式文字會備份並寫入原模組，切換語言也會維持繁中，可從備份還原。'
                +'遊戲必須先關閉；圖片文字、用途不明的程式文字與特殊格式會列入報告。\n是否繼續？')
        if QMessageBox.question(self,'一鍵完整翻譯',prompt)!=QMessageBox.Yes:return
        self.progress.setValue(0);set_pill(self.status,'處理中','progress')
        if jobs.is_instance(instance):self.remember_instance(instance)
        self.run_worker('full_translate',lambda w:self.full_translation_operation(instance,model,w),self.full_translation_done)

    def full_translation_operation(self,instance,model,w):
        return jobs.full_translation(instance,self.home,model['model'] if model else None,w.progress.emit,lambda:w.cancelled,w.publish,
                                     options=dict(set_language=self.set_language.isChecked()))

    def full_translation_done(self,result):
        self.job_done(result);self.navigate(1);self.check_outdated()
        if result.get('ai_review_message'):self.ai_status.setText(result['ai_review_message'])
        # The same two numbers as the start page, read back from the game's files, plus what this run changed.
        view=jobs.home_cards(result);(rate,rate_note),(english,english_note)=view['cards']
        summary=f'中文化完成率 {rate}（{rate_note}）\n還缺中文 {english} 句：{english_note}'+('\n'+view['written'] if view['written'] else '')
        if result['status'] in ('installed','needs_review'):self.notify_finished('翻譯完成',f'中文化完成率 {rate}，還缺中文 {english} 句。')
        else:self.notify_finished('翻譯已停止，需要處理',result.get('apply_error') or '請查看翻譯報告。')
        if result['status']=='installed':
            notes='\n'.join(self.applied_notes(result));waiting=self.unapplied_count()
            if waiting:notes=f'另有 {waiting:,} 筆已翻好但還沒寫入，可在報告頁按「備份並套用譯文」。'+('\n'+notes if notes else '')
            QMessageBox.information(self,'本次處理完成',summary+('\n\n'+notes if notes else '')+'\n\n重新啟動遊戲後生效。')
        elif result['status']=='awaiting_game':
            QMessageBox.information(self,'譯文已保存，等待套用',result['apply_error'])
        elif self.nothing_new(result):
            QMessageBox.information(self,'沒有需要寫入的內容',summary)

    def nothing_new(self,session):
        """A modpack translated before and unchanged since: everything is still applied, nothing waits."""
        return bool(session.get('status')=='needs_review' and session.get('recovered_count') and not session.get('is_preview')
                    and not jobs.applicable_count(session))

    def cancel_job(self):
        if self.worker and self.mode in ('plan','full_translate','ai_translate','ai_login','ai_install'):
            self.worker.cancelled=True;self.cancel.setEnabled(False);self.ai_stop_btn.setEnabled(False);self.detail.setText('正在停止，已送出的 AI 請求可能已消耗額度…')

    def job_done(self,result):
        self.session=result
        names={'installed':('已套用','done'),'blocked':('需要處理','blocked'),'awaiting_game':('等待關閉遊戲','progress'),'apply_failed':('套用未完成','blocked'),'cancelled':('已停止','todo')}
        set_pill(self.status,*names.get(result['status'],('可查看報告','todo')))
        self.progress.setRange(0,100)
        if result['status']=='installed':self.progress.setValue(100)
        self.update_stats()
        self.refresh_history();self.refresh_backups();self.fill_table()
        if result['status']=='blocked':self.detail.setText(str(result['errors'][-1][-1]))
        elif result.get('apply_error'):self.detail.setText(result['apply_error'])
        self.step.setText(self.status.text());self.append_activity(self.status.text())

    def show_cards(self,view):
        for (number,note),n,sub in zip(view['cards'],self.stats,self.stat_notes):n.setText(number);sub.setText(note)
        self.written_note.setText(view.get('written',''))

    def update_stats(self):
        rows=self.session['rows']
        # The start page only reports work done in this session; saved reports live on the report page.
        if self.live_session:self.show_cards(self.session.get('preview_cards') or jobs.home_cards(self.session))
        pending=self.unapplied_count()
        if self.session['status'] in ('awaiting_game','apply_failed','ready_to_apply') or (pending and self.session['status'] in ('needs_review','installed')):
            verb='重試套用' if self.session['status'] in ('awaiting_game','apply_failed') else '備份並套用譯文'
            self.apply_btn.setText(f'{verb}（{pending:,} 筆，不重新翻譯）' if pending else '重試套用（不重新翻譯）')
        else:self.apply_btn.setText('備份並套用譯文')
        # One-click already applied everything (including rows worth checking); the button only shows
        # when translations are still waiting, e.g. the game was running.
        self.apply_btn.setVisible(bool(pending) or self.session['status'] in ('awaiting_game','apply_failed'))

    def unapplied_count(self):
        if not self.session or self.session.get('is_preview') or self.session.get('status')=='restored':return 0
        return jobs.applicable_count(self.session)

    def refresh_history(self):
        current=self.session['report'] if self.session else None
        self.history.clear();self.history.addItem('選擇本機翻譯紀錄',None)
        for p in sorted((self.home/'output').glob('*/報告/*/session.json'),key=lambda p:p.parent.name,reverse=True)[:100]:
            self.history.addItem(history_label(p),str(p))
            if str(p.parent)==current:self.history.setCurrentIndex(self.history.count()-1)

    def load_history(self,index):
        path=self.history.itemData(index)
        if path:
            try:self.use_session(json.loads(Path(path).read_text(encoding='utf-8')));self.page_index=0;self.update_stats();self.fill_table()
            except Exception as exc:QMessageBox.warning(self,'無法讀取紀錄',str(exc))

    def set_filter(self,mode):
        self.filter_mode=mode
        for name,chip in self.chips.items():chip.setChecked(name==mode)
        self.reset_table()

    def pick_filter(self,mode):
        """A filter the user clicked: also bring the whole list into view."""
        self.set_filter(mode);self.fit_list()
        QTimer.singleShot(0,self.show_list)  # after the page has taken its new height

    def show_list(self):
        area=self.pages.widget(1);area.widget().layout().activate()
        area.verticalScrollBar().setValue(max(0,self.list_panel.y()-8))

    def fit_list(self):
        """Filters, table and buttons together are as tall as the window shows."""
        if hasattr(self,'list_panel'):self.list_panel.setMinimumHeight(max(420,self.pages.widget(1).viewport().height()-16))

    def resizeEvent(self,event):
        super().resizeEvent(event);self.fit_list()

    def reset_table(self,*_):self.page_index=0;self.show_rows()
    def turn_page(self,direction):self.page_index=max(0,self.page_index+direction);self.show_rows()

    def use_session(self,session):
        """Adopt a saved report; older reports get the current no-translation rules."""
        self.session=session;jobs.reclassify_keep_original(session);jobs.readopt_rejected(session)
        summary=Path(session.get('report',''))/'summary.json'
        if session.get('report') and not summary.exists() and summary.parent.is_dir():
            # Reports from before v0.4.3 lack the sidecar the history list reads.
            try:jobs.write_json(summary,jobs.session_summary(session));self.refresh_history()
            except OSError:logging.info('Cannot write report summary',exc_info=True)

    def update_ai_button(self):
        count=len(ai.pending_rows(self.session)) if self.session and not self.session.get('is_preview') else 0
        self.ai_run_btn.setText(f'AI 補翻缺漏（{count:,} 筆）' if count else 'AI 補翻缺漏')
        self.ai_run_btn.setEnabled(bool(count) and not self.busy)
        # A greyed-out button says why, so it never looks broken.
        asked=len(ai.asked_rows(self.session)) if self.session and not self.session.get('is_preview') and not count else 0
        self.ai_run_btn.setToolTip(f'有 {count:,} 筆沒有中文來源的文字可以交給 AI 補翻。' if count else
            f'沒有可以再送的缺漏：{asked:,} 筆 AI 已經回答過，譯文沒通過檢查或 AI 判斷保留原文，不再重送以免重複消耗額度。'
            '原因寫在每一筆的說明裡；雙擊那一筆可以拿 AI 的譯文來修改後確認。' if asked else '這批沒有需要 AI 補翻的缺漏。')
        if hasattr(self,'ai_run_hint'):
            self.ai_run_hint.setVisible(bool(asked))
            self.ai_run_hint.setText(f'「AI 補翻缺漏」不能按：{asked:,} 筆 AI 已經回答過（沒通過檢查或 AI 判斷保留原文），不再重送。'
                                     '雙擊那一筆可以看到 AI 的譯文，改好後按「確認這筆」。')
        doubts=len(ai.doubt_rows(self.session)) if self.session and not self.session.get('is_preview') else 0
        self.ai_check_btn.setText(f'AI 核對疑點（{doubts:,} 筆）' if doubts else 'AI 核對疑點')
        self.ai_check_btn.setEnabled(bool(doubts) and not self.busy)
        listed=getattr(self,'listed_confirmable',0) if self.session and not self.session.get('is_preview') else 0
        self.confirm_all_btn.setText(f'確認目前列出的全部（{listed:,} 筆）' if listed else '確認目前列出的全部')
        self.confirm_all_btn.setEnabled(bool(listed) and not self.busy)
        self.undo_confirm_btn.setVisible(bool(self.settings.value('last_confirm_batch','')));self.undo_confirm_btn.setEnabled(not self.busy)

    def fill_table(self):
        """The whole report page, after the report itself changed."""
        if not self.session:
            self.facts=None;self.table.setRowCount(0);return
        rows=self.session['rows'];preview=self.session.get('is_preview')
        # Each row is judged once per change of the report; filtering, searching and paging through
        # some 100,000 rows then only read these lists.
        self.facts=dict(rows=rows,count=len(rows),category=[jobs.row_category(r) for r in rows],check=[jobs.needs_check(r) for r in rows],
                        confirmable=[not preview and self.confirmable(r) for r in rows])
        counts=collections.Counter(self.facts['category']);counts['all']=len(rows)
        counts['translated']=sum(counts[c] for c in jobs.TRANSLATED_CATEGORIES)
        counts['review']=sum(self.facts['check'])
        for chip_mode,chip in self.chips.items():
            chip.setText(f"{self.chip_names[chip_mode]} {counts[chip_mode]:,}")
            chip.setVisible(chip_mode in ('all','translated','review','missing') or counts[chip_mode]>0)
        self.show_rows()
        self.fill_summary()

    def show_rows(self):
        """The rows of the current filter, search and page."""
        facts=getattr(self,'facts',None)
        if not self.session:return self.fill_table()
        rows=self.session['rows']
        if not facts or facts['rows'] is not rows or facts['count']!=len(rows):return self.fill_table()
        mode=self.filter_mode;query=self.search.text().strip().casefold()
        size=int(self.page_size.currentData() or 100)
        def match(i,r):
            if mode=='review' and not facts['check'][i]:return False
            if mode=='translated' and facts['category'][i] not in jobs.TRANSLATED_CATEGORIES:return False
            if mode not in ('all','review','translated') and facts['category'][i]!=mode:return False
            return not query or query in (r['source']+' '+r['key']+' '+str(jobs.original_of(r))+' '+str(r.get('zh_cn') or '')+' '+r['proposed']+' '+str(r.get('issue') or '')).casefold()
        listed=[i for i,r in enumerate(rows) if match(i,r)];pages=max(1,(len(listed)+size-1)//size)
        filtered=[rows[i] for i in listed]
        self.listed_rows=filtered;self.listed_confirmable=sum(facts['confirmable'][i] for i in listed)
        self.page_index=min(self.page_index,pages-1)
        self.visible_rows=filtered[self.page_index*size:(self.page_index+1)*size]
        tokens=THEMES['dark' if self.dark_theme else 'light']
        self.table.setUpdatesEnabled(False);self.table.setRowCount(len(self.visible_rows))
        for i,r in enumerate(self.visible_rows):
            state=(('已套用・建議確認' if jobs.needs_check(r) else '已套用') if r.get('installed') else '待套用' if r.get('review_method')=='auto_validated_one_click' else '已確認' if r['reviewed']
                   else '無需翻譯' if r['origin'] in ('keep_original','not_display') else '比對中' if r['origin']=='pending' else '待校對' if r['supported'] and r['changed']
                   else '不需更動' if r['supported'] and r['origin']!='untranslated' else '待查')
            original=jobs.original_of(r) or r['key']
            for j,text in enumerate((original,r['proposed'],jobs.SOURCE_NAMES.get(r['origin'],r['origin']),'● '+state)):
                item=QTableWidgetItem(str(text).replace('\n',' ')[:130])
                if j==0:
                    outer=r['source'].split('!/')[0]
                    shown=jobs.mod_display_name(self.session.get('instance'),outer) if outer.startswith('mods/') and self.session.get('instance') else ''
                    checked=r.get('ai_review') or {}
                    seen={'ok':'AI 已對照英文核對：無誤','fixed':'AI 核對後改寫','rejected':'AI 核對：'+str(checked.get('note') or ''),
                          'skipped':'AI 未核對：'+str(checked.get('note') or '')}.get(checked.get('verdict'),'')
                    mine='你已確認' if str(r.get('review_method') or '').startswith('user_confirmed') else ''
                    # A file that holds only Chinese is shown with the installed mod's English; its own text is kept here.
                    own='這個檔案裡的中文：'+str(r.get('zh_cn')) if r.get('en_ref') and r.get('zh_cn') else ''
                    same='和「'+r['same_key_as'].split('!/')[0].split('/')[-1]+'」裡的同一句用同一個譯文' if r.get('same_key_as') else ''
                    turned=(r.get('ai_rejected') or {}).get('text')
                    turned='AI 的譯文（未採用，雙擊可拿來修改）：'+turned if turned and not r.get('installed') else ''
                    item.setToolTip('\n'.join(x for x in (shown and '模組：'+shown,r['key'],r['source'],own,r.get('issue') or '',turned,same,seen,mine) if x))
                else:item.setToolTip(str(text))
                if j==0:item.setData(MODULE_ROLE,jobs.module_label(self.session.get('instance'),r))
                if j==3:
                    item.setForeground(QColor(tokens[STATE_ROLE.get(state,'text60')]))
                    font=item.font();font.setBold(True);item.setFont(font)
                self.table.setItem(i,j,item)
            self.table.setRowHeight(i,50)
        self.table.setUpdatesEnabled(True);self.table.scrollToTop()
        self.page_label.setText(f'共 {len(filtered):,} 筆 · 第 {self.page_index+1} / {pages} 頁')
        self.prev.setEnabled(self.page_index>0);self.next.setEnabled(self.page_index+1<pages)
        self.update_ai_button()

    def fill_summary(self):
        counts=self.session.get('source_counts',{})
        # Gaps are counted once, in the line above; the source line lists where translations came from.
        self.report_sources.setText('譯文來源：'+'　'.join(f'{jobs.SOURCE_NAMES.get(k,k)} {v:,}' for k,v in sorted(counts.items(),key=lambda kv:-kv[1]) if k!='untranslated'))
        stages={'scanning':'掃描中，找到的文字稍後會列在這裡。','references':'掃描已完成，正在更新參考庫；下方暫列原文。','matching':'正在比對中文來源，譯文陸續加入。',
                'awaiting_game':'譯文已保存。關閉相關遊戲後，按右下方「重試套用」。','cancelled':'已停止；已保存的內容仍可查看。','apply_failed':'套用未完成；譯文已保存。',
                'blocked':'此批次無法繼續，請查看下方原因。','installed':'已直接套用到模組包，原檔已備份。','restored':'這一批已還原。'}
        badges={'installed':('已套用','done'),'blocked':('需要處理','blocked'),'apply_failed':('套用未完成','blocked'),'awaiting_game':('等待關閉遊戲','progress'),
                'cancelled':('已停止','todo'),'restored':('已還原','todo'),'scanning':('處理中','progress'),'references':('處理中','progress'),'matching':('處理中','progress')}
        partial=self.session['status']=='installed' and self.unapplied_count()
        kept=self.nothing_new(self.session)
        set_pill(self.report_state,*(('部分套用','progress') if partial else ('已套用','done') if kept else badges.get(self.session['status'],('待套用','todo'))))
        message='先前套用的翻譯都還在，這次沒有新的內容要寫入。' if kept else stages.get(self.session['status'],'本次已產生的譯文與待處理項目如下。')
        pending=self.unapplied_count()
        if pending and self.session['status'] in ('needs_review','ready_to_apply','installed'):
            # Reports from older versions could stop after confirming without writing anything.
            message=f'這批有 {pending:,} 筆已通過檢查的譯文，但還沒寫入模組包。關閉遊戲後按右下「備份並套用譯文」，會先備份再套用，不用重新翻譯。'
        if self.session.get('is_preview'):message+=f"\n已記錄 {self.session['preview_total']:,} 筆，處理中先預覽最近 200 筆；結束後載入完整報告。"
        if self.session.get('apply_error'):message+='\n'+self.session['apply_error']
        if self.session.get('status')=='installed':message+=''.join('\n'+n for n in self.applied_notes(self.session))
        self.report_summary.setText(message)
        self.fill_overview()
        problems=[jobs.describe_error(e) for e in self.session.get('errors',[])]
        problems+=[Path(str(r[0])).name+'：原本的 zh_tw.json 格式錯誤（遊戲也讀不到），已依英文與簡中重建' for r in self.session.get('repairs',[])]
        self.report_errors.setVisible(bool(problems))
        self.report_errors.setText('需要留意：\n'+'\n'.join('• '+p for p in problems[:5])+(f'\n另有 {len(problems)-5} 項，詳見報告資料夾。' if len(problems)>5 else ''))

    def toggle_sources(self):
        show=not self.report_sources.isVisible();self.report_sources.setVisible(show)
        self.sources_toggle.setText('隱藏譯文來源明細' if show else '顯示譯文來源明細')

    def fill_overview(self):
        o=jobs.report_overview(self.session)
        cards=jobs.home_cards(self.session)
        for key,(number,text) in zip(('rate','english'),cards['cards']):
            value,detail=self.overview[key];value.setText(number);detail.setText(text)
        value,detail=self.overview['check'];value.setText(f"{o['check']:,}")
        detail.setText('、'.join(f'{k} {n:,}' for k,n in o['check_kinds'])+'\n按上方「建議確認」查看' if o['check'] else '沒有需要確認的翻譯')
        value,detail=self.overview['backup']
        if o['backup']:value.setText('已備份');detail.setText(stamp_text(Path(o['backup']).name)+'\n可在「備份與還原」復原')
        else:value.setText('—');detail.setText('這次沒有寫入；先前的備份在「備份與還原」' if o['recovered'] else '還沒有套用，所以沒有備份')
        notes=[]
        if cards['written']:notes.append(cards['written'])
        if o['applied']:notes.append(f"這一批寫入 {o['applied']:,} 筆譯文"+(f"（含先前套用 {o['recovered']:,} 筆）" if o['recovered'] else ''))
        if o['not_applied']:notes.append('沒有寫入：'+'、'.join(f'{n:,} 筆{why}' for n,why in o['not_applied']))
        if o['rechecked']:notes.append('套用後已重新掃描整合包確認寫入')
        if o['context']:notes.append(f"另有 {o['context']:,} 筆程式或設定裡的文字，需確認是否顯示在遊戲中（見「待查程式與設定」）")
        if o['renamed']:notes.append(f"{o['renamed']:,} 筆是整合包改過名稱的文字，只採用符合新名稱的來源")
        if self.session.get('ai_checked'):notes.append(f"AI 對照英文核對過 {self.session['ai_checked']:,} 筆有疑點的譯文，判斷無誤")
        reused=sum(bool(r.get('ai_reused')) for r in self.session.get('rows',[]))
        if reused:notes.append(f'{reused:,} 筆沿用先前 AI 翻過的同一句，沒有再消耗額度')
        notes.append('外部翻譯 API 未使用（0 筆）')
        self.report_counts.setText('　·　'.join(notes))

    def review_current(self):self.review_row(self.table.currentRow(),0)
    def review_row(self,index,column=0):
        if self.busy or not self.session or index<0 or index>=len(getattr(self,'visible_rows',[])):return
        row=self.visible_rows[index];dialog=ReviewDialog(row,self)
        if dialog.exec()==QDialog.Accepted:
            # Only rows the user confirmed here become translation memory for later modpacks.
            original=jobs.original_of(row)
            if row.get('kind') in ('language','class_display') and row_memory_scope(row) and original:
                jobs.TranslationMemory(self.home).remember(row_memory_scope(row),row['key'],original,row['proposed'],row['source'])
            jobs.write_json(Path(self.session['report'])/'session.json',self.session);self.fill_table()

    def apply_job(self):
        if not self.session:return
        # No row-by-row confirmation needed: everything that passes the automatic checks is applied,
        # the same as one-click; doubtful rows stay listed under 建議確認.
        count=jobs.applicable_count(self.session)
        if not count:QMessageBox.information(self,'沒有可套用的譯文','這批沒有尚未套用、且通過檢查的譯文。');return
        language='，並把遊戲語言設為繁體中文' if self.set_language.isChecked() else ''
        if QMessageBox.question(self,'備份並套用',f'將備份原檔，並套用 {count:,} 筆通過檢查的譯文{language}到：\n{self.session["instance"]}\n\n'
                                '已確認用途的程式文字會寫入原模組，切換語言也會維持繁中，可從備份還原。'
                                '不需要逐筆確認；有疑點的會列在「建議確認」。請先關閉此模組包的遊戲。是否繼續？')!=QMessageBox.Yes:return
        self.session['set_language']=self.set_language.isChecked()
        def operation(w):
            w.progress.emit(0,'整理譯文',f'統一譯名並確認 {count:,} 筆譯文，套用前不會修改任何檔案')
            jobs.prepare_to_apply(self.session)
            return jobs.apply_session(self.session,self.home,w.progress.emit)
        # Make the start page describe this job right away: which modpack, how many rows, what is happening.
        self.path.setText(self.session['instance'])
        self.step.setText(f"正在把 {count:,} 筆譯文套用到「{Path(self.session['instance']).name}」")
        self.detail.setText('先整理譯文，再確認遊戲已關閉、備份原檔、寫入並檢查；請不要開啟遊戲。')
        self.show_cards(jobs.home_cards(self.session))
        self.navigate(0);self.run_worker('apply',operation,self.apply_done)

    def apply_done(self,result):
        self.check_outdated()
        self.job_done(result);self.notify_finished('套用完成',f"已套用 {result.get('installed_count',0):,} 筆，原檔已備份。")

    def applied_notes(self,result):
        """Plain-language follow-ups after applying (language switch, pack location, skipped embedded mods)."""
        notes=[]
        if result.get('resource_pack'):
            notes.append('模組的翻譯放在資源包「MCTranslator-zh_tw」並已自動啟用，模組檔本身沒有修改，'
                         'CurseForge 更新或檢查檔案時不會洗掉翻譯。')
        for why,n in (result.get('held_back') or {}).items():notes.append(f'{n:,} 筆{why}。')
        notes.append('遊戲語言已設為繁體中文（台灣）。' if result.get('language_set') else '請在遊戲的「選項 → 語言」選擇繁體中文（台灣）。')
        return notes

    def open_report(self):
        if self.session:open_path(self.session['report'])

    def refresh_backups(self):
        self.backups.clear()
        for p in sorted((self.home/'output').glob('*/原始備份/*/_備份紀錄/manifest.json'),reverse=True):
            try:
                data=json.loads(p.read_text(encoding='utf-8'))
                state,role={'installed':('可還原','done'),'restored':('已還原','todo'),'restoring':('還原中斷，可繼續還原','blocked'),
                            'backed_up':('套用中斷，可還原','blocked'),'rollback_incomplete':('復原未完成，可還原','blocked'),
                            'backing_up':('備份時中斷，遊戲檔案未修改','todo'),
                            'rolled_back':('套用失敗，已自動復原','todo')}.get(data['status'],(data['status'],'todo'))
                added=sum(f.get('before') is None for f in data['files'])
                row=QWidget();line=QHBoxLayout(row);line.setContentsMargins(14,10,14,10);text=QVBoxLayout();text.setSpacing(2)
                text.addWidget(label(Path(data['instance']).name,'section'))
                text.addWidget(label(f"{stamp_text(p.parents[1].name)}　·　修改 {len(data['files'])-added:,} 個檔案"+(f"、新增 {added:,} 個" if added else ''),'sub'))
                line.addLayout(text,1);pill=label('','pill');set_pill(pill,state,role);line.addWidget(pill,0,Qt.AlignVCenter)
                row.setAttribute(Qt.WA_TransparentForMouseEvents)
                item=QListWidgetItem();item.setSizeHint(row.sizeHint().expandedTo(QSize(0,64)))
                item.setData(Qt.UserRole,(str(p.parents[1]),data));self.backups.addItem(item);self.backups.setItemWidget(item,row)
            except (ValueError,KeyError,OSError):continue
        self.backups_empty.setVisible(self.backups.count()==0)

    def open_backup(self):
        item=self.backups.currentItem()
        if item:open_path(item.data(Qt.UserRole)[0])

    def restore_job(self):
        item=self.backups.currentItem()
        if not item:return
        backup,data=item.data(Qt.UserRole)
        if data['status'] not in jobs.RESTORABLE:
            QMessageBox.information(self,'這一批不需要還原','這一批沒有留下寫入模組包的修改（已還原、已自動復原，或在備份階段就中斷）。');return
        cut=data['status'] in jobs.INTERRUPTED
        if QMessageBox.question(self,'還原這一批翻譯？',('這一批上次沒有做完。程式會逐一檢查：還是原樣的檔案不動，已寫入的檔案還原。\n\n' if cut else '')
                                +f"將還原 {len(data['files'])} 個檔案：\n{data['instance']}\n\n本批新增的翻譯檔也會移除；有後續修改時會停止。")!=QMessageBox.Yes:return
        self.run_worker('restore',lambda w:jobs.restore_backup(Path(backup),Path(data['instance'])),self.restore_done)
    def restore_done(self,result):
        self.check_outdated()
        if self.session and self.session.get('backup')==result['backup_path']:
            self.session['status']='restored';self.session['installed_count']=0
            for row in self.session['rows']:
                if row.get('installed'):row['installed']=False;row['reviewed']=False
            jobs.write_json(Path(self.session['report'])/'session.json',self.session)
            self.show_cards(dict(cards=[('—','已還原；重新按「一鍵完整翻譯並套用」後重新計算')]*2,written='這一批已還原。'))
            set_pill(self.status,'已還原','todo');self.fill_table()
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
        self.release_notes.setMarkdown(info.get('notes',''))
        available=info['status']=='available'
        self.navs[3].setText('程式更新 · 有新版' if available else '程式更新')
        self.update_badge.setText('新版本 '+info.get('version',''));self.update_badge.setVisible(available)
        self.install_btn.setEnabled(available and not self.busy)
    def install_update(self):
        if not self.update_info or self.update_info['status']!='available':return
        if not getattr(sys,'frozen',False):QMessageBox.information(self,'原始碼模式','請在打包後的 EXE 使用程式更新。');return
        if QMessageBox.question(self,'下載並安裝更新',f"更新到 {self.update_info['version']}？\n下載後會校驗、關閉程式並重新啟動。備份、報告和設定都會保留。")!=QMessageBox.Yes:return
        self.run_worker('download_update',lambda w:updater.download_update(self.update_info,self.home,lambda p:w.progress.emit(p,'下載更新','')),self.update_downloaded)
        self.update_progress.show();self.worker.progress.connect(lambda p,*_:(self.update_progress.setValue(p),self.update_status.setText(f'下載中 {p}%')))
    def update_downloaded(self,result):
        try:
            updater.launch_update(result[0],result[1],self.home)
            # Connecting to finished here would race: the worker may already have finished,
            # leaving the old window open while the helper waits for it to exit.
            self.quit_after_worker=True
            self.update_status.setText('校驗完成，程式即將關閉並自動開啟新版…')
            if not self.worker.isRunning():QTimer.singleShot(0,lambda:QApplication.exit(0))
        except Exception as exc:self.on_error(str(exc))

    def closeEvent(self,event):
        if self.busy:
            QMessageBox.information(self,'工作仍在進行','請等待目前工作完成。掃描工作可先按「停止」，套用與更新期間請勿關閉。');event.ignore()
        elif self.pending_workers():
            # Defer exit until bounded background requests return; never kill a QThread. A hidden window
            # no longer counts for quit-on-last-window-closed, so the app quits explicitly afterwards.
            self.settings.setValue('geometry',self.saveGeometry())
            if self.tray:self.tray.hide()
            self.hide();event.ignore()
            for w in self.pending_workers():w.finished.connect(lambda w=w:self.quit_when_idle(w),Qt.QueuedConnection)
        else:
            if self.isVisible():self.settings.setValue('geometry',self.saveGeometry())
            if self.tray:self.tray.hide()
            event.accept()

    def pending_workers(self):
        alive=[]
        for w in [self.update_worker,*self.background]:
            try:
                if w and w.isRunning():alive.append(w)
            except RuntimeError:pass  # already deleted via deleteLater
        return alive

    def quit_when_idle(self,worker):
        try:worker.wait(5000)  # finished is emitted just before the thread fully stops
        except RuntimeError:pass
        if not self.pending_workers():QApplication.quit()


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
    home=app_home()
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s:%(name)s:%(message)s',
                        handlers=[RotatingFileHandler(home/'application.log',maxBytes=1024*1024,backupCount=2,encoding='utf-8')])
    lock=QLockFile(str(home/'application.lock'))
    if not lock.tryLock(50):QMessageBox.information(None,'程式已開啟','請切換到已開啟的 MC Translator 視窗。');return
    updater.clean_leftovers(home)
    window=MainWindow(home);window.show()
    smoke_dest=sys.argv[sys.argv.index('--smoke-test')+1] if '--smoke-test' in sys.argv else os.environ.get('MC_TRANSLATOR_SMOKE_DEST')
    if smoke_dest:
        dest=Path(smoke_dest);dest.mkdir(parents=True,exist_ok=True)
        def capture():
            window.grab().save(str(dest/'desktop.png'))
            window.navigate(3);app.processEvents();window.grab().save(str(dest/'updates.png'))
            window.navigate(4);app.processEvents();window.grab().save(str(dest/'ai.png'))
            window.navigate(6);app.processEvents();window.grab().save(str(dest/'shared.png'))
            (dest/'smoke.json').write_text(json.dumps(dict(version=updater.VERSION,window=window.windowTitle(),tabs=window.pages.count(),frozen=bool(getattr(sys,'frozen',False)))),encoding='utf-8')
            window.close()  # waits for the catalog request instead of killing its thread
        QTimer.singleShot(800,capture)
    else:
        QTimer.singleShot(1800,window.check_updates_on_start)
        QTimer.singleShot(3000,lambda:window.catalog is None and not window.busy and window.refresh_catalog())  # translation update badge
        QTimer.singleShot(900,window.probe_ai)
    app.exec();lock.unlock()


if __name__=='__main__':main()
