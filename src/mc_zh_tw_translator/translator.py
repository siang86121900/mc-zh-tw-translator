"""

翻譯來源優先順序（完全免費、禁止外部翻譯 API）：
  1. JAR 內現有 zh_tw（直接保留）
  2. 同檔案同 namespace 的 zh_cn（s2twp 轉繁並校驗格式）
  3. ref_pack.json／CFPA（依 namespace 參考庫）
  4. 翻譯記憶 translation_cache.json
  5. Minecraft 專用詞彙表
  6. 找不到來源：保留原文並列入待查

Patchouli 書本翻譯（新增）：
  - 偵測 JAR 內 patchouli_books/.../en_us/ 資料夾
  - 對應建立 zh_tw/ 資料夾
  - 跳過 template/ 資料夾內的 JSON
  - 翻譯欄位：name, text, title, landing_text
  - 優先用同層 zh_cn/ 的內容 opencc 轉繁體，沒有就保留原文並列入待查

依賴：pip install requests opencc-python-reimplemented
"""

import re
import json
import time
import requests
import zipfile
import threading
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"

# opencc 選用性載入（簡中→繁中）
try:
    import opencc
    _opencc_converter = opencc.OpenCC('s2twp')
    OPENCC_AVAILABLE = True
except ImportError:
    _opencc_converter = None
    OPENCC_AVAILABLE = False

def s2tw(text: str) -> str:
    """簡體轉繁體台灣用語，opencc 未安裝時原樣返回"""
    if OPENCC_AVAILABLE and _opencc_converter:
        return _opencc_converter.convert(text)
    return text

def is_jar_signature_file(path: str) -> bool:
    return re.match(r'^META-INF/[^/]+\.(SF|RSA|DSA|EC)$', path, re.IGNORECASE) is not None

# =============================================================================
# Minecraft 專用詞彙表
# =============================================================================
MINECRAFT_GLOSSARY = {
    "shift": "Shift", "ctrl": "Ctrl", "control": "Ctrl",
    "health": "生命值", "mana": "魔力", "stamina": "耐力", "durability": "耐久度",
    "experience": "經驗值", "level": "等級", "damage": "傷害", "armor": "盔甲",
    "attack speed": "攻擊速度", "attack damage": "攻擊傷害", "knockback": "擊退",
    "enchantment": "附魔", "enchanted": "已附魔",
    "crafting": "合成", "smelting": "冶煉", "brewing": "釀造",
    "inventory": "物品欄", "hotbar": "快捷欄", "chest": "儲物箱",
    "furnace": "熔爐", "workbench": "工作台", "crafting table": "工作台",
    "anvil": "鐵砧", "enchanting table": "附魔台", "beacon": "烽火台",
    "respawn": "重生", "spawn": "生成", "despawn": "消失",
    "mob": "生物", "hostile": "敵對", "passive": "被動", "neutral": "中立",
    "biome": "生態域", "dimension": "維度", "realm": "領域",
    "overworld": "主世界", "nether": "地獄", "end": "終界",
    "portal": "傳送門", "waypoint": "路點",
    "sword": "劍", "axe": "斧頭", "pickaxe": "鎬", "shovel": "鏟子",
    "hoe": "鋤頭", "bow": "弓", "crossbow": "弩", "trident": "三叉戟",
    "shield": "盾牌", "helmet": "頭盔", "chestplate": "胸甲",
    "leggings": "護腿", "boots": "靴子",
    "potion": "藥水", "arrow": "箭矢", "food": "食物", "seed": "種子",
    "ore": "礦石", "ingot": "錠", "gem": "寶石", "crystal": "水晶",
    "dust": "粉末", "shard": "碎片", "fragment": "碎塊",
    "log": "原木", "plank": "木板", "slab": "半磚", "stairs": "階梯",
    "stone": "石頭", "cobblestone": "鵝卵石", "gravel": "礫石", "sand": "沙",
    "soul sand": "靈魂砂", "netherrack": "地獄石", "obsidian": "黑曜石",
    "bedrock": "基岩", "dirt": "泥土", "grass": "草",
    "coal": "煤炭", "iron": "鐵", "gold": "金", "diamond": "鑽石",
    "emerald": "綠寶石", "lapis": "青金石", "redstone": "紅石",
    "quartz": "石英", "netherite": "下界合金", "copper": "銅",
    "amethyst": "紫水晶", "ancient debris": "遠古遺骸",
    "zombie": "殭屍", "skeleton": "骷髏", "creeper": "苦力怕",
    "spider": "蜘蛛", "enderman": "終界使者", "witch": "女巫",
    "blaze": "烈焰使者", "ghast": "地獄幽靈", "slime": "史萊姆",
    "dragon": "龍", "ender dragon": "終界龍", "wither": "凋零",
    "warden": "伏守者", "pillager": "掠奪者", "ravager": "劫毀獸",
    "villager": "村民", "golem": "傀儡", "iron golem": "鐵魔像",
    "wolf": "狼", "cat": "貓", "horse": "馬", "pig": "豬",
    "cow": "牛", "sheep": "綿羊", "chicken": "雞", "bee": "蜜蜂",
    "poison": "劇毒", "blindness": "失明", "slowness": "緩速",
    "weakness": "虛弱", "mining fatigue": "挖掘疲勞", "strength": "力量",
    "speed": "加速", "haste": "挖掘加速", "regeneration": "回復",
    "resistance": "抗性", "fire resistance": "抗火",
    "water breathing": "水下呼吸", "night vision": "夜視",
    "invisibility": "隱形", "levitation": "懸浮",
    "quest": "任務", "objective": "目標", "reward": "獎勵",
    "complete": "完成", "unlock": "解鎖", "requirement": "需求",
    "optional": "選擇性", "main": "主線", "side": "支線",
    "chapter": "章節", "challenge": "挑戰",
    "tier": "階級", "rank": "等階", "upgrade": "升級",
    "recipe": "配方", "material": "材料", "component": "零件",
    "energy": "能量", "rf": "RF能量", "fe": "FE能量",
    "fluid": "流體", "pipe": "管道", "cable": "電纜",
    "machine": "機器", "generator": "發電機", "battery": "電池",
    "storage": "儲存", "tank": "儲液罐", "filter": "過濾器",
}

# =============================================================================
# Patchouli 書本翻譯設定
# =============================================================================

# 需要翻譯的欄位
PATCHOULI_TRANSLATE_FIELDS = {"name", "text", "title", "landing_text", "header", "subtitle", "description"}

# 結構性欄位，不翻譯
PATCHOULI_SKIP_FIELDS = {
    "type", "icon", "category", "image", "flag",
    "advancement", "trigger", "id", "link", "anchor",
    "pattern", "key", "recipe", "input", "output",
    "entity", "offset", "rotate", "default_rotation",
    "book_texture", "filler_texture", "crafting_texture",
    "model", "header_color", "nameplate_color", "link_color",
    "link_hover_color", "progress_bar_color", "progress_bar_background",
    "open_sound", "flip_sound", "index_icon", "item", "stack",
    "extra_recipe_mappings", "tag", "read_by_default", "show_progress",
    "custom_book_item", "use_blocky_font", "i18n", "creative_tab",
    "sort_num", "mail_key", "priority",
    "entries", "relations", "link", "links",
}

# =============================================================================
# 參考庫
# =============================================================================

CFPA_URL = "https://github.com/CFPAOrg/Minecraft-Mod-Language-Package/releases/latest/download/Minecraft-Mod-Language-Modpack-1-20.zip"

