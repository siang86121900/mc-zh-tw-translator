# mc-zh-tw-translator

Minecraft 模組、任務書、Patchouli/TConstruct/Alex's Caves 書本資源的繁體中文化工具。

這個專案由原本的 `translate.py` 拆成可安裝的小型 Python 專案，並內建目前更新過的參考資料：

- `data/ref_pack.json`：由 TeamKugimiya/ModsTranslationPack main 合併，86,157 個唯一 key。
- `data/cfpa_cache.json`：由 CFPA autobuild `Minecraft-Mod-Language-Modpack-1-20.zip` 轉繁中，125,439 條。
- `data/cfpa_zh_cn.zip`：CFPA 1.20 原始簡中包。

每次執行翻譯會先嘗試更新 ModsTranslationPack main 與 CFPA autobuild，並記錄 commit、資產時間、SHA-256 與實際條目數；無法確認最新版本時不得宣稱已使用最新資料。翻譯完全不呼叫外部翻譯 API；找不到免費來源時保留原文並列入待審。

## 安裝

```bash
cd /Users/vm5-james/workspace/mc-zh-tw-translator
python3 -m pip install -e .
```

## 使用

零成本模式，不使用 Google / DeepL / Claude API：

```bash
mc-zh-tw-translator translate /path/to/mod.jar --engine none
```

翻譯整個 mods 資料夾：

```bash
mc-zh-tw-translator translate /path/to/mods --engine none
```

找不到免費來源時會保留英文並列入待審；本工具不提供外部翻譯 API。

保留原本互動式流程：

```bash
mc-zh-tw-translator --interactive
```

## 輸出

- 單一 `.jar` 預設輸出到同資料夾的 `*_translated.jar`。
- 單一 `.zip` 預設輸出到同資料夾的 `*_translated.zip`。
- 資料夾預設輸出到 `translated/`。

## 注意

`--engine none` 是唯一模式，不會打任何翻譯 API。找不到現成翻譯時會保留英文，適合使用 CFPA、OpenCC、參考包與已確認翻譯記憶做免費翻譯。
