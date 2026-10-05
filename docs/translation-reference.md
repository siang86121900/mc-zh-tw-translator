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
- FancyMenu 版面檔（`config/fancymenu/customization/*.txt`）以沒有引號的 `label = 開始遊戲` 寫按鈕、滑鼠提示（hoverlabel）、說明（description）與文字元件（source），照原樣顯示；`%n%` 是換行、`&e` 是顏色碼。`identifier` 等其他欄位不改。Elemental Awakening、VEF、Tensura 都有簡中按鈕。
- KubeJS 的 `kubejs/config/client.properties` 的 `title=` 是遊戲視窗標題（Elemental Awakening：元素觉醒）。
- Tensura 的 `config/ymktn/welcome.txt` 是 Markdown 純文字，`##` 是標題不是註解；不確定由哪個模組讀取，依 2026-10-02 的放寬規則逐行轉繁並標示未確認。YSM 的 `builtin/notice.txt` 每次啟動重新產生、遊戲不顯示，不改；`blacklist.txt` 只有註解是中文，不改。
- 整合包根目錄的 `data/` 是模組執行時寫的資料：Collective 每次啟動重建 `data/serilum/translations`，寫入會被蓋掉，不處理。
- 同一模組的兩個版本同時放在 mods（Elemental Awakening 的 IMBlocker 5.5.4 與 5.6.2）：Forge／NeoForge 的 UniqueModListBuilder 只載入版本最新的一份，所以只採用那份的語系檔（desktop_jobs.older_copies），否則兩份的譯文會在每次重跑時互相覆蓋。
- Sinytra Connector 會在每台電腦把 Fabric 模組轉成 `mods/.connector/*_mapped_*.jar`，內容與雜湊因電腦而異；原本的模組檔就在 `mods`，所以掃描與分享補丁都只認原檔（desktop_jobs.generated_copy）。v0.21.0 以前的補丁把轉換檔列為必要檔案，Tensura 的 Mebahel 矮人模組在別人電腦會被略過。
- Essential 1.4.1.1（NeoForge 1.21.1，The Pixelmon Modpack）的介面用模組自帶字型畫字：內層 jar 的 `fonts/Minecraft-Regular.json` 只有 95 個字元（U+0020～U+007E），沒有中文也不改用遊戲的備用字型，中文顯示成「□」。字型不在 `assets/` 裡，資源包無法替換；整合包由 CurseForge 管理，改模組檔也會被換回。掃描時 `full_translation_audit.own_font_without_chinese` 讀模組自帶的 `fonts/*.json`（字元清單＋atlas），全部沒有中文字時標記 no_chinese_font（scan-14），讓這類模組的語系文字保留英文、不送 AI，先前寫入的中文改回英文一次（2026-10-02 使用者選擇）。代價是按鍵設定等用遊戲字型顯示的少數 Essential 文字也是英文。主選單上的 singleplayer、quit 等字是 FancyMenu 版面引用的 PNG 圖片，不是文字。
- Whispering Quests 3.2（Forge 1.20.1，Elemental Awakening v1.4.6）的任務在整合包作者自製的 `ysjxmodel-1.0.0.jar` 的 `data/ysjxmodel/whisperingquests/`（tasks 主線 153、支線 42、每日 28，chapters 8），只有簡中。`QuestDataManager`、`ChapterDataManager` 繼承 `SimpleJsonResourceReloadListener`（最上層資料包的同路徑檔案取代下層）；`QuestScreen` 以 `Component.m_237113_`（literal）畫標題、說明，`RewardDisplayUtils.poolNameText` 也是 literal（javap 查證），所以語系檔與資源包都蓋不到。`QuestManager` 只用 title 組完成訊息，存檔只記任務 id。OpenLoader 19.0.5 的 `OpenLoaderRepositorySource` 以 `Pack.Position.TOP`、`PackSource(..., true)` 加入 `config/openloader/data` 裡每個資料包，因此翻譯資料包放在那裡、檔名以 zz 開頭排在整合包自己的 OpenLoader 資料包（yuansujuexing）之後。v0.24.2 以前掃描只讀模組的語系檔、書本與 class，模組裡 `data/` 的任務整類漏掉，報告也沒有紅字；之後模組 `data/` JSON 顯示欄位含中文、沒有讀取器的，依資料夾列為格式尚未支援。同包的 `torchesbecomesunlight` 對話檔 `data/torchesbecomesunlight/dialogue/` 的台詞是語系鍵（已由語系檔翻譯），只有 `description` 欄位是中文、用途未查證，列在格式尚未支援。
- 自然指南針 1.11.2（BiomeUtils.getBiomeName）以 I18n 查「biome.<模組>.<路徑>」，查不到就顯示鍵本身；探險家指南針 1.4.0（StructureUtils.getPrettyStructureName，translateStructureNames 預設開）查「structure.<模組>.<路徑>」，結構的「團體」是結構組（structure_set）的鍵，維度查「dimension.<模組>.<路徑>」，查不到就把代碼的底線換空白、字首大寫。VEFV2.7.1 有 602 個這類名稱（結構 585、維度 14、生態域 3）在所有語系檔都不存在，例如 Jellyfishing 的 ghostly_graveyard、More Critters 的 abandoned_mine、PasterDream 的 lamp_shadow_world。TerraBlender 的 deferred_placeholder 是程式裡註冊的佔位生態域，不在 data 裡，掃描抓不到。
- 2026-10-03 對 7 個真實整合包（COBBLEVERSE、Chapter of Yuusha、Elemental Awakening、Tensura、The Foll、Pixelmon、VEFV2.7.1）做反向盤點：打開每個檔案（含模組檔內兩層），把中文與四字以上英文句子和掃描產生的條目逐檔比對（現為 `scripts/inventory_text.py`）。找到下列從未被發現、報告也沒有紅字的類別，查證依據如下（javap 只讀位元碼，不執行）：
  - 資料檔命名、卻沒有任何語系檔定義的語系鍵：戰利品表的 `set_name`／`set_lore`、進度的 title／description 寫 `{"translate": 鍵, "fallback": 英文}` 或直接拿英文句子當鍵（ATi Structures 的「Uranium Tipped Arrow」）。遊戲找不到鍵就顯示 fallback 或鍵本身，任何語言都是英文；Incendium 5.4.4 整個沒有語系檔，Pixelmon 9.4.1 的研究任務鍵（research.standard.…）也不在語系檔。翻譯資源包加上同一個鍵即可（`Audit.data_keys`），沒有 fallback、本身也不是英文句子的鍵（rechiseled.advancement.….title）沒有可翻的內容，不列。
  - 光影的設定選單：Iris 1.8（Fabric／NeoForge 1.21.1）與 Oculus 1.7／1.8（Forge 1.20.1）的 `LanguageMap` 讀光影包 `shaders/lang/*.lang`，檔名轉小寫、以 UTF-8 的 `Properties.load` 讀（等號兩邊可有空白、`!` 也是註解）；`MixinClientLanguage` 依遊戲目前的語言順序（zh_tw，再 en_us）查表。所以在同一資料夾加 `zh_tw.lang` 就生效；光影程式不在分享補丁內；格式 3 可分享語系文字的逐句紀錄。
  - FancyMenu 版面的英文按鈕與文字：`label`、`hoverlabel`、`description`、`tooltip` 與 `source_mode = direct` 的文字元件 `source` 照字面顯示。圖片的 `source = [source:local]…`、網址不翻；`{"placeholder":…}`、`%#FF5555%` 這類顏色碼、`%n%` 換行與 markdown 連結目標必須原樣保留（`embedded_text.fancymenu_marks`）。英文改成中文不是「只改中文字」，不使用格式 2 的一般中文轉換；格式 3 可分享有用途證明的逐句翻譯，由接收端以自己的原檔重建，不帶整份版面檔。
  - 冰與火的生物圖鑑：`BestiaryScreen` 以 `Options.languageCode` 組出 `lang/bestiary/<語言>_0/<頁>.txt`，經資源管理器讀取，找不到才用 en_us_0。Tensura 的 IceAndFireCE 2.0-beta.15 沒有 zh_tw_0（有 zh_cn_0），所以整本英文。
  - Saint's Dragons 0.9.5 的龍圖鑑：`CodexEcologyPanel` 以 `LanguageManager.getSelected()` 讀 `codex/<語言>/ecology/*.txt`，退回 en_us。
  - Chrono Dawn 0.8.0 的 Chronicle：`ChronicleData` 經資源管理器讀 `assets/chronodawn/chronicle/`，每段文字是 `{"en_us": …, "ja_jp": …}`，`LocalizedText.get` 以 `getOrDefault(語言代碼, en_us)` 取字，所以加 `zh_tw` 欄位即可。
  - foxablazeaqzl_wiki 1.0.2.5（Tensura）：`FoxItemWikiData.languageKey` 遇到 zh 開頭的語言一律取 `zh_cn`（或 `zh`）欄位，所以遊戲設繁中時顯示簡體；把那個欄位轉成台灣繁體寫進翻譯資源包（`full_translation_audit.INLINE_FIELDS`）。
  - Pixelmon 9.4.1 NPC：`OpenDialogueInteractionResult`／`OpenPagedDialogueInteractionResult` 把 title、message、pages 交給 `DialogueFactory.Builder.title/description`，兩者都是 `Component.translatable`，所以以英文句子為鍵的語系條目就會顯示中文。含 `%` 的句子會被當成格式，不列。
  - Cobblemon 1.7.3 對話（`data/<模組>/dialogues/`）：`DialogueTextAdapter` 把字串行轉成 `asTranslated`（`Component.translatable`），lines 與選項 text 同樣以句子為鍵；MoLang 運算式不是文字。
  - Apotheosis 7.4.3 小頭目：`ApothMiniboss` 以 `Component.translatable(name)` 設定頭上的名字，只取檔案最上層的 `name`。
  - 資料包任務：Slime Throne Extras 2.0.9 的 `st_quests` 名稱（`STPrestigeScreens` 與完成訊息 `stextras.quest.completed` 的參數）、Monster Expansion 0.7.6 的 `quest_data`（name、objective、description、display_name）與 `monsterology`（title、type、lore、fighting_tips），都由 `SimpleJsonResourceReloadListener` 從資料包讀、用遊戲字型照字面畫，和 Whispering Quests 一樣寫進翻譯資料包（`DATA_TEXT_FORMATS`）。
  - OpenLoader 21.1.5（NeoForge 1.21.1，Tensura）的 `OpenLoaderRepositorySource` 只讀 `config/openloader/packs`（與 datapacks 資料夾），依內容判斷資料包（有 data/），以 `PackSelectionConfig(必載, TOP)` 加入；`config/openloader/options.json` 的 `load_data_packs` 可關閉。舊版 19.0.x 讀 `config/openloader/data`。翻譯資料包依整合包裡有的資料夾決定位置（`desktop_jobs.data_pack_file`）；v0.29 以前在 1.21 整合包一律列為沒有 OpenLoader。
  - 保留英文：Beyond Adventures 1.1.9 的任務名稱（`MissionsScreen`）與召喚說明（`InfoScreen` 讀 `info_text/text.txt`）用模組自己的點陣字型 `beyond_gacha_c:tensura_*`，字型只有英文小寫字母與數字，中文會變成方框（`desktop_jobs.KEEP_ENGLISH_FORMATS`）。
  - 尚未處理：The Foll 的 Age of Mythology 資料檔裡的簡體名稱（tarot_city、parallel_world_events 的 alias）用途未查清，可能被程式拿來比對，維持紅字；saintsdragons 的 `data/saintsdragons/ivy_chatter/*.txt`（NPC 閒聊）是伺服器端純文字、不分語言，尚未有讀取器；YSM 的 `config/yes_steve_model/builtin/` 動作名稱由模組產生，未確認改了會不會被蓋回。
  - 不是玩家文字（盤點時判定）：設定檔註解、授權與更新記錄、拼音字典（JECharacters 的 `data.txt`）、寶可夢對戰引擎 showdown 的 JS、其他語言的檔案、翻譯包裡給沒安裝模組的頁面、FTB Quests 的 `quests-backup`、動作檔的開發描述、Xaero 的範例圖示設定。
  - v0.31.0 盤點（2026-10-03）另判定：TaCZ 槍包 JSON 的 `//` 註解、TaCZ 的 Lua 腳本與 `geo_models` 名稱（scar_h - 副本）、TLM 女僕模型動作檔的運算式與 `settings/*.yml` 提示詞註解、函式庫資料（ICU `com/ibm/icu/...`、Apache codec `language/bm/*.txt`）、`loot_modifiers` 的分類標籤（Changes, Loot）、非標準檔名的其他語言檔（`uk-ua.json`、`ru_ru[INVALID_CONVENTIONS].json`）都不是玩家文字。Alex's Caves 的 `books/tok/`（Toki Pona）、光影包的 `CONTRIBUTORS.md`、Better Modlist 的 `an-ES`／`bn-BD` 等其他語言檔、`optifine/ctm` 的 properties 也不是。待決定：`assets/*/texts/` 的標題畫面隨機標語（Dungeons Delight `splashes.txt`、Alex's Caves `end.txt`）沒有讀取器；原版的標語在任何語言都顯示英文，是否翻譯尚未請使用者決定（v0.30.0 起就存在，非 v0.31.0 造成）。盤點列出但已涵蓋：模組書的 `zh_cn/` 頁（掃描以 `en_us/` 頁建立條目、取簡中轉繁：Apotheosis Patchouli 512 筆、Goety black_book 1,915 筆、Dimensional Dungeons 115 筆、Alex's Mobs 動物圖鑑 273 筆、冰與火的 Tinkers 頁 12 筆、Mortal Cultivation 修仙指南 173 筆、辣條工藝 2 指南 43 筆、暮色風味樂事指南 36 筆；VEFV 的 Alex's Mobs 動物圖鑑模組自帶 zh_tw 91 頁）；模組內嵌的函式庫語系檔（fabric-resource-loader-v0 每個副本、LambDynamicLights 裡的 SpruceUI 都已自帶 zh_tw）；Incendium 的 `1-21-*-overlay` 戰利品表 `translate`＋`fallback`（Audit.data_keys 補語系條目）。
  - 防漏：模組 `assets/<模組>/<種類>/` 的 JSON、txt、md 有句子卻沒有讀取器產生條目時，每個資料夾列一筆格式尚未支援（`Audit.unsupported_assets`）；遊戲資料種類（models、sounds、font…）與其他語言的副本不讀。
