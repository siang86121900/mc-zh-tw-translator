"""Build the standalone EXE and release integrity files; never upload a release."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from mc_zh_tw_translator.updater import VERSION

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--checksum-only',action='store_true');args=parser.parse_args()
    if not args.checksum_only:
        if not (ROOT/'assets/mc-translator.ico').exists():
            subprocess.run([sys.executable, str(ROOT/'scripts/make_icon.py')], cwd=ROOT, check=True)
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm',str(ROOT/'MCTranslator.spec')],cwd=ROOT,check=True)
    exe=ROOT/'dist/MCTranslator.exe'
    digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    (exe.parent/'SHA256SUMS.txt').write_text(digest+'  MCTranslator.exe\n',encoding='ascii')
    (exe.parent/'build-info.json').write_text(json.dumps(dict(version=VERSION,name=exe.name,size=exe.stat().st_size,sha256=digest),indent=2),encoding='utf-8')
    print(json.dumps(dict(path=str(exe),version=VERSION,size=exe.stat().st_size,sha256=digest)))

if __name__=='__main__':main()
