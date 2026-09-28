"""Normalize Simplified Chinese and Mainland terminology in zh_tw resources."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from opencc import OpenCC


SIGNATURE_RE = re.compile(r"^META-INF/[^/]+\.(?:SF|RSA|DSA|EC)$", re.I)
converter = OpenCC("s2twp")

TAIWAN_TERMS = {
    "內存": "記憶體",
    "緩存": "快取",
    "默認": "預設",
    "設置": "設定",
    "視頻": "影片",
    "網絡": "網路",
    "鼠標": "滑鼠",
    "文件夾": "資料夾",
    "文件": "檔案",
    "服務器": "伺服器",
    "加載": "載入",
    "保存": "儲存",
    "創建": "建立",
    "刪除": "刪除",
    "點選": "點擊",
    "屏幕": "螢幕",
    "質量": "品質",
    "優化": "最佳化",
    "激活": "啟用",
    "禁用": "停用",
    "用戶": "使用者",
    "數據": "資料",
    "信息": "資訊",
    "模塊": "模組",
    "反饋": "回饋",
    "打印": "列印",
    "光標": "游標",
    "剪貼板": "剪貼簿",
    "分辨率": "解析度",
    "幀率": "影格率",
    "崩潰": "當機",
    "兼容": "相容",
    "自定義": "自訂",
    "搜索": "搜尋",
    "隊列": "佇列",
    "鏈接": "連結",
    "通過": "透過",
    "獲取": "取得",
    "生成": "產生",
    "概率": "機率",
    "幾率": "機率",
    "等級": "等級",
    "爬行者": "苦力怕",
    "爬山虎": "苦力怕",
    "萬裡": "萬里",
    "冰冰龍鋼": "冰龍鋼",
    "礦石Tnt": "礦石 TNT",
    "打蠟凸凸": "盈凸月",
    "蠟新月": "盈月眉月",
}


def normalize_text(value: str) -> str:
    value = converter.convert(value)
    value = re.sub(r"演{2,}算法", "演算法", value)
    for old, new in TAIWAN_TERMS.items():
        value = value.replace(old, new)
    return value


def normalize_value(value):
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_value(item) for key, item in value.items()}
    return value


def normalize_json(raw: bytes) -> bytes:
    data = json.loads(raw.decode("utf-8-sig"))
    converted = normalize_value(data)
    return (json.dumps(converted, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def normalize_jar(path: Path) -> int:
    replacements = {}
    with zipfile.ZipFile(path, "r") as archive:
        for name in archive.namelist():
            if name.endswith("/lang/zh_tw.json") or "/zh_tw/" in name and name.endswith(".json"):
                try:
                    old = archive.read(name)
                    new = normalize_json(old)
                except Exception:
                    continue
                if new != old:
                    replacements[name] = new
        if not replacements:
            return 0
        fd, temp_name = tempfile.mkstemp(suffix=".jar", dir=path.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temp_name, "w") as output:
                for item in archive.infolist():
                    if SIGNATURE_RE.match(item.filename):
                        continue
                    output.writestr(item, replacements.get(item.filename, archive.read(item.filename)))
            archive.close()
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    return len(replacements)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    changed_jars = changed_entries = changed_files = 0
    for jar in sorted((args.root / "mods").glob("*.jar")):
        count = normalize_jar(jar)
        if count:
            changed_jars += 1
            changed_entries += count
    kubejs_root = args.root / "kubejs"
    for path in sorted(kubejs_root.rglob("*")):
        relative_parts = tuple(part.lower() for part in path.relative_to(kubejs_root).parts)
        is_zh_tw = path.name.lower() == "zh_tw.json" or "zh_tw" in relative_parts[:-1]
        if not path.is_file() or not is_zh_tw:
            continue
        try:
            old = path.read_bytes()
            if path.suffix.lower() == ".json":
                new = normalize_json(old)
            elif path.suffix.lower() == ".txt":
                new = normalize_text(old.decode("utf-8-sig")).encode("utf-8")
            else:
                continue
        except Exception:
            continue
        if new != old:
            path.write_bytes(new)
            changed_files += 1
    print(f"Changed JARs: {changed_jars}")
    print(f"Changed JAR resources: {changed_entries}")
    print(f"Changed KubeJS files: {changed_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
