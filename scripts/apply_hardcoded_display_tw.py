"""Apply reviewed display-only constants; preserve bytecode and protected tokens."""
import collections,hashlib,json,re,shutil,struct,sys,zipfile
from pathlib import Path
BASE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
OUT=Path('output/VEFV2.7.1_hardcoded_review')
BACK=Path('output/VEFV2.7.1_hardcoded_backup')
PACK=Path('output/VEFV2.7.1_繁體中文化補丁_20260910')
EXTRA={
 'ClientEvent.class','AaroncosLefthandBossBar.class',
 'DreamTrainStructurePr0Procedure.class','ShadowDungeonPortalPr0Procedure.class',
 'WorkshopAnvilPr2Procedure.class','WorkshopGrindPr0Procedure.class',
 'ItemTooltipsCoinProcedure.class','ItemTooltipsKilledProcedure.class','LampShadowPr0Procedure.class',
 'StomachCommand.class','StomachScreen.class','StomachScreen$StomachSwitchButton.class',
 'FreezerCategory.class','TournamentHandler.class','RecyclingPriceClientTooltip.class',
 'XiangcaoSellingBinItem.class','MixinGuiGraphics.class',
}
TERMS={'永珍':'萬象','豬靈':'豬布林','下界之星':'地獄之星','末影箱':'終界箱','末影的力量':'終界的力量',
 '配置介面':'設定介面','配置檔案':'設定檔','回覆4點生命':'恢復4點生命','倒計時':'倒數計時','揹包':'背包',
 '觸控下方':'觸摸下方','未選則':'未選擇','狐火立場':'狐火力場','治療立場':'治療力場','在立場內':'在力場內',
 '受到的的':'受到的','附近的的':'附近的','重新整理':'重設','神秘':'神祕','當前':'目前',
 '潛行右擊':'潛行並按右鍵','聯機':'連線','敲可愛':'超可愛','tips':'提示',
}
EXACT={
 '§7§o哪个魔法师的兜里不会踹几块魔法石呢？':'§7§o哪個魔法師的口袋裡不會揣著幾塊魔法石呢？',
 '§7现实将以为梦粉饰':'§7現實將被夢境妝點',
 '§7甜美而梦幻的味道 让你交融与梦':'§7甜美而夢幻的滋味，讓你與夢境交融',
 '§a前往下层打开触摸大门的“眼睛”':'§a前往下層，觸摸大門的「眼睛」以開啟大門',
 '笔记的背面刻印这一个坐标':'筆記背面刻著一組座標',
 '§7对空气使用以跳跃世界时间更替昼夜':'§7對空氣使用，可快轉世界時間，切換晝夜',
 '§7产生会顶去所有占地方块 不要在家使用！':'§7產生結構會取代範圍內的方塊，不要在家中使用！',
 '§7生成会顶去所有占地方块 不要在家使用！':'§7產生結構會取代範圍內的方塊，不要在家中使用！',
 '§7请不要用蓝图点击浸影宝盒哦 （源于一次崩溃bug）':'§7請勿手持藍圖點擊浸影寶盒（曾因此發生當機）。',
 '请不要用蓝图点击浸影宝盒哦 （源于一次崩溃bug）':'請勿手持藍圖點擊浸影寶盒（曾因此發生當機）。',
 '§5你回想到了曾经也有过类似的感觉，也许应该躺倒床上休息一下...':'§5你想起以前也有過類似的感覺，也許該躺到床上休息一下……',
 '§5你在睡梦中惊醒，背后冒出了些许冷汗，你回忆起自己梦见了往日探索中遇见的奇怪裂隙，在慢慢靠近并凝视着你。':'§5你從睡夢中驚醒，背後冒出些許冷汗。你想起夢中那道曾在探索時遇見的奇怪裂隙，正慢慢靠近，凝視著你。',
 '§5你拿起附近的材料迅速地把这些梦境记录下来，在这之后你就失去了对这段梦境的记忆。':'§5你拿起附近的材料，迅速記下夢中的景象。寫完之後，這段夢境便從你的記憶中消失了。',
 '§7▪ §9对以自身为中心 引燃19*19范围内的所有亡灵生物15秒并造成20点火焰伤害':'§7▪ §9以自身為中心，點燃19*19範圍內所有不死生物15秒，並造成20點火焰傷害',
 '§7▪ §9对以自身为中心 7*7范围内的所有敌人陷入混乱并失去行动能力 持续10秒':'§7▪ §9使自身周圍7*7範圍內的所有敵人陷入混亂，並失去行動能力，持續10秒',
 '§7▪ §9立刻重置瞬身术的cd时间':'§7▪ §9立即重設瞬身術的冷卻時間',
 '§7▪ §9恢复san值 部分正面药水效果 额外饱和':'§7▪ §9恢復精神值、獲得部分正面藥水效果與額外飽和度',
 '§7▪ §9获得的增益强度与食用食物的饱食/饱和成正相关':'§7▪ §9食物提供的飽食度／飽和度越高，獲得的增益就越強',
 '§7你受到了笔记的启发':'§7你受到筆記的啟發',
 '§7你收到了笔记的启发':'§7你受到筆記的啟發',
}
def tweak(old,new):
 if old in EXACT:return EXACT[old]
 for a,b in TERMS.items():new=new.replace(a,b)
 new=new.replace('收到了筆記的啟發','受到筆記的啟發')
 new=re.sub(r'\bshift\b','SHIFT',new,flags=re.I);new=re.sub(r'\bctrl\b','CTRL',new,flags=re.I)
 return new