- v0.32.0 盤點（2026-10-03，逐個文字位置比對）新增與查證：
  - VillagerConfig 4.5.4（Fabric 1.21.1，COBBLEVERSE）的 `TradeManager` 讀 `data/<ns>/trades/*.json`，交易結果是原版戰利品物品項目；`set_name` 直接寫字串（`"name": "§7Brock's Gym"`）是照字面顯示的文字元件。戰利品表與交易的 `set_name`／`set_lore` 純字串現在也翻譯（`embedded_text.plain_loot_spans`，位置記為 `["plain", n]`，原本 `{"text"}` 的位置不變）；項目自己的 `"name": "minecraft:map"` 與地圖的 `destination` 是代碼。
  - 進度的 `display.title`／`description` 直接寫字串（Beautify 2.0.2 的「Blinded by the lights」，VEFV2.7.1 約 110 處）同樣是照字面的元件，一併讀取；Treasure Bags 1.9.0 的 `BagType$Serializer` 以 `Component.Serializer` 讀 `treasurebags_types/*.json` 的 `displayName`，是寶藏袋的名稱。
  - REI 16.0.799 的 `CollapsibleEntryRegistryImpl` 把 `config/roughlyenoughitems/collapsible.json5` 每個自訂分組的 `name` 以 `Component.literal` 顯示在收合的物品組上；分組以 `id`（custom:<uuid>）辨識，所以名稱可原地翻譯（`embedded_text.rei_units`）。
  - 結構檔裡 1.20.5 以前格式的書（`Book.tag.title`／`tag.pages`）：遊戲的資料修正器轉成 written_book_content 時，不是 JSON 的頁面當成照字面的文字。Pixelmon 9.4.1 的 `boats/boat_pirate.nbt` 海盜日記因此漏掉，現在純文字頁與 JSON 頁都讀。
  - Capsule 1.20.1 的藍圖膠囊：`capsule-common.toml` 的 `lootTemplatesPaths`（config/capsule/loot/common…）、`starterTemplatesPath`、`prefabsTemplatesPath`、`rewardTemplatesPath` 指向 `config/capsule/` 下的建築檔，放出膠囊時把建築連同裡面的書與告示牌放進世界（Chapter of Yuusha 的「Blueprint Capsules」書）。現在當成建築檔讀取並原地寫入；模組檔裡的 `data/capsule/initialconfig/` 只是第一次啟動時複製到 config 的種子，不翻。
  - 建築檔裡直接存成純文字、沒有 JSON 引號的名稱（cobblemon-additions 4.1.6 商店店員的 `CustomName` "Arborist"、Repurposed Structures 物品的 "Dry Whisky"）：遊戲寬鬆解析成同一段文字。以前讀取器只認 JSON 元件而跳過；現在照樣讀取，寫回時存成 JSON 字串（加引號），遊戲一定讀得懂。判斷依據是「不是合法 JSON」，不看第一個字元：CTOV 的「[Energy Detector]」看起來像陣列、Dungeons Arise 的書頁是好幾段各自加引號的句子，都不是 JSON。NBT 清單與陣列長度的上限改為檔案本身的大小（每個元素至少一個位元組），Dungeons Arise 的 keep_kayra_main_0（3.8 MB）超過舊的 100 萬上限而被當成壞檔。
  - 少了 gzip 結尾標記的建築檔（Oh The Biomes We've Gone 1.5.11、Dungeons Arise 2.1.58，VEFV2.7.1 有 211 個）：遊戲的 NbtIo 讀到 NBT 結束就停，照樣讀得到；以前掃描與盤點都整檔放棄，裡面的告示牌與書本因此沒被讀。現在讀取與寫回都接受（`full_translation_audit.gunzip`），內容本身截斷的仍算讀取失敗。
  - FancyMenu 文字元件裡佔位符的參數（`{"placeholder":"json",…"source":"…/update.json"}`）不再讓整句被當成檔案路徑跳過（Pixelmon 主選單的 Installed／Latest Pixelmon）。
  - owo-lib 0.12 的豐富語系值（值是 `{"text": …, "color": "gray"}` 這類文字元件）以前被掃描整筆丟掉、報告也沒有紅字；現在列為格式尚未支援。COBBLEVERSE 只有 6 句，其中玩家看得到的是創造模式物品欄的 Shift 多選提示。
  - 保留英文並以灰字說明（`desktop_jobs.KEEP_ENGLISH_FORMATS`）：Better Pokédex Scanner 1.0.0 的 `VariantLabelLoader` 以 `listResourceStacks` 由下層到上層讀所有 `variant_labels`，`VariantLabelRegistry.findMappedLabel` 取第一個符合的群組，模組自己的英文永遠先找到，資源包蓋不過；Music Notification 3.0 的曲名、作者與專輯（`MusicResourceReloadListener` 以 `getResourceStack` 由下而上 `putAll`，資源包可以蓋過，但曲名是作品名稱，比照官方唱片名保留英文；`random.json` 程式沒有讀）。
  - 盤點工具的誤報（已修正）：函式檔的條目位置記為 `[行, n]`、盤點記為「行:序」，SNBT 字串還帶著跳脫字元，所以函式文字一句都對不上；戰利品表與交易也一樣改以同檔文字比對。有定義語系鍵的 fallback、只有一段文字加一段空白 `"text": ""` 的元件、`data_keys` 已補條目的函式 fallback 都算已涵蓋；空的設定檔與 JSON5 不再算讀取失敗；殘缺的壓縮檔記為未完成而不是讓盤點停止。
  - 不是玩家文字（v0.32.0 盤點判定）：寶可夢物種定義的 `name`／`forms.name`（Cobblemon、Pixelmon 以 `cobblemon.ui.pokedex.info.form.<物種>-<型態>` 等語系鍵顯示）、戰利品表項目與池的名稱、進度的觸發條件、`$` 開頭的巨集變數、建築木桶標記戰利品表的小寫說明（`village_desert_house`）、函式庫訊息（BouncyCastle、Apache commons-math）、Essential 載入器另外下載的那份 Essential、FancyMenu 編輯器的曲目與主題清單、Cobblemon NPC 編輯器的行為與設定名稱、對戰引擎腳本的記錄字串、生成桶名稱、Raid 的型態屬性、設定檔的區段名稱與數值清單、Iris 的光影檔名、原版 1.20.5 起在遊戲資料夾記下玩家打過指令的 `command_history.txt`。REI 為了拼音／倉頡搜尋自己下載的 Unicode 漢字字典 `config/roughlyenoughitems/unihan.zip`（Unihan_*.txt，其中兩個超過盤點大小上限未讀）是搜尋用資料，不是顯示文字（v0.33.2 COBBLEVERSE 上架前盤點）。車萬女僕 1.5.3 的 `config/touhou_little_maid/file/` 是模型包的下載快取：`InfoGetManager.reloadPack` 下載後複製到 `tlm_custom_pack/` 才由 `CustomPackLoader.readModelFromZipFile` 載入（`LanguageLoader` 讀包內 `assets/<包>/lang/<語言>.lang|json`，`LanguageMixin` 先查目前語言再查 en_us），所以只翻 `tlm_custom_pack/` 那份。`assets/<模組>/tips/` 是 Tips 模組的格式，VEFV2.7.1 沒裝 Tips，不會顯示；之後遇到裝了 Tips 的整合包要另加讀取器。Farming for Blockheads 的 `farmingforblockheads_compat` 分組名稱是設定檔開關用的識別名，市集畫面顯示的分類是語系鍵。Supplementaries 的笛子曲名、Untamed Wilds 的 entities 名稱、Expanded Storage 的轉換工具名、Friends & Foes 的哞菇變種都是代碼。Starcatcher 魚的星座代碼、More Mob Variants 的變種名、Untamed Wilds 的 spawn_tables、AmbientSounds 的維度代碼、車萬女僕的 AI 角色設定 yml 與 skills 參考檔（送給 AI 的提示詞）、PatPat 與 CustomSkinLoader 的範例設定、只有一個字母的告示牌、設定檔的英文設定值（依既有規則不翻）也不是要翻的玩家文字。
  - 發布 v0.32.0 前的最終盤點（2026-10-04，使用者同意只檢查要上架的整合包）：COBBLEVERSE 剩 18 類、VEFV2.7.1 剩 38 類，全部判定過。仍待處理：owo 豐富語系 6 句（紅字列出）、Mermod 的能力名稱與說明（Origins 類格式，紅字列出）、Towers of the Wild 把「Brrrrrr」「BANANAS?」直接當語系鍵的兩個進度標題、標題畫面隨機標語（待使用者決定）、有裝 Tips 模組時的 `assets/*/tips/`。讀取失敗 11 個：內嵌的 MixinExtras 程式庫、格式錯誤的 sounds.json、Legendary Monsters 的 space_station.nbt（超過盤點大小上限）、車萬女僕包裡以 GBK 編碼的 music.json 與 read me.txt，都不是會顯示的文字。

