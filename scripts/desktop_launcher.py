"""PyInstaller entry point. No terminal window and no source-tree dependency."""
import os
import sys
from pathlib import Path

if not getattr(sys,'frozen',False):
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root/'src'),str(root/'scripts')]
if sys.stdout is None:sys.stdout=open(os.devnull,'w',encoding='utf-8')
if sys.stderr is None:sys.stderr=open(os.devnull,'w',encoding='utf-8')

from mc_zh_tw_translator.desktop import main

if __name__=='__main__':main()
