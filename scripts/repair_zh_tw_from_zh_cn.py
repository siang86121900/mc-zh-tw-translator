"""Repair missing/English zh_tw values using a mod's bundled zh_cn file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from mc_zh_tw_translator.translator import s2tw


LATIN_RE = re.compile(r"[A-Za-z]{3,}")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
SIGNATURE_RE = re.compile(r"^META-INF/[^/]+\.(?:SF|RSA|DSA|EC)$", re.I)


def load(archive: zipfile.ZipFile, name: str) -> dict:
    if name not in archive.namelist():
        return {}
    try:
        value = json.loads(archive.read(name).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def needs_repair(en_value: object, zh_value: object) -> bool:
    if zh_value is None:
        return True
    if not isinstance(en_value, str) or not isinstance(zh_value, str):
        return False
    en = en_value.strip()
    zh = zh_value.strip()
    return bool(LATIN_RE.search(en)) and (
        en == zh or (LATIN_RE.search(zh) and not CJK_RE.search(zh) and len(zh) > 3)
    )


def repair(jar: Path) -> list[tuple[str, str, str]]:
    changes = []
    replacements: dict[str, bytes] = {}
    with zipfile.ZipFile(jar, "r") as archive:
        names = set(archive.namelist())
        for en_name in sorted(names):
            if not en_name.startswith("assets/") or not en_name.endswith("/lang/en_us.json"):
                continue
            base = en_name[:-10]
            cn_name = base + "zh_cn.json"
            tw_name = base + "zh_tw.json"
            if cn_name not in names:
                continue
            en_data = load(archive, en_name)
            cn_data = load(archive, cn_name)
            tw_data = load(archive, tw_name)
            changed = False
            for key, en_value in en_data.items():
                cn_value = cn_data.get(key)
                if not isinstance(cn_value, str) or not CJK_RE.search(cn_value):
                    continue
                if cn_value.strip() == str(en_value).strip():
                    continue
                if needs_repair(en_value, tw_data.get(key)):
                    old = tw_data.get(key, "<missing>")
                    new = s2tw(cn_value)
                    tw_data[key] = new
                    changes.append((f"{jar.name}:{key}", str(old), new))
                    changed = True
            if changed:
                replacements[tw_name] = (
                    json.dumps(tw_data, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8")

        if not replacements:
            return []
        fd, temp_name = tempfile.mkstemp(suffix=".jar", dir=jar.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temp_name, "w") as output:
                for item in archive.infolist():
                    if SIGNATURE_RE.match(item.filename):
                        continue
                    if item.filename in replacements:
                        output.writestr(item, replacements.pop(item.filename))
                    else:
                        output.writestr(item, archive.read(item.filename))
                for name, data in replacements.items():
                    output.writestr(name, data)
            archive.close()
            os.replace(temp_name, jar)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mods", type=Path)
    args = parser.parse_args()
    all_changes = []
    for jar in sorted(args.mods.glob("*.jar")):
        all_changes.extend(repair(jar))
    for label, old, new in all_changes:
        print(f"{label}\n  {old!r} -> {new!r}")
    print(f"Repaired {len(all_changes)} values from bundled zh_cn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
