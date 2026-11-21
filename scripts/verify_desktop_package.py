"""Block publishing an EXE that cannot generate/read artwork and install a legacy cloud pack."""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def verify(exe: Path, expected_version: str, network=False) -> dict:
    with tempfile.TemporaryDirectory(prefix='mctranslator-release-') as directory:
        destination=Path(directory).resolve()
        result=subprocess.run([str(exe.resolve()),'--smoke-test',str(destination)]+(['--smoke-network-check'] if network else []),
                              env={**os.environ,'QT_QPA_PLATFORM':'offscreen'},timeout=120)
        report=json.loads((destination/'smoke.json').read_text(encoding='utf-8'))
        required=('https_context','https_ca_loaded','cover_generated','cover_readback','custom_cover_read','legacy_cloud_cover_install')+('https_live',)*bool(network)
        if result.returncode or report.get('status')!='passed' or report.get('version')!=expected_version or report.get('frozen') is not True or not all(report.get(key) is True for key in required):
            raise RuntimeError('正式 EXE 功能驗證失敗：'+json.dumps(report,ensure_ascii=False))
        return report


def main():
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    from mc_zh_tw_translator.updater import VERSION
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,default=Path('dist/MCTranslator.exe'))
    parser.add_argument('--network',action='store_true',help='另外驗證正式 EXE 連線公開更新與補丁目錄')
    args=parser.parse_args();print(json.dumps(verify(args.exe,VERSION,args.network),ensure_ascii=True))


if __name__=='__main__':main()
