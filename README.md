# mc-zh-tw-translator

Minecraft 模組、任務書、Patchouli/TConstruct/Alex's Caves 書本資源的繁體中文化工具。

## 給一般使用者

從 [最新版下載頁](https://github.com/siang86121900/mc-zh-tw-translator/releases/latest) 下載 `MCTranslator.exe`，雙擊即可使用。

1. 直接貼上模組包根資料夾路徑，或按「選擇資料夾」。
2. 按「一鍵完整翻譯並套用」。程式自動掃描、更新參考庫、產生譯文、驗證、備份與套用。
3. 「即時處理紀錄」顯示目前檔案、參考庫下載量與最近的原文 → 譯文；完整來源在「翻譯報告」。
4. 遊戲仍在執行時保留譯文與報告；關閉對應遊戲後按「重試套用」，不用重新翻譯。其他資料夾的 Forge 伺服器會另外辨識。

亮色／深色可切換並記住；小視窗可捲動。開啟程式會檢查新版本，有更新時在頂端與側欄提示，**由你按下載與安裝**。自動檢查可在更新頁關閉。首次使用舊版 v0.2／v0.3，請先手動按一次「檢查更新」，升級後才有啟動提示。

「完整」指連續處理整個流程，不保證所有文字都能翻譯；圖片、動態文字與尚未支援的腳本／設定會留在待查清單。AI 選用，會消耗你原本的 Codex 額度。

## 預設作業流程：備份後直接套用

使用者提供的路徑就是最終翻譯位置。代理掃描整包、更新參考庫、產生候選並校對，驗證通過後備份原始檔，直接更新指定位置，不要求使用者搬移輸出檔。

一次要求就接續完成整包流程，不需要使用者逐批催促。優先採用同版本語系、簡中轉繁與參考庫；缺少來源的玩家文字由目前對話中的 AI 補譯、校對。只有真正需要使用者介入的阻礙才暫停，不能把一般補翻工作當成下一次請求。

- 原檔備份：`output/<名稱>/原始備份/<時間戳>/`，保留相對路徑，每批獨立保存。
- 備份紀錄：該批備份的 `_備份紀錄/manifest.json`，包含 instance 路徑、前後 SHA-256、新增檔清單及套用狀態。
- 本機報告：`output/<名稱>/報告/<批次>/`；歷史紀錄保留原位置。
- 最終品質報告：直接顯示在程式裡，保留可搜尋的本機明細，不另外產生 PDF。列出各來源、不確定項目、原文／譯文、原因及套用狀態；參考來源同樣需要校對。
- 翻譯候選：獨立的暫存／待審目錄，不是使用者需要複製回去的成品。

備份只涵蓋本批將修改的原檔，不是整個 instance 或存檔備份。新增檔沒有原檔可備份，須依清冊處理；還原時不要把 `_備份紀錄` 複製到遊戲，也不要覆蓋使用者後來自行修改的內容。完整規則見 [AGENTS.md](AGENTS.md)。

修改 JAR 前確認使用該 instance 的遊戲已關閉；遊戲執行時可先使用已校對的暫時語系覆蓋。程式不會自行結束遊戲。

參考庫來自 ModsTranslationPack main 與 CFPA autobuild。版本、資產時間、雜湊及條目數以當次預檢紀錄為準，不以 README 的固定數字判斷最新。無法確認最新就停止正式翻譯；不使用外部翻譯 API，參考來源缺漏由目前對話 AI 補譯並記錄為 `ai_translation`。

## 執行環境

### Windows EXE

雙擊 `MCTranslator.exe` → 貼上或選擇模組包根資料夾 → 一鍵完整翻譯並套用。掃描是內部步驟，不必另外執行。報告、來源校對、備份及還原都在程式內。

程式使用白底藍色的 Agent Task Board 視覺，原生桌面視窗，不需要 Python 或輸入指令；選用 AI 時才會開啟瀏覽器供官方登入。程式資料預設在 EXE 旁的 `MCTranslatorData/`，原檔備份在其 `output/<名稱>/原始備份/`；目錄不可寫入時改用 `%LOCALAPPDATA%/MCTranslator/`。移動 EXE 時請一併移動資料資料夾以保留歷史；不要把內含個人登入資料的資料夾分享給別人。

這一版能掃描整包與比對免費中文來源；可選擇連接 ChatGPT／Codex 補翻語系與書本缺漏。一鍵模式會套用支援格式中通過自動檢查的候選，保留自動檢查與人工校對的區別，不保證語意正確。JAR 套用需要可用的 Java 及關閉相關遊戲。首次翻譯需網路更新參考庫；更新失敗會停止，保留掃描報告。報告在掃描完成後即可預覽，套用失敗不會讓結果消失；重開程式會載入最近紀錄。

#### 選用 AI 補翻與模型

1. 開啟「AI 帳號與模型」。若沒有 Codex，按「安裝官方元件」即可（需下載約數百 MB，不必輸入指令）。
2. 按「連接 ChatGPT」，閱讀額度與資料傳送提醒，在官方網頁登入。
3. 選擇帳號實際可用的模型；模型會影響上下文與術語判斷，但不保證正確。本專案尚無模型翻譯品質排行榜。
4. 完成來源掃描後，在「翻譯報告」按「AI 補翻缺漏」。再次確認模型、筆數及額度提醒後才會送出。

**會消耗你原本 ChatGPT 方案的 Codex 額度，與其他 Codex 工作共用，不是額外贈送的免費額度。不同模型消耗可能不同。** 程式不使用 API key、不另收 API 費、不自動加購或切換付費模式。為避免額外消耗，僅支援可確認的個人方案；額外點數可用、企業點數方案、資料缺漏或額度剩餘 10% 以下時保守停止。這不是供應商端的費用鎖，其他裝置並行使用仍可能改變額度。

只傳送待補翻原文、語系鍵及模組相對路徑給 OpenAI，不傳整包與存檔。登入由官方元件管理，獨立資料在 `MCTranslatorData/codex-account/`；本程式不讀取其中 token。按「登出」只登出本程式連接。不要分享此資料夾。

每批最多 12 筆／6,000 原文字元，完成即保存。停止或額度不足時保留先前譯文；已送出的請求可能已消耗額度，不自動重送。譯文保留模型、AI 來源及疑點；不會自動當成人工已確認。模型失效時請重新整理並選擇，不會偷偷切換。Gemini 與 Claude 尚未串接。

官方協定依據：[Codex App Server](https://learn.chatgpt.com/docs/app-server)、[登入方式](https://learn.chatgpt.com/docs/auth)。

開啟程式會在背景檢查版本，也可手動按「檢查更新」。有新版會顯示提示，使用者自行決定是否下載安裝。更新校驗失敗保留原程式，更新不動遊戲、備份和設定。更新來源是此專案 GitHub 公開 Release；只推送原始碼不會產生可下載更新，必須成功發布 EXE 與校驗檔。

開發者打包方式：

```powershell
python -m pip install -r requirements-desktop.txt
python scripts/package_desktop.py
```

產物為 `dist/MCTranslator.exe`。正式發布更新時，將版本號更新後建立 `vX.Y.Z` 標籤並推送；GitHub Actions 會自動打包 EXE、產生 `SHA256SUMS.txt` 並建立公開 Release。Release 附件需要同名 EXE 和 SHA-256 校驗檔，更新器會先驗證大小、格式與雜湊才替換。不把 private instance、cache、backup 或帳號資料打包進 EXE。

### 原始碼工具

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

這個 CLI 找不到來源時仍會保留英文並列入待審；代理必須接續完成 AI 補譯與校對。CLI 不會自動呼叫模型；桌面版的 AI 補翻是另外經使用者同意的 ChatGPT／Codex 訂閱連接，不是付費翻譯 API。

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