- VaultPatcher（`vaultpatcher-all-1.5.2.jar`，套件 `me.fengming.vaultpatcher_asm`）在遊戲載入模組 class 時，把 `vaultpatcher/modules/<模組>.json` 每組 `pairs` 的 `key`（class 裡的英文常數）換成 `value`（`LdcNodeHandler`），要載入哪些模組寫在 `config/vaultpatcher_asm/config.json` 的 `modules`。Elemental Awakening v1.4.6 的作者把 Spellblades and Such 與 Book of Dragons 的硬編碼文字寫成簡中 `value`（未鉴定。、葛伦科龙），v0.33.3 以前讀到了卻不在可原地轉換的資料夾裡，遊戲照樣顯示簡體。現在只把 `value` 轉台灣用語，`key` 不動（VaultPatcher 拿它比對 class 裡的原文）；某組的 `value` 同時是別組的 `key` 時也不動。`debug_mode.use_cache` 預設開啟：`core.cache.ClassCache.updated` 只比對原模組 class 的 SHA-256，沒變就直接用 `vaultpatcher/cache/<class>.class`，所以改了 `value` 的那幾個 `target_class` 要一起移除快取（`desktop_jobs.vaultpatcher_cache`，先備份、可還原），下次啟動 VaultPatcher 會用新的 `value` 重做快取。快取本身是產物，不掃描（`NOT_READ`）。
- KubeJS 腳本的樣板字串（反引號、中間夾 `${group.bonus}`）以前沒有被讀取：Elemental Awakening `kubejs/client_scripts/spell/food_effects.js` 的「八系法术强度、近战与远程伤害 +${group.bonus}%」因此在遊戲裡還是簡體。現在 `.js` 檔同一行的樣板字串也讀（`full_translation_audit.TEMPLATE`），`${}` 裡只能是變數與欄位，有引號或大括號的運算式不算；編號從 1000 起，原本的條目位置不變。
- 模組自己連英文語系都沒寫名字的物品（Monster Expansion 0.7.6 的 `item.monsterexpansion.great_sword`），英文版也顯示代碼。以「有物品模型、程式裡有同名字串、所有語系檔都沒有名字」去找，Elemental Awakening 一包就有 324 個，大多是畫作花樣、除錯道具與渲染用模型，`great_sword` 本身反而不在「資料檔有引用」的那 165 個裡，靜態判斷分不出哪些真的會出現在背包；尚未支援，待決定做法。

