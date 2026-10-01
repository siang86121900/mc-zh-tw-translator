# 翻譯案例與技術參考

配合根目錄 AGENTS.md 使用；遇到相應模組或修改 class 時，先讀相關段落。案例不能當成不分版本的自動替換白名單。

## 術語與自然組句

  - `爬行者`、`爬山虎` -> `苦力怕`
  - `觸及金子` / `Gold Touched` -> `點金之觸`
  - 按鍵名稱 `SHIFT` 不可翻成 `轉移`
  - `冰冰龍鋼` -> `冰龍鋼`
  - `礦石Tnt` -> `礦石 TNT`
  - `打蠟凸凸` -> `盈凸月`
  - `蠟新月` -> `盈月眉月`
  - `石灰注入織物`、`注入佈藝` -> 依語境改為 `淺綠色灌注織物`、`灌注織物`
  - `萬裡` -> `萬里`
- 不要把所有命中簡體字的內容都硬改；像 `生物`、`速度`、`玩家` 本身是繁中也常用的詞。先修高可信錯詞，再把低可信項留給人工語境判斷。
- `Creeper Spores` 這類模組或整合項若會直接顯示給玩家，繁中優先用「苦力怕孢子」，不要保留「爬行者」。
- `Ice and Fire` 常見術語：
  - `Ice Dragonsteel` -> `冰龍鋼`
  - `Fire Dragonsteel` -> `火龍鋼`
  - `Lightning Dragonsteel` -> `閃電龍鋼`
  - `Sea Serpent Armor` 的水中效果要翻成自然描述，例如「潮濕時提供力量效果，穿著全套時效果等級提高」。
- `Weapon Master` 類型文字若出現 `overweight`，不要直譯成奇怪的「超重型清潔器」；依語境可用「重型」「橫掃」「精準」等自然武器分類。
- `Tetra` 的 multi schematic 說明不要保留「的一部分...一起放」這類直翻，應改成「此項屬於多方塊結構圖。將它與同一張結構圖的其他完好部件一同放置...」。


## 已知漏翻與覆蓋案例


- 翻譯與掃描都必須以 `en_us`、`zh_cn`、`zh_tw` 的 key 聯集為基礎，不能只遍歷英文檔。只有簡中檔存在的玩家可見 key 也要補翻；例如 `tooltip.xiangcaomengjia.bulk_bonus_hint`、`variety_bonus_hint`。沒有英文時，以相符的中文來源檢查佔位符與語意，不可直接略過。
- 不能用「值包含任意中文字」判定翻譯完成。`Holds:藥水…` 這類中英混雜值仍須處理；按鍵、模組名等合理英文應逐段判斷，不可因此放過整句操作提示。
- 查找中文來源時，要納入同一 instance 中與模組版本、namespace 和 key 相符的 KubeJS／資源包中文，並確認它是否為整合包刻意覆寫的名稱；不可只查 JAR。例如 Mineral Delight 有部分中文放在 `kubejs/assets/mineraldelight/lang/zh_cn.json`。
- 區分「參考譯文的 namespace 配對」與「遊戲載入後相同 key 的覆蓋」。一般語言資源合併時，不同 namespace 的檔案也可能提供相同 key；必須跨模組搜尋衝突。例如 Lightman's Currency 曾在自己的 `zh_tw.json` 中把 `item.minecraft.smithing_template` 覆蓋為英文，不能只修截圖標示的 Ultramarine。
- 提取 namespace 必須依實際 `assets/<namespace>/lang/...` 路徑解析；JAR 內附的可選資源包需另記路徑及啟用狀態，不能固定取整條路徑的第二段或把可選資源包視為必定生效。
- 畫面顯示原始語系鍵或中英混合的 key 時，先追查程式如何組出該 key。不得翻譯 registry ID、NBT 欄位或其他機器識別值。Untamed Wilds 4.0.4 的 `EntityUtils.getRegistryName` 使用翻譯後的生物名稱組瓶裝物品 key；可保留原 key 並補對應的相容鍵，但必須依真正的生物種類與所有變種建立，不能把變種名稱誤當種類，也不能只補截圖那一瓶。
- 修正一個案例後，要檢查同模組同類文字：例如整組套索、冰淇淋及效果、家具操作提示、瓶裝生物變種。不可用截圖案例通過代替整組檢查。
- 交付前從實際 instance 讀回改動，跨 JAR、資源包與 KubeJS 核對相同 key 的衝突，依啟用狀態與載入順序判斷最終值；順序不明就記錄未確認。保留修改前後差異及備份，修改過的 JAR 另用真正的修改前備份執行 `verify --input`，不可把輸出本身當作輸入證明未損壞。
- 規則文件與靜態掃描不是完成證明。新增上述規則後，仍須確認實際翻譯／掃描程式有落實；未涵蓋的檢查明確記錄，不可因更新了 `AGENTS.md` 就宣稱漏翻已全面防止。

