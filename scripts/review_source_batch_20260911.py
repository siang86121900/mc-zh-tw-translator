"""Stage the individually inspected source-backed batch; retain unresolved items."""
import json,re,zipfile,hashlib,collections
from pathlib import Path
from opencc import OpenCC
from full_translation_audit import placeholders,fingerprint
from review_context_20260911 import CONTEXT
BASE=Path('C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
OUT=Path('output/review_20260911');CC=OpenCC('s2twp')
rows=json.loads((OUT/'source_proposals.json').read_text(encoding='utf8'))
rows=[r for r in rows if 'english' in r['flags'] or 'missing' in r['flags']]
existing={(r['source'],r['key']) for r in rows}
for line in (OUT/'before/strings.jsonl').read_text(encoding='utf8').splitlines():
 r=json.loads(line)
 if r['kind']=='language' and r['key'] in CONTEXT and (r['source'],r['key']) not in existing:
  rows.append(dict(r,proposal=CONTEXT[r['key']],translation_source='context_review'));existing.add((r['source'],r['key']))
manual={
'tooltip.composite_material.creative_reinforced_book':'在合成格中，可提升附魔物品上所有最高等級不為 1 的附魔（最多比原本最高等級再提高 %s 級）。',
'message.composite_material.lacerator':'蓄力時間：%f秒 額外傷害：%f 箭矢基礎傷害：%.2f',
'message.composite_material.lacerator_1':'蓄力時間：%f秒 額外傷害：%f',
'waila.cookingforblockheads:toast_progress':'烘烤中……（%s %%）',
'gui.enchantinginfuser.tooltip.enchanting_power':'附魔能力',
'death.attack.endergetic.munch':'%1$s 被 %2$s 啃咬致死',
'fancymenu.placeholders.percentram':'已用記憶體（%%）',
'command.lightmanscurrency.lcadmin.traderdata.list.dimension':'維度：%s',
'gui.lightmanscurrency.interface.difference.expensive':'交易價格高出 %s',
'gui.lightmanscurrency.interface.info.trader.permissions':'你已無權連結至 %s',
'gui.lightmanscurrency.interface.item.difference.quantity.less':'交易少了 %1$s %2$s 個物品',
'gui.lightmanscurrency.interface.item.difference.quantity.more':'交易多了 %1$s %2$s 個物品',
'tooltip.lightmanscurrency.colored_item':'顏色：%s',
'tooltip.lightmanscurrency.slot_machine.roll.once.2':'花費 %1$s',
'traderule.lightmanscurrency.timed_sale.info.purchase':'此交易正在促銷，將為 %2$s 多支付 %1$s%%',
'traderule.lightmanscurrency.timed_sale.info.sale':'此交易正在促銷，以 %1$s%% 的價格出售 %2$s',
'tooltip.smc.perfrostite_armors':'免疫中毒、飢餓、緩速與黑暗效果。',
'death.attack.the_bumblezone.architects.player':'%1$s 因試圖逃離精華事件而喪命',
'death.attack.the_bumblezone.cosmic_crystal.player':'%1$s 被宇宙水晶的力量徹底摧毀',
'death.attack.the_bumblezone.sentry_watcher_crushing.player':'%1$s 被哨兵守衛壓死了',
'death.attack.the_bumblezone.spikes.player':'%1$s 在全知精華事件中被刺穿了',
'death.attack.twilightforest.yeeted':'%1$s 最後一次被拋飛了',
'block.youkaishomecoming.bloody_flesh':'血淋淋的肉',
'item.youkaishomecoming.flesh_chocolate_mousse':'%1$s巧克力慕斯',
'sodium.options.buttons.apply':'套用','sodium.options.buttons.donate':'支持 Sodium！','sodium.options.buttons.undo':'復原',
'sodium.options.pages.quality':'畫質','sodium.options.pages.advanced':'進階',
'sodium.options.use_no_error_context.name':'停用 OpenGL 錯誤檢查',
'sodium.options.use_no_error_context.tooltip':'啟用後，會建立停用錯誤檢查的 OpenGL 執行環境。這可能略微提升效能，但遇到 OpenGL 錯誤時，遊戲更可能直接當機而無法妥善處理。若出現原因不明的突然當機，請停用此選項。',
'embeddium.options.use_quad_normals_for_lighting.name':'使用精確的四邊形明暗計算',
'embeddium.options.use_quad_normals_for_lighting.tooltip':'啟用後，Embeddium 會依非原版方塊面的實際朝向計算明暗，而非使用對齊座標軸的方向。停用 Forge 實驗性光照管線時，可改善光照品質（為獲得最佳效能，建議停用該管線）。\n\n若實驗性光照管線已啟用，此選項便不會生效。',
'sodium.options.biome_blend.tooltip':'控制方塊染色時，取樣周圍生態域的範圍。提高此值會大幅增加區塊建構時間，而畫質改善會逐漸趨緩。',
'sodium.options.cpu_render_ahead_limit.tooltip':'設定 CPU 最多可預先提交多少畫格，等待 GPU 完成繪製。數值過低或過高都可能導致畫面更新率不穩定。',
'sodium.options.graphics_quality.tooltip':'預設畫質會控制部分舊式選項，也是維持模組相容性所需的設定。下方選項若設為「預設」，便會沿用此設定。',
'sodium.options.use_block_face_culling.tooltip':'啟用後，只有朝向鏡頭的方塊面會提交繪製。這能在繪製流程前期排除大量方塊面，節省 GPU 記憶體頻寬與運算時間。部分資源包可能不相容；若方塊出現破洞，請嘗試停用。',
'sodium.options.use_fog_occlusion.tooltip':'啟用後，不會繪製完全被霧遮住的區塊，以提升效能。霧較濃時（例如水下）改善可能更明顯，但某些場景的天空與霧之間可能出現顯示瑕疵。',
'enchantment.improved_exp.bakingpowder.desc':'讓鋤頭一次耕作多個方塊。',
'enchantment.improved_exp.fear_of_dark.desc':'穿戴者身處黑暗時會受到傷害。',
'enchantment.improved_exp.harm.desc':'移除穿戴者身上的所有增益效果。',
'enchantment.improved_exp.hungry.desc':'穿戴者會持續失去飽食度與飽和度。',
'enchantment.improved_exp.saturation.desc':'恢復飽食度與飽和度。',
'enchantment.improved_exp.fertilizing.desc':'按下 Z 鍵，對附近方塊施加骨粉效果。',
'enchantment.improved_exp.return_from_void.desc':'穿戴者墜入虛空時，將其傳送回地表。',
'enchantment.improved_exp.passage.desc':'使用者會飛向視線所朝的位置。',
'enchantment.improved_exp.lavawalker.desc':'附近的熔岩會凝固成黑曜石。',
'enchantment.deeperdarker.catalysis.desc':'擊殺生物時，會讓伏聆在附近蔓延。',
'enchantment.create_sa.impact.desc':'讓攪拌器抓鉤能造成一小波範圍傷害。',
}
for k in ['death.attack.gas.player','death.attack.moon_arrow.item','death.attack.moon_arrow.player']:manual[k]='%1$s 被 %2$s 使用 %3$s 殺死了'
manual.update(CONTEXT)
skip={r['key']:'須核對相鄰組句或模組特殊行為後再改' for r in rows if ('EnigmaticLegacy-' in r['source'] or 'simplyswords-' in r['source'] or r['key'] in ['itemGroup.bygonenethertab','item.patchouli:intro_book.name','death.attack.twilightdelight.thorn_rose_tea.player','twilightforest.book.tfstronghold.2','tooltip.ironfurnaces.rainbow_gen2'])}
approved=[];pending=[];byjar=collections.defaultdict(list)
for r in rows:
 if r['key'] in skip and r['key'] not in CONTEXT:pending.append(dict(r,reason=skip[r['key']]));continue
 v=manual.get(r['key'],CC.convert(r['proposal']))
 for a,b in {'配置':'設定','全屏':'全螢幕','渲染':'繪製','幀率':'畫面更新率','幀生成時間':'畫格生成時間','幀數':'畫格數','幀':'畫格','重新整理率':'更新率','紋理':'材質','質量':'品質','禁用':'停用','崩潰':'當機','生物群系':'生態域','生物群落':'生態域','刷怪蛋':'生怪蛋','魔咒':'附魔','彈射物':'投射物','幽匿':'伏聆','移動地更快':'移動得更快'}.items():v=v.replace(a,b)
 if isinstance(r['en'],str) and placeholders(r['en'])!=placeholders(v):pending.append(dict(r,reason='參數不相符'));continue
 r=dict(r,after=v,review_note='逐項對照目前英文與中文來源，校正版本、語意及參數；不是僅憑來源命中。')
 approved.append(r);byjar[r['source'].split('!/')[0]].append(r)
hashes={}
for rel,group in byjar.items():
 p=BASE/rel;hashes[rel]=hashlib.sha256(p.read_bytes()).hexdigest();edits={}
 with zipfile.ZipFile(p) as z:
  for r in group:
   n=r['source'].split('!/',1)[1].replace('/en_us.json','/zh_tw.json');d=edits.setdefault(n,json.loads(z.read(n)))
   assert d.get(r['key'])==r['current'];d[r['key']]=r['after']
  dest=OUT/'staged'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
  with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as w:
   for i in z.infolist():
    if re.match(r'META-INF/.*\.(SF|RSA|DSA|EC)$',i.filename,re.I):continue
    w.writestr(i,json.dumps(edits[i.filename],ensure_ascii=False,indent=2).encode() if i.filename in edits else z.read(i.filename))
(OUT/'batch_review.json').write_text(json.dumps(dict(approved=approved,pending=pending,source_hashes=hashes),ensure_ascii=False,indent=2),encoding='utf8')
print(len(approved),'reviewed changes in',len(hashes),'jars;',len(pending),'held for context')
