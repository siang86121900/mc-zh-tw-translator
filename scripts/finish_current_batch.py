import json,re,zipfile
from pathlib import Path
from normalize_zh_tw import normalize_text
root=Path(__file__).resolve().parents[1]; out=root/'output/2026-09-09'
pairs='''Region Keep Distance|區域保留距離
Distance to keep loaded regions|保留已載入區域的距離
Automatic memory limit|自動記憶體上限
Automatically determines the memory limit to set given the amount of available vram on your system (Close and reopen settings to edit the max memory)|依系統可用的顯示記憶體自動設定上限（關閉並重新開啟設定後，可編輯記憶體上限）
Max gpu memory|顯示記憶體上限
Max gpu memory allowed, will start to cull chunks if this limit is hit|允許使用的顯示記憶體上限；達到上限時會開始剔除區塊
Enables temporal coherence|啟用時間一致性
Removes artifacting when turning around|消除轉動視角時的畫面瑕疵
Translucency Sorting|半透明排序
None|無
Sections|區塊分段
Quads|四邊形
Statistics Level|統計層級
Statistics logging level, tracks the visibility count of cull layers|統計記錄層級，用於追蹤各剔除層的可見數量
Frustum|視錐體
Regions|區域
Enable async bfs|啟用非同步 BFS
Enables asynchronous bfs chunk section loading, greatly reduces the frame time when moving, more noticeable with higher render distances|啟用非同步廣度優先搜尋來載入區塊分段，大幅縮短移動時的每幀耗時；繪製距離越遠，效果越明顯
Crispy Fried Perch|酥炸鱸魚
Roasted Tambaqui|烤淡水白鯧
§bIncreases the amount of fillets you get on a cutting board|§b增加在砧板上取得的魚片數量
Crispy Nori|香脆海苔
Fish Chorba|香料魚湯
Trout Steak|鱒魚排
Crispy Roll Medley|酥脆魚捲拼盤
Fish and Chips|炸魚薯條
Fried Perch Roll|炸鱸魚捲
§7Has 2% chance to apply §cPoison (00:03)|§7有 2% 機率造成§c中毒（00:03）
Wood Selling Bin|木製出貨箱
Iron Selling Bin|鐵製出貨箱
Gold Selling Bin|金製出貨箱
Diamond Selling Bin|鑽石出貨箱
Netherite Selling Bin|獄髓出貨箱
Selling Bin|出貨箱
Trade Frequency: %s | Process Per Tick: %s|交易頻率：%s | 每遊戲刻處理數量：%s
Next: %s|下次交易：%s
Selling yields: %s property points|出售可獲得 %s 財產點數
Selling this item yields|出售此物品可獲得
→ %s property points|→ %s 財產點數
(Price varies by multiplier and random; actual sell price may differ)|（價格受倍率與隨機因素影響，實際售價可能不同）
Selling more of the same item lowers its price|大量出售相同物品會使其價格下降
Selling Bin Trades Config|出貨箱交易設定
Add|新增
Save|儲存
Reload|重新載入
Close|關閉
Delete|刪除
Edit|編輯
Pick Item|選擇物品
Added|已新增
Click to edit|點擊以編輯
Add Trade|新增交易
Count ≥1, Price ≥0|數量須 ≥1，價格須 ≥0
Enter valid numbers|請輸入有效數字
Search by name or ID…|依名稱或 ID 搜尋…
Set Price|設定價格
Count|數量
Price|價格
Confirm|確認
Saved to trades.json|已儲存至 trades.json
Save failed|儲存失敗
Reloaded trades.json|已重新載入 trades.json
Pick Trigger Item|選擇觸發物品
Pick Structure|選擇結構
Summon Entity|召喚實體
Effect (optional)|效果（選填）
Ghastling|小幽靈
Music Disc|唱片
The Nether|地獄
The End|終界
Starcatcher's Smithing|Starcatcher 鍛造
Jungles & Lush Caves|叢林與蒼鬱洞窟
- Price is increased by +%s%% based on top 50%%|- 位居前 50%%，價格提高 +%s%%
Signing will lock in all your current catches|簽名後會固定目前的漁獲紀錄
This book will no longer be updated with new catches after locking.|固定紀錄後，本書將不再收錄新的漁獲。
Bowl Required.|需要碗。
Shift-right-click to place. Right-click with a tool to rotate.|按住 Shift 並按右鍵放置；手持工具按右鍵旋轉。
Rolling in the Deep|深海收穫'''
mapping=dict(line.rsplit('|',1) for line in pairs.splitlines())
# The trade-frequency string itself contains separators.
mapping['Trade Frequency: %s | Process Per Tick: %s']='交易頻率：%s | 每遊戲刻處理數量：%s'
mapping.update({'Hey how did you get this note??':'嘿，你怎麼拿到這張紙條的？？','Are you cheating in creative mode??':'你是在創造模式作弊嗎？？','These notes should only be obtained through':'這些紙條只能透過漂流瓶取得，','bottles otherwise they won\'t have the correct':'否則資料可能不正確，','data and might crash the game! Be careful.':'甚至導致遊戲當機！請小心。'})
mapping['Translucency sorting level, each level has different performance impact and visual quality. \nNone:No translucency sorting, no impact, can look quite bad\nSections: Section level translucency sorting, brings translucency to the same level as sodium, minimal impact\nQuads: Incremental sorting, sorts geometry correctly over multiple frames, can cause visual weirdness while sorting']='半透明排序層級；各層級對效能與畫面品質的影響不同。\n無：不進行排序，不影響效能，但畫面可能不佳\n區塊分段：以區塊分段排序，呈現與 Sodium 相同的半透明效果，效能影響極小\n四邊形：分多幀逐步完成幾何排序，排序期間畫面可能暫時異常'
def process(data):
    return {k:normalize_text(mapping.get(v,v)) if isinstance(v,str) else v for k,v in data.items()}
