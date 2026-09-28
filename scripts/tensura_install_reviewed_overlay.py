"""Prepare or install only the fingerprinted, reviewed language entries."""
import argparse, collections, hashlib, json
from pathlib import Path
from full_translation_audit import parse, placeholders
from mc_zh_tw_translator.deployment import apply_reviewed

ROOT=Path(__file__).resolve().parents[1]
B=ROOT/'output/Tensura Neo Otherworld/rebuild_review'
INSTANCE=Path('C:/Users/User/curseforge/minecraft/Instances/Tensura Neo Otherworld')
def digest(b):return hashlib.sha256(b).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--install',action='store_true');args=ap.parse_args()
    rows=json.loads((B/'reviewed_provenance.json').read_text(encoding='utf-8'))
    grouped=collections.defaultdict(dict)
    for r in rows:
        if not r['reviewed']:
            raise ValueError('Unreviewed entry: '+r['key'])
        if r['review_fingerprint']!=digest(json.dumps([r['file'],r['key'],r['en'],r['zh_cn'],r['before'],r['after']],ensure_ascii=False).encode()):
            raise ValueError('Review fingerprint changed: '+r['key'])
        if placeholders(r['en'])!=placeholders(r['after']):
            raise ValueError('Placeholder mismatch: '+r['key'])
        grouped[r['namespace']][r['key']]=r['after']
    manifest=[]
    if args.install:
        manifest=json.loads((B/'overlay_manifest.json').read_text(encoding='utf-8'))
        # Validate all files before writing any of them.
        for r in manifest:
            p=INSTANCE/r['file'];b=p.read_bytes() if p.exists() else None
            if (digest(b) if b is not None else None)!=r['before']:
                raise ValueError('Instance changed: '+str(p))
            if digest((B/'overlay'/r['file']).read_bytes())!=r['after']:
                raise ValueError('Candidate changed: '+r['file'])
        # Bind the complete staged file to the reviewed edits, not just a claimed hash.
        for r in manifest:
            p=INSTANCE/r['file']
            ns=Path(r['file']).parts[2]
            expected=parse(p.read_bytes()) if p.exists() else {}
            expected.update(grouped[ns])
            if parse((B/'overlay'/r['file']).read_bytes()) != expected:
                raise ValueError('Staged file contains unreviewed changes: '+r['file'])
        records=[dict(r,reviewed=True,verified=True) for r in manifest]
        backup=apply_reviewed(INSTANCE,B/'overlay',records,ROOT/'output')
        (B/'overlay_installation.json').write_text(json.dumps(dict(installed=True,files=manifest,backup=str(backup),entries=len(rows),jar_changes=False,language_setting_changed=False),ensure_ascii=False,indent=2),encoding='utf-8')
        print('Installed and read back:',len(manifest),'files;',len(rows),'reviewed entries')
        return
    for ns,edits in grouped.items():
        rel=Path('kubejs/assets')/ns/'lang/zh_tw.json'
        p=INSTANCE/rel;original=p.read_bytes() if p.exists() else None
        data=parse(original) if original else {}
        before=dict(data);data.update(edits)
        assert all(data[k]==v for k,v in before.items() if k not in edits)
        dst=B/'overlay'/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        assert parse(dst.read_bytes())==data
        manifest.append(dict(file=rel.as_posix(),before=digest(original) if original else None,after=digest(dst.read_bytes()),reviewed_keys=sorted(edits)))
    (B/'overlay_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Prepared',len(manifest),'files;',len(rows),'reviewed entries')
if __name__=='__main__':main()
