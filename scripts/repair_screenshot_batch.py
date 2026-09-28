"""Stage reviewable locale changes; --apply installs exactly the staged files."""
import json,re,zipfile,shutil,sys
from pathlib import Path
from full_translation_audit import parse,placeholders
from normalize_zh_tw import normalize_text
from mc_zh_tw_translator.translator import ReferencePackDB,is_jar_signature_file
ROOT=Path(__file__).resolve().parents[1]
BASE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
OUT=ROOT/'output/VEFV2.7.1_screenshot_review'
BACK=ROOT/'output/VEFV2.7.1_screenshot_backup'
PAIRS=dict(s.split('|',1) for s in (ROOT/'data/screenshot_reviewed_pairs.txt').read_text(encoding='utf-8').splitlines() if s)
def chinese(v):return isinstance(v,str) and bool(re.search('[\u3400-\u9fff]',v))
def read(z,n):return parse(z.read(n)) if n in z.namelist() else {}
def save(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if '--apply' in sys.argv:
  manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
  for filename,paths in manifest.items():
   p=BASE/'mods'/filename;b=BACK/'mods'/filename;b.parent.mkdir(parents=True,exist_ok=True)
   if not b.exists():shutil.copy2(p,b)
   changes={n:(OUT/'jars'/filename/n).read_bytes() for n in paths}
   with zipfile.ZipFile(p) as z,zipfile.ZipFile(p.with_suffix('.review.tmp'),'w',zipfile.ZIP_DEFLATED) as w:
    for info in z.infolist():
     if is_jar_signature_file(info.filename):continue
     w.writestr(info,changes.pop(info.filename,z.read(info.filename)))
    for n,v in changes.items():w.writestr(n,v)
   p.with_suffix('.review.tmp').replace(p)
  print('Installed',len(manifest),'JARs');return
 db=ReferencePackDB(ROOT/'data');db.load_all()
 manifest={};report=[];unresolved=[]
 patterns=['handcrafted*','MobLassos*','mineraldelight*','refinedcooking*','simple_cream*','xiangcaomengjia*','untamedwilds*','lightmanscurrency*','the_bumblezone*']
 for pattern in patterns:
  p=next((BASE/'mods').glob(pattern+'.jar'));manifest[p.name]=[]
  with zipfile.ZipFile(p) as z:
   for n in z.namelist():
    if not re.fullmatch(r'assets/[^/]+/lang/en_us.json',n):continue
    ns=n.split('/')[1];db.set_namespace(ns);en=read(z,n);cn=read(z,n.replace('en_us','zh_cn'));tw=read(z,n.replace('en_us','zh_tw'));old=tw.copy()
    overlay=BASE/'kubejs/assets'/ns/'lang/zh_cn.json'
    overlaycn=parse(overlay.read_bytes()) if overlay.exists() else {}
    if ns=='the_bumblezone':
     for k,v in list(tw.items()):
      if v=='Rimsky Korsakov - Flight of the Bumblebee':tw[k]='林姆斯基－柯薩科夫－野蜂飛舞'
     tw['the_bumblezone.midnightconfig.musicDiscTimeLengthFlightOfTheBumblebee']='《野蜂飛舞》音樂唱片播放時長'
     tw['the_bumblezone.music_disc_flight_of_the_bumblebee_rimsky_korsakov.description']='仔細聆聽，仍能聽見一群憤怒蜜蜂的嗡嗡聲……這張稀有唱片可向流浪商人購買，或在蜜蜂領域的特定建築中找到！曲目是林姆斯基－柯薩科夫《野蜂飛舞》的 MIDI 版本。'
     tw['the_bumblezone.configuration.playwrathofhiveeffectmusic.tooltip']='啟用後，當你具有蜂巢之怒效果時，會播放 §6林姆斯基－柯薩科夫§f的§6《野蜂飛舞》§f。'
    elif ns in ['untamedwilds','lightmanscurrency']:
     if ns=='lightmanscurrency':tw['item.minecraft.smithing_template']='鍛造模板'
     else:
      # EntityUtils.getRegistryName uses translated EntityType.getDescription().getString().
      # Mirror every bottle key under the exact localized family name it constructs.
      families={Path(x).stem for x in z.namelist() if re.fullmatch(r'data/untamedwilds/entities/[^/]+\.json',x)}
      entities={k.removeprefix('entity.untamedwilds.'):v for k,v in en.items() if k.removeprefix('entity.untamedwilds.') in families and isinstance(v,str)}
      for k,v in list(tw.items()):
       if not k.startswith('item.untamedwilds.bottle_'):continue
       for entity in sorted(entities,key=len,reverse=True):
        prefix='item.untamedwilds.bottle_'+entity+'_'
        if k.startswith(prefix):
         local=tw.get('entity.untamedwilds.'+entity,entities[entity]).replace(' ','_').lower()
         tw['item.untamedwilds.bottle_'+local+'_'+k[len(prefix):]]=v;break
    else:
     for k in en.keys()|cn.keys():
      v=en.get(k,'');current=tw.get(k,'')
      if k.startswith('itemGroup.') or k.startswith('item_group.') or k.endswith('.author'):continue
      if chinese(current):continue
      source=cn.get(k) or overlaycn.get(k)
      if not chinese(source):source=db.lookup(k)
      if chinese(source):result=normalize_text(source)
      elif v in PAIRS:result=PAIRS[v]
      else:
       if isinstance(v,str) and re.search('[A-Za-z]',v):unresolved.append([ns,k,v,current])
       continue
      reference=en.get(k) or cn.get(k)
      if placeholders(reference)!=placeholders(result):raise ValueError((k,reference,result))
      tw[k]=result
    if ns=='xiangcaomengjia':
     tw['tooltip.xiangcaomengjia.bulk_bonus_hint']='單次出售滿 %s 組可獲得批量加成'
     tw['tooltip.xiangcaomengjia.variety_bonus_hint']='本週期出售 %s 種不同物品可獲得種類加成'
    if ns=='handcrafted':
     tw.update({k:PAIRS[v] for k,v in en.items() if k.startswith('tooltip.') and v in PAIRS})
     tw['tooltip.handcrafted.hold_shift']='按住 SHIFT 查看更多資訊'
     tw['tooltip.handcrafted.shelf_help']='可放置：藥水、書本、陶瓷器與蜘蛛網'
    diff={k:v for k,v in tw.items() if old.get(k)!=v}
    if diff:
     target=n.replace('en_us','zh_tw');save(OUT/'jars'/p.name/target,tw);manifest[p.name].append(target)
     report.extend({'jar':p.name,'file':target,'key':k,'before':old.get(k),'after':v,'en':en.get(k),'cn':cn.get(k) or overlaycn.get(k)} for k,v in diff.items())
 manifest={k:v for k,v in manifest.items() if v}
 save(OUT/'manifest.json',manifest);save(OUT/'changes.json',report);save(OUT/'unresolved.json',unresolved)
 print('Staged:',len(report),'changes in',len(manifest),'JARs; remaining candidates',len(unresolved))
if __name__=='__main__':main()