- CraftTweaker 腳本（`scripts/*.zs`）的 `addTooltip`、`setDisplayName` 等直接寫字串。Chapter of Yuusha v3.13.15 的 129 個腳本中 128 個含簡中提示（約 5,000 句），v0.20.2 以前完全沒掃描。現在簡體在原檔轉台灣用語；`§` 等跳脫字元保留原樣；註解與 `/* */` 區塊、`{"鍵": 值}` 的鍵不改；英文字串列待查。
- TACZ 1.1.4 的 `GunPackLoader` 是 `RepositorySource`，`tacz/<槍械包>/assets/<ns>/lang/` 會當一般資源包語系檔讀取；車萬女僕 1.5 的 `LanguageLoader` 讀 `tlm_custom_pack/<包>/assets/<ns>/lang/<語言代碼>.json`。缺 zh_tw 時在該包裡新增 zh_tw.json。TACZ 顯示設定的 `text_show.*.text`（槍身上印的品牌字）是畫面文字，簡體原地轉換；模型檔的 `identifier`、動畫骨架名稱不是。
- Patchouli 1.20.1-84 的 `Book` 讀取 `name` 與 `landing_text`，`GuiBookLanding` 以 `Component.translatable` 顯示（javap 查證）。Simply Swords 的 Runic Grimoire 把英文直接寫在 `data/simplyswords/patchouli_books/runic_grimoire/book.json`，所以以英文原句為鍵寫入翻譯資源包。首頁的「1st版」是 Patchouli 自己的序數加上它內建繁中的「版」。
- Call of Yucatán 1.0.13（MCreator）把「While Kukulkan's Bless is Applied:」等提示用 `Component.literal` 寫在 class（`AncientGoldPillarBlock` 等 7 個），沒有語系鍵；CurseForge 整合包會把改過的模組檔換回原版，因此無法安全翻譯，報告列在「無法寫入」。
- Apotheosis 的 `config/apotheosis/names.cfg`（Forge 舊式清單，每行一個名字，用來隨機組成名稱）與 yzzz-fix 的 `.yaml` 標籤含簡中，原地轉換。

## 硬編碼文字（修改 class 前必讀）

- APP 的通用支援由 `class_text.py` 實作：逐個 class 檢查每次載入同一常數的位置，僅接受直接 literal 呼叫或 Forge／NeoForge Builder.comment（單字串與直接建立的字串陣列）。private static final 的內嵌常數須沒有欄位存取；公開常數、註解與 bootstrap 引用仍拒絕。其他 bytecode 資料流不能套用此證據。
- 改寫後保留常數索引及非翻譯內容，使用隨 APP 附帶的 ClassTextCheck Java 解析器與 Java ZipFS 驗證；解析不執行模組，不等於遊戲內實測。掃描快取版本變更會重查舊候選。class 修改不放入分享補丁。
- 設定說明的語系鍵（2026-10-01 以位元碼查證）：NeoForge 21.1.244 的 `ConfigurationScreen$ConfigurationSectionScreen.getTooltipComponent` 以 `translatableWithFallback(<key>.tooltip, comment)` 顯示說明，`getTranslationKey` 先用 `ValueSpec.getTranslationKey()`（模組呼叫 `Builder.translation` 的值），沒有時用 `<modId>.configuration.<設定名稱>`。Configured（Forge 1.20.1 2.2.3、NeoForge 1.21.1 2.6.3）的 `ForgeValue`／`NeoForgeValue.getComment` 只在 `I18n.exists(<translationKey>.tooltip)` 時改用語系檔，沒有模組語系鍵時一律顯示 comment；Configured 只替沒有 `IConfigScreenFactory` 的模組產生畫面，不蓋掉模組註冊的 ConfigurationScreen。ForgeConfigScreens 8.0.2 直接顯示 comment，不查語系檔。Forge 本身沒有通用設定畫面（只有 ConfigScreenHandler）。
- `class_text.config_tooltips` 只接受直線鏈：`comment` →（`translation`／`worldRestart`／`gameRestart`）→ 名稱常數 → `define*`，中間只允許把 builder 放回堆疊的指令、不跨分支目標；`push` 的分區說明、名稱不是常數的設定都不連結。預設鍵另須該模組檔引用 ConfigurationScreen 且只宣告一個 modId。掃描快取版本 scan-7。不同設定共用同一語系鍵但原文不同時不建立覆蓋；已存在語系條目的鍵交由一般語系流程處理。同鍵候選譯文不一致時停止寫入，避免重跑互相覆蓋。


