"""Stage screenshot-family fixes, with bytecode use checks and no sharing."""
import json,re,zipfile,struct,subprocess,hashlib,shutil
from pathlib import Path
from audit_hardcoded_display import pool
BASE=Path('C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
OUT=Path('output/latest_screenshot_fix');OUT.mkdir(parents=True,exist_ok=True)
changes=[];hashes={};classes=[]
manual={
'item.simplyswords.caelestis':'天穹',
'effect.simplyswords.astral_shift':'星界轉移',
'block.twilightforest.wrought_iron_fence':'鍛鐵柵欄',
'block.twilightforest.wrought_iron_fence.cap':'手持鐵錠或鐵粒按右鍵，即可加上頂端飾件',
'subtitles.twilightforest.block.wrought_iron_fence.extend':'鐵器鏗鏘作響',
}
for i,v in enumerate(['獨特效果：星界轉移','持握時，有機率','完全避開','襲來的傷害。','短暫踏入星界，','期間免疫所有傷害，持續','%d秒','離開星界時，','會引發猛烈爆炸；','根據停留星界期間','所抵擋的傷害量，','對周圍造成範圍傷害。'],1):manual[f'item.simplyswords.caelestissworditem.tooltip{i}']=v
for m,t in {'copper':'銅','diamond':'鑽石','emerald':'綠寶石','ender_pearl':'終界珍珠','gold':'金','iron':'鐵','lapis':'青金石','netherite':'獄髓'}.items():manual['item.lightmanscurrency.coin_ancient.'+m]='古代'+t+'硬幣'
parts={'button':'按鈕','door':'門','fence':'柵欄','fence_gate':'柵欄門','log':'原木','planks':'材','pressure_plate':'壓力板','sapling':'樹苗','slab':'半磚','stairs':'樓梯','trapdoor':'地板門','wood':'塊'}
for part,v in parts.items():manual['block.eeeabsmobs.blighted_oak_'+part]='枯萎橡木'+v
manual.update({'block.eeeabsmobs.stripped_blighted_oak':'剝皮枯萎橡木原木','block.eeeabsmobs.stripped_blighted_oak_wood':'剝皮枯萎橡木塊','block.eeeabsmobs.blighted_stone_button':'枯石按鈕','block.eeeabsmobs.blighted_stone_pressure_plate':'枯石壓力板'})
literal={'§7Right-click with Chest to add Storage':'§7手持儲物箱按右鍵，即可增加收納空間','§7Right-click with Cauldron to add Sink':'§7手持鍋釜按右鍵，即可加裝水槽'}
for p in (BASE/'mods').glob('*.jar'):
 if not re.match(r'(cozy_home|eeeabsmobs|lightmanscurrency|simplyswords|twilightforest|untamedwilds)-',p.name):continue
 edits={}
 with zipfile.ZipFile(p) as z:
  for n in z.namelist():
   if re.match(r'^assets/[^/]+/lang/zh_tw.json$',n):
    d=json.loads(z.read(n));old=dict(d);ns=n.split('/')[1]
    for k,v in manual.items():
     if k.split('.')[1]==ns:d[k]=v
    if ns=='untamedwilds':
     prefix='entity.untamedwilds.'
     bases={k[len(prefix):]:v for k,v in old.items() if k.startswith(prefix) and '.' not in k[len(prefix):] and '_' not in k[len(prefix):] and re.search('[\u3400-\u9fff]',v)}
     for k,v in old.items():
      for b,tw in bases.items():
       if k.startswith(prefix+b+'_'):d[prefix+tw+k[len(prefix+b):]]=v;break
    if ns=='simplyswords':
     trans={'Caelestis':'天穹','Astral Shift':'星界轉移','damage modifier':'傷害倍率','attack speed':'攻擊速度','can be looted':'可從戰利品獲得','cooldown':'冷卻時間','duration':'持續時間','damage max':'傷害上限','avoidance chance':'閃避機率'}
     for k,v in list(d.items()):
      if k.startswith('text.autoconfig.') and ('caelesti' in k.lower() or 'astralshift' in k.lower()):
       for a,b in trans.items():v=v.replace(a,b)
       d[k]=v
    for k,v in d.items():
     if old.get(k)!=v:changes.append(dict(source=p.name+'!/'+n,key=k,before=old.get(k),after=v))
    if d!=old:edits[n]=json.dumps(d,ensure_ascii=False,indent=2).encode()
   if p.name.startswith('cozy_home') and n.endswith('.class'):
    raw=z.read(n);cp=pool(raw);found={i:s for i,s in cp.items() if s in literal}
    if not found:continue
    result=subprocess.run(['javap','-J-Dfile.encoding=UTF-8','-c','-p','-classpath',str(p),n[:-6].replace('/','.')],capture_output=True)
    assert result.returncode==0,result.stderr
    listing=result.stdout.decode('utf8');(OUT/(Path(n).stem+'.javap.txt')).write_text(listing,encoding='utf8')
    ins=[s.strip() for s in listing.splitlines() if re.match(r'\s*\d+:',s)]
    changed=raw
    for idx,s in found.items():
     uses=[ins[i+1] for i,x in enumerate(ins[:-1]) if re.match(r'\d+: ldc(?:_w)?\s+#'+str(idx)+r'\s',x)]
     if n.endswith('/GeneralDeskToolTipProcedure.class'):
      assert uses==['2: areturn']
      callers=[q for q in z.namelist() if q.endswith('.class') and q!=n and b'GeneralDeskToolTipProcedure' in z.read(q)]
      assert callers
      for q in callers:
       r=subprocess.run(['javap','-J-Dfile.encoding=UTF-8','-c','-p','-classpath',str(p),q[:-6].replace('/','.')],capture_output=True)
       assert r.returncode==0
       listing2=r.stdout.decode('utf8');(OUT/(Path(q).stem+'.javap.txt')).write_text(listing2,encoding='utf8')
       seq=[x.strip() for x in listing2.splitlines() if re.match(r'\s*\d+:',x)]
       callers_uses=[seq[j+1] for j,x in enumerate(seq[:-1]) if 'GeneralDeskToolTipProcedure.execute' in x]
       assert callers_uses and all('Component.m_237113_' in x for x in callers_uses),q
     else:assert uses and all('Component.m_237113_' in u for u in uses),(n,s,uses)
     a=s.encode();b=literal[s].encode();needle=b'\x01'+struct.pack('>H',len(a))+a;replacement=b'\x01'+struct.pack('>H',len(b))+b
     assert changed.count(needle)==1
     changed=changed.replace(needle,replacement)
     changes.append(dict(source=p.name+'!/'+n,key=idx,before=s,after=literal[s]))
    check=changed
    for s in found.values():
     a=s.encode();b=literal[s].encode();check=check.replace(b'\x01'+struct.pack('>H',len(b))+b,b'\x01'+struct.pack('>H',len(a))+a)
    assert check==raw
    edits[n]=changed;classes.append(n)
  if edits:
   hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
   dst=OUT/'staged/mods'/p.name;dst.parent.mkdir(parents=True,exist_ok=True)
   with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
    for i in z.infolist():
     if re.match(r'META-INF/.*\.(SF|RSA|DSA|EC)$',i.filename,re.I):continue
     w.writestr(i,edits.get(i.filename,z.read(i.filename)))
(OUT/'report.json').write_text(json.dumps(dict(changes=changes,source_hashes=hashes,classes=classes),ensure_ascii=False,indent=2),encoding='utf8')
print('Staged',len(changes),'changes;',len(hashes),'jars;',len(classes),'classes')