- 不是玩家文字（Elemental Awakening 2026-10-05，使用者要求「不該有誤報」）：冰與火圖鑑其他語言的頁面（`lang/bestiary/ja_jp_0/`，語言資料夾多了 `_0`；`text_inventory.LOCALE` 與 `locale_source` 都認得，繁中與簡中頁面也對到圖鑑條目），設定檔（config／defaultconfigs 的 toml、yml、cfg）的英文區段名與設定值（`names.cfg` 這類名稱清單除外），法術、翻滾動作檔的說明（spell_animations、rolling_animations），碰撞箱（hitboxes），FancyMenu 編輯器的曲目與主題，`kubejs.plugins.txt`、反編譯工具的參數表、打包進模組的函式庫（`repack/`），Supplementaries 沒用到的歌曲，Neruina 的錯誤回報範本，Create 思索場景的建築檔，槍械包自己的名稱，Citadel 的贊助者名單，UUID、Java 類別名、base64 資料（FTB 任務裡玩家頭顱的皮膚）、帶顏色碼的指令（`&b/ftbteams party create`），建築告示牌上只有一兩個字母的裝飾，Konkrete 等其他語言的介面檔（`foreign_file`），存檔裡的隊伍名稱，以及腳本裡提到欄位名的程式碼行。另外查過模組程式確認不會顯示的：Monster Expansion 0.7.6 的 `monster_ref` 名稱（`MonsterRefManager.parseRef` 不讀 `name`，指南顯示由 `entity_id` 組出的語系鍵），Supplementaries 3.1.43 的笛子曲名（`Song.getTranslationKey` 只當鍵與錄音檔名），沒有任何模組讀的 Citadel `backup_text.txt`，Legendary Monsters 2.1.22 沒被引用的整份 `space_station.nbt`（太空站由 `space_station_main` 與 `part1-9` 組成），包在載入器裡的 MixinExtras 程式庫，`sounds.json`；KubeJS 啟動腳本裡同一行有註冊代碼、而語系檔已有 `block.kubejs.<代碼>` 的顯示名稱（遊戲顯示語系檔的名字）；樣板字串裡只有 `${}` 與數值、沒有文字的片段。模組自帶就壞掉的檔案（Dungeon Now Loading 2.2 的 4 個建築檔解壓縮失敗、Integrated Villages 的 6 個戰利品表 JSON 格式錯誤）改以灰字說明，不列紅字。仍會列出的（是玩家文字、尚未支援）：標題畫面隨機標語、Alex's Caves 的 `texts/end.txt`、只有簡中的 Patchouli 書頁、戰利品裡寫死的名字、Konkrete 的英文介面 `en_us.local`。

