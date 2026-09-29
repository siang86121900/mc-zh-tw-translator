# 開發與代理作業說明

一般使用者只需要 [README](../README.md)。這份文件給修改程式、發布版本或以代理（AI）執行整包翻譯的人；完整規則以 [AGENTS.md](../AGENTS.md) 為準。

## 代理作業流程：備份後直接套用

使用者提供的路徑就是最終翻譯位置。代理掃描整包、更新參考庫、產生候選並校對，驗證通過後備份原始檔，直接更新指定位置，不要求使用者搬移輸出檔。

一次要求就接續完成整包流程，不需要使用者逐批催促。優先採用同版本語系、簡中轉繁與參考庫；缺少來源的玩家文字由目前對話中的 AI 補譯、校對。只有真正需要使用者介入的阻礙才暫停。

- 原檔備份：`output/<名稱>/原始備份/<時間戳>/`，保留相對路徑，每批獨立保存。
- 備份紀錄：該批備份的 `_備份紀錄/manifest.json`，包含 instance 路徑、前後 SHA-256、新增檔清單及套用狀態。
- 本機報告：`output/<名稱>/報告/<批次>/`。
- 翻譯候選：獨立的暫存／待審目錄，不是使用者需要複製回去的成品。

備份只涵蓋本批將修改的原檔，不是整個 instance 或存檔備份。新增檔沒有原檔可備份，須依清冊處理；還原時不要把 `_備份紀錄` 複製到遊戲，也不要覆蓋使用者後來自行修改的內容。

參考庫來自 ModsTranslationPack main 與 CFPA autobuild。版本、資產時間、雜湊及條目數以當次預檢紀錄為準；無法確認最新就停止正式翻譯。不使用外部翻譯 API，參考來源缺漏記錄為 `ai_translation`。

桌面版的翻譯記憶存在程式資料夾的 `translation_memory.json`，只收使用者在報告中按「確認這筆」的譯文，以「模組 namespace＋語系鍵＋原文雜湊」對應；自動來源、參考庫與 AI 候選不會寫入。模組包附帶的翻譯包（OpenLoader、resourcepacks）中，namespace 不在已安裝模組（含 jar-in-jar）裡的語系會略過並計入 `not_installed`。

補充來源（`desktop_references.refresh`）：ParaTranslationPack 最新 main、CFPA 較舊版本資產（最多 3 個，來源標為 `cross_version_reference` 並列為待核對）、Minecraft 官方 zh_tw（優先讀本機啟動器 `Install`／`.minecraft`，否則從 Mojang 下載）。這些來源失敗只記錄在 `references.notes`，不阻擋翻譯；ModsTranslationPack 與同版本 CFPA 仍須確認最新。自訂譯名存在 `user_glossary.json`。

套用：桌面程式一律直接改模組 jar；內嵌 jar-in-jar 的文字在有 KubeJS 時寫到 `kubejs/assets`（計入 `nested_packed`），否則略過（計入 `nested_skipped`）。後端仍保留 `apply_mode='pack'`（全部寫到 `kubejs/assets` 或 `mods/mctranslator_zh_tw.jar` 資源模組）與 `set_language=True`（改 `options.txt`），介面目前不提供，尚未進遊戲實測。

## 打包與發布

```powershell
python -m pip install -r requirements-desktop.txt
python scripts/package_desktop.py
```

產物為 `dist/MCTranslator.exe`。發布新版：

1. 更新 `src/mc_zh_tw_translator/updater.py` 的 `VERSION`。
2. 新增 `docs/release-notes/vX.Y.Z.md`，用玩家看得懂的話寫這一版的修正與新功能。程式的「程式更新」頁會直接顯示這份內容；缺少時發布流程會失敗。
   **不要使用 `#` 標題、`**` 粗體或反引號**：v0.4.1 以前的程式以純文字顯示說明，這些符號會原樣出現。分類用單獨一行文字，條列用 `- `，段落之間空一行；這樣舊版純文字與新版排版都好讀。
3. 建立 `vX.Y.Z` 標籤並推送。GitHub Actions 會執行測試、打包 EXE、產生 `SHA256SUMS.txt` 並建立公開 Release。

更新器會先驗證大小、格式與雜湊才替換程式。只推送原始碼不會產生可下載的更新。不把 private instance、cache、backup 或帳號資料打包進 EXE。

## 原始碼工具

