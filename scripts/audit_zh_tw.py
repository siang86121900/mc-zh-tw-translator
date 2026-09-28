"""Audit zh_tw coverage in translated JARs and KubeJS assets."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path


LANG_RE = re.compile(r"^assets/([^/]+)/lang/en_us\.json$")
LATIN_RE = re.compile(r"[A-Za-z]{3,}")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def load(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def suspicious(en_value: object, zh_value: object) -> bool:
    if not isinstance(en_value, str) or not isinstance(zh_value, str):
        return False
    en = en_value.strip()
    zh = zh_value.strip()
    if not LATIN_RE.search(en):
        return False
    if en == zh:
        return True
    return bool(LATIN_RE.search(zh)) and not CJK_RE.search(zh) and len(zh) > 3


def audit_pair(label: str, en_data: dict, zh_data: dict, totals: Counter, details: list):
    missing = sorted(set(en_data) - set(zh_data))
    unchanged = sorted(
        key for key in en_data.keys() & zh_data.keys()
        if suspicious(en_data[key], zh_data[key])
    )
    totals["sources"] += 1
    totals["keys"] += len(en_data)
    totals["missing"] += len(missing)
    totals["suspicious"] += len(unchanged)
    if missing or unchanged:
        details.append((label, missing, unchanged))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    totals = Counter()
    details = []

    mods = args.root / "mods"
    for jar in sorted(mods.glob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as archive:
                names = set(archive.namelist())
                for name in sorted(names):
                    match = LANG_RE.match(name)
                    if not match:
                        continue
                    zh_name = name[:-10] + "zh_tw.json"
                    en_data = load(archive.read(name))
                    zh_data = load(archive.read(zh_name)) if zh_name in names else {}
                    audit_pair(f"{jar.name}!/{name}", en_data, zh_data, totals, details)
        except zipfile.BadZipFile:
            totals["bad_jars"] += 1

    kubejs = args.root / "kubejs" / "assets"
    for en_path in sorted(kubejs.glob("*/lang/en_us.json")):
        zh_path = en_path.with_name("zh_tw.json")
        en_data = load(en_path.read_bytes())
        zh_data = load(zh_path.read_bytes()) if zh_path.exists() else {}
        audit_pair(str(en_path.relative_to(args.root)), en_data, zh_data, totals, details)

    print(json.dumps(dict(totals), ensure_ascii=False, indent=2))
    for label, missing, unchanged in sorted(
        details, key=lambda item: len(item[1]) + len(item[2]), reverse=True
    ):
        print(f"\n{label}")
        if missing:
            print(f"  MISSING {len(missing)}: " + ", ".join(missing[:20]))
        if unchanged:
            print(f"  SUSPICIOUS {len(unchanged)}: " + ", ".join(unchanged[:20]))
    return 1 if totals["missing"] or totals["bad_jars"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
