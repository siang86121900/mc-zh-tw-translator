from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

from opencc import OpenCC


PLACEHOLDER_RE = re.compile(r"(?:%\d+\$[a-zA-Z]|%[a-zA-Z]|\{\d+\})")
FORMAT_RE = re.compile(r"§[0-9a-fk-orA-FK-OR]")
PLAYER_KEY_RE = re.compile(
    r"(?:dragon_species|itemGroup|item_group|\.title$|\.name$|^item\.|^block\.|^entity\.|^biome\.|tooltip|description|\.desc$)",
    re.I,
)


def language_identity(path: str) -> tuple[str, str] | None:
    parts = PurePosixPath(path).parts
    if len(parts) < 4 or parts[0] != "assets" or parts[-2] != "lang" or not parts[-1].endswith(".json"):
        return None
    return parts[1], parts[-1][:-5]


def load_jar_languages(root: Path, catalog: dict[tuple[str, str], dict[str, str]]) -> None:
    for jar in sorted(root.glob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as archive:
                for name in archive.namelist():
                    identity = language_identity(name)
                    if not identity or identity[1] not in {"en_us", "zh_cn"}:
                        continue
                    try:
                        data = json.loads(archive.read(name).decode("utf-8-sig"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if isinstance(data, dict):
                        catalog[identity].update({str(k): str(v) for k, v in data.items()})
        except zipfile.BadZipFile:
            continue


def load_kubejs_languages(root: Path, catalog: dict[tuple[str, str], dict[str, str]]) -> None:
    if not root.exists():
        return
    for path in root.glob("*/lang/*.json"):
        namespace = path.parts[-3]
        locale = path.stem
        if locale not in {"en_us", "zh_cn"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            catalog[(namespace, locale)].update({str(k): str(v) for k, v in data.items()})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource-pack", type=Path, required=True)
    parser.add_argument("--original-mods", type=Path, required=True)
    parser.add_argument("--original-kubejs-assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    load_jar_languages(args.original_mods, source)
    load_kubejs_languages(args.original_kubejs_assets, source)
    converter = OpenCC("s2twp")

    rows: list[dict[str, object]] = []
    stats = defaultdict(int)
    with zipfile.ZipFile(args.resource_pack) as archive:
        for name in archive.namelist():
            identity = language_identity(name)
            if not identity or identity[1] != "zh_tw":
                continue
            namespace = identity[0]
            data = json.loads(archive.read(name).decode("utf-8-sig"))
            for key, tw_value in data.items():
                tw = str(tw_value)
                en = source[(namespace, "en_us")].get(key)
                cn = source[(namespace, "zh_cn")].get(key)
                stats["total"] += 1
                if en is not None:
                    stats["with_en"] += 1
                if cn is not None:
                    stats["with_cn"] += 1
                converted = converter.convert(cn) if cn is not None else None
                differs = converted is not None and converted != tw
                placeholder_bad = en is not None and sorted(PLACEHOLDER_RE.findall(en)) != sorted(PLACEHOLDER_RE.findall(tw))
                format_differs = en is not None and sorted(x.lower() for x in FORMAT_RE.findall(en)) != sorted(x.lower() for x in FORMAT_RE.findall(tw))
                if differs:
                    stats["differs_from_cn"] += 1
                if placeholder_bad:
                    stats["placeholder_mismatch"] += 1
                if format_differs:
                    stats["format_code_difference"] += 1
                if differs or placeholder_bad:
                    rows.append(
                        {
                            "namespace": namespace,
                            "key": key,
                            "english": en,
                            "zh_cn": cn,
                            "zh_cn_to_tw": converted,
                            "current_zh_tw": tw,
                            "player_visible_key": bool(PLAYER_KEY_RE.search(key)),
                            "placeholder_mismatch": placeholder_bad,
                            "format_code_difference": format_differs,
                        }
                    )

    rows.sort(key=lambda row: (not row["placeholder_mismatch"], not row["player_visible_key"], row["namespace"], row["key"]))
    payload = {"stats": dict(stats), "differences": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(stats), ensure_ascii=False))
    print(f"Report rows: {len(rows)}")
    print(f"Created: {args.output}")


if __name__ == "__main__":
    main()
