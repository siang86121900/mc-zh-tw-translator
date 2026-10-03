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
    parser=argparse.ArgumentParser();parser.add_argument('--checksum-only',action='store_true')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dist');args=parser.parse_args()
    destination=args.output_dir.resolve();destination.mkdir(parents=True,exist_ok=True)
    sources=list((ROOT/'src').rglob('*.py'))+[ROOT/'scripts/full_translation_audit.py',
            ROOT/'scripts/desktop_launcher.py',ROOT/'MCTranslator.spec',ROOT/'requirements-desktop.txt']
    def source_hashes():
        return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(sources)}
    hashes=source_hashes()
    if not args.checksum_only:
        if not (ROOT/'assets/mc-translator.ico').exists():
            subprocess.run([sys.executable, str(ROOT/'scripts/make_icon.py')], cwd=ROOT, check=True)
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(destination),
                        str(ROOT/'MCTranslator.spec')],cwd=ROOT,check=True)
        if hashes!=source_hashes():raise RuntimeError('建置途中原始碼改變，請完成修改後重新建置；本次不產生版本證明。')
    exe=destination/'MCTranslator.exe'
    digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    (exe.parent/'SHA256SUMS.txt').write_text(digest+'  MCTranslator.exe\n',encoding='ascii')
    if args.checksum_only:
        # A checksum of an existing executable cannot prove it contains today's source.
        print(json.dumps(dict(path=str(exe),size=exe.stat().st_size,sha256=digest)))
        return
    source_digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    (exe.parent/'build-info.json').write_text(json.dumps(dict(version=VERSION,name=exe.name,size=exe.stat().st_size,
        sha256=digest,source_sha256=source_digest,source_files=hashes),indent=2),encoding='utf-8')
    print(json.dumps(dict(path=str(exe),version=VERSION,size=exe.stat().st_size,sha256=digest)))

if __name__=='__main__':main()
