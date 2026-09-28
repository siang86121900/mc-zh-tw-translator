"""Package an existing instance's translation changes without personal state."""
from pathlib import Path
import collections,hashlib,json,os,re,shutil,zipfile
BASE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
NAME='VEFV2.7.1_繁體中文化補丁_20260910'
DEST=Path('output')/NAME
ORIGINAL=Path('input/VEFV2.7.1_zh_tw_patch')
INV=json.loads(Path('output/share_inventory.json').read_text(encoding='utf-8'))
selected={x['file']:'模組中文語系、書本或已確認的提示修正' for x in INV['jars']}
for folder in ['kubejs/assets','kubejs/data','config','defaultconfigs','patchouli_books']:
 for p in (BASE/folder).rglob('*'):
  if not p.is_file():continue
  rel=p.relative_to(BASE).as_posix()
  if '/zh_tw/' in '/'+rel or re.search(r'/zh_tw\.(json|lang|local|txt)$',rel):selected[rel]='繁體中文語系或書本資源'
for x in INV['loose']:
 rel=x['file']
 if rel.startswith('config/ftbquests/quests/') and rel.endswith('.snbt'):selected[rel]='任務文字定義，不含玩家進度'
 if rel.startswith('kubejs/client_scripts/src/') and rel.endswith('.js'):
  before=(Path('input')/rel).read_text(encoding='utf-8-sig');after=(BASE/rel).read_text(encoding='utf-8-sig')
  # Reject logic changes: outside string literals, all code must remain identical.
  string=re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`''')
  assert string.sub('STRING',before)==string.sub('STRING',after),rel
  selected[rel]='既有客戶端提示腳本的文字修正'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
DEST.mkdir(parents=True,exist_ok=True);manifest=[]
for rel,reason in sorted(selected.items()):
 src=BASE/rel;dst=DEST/rel;dst.parent.mkdir(parents=True,exist_ok=True)
 shutil.copy2(src,dst);digest=sha(dst);assert sha(src)==digest,rel
 manifest.append(dict(path=rel,bytes=dst.stat().st_size,sha256=digest,reason=reason))
 if rel.startswith('mods/'):
  orig=ORIGINAL/rel;orig.parent.mkdir(parents=True,exist_ok=True)
  if not orig.exists():shutil.copy2(Path('input')/rel,orig)
counts=collections.Counter(r['path'].split('/')[0] for r in manifest)
readme=f'''VEFV2.7.1 繁體中文化補丁

這是中文化補丁，不是完整模組包。
對方必須先安裝完整且相同版本的 VEFV2.7.1，再套用本補丁。
Minecraft 1.20.1 / Forge 47.4.10。不要直接貼進空白 Forge 設定檔。

安裝方法
1. 安裝完整 VEFV2.7.1，確認模組版本相符，然後關閉 Minecraft。
2. 在 CurseForge 對該模組包按右鍵，選「Open Folder／開啟資料夾」。
3. 先備份自己的 mods、kubejs 與 config。若已有世界，也先备份 saves。
4. 解壓縮本補丁，把 mods、kubejs、config 等提供的資料夾貼進上一步
   開啟的位置，允許合併資料夾，遇到同名檔案選「取代目的地中的檔案」。
   不要刪除原本整個 mods／config／kubejs；本包只提供需要覆蓋的檔案。
   不要把外層補丁資料夾整個貼進去，也不要把全部內容塞入 mods。
5. 開啟遊戲，在語言選單選擇「繁體中文」，然後重新啟動遊戲。

貼上後的結構範例
你的 VEFV2.7.1 資料夾/
  mods/       中文化過的同版本模組 JAR
  kubejs/     繁中語系及客戶端提示文字
  config/     任務文字與其他繁中語系

本包內容
依目前 instance 與本機原始輸入比對，收錄 {counts.get('mods',0)} 個修改過的 JAR。
KubeJS 檔案 {counts.get('kubejs',0)} 個，config 檔案 {counts.get('config',0)} 個。
完整路徑與 SHA-256 見「檔案清單.json」。清單及本說明不必貼入遊戲資料夾。
JAR 內包含語系、書本及一處已確認的硬編碼提示翻譯，因此不能只分享
外部 zh_tw.json 就涵蓋目前修正。沒有中文化差異的模組由原模組包提供。

未包含
世界存檔、玩家任務進度、帳號資料、options.txt、伺服器清單、地圖記錄、
截圖、日誌、備份、個人材質包與光影設定；不會替對方切換語言或按鍵。
另行新增且沒有中文化差異依據的 IMBlocker 不包含在此補丁。

注意
這份是目前已完成修正的分享快照，仍可能有漏翻或待校對文字，
不代表全包已經百分之百翻譯完成。不同模組版本不能直接混用；
若目的地已有不同版本的同名模組，請先恢復相同版本的原包再套用。
補丁不會改玩家進度，但既有存檔或伺服器自己的任務文字覆蓋仍可能優先生效。
先前「建立空白 Forge 後貼上完整包」的教學適用完整包，不適用本補丁。
'''.replace('备份','備份')
(DEST/'安裝說明.txt').write_text(readme,encoding='utf-8-sig')
(DEST/'檔案清單.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
Path('output/translation_share_summary.json').write_text(json.dumps(dict(folder=str(DEST),files=len(manifest),counts=dict(counts),bytes=sum(x['bytes'] for x in manifest)),ensure_ascii=False,indent=2),encoding='utf-8')
print('Staged',len(manifest),'files',dict(counts),flush=True)
