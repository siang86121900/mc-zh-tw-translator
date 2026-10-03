"""Read-only inventory of player-looking text the app's scan does not cover, for checking before a release.

Every file of a modpack is opened, archives too (two levels deep): Chinese and English sentences of four words or more
are collected per file and compared with the files the app's own scan made rows for (desktop_jobs.scan). What is
left is grouped by kind of file (mods' data/<mod>/<kind>/, assets/<mod>/<kind>/, top-level folders), so a whole
kind of text no reader covers shows up as one line. Nothing in the modpack is written; results go to --output.

    python scripts/inventory_text.py "<modpack>" ["<modpack>" ...] --output <folder> [--compare <earlier categories.json>]

With --compare, only the categories that are new or hold more files than in the earlier run are printed: what a
change of the app (or a new modpack) left uncovered. Each category still needs a person to judge whether players
see it (docs/translation-reference.md lists the kinds already judged not to be player text).
"""
import argparse
import collections
import gzip
import io
import json
import re
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src'), str(Path(__file__).resolve().parent)]
from mc_zh_tw_translator import desktop_jobs  # noqa: E402

HAN = re.compile('[㐀-鿿]+')
EN_SENTENCE = re.compile(r"(?:^|[\s\"'(])([A-Za-z][a-z']+(?:[ ,]+[A-Za-z][a-z']+){3,})")
SKIP_TOP = {'saves', 'logs', 'crash-reports', 'screenshots', 'backups', 'cache', '.mixin.out', 'natives', 'libraries',
            'versions', 'downloads', 'local', 'modernfix', 'lightspeed-cache', '.cache', '.fabric', 'simplebackups',
            'xaero', 'journeymap', 'schematics', 'debug', 'dynamic-resource-pack-cache', 'licenses'}
TEXT_SUFFIXES = {'.json', '.json5', '.jsonc', '.snbt', '.toml', '.txt', '.lang', '.cfg', '.yaml', '.yml', '.properties',
                 '.js', '.zs', '.mcfunction', '.md', '.xml', '.csv', '.ini', '.html', '.nbt', '.lua'}
# Other languages' copies and files for people (licences, change logs) are not text the game shows in Chinese.
OTHER_LANGUAGE = re.compile(r'(?:^|/)(?!en_us|zh_tw|zh_cn)[a-z]{2}_[a-z]{2}(?:_\d)?(?:/|\.(?:json|lang|txt|md)$)', re.I)
NOT_PLAYER = re.compile(r'(?i)(?:^|/)(?:META-INF/|license|licence|notice|readme|changelog|credits?|authors?)|\.class$')


def strings_of(name, raw):
    """Chinese runs (with a little context) and English sentences of one file."""
    if PurePosixPath(name).suffix.lower() == '.nbt':
        try: raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error): pass  # damaged .nbt files in Tensura and Elemental Awakening mods: read as they are
    text = raw.decode('utf-8', 'ignore')
    if '\0' in text[:2000] and not name.lower().endswith('.nbt'): return []
    found = []; last = -1
    for m in HAN.finditer(text):
        if m.start() < last: continue
        last = m.end() + 60; found.append(text[max(0, m.start() - 20):last].strip()[:120])
    found += [m[1][:120] for m in EN_SENTENCE.finditer(text)]
    return found


def walk(root, sink):
    def archive(z, label, depth):
        for info in z.infolist():
            n = info.filename; low = n.lower()
            if low.endswith(('.jar', '.zip')) and depth < 2 and info.file_size < 300 << 20:
                try:
                    with zipfile.ZipFile(io.BytesIO(z.read(n))) as inner: archive(inner, f'{label}!/{n}', depth + 1)
                except (zipfile.BadZipFile, OSError, RuntimeError): pass
            elif (PurePosixPath(low).suffix in TEXT_SUFFIXES and info.file_size < 8 << 20
                  and not NOT_PLAYER.search(n) and not OTHER_LANGUAGE.search('/' + n)):
                try: found = strings_of(n, z.read(n))
                except (OSError, RuntimeError, zipfile.BadZipFile): continue
                if found: sink(f'{label}!/{n}', found)
    for p in sorted(root.rglob('*')):
        if not p.is_file(): continue
        rel = p.relative_to(root).as_posix()
        if rel.split('/', 1)[0] in SKIP_TOP or rel.startswith('mods/.'): continue
        try:
            if rel.lower().endswith(('.jar', '.zip')):
                if p.stat().st_size < 1200 << 20:
                    with zipfile.ZipFile(p) as z: archive(z, rel, 0)
            elif (p.suffix.lower() in TEXT_SUFFIXES and p.stat().st_size < 8 << 20
                  and not NOT_PLAYER.search(rel) and not OTHER_LANGUAGE.search('/' + rel)):
                found = strings_of(rel, p.read_bytes())
                if found: sink(rel, found)
        except (OSError, zipfile.BadZipFile): continue


def category(path):
    parts = path.split('!/'); inner = parts[-1]; ext = PurePosixPath(inner).suffix.lower(); top = parts[0].split('/', 1)[0]
    if len(parts) > 1:
        m = re.match(r'(?:.*/)?(assets|data)/[^/]+/([^/]+)/', inner)
        return f'{top} 檔內 {m[1]}/*/{m[2]} ({ext})' if m else f'{top} 檔內 {inner.split("/")[0]} ({ext})'
    bits = inner.split('/')
    return f'{"/".join(bits[:2]) if len(bits) > 2 else bits[0]} ({ext})'


def inventory(root, out):
    audit = desktop_jobs.scan(root, out/'scan', lambda *a: None, lambda: False, cache=None, details='summary')
    covered = {r['source'].removeprefix('instance!/') for r in audit.rows}
    # A folder the scan already lists as a format not supported yet (data/<mod>/<kind>/) is known, not missed.
    listed = tuple(s for s in covered if s.endswith('/'))
    lang_dirs = {m[1] for s in covered if (m := re.match(r'(.*/lang/)[a-z_]+\.(json|lang|snbt)$', s, re.I))}
    cats = collections.defaultdict(lambda: dict(files=0, strings=0, samples=[]))

    def sink(name, found):
        m = re.match(r'(.*/lang/)[a-z_]+\.(json|lang|snbt)$', name, re.I)
        if name in covered or (m and m[1] in lang_dirs) or name.startswith(listed):
            return
        c = cats[category(name)]; c['files'] += 1; c['strings'] += len(found)
        if len(c['samples']) < 3: c['samples'].append([name[-140:], found[:3]])
    walk(root, sink)
    return dict(sorted(cats.items(), key=lambda kv: -kv[1]['strings']))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('modpacks', nargs='+', type=Path); ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--compare', type=Path, help='categories.json of an earlier run')
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    earlier = json.loads(args.compare.read_text(encoding='utf-8')) if args.compare else None
    everything = {}
    for root in args.modpacks:
        cats = inventory(root.resolve(), args.output/root.name)
        everything[root.name] = cats
        before = (earlier or {}).get(root.name, {})
        print(f'== {root.name}: {len(cats)} 類沒有讀取器負責的文字')
        for name, c in cats.items():
            if earlier is not None and name in before and c['files'] <= before[name]['files']: continue
            print(f"  {c['files']:6} 檔 {c['strings']:7} 句  {name}")
            for path, found in c['samples'][:1]: print(f"           {path} | {' / '.join(found)[:160]}")
    (args.output/'categories.json').write_text(json.dumps(everything, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