- 2026-10-05 起支援的格式（使用者要求 Elemental Awakening 剩下的 13 個檔案都要翻成繁體）：
  - 只有簡中寫完整、英文只是短短一段的書頁（Jerotes Village 二輪世界探索指南：簡中 9 段、英文 1 段且內容不同；黑金聯盟的一頁）：繁中版改照簡中的頁面結構產生，每段都轉繁，英文不拿來比對（Audit cn_shape）。先前以英文為底只寫出 1 段。
  - 透過資源系統讀、不分語言的文字檔（`full_translation_audit.RESOURCE_TEXTS`）：Fancy Toasts 1.4.6 的 `splashes.txt`（SplashManager.readSplashes 用 ResourceManager.getResource，`{user.name}` 會換成玩家名稱）、Mutant More 的 `texts/mutantmore_splashes.txt`（SplashManagerMixin 用 ResourceManager.openAsReader 讀）、模組放的 `assets/minecraft/texts/end.txt`（擊敗終界龍後的片尾文字，WinScreen 讀 minecraft:texts/end.txt；Alex's Caves 有自己的版本）。翻譯資源包放同路徑的一份就會蓋過。
  - 冰與火 2.1.13 的 `splashes.txt` 保留英文並以灰字說明：IceAndFireMainMenu 只在 `"Custom main menu"` 開啟時顯示（Elemental Awakening 關閉），而且先從 GitHub 讀，讀不到才用 getResourceAsStream 讀模組檔，資源包蓋不過。
  - Konkrete 1.8.0 的 `config/konkrete/locals/<語言>.local`：Locals.localize 先用遊戲目前的語言，沒有才用 en_us，所以在旁邊新增 `zh_tw.local`（`key=value`，讀取時會去掉等號兩邊的空白）。
  - owo-lib 的帶格式語系值（`{"text": …, "color": "gray"}`）：每段文字一筆，鍵記成 `[語系鍵, 路徑]`，zh_tw 寫回同樣的元件、只換文字，顏色保留（OwoTranslationMixin 在任何語言檔都讀這種值）。
  - 資料檔裡拿一個大寫開頭的英文單字當語系鍵（ATi Structures 1.4.6 戰利品：`{"translate": "RedBull"}`、`Chlorophyll`、`Indestructible `）：沒有語系檔定義時遊戲顯示鍵本身，和句子當鍵一樣補成語系條目。小寫單字可能是真的鍵，不補。
  - Immersive Paintings 0.6.13 的畫名（`data/immersive_paintings/paintings/*.json` 的 `name`）：選畫畫面用 Component.literal 顯示；PaintingsLoader 先列出 png、再從最上層讀同名 json，所以翻譯資料包的 json 改畫名、圖仍用模組的。`author` 是人名，保留。
  - Torches Becomes Sunlight 0.4.9 的 `data/torchesbecomesunlight/dialogue/` 不再列為漏翻：`title`、`description` 只在 Dialogue.serializeNBT 存讀，不顯示；台詞是語系鍵（`dialogue.frostnova_fight.main1`），照一般語系檔翻。

