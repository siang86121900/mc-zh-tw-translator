from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


PLACEHOLDER_RE = re.compile(r"(?:%\d+\$[a-zA-Z]|%[a-zA-Z]|\{\d+\})")
SPECIES_NAME_RE = re.compile(r"^dragon_species\.dragonsurvival\.[^.]+$")
AUTHOR_CN_NAMESPACES = {
    "crystcursed_dragon",
    "ds_aether_addon",
    "eternal_starlight",
    "frostfire_dragon",
    "icedragon",
    "star_dragon",
    "wing_kirin",
}


def placeholders(text: str | None) -> list[str]:
    return sorted(PLACEHOLDER_RE.findall(text or ""))


def placeholder_types(text: str | None) -> list[str]:
    return sorted(token[-1] for token in placeholders(text))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("kubejs_assets", type=Path)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    patches: dict[str, dict[str, str]] = defaultdict(dict)
    reasons = defaultdict(int)

    for row in report["differences"]:
        en = row.get("english")
        cn_tw = row.get("zh_cn_to_tw")
        current = row.get("current_zh_tw")
        if not cn_tw:
            continue

        reason = None
        if row["namespace"] in AUTHOR_CN_NAMESPACES:
            reason = "dragon_addon_from_author_zh_cn"
        elif SPECIES_NAME_RE.fullmatch(row["key"]):
            reason = "species_name_from_author_zh_cn"
        elif en and "Creeper" in en and ("爬行者" in current or "爬山虎" in current):
            cn_tw = current.replace("爬行者", "苦力怕").replace("爬山虎", "苦力怕")
            reason = "minecraft_creeper_term"
        elif row["namespace"] == "iceandfire" and "冰冰龍鋼" in current:
            cn_tw = current.replace("冰冰龍鋼", "冰龍鋼")
            reason = "ice_dragonsteel_term"
        elif row["key"] == "tooltip.see_more" and current == "轉移更多...":
            cn_tw = "按住 SHIFT 顯示更多……"
            reason = "shift_key_term"
        elif row.get("placeholder_mismatch") and placeholder_types(en) == placeholder_types(cn_tw):
            reason = "restore_placeholders"
        elif placeholder_types(en) == ["s", "s"] and placeholder_types(current) == ["s"]:
            cn_tw = current.replace("%s", "%s%s", 1)
            reason = "restore_second_string_placeholder"
        elif en is not None and current == en and cn_tw != en:
            reason = "replace_untranslated_english"

        if reason:
            patches[row["namespace"]][row["key"]] = cn_tw
            reasons[reason] += 1

    for namespace, values in patches.items():
        target = args.kubejs_assets / namespace / "lang" / "zh_tw.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8-sig"))
        else:
            data = {}
        data.update(values)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(dict(reasons), ensure_ascii=False))
    print(f"Namespaces patched: {len(patches)}")
    print(f"Keys patched: {sum(len(values) for values in patches.values())}")


if __name__ == "__main__":
    main()