class ReferencePackDB:
    def __init__(self, base_dir: Optional[str | Path] = None):
        self.key_db: dict[str, str] = {}
        self._base_dir = Path(base_dir) if base_dir else DEFAULT_DATA_DIR

    def load_all(self):
        self._refresh_latest()
        ref = self._base_dir / 'ref_pack_scoped.json'
        cfpa = self._base_dir / 'cfpa_scoped.json'
        if ref.exists() and cfpa.exists():
            self.scoped_db = json.loads(cfpa.read_text(encoding='utf-8'))
            for namespace, values in json.loads(ref.read_text(encoding='utf-8')).items():
                self.scoped_db.setdefault(namespace, {}).update(values)
            self.namespace = ''
            print(f"  [參考庫] 已載入 namespace 參考庫：{sum(map(len, self.scoped_db.values()))} 條")
            return
        self._load_ref_pack()
        self._load_cfpa()

    def _refresh_latest(self) -> None:
        """每次翻譯前更新兩個外部參考庫；失敗時保留快取但明確告警。"""
        update_script = PACKAGE_ROOT / "scripts" / "update_references_current.py"
        if self._base_dir.resolve() != DEFAULT_DATA_DIR.resolve() or not update_script.exists():
            print("  [參考庫] 非預設資料目錄，跳過自動更新；請手動執行 scripts/update_references_current.py")
            return
        print("  [參考庫] 每次翻譯前更新 ModsTranslationPack／CFPA ...")
        try:
            proc = subprocess.run(
                [sys.executable, str(update_script)],
                cwd=str(PACKAGE_ROOT), text=True, encoding="utf-8",
                errors="replace", capture_output=True, timeout=600,
            )
            if proc.returncode != 0:
                detail = (proc.stdout + proc.stderr).strip().splitlines()[-1:]
                print(f"  [參考庫] 更新失敗，使用既有快取：{' '.join(detail)}")
            else:
                print("  [參考庫] 已完成最新資料更新")
        except Exception as exc:
            print(f"  [參考庫] 更新失敗，使用既有快取：{exc}")

    def _load_ref_pack(self):
        path = self._base_dir / "ref_pack.json"
        if not path.exists():
            print("  [參考庫] 找不到 ref_pack.json")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.key_db.update(data)
            print(f"  [參考庫] ref_pack.json：{len(data)} 條（繁體）")
        except Exception as e:
            print(f"  [參考庫] 載入 ref_pack.json 失敗: {e}")

    def _get_latest_cfpa_tag(self) -> str:
        try:
            resp = requests.get(
                "https://api.github.com/repos/CFPAOrg/Minecraft-Mod-Language-Package/releases/latest",
                timeout=10, headers={"Accept": "application/vnd.github+json"}
            )
            if resp.ok:
                return resp.json().get("tag_name", "")
        except Exception:
            pass
        return ""

    @staticmethod
    def _tag_to_date(tag: str) -> str:
        if "Snapshot-" in tag:
            d = tag.replace("Snapshot-", "")
            if len(d) >= 8:
                return f"{d[:4]}/{d[4:6]}/{d[6:8]}"
        return tag

    def _load_cfpa(self):
        cache_path   = self._base_dir / "cfpa_cache.json"
        zip_path     = self._base_dir / "cfpa_zh_cn.zip"
        version_path = self._base_dir / "cfpa_version.txt"

        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                added = self._merge_cfpa(data)

                local_tag = ""
                if version_path.exists():
                    local_tag = version_path.read_text(encoding='utf-8').strip()
                local_date = self._tag_to_date(local_tag) if local_tag else "未知"

                print(f"  [CFPA] 已載入快取：{len(data)} 條，新增 {added} 條（簡中→繁體）")
                print(f"  [CFPA] 目前版本：{local_date}")

                if not OPENCC_AVAILABLE:
                    return

                print("  [CFPA] 查詢最新版本中...", end='', flush=True)
                latest_tag = self._get_latest_cfpa_tag()
                if not latest_tag:
                    print(" 無法連線，跳過檢查")
                    return

                latest_date = self._tag_to_date(latest_tag)
                if latest_tag == local_tag:
                    print(f" 已是最新（{latest_date}）")
                    return

                print(f" 有新版！")
                print(f"  [CFPA] 新版本：{latest_date}（目前：{local_date}）")
                choice = input("  是否更新？更新後快取自動重建 (y/n，預設 n): ").strip().lower()
                if choice != 'y':
                    print("  跳過更新")
                    return

                cache_path.unlink(missing_ok=True)
                if zip_path.exists():
                    zip_path.unlink()
                self._download_and_build_cache(zip_path, cache_path, version_path, latest_tag)
                return

            except Exception as e:
                print(f"  [CFPA] 快取讀取失敗，重新轉換: {e}")

        if zip_path.exists():
            self._convert_and_cache_cfpa(zip_path, cache_path, version_path, tag="manual")
            return

        if not OPENCC_AVAILABLE:
            print("  [CFPA] 需要 opencc 才能使用 CFPA 翻譯包：")
            print("         pip install opencc-python-reimplemented")
            return

        print("  [CFPA] 查詢最新版本中...", end='', flush=True)
        latest_tag = self._get_latest_cfpa_tag()
        latest_date = self._tag_to_date(latest_tag) if latest_tag else "未知"
        print(f" {latest_date}")

        print(f"\n  [CFPA] 找不到 CFPA 翻譯包（約 100MB，涵蓋大量模組的簡中翻譯）")
        print(f"  最新版本：{latest_date}")
        print(f"  下載後轉成繁體並永久快取，之後啟動秒速載入，有新版會提示更新")
        choice = input("  是否自動下載？(y/n，預設 n): ").strip().lower()
        if choice != 'y':
            print("  跳過下載")
            return

        self._download_and_build_cache(zip_path, cache_path, version_path, latest_tag)

    def _download_and_build_cache(self, zip_path, cache_path, version_path, tag):
        print(f"  下載中：{CFPA_URL}")
        print("  （約 100MB，可能需要幾分鐘）")
        try:
            resp = requests.get(CFPA_URL, stream=True, timeout=300)
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            downloaded = 0
            with open(zip_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded / total * 100
                        print(f"\r  進度: {pct:.0f}%  ({downloaded//1024//1024}MB / {total//1024//1024}MB)",
                              end='', flush=True)
            print()
            self._convert_and_cache_cfpa(zip_path, cache_path, version_path, tag)
        except Exception as e:
            print(f"  下載失敗: {e}")

    def _convert_and_cache_cfpa(self, zip_path, cache_path, version_path=None, tag=""):
        if not OPENCC_AVAILABLE:
            print("  [CFPA] 需要 opencc 才能轉換：pip install opencc-python-reimplemented")
            return
        print(f"  [CFPA] 轉換 {zip_path.name} 中...")
        converted = {}
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                cn_files = [f for f in z.namelist()
                            if f.endswith('lang/zh_cn.json') or f.endswith('lang/zh_CN.json')]
                print(f"  找到 {len(cn_files)} 個 zh_cn.json")
                for i, f in enumerate(cn_files, 1):
                    try:
                        data = json.loads(z.read(f).decode('utf-8'))
                        for k, v in data.items():
                            if isinstance(v, str) and v.strip() and not k.startswith('_'):
                                converted[k] = s2tw(v)
                    except Exception:
                        pass
                    if i % 100 == 0 or i == len(cn_files):
                        print(f"\r  進度: {i}/{len(cn_files)}", end='', flush=True)
            print()
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(converted, f, ensure_ascii=False, separators=(',', ':'))
            if version_path and tag:
                version_path.write_text(tag, encoding='utf-8')
            added = self._merge_cfpa(converted)
            date_str = self._tag_to_date(tag) if tag and tag != "manual" else tag
            print(f"  [CFPA] 轉換完成：{len(converted)} 條，新增 {added} 條，版本 {date_str}")
        except Exception as e:
            print(f"  [CFPA] 轉換失敗: {e}")

    def _merge_cfpa(self, data: dict) -> int:
        added = 0
        for k, v in data.items():
            if k not in self.key_db:
                self.key_db[k] = v
                added += 1
        return added

    def lookup(self, key: str) -> Optional[str]:
        if hasattr(self, 'scoped_db'):
            return self.scoped_db.get(self.namespace, {}).get(key)
        return self.key_db.get(key)

    def set_namespace(self, namespace: str):
        self.namespace = namespace

    @property
    def is_loaded(self) -> bool:
        return bool(getattr(self, 'scoped_db', self.key_db))

    def stats(self) -> str:
        if hasattr(self, 'scoped_db'):
            return f"{sum(map(len, self.scoped_db.values()))} 條（依 namespace）"
        return f"{len(self.key_db)} 條"

# =============================================================================
# 翻譯引擎
# =============================================================================

class TranslationEngine:
    """免費模式佔位引擎；正式翻譯不得呼叫外部翻譯 API。"""

    def __init__(self, engine: str = "none"):
        if engine != "none":
            raise ValueError("本工具已停用所有外部翻譯 API；只能使用 engine=none")
        self.engine = "none"

    def translate(self, text: str) -> str:
        raise Exception("未啟用翻譯 API；找不到免費來源的文字會保留原文並列入待審")

# =============================================================================
# 主翻譯器
# =============================================================================

class CTE2QuestTranslator:
    def __init__(self, max_workers: int = 5, engine: str = "none",
                 data_dir: Optional[str | Path] = None):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.translation_cache: dict[str, str] = {}
        # 自動快取只是候選，不得直接凌駕可信參考庫。
        self.approved_memory: dict[str, str] = {}
        self.source_counts: dict[str, int] = {}
        self.cache_file = self.data_dir / "translation_cache.json"
        self.approved_memory_file = self.data_dir / "approved_translation_memory.json"
        self.cache_lock = threading.Lock()
        self.max_workers = max_workers
        self.engine_obj = TranslationEngine(engine)

        print("\n初始化參考庫...")
        if not OPENCC_AVAILABLE:
            print("  提示：安裝 opencc 可支援 CFPA 簡中包自動轉繁體")
            print("        pip install opencc-python-reimplemented")
        self.ref_db = ReferencePackDB(self.data_dir)
        self.ref_db.load_all()
        print(f"  參考庫就緒：{self.ref_db.stats()}")

        self._load_cache()
        self._load_approved_memory()

    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.translation_cache = json.load(f)
                print(f"已載入翻譯快取：{len(self.translation_cache)} 條")
            except Exception as e:
                print(f"載入快取失敗: {e}")

    def _load_approved_memory(self):
        if not self.approved_memory_file.exists():
            print("已確認翻譯記憶：0 條（自動快取不會直接採用）")
            return
        try:
            with self.approved_memory_file.open('r', encoding='utf-8') as f:
                self.approved_memory = json.load(f)
            print(f"已確認翻譯記憶：{len(self.approved_memory)} 條")
        except Exception as e:
            print(f"載入已確認翻譯記憶失敗: {e}")

    def _save_cache(self):
        try:
            with self.cache_lock:
                tmp_file = self.cache_file.with_suffix(self.cache_file.suffix + ".tmp")
                with open(tmp_file, 'w', encoding='utf-8') as f:
                    json.dump(self.translation_cache, f, ensure_ascii=False, indent=2)
                tmp_file.replace(self.cache_file)
            print(f"已儲存翻譯快取：{len(self.translation_cache)} 條")
        except Exception as e:
            print(f"儲存快取失敗: {e}")

    # ------------------------------------------------------------------
    # 翻譯核心
    # ------------------------------------------------------------------

    def _count_source(self, source: str, amount: int = 1) -> None:
        self.source_counts[source] = self.source_counts.get(source, 0) + amount

    def _memory_lookup(self, text: str) -> Optional[str]:
        with self.cache_lock:
            value = self.approved_memory.get(text)
        if value is not None and not self.is_untranslated(text, value):
            return value
        return None

    def _glossary_lookup(self, text: str) -> Optional[str]:
        lower = text.strip().lower()
        if lower in MINECRAFT_GLOSSARY:
            return MINECRAFT_GLOSSARY[lower]
        return None

    def translate_text(self, text: str, lang_key: str = "") -> str:
        if not text.strip():
            return text

        if lang_key and self.ref_db.is_loaded:
            ref = self.ref_db.lookup(lang_key)
            if ref and not self.is_untranslated(text, ref):
                with self.cache_lock:
                    self.translation_cache[text] = ref
                return ref

        # 參考庫之後才使用人工確認的翻譯記憶；自動 cache 不在此採用。
        cached = self._memory_lookup(text)
        if cached is not None:
            return cached

        result = self._glossary_lookup(text)
        if result is not None:
            with self.cache_lock:
                self.translation_cache[text] = result
            return result

        # 完全免費模式：沒有可信來源時保留原文，交由報告列為待審。
        self._count_source("untranslated", 1)
        return text

    def _glossary_postprocess(self, en: str, zh: str) -> str:
        # 含佔位符的字串跳過詞彙表後處理，避免 %s/%d 被詞彙替換黏在一起導致格式錯誤
        if re.search(r'%(\d+\$)?[sdfoxXeEgGaAcCbBhH%]', en):
            return zh
        lower_en = en.lower()
        for en_term, zh_term in MINECRAFT_GLOSSARY.items():
            if en_term in lower_en and zh_term not in zh:
                # 只替換獨立單詞（前後是空格、標點或字串邊界）
                zh = re.sub(
                    r'(?<![a-zA-Z])' + re.escape(en_term) + r'(?![a-zA-Z])',
                    zh_term, zh, flags=re.IGNORECASE
                )
        return zh

    # ------------------------------------------------------------------
    # 格式處理
    # ------------------------------------------------------------------

    def clean_for_translation(self, text: str) -> tuple[str, dict]:
        if not text:
            return text, {}
        info = {"tokens": []}
        cleaned = text

        def protect(pattern: str, label: str):
            nonlocal cleaned

            def repl(match):
                token = f"__MC_{label}_{len(info['tokens'])}__"
                info["tokens"].append((token, match.group(0)))
                return token

            cleaned = re.sub(pattern, repl, cleaned)

        protect(r'\{image:[^}]+\}', "IMAGE")
        protect(r'[§&][0-9a-fk-or]', "FMT")
        protect(r'\$\([^)]*\)', "BOOK")
        protect(r'\{[#\w][^{}]*\}', "BRACE")
        protect(r'\n', "NL")
        protect(r'%(\d+\$)?[sdfoxXeEgGaAcCbBhH%]', "PH")

        if not info["tokens"]:
            info.pop("tokens", None)

        return cleaned.strip(), info

    def restore_formatting(self, translated: str, original: str, info: dict) -> str:
        result = translated
        for token, value in info.get("tokens", []):
            result = result.replace(token, value)

        # Some translation APIs may drop leading/trailing formatting tokens.
        # Keep the most important Minecraft style boundaries intact.
        leading_match = re.match(r'^(?:&[0-9a-fk-or])+', original, re.IGNORECASE)
        leading = leading_match.group(0) if leading_match else ""
        if leading and not result.startswith(leading):
            result = leading + result
        if original.endswith('&r') and not result.endswith('&r'):
            result += '&r'
        return result

    def should_translate(self, key: str, value: str) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        skip_keys = [
            r'^comment_id$', r'.*\.id$', r'^id$', r'.*_id$',
            r'^sounds?\.', r'^subtitle\.sounds?\.',
            r'^key\.', r'^commands?\.', r'^argument\.', r'^option\.',
        ]
        for p in skip_keys:
            if re.match(p, key, re.IGNORECASE):
                return False
        skip_values = [
            r'^/.*',                                    # 指令
            r'^https?://',                              # URL
            r'^[A-Z_]+$',                              # 全大寫常數
            r'^\d+$',                                  # 純數字
            r'^[\d.]+$',                               # 小數
            r'^(true|false|null)$',                    # 布林值
            r'^[a-zA-Z0-9_-]+:[a-zA-Z0-9_./-]+$',    # namespace:path 格式
            r'^#[a-zA-Z_]+#$',                        # Patchouli 模板變數（#tier#）
            r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$',  # i18n key（mod.key.subkey）
        ]
        for p in skip_values:
            if re.match(p, value.strip()):
                return False
        return len(re.sub(r'[^a-zA-Z]', '', value)) >= 3

    def is_untranslated(self, en: str, zh: str) -> bool:
        if not isinstance(en, str) or not isinstance(zh, str):
            return False
        return en == zh or (zh and all(ord(c) < 128 for c in zh))

    # ------------------------------------------------------------------
    # SNBT / JSON 處理
    # ------------------------------------------------------------------

    def translate_description_array(self, text: str) -> list:
        originals = [m.group(1) for m in re.finditer(r'"([^"]*)"', text)]

        def do(line):
            if self.should_translate('description', line):
                clean, fmt = self.clean_for_translation(line)
                if clean:
                    return self.restore_formatting(self.translate_text(clean), line, fmt)
            return line

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            results = list(ex.map(do, originals))

        n = sum(1 for o, r in zip(originals, results) if o != r)
        if n:
            print(f"    翻譯了 {n} 行 description")
        return [r.replace('\\', '\\\\').replace('"', '\\"') for r in results]

    def translate_json_value(self, key: str, value: Any, depth: int = 0) -> Any:
        if isinstance(value, str):
            if self.should_translate(key, value):
                clean, fmt = self.clean_for_translation(value)
                if clean:
                    return self.restore_formatting(self.translate_text(clean), value, fmt)
            return value
        elif isinstance(value, dict):
            return {k: self.translate_json_value(k, v, depth+1) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.translate_json_value(f"{key}[{i}]", item, depth+1)
                    for i, item in enumerate(value)]
        return value

    @staticmethod
    def _strip_json_comments(text: str) -> str:
        result = []
        i = 0
        in_string = False
        while i < len(text):
            c = text[i]
            if in_string:
                result.append(c)
                if c == '\\':
                    i += 1
                    if i < len(text):
                        result.append(text[i])
                elif c == '"':
                    in_string = False
                i += 1
                continue
            if c == '"':
                in_string = True
                result.append(c)
                i += 1
                continue
            if c == '/' and i + 1 < len(text) and text[i+1] == '/':
                while i < len(text) and text[i] != '\n':
                    i += 1
                continue
            if c == '/' and i + 1 < len(text) and text[i+1] == '*':
                i += 2
                while i + 1 < len(text) and not (text[i] == '*' and text[i+1] == '/'):
                    i += 1
                i += 2
                continue
            result.append(c)
            i += 1
        return ''.join(result)

    def process_json(self, content: str) -> str:
        try:
            cleaned = self._strip_json_comments(content)
            data = json.loads(cleaned)
            return json.dumps(
                {k: self.translate_json_value(k, v) for k, v in data.items()},
                ensure_ascii=False, indent=2
            )
        except json.JSONDecodeError as e:
            print(f"    JSON 解析錯誤: {e}")
            return content

    def process_snbt(self, content: str) -> str:
        def replace_desc(m):
            lines = self.translate_description_array(m.group(1))
            if lines:
                fmt = '\n'.join(
                    f'\t\t\t\t"{l}"' if i == len(lines)-1 else f'\t\t\t\t"{l}",'
                    for i, l in enumerate(lines)
                )
                return f'description: [\n{fmt}\n\t\t\t]'
            return m.group(0)

        content = re.sub(
            r'description:\s*\[((?:[^\[\]]*?"[^"]*"[^\[\]]*?)*)\]',
            replace_desc, content, flags=re.DOTALL
        )

        for field in ['title', 'subtitle']:
            def replace_field(m, f=field):
                orig = m.group(1)
                if self.should_translate(f, orig):
                    clean, fmt = self.clean_for_translation(orig)
                    if clean:
                        t = self.restore_formatting(self.translate_text(clean), orig, fmt)
                        esc = t.replace('\\', '\\\\').replace('"', '\\"')
                        print(f"    翻譯 {f}: {orig[:30]} -> {t[:30]}")
                        return f'{f}: "{esc}"'
                return m.group(0)
            content = re.sub(rf'{field}:\s*"([^"]*)"', replace_field, content)

        return content

    def process_file(self, path: str) -> str:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        if path.endswith('.json'):
            return self.process_json(content)
        elif path.endswith('.snbt'):
            return self.process_snbt(content)
        return content

    # ------------------------------------------------------------------
    # Patchouli 書本翻譯
    # ------------------------------------------------------------------

    def _translate_patchouli_string(self, value: str, zh_cn_value: str = None) -> str:
        if not value or not value.strip():
            return value
        v = value.strip()
        # Patchouli 模板變數（如 #tier#）直接跳過
        if re.match(r'^#[a-zA-Z_]+#$', v):
            return value
        # i18n key（mod.key.subkey 格式）直接跳過，不翻譯
        if re.match(r'^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$', v):
            return value
        # resource location（namespace:path）直接跳過
        if re.match(r'^[a-zA-Z0-9_-]+:[a-zA-Z0-9_./-]+$', v):
            return value

        if OPENCC_AVAILABLE and zh_cn_value and isinstance(zh_cn_value, str) and zh_cn_value.strip():
            converted = s2tw(zh_cn_value)
            with self.cache_lock:
                self.translation_cache[value] = converted
            return converted

        with self.cache_lock:
            if value in self.translation_cache:
                return self.translation_cache[value]

        clean, fmt = self.clean_for_translation(value)
        if not clean or len(re.sub(r'[^a-zA-Z]', '', clean)) < 3:
            return value
        translated = self.translate_text(clean)
        return self.restore_formatting(translated, value, fmt)

    def _translate_patchouli_node(self, field: str, value: Any, zh_cn_node: Any = None) -> Any:
        if isinstance(value, str):
            if field in PATCHOULI_SKIP_FIELDS:
                return value
            if field not in PATCHOULI_TRANSLATE_FIELDS:
                return value
            zh_str = zh_cn_node if isinstance(zh_cn_node, str) else None
            return self._translate_patchouli_string(value, zh_str)
        elif isinstance(value, dict):
            result = {}
            for k, v in value.items():
                cn_child = zh_cn_node.get(k) if isinstance(zh_cn_node, dict) else None
                result[k] = self._translate_patchouli_node(k, v, cn_child)
            return result
        elif isinstance(value, list):
            result = []
            for i, item in enumerate(value):
                cn_item = zh_cn_node[i] if isinstance(zh_cn_node, list) and i < len(zh_cn_node) else None
                if isinstance(item, str):
                    # resource location（namespace:path）直接保留，不翻譯
                    if re.match(r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', item, re.IGNORECASE):
                        result.append(item)
                    else:
                        result.append(self._translate_patchouli_node("text", item, cn_item))
                else:
                    result.append(self._translate_patchouli_node(field, item, cn_item))
            return result
        return value

    def _translate_patchouli_json(self, content: str, zh_cn_content: str = None) -> str:
        try:
            cleaned = self._strip_json_comments(content)
            en_data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"      JSON 解析錯誤（en）: {e}")
            return content

        zh_cn_data = {}
        if zh_cn_content:
            try:
                zh_cn_data = json.loads(self._strip_json_comments(zh_cn_content))
            except Exception:
                zh_cn_data = {}

        translated = {}
        for k, v in en_data.items():
            cn_val = zh_cn_data.get(k)
            translated[k] = self._translate_patchouli_node(k, v, cn_val)

        return json.dumps(translated, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # TConstruct 書本翻譯
    # ------------------------------------------------------------------

    TCONSTRUCT_TRANSLATE_FIELDS = {"title", "text", "subtitle", "name", "description", "subText", "tooltip", "detailed", "effects", "properties", "block", "entity"}
    TCONSTRUCT_SKIP_FIELDS = {
        "modifier_id", "more_text_space", "tool_filter",
        "icon", "category", "type", "image", "id", "flag",
        "coverTexture", "bookTexture", "coverColor", "arrowColor",
        "slotColor", "drawSectionListText", "centerPageTitles",
        "largePageTitles", "drawFourColumnIndex", "paragraph",
    }

    def _translate_tconstruct_node(self, field: str, value: Any, zh_cn_node: Any = None) -> Any:
        if isinstance(value, str):
            if field in self.TCONSTRUCT_SKIP_FIELDS:
                return value
            if field not in self.TCONSTRUCT_TRANSLATE_FIELDS:
                return value
            zh_str = zh_cn_node if isinstance(zh_cn_node, str) else None
            return self._translate_patchouli_string(value, zh_str)
        elif isinstance(value, dict):
            result = {}
            for k, v in value.items():
                cn_child = zh_cn_node.get(k) if isinstance(zh_cn_node, dict) else None
                result[k] = self._translate_tconstruct_node(k, v, cn_child)
            return result
        elif isinstance(value, list):
            result = []
            for i, item in enumerate(value):
                cn_item = zh_cn_node[i] if isinstance(zh_cn_node, list) and i < len(zh_cn_node) else None
                if isinstance(item, str):
                    if re.match(r'^[a-z0-9_.-]+:[a-z0-9_./-]+$', item, re.IGNORECASE):
                        result.append(item)
                    else:
                        result.append(self._translate_tconstruct_node("text", item, cn_item))
                else:
                    result.append(self._translate_tconstruct_node(field, item, cn_item))
            return result
        return value

    def _translate_tconstruct_json(self, content: str, zh_cn_content: str = None) -> str:
        try:
            en_data = json.loads(self._strip_json_comments(content))
        except json.JSONDecodeError as e:
            print(f"      JSON 解析錯誤: {e}")
            return content

        zh_cn_data = {}
        if zh_cn_content:
            try:
                zh_cn_data = json.loads(self._strip_json_comments(zh_cn_content))
            except Exception:
                zh_cn_data = {}

        translated = {k: self._translate_tconstruct_node(k, v, zh_cn_data.get(k))
                      for k, v in en_data.items()}
        return json.dumps(translated, ensure_ascii=False, indent=2)


    def _merge_tconstruct_with_existing(self, en_content: str, zh_tw_content: str,
                                         zh_cn_content: str = None) -> str:
        """
        已有 zh_tw 的情況下，以 en_us 為基準：
        - en_us 有、zh_tw 也有 → 保留 zh_tw（不重翻）
        - en_us 有、zh_tw 沒有 → 優先使用 zh_cn→opencc，否則保留原文
        - zh_tw 有、en_us 沒有 → 捨棄（避免過時翻譯殘留）
        遞迴處理 dict / list 結構。
        """
        try:
            en_data = json.loads(self._strip_json_comments(en_content))
        except Exception:
            return en_content

        try:
            zh_tw_data = json.loads(self._strip_json_comments(zh_tw_content))
        except Exception:
            zh_tw_data = {}

        zh_cn_data = {}
        if zh_cn_content:
            try:
                zh_cn_data = json.loads(self._strip_json_comments(zh_cn_content))
            except Exception:
                pass

        def merge_node(field, en_val, zh_tw_val, zh_cn_val):
            if isinstance(en_val, str):
                # 已有翻譯且不是原文 → 保留
                if isinstance(zh_tw_val, str) and zh_tw_val.strip() and zh_tw_val != en_val:
                    return zh_tw_val
                # 沒有翻譯 → 補翻
                if field in self.TCONSTRUCT_SKIP_FIELDS:
                    return en_val
                if field not in self.TCONSTRUCT_TRANSLATE_FIELDS:
                    return en_val
                zh_cn_str = zh_cn_val if isinstance(zh_cn_val, str) else None
                return self._translate_patchouli_string(en_val, zh_cn_str)

            elif isinstance(en_val, dict):
                result = {}
                for k, v in en_val.items():
                    tw_child = zh_tw_val.get(k) if isinstance(zh_tw_val, dict) else None
                    cn_child = zh_cn_val.get(k) if isinstance(zh_cn_val, dict) else None
                    result[k] = merge_node(k, v, tw_child, cn_child)
                return result

            elif isinstance(en_val, list):
                result = []
                for i, item in enumerate(en_val):
                    tw_item = zh_tw_val[i] if isinstance(zh_tw_val, list) and i < len(zh_tw_val) else None
                    cn_item = zh_cn_val[i] if isinstance(zh_cn_val, list) and i < len(zh_cn_val) else None
                    if isinstance(item, str):
                        result.append(merge_node("text", item, tw_item, cn_item))
                    else:
                        result.append(merge_node(field, item, tw_item, cn_item))
                return result

            return en_val

        merged = {}
        for k, v in en_data.items():
            merged[k] = merge_node(k, v, zh_tw_data.get(k), zh_cn_data.get(k))

        return json.dumps(merged, ensure_ascii=False, indent=2)

    def _find_tconstruct_books(self, namelist: list[str]) -> dict[str, list[str]]:
        books: dict[str, list[str]] = {}
        pat = re.compile(r'^(assets/[^/]+/(?:.*/)?book/(?:[^/]+/)?en_us)', re.IGNORECASE)
        for fname in namelist:
            if not fname.endswith('.json'):
                continue
            m = pat.match(fname)
            if m:
                books.setdefault(m.group(1), []).append(fname)
        return books

    def _find_text_books(self, namelist: list[str]) -> dict[str, list[str]]:
        books: dict[str, list[str]] = {}
        pat = re.compile(r'^(assets/[^/]+/book/[^/]+/en_us)', re.IGNORECASE)
        for fname in namelist:
            if not fname.lower().endswith('.txt'):
                continue
            m = pat.match(fname)
            if m:
                books.setdefault(m.group(1), []).append(fname)
        return books

    def _translate_text_book_content(self, content: str, zh_cn_content: str = None) -> str:
        if OPENCC_AVAILABLE and zh_cn_content and zh_cn_content.strip():
            return s2tw(zh_cn_content)

        parts = re.split(r'(<NEWLINE>\s*)', content)
        translated_parts = []
        for part in parts:
            if not part or part.startswith('<NEWLINE>') or not part.strip():
                translated_parts.append(part)
                continue
            clean = part.strip()
            if len(re.sub(r'[^a-zA-Z]', '', clean)) < 3:
                translated_parts.append(part)
                continue
            leading = part[:len(part) - len(part.lstrip())]
            trailing = part[len(part.rstrip()):]
            translated_parts.append(leading + self.translate_text(clean) + trailing)
        return ''.join(translated_parts)

    def translate_text_books_in_jar(self, jr: zipfile.ZipFile, jw: zipfile.ZipFile,
                                    all_files: list[str]):
        books = self._find_text_books(all_files)
        if not books:
            return

        total_files = sum(len(v) for v in books.values())
        print(f"\n  [Text Book] 偵測到 {len(books)} 本書，共 {total_files} 個檔案")

        zh_cn_map: dict[str, bytes] = {}
        for fname in all_files:
            if '/book/' in fname and '/zh_cn/' in fname.lower() and fname.lower().endswith('.txt'):
                try:
                    zh_cn_map[fname] = jr.read(fname)
                except Exception:
                    pass
        print(f"  [Text Book] zh_cn 參考：{len(zh_cn_map)} 個")

        done = 0
        for en_us_root, en_files in books.items():
            book_name = en_us_root.split('/book/')[1].split('/')[0] if '/book/' in en_us_root else en_us_root
            print(f"\n  文字書本：{book_name}（{len(en_files)} 個）")

            for en_path in en_files:
                done += 1
                zh_tw_path = re.sub(r'/en_us/', '/zh_tw/', en_path, flags=re.IGNORECASE)
                zh_cn_path = re.sub(r'/en_us/', '/zh_cn/', en_path, flags=re.IGNORECASE)
                try:
                    try:
                        en_content = jr.read(en_path).decode('utf-8')
                    except UnicodeDecodeError:
                        en_content = jr.read(en_path).decode('utf-8-sig')

                    zh_cn_content = None
                    if zh_cn_path in zh_cn_map:
                        try:
                            zh_cn_content = zh_cn_map[zh_cn_path].decode('utf-8')
                        except UnicodeDecodeError:
                            zh_cn_content = zh_cn_map[zh_cn_path].decode('utf-8-sig')

                    translated = self._translate_text_book_content(en_content, zh_cn_content)
                    src = "zh_cn→opencc" if zh_cn_content and OPENCC_AVAILABLE else "untranslated"
                    jw.writestr(zh_tw_path, translated.encode('utf-8'))
                    print(f"    [{src}] {zh_tw_path}  ({done}/{total_files})")
                except Exception as e:
                    print(f"    [失敗] {en_path}: {e}")
                    try:
                        jw.writestr(zh_tw_path, jr.read(en_path))
                    except Exception:
                        pass

        print(f"  [Text Book] 完成，共 {done} 個檔案")

    def translate_tconstruct_books_in_jar(self, jr: zipfile.ZipFile, jw: zipfile.ZipFile,
                                           all_files: list[str]):
        books = self._find_tconstruct_books(all_files)
        if not books:
            return

        total_files = sum(len(v) for v in books.values())
        print(f"\n  [TConstruct Book] 偵測到 {len(books)} 本書，共 {total_files} 個檔案")

        zh_cn_map: dict[str, bytes] = {}
        for fname in all_files:
            if '/book/' in fname and '/zh_cn/' in fname.lower() and fname.endswith('.json'):
                try:
                    zh_cn_map[fname] = jr.read(fname)
                except Exception:
                    pass
        print(f"  [TConstruct Book] zh_cn 參考：{len(zh_cn_map)} 個")

        # 建立已有 zh_tw 的快速查找表（用於補翻譯）
        zh_tw_map: dict[str, bytes] = {}
        for fname in all_files:
            if '/book/' in fname and '/zh_tw/' in fname.lower() and fname.endswith('.json'):
                try:
                    zh_tw_map[fname] = jr.read(fname)
                except Exception:
                    pass
        print(f"  [TConstruct Book] 已有 zh_tw：{len(zh_tw_map)} 個")

        done = 0
        for en_us_root, en_files in books.items():
            book_name = en_us_root.split('/book/')[1].split('/')[0] if '/book/' in en_us_root else en_us_root
            print(f"\n  書本：{book_name}（{len(en_files)} 個）")

            for en_path in en_files:
                done += 1
                zh_tw_path = re.sub(r'/en_us/', '/zh_tw/', en_path, flags=re.IGNORECASE)
                zh_cn_path = re.sub(r'/en_us/', '/zh_cn/', en_path, flags=re.IGNORECASE)

                try:
                    en_bytes = jr.read(en_path)
                    try:
                        en_content = en_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        en_content = en_bytes.decode('utf-8-sig')

                    zh_cn_content = None
                    if zh_cn_path in zh_cn_map:
                        try:
                            zh_cn_content = zh_cn_map[zh_cn_path].decode('utf-8')
                        except Exception:
                            pass

                    # 若 JAR 裡已有 zh_tw，先載入作為基底，再用 en_us 補齊缺漏的 key
                    existing_zh_tw_content = None
                    if zh_tw_path in zh_tw_map:
                        try:
                            existing_zh_tw_content = zh_tw_map[zh_tw_path].decode('utf-8')
                        except Exception:
                            pass

                    if existing_zh_tw_content:
                        # 比對 en_us 的 key，補翻譯缺少的部分
                        translated = self._merge_tconstruct_with_existing(
                            en_content, existing_zh_tw_content, zh_cn_content)
                        src = "補翻譯"
                    else:
                        translated = self._translate_tconstruct_json(en_content, zh_cn_content)
                        src = "zh_cn→opencc" if (zh_cn_content and OPENCC_AVAILABLE) else "untranslated"

                    jw.writestr(zh_tw_path, translated.encode('utf-8'))
                    print(f"    [{src}] {zh_tw_path}  ({done}/{total_files})")

                except Exception as e:
                    print(f"    [失敗] {en_path}: {e}")
                    try:
                        jw.writestr(zh_tw_path, jr.read(en_path))
                    except Exception:
                        pass

        print(f"  [TConstruct Book] 完成，共 {done} 個檔案")

        app_pat = re.compile(r'^(assets/[^/]+/book/[^/]+)/appearance\.json$', re.IGNORECASE)
        app_files = [f for f in all_files if app_pat.match(f)]
        if app_files:
            print(f"\n  [TConstruct Book] 處理 appearance.json（{len(app_files)} 個）")
            for app_path in app_files:
                m = app_pat.match(app_path)
                if not m:
                    continue
                book_root = m.group(1)
                zh_tw_app = f"{book_root}/zh_tw/appearance.json"
                zh_cn_app = f"{book_root}/zh_cn/appearance.json"

                try:
                    en_bytes = jr.read(app_path)
                    try:
                        en_content = en_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        en_content = en_bytes.decode('utf-8-sig')

                    zh_cn_content = None
                    if zh_cn_app in all_files:
                        try:
                            zh_cn_content = jr.read(zh_cn_app).decode('utf-8')
                        except Exception:
                            pass

                    try:
                        en_data = json.loads(self._strip_json_comments(en_content))
                        zh_cn_data = {}
                        if zh_cn_content:
                            try:
                                zh_cn_data = json.loads(self._strip_json_comments(zh_cn_content))
                            except Exception:
                                pass

                        result = dict(en_data)
                        for field in ("title", "subtitle"):
                            if field in en_data and isinstance(en_data[field], str):
                                cn_val = zh_cn_data.get(field) if zh_cn_data else None
                                result[field] = self._translate_patchouli_string(en_data[field], cn_val)

                        jw.writestr(zh_tw_app, json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8'))
                        src = "zh_cn→opencc" if (zh_cn_content and OPENCC_AVAILABLE) else "untranslated"
                        print(f"    [{src}] {zh_tw_app}")
                    except Exception as e:
                        print(f"    [失敗] {app_path}: {e}")
                        jw.writestr(zh_tw_app, en_bytes)
                except Exception as e:
                    print(f"    [失敗] {app_path}: {e}")


    def _merge_patchouli_with_existing(self, en_content: str, zh_tw_content: str,
                                        zh_cn_content: str = None) -> str:
        """
        同 _merge_tconstruct_with_existing，但使用 Patchouli 欄位白名單。
        """
        try:
            en_data = json.loads(self._strip_json_comments(en_content))
        except Exception:
            return en_content

        try:
            zh_tw_data = json.loads(self._strip_json_comments(zh_tw_content))
        except Exception:
            zh_tw_data = {}

        zh_cn_data = {}
        if zh_cn_content:
            try:
                zh_cn_data = json.loads(self._strip_json_comments(zh_cn_content))
            except Exception:
                pass

        def merge_node(field, en_val, zh_tw_val, zh_cn_val):
            if isinstance(en_val, str):
                if isinstance(zh_tw_val, str) and zh_tw_val.strip() and zh_tw_val != en_val:
                    return zh_tw_val
                if field in PATCHOULI_SKIP_FIELDS:
                    return en_val
                if field not in PATCHOULI_TRANSLATE_FIELDS:
                    return en_val
                zh_cn_str = zh_cn_val if isinstance(zh_cn_val, str) else None
                return self._translate_patchouli_string(en_val, zh_cn_str)
            elif isinstance(en_val, dict):
                result = {}
                for k, v in en_val.items():
                    tw_child = zh_tw_val.get(k) if isinstance(zh_tw_val, dict) else None
                    cn_child = zh_cn_val.get(k) if isinstance(zh_cn_val, dict) else None
                    result[k] = merge_node(k, v, tw_child, cn_child)
                return result
            elif isinstance(en_val, list):
                result = []
                for i, item in enumerate(en_val):
                    tw_item = zh_tw_val[i] if isinstance(zh_tw_val, list) and i < len(zh_tw_val) else None
                    cn_item = zh_cn_val[i] if isinstance(zh_cn_val, list) and i < len(zh_cn_val) else None
                    if isinstance(item, str):
                        result.append(merge_node("text", item, tw_item, cn_item))
                    else:
                        result.append(merge_node(field, item, tw_item, cn_item))
                return result
            return en_val

        merged = {k: merge_node(k, v, zh_tw_data.get(k), zh_cn_data.get(k))
                  for k, v in en_data.items()}
        return json.dumps(merged, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Alex's Caves 書本翻譯（assets/<mod>/books/en_us/...）
    # ------------------------------------------------------------------

    def _find_alexscaves_books(self, namelist: list[str]) -> list[str]:
        """
        找 assets/<mod>/books/en_us/ 下的所有 JSON 和 TXT 檔。
        回傳 en_us 路徑清單。
        """
        pat = re.compile(r'^assets/[^/]+/books/en_us/.+\.(json|txt)$', re.IGNORECASE)
        return [f for f in namelist if pat.match(f)]

    def _translate_alexscaves_txt(self, en_text: str, zh_cn_text: str = None) -> str:
        """
        翻譯 Alex's Caves 的 .txt 書本內容。
        優先用 zh_cn_text 做 opencc 轉繁體，沒有就保留原文並列入待審。
        """
        if not en_text.strip():
            return en_text

        # 優先：opencc 轉換 zh_cn
        if OPENCC_AVAILABLE and zh_cn_text and zh_cn_text.strip():
            return s2tw(zh_cn_text)

        # 檢查快取（整段）
        with self.cache_lock:
            if en_text in self.translation_cache:
                return self.translation_cache[en_text]

        # 無 zh_cn 時：逐段落翻譯（以空行分段）
        paragraphs = re.split(r'(\n{2,})', en_text)
        translated_parts = []
        for part in paragraphs:
            if re.match(r'^\n+$', part):
                translated_parts.append(part)
            elif part.strip():
                clean, fmt = self.clean_for_translation(part)
                if clean and len(re.sub(r'[^a-zA-Z]', '', clean)) >= 3:
                    t = self.translate_text(clean)
                    translated_parts.append(self.restore_formatting(t, part, fmt))
                else:
                    translated_parts.append(part)
            else:
                translated_parts.append(part)

        result = ''.join(translated_parts)
        with self.cache_lock:
            self.translation_cache[en_text] = result
        return result

    def translate_alexscaves_books_in_jar(self, jr: zipfile.ZipFile, jw: zipfile.ZipFile,
                                           all_files: list[str]):
        """處理 Alex's Caves 風格書本的 en_us → zh_tw 翻譯（JSON + TXT）。"""
        en_files = self._find_alexscaves_books(all_files)
        if not en_files:
            return

        print(f"\n  [Alex's Books] 偵測到 {len(en_files)} 個檔案")

        # 建立 zh_cn 快速查找表（JSON 和 TXT）
        zh_cn_map: dict[str, bytes] = {}
        for fname in all_files:
            if '/books/zh_cn/' in fname.lower() and fname.endswith(('.json', '.txt')):
                try:
                    zh_cn_map[fname] = jr.read(fname)
                except Exception:
                    pass
        print(f"  [Alex's Books] zh_cn 參考：{len(zh_cn_map)} 個")

        # 建立已有 zh_tw 的查找表
        zh_tw_map_alex: dict[str, bytes] = {}
        for fname in all_files:
            if '/books/zh_tw/' in fname.lower() and fname.endswith(('.json', '.txt')):
                try:
                    zh_tw_map_alex[fname] = jr.read(fname)
                except Exception:
                    pass
        print(f"  [Alex's Books] 已有 zh_tw：{len(zh_tw_map_alex)} 個")

        done = 0
        for en_path in en_files:
            done += 1
            zh_tw_path = re.sub(r'/books/en_us/', '/books/zh_tw/', en_path, flags=re.IGNORECASE)
            zh_cn_path = re.sub(r'/books/en_us/', '/books/zh_cn/', en_path, flags=re.IGNORECASE)

            try:
                en_bytes = jr.read(en_path)
                try:
                    en_content = en_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    en_content = en_bytes.decode('utf-8-sig')

                zh_cn_content = None
                zh_cn_match = next((f for f in zh_cn_map if f.lower() == zh_cn_path.lower()), None)
                if zh_cn_match:
                    try:
                        zh_cn_content = zh_cn_map[zh_cn_match].decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            zh_cn_content = zh_cn_map[zh_cn_match].decode('utf-8-sig')
                        except Exception:
                            zh_cn_content = None

                is_txt = en_path.lower().endswith('.txt')

                if is_txt:
                    # TXT 檔：優先 opencc 轉繁體，否則保留原文並列入待審
                    translated = self._translate_alexscaves_txt(en_content, zh_cn_content)
                    src = "zh_cn→opencc" if (zh_cn_content and OPENCC_AVAILABLE) else "untranslated"
                    jw.writestr(zh_tw_path, translated.encode('utf-8'))
                    print(f"    [{src}] {zh_tw_path}  ({done}/{len(en_files)})")
                else:
                    # JSON 檔：補翻譯或全新翻譯
                    existing_zh_tw_content = None
                    zh_tw_match = next((f for f in zh_tw_map_alex if f.lower() == zh_tw_path.lower()), None)
                    if zh_tw_match:
                        try:
                            existing_zh_tw_content = zh_tw_map_alex[zh_tw_match].decode('utf-8')
                        except Exception:
                            pass

                    if existing_zh_tw_content:
                        translated = self._merge_patchouli_with_existing(
                            en_content, existing_zh_tw_content, zh_cn_content)
                        src = "補翻譯"
                    else:
                        translated = self._translate_patchouli_json(en_content, zh_cn_content)
                        src = "zh_cn→opencc" if (zh_cn_content and OPENCC_AVAILABLE) else "untranslated"

                    jw.writestr(zh_tw_path, translated.encode('utf-8'))
                    print(f"    [{src}] {zh_tw_path}  ({done}/{len(en_files)})")

            except Exception as e:
                print(f"    [失敗] {en_path}: {e}")
                try:
                    jw.writestr(zh_tw_path, jr.read(en_path))
                except Exception:
                    pass

        # root.json 也要處理
        root_pat = re.compile(r'^assets/[^/]+/books/root\.json$', re.IGNORECASE)
        root_files = [f for f in all_files if root_pat.match(f)]
        if root_files:
            print(f"\n  [Alex's Books] 處理 root.json（{len(root_files)} 個）")
            for root_path in root_files:
                base = re.match(r'^(assets/[^/]+/books)/', root_path, re.IGNORECASE)
                if not base:
                    continue
                zh_tw_root = f"{base.group(1)}/zh_tw/root.json"
                zh_cn_root = f"{base.group(1)}/zh_cn/root.json"
                try:
                    en_bytes = jr.read(root_path)
                    en_content = en_bytes.decode('utf-8', errors='replace')
                    zh_cn_content = None
                    zh_cn_root_match = next(
                        (f for f in all_files if f.lower() == zh_cn_root.lower()), None)
                    if zh_cn_root_match:
                        try:
                            zh_cn_content = jr.read(zh_cn_root_match).decode('utf-8')
                        except Exception:
                            pass
                    translated = self._translate_patchouli_json(en_content, zh_cn_content)
                    jw.writestr(zh_tw_root, translated.encode('utf-8'))
                    src = "zh_cn→opencc" if (zh_cn_content and OPENCC_AVAILABLE) else "untranslated"
                    print(f"    [{src}] {zh_tw_root}")
                except Exception as e:
                    print(f"    [失敗] {root_path}: {e}")

        print(f"  [Alex's Books] 完成，共 {done} 個檔案")

    # ------------------------------------------------------------------
    # Patchouli 書本翻譯
    # ------------------------------------------------------------------

    def _find_patchouli_books(self, namelist: list[str]) -> dict[str, list[str]]:
        pat = re.compile(
            r'^((?:assets|data)/[^/]+/patchouli_books/[^/]+/en_us(?:/[^/]+)*)(/[^/]+\.json)$',
            re.IGNORECASE
        )
        books: dict[str, list[str]] = {}
        for fname in namelist:
            m = pat.match(fname)
            if m:
                folder = m.group(1)
                books.setdefault(folder, []).append(fname)
        return books

    def translate_patchouli_in_jar(self, jr: zipfile.ZipFile, jw: zipfile.ZipFile,
                                    all_files: list[str], to_skip: set[str]):
        books = self._find_patchouli_books(all_files)
        if not books:
            return

        print(f"\n  [Patchouli] 偵測到 {len(books)} 個資料夾")

        zh_cn_map: dict[str, bytes] = {}
        for fname in all_files:
            if '/patchouli_books/' in fname and '/zh_cn/' in fname.lower():
                zh_cn_map[fname] = jr.read(fname)

        # 建立已有 zh_tw 的查找表
        zh_tw_map_patch: dict[str, bytes] = {}
        for fname in all_files:
            if '/patchouli_books/' in fname and '/zh_tw/' in fname.lower() and fname.endswith('.json'):
                try:
                    zh_tw_map_patch[fname] = jr.read(fname)
                except Exception:
                    pass
        print(f"  [Patchouli] 已有 zh_tw：{len(zh_tw_map_patch)} 個")

        total_files = sum(len(v) for v in books.values())
        done = 0

        for folder, en_files in books.items():
            for en_path in en_files:
                done += 1
                zh_tw_path = en_path.replace('/en_us/', '/zh_tw/').replace('/EN_US/', '/zh_tw/')
                zh_cn_path = en_path.replace('/en_us/', '/zh_cn/').replace('/EN_US/', '/zh_cn/')
                rel = en_path[len(folder):].lstrip('/')
                in_template = rel.lower().startswith('template/') or rel.lower().startswith('templates/')

                try:
                    en_bytes = jr.read(en_path)
                    try:
                        en_content = en_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        en_content = en_bytes.decode('utf-8-sig')

                    if in_template:
                        jw.writestr(zh_tw_path, en_bytes)
                        print(f"    [複製] {zh_tw_path}")
                    else:
                        zh_cn_content = None
                        if zh_cn_path in zh_cn_map:
                            try:
                                zh_cn_content = zh_cn_map[zh_cn_path].decode('utf-8')
                            except UnicodeDecodeError:
                                try:
                                    zh_cn_content = zh_cn_map[zh_cn_path].decode('utf-8-sig')
                                except Exception:
                                    zh_cn_content = None

                        # 若 JAR 裡已有 zh_tw，補齊缺漏 key
                        existing_zh_tw_content = None
                        if zh_tw_path in zh_tw_map_patch:
                            try:
                                existing_zh_tw_content = zh_tw_map_patch[zh_tw_path].decode('utf-8')
                            except Exception:
                                pass

                        if existing_zh_tw_content:
                            translated = self._merge_patchouli_with_existing(
                                en_content, existing_zh_tw_content, zh_cn_content)
                            src = "補翻譯"
                        else:
                            translated = self._translate_patchouli_json(en_content, zh_cn_content)
                            src = "zh_cn→opencc" if (zh_cn_content and OPENCC_AVAILABLE) else "untranslated"

                        jw.writestr(zh_tw_path, translated.encode('utf-8'))
                        print(f"    [{src}] {zh_tw_path}  ({done}/{total_files})")

                    to_skip.add(zh_tw_path)

                except Exception as e:
                    print(f"    [失敗] {en_path}: {e}")
                    try:
                        jw.writestr(zh_tw_path, jr.read(en_path))
                    except Exception:
                        pass

        print(f"  [Patchouli] 完成，共處理 {done} 個檔案")

    # ------------------------------------------------------------------
    # JAR 翻譯
    # ------------------------------------------------------------------

    def _translate_key(self, args):
        key, value = args
        if not isinstance(value, str) or not value.strip():
            return key, value
        clean, fmt = self.clean_for_translation(value)
        if not clean or len(re.sub(r'[^a-zA-Z]', '', clean)) < 3:
            return key, value
        return key, self.restore_formatting(self.translate_text(clean, lang_key=key), value, fmt)

    # 已知錯誤翻譯的強制修正清單（key: 正確的繁體中文值）
    KNOWN_FIXES: dict[str, str] = {
        "ars_nouveau.tier": "等級 %s",   # 原始翻譯含多餘 %s 格式符，保留正確格式
        "create.tooltip.keyCtrl": "Ctrl",
        "create.tooltip.keyShift": "Shift",
        "jei.key.shift": "Shift",
        "key.keyboard.control": "Ctrl",
        "key.keyboard.shift": "Shift",
        "keyboard.biomancy.ctrl": "Ctrl",
        "keyboard.biomancy.shift": "Shift",
        "tooltip.hexerei.shift": "Shift",
    }

    # 翻譯時值含 %s 但原文不含的，視為錯誤翻譯需重翻
    @staticmethod
    def _is_bad_translation(en_val: str, zh_val: str) -> bool:
        """偵測壞翻譯：原文和譯文的格式佔位符不一致。"""
        import re
        pat = r'%(?:\d+\$)?[sdfoxXeEgGaAcCbBhH%]'
        en_placeholders = re.findall(pat, en_val)
        zh_placeholders = re.findall(pat, zh_val)
        if en_placeholders != zh_placeholders:
            return True
        return False

    def translate_lang_data(self, en_data: dict, existing_zh: dict) -> dict:
        result = dict(existing_zh)
        to_do = []
        skip = 0

        for key, en_val in en_data.items():
            if key in self.KNOWN_FIXES:
                result[key] = self.KNOWN_FIXES[key]
                skip += 1
                continue

            zh_val = existing_zh.get(key)
            if zh_val is None or self.is_untranslated(en_val, zh_val):
                to_do.append((key, en_val))
            elif isinstance(en_val, str) and isinstance(zh_val, str) and self._is_bad_translation(en_val, zh_val):
                # 偵測到壞翻譯（如原文無佔位符但譯文有）→ 重翻
                print(f"  [壞翻譯] 重翻 {key}: {repr(zh_val)[:50]}")
                to_do.append((key, en_val))
            else:
                skip += 1

        need_api = []
        local_cn_hits = 0
        memory_hits = 0
        ref_hits = 0
        glossary_hits = 0
        for key, en_val in to_do:
            # zh_cn 已在呼叫本函式前轉成 zh_tw 放入 existing_zh；此處只統計。
            if key in existing_zh and not self.is_untranslated(en_val, existing_zh[key]):
                result[key] = existing_zh[key]
                local_cn_hits += 1
                continue
            ref = self.ref_db.lookup(key) if self.ref_db.is_loaded else None
            if ref and not self.is_untranslated(en_val, ref) and not self._is_bad_translation(en_val, ref):
                result[key] = ref
                ref_hits += 1
                continue
            cached = self._memory_lookup(en_val)
            if cached is not None:
                result[key] = cached
                memory_hits += 1
                continue
            glossary = self._glossary_lookup(en_val)
            if glossary is not None:
                result[key] = glossary
                glossary_hits += 1
                continue
            need_api.append((key, en_val))

        print(
            f"  需翻譯: {len(to_do)} | 同檔 zh_cn: {local_cn_hits} | "
            f"翻譯記憶: {memory_hits} | 參考庫/CFPA: {ref_hits} | "
            f"術語表: {glossary_hits} | 待審: {len(need_api)} | 跳過: {skip}"
        )
        for source, count in {
            "instance_zh_cn": local_cn_hits,
            "translation_memory": memory_hits,
            "reference_pack_or_cfpa": ref_hits,
            "glossary": glossary_hits,
            "untranslated": len(need_api),
        }.items():
            self._count_source(source, count)

        if not need_api:
            return result

        done = 0
        total = len(need_api)
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._translate_key, item): item for item in need_api}
            for future in as_completed(futures):
                done += 1
                try:
                    key, val = future.result()
                    result[key] = val
                    if done % 20 == 0 or done == total:
                        print(f"  待審進度: {done}/{total}")
                except Exception as e:
                    ok, ov = futures[future]
                    print(f"  失敗 [{ok}]: {e}")
                    result[ok] = ov

        # 最終掃描：修正原文無佔位符但譯文有佔位符的壞翻譯
        import re as _re
        fixed = 0
        for key in list(result.keys()):
            en_val = en_data.get(key)
            zh_val = result.get(key)
            if not isinstance(en_val, str) or not isinstance(zh_val, str):
                continue
            if self._is_bad_translation(en_val, zh_val):
                # 重新翻譯
                clean, fmt = self.clean_for_translation(en_val)
                if clean:
                    new_val = self.restore_formatting(self.translate_text(clean, lang_key=key), en_val, fmt)
                    print(f"  [修正壞翻譯] {key}: {repr(zh_val)[:40]} → {repr(new_val)[:40]}")
                    result[key] = new_val
                    fixed += 1
        if fixed:
            print(f"  修正壞翻譯：{fixed} 條")
        return result

    def translate_jar(self, jar_path: str, output_path: Optional[str] = None):
        p = Path(jar_path)
        if not p.exists():
            print(f"找不到檔案: {jar_path}")
            return
        if output_path is None:
            output_path = str(p.parent / f"{p.stem}_translated.jar")

        print(f"\n{'='*50}")
        print(f"JAR: {p.name}  →  {Path(output_path).name}")

        lang_pat = re.compile(r'(^|.*/)assets/[^/]+/lang/en_us\.json$', re.IGNORECASE)
        try:
            with zipfile.ZipFile(jar_path, 'r') as jr:
                all_files = jr.namelist()
                lang_files = [f for f in all_files if lang_pat.match(f)]

                has_patchouli = any('/patchouli_books/' in f for f in all_files)
                has_tconstruct_book = any(
                    re.match(r'^assets/[^/]+/(?:.*/)?book/(?:[^/]+/)?en_us/', f, re.IGNORECASE)
                    for f in all_files
                )
                has_text_book = any(
                    re.match(r'^assets/[^/]+/book/[^/]+/en_us/.*\.txt$', f, re.IGNORECASE)
                    for f in all_files
                )
                has_alexscaves_book = any(
                    re.match(r'^assets/[^/]+/books/en_us/', f, re.IGNORECASE)
                    for f in all_files
                )

                if not lang_files and not has_patchouli and not has_tconstruct_book and not has_text_book and not has_alexscaves_book:
                    print("  找不到 en_us.json 且無書本資料，跳過")
                    if output_path and str(Path(output_path).resolve()) != str(Path(jar_path).resolve()):
                        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(jar_path, output_path)
                        print(f"  已原樣複製: {output_path}")
                    return

                results = {}
                # 預先把書本的 zh_tw 路徑加入 to_skip，
                # 避免主流程複製舊版後 append 再寫一次造成重複條目
                to_skip = set()
                if has_tconstruct_book:
                    for f in all_files:
                        if re.match(r'^assets/[^/]+/(?:.*/)?book/(?:[^/]+/)?zh_tw/', f, re.IGNORECASE):
                            to_skip.add(f)
                if has_text_book:
                    for f in all_files:
                        if re.match(r'^assets/[^/]+/book/[^/]+/zh_tw/.*\.txt$', f, re.IGNORECASE):
                            to_skip.add(f)
                if has_patchouli:
                    for f in all_files:
                        if '/patchouli_books/' in f and '/zh_tw/' in f.lower():
                            to_skip.add(f)
                if has_alexscaves_book:
                    for f in all_files:
                        if re.match(r'^assets/[^/]+/books/zh_tw/', f, re.IGNORECASE):
                            to_skip.add(f)
                if to_skip:
                    print(f"  預先跳過 {len(to_skip)} 個既有 zh_tw 書本檔案（將由翻譯器重新生成）")

                for lang_file in lang_files:
                    zh_path = lang_file.replace('en_us.json', 'zh_tw.json')
                    has_zh = zh_path in all_files
                    print(f"  {lang_file}  {'（補翻譯）' if has_zh else '（全新）'}")
                    print(f"\n  處理: {lang_file}")
                    try:
                        en_content = jr.read(lang_file).decode('utf-8')
                        en_data = json.loads(self._strip_json_comments(en_content))
                        existing_zh = {}
                        if has_zh:
                            try:
                                existing_zh_content = jr.read(zh_path).decode('utf-8')
                                existing_zh = json.loads(self._strip_json_comments(existing_zh_content))
                                print(f"  現有 zh_tw: {len(existing_zh)} 條")
                            except Exception as e:
                                print(f"  讀取 zh_tw 失敗: {e}")

                        cn_path = lang_file.replace('en_us.json', 'zh_cn.json')
                        if cn_path in all_files:
                            cn_data = json.loads(self._strip_json_comments(jr.read(cn_path).decode('utf-8-sig')))
                            for key, value in cn_data.items():
                                old = existing_zh.get(key)
                                en = en_data.get(key, '')
                                if isinstance(value, str) and (old is None or self.is_untranslated(en, old) or self._is_bad_translation(en, old)):
                                    converted = s2tw(value)
                                    if not self._is_bad_translation(en, converted):
                                        existing_zh[key] = converted
                        if hasattr(self.ref_db, 'set_namespace'):
                            self.ref_db.set_namespace(lang_file.split('/assets/')[-1].split('/')[0] if '/assets/' in lang_file else lang_file.split('/')[1])
                        translated = self.translate_lang_data(en_data, existing_zh)
                        results[zh_path] = translated
                        to_skip.add(zh_path)
                        print(f"  完成: {len(translated)} 條")
                        self._save_cache()
                    except Exception as e:
                        print(f"  處理失敗: {e}")

                with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as jw:
                    for fname in all_files:
                        if is_jar_signature_file(fname):
                            continue
                        if fname not in to_skip:
                            jw.writestr(fname, jr.read(fname))
                    for zh_path, data in results.items():
                        jw.writestr(zh_path,
                                    json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
                        print(f"  寫入: {zh_path}")

                if has_patchouli or has_tconstruct_book or has_alexscaves_book:
                    with zipfile.ZipFile(jar_path, 'r') as jr2:
                        with zipfile.ZipFile(output_path, 'a', zipfile.ZIP_DEFLATED) as jw2:
                            if has_patchouli:
                                print(f"\n  [Patchouli] 開始處理書本翻譯...")
                                dummy_skip = set()
                                self.translate_patchouli_in_jar(jr2, jw2, all_files, dummy_skip)
                            if has_tconstruct_book:
                                print(f"\n  [TConstruct Book] 開始處理書本翻譯...")
                                self.translate_tconstruct_books_in_jar(jr2, jw2, all_files)
                            if has_text_book:
                                print(f"\n  [Text Book] 開始處理文字書本翻譯...")
                                self.translate_text_books_in_jar(jr2, jw2, all_files)
                            if has_alexscaves_book:
                                print(f"\n  [Alex's Books] 開始處理書本翻譯...")
                                self.translate_alexscaves_books_in_jar(jr2, jw2, all_files)
                    self._save_cache()

            print(f"  ✓ {output_path}")
        except Exception as e:
            print(f"  錯誤: {e}")
            import traceback
            traceback.print_exc()

    def translate_jar_folder(self, folder: str, output_folder: Optional[str] = None):
        folder_p = Path(folder)
        jars = list(folder_p.glob("*.jar"))
        if not jars:
            print(f"找不到 .jar: {folder}")
            return
        out_dir = Path(output_folder) if output_folder else folder_p / "translated"
        out_dir.mkdir(exist_ok=True)
        print(f"找到 {len(jars)} 個 JAR，輸出: {out_dir}")
        for i, jar in enumerate(jars, 1):
            print(f"\n[{i}/{len(jars)}] {jar.name}")
            self.translate_jar(str(jar), str(out_dir / jar.name))
        print(f"\n全部完成！輸出: {out_dir}")
        self._save_cache()

    # ------------------------------------------------------------------
    # ZIP 翻譯（SNBT / JSON）
    # ------------------------------------------------------------------

    def translate_zip(self, zip_path: str, output_path: Optional[str] = None):
        p = Path(zip_path)
        if not p.exists():
            print(f"找不到: {zip_path}")
            return
        if output_path is None:
            output_path = str(p.parent / f"{p.stem}_translated.zip")
        count = 0
        try:
            with zipfile.ZipFile(zip_path, 'r') as zr, \
                 zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zw:
                for fname in zr.namelist():
                    raw = zr.read(fname)
                    if fname.endswith(('.snbt', '.json')):
                        try:
                            try:
                                content = raw.decode('utf-8')
                            except UnicodeDecodeError:
                                content = raw.decode('utf-8-sig')
                            out = self.process_json(content) if fname.endswith('.json') \
                                  else self.process_snbt(content)
                            zw.writestr(fname, out.encode('utf-8'))
                            count += 1
                        except Exception as e:
                            print(f"  {fname} 失敗: {e}")
                            zw.writestr(fname, raw)
                    else:
                        zw.writestr(fname, raw)
            print(f"完成，翻譯 {count} 個檔案 → {output_path}")
        except Exception as e:
            print(f"ZIP 處理失敗: {e}")
        self._save_cache()

    # ------------------------------------------------------------------
    # 資料夾翻譯（SNBT / JSON）
    # ------------------------------------------------------------------

    def translate_folder(self, folder: str, output_folder: Optional[str] = None):
        p = Path(folder)
        if not p.exists():
            print(f"找不到: {folder}")
            return
        if output_folder is None:
            output_folder = str(p.parent / f"{p.name}_translated")
        out = Path(output_folder)
        out.mkdir(exist_ok=True)
        files = list(p.glob("*.snbt")) + list(p.glob("*.json"))
        if not files:
            print("找不到 .snbt / .json")
            return
        print(f"共 {len(files)} 個檔案")
        for i, f in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] {f.name}")
            try:
                result = self.process_file(str(f))
                with open(out / f.name, 'w', encoding='utf-8') as fw:
                    fw.write(result)
                print(f"  ✓ {out / f.name}")
            except Exception as e:
                print(f"  失敗: {e}")
        self._save_cache()
        print(f"\n完成！輸出: {output_folder}")

# =============================================================================
# 主程式
# =============================================================================

def main():
    print("CTE2 FTB 任務書翻譯程式")
    print("=" * 50)
    print("自動載入：ref_pack.json（繁體）+ CFPA 簡中轉繁體")
    print("支援：.jar 資料夾批次 / 單一 .jar / .zip / SNBT 資料夾")
    print("新增：Patchouli 書本 en_us → zh_tw 自動翻譯")
    print("=" * 50)

    if OPENCC_AVAILABLE:
        print("✓ opencc 已安裝")
    else:
        print("! opencc 未安裝（CFPA 下載功能需要）")
        print("  安裝：pip install opencc-python-reimplemented")

    try:
        workers = int(input("\n執行緒數 (預設 5，建議 3~10，上限不超過 20): ").strip() or "5")
        workers = max(1, min(workers, 20))
    except ValueError:
        workers = 5

    translator = CTE2QuestTranslator(max_workers=workers)

    input_path = input("\n請輸入路徑 (.jar / .zip / 資料夾): ").strip().strip('"').strip("'")
    if not input_path:
        print("未輸入路徑")
        return

    p = Path(input_path)

    if input_path.endswith('.jar'):
        out = input("輸出路徑（留空自動產生）: ").strip()
        translator.translate_jar(input_path, out or None)

    elif input_path.endswith('.zip'):
        out = input("輸出路徑（留空自動產生）: ").strip()
        translator.translate_zip(input_path, out or None)

    elif p.is_dir():
        jars = list(p.glob("*.jar"))
        sn   = list(p.glob("*.snbt"))
        js   = list(p.glob("*.json"))

        if jars:
            print(f"\n偵測到 {len(jars)} 個 .jar → 批次翻譯")
            out = input("輸出資料夾（留空自動產生 translated/）: ").strip()
            out_dir = out or None
            translator.translate_jar_folder(input_path, out_dir)

            # ★ 修正：同層的 .json / .snbt 也一起翻譯，輸出到同一個資料夾
            if sn or js:
                resolved_out = out if out else str(p / "translated")
                print(f"\n偵測到同層 {len(js)} 個 .json / {len(sn)} 個 .snbt → 一併翻譯")
                translator.translate_folder(input_path, resolved_out)

        elif sn or js:
            print(f"\n偵測到任務檔案 → 任務翻譯")
            out = input("輸出資料夾（留空自動產生）: ").strip()
            translator.translate_folder(input_path, out or None)

        else:
            print("找不到可處理的檔案")

    else:
        print("路徑不存在或格式不支援")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[未預期錯誤] {e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\n按 Enter 關閉視窗...")