## 硬編碼文字（修改 class 前必讀）

2026-10-03 本機 v0.32.0 的獨立文字涵蓋檢查（尚未發布）：COBBLEVERSE 中的 `assets/better_pokedex_scanner/variant_labels/cobblemon.json` 有 `headerLabel`、`aspectLabels` 與 `aspectDisplays.parts[].text` 等變體標籤，現有翻譯讀取器沒有涵蓋，先列為未支援候選。分段顏色與拼接文字需要按整組處理；尚未建立寫入支援，不能宣稱新增診斷就已翻好。仍須追查模組讀取與顯示位置後才能加入讀取器。

這次盤點的非玩家資料排除：Showdown 引擎的內嵌 `showdown.zip` 與 assets/data 的 `showdown/` 腳本、幾何模型 `geo/` 的骨架名稱、Fabric／Quilt 的 mod 宣告、Mixin refmap、JSON schema、重新定位的函式庫診斷、材質包 OptiFine 模型選擇 properties、授權／貢獻者／贊助者清單、啟動器清單與備份路標。這些不納入獨立文字候選；其他來源中名稱看似識別值但尚未證明用途的內容保留診斷，不能整類忽略或寫入。此檢查仍不涵蓋存檔、圖片或所有動態組句，不是遊戲內驗收。

- APP 的通用支援由 `class_text.py` 實作：逐個 class 檢查每次載入同一常數的位置，僅接受直接 literal 呼叫或 Forge／NeoForge Builder.comment（單字串與直接建立的字串陣列）。private static final 的內嵌常數須沒有欄位存取；公開常數、註解與 bootstrap 引用仍拒絕。其他 bytecode 資料流不能套用此證據。
- 改寫後保留常數索引及非翻譯內容，使用隨 APP 附帶的 ClassTextCheck Java 解析器與 Java ZipFS 驗證；解析不執行模組，不等於遊戲內實測。掃描快取版本變更會重查舊候選。class 位元組不放入分享補丁；格式 3 只帶用途已確認的常數文字，接收端重新驗證並改寫自己的原檔。
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

