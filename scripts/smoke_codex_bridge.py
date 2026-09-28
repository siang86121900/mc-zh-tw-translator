"""Read-only protocol smoke test: isolated, signed out, never starts model turns."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from mc_zh_tw_translator.codex_bridge import CodexClient, install_runtime

with tempfile.TemporaryDirectory(prefix='mc-codex-smoke-') as folder:
    if '--install' in sys.argv:
        install_runtime(Path(folder),lambda p,*_:print(f'Official runtime download: {p}%',flush=True))
    with CodexClient(Path(folder)) as client:
        account=client.account()
        if account is not None:raise RuntimeError('Isolated client unexpectedly signed in')
        print(json.dumps({'initialized':True,'signed_in':False,'model_turns':0}))
