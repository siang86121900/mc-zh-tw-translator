from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path, PurePosixPath


def is_lang_json(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) >= 4 and parts[0] == "assets" and parts[-2] == "lang" and parts[-1] == "zh_tw.json"


def merge_json(store: dict[str, bytes], path: str, raw: bytes) -> None:
    incoming = json.loads(raw.decode("utf-8-sig"))
    current = json.loads(store[path].decode("utf-8")) if path in store else {}
    if not isinstance(current, dict) or not isinstance(incoming, dict):
        raise ValueError(f"Language file must contain a JSON object: {path}")
    current.update(incoming)
    store[path] = (json.dumps(current, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def collect_changed_jar_assets(original: Path, translated: Path, store: dict[str, bytes]) -> tuple[int, int]:
    added = merged = 0
    with zipfile.ZipFile(original) as before, zipfile.ZipFile(translated) as after:
        before_names = set(before.namelist())
        for name in after.namelist():
            if name.endswith("/") or not name.startswith("assets/"):
                continue
            raw = after.read(name)
            if name in before_names and before.read(name) == raw:
                continue
            if is_lang_json(name):
                merge_json(store, name, raw)
                merged += 1
            else:
                store[name] = raw
                added += 1
    return added, merged


def collect_changed_kubejs_assets(original: Path, translated: Path, store: dict[str, bytes]) -> tuple[int, int]:
    added = merged = 0
    if not translated.exists():
        return added, merged
    for path in translated.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(translated).as_posix()
        original_file = original / relative
        raw = path.read_bytes()
        if original_file.exists() and original_file.read_bytes() == raw:
            continue
        archive_path = f"assets/{relative}"
        if is_lang_json(archive_path):
            merge_json(store, archive_path, raw)
            merged += 1
        else:
            store[archive_path] = raw
            added += 1
    return added, merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a zh_tw resource pack from translated mod JARs.")
    parser.add_argument("--original-mods", type=Path, required=True)
    parser.add_argument("--translated-mods", type=Path, required=True)
    parser.add_argument("--original-kubejs-assets", type=Path)
    parser.add_argument("--translated-kubejs-assets", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    files: dict[str, bytes] = {}
    changed = merged = jars = 0
    for translated in sorted(args.translated_mods.glob("*.jar")):
        original = args.original_mods / translated.name
        if not original.exists():
            continue
        jar_changed, jar_merged = collect_changed_jar_assets(original, translated, files)
        changed += jar_changed
        merged += jar_merged
        jars += 1

    if args.original_kubejs_assets and args.translated_kubejs_assets:
        kube_changed, kube_merged = collect_changed_kubejs_assets(
            args.original_kubejs_assets, args.translated_kubejs_assets, files
        )
        changed += kube_changed
        merged += kube_merged

    pack_meta = {
        "pack": {
            "pack_format": 15,
            "description": "BeLoong 繁體中文翻譯包（Minecraft 1.21.1）",
        }
    }
    files["pack.mcmeta"] = (json.dumps(pack_meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)

    print(f"Scanned JARs: {jars}")
    print(f"Changed non-language assets: {changed}")
    print(f"Merged language sources: {merged}")
    print(f"Resource-pack files: {len(files)}")
    print(f"Created: {args.output}")


if __name__ == "__main__":
    main()
