from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from opencc import OpenCC


CORRECTIONS = {
    "鼠標": "滑鼠",
    "鼠標鍵": "滑鼠按鍵",
    "視頻": "影片",
    "信息": "資訊",
    "默認": "預設",
    "保存": "儲存",
    "加載": "載入",
    "服務器": "伺服器",
    "文件夾": "資料夾",
    "文件": "檔案",
    "屏幕": "畫面",
    "在線": "線上",
    "模組包": "整合包",
    "模塊": "模組",
    "爬行者": "苦力怕",
    "爬山虎": "苦力怕",
    "萬裡": "萬里",
}


KONKRETE_ZH_TW = """general.width = 寬度
general.height = 高度
general.on = 開啟
general.off = 關閉

popup.done = 完成

popup.yesno.confirm = 確認
popup.yesno.cancel = 取消

popup.notification.accept = 接受

popup.choosefile.back = 返回
popup.choosefile.title = 選擇檔案
popup.choosefile.choose = 選擇
popup.choosefile.supported = 支援的檔案類型：

configscreen.boolean.enabled = 已啟用
configscreen.boolean.disabled = 已停用
"""


def convert(text: str, converter: OpenCC) -> str:
    text = converter.convert(text)
    for source, target in CORRECTIONS.items():
        text = text.replace(source, target)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    shutil.copytree(args.source, args.destination, dirs_exist_ok=True)

    converter = OpenCC("s2twp")
    converted = 0
    for source_file in args.destination.rglob("zh_cn.*"):
        target_file = source_file.with_name(source_file.name.replace("zh_cn.", "zh_tw.", 1))
        text = source_file.read_text(encoding="utf-8-sig")
        target_file.write_text(convert(text, converter), encoding="utf-8", newline="\n")
        converted += 1

    konkrete = args.destination / "konkrete" / "locals" / "zh_tw.local"
    konkrete.parent.mkdir(parents=True, exist_ok=True)
    konkrete.write_text(KONKRETE_ZH_TW, encoding="utf-8", newline="\n")

    json_files = list(args.destination.rglob("zh_tw.json"))
    for json_file in json_files:
        json.loads(json_file.read_text(encoding="utf-8-sig"))

    print(f"Copied config to: {args.destination}")
    print(f"Converted zh_cn files: {converted}")
    print(f"Validated zh_tw JSON files: {len(json_files)}")
    print(f"Created: {konkrete}")


if __name__ == "__main__":
    main()
