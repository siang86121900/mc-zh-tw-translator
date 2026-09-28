from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root

    source_files: list[Path] = []
    for base in (root / "config" / "ftbquests", root / "kubejs" / "data"):
        if base.exists():
            source_files.extend(path for path in base.rglob("*") if path.is_file())

    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in source_files
    )
    references = sorted(
        set(re.findall(r'kubejs:([a-z0-9_]+)(?![a-z0-9_./-])', source_text))
    )

    startup_dir = root / "kubejs" / "startup_scripts"
    startup_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in startup_dir.rglob("*.js")
    )
    registrations = set(
        re.findall(r"event\.create\(['\"](?:kubejs:)?([a-z0-9_]+)", startup_text)
    )

    texture_dir = root / "kubejs" / "assets" / "kubejs" / "textures" / "item"
    lang_path = root / "kubejs" / "assets" / "kubejs" / "lang" / "zh_tw.json"
    language = json.loads(lang_path.read_text(encoding="utf-8"))

    rows = []
    for item_id in references:
        row = {
            "id": f"kubejs:{item_id}",
            "registered": item_id in registrations,
            "texture": (texture_dir / f"{item_id}.png").exists(),
            "zh_tw": f"item.kubejs.{item_id}" in language,
        }
        rows.append(row)

    report = {
        "referenced_items": len(references),
        "registered_items": len(registrations),
        "problems": [
            row
            for row in rows
            if not row["registered"] or not row["texture"] or not row["zh_tw"]
        ],
        "items": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
