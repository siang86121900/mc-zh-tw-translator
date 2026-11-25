"""Traditional Chinese chat text for Vonix Guardian (使用者 2026-11-26 指定).

Display-only string constants, checked against the MIT source at the 2.3.2
release (github.com/Vonix-Network/VonixGuardian, commit "release: 2.3.2").
Each class is bound to its SHA-256 in vonix.CLASS_EDITS; \x01 marks a
string-concatenation argument and must stay in the same order.

Decisions (使用者 2026-11-26 同意)：put/took are shared by chests and the
player's own inventory, so they read 增加／減少 (the logged inventory gained or
lost items). Times stay UTC (fixed in code); the date pattern is numeric.
"""

C = 'network/vonix/guardian/core/'
M = 'network/vonix/guardian/mc/v1_20_1/common/'
AGO = {'\x01d ago': '\x01 天前', '\x01h ago': '\x01 小時前', '\x01m ago': '\x01 分鐘前',
       '\x01s ago': '\x01 秒前', '\x01w ago': '\x01 週前'}

TEXT = {
 C+'command/LookupText.class': {**AGO,
  ' · click to copy': ' · 點一下複製',
  ' · rolled back': ' · 已還原',
  'Click to copy id \x01': '點一下複製紀錄編號 \x01',
  'Click to fill in \x01': '點一下填入 \x01',
  'Not stored yet': '尚未寫入紀錄',
  'block data': '方塊資料', 'item data': '物品資料', 'entity data': '生物資料',
  "d MMM HH:mm 'UTC'": "M/d HH:mm 'UTC'",
  'broke': '破壞', 'changed': '變更', 'clicked': '點擊', 'crafted': '合成',
  'dispensed': '射出', 'dropped': '丟出', 'exploded': '爆炸', 'generated': '產生地形',
  'grew': '長出', 'joined': '加入遊戲', 'killed': '擊殺', 'left': '離開遊戲',
  'opened a portal at': '開啟傳送門', 'picked up': '撿起', 'placed': '放置',
  'put': '增加', 'took': '減少', 'ran': '執行', 'renamed to': '改名為', 'said': '說',
  'spawned': '生成', 'toggled': '切換', 'trampled': '踩壞', 'used': '使用', 'wrote': '寫下',
  'waxed': '已上蠟', 'now \x01': '現在是 \x01', 'was \x01': '原本是 \x01',
  'pair \x01': '配對 \x01', 'slot \x01': '欄位 \x01',
 },
 C+'query/InspectorLookup.class': {**AGO,
  ' | at (': ' | 位置 (', ' | rolled back': ' | 已還原', ' | slot=': ' | 欄位=',
  '----- VonixGuardian | Block history | world=\x01 | pos=(\x01, \x01, \x01) -----':
      '----- VonixGuardian | 方塊紀錄 | 世界=\x01 | 座標=(\x01, \x01, \x01) -----',
  'No history found for this block.': '這個方塊沒有任何紀錄。',
  'block': '方塊', 'item': '物品', 'world': '世界', 'entity': '生物', 'message': '訊息',
  'command': '指令', 'sign': '告示牌', 'player': '玩家', 'target': '目標', 'hanging': '掛飾',
  'broke': '破壞', 'changed block': '變更方塊', 'clicked': '點擊', 'crafted': '合成',
  'created portal': '開啟傳送門', 'deposited': '增加', 'withdrew': '減少', 'dispensed': '射出',
  'dropped': '丟出', 'exploded': '爆炸', 'grew': '長出', 'interacted with': '互動',
  'joined': '加入遊戲', 'killed': '擊殺', 'left': '離開遊戲', 'picked up': '撿起',
  'placed': '放置', 'populated': '產生地形', 'ran': '執行', 'renamed': '改名', 'said': '說',
  'signed': '寫告示牌', 'spawned': '生成', 'toggled': '切換', 'trampled': '踩壞',
  'transformed': '轉變',
 },
 M+'LookupFormatter.class': {
  '  Next: \x01': '  下一頁：\x01',
  ' — more below': '，下面還有',
  'Click to put the next page in the chat box': '點一下把下一頁的指令放進聊天框',
  'Lookup page \x01\x01': '查詢結果第 \x01 頁\x01',
  'Lookup: \x01 \x01 (page \x01/\x01)': '查詢：\x01 \x01（第 \x01/\x01 頁）',
  'result': '筆', 'results': '筆',
 },
 M+'GuardianCommands$Lookup.class': {
  '[VonixGuardian] Count: \x01': '[VonixGuardian] 共 \x01 筆',
  '[VonixGuardian] Lookup aborted: the permission-filtered page exceeded the 100000-row scan limit. Narrow the time, radius, or action filter and try again.':
      '[VonixGuardian] 查詢中止：要掃描的紀錄超過 100000 筆。請縮小時間、範圍或動作條件再試一次。',
  '[VonixGuardian] Lookup error: \x01': '[VonixGuardian] 查詢失敗：\x01',
  '[VonixGuardian] No results found. Try a wider radius (r:20+) or longer time (t:24h+), or check filter tokens.':
      '[VonixGuardian] 找不到紀錄。可以加大範圍（r:20 以上）、拉長時間（t:24h 以上），或檢查查詢條件。',
 },
 M+'GuardianCommands$Inspect.class': {
  '[VonixGuardian] /vg inspect must be run by a player.': '[VonixGuardian] /vg inspect 只能由玩家在遊戲裡使用。',
  '[VonixGuardian] Inspect mode ENABLED. Left-click a block to look it up.': '[VonixGuardian] 已開啟檢查模式：左鍵點方塊可以查它的紀錄。',
  '[VonixGuardian] Inspect mode disabled.': '[VonixGuardian] 已關閉檢查模式。',
 },
 M+'GuardianCommands$Near.class': {
  '[VonixGuardian] /vg near must be run by a player.': '[VonixGuardian] /vg near 只能由玩家在遊戲裡使用。',
 },
 M+'GuardianCommands$Give.class': {
  '[VonixGuardian] /vg give must be run by a player.': '[VonixGuardian] /vg give 只能由玩家在遊戲裡使用。',
  '[VonixGuardian] Gave \x01x \x01': '[VonixGuardian] 已給予 \x01 個 \x01',
  '[VonixGuardian] Give failed: \x01': '[VonixGuardian] 給予失敗：\x01',
  '[VonixGuardian] Invalid item id: \x01': '[VonixGuardian] 物品代碼無效：\x01',
  '[VonixGuardian] Unknown item: \x01': '[VonixGuardian] 找不到物品：\x01',
 },
 M+'GuardianCommands$Teleport.class': {
  '[VonixGuardian] /vg teleport must be run by a player.': '[VonixGuardian] /vg teleport 只能由玩家在遊戲裡使用。',
  '[VonixGuardian] Invalid coordinates: \x01': '[VonixGuardian] 座標無效：\x01',
  '[VonixGuardian] Teleport failed: \x01': '[VonixGuardian] 傳送失敗：\x01',
  '[VonixGuardian] Teleported to \x01 \x01 \x01 \x01': '[VonixGuardian] 已傳送到 \x01 \x01 \x01 \x01',
  '[VonixGuardian] Unknown world: \x01': '[VonixGuardian] 找不到世界：\x01',
  '[VonixGuardian] Usage: /vg teleport <world> <x> [y] <z>': '[VonixGuardian] 用法：/vg teleport <世界> <x> [y] <z>',
 },
 M+'GuardianCommands$Undo.class': {
  'Undo (\x01)': '取消還原（\x01）',
  '[VonixGuardian] Nothing to undo.': '[VonixGuardian] 沒有可以取消的還原。',
  '[VonixGuardian] Undo error: \x01': '[VonixGuardian] 取消還原失敗：\x01',
  '[VonixGuardian] Undo: dropped \x01 entries from history (legacy/empty entry — world state not reverted).':
      '[VonixGuardian] 取消還原：從紀錄移除 \x01 筆空白或舊格式項目（世界沒有變動）。',
 },
 M+'GuardianCommands$Preview.class': {
  'Applied preview': '已套用預覽',
  '[VonixGuardian] Apply error: \x01': '[VonixGuardian] 套用失敗：\x01',
  '[VonixGuardian] No pending rollback preview.': '[VonixGuardian] 目前沒有待套用的還原預覽。',
  '[VonixGuardian] Pending rollback preview changed or expired; run preview again.': '[VonixGuardian] 還原預覽已變動或過期，請重新預覽。',
  '[VonixGuardian] Preview permission changed; run the preview again.': '[VonixGuardian] 權限已變動，請重新預覽。',
  '[VonixGuardian] Rollback preview cancelled.': '[VonixGuardian] 已取消還原預覽。',
 },
 M+'GuardianCommands$Rollback.class': {
  'Rollback': '還原',
  '[VonixGuardian] Rollback error: \x01': '[VonixGuardian] 還原失敗：\x01',
 },
 M+'GuardianCommands$Restore.class': {
  'Restore': '重做',
  '[VonixGuardian] Restore error: \x01': '[VonixGuardian] 重做失敗：\x01',
 },
 M+'GuardianCommands$Purge.class': {
  '[VonixGuardian] Purge error: \x01': '[VonixGuardian] 清除紀錄失敗：\x01',
  '[VonixGuardian] Purge refused: \x01 (CP-1:1 safety floor; use a larger t: window)': '[VonixGuardian] 拒絕清除：\x01（安全下限，請用更長的 t: 時間）',
 },
 M+'GuardianCommands$Batch.class': {
  '[VonixGuardian] Batch error: \x01': '[VonixGuardian] 批次指令失敗：\x01',
  '[VonixGuardian] Batch id must be a positive number. Nothing was changed.': '[VonixGuardian] 批次編號必須是正整數，沒有任何變更。',
 },
 M+'GuardianCommands$Reload.class': {
  '[VonixGuardian] Errors: \x01 \x01': '[VonixGuardian] 錯誤：\x01 \x01',
  '[VonixGuardian] Errors: 0 (none)': '[VonixGuardian] 錯誤：0（無）',
  '[VonixGuardian] Hot-swapped: \x01 \x01': '[VonixGuardian] 已即時套用：\x01 \x01',
  '[VonixGuardian] Reload failed: \x01': '[VonixGuardian] 重新載入失敗：\x01',
  '[VonixGuardian] Reloading configuration...': '[VonixGuardian] 正在重新載入設定……',
  '[VonixGuardian] Requires restart: \x01 \x01': '[VonixGuardian] 需要重開伺服器：\x01 \x01',
 },
 M+'GuardianCommands$Config.class': {
  '[VonixGuardian] Cannot persist config: no config path is known.': '[VonixGuardian] 無法儲存設定：找不到設定檔位置。',
  '[VonixGuardian] Config key vanished under concurrent update: \x01': '[VonixGuardian] 設定項目在更新途中消失：\x01',
  '[VonixGuardian] Config saved but reload failed: \x01': '[VonixGuardian] 設定已儲存，但重新載入失敗：\x01',
  '[VonixGuardian] Config update failed: \x01': '[VonixGuardian] 設定更新失敗：\x01',
  '[VonixGuardian] Unknown or read-only config key: \x01': '[VonixGuardian] 沒有這個設定項目或不能修改：\x01',
  '[VonixGuardian] Updated \x01 = \x01 (hot-swapped: \x01)': '[VonixGuardian] 已更新 \x01 = \x01（即時套用：\x01）',
 },
 M+'GuardianCommands$EntityLog.class': {
  '[VonixGuardian] Allowlist saved but reload failed: \x01': '[VonixGuardian] 名單已儲存，但重新載入失敗：\x01',
  '[VonixGuardian] Cannot persist config: no config path is known.': '[VonixGuardian] 無法儲存設定：找不到設定檔位置。',
  '[VonixGuardian] Entity allowlist (\x01):': '[VonixGuardian] 生物記錄名單（\x01）：',
  '[VonixGuardian] Entity allowlist is empty. Use /vg entitylog add <ns:path|ns:*|ns> to whitelist modded griefers.':
      '[VonixGuardian] 生物記錄名單是空的。可用 /vg entitylog add <ns:path|ns:*|ns> 加入要記錄的模組生物。',
  '[VonixGuardian] entityChangeLogAllEntities=true — ALL entities are logged (allowlist ignored). This can flood on modded packs.':
      '[VonixGuardian] entityChangeLogAllEntities=true：所有生物都會記錄（不看名單），模組包可能產生大量紀錄。',
  '[VonixGuardian] entitylog update failed: \x01': '[VonixGuardian] 生物記錄名單更新失敗：\x01',
 },
 M+'GuardianCommands$Consumer.class': {
  '[VonixGuardian] Consumer PAUSED — incoming events are buffered, not written.': '[VonixGuardian] 已暫停寫入：新紀錄先暫存，還沒寫進資料庫。',
  '[VonixGuardian] Consumer PAUSED.': '[VonixGuardian] 已暫停寫入。',
  '[VonixGuardian] Consumer RESUMED — draining buffered events.': '[VonixGuardian] 已恢復寫入：正在寫入暫存的紀錄。',
  '[VonixGuardian] Consumer RESUMED.': '[VonixGuardian] 已恢復寫入。',
  '[VonixGuardian] Consumer is currently \x01 (queue.depth=\x01)': '[VonixGuardian] 寫入狀態：\x01（等待寫入 \x01 筆）',
 },
 M+'GuardianCommands$MigrateDb.class': {
  '[VonixGuardian] migrate-db is console-only.': '[VonixGuardian] migrate-db 只能在伺服器主控台使用。',
  "[VonixGuardian] migrate-db: second argument must be 'CONFIRM' to proceed.": "[VonixGuardian] migrate-db：第二個參數要輸入 'CONFIRM' 才會執行。",
 },
 M+'GuardianCommands.class': {
  '[VonixGuardian] Command worker is saturated; retry shortly or reduce concurrent heavy commands.': '[VonixGuardian] 指令太多正在處理，請稍後再試。',
  '[VonixGuardian] Rollback planning: scanned=\x01 planned=\x01 skipped=\x01': '[VonixGuardian] 還原規劃：掃描 \x01 筆、預計變更 \x01 筆、略過 \x01 筆',
 },
 C+'command/MutationOutcomeFormatter.class': {
  '\x01 of \x01 planned changes were neither applied nor reported as skipped or failed. Treat the world as partly changed and check the server log before re-running.':
      '有 \x01 項（共預計 \x01 項）沒有套用、略過或失敗的回報。請把世界當成只改了一部分，先看伺服器紀錄再重跑。',
  '\x01 verbose: applied \x01, skipped \x01, world changes \x01.': '\x01 詳細：套用 \x01、略過 \x01、世界變更 \x01。',
  '  \x01 found 0 matching actions. Explosions record their blast center. Try r:20+ or stand at the source of the damage.':
      '  \x01 找不到符合的紀錄。爆炸記在爆炸中心，可以試 r:20 以上，或站到受損的地方。',
  ' (of ': '（預計 ', ' planned)': ' 項）', ' changed': ' 項已變更', ' would change': ' 項將會變更',
  ' compensated': ' 項已補回', ' count: planned=': ' 數量：預計=', ' skipped=': ' 略過=',
  ' is closed': ' 已結束', ' is still open. Use /vg batch show ': ' 尚未結束，請用 /vg batch show ',
  ' need repair': ' 項需要修復', ' others ': ' 種其他 ', '(preview) ': '（預覽）',
  ', failed=': '，失敗=', ', skipped=': '，略過=', '. Batch ': '。批次 ',
  '. Nothing was changed.': '。沒有任何變更。',
  '. The world was not changed and no blocks were drawn in it. /vg apply runs this plan, /vg cancel drops it':
      '。世界沒有變動。/vg apply 會照這個計畫執行，/vg cancel 取消',
  'Compensated': '已補回', 'Done': '完成', 'Failed': '失敗', 'Needs repair': '需要修復',
  'Partly done': '部分完成', 'Mutation': '操作',
 },
 C+'rollback/RollbackResult.class': {
  '\x01 unclassified': '\x01 未分類',
  'chat/session (nothing to undo)': '聊天／上下線（不用還原）',
  'clicks recorded, nothing to undo': '只有點擊紀錄，不用還原',
  'entity restore unsupported': '不支援還原生物',
  'no item NBT captured (storage.persistNbt was off)': '沒有存物品資料（storage.persistNbt 未開啟）',
  'row has no actor, cannot be aimed': '紀錄沒有執行者，無法對應',
  'state not tracked, cannot invert': '沒有記錄狀態，無法還原',
  'stored payload unreadable': '紀錄內容讀不懂',
  'superseded by a newer edit': '之後又被改過',
 },
 C+'rollback/RollbackBatches.class': {
  '\x01 (ids \x01)': '\x01（編號 \x01）',
  '\x01 open rollback \x01.': '\x01 個未結束的還原\x01。',
  '  /vg batch close \x01 marks this audit row finished and does not change the world.': '  /vg batch close \x01 會把這筆標成已結束，不會改動世界。',
  '  /vg batch show <id> lists the action ids. /vg batch close <id> marks one finished and does not change the world.':
      '  /vg batch show <編號> 列出紀錄編號；/vg batch close <編號> 標成已結束，不會改動世界。',
  '  actions: \x01': '  紀錄：\x01', ' more': ' 筆', '(none)': '（無）', ', and ': '，還有 ',
  'At least 20 open rollback batches. More may exist.': '至少有 20 個未結束的還原批次，可能還有更多。',
  'Open rollback batches: \x01 covering \x01 \x01. Use /vg batch to inspect or close them. The world was not changed.':
      '未結束的還原批次：\x01，共 \x01 \x01。可用 /vg batch 查看或結束，世界沒有變動。',
  '[VonixGuardian] \x01 The world was not changed.': '[VonixGuardian] \x01 世界沒有變動。',
  '[VonixGuardian] Batch \x01 is \x01 (\x01, \x01 \x01). The world was not changed.': '[VonixGuardian] 批次 \x01 狀態：\x01（\x01，\x01 \x01）。世界沒有變動。',
  '[VonixGuardian] Batch \x01 is already closed (\x01, \x01 actions). The world was not changed.': '[VonixGuardian] 批次 \x01 早已結束（\x01，\x01 筆紀錄）。世界沒有變動。',
  '[VonixGuardian] Batch \x01 is now closed (\x01, \x01 actions). The world was not changed. The logged actions are still in the audit log.':
      '[VonixGuardian] 批次 \x01 已結束（\x01，\x01 筆紀錄）。世界沒有變動，紀錄仍保留。',
  '[VonixGuardian] Batch \x01 was not closed. The world was not changed.': '[VonixGuardian] 批次 \x01 沒有結束。世界沒有變動。',
  '[VonixGuardian] No batch \x01. Nothing was closed and the world was not changed.': '[VonixGuardian] 沒有批次 \x01，沒有結束任何批次，世界沒有變動。',
  '[VonixGuardian] No batch \x01. The world was not changed.': '[VonixGuardian] 沒有批次 \x01。世界沒有變動。',
  '[VonixGuardian] No open rollback batches. The world was not changed.': '[VonixGuardian] 沒有未結束的還原批次。世界沒有變動。',
  'action': '筆紀錄', 'actions': '筆紀錄', 'already closed': '已結束', 'at least 20 shown': '至少顯示 20 個',
  'batch': '批次', 'batches': '批次', 'mode \x01': '模式 \x01', 'no open batch row': '沒有未結束的批次',
  'restore': '重做', 'rollback': '還原',
 },
 C+'command/PurgeReport.class': {
  '  … and \x01 more.': '  ……還有 \x01 筆。',
  '\x01 \x01,\x01,\x01 \x01 by \x01': '\x01 \x01,\x01,\x01 \x01，執行者 \x01',
  '[VonixGuardian] Purge count: \x01 rows match in \x01. Nothing was deleted.': '[VonixGuardian] 清除數量：符合 \x01 筆（範圍：\x01），沒有刪除任何紀錄。',
  '[VonixGuardian] Purge preview: \x01 rows would be deleted in \x01. Nothing was deleted.': '[VonixGuardian] 清除預覽：會刪除 \x01 筆（範圍：\x01），還沒有刪除。',
  '[VonixGuardian] Purge produced no result.': '[VonixGuardian] 清除沒有結果。',
  '[VonixGuardian] Purge removed \x01 rows in \x01 (minAge=\x01s).': '[VonixGuardian] 已清除 \x01 筆紀錄（範圍：\x01，至少 \x01 秒前）。',
 },
 C+'command/OperatorText.class': {'unknown error': '不明錯誤'},
 # PurgeScope.label is only read by PurgeReport (display).
 C+'rollback/PurgeScope.class': {'all worlds': '全部世界'},
 C+'command/CommandSpec.class': {
  'Apply the pending preview. This changes the world.': '套用待執行的還原預覽，會改動世界。',
  'Copy the Guardian catalog to another JDBC backend.': '把紀錄資料庫複製到另一個資料庫。',
  'Drop the pending preview. The world is not changed.': '取消待執行的還原預覽，世界不會變動。',
  'Get or set a hot-swap-safe configuration key.': '查看或修改可以即時套用的設定。',
  'Give an item id captured by lookup.': '給予查詢結果裡的物品。',
  'List subcommands and their syntax.': '列出所有指令與用法。',
  'List, add, or remove modded entities from the griefing allowlist.': '查看、加入或移除要記錄破壞行為的模組生物。',
  'List, show, or close an unfinished rollback. Closing does not change the world.': '查看或結束沒完成的還原；結束不會改動世界。',
  'Pause, resume, or toggle the audit write consumer.': '暫停或恢復寫入紀錄。',
  'Permanently delete old log rows in every world unless you name one. #preview and #count do not delete.':
      '永久刪除舊紀錄（沒指定世界就是全部世界）。#preview 和 #count 不會刪除。',
  'Put back actions that a rollback changed in the world.': '把被還原的變更重做回去。',
  'Query the audit log with filter tokens (u: t: r: a: i: e: #…).': '用條件查詢紀錄（u: t: r: a: i: e: #…）。',
  'Reload the Guardian configuration file from disk.': '重新讀取設定檔。',
  'Reverse your last rollback or restore. This changes the world again.': '取消你上一次的還原或重做，會再次改動世界。',
  'Show queue depth, storage reachability and schema, and runtime stats.': '顯示紀錄寫入、資料庫與執行狀態。',
  'Show recent activity in a small radius around you.': '顯示你附近最近的紀錄。',
  'Teleport to a world coordinate from a lookup row.': '傳送到查詢結果裡的座標。',
  'Toggle inspection mode — left/right click to query a block.': '切換檢查模式：用滑鼠點方塊查它的紀錄。',
  'Undo logged actions in the world (default radius 10).': '把世界還原成紀錄之前的樣子（預設半徑 10 格）。',
 },
 C+'command/CommandHelp.class': {
  '  #preview and #count do not delete.': '  #preview 和 #count 不會刪除。',
  '  #preview behaves as it does for rollback: a count, no blocks drawn.': '  #preview 跟還原一樣只計算數量，不改動世界。',
  '  #preview changes nothing and draws nothing in the world: it counts the plan': '  #preview 不會改動世界，只計算預計的變更，',
  '  /vg restore with a matching filter puts those blocks back.': '  用相同條件執行 /vg restore 可以把方塊重做回去。',
  '  A bare purge covers every world. Name one with r:#nether, r:#overworld, r:#end, or r:#world_<name>.':
      '  沒指定世界就會清除全部世界。可用 r:#nether、r:#overworld、r:#end 或 r:#world_<名稱> 指定。',
  '  A single t: deletes rows older than that age. t:40d-60d deletes only the rows inside that window.':
      '  只寫一個 t: 會刪除比這更舊的紀錄；t:40d-60d 只刪這段時間內的紀錄。',
  '  After a restart, /vg batch lists an unfinished rollback and its action ids;': '  伺服器重開後，/vg batch 會列出沒完成的還原和紀錄編號；',
  '  Console refuses anything newer than 24h. In-game refuses anything newer than 30d.': '  主控台不能刪 24 小時內的紀錄，遊戲內不能刪 30 天內的紀錄。',
  '  Example: /vg batch': '  例如：/vg batch', '  Example: /vg batch close 17': '  例如：/vg batch close 17',
  '  Example: /vg batch show 17': '  例如：/vg batch show 17', '  Example: /vg lookup #count r:20': '  例如：/vg lookup #count r:20',
  '  Example: /vg lookup r:10 t:2h': '  例如：/vg lookup r:10 t:2h', '  Example: /vg purge t:30d': '  例如：/vg purge t:30d',
  '  Example: /vg purge t:40d-60d r:#nether #preview': '  例如：/vg purge t:40d-60d r:#nether #preview',
  '  Example: /vg restore r:10 t:2m': '  例如：/vg restore r:10 t:2m', '  Example: /vg rollback r:10 t:2m': '  例如：/vg rollback r:10 t:2m',
  '  Example: /vg rollback r:20 t:5m #preview': '  例如：/vg rollback r:20 t:5m #preview',
  '  Lists a rollback that did not finish. Closing marks the audit row finished.': '  列出沒完成的還原；結束只會把紀錄標成已結束。',
  '  Needs \x01.': '  需要權限 \x01。',
  '  Needs the node of the pending preview: \x01 or \x01.': '  需要待執行預覽的權限：\x01 或 \x01。',
  '  Remembers the last 20 operations per operator, in memory only: a server restart clears them.': '  每位管理員記得最近 20 次操作，只存在記憶體，伺服器重開就會清掉。',
  '  Reserved, enforced by nothing today: \x01.': '  保留但目前沒有作用：\x01。',
  '  Reverses your last rollback or restore. This changes the world again.': '  取消你上一次的還原或重做，會再次改動世界。',
  '  Runs the exact plan the last #preview kept, then clears it.': '  照上一次 #preview 留下的計畫執行，然後清掉計畫。',
  '  The world is not changed. Unlike /vg undo, this survives a restart.': '  世界不會變動；和 /vg undo 不同，伺服器重開後仍然有效。',
  '  This changes blocks in the world. /vg cancel drops the plan instead.': '  這會改動世界裡的方塊；不要執行請用 /vg cancel。',
  '  This changes blocks in the world. Default radius is 10.': '  這會改動世界裡的方塊，預設半徑 10 格。',
  '  This puts rolled-back blocks back into the world. Default radius is 10.': '  把被還原的方塊重做回去，預設半徑 10 格。',
  '  Tokens: u: user, t: time, r: radius, a: action, i: include, e: exclude, #preview #count': '  條件：u: 玩家、t: 時間、r: 範圍、a: 動作、i: 包含、e: 排除、#preview #count',
  '  and holds it for /vg apply (changes those blocks) or /vg cancel (drops it).': '  並保留給 /vg apply（執行變更）或 /vg cancel（取消）。',
  '#preview draws nothing: it counts the plan and keeps it for /vg apply or /vg cancel.': '#preview 不改動世界，只計算並保留計畫給 /vg apply 或 /vg cancel。',
  'Filter tokens: u:<player>  t:<time or time-time>  r:<blocks|#global|#world_name|#worldedit>': '查詢條件：u:<玩家>  t:<時間或時間-時間>  r:<格數|#global|#world_名稱|#worldedit>',
  'Flags: #preview and #count do not change the world or delete rows. Also #verbose #silent #optimize.': '旗標：#preview 和 #count 不改動世界也不刪紀錄；另有 #verbose #silent #optimize。',
  'Lookup pages: /vg lookup <page>[:<perPage>] before filter': '查詢分頁：在條件前面寫 /vg lookup <頁數>[:<每頁筆數>]',
  'Permission nodes (\x01) — grant these; permissions.perNodeOpLevels uses the same strings:': '權限節點（\x01）：要給這些權限；permissions.perNodeOpLevels 也用同樣名稱：',
  '[VonixGuardian] /vg lookup <page>[:<perPage>] before filter': '[VonixGuardian] /vg lookup <頁數>[:<每頁筆數>] 寫在條件前面',
  '[VonixGuardian] /vg restore <filter>  (alias /vg rs)': '[VonixGuardian] /vg restore <條件>（也可用 /vg rs）',
  '[VonixGuardian] /vg rollback <filter>  (alias /vg rb)': '[VonixGuardian] /vg rollback <條件>（也可用 /vg rb）',
  '[VonixGuardian] /vg purge <filter>': '[VonixGuardian] /vg purge <條件>',
  '[VonixGuardian] /vg batch [list|show <id>|close <id>]': '[VonixGuardian] /vg batch [list|show <編號>|close <編號>]',
  '[VonixGuardian] Commands (also /co and /guardian):': '[VonixGuardian] 指令（也可用 /co 或 /guardian）：',
  'a:click rows are interactions (right-click, cake, anvil, item frame, taming). They are recorded and never rolled back.':
      'a:click 是互動紀錄（右鍵、蛋糕、鐵砧、物品展示框、馴服），只記錄、不會還原。',
  '  \x01 more are not vonixguardian.<sub>: \x01.': '  另有 \x01 個不是 vonixguardian.<sub>：\x01。',
  '               a:<action>  i:<id>  e:<id>': '               a:<動作>  i:<代碼>  e:<代碼>',
 },
}
