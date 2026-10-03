"""Read-only position-level inventory. Reports are local; no instance files are written.

python scripts/inventory_text.py <instance> --output <folder> [--compare <categories.json>]
--check fails on uncovered text, known unsupported candidates, or incomplete reads.
--decisions accepts explicit non-player decisions bound to each candidate's fingerprint.
Matching file counts or an old report are never acceptance evidence.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src'), str(Path(__file__).resolve().parent)]
from mc_zh_tw_translator import desktop_jobs
from mc_zh_tw_translator import text_inventory as inventory_tools


def inventory(root, out, decisions=None):
    out.mkdir(parents=True, exist_ok=True)
    audit = desktop_jobs.scan(root, out / 'scan', lambda *_: None, lambda: False,
                              cache=out/'cache', details='summary')
    result = audit.text_inventory
    # Developer judgements, never user translation confirmations. Source, position and
    # wording changes invalidate the decision, and a reason is mandatory.
    for item in result['candidates']:
        decision = (decisions or {}).get(item['fingerprint'], {})
        kept = next((why for pattern, why in desktop_jobs.KEEP_ENGLISH_FORMATS if pattern.search(item['source'])), None)
        if (item['state'] != 'covered' and decision.get('status') == 'not_player_text'
                and isinstance(decision.get('reason'), str) and decision['reason'].strip()):
            item['state'] = 'excluded'; item['reason'] = decision['reason']
        elif item['state'] != 'covered' and kept:
            # Checked in the mod's program and kept English on purpose; the report says why in grey.
            item['state'] = 'excluded'; item['reason'] = kept
    result['counts']=dict(collections.Counter(c['state'] for c in result['candidates']))
    result['accepted'] = not result['errors'] and not any(
        c['state'] in ('uncovered', 'listed') for c in result['candidates']) and not audit.errors
    result['scan_errors'] = audit.errors
    (out / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    return inventory_tools.categories(result), result['accepted']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('modpacks', nargs='+', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--compare', type=Path)
    ap.add_argument('--decisions', type=Path)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv); args.output.mkdir(parents=True, exist_ok=True)
    earlier = json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
    decisions = json.loads(args.decisions.read_text(encoding='utf-8')) if args.decisions else {}
    everything = {}; accepted = True; seen = set()
    for root in args.modpacks:
        root = root.resolve()
        if not root.is_dir(): raise ValueError('找不到要盤點的模組包資料夾：' + str(root))
        label = root.name
        if label in seen: label += '-' + inventory_tools.digest(str(root))[:8]
        seen.add(label)
        cats, ok = inventory(root, args.output / label, decisions)
        everything[label] = cats; accepted = accepted and ok
        shown = inventory_tools.changed_categories(cats, (earlier or {}).get(label, {})) if earlier is not None else cats
        print(f'{label}：{len(cats)} 類未涵蓋或未能檢查的文字；' + ('涵蓋驗收通過' if ok else '涵蓋驗收未通過'))
        for name, c in shown.items():
            print(f"  {c['files']:,} 檔、{c['strings']:,} 個文字位置：{name}")
            for path, found in c['samples'][:1]: print(f'    {path}：{found}')
    (args.output / 'categories.json').write_text(json.dumps(everything, ensure_ascii=False, indent=1), encoding='utf-8')
    return 1 if args.check and not accepted else 0


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as exc:
        print(desktop_jobs.explain_error(exc), file=sys.stderr); sys.exit(2)
