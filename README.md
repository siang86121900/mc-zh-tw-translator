# mc-zh-tw-translator

Minecraft 模組、任務書、Patchouli/TConstruct/Alex's Caves 書本資源的繁體中文化工具。

## 預設作業流程：備份後直接套用

使用者提供的路徑就是最終翻譯位置。代理掃描整包、更新參考庫、產生候選並校對，驗證通過後備份原始檔，直接更新指定位置，不要求使用者搬移輸出檔。

一次要求就接續完成整包流程，不需要使用者逐批催促。優先採用同版本語系、簡中轉繁與參考庫；缺少來源的玩家文字由目前對話中的 AI 補譯、校對。只有真正需要使用者介入的阻礙才暫停，不能把一般補翻工作當成下一次請求。

- 原檔備份：`output/<名稱>/原始備份/<時間戳>/`，保留相對路徑，每批獨立保存。
- 備份紀錄：該批備份的 `_備份紀錄/manifest.json`，包含 instance 路徑、前後 SHA-256、新增檔清單及套用狀態。
- 本機報告：`output/<名稱>/報告/<批次>/`；歷史紀錄保留原位置。
- 最終品質報告：PDF 加上完整來源明細，列出 AI 補譯與各來源的不確定項目、原文／譯文、原因及套用狀態。簡中轉繁和參考庫同樣需要校對，不保證一定正確。
- 翻譯候選：獨立的暫存／待審目錄，不是使用者需要複製回去的成品。

備份只涵蓋本批將修改的原檔，不是整個 instance 或存檔備份。新增檔沒有原檔可備份，須依清冊處理；還原時不要把 `_備份紀錄` 複製到遊戲，也不要覆蓋使用者後來自行修改的內容。完整規則見 [AGENTS.md](AGENTS.md)。

修改 JAR 前確認使用該 instance 的遊戲已關閉；遊戲執行時可先使用已校對的暫時語系覆蓋。程式不會自行結束遊戲。

參考庫來自 ModsTranslationPack main 與 CFPA autobuild。版本、資產時間、雜湊及條目數以當次預檢紀錄為準，不以 README 的固定數字判斷最新。無法確認最新就停止正式翻譯；不使用外部翻譯 API，參考來源缺漏由目前對話 AI 補譯並記錄為 `ai_translation`。

## 執行環境

需 Python、`requests`、`opencc-python-reimplemented`；JAR 驗證需 Java。在專案根目錄執行：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
python -m mc_zh_tw_translator --help
```

## 候選產生工具

舊 CLI `translate` 只處理單一壓縮檔或目錄直屬檔案，**不會遞迴翻譯整個 instance，也不會自動備份與直接套用**。代理必須完成前述完整流程，不能把 CLI 成功結束當作已更新遊戲。單獨使用時指定獨立輸出目錄，不要把輸出指向原檔。

零成本模式，不使用 Google / DeepL / Claude API：

```bash
python -m mc_zh_tw_translator translate /path/to/mod.jar --engine none -o tmp/pack/batch/mod.jar
```

翻譯整個 mods 資料夾：

```bash
python -m mc_zh_tw_translator translate /path/to/mods --engine none -o tmp/pack/batch/mods
```

這個 CLI 找不到來源時仍會保留英文並列入待審；代理必須接續完成 AI 補譯與校對。本工具不提供外部翻譯 API，AI 補譯是對話中的作業步驟，不是 CLI 自動呼叫模型。

保留原本互動式流程：

```bash
python -m mc_zh_tw_translator --interactive
```

## 備份、套用與驗證

套用程式使用 `mc_zh_tw_translator.deployment.apply_reviewed(instance, staged, records, output_root)`。每筆檔案紀錄需要 `file`（相對路徑）、`before`（原 SHA-256，新增檔為 null）、`after`（候選 SHA-256）、`reviewed: true`、`verified: true`。審核標記須有實際證據，不能由自動來源命中直接設定。

此函式確認檔案未改變、備份全部原檔，再逐檔原子寫回並讀回驗證。一般例外發生時嘗試還原本批變更；斷電、強制終止或還原衝突須依清冊人工復原。它不代替內容校對、Java／資源驗證或遊戲狀態檢查。

```powershell
python scripts/full_translation_audit.py 'C:/path/instance' --output 'output/pack/報告/batch/before'
python -m mc_zh_tw_translator verify 'tmp/pack/batch/mods' --input 'C:/path/instance/mods'
```

套用後重掃實際 instance，驗證 `<instance>/mods`，並對修改的 JAR 逐檔與該批原檔備份比對。語系鍵補齊或結構驗證通過不代表翻譯完成。

## 注意

`--engine none` 是唯一 CLI 模式，不會打任何翻譯 API。它使用 CFPA、OpenCC、參考包與已確認翻譯記憶產生候選，缺漏由代理接續處理。報告把 AI 補譯、簡中轉繁、參考庫命中與真正人工確認分開；沒有使用 Google 翻譯就明記為 0 筆。

既有參考庫更新腳本固定選 CFPA 1.20 資產；處理其他版本須核對適用版本、namespace 與英文語意。既有翻譯器更新失敗可能沿用快取，代理必須另外確認預檢成功。`scripts/` 的歷史批次腳本含固定路徑與舊備份配置，執行前先閱讀，不能當成通用一鍵流程。
