# 專案作業規則

## 範圍與目前偏好
- 預設以繁體中文回覆；譯文使用自然台灣用語。
- 整個 instance 翻譯預設涵蓋 `mods`、`kubejs`、`config`／`defaultconfigs`、`resourcepacks`、`datapacks`、任務、Patchouli／外部書本及其他玩家可見文字；不得只處理 `mods`，除非使用者明確限定範圍。
- 使用者提供的路徑就是翻譯與最終套用位置；預設由代理先備份，再直接更新該位置，不要求使用者複製輸出檔回去。操作前核對當次指定的絕對路徑；已提供清楚路徑時不重複詢問。近期指定為 `C:/Users/User/curseforge/minecraft/Instances/Tensura Neo Otherworld`。
- 使用者給出位置並要求翻譯，即授權完成整包掃描、來源查找、AI 補譯、校對、備份、驗證、直接套用及最終報告。正常的分批處理是內部步驟，不得做完一批就結束並等待使用者再說「繼續」。只有確實需要使用者介入的阻礙（例如相關遊戲鎖檔、權限拒絕、來源損壞或無法確認最新參考庫）才停下說明；先完成不受阻的工作，不得假稱整包完成。
- 每批套用前，將所有將被修改的真正原檔備份到 `output/<名稱>/原始備份/<時間戳>/`，保留相對目錄結構，先驗證全部備份雜湊再寫回。每批使用新目錄，禁止覆蓋先前備份。這是「受影響原檔備份」，不是完整 instance／存檔備份。
- 備份清冊保存 instance 絕對路徑、每檔修改前後 SHA-256、原本不存在的新增檔、套用狀態與還原資訊。新增檔沒有原檔可備份，須明列，避免只複製備份後仍殘留翻譯覆蓋。
- `input/` 與既有輸出僅作歷史參考，不再要求使用者先把整包放入 input。必要的翻譯候選放 `tmp/<名稱>/<批次>/` 或獨立待審目錄，報告放 `output/<名稱>/報告/<批次>/`；候選不是交付成品，不要求使用者搬移。
- 使用者已取消分享檔案：後續只更新指定 instance 與本機報告，不自動同步、重建或交付補丁／ZIP；不自行刪除既有分享檔。只有重新要求分享時才恢復。
- 批次腳本可能含固定路徑、來源雜湊與既定修正清單；執行前檢查，不能盲目重跑。
- 執行完整翻譯時，先稽核整個 instance，再按目錄分階段產生候選、校對與驗證；通過後備份真正原檔並直接套用指定位置。每階段完成後合併清冊、重掃實際 instance，明確回報尚未涵蓋的檔案類型。直接套用不代表略過內容校對或驗證。
- 不同 instance 的輸出、備份、報告與候選必須分開命名；過去 VEFV2.7.1 或其他 instance 的輸出不得當作目前 instance 的翻譯來源。完成新 instance 後，舊產物只保留參考庫、已確認翻譯記憶與必要稽核證據，其餘列入清理清單。
- 優先使用免費、本機或既有參考來源。上述來源缺漏時，由目前對話中的 AI 依上下文直接補譯，標記 `ai_translation`；「沒有參考來源」本身不再是留下整批英文並停止的理由。這不授權呼叫 Google／DeepL／Claude 或其他外部翻譯 API。
- 本專案的外部翻譯引擎與 API key 命令列參數仍停用；`--engine` 僅允許 `none`。CLI 留下的未翻內容須由代理接續補譯、校對和驗證，不得把舊 CLI 的保留原文行為當成完整流程已完成。
- 每次翻譯開始前必須先完成參考庫預檢：更新並記錄 ModsTranslationPack 最新 main commit、CFPA 最新 autobuild 資產時間／雜湊及條目數；無法確認最新時停止正式翻譯並明確回報，不得沿用舊資料冒充最新。
- 正式輸出必須保留逐筆來源標記；未人工確認的自動轉換、參考庫命中或 API 候選不得標為 `manual`，也不得在未通過 verify 前套用 instance。

## 翻譯來源與品質
- 每次翻譯前更新參考庫：`TeamKugimiya/ModsTranslationPack` 最新 main 對應 `data/ref_pack.json`；`CFPAOrg/Minecraft-Mod-Language-Package` 最新 autobuild 資產對應 `data/cfpa_zh_cn.zip`／`cfpa_cache.json`。重建 scoped／合併快取，記錄 commit、資產時間或雜湊及實際條目數。固定 tag、日期或舊條目數不能證明最新；無法確認時如實回報。
- 每個 key 必須依序查找，禁止跳過前一層：
  1. 同一檔案、同一模組版本、同一 namespace 的可信 zh_tw；
  2. 同一檔案、同一模組版本、同一 namespace 的 zh_cn，先以 `s2twp` 轉繁，再依台灣術語與上下文人工校正；
  3. 最新繁中參考庫／同 namespace CFPA；
  4. 已人工確認的翻譯記憶 `data/approved_translation_memory.json`；
  5. Minecraft 術語表；
  6. 上述來源都沒有時，由目前對話中的 AI 根據同模組語境、英文語意與術語補譯，標記 `ai_translation`，再逐項校對。低信心的合理譯法可在通過內容與格式檢查後套用，並在最終報告指出疑點；真正無法辨識的文字、非顯示字串或機器識別值不得硬翻，須記錄保留原因。
  同一 instance 的 KubeJS／資源包／OpenLoader zh_cn 必須納入整包流程的來源鏈；核對模組、namespace、key，不能混用不同模組的通用 key。每次翻譯報告必須記錄各來源命中數，API 數量必須為 0。
