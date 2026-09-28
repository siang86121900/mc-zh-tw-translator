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

套用模式：`apply_mode='jar'` 直接改模組 jar（內嵌 jar-in-jar 的文字會略過並計入 `nested_skipped`）；`'pack'` 寫到 `kubejs/assets` 或 `mods/mctranslator_zh_tw.jar`（lowcodefml／fabric 資源模組，對翻譯到的模組宣告 `ordering="AFTER"`）。`set_language=True` 會把 `options.txt` 的 `lang` 改為 `zh_tw`，與其他檔案一起備份與還原。

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

## 注意

- 報告把 AI 補譯、簡中轉繁、參考庫命中與人工確認分開；沒有使用外部翻譯 API 就記為 0 筆。
- 舊參考庫更新腳本固定選 CFPA 1.20 資產；其他版本須核對適用版本、namespace 與英文語意。
- `scripts/` 的歷史批次腳本含固定路徑與舊備份配置，執行前先閱讀，不能當成通用一鍵流程。
- AI 補翻協定依據：[Codex App Server](https://learn.chatgpt.com/docs/app-server)、[登入方式](https://learn.chatgpt.com/docs/auth)。