需 Python、`requests`、`opencc-python-reimplemented`；JAR 驗證需 Java。在專案根目錄執行：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m mc_zh_tw_translator --help
```

### 候選產生 CLI

`translate` 只處理單一壓縮檔或目錄直屬檔案，**不會遞迴翻譯整個 instance，也不會備份與套用**；成功結束不代表遊戲已更新。輸出請指定獨立目錄。`--engine none` 是唯一模式，不呼叫任何翻譯 API，找不到來源時保留英文並列入待審。

```bash
python -m mc_zh_tw_translator translate /path/to/mod.jar --engine none -o tmp/pack/batch/mod.jar
python -m mc_zh_tw_translator translate /path/to/mods --engine none -o tmp/pack/batch/mods
python -m mc_zh_tw_translator --interactive
```

## 備份、套用與驗證

套用使用 `mc_zh_tw_translator.deployment.apply_reviewed(instance, staged, records, output_root)`。每筆檔案紀錄需要 `file`（相對路徑）、`before`（原 SHA-256，新增檔為 null）、`after`（候選 SHA-256）、`reviewed: true`、`verified: true`。審核標記須有實際證據，不能由自動來源命中直接設定。

此函式確認檔案未改變、備份全部原檔，再逐檔原子寫回並讀回驗證；一般例外會嘗試還原本批變更。它不代替內容校對、Java／資源驗證或遊戲狀態檢查。

```powershell
python scripts/full_translation_audit.py 'C:/path/instance' --output 'output/pack/報告/batch/before'
python -m mc_zh_tw_translator verify 'tmp/pack/batch/mods' --input 'C:/path/instance/mods'
```

套用後重掃實際 instance，驗證 `<instance>/mods`，並對修改的 JAR 逐檔與該批原檔備份比對。語系鍵補齊或結構驗證通過不代表翻譯完成。

## 翻譯補丁與現成翻譯目錄

「現成翻譯」頁使用 `mc_zh_tw_translator.patches`：

- `export_patch(instance, home)`：從該 instance 仍為 `installed` 的備份清冊收集翻譯檔，輸出到 `output/<instance>/分享/*.zip`。ZIP 內含 `manifest.json`（格式 `mctranslator-patch-1`、整合包 projectID／fileID、每檔原 SHA-256 與項目雜湊）、`payload/` 與 `授權與來源.txt`。
- `apply_patch(instance, zip, home)`：驗證清冊與路徑白名單，只改雜湊與原檔相符的檔案，經 `apply_reviewed` 備份與寫回。
- `fetch_catalog()` 讀 `https://raw.githubusercontent.com/siang86121900/mc-zh-tw-translator/translations/index.json`；404 視為尚無公開翻譯。補丁下載網址必須是本專案的 GitHub Release 附件，並驗 SHA-256 與大小。
- CurseForge 整合包由 `%APPDATA%/CurseForge/agent/GameInstances/MinecraftGameInstance.json` 偵測（含自訂位置），整合包身分讀 `minecraftinstance.json`；「用 CurseForge 安裝」開啟 `curseforge://install?addonId=<projectID>&fileId=<fileID>`，無反應時請使用者手動搜尋。

套用補丁後在 `applied_patches.json` 記錄每個 instance 最後套用的補丁雜湊；目錄上同一整合包版本的補丁雜湊不同時顯示「翻譯有更新」。

上架一個現成翻譯（需使用者授權）：`python scripts/publish_translation.py <補丁.zip> --translator 名稱 [--notes 說明] [--dry-run]`。它把補丁放到 `translations` 分支的 `packs/<projectID>/`、更新 `index.json`（同整合包同版本會取代）並推送。手動作法：

1. 用程式匯出補丁，建立或更新預先發行版（prerelease）`translations` 並上傳 ZIP；預先發行版不會被 `releases/latest` 當成程式更新。
2. 在 `translations` 分支的 `index.json` 加入：

```json
{"packs":[{"name":"Tensura Neo Otherworld","projectID":1478248,"fileID":8908669,"version":"1.1.1a","gameVersion":"1.21.1",
  "translator":"名稱","updated":"2026-09-29","notes":"","url":"https://github.com/siang86121900/mc-zh-tw-translator/releases/download/translations/檔名.zip",
  "sha256":"<ZIP 的 SHA-256>","size":12345}]}
```

## 注意

- 報告把 AI 補譯、簡中轉繁、參考庫命中與人工確認分開；沒有使用外部翻譯 API 就記為 0 筆。
- 舊參考庫更新腳本固定選 CFPA 1.20 資產；其他版本須核對適用版本、namespace 與英文語意。
- `scripts/` 的歷史批次腳本含固定路徑與舊備份配置，執行前先閱讀，不能當成通用一鍵流程。
- Java ZipFS 檢查優先使用 CurseForge／Minecraft 啟動器內建的 Java 17+（純 JRE），因此執行預先編譯的 `ZipFsCheck.class`（內嵌於 `verifier.py`），不需要 JDK。
- AI 補翻協定依據：[Codex App Server](https://learn.chatgpt.com/docs/app-server)、[登入方式](https://learn.chatgpt.com/docs/auth)。
