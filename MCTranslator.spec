# Reproducible Windows build; no instance, reference cache or credentials bundled.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
import sys

root=Path(SPECPATH)
sys.path.insert(0,str(root/'src'))
from mc_zh_tw_translator.updater import VERSION
version_numbers=tuple(map(int,VERSION.split('.')))+(0,)
version_info=VSVersionInfo(ffi=FixedFileInfo(filevers=version_numbers,prodvers=version_numbers,mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[
    StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription','MC Translator'),StringStruct('ProductName','MC Translator'),StringStruct('FileVersion',VERSION),StringStruct('ProductVersion',VERSION),StringStruct('OriginalFilename','MCTranslator.exe')])]),
    VarFileInfo([VarStruct('Translation',[1033,1200])])])
a=Analysis([str(root/'scripts/desktop_launcher.py')],
           pathex=[str(root/'src'),str(root/'scripts')],
           binaries=[],datas=collect_data_files('opencc')+[(str(root/'assets/mc-translator.ico'),'assets'),(str(root/'assets/chevron.svg'),'assets'),(str(root/'assets/check.svg'),'assets')],
           hiddenimports=['full_translation_audit'],
           excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml',
                     'PySide6.QtQuick','matplotlib','numpy','pandas','scipy','PIL','reportlab',
                     'tkinter','IPython','pytest'],
           noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='MCTranslator',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        disable_windowed_traceback=False, icon=str(root/'assets/mc-translator.ico'),version=version_info)