for p in (out/'mods').glob('*.jar'):
    changes={}
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.endswith('/lang/zh_tw.json'):
                d=json.loads(z.read(n)); result=process(d)
                if '/starcatcher/' in n:
                    # These English continuation lines are already incorporated into preceding Chinese lines.
                    for key in ('gui.guide.page.10.right.7','tooltip.starcatcher.driftfin.1','tooltip.starcatcher.frostjaw_trout.1','tooltip.starcatcher.drifting_bream.1','tooltip.starcatcher.fossilized_angelfish.3','tooltip.starcatcher.dripfin.1','tooltip.starcatcher.willish.3'):
                        result[key]=''
                    result['tooltip.starcatcher.willish.2']='牠極其醜陋，應該被丟回牠所屬的地獄。'
                if result!=d: changes[n]=json.dumps(result,ensure_ascii=False,indent=2).encode()
        if changes: contents={n:z.read(n) for n in z.namelist() if not re.match(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)$',n,re.I)}
    if changes:
        with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
            for n,b in (contents|changes).items(): z.writestr(n,b)
for p in (out/'kubejs/assets').rglob('zh_tw.json'):
    p.write_text(json.dumps(process(json.loads(p.read_text(encoding='utf-8-sig'))),ensure_ascii=False,indent=2),encoding='utf-8')
# Convert Chinese display strings in quest files without touching identifiers or commands.
count=0
for p in (root/'input/config/ftbquests/quests').rglob('*.snbt'):
    text=p.read_text(encoding='utf-8-sig')
    def literal(m):
        value=m[0]
        if re.search('[\u3400-\u9fff]',value) and not re.match(r'"/?(?:execute|give|tellraw|summon|kubejs|ftbquests)\s',value):
            return normalize_text(value)
        return value
    result=re.sub(r'"(?:\\.|[^"\\])*"',literal,text)
    target=out/p.relative_to(root/'input'); target.write_text(result,encoding='utf-8'); count+=1
for p in (out/'config/armorsets').glob('*.json'):
    d=json.loads(p.read_text(encoding='utf-8-sig'))
    def walk(v,key=''):
        if isinstance(v,dict): return {k:walk(x,k) for k,x in v.items()}
        if isinstance(v,list): return [walk(x,key) for x in v]
        return normalize_text(v) if isinstance(v,str) and key in ('customTooltips','description') else v
    p.write_text(json.dumps(walk(d),ensure_ascii=False,indent=2),encoding='utf-8')
print('Normalized quests:',count)