- 語系檔找不到截圖文字時，必須檢查 JAR 的 `.class` 字串常數與使用位置；例如 PasterDream 的裂隙提示、劇情對話及物品說明直接寫在程式內，新增 `zh_tw.json` 不會取代這些 literal 訊息。
- 可用 `scripts/audit_hardcoded_display.py` 建立候選與用途報告，但執行前先確認腳本指向使用者指定的 instance。目前腳本含固定路徑，不能直接套到其他模組包。掃描所有 class，不可用少數中文字作為前置篩選而漏掉短名稱。
- 用 `javap -c -p` 或等效位元碼分析確認字串的全部使用位置。直接傳入 `Component.literal` 的文字可列入顯示候選；載入提示陣列、GUI 標題、繪字呼叫、格式化數字及動態組句需要追查資料流。混淆名稱與 Fabric 對應方法依實際版本確認，不可把某個方法名稱當成所有版本通用的證據。
- 必須區分玩家顯示文字、設定說明、開發時語系產生器、日誌、識別碼及字串比較。`ForgeConfigSpec.Builder.comment` 的說明可翻譯；`push`、`define` 的設定鍵、NBT 欄位、registry ID、URL、指令結構，以及 `equals`／`contains` 的判斷字串不可直接轉換。相同常數同時用於顯示與判斷時，先解決相容性，不可只憑一次顯示用途就修改。
- `invokedynamic` 組句模板中的 `\u0001`／`\u0002` 是控制字元，必須保留其數量與順序；同時保留格式碼、換行、`%s`／`%.1f` 等參數、DecimalFormat 的 `#`／`0` 模式、數值與單位。指令內的中文標題只能在確認用途後修改標題內容，不能改動 selector 或指令邏輯。
- JVM 常數池使用 Modified UTF-8；處理 NUL、補充平面字元或代理對時必須正確解碼與編碼。不可把解碼失敗的替代字元寫回 JAR。修改常數時更新位元組長度，保留常數索引、其他常數、方法位元碼及 class 屬性。
- 簡轉繁後仍須校對語意與術語，不能直接接受 OpenCC 的每項替換。例如「萬象」不可誤成「永珍」；描述效果區域的「治療立場／狐火立場」應為「治療力場／狐火力場」；「回覆生命」應依語意改為「恢復生命」。保留角色與模組的專有名稱，並與同版本語系、書本用詞核對。
- 先建立綁定 JAR 雜湊、class 路徑及原文的修正清單，再備份並套用。現有 `scripts/apply_hardcoded_display_tw.py` 與 `scripts/fix_pasterdream_crack_text.py` 是特定批次工具，不可盲目重跑或把其中的類別名稱清單當成通用安全白名單；來源版本改變就重新查核。
- 套用後必須讀回全部修正文字、驗證受保護的格式與參數，並比對除預期文字常數及其長度外的 class 內容完全一致。對每個修改過的 class 執行 Java 解析，再執行 instance 的 Java ZipFS 驗證與修改前輸入比對。解析通過不等於所有事件已在遊戲內觸發測試，交付時不得混稱。
- 用途未確認的常數保留在待查清單；開發工具或日誌文字的排除需記錄理由。分別回報常數修改次數、不同原文數、class 數及模組數，不可把重複字串的多處修改稱為相同數量的獨立句子。


