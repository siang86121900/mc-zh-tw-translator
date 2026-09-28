"""Offline visual regression artifacts; no account, network or instance writes."""
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontInfo, QFontDatabase
from mc_zh_tw_translator.desktop import MainWindow

app=QApplication([]);app.setStyle('Fusion')
for name in ('segoeui.ttf','msjh.ttc','msjhbd.ttc'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
font=QFont();font.setFamilies(['Segoe UI','Microsoft JhengHei UI','Microsoft JhengHei'])
font.setPointSize(10);font.setHintingPreference(QFont.PreferFullHinting);app.setFont(font)
out=ROOT/'tmp'/'visual-qa';out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    window=MainWindow(Path(folder));window.resize(1120,850);window.show();app.processEvents()
    window.grab().save(str(out/'start.png'))
    for theme in ('light','dark'):
        window.dark_theme=theme=='dark';window.apply_theme()
        for width,height in ((1120,850),(880,600)):
            window.resize(width,height)
            for index,name in enumerate(('start','report','backups','updates','ai')):
                window.navigate(index);app.processEvents()
                window.grab().save(str(out/f'{theme}-{name}-{width}.png'))
        window.navigate(1);window.filter.showPopup();app.processEvents()
        window.filter.view().window().grab().save(str(out/f'{theme}-popup.png'))
        window.filter.hidePopup()
    print(json.dumps(dict(family=QFontInfo(window.path.font()).family(),pixel_size=QFontInfo(window.path.font()).pixelSize(),dpr=window.devicePixelRatioF())))
    window.close()