def immutable(b):
 # Replace UTF8 entries with a marker; every other byte must be identical.
 i=10;k=1;out=[b[:10]]
 while k<struct.unpack_from('>H',b,8)[0]:
  start=i;t=b[i];i+=1
  if t==1:size=struct.unpack_from('>H',b,i)[0];i+=2+size;out.append(b'\x01')
  else:
   if t in (5,6):i+=8;k+=1
   else:i+={3:4,4:4,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}[t]
   out.append(b[start:i])
  k+=1
 return b''.join(out)+b[i:]
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if '--apply' not in sys.argv:
  rows=json.loads(Path('output/hardcoded_display_review.json').read_text(encoding='utf-8'));approved=[];pending=[]
  for r in rows:
   name=r['entry'].split('/')[-1]
   literal=r['status']=='direct_literal' or (r['uses'] and all('net/minecraft/class_2561.method_43470:' in u for u in r['uses']))
   # Config comments are descriptions only, never push/define keys or values.
   comment=bool(r['uses']) and all('ForgeConfigSpec$Builder.comment:' in u for u in r['uses'])
   extra=name in EXTRA and (r['jar'].startswith(('PasterDream','DimensionalStomach','kaleidoscope_world_liquor','starcatcher','xiangcaomengjia')))
   if not (literal or comment or extra):pending.append(r);continue
   r['new']=tweak(r['old'],r['new'])
   if r['old']==r['new']:continue
   for pattern in [r'§[0-9a-fk-or]',r'[\x01\x02]',r'%(?:\d+\$)?(?:\.\d+)?[sdf]',r'\n',r'#+']:
    assert re.findall(pattern,r['old'])==re.findall(pattern,r['new']),(r['old'],r['new'],pattern)
   r['evidence']='direct literal' if literal else 'configuration comment' if comment else 'reviewed display context'
   approved.append(r)
  (OUT/'changes.json').write_text(json.dumps(approved,ensure_ascii=False,indent=2),encoding='utf-8')
  (OUT/'remaining_context.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf-8')
  print('Staged',len(approved),'constants;',len(pending),'other contexts');return
 rows=json.loads((OUT/'changes.json').read_text(encoding='utf-8'));byjar=collections.defaultdict(list)
 for r in rows:byjar[r['jar']].append(r)
 for name,changes in byjar.items():
  p=BASE/'mods'/name;backup=BACK/'mods'/name;backup.parent.mkdir(parents=True,exist_ok=True)
  if not backup.exists():shutil.copy2(p,backup)
  edits={}
  with zipfile.ZipFile(p) as z:
   for r in changes:
    b=edits.get(r['entry'],z.read(r['entry']));a=r['old'].encode();v=r['new'].encode()
    needle=b'\x01'+struct.pack('>H',len(a))+a
    assert b.count(needle)==1,(name,r['entry'],r['old'])
    edits[r['entry']]=b.replace(needle,b'\x01'+struct.pack('>H',len(v))+v)
   for n,b in edits.items():assert immutable(z.read(n))==immutable(b),n
   with zipfile.ZipFile(p.with_suffix('.tw.tmp'),'w',zipfile.ZIP_DEFLATED) as w:
    for info in z.infolist():
     if re.fullmatch(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)',info.filename,re.I):continue
     w.writestr(info,edits.get(info.filename,z.read(info.filename)))
  p.with_suffix('.tw.tmp').replace(p);shutil.copy2(p,PACK/'mods'/name)
  orig=Path('input/VEFV2.7.1_zh_tw_patch/mods')/name
  if not orig.exists():shutil.copy2(Path('input/mods')/name,orig)
 manifest=json.loads((PACK/'檔案清單.json').read_text(encoding='utf-8'));md={r['path']:r for r in manifest}
 for name in byjar:
  p=PACK/'mods'/name;rel='mods/'+name
  md[rel]=dict(path=rel,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),reason='繁中語系及已確認用途的硬編碼顯示文字／設定說明')
 (PACK/'檔案清單.json').write_text(json.dumps(list(md.values()),ensure_ascii=False,indent=2),encoding='utf-8')
 print('Applied',len(rows),'constants in',len(byjar),'JARs; bytecode structure unchanged')
if __name__=='__main__':main()
