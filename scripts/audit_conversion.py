"""Find Simplified-to-Taiwan conversion slips in real modpacks (read only).

One simplified character can stand for several traditional ones (只 only / 隻 counter, 并 並 / 併, 干 乾 / 幹 / 干,
几 幾 / 機 / 几…); the converter picks by its word list and is wrong where it knows no phrase (擊殺 3 只殭屍).
This tool converts every Simplified string of the given modpacks' mods, quests, KubeJS and configs, and lists,
for each simplified character that came out as more than one traditional character, the contexts of each
choice, so a person can spot the wrong ones and add a rule to desktop_references.SLIPS (with a test).

    python scripts/audit_conversion.py <modpack folder> [...] --output report.txt [--save corpus.json]
    python scripts/audit_conversion.py --corpus corpus.json --output report.txt   (again, after changing the rules)

With --corpus the report also lists every text whose conversion changed since the corpus was saved, so a new
rule's effect on real text is seen before it is released. Nothing in the modpacks is written.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from mc_zh_tw_translator.desktop_references import has_simplified, to_taiwan  # noqa: E402

HAN = re.compile('[一-鿿]')
QUOTED = re.compile(r'"((?:\\.|[^"\\])*)"')
LOOSE = ('kubejs', 'config', 'defaultconfigs', 'scripts')


def collect(folders):
    texts = set()
    def add(value):
        if isinstance(value, str) and HAN.search(value) and has_simplified(value):
            texts.add(value)
    def walk(value):
        if isinstance(value, dict):
            for v in value.values():walk(v)
        elif isinstance(value, list):
            for v in value:walk(v)
        else:add(value)
    for folder in folders:
        for jar in list((folder/'mods').glob('*.jar'))+list((folder/'resourcepacks').glob('*.zip')):
            try:z = zipfile.ZipFile(jar)
            except (OSError, zipfile.BadZipFile):continue
            with z:
                for name in z.namelist():
                    if name.endswith('.json') and ('/lang/zh_cn' in name or '/data/' in '/'+name):
                        try:walk(json.loads(z.read(name).decode('utf-8-sig')))
                        except (ValueError, UnicodeError):pass
        for sub in LOOSE:
            for p in (folder/sub).rglob('*'):
                if p.suffix in ('.json', '.snbt', '.js', '.zs') and p.is_file() and p.stat().st_size < 5_000_000:
                    try:text = p.read_text(encoding='utf-8')
                    except (OSError, UnicodeError):continue
                    for m in QUOTED.finditer(text):add(m[1])
    return sorted(texts)


def ambiguous(pairs, per_choice=8):
    """Simplified characters that came out as more than one traditional character, with contexts."""
    choices = collections.defaultdict(collections.Counter)
    contexts = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for simplified, converted in pairs:
        if len(simplified) != len(converted):continue  # a phrase changed length; positions no longer line up
        for i, (a, b) in enumerate(zip(simplified, converted)):
            if HAN.match(a):
                choices[a][b] += 1
                contexts[a][b][converted[max(0, i-3):i+4].replace('\n', '⏎')] += 1
    lines = []
    for a, counter in sorted(choices.items(), key=lambda x: -sum(x[1].values())):
        if len(counter) < 2:continue
        lines.append(f'{a}：'+'、'.join(f'{b} {n}' for b, n in counter.most_common()))
        for b, _ in counter.most_common():
            lines.append(f'    {b}｜'+'  '.join(f'{k}({v})' for k, v in contexts[a][b].most_common(per_choice)))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folders', nargs='*', type=Path)
    ap.add_argument('--corpus', type=Path, help='a corpus saved earlier with --save: [[simplified, converted], ...]')
    ap.add_argument('--save', type=Path, help='save the texts and today\'s conversion, to compare after a rule change')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    earlier = json.loads(args.corpus.read_text(encoding='utf-8')) if args.corpus else []
    texts = [s for s, _ in earlier] if earlier else collect(args.folders)
    pairs = [(s, to_taiwan(s)) for s in texts]
    report = [f'{len(pairs):,} 句簡中', '', '＝ 一個簡體字轉成多個繁體字的情形（逐一檢查少數那一邊）＝']+ambiguous(pairs)
    if earlier:
        changed = [(s, old, new) for (s, old), (_, new) in zip(earlier, pairs) if old != new]
        report += ['', f'＝ 和上次相比改變的轉換：{len(changed):,} 句 ＝']+[f'{old}\n  → {new}' for _, old, new in changed]
    args.output.write_text('\n'.join(report)+'\n', encoding='utf-8')
    if args.save:args.save.write_text(json.dumps(pairs, ensure_ascii=False), encoding='utf-8')
    print(f'{len(pairs):,} 句；報告：{args.output}')


if __name__ == '__main__':
    main()