- 衝突依版本、來源距離與英文語意判斷。既有 zh_tw 若仍為英文、簡體或錯譯，不算可用翻譯；不確定或機翻不自然時重查簡中。
- 簡中轉繁與參考庫不是準確保證，同樣要校對版本差異、台灣用語、名稱一致性與語意。來源類別與信心／校對狀態分開記錄；AI 自行產生或自行校對的內容不能冒稱人工譯者確認，也不能改掉其 AI 來源標記。
- 保留格式碼、換行、佔位符與參數順序；簡轉繁後校對語境、台灣術語及 prefix/suffix 拼接結果，不能只轉字形。
- 物品、方塊、提示、書本、任務等玩家文字須翻譯。模組名通常保留；按鍵、縮寫、作者／歌曲名等合理英文逐項判定，不因此略過整句。
- 不翻 registry ID、NBT／設定鍵、結構檔名、StructureName（即使含中文）、UUID、色碼、URL、指令結構。價格、數量、解鎖條件、大小寫與 NBT 型別保持不變。
- 術語及模組案例見 [詳細參考](docs/translation-reference.md)，處理相應模組時讀取相關段落。

## 全面掃描與完成判定
- 整包翻譯或全面檢查先跑 `python scripts/full_translation_audit.py <instance> --output <報告目錄>`，修改後重掃實際 instance，保留逐檔清冊、逐筆文字、待查與錯誤清單。
- 檢查 en_us／zh_cn／zh_tw key 聯集；沒有 en_us 但只有 zh_cn 的語系檔仍必須建立或更新 zh_tw。繁中內的英文、中英混雜、簡體、錯詞、格式及佔位符錯誤也列為待處理。
- 範圍包括所有 mods JAR、資源包、KubeJS assets/data／腳本顯示文字、config/defaultconfigs、任務、外部書本、存檔中的 FTB Quests 覆蓋及 class 字串候選。不能只修截圖或要求使用者逐條找漏翻。
- 書本涵蓋 assets/data 下 patchouli_books、book、books 的 en_us JSON／TXT，entries/categories 及語言目錄外 book.json 的 name、landing_text、subtitle；產生對應 zh_tw 路徑。
- KubeJS 的 lang/zh_cn.json 或 en_us.json 須補 zh_tw.json；zh_cn/*.txt 須補對應 zh_tw/*.txt。armorsets 的 customTooltips 與 bonus description 等非語系文字也須檢查。
- 商店須查 config/SDMShop 分類 title、多行 description、商品 NBT display.Name／Lore 的內嵌 JSON；二進位 .data 必須辨識並解析，失敗列入錯誤。不得修改 translate key、共用設定以外的玩家交易／進度。
- 不以 rg 搜壓縮 JAR 或少數中文字篩選代替資源／class 提取。動態文字與未涵蓋格式留在待查清單，不能視為已檢查。
- 人工判定綁定來源路徑、key／欄位、原文與譯文 fingerprint；來源改變重新校對。自動來源命中、OpenCC 或 API 翻譯不能標為人工完成。
- `zh_cn → zh_tw` 不得只做字形轉換後直接宣稱完成；必須保留來源標記，逐項檢查台灣詞彙、專有名詞、格式碼、換行與佔位符。報告至少分開列出 `same_source_zh_cn`、`instance_zh_cn`、`translation_memory`、`reference_pack_or_cfpa`、`glossary`、`ai_translation`、`api` 及 `manual` 數量；AI 審核狀態另列，不據此把來源改成 manual。
- 分開回報掃描範圍、修正數、剩餘項與實測範圍。missing=0、verify 通過或掃過每個檔案，不等於整包翻完；未通過內容、格式及資源驗證閘門只能回報部分完成。

## 定位顯示問題
- 先查 options.txt 的 lang、啟用資源包、重複 JAR、重啟／重載狀態；跨 namespace 搜相同 key 的覆蓋。可選資源包不視為必定啟用，順序不明記錄未確認。
- 畫面顯示語系鍵時追查程式組法。nsprefab 使用 item.nsprefab.<StructureName>，以同結構商品／任務的可信中文名稱補對應；保留 ID，檢查整組結構與名稱衝突。
- 語系找不到時查 class 使用位置與動態組句；literal 不會被新增語系檔覆蓋。修改 bytecode 前必讀詳細參考的「硬編碼文字」。
- 優先修正錯誤來源；需要相容覆蓋才用 kubejs/assets/<namespace>/lang/zh_tw.json，只有證據顯示讀取 zh_cn 才同步該語系。
- 不改 KubeJS server/startup 程式邏輯；確認是玩家文字才改字串。嵌入 JSON 的機器欄位與所有非顯示內容須比對不變。

## 套用與驗證
- 修改 instance JAR 前確認使用該 instance 的 Minecraft／Java 已關閉；不能把其他伺服器或工具的 Java 程序直接判作該 instance 正在使用。無法確認或檔案鎖定時請使用者關閉相關遊戲，不能自行結束程序。關閉時優先寫回 JAR，開啟時可先使用已校對的暫時語系覆蓋；覆蓋也必須備份及登記新增檔，後續合併時確認不再需要才移除。
- 套用前備份真正原檔並記錄雜湊，套用後讀回全部改動、核對覆蓋衝突。來源或候選在驗證後改變則停止套用；寫入失敗要保留備份與失敗清冊，能安全還原的本批改動自動還原。通用檔案套用使用 `mc_zh_tw_translator.deployment.apply_reviewed`；此函式只負責備份、雜湊檢查、寫回與失敗還原，不能代替翻譯審核、Java／資源驗證或遊戲狀態確認。只清理確認相關的 LightSpeed／resource cache；找不到就記錄，不刪無關快取。
- 修改 JAR 移除 META-INF/*.SF、*.RSA、*.DSA、*.EC 失效簽章。無翻譯內容的 JAR 原樣複製，輸入輸出檔案數一致。
- 翻譯命令只允許 `--engine none`；其缺漏交由目前對話 AI 補譯後接續校對與套用。不得藉一次完成的要求跳過驗證、改動機器欄位或捏造來源。
- JAR 候選套用前以當次真正原檔執行 `verify <候選 mods 目錄> --input <原始 mods 目錄>`；套用後執行 `verify <instance>/mods`，並對修改過的 JAR 逐檔執行 `verify <instance>/mods/<檔名.jar> --input output/<名稱>/原始備份/<時間戳>/mods/<檔名.jar>`。驗證器目前只讀指定目錄直屬 JAR，不能把 instance 根目錄當 mods 目錄。備份只含修改檔時應逐檔比對，不可拿輸出當原始輸入。
- 必須通過 Java ZipFS 與書本覆蓋檢查；Python zipfile 或 jar tf 不能代替。啟動失敗先讀最新 latest.log／stdout-logs.txt，再逐一驗證 instance JAR。
- 規則更新不能代替程式落實；掃描器未涵蓋項明確列出，不宣稱已全面防止漏翻。
- 還原時先核對清冊及目前檔案是否仍為本批套用雜湊，避免覆蓋使用者後來的修改。還原既有檔，並僅移除清冊記錄且雜湊相符的本批新增檔；有其他修改時先回報衝突。不要把備份內 `_備份紀錄` 複製進遊戲。
- 最終用白話回報「已直接套用什麼、備份在哪裡、還剩什麼、是否需要重啟」，不把候選筆數或缺少語系鍵數當成翻譯完成率。舊 CLI `translate` 是候選產生工具，不是整包遞迴翻譯／直接套用工具，不得把其成功結束當作已更新 instance。

## 最終翻譯品質報告
- 每次整包作業結束，在 `output/<名稱>/報告/<批次>/` 產生容易閱讀的 PDF 品質報告，並保留可搜尋的完整明細（JSON／CSV）。PDF 生成須依 PDF 技能完成中文字型與渲染檢查；若環境無法產生，交付可讀的 Markdown／HTML 並如實說明，不假稱有 PDF。
- 開頭以白話說明已套用範圍、備份位置、實測範圍與剩餘阻礙；列各類來源數量。Google／其他外部翻譯 API 未使用就明寫「未使用（0 筆）」，不能把 AI 補譯標成 Google 翻譯。
- 報告逐筆列出 AI 補譯，以及不論來源為何的低信心或衝突項目，包含模組／檔案／key、原文、最終譯文、來源、疑點、校對狀態與是否已套用。無疑點的簡中或參考庫譯文可統計摘要，完整來源仍留在明細。
- 不確定度使用有理由的分類（例如名稱待核對、版本語意差異、缺少遊戲畫面），不杜撰準確率。報告供使用者知情與後續修正，不把每條不確定譯文都變成阻塞整包交付的確認問題。

## 分享作業（僅使用者重新要求時）
- 補丁保持 mods/kubejs/config 相對路徑，只收中文化必要檔；排除 saves、交易／進度、帳號、options.txt、伺服器清單、地圖、日誌及個人材質／光影。腳本須證明只有文字改動。
- 說明寫清楚：先裝完整同版本模組包、關閉遊戲、合併資料夾並取代同名檔；不刪原資料夾，不把補丁當成可裝入空白 Forge 的完整包。
- 重算每檔大小、數量與 SHA-256，新增 JAR 保留真正原始驗證輸入。完成當前 JAR 驗證後逐項讀 ZIP 核對路徑與雜湊，產生 ZIP 校驗碼；不能沿用舊驗證紀錄。
