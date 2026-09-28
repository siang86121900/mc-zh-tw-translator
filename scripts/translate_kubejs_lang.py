"""Recursively fill KubeJS zh_tw language files from en_us/zh_cn sources."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from mc_zh_tw_translator.translator import (
    CTE2QuestTranslator,
    OPENCC_AVAILABLE,
    s2tw,
)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", choices=["none"], default="none")
    args = parser.parse_args()

    if args.output.exists():
        shutil.copytree(args.source, args.output, dirs_exist_ok=True)
    else:
        shutil.copytree(args.source, args.output)

    translator = CTE2QuestTranslator(engine=args.engine)
    en_files = sorted(args.source.glob("assets/*/lang/en_us.json"))
    print(f"Found {len(en_files)} KubeJS en_us language files")

    for index, en_path in enumerate(en_files, 1):
        relative = en_path.relative_to(args.source)
        out_lang = args.output / relative.parent
        zh_tw_path = out_lang / "zh_tw.json"
        zh_cn_path = args.source / relative.parent / "zh_cn.json"
        en_data = load_json(en_path)
        existing = load_json(zh_tw_path)

        if OPENCC_AVAILABLE:
            for key, value in load_json(zh_cn_path).items():
                if key not in existing and isinstance(value, str):
                    existing[key] = s2tw(value)

        print(f"[{index}/{len(en_files)}] {relative.parent.parent.name}")
        translated = translator.translate_lang_data(en_data, existing)
        out_lang.mkdir(parents=True, exist_ok=True)
        with zh_tw_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(translated, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    translator._save_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
