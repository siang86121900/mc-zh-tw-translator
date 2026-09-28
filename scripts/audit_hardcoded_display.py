"""Find Chinese JVM constants and prove direct Component.literal usage before staging."""
import json,re,struct,subprocess,zipfile
from pathlib import Path
from collections import Counter
from normalize_zh_tw import normalize_text
BASE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1/mods')
def pool(b):
 i=10;k=1;utf={};strings={};count=struct.unpack_from('>H',b,8)[0]
 while k<count:
  t=b[i];i+=1
  if t==1:
   size=struct.unpack_from('>H',b,i)[0];i+=2;utf[k]=b[i:i+size].decode('utf-8','replace');i+=size
  elif t==8:strings[k]=struct.unpack_from('>H',b,i)[0];i+=2
  elif t in (5,6):i+=8;k+=1
  else:i+={3:4,4:4,7:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}[t]
  k+=1
 return {k:utf[v] for k,v in strings.items()}
def main():
 rows=[];counts=Counter();errors=[]
 for p in BASE.glob('*.jar'):
  candidates={}
  with zipfile.ZipFile(p) as z:
   for n in z.namelist():
    if not n.endswith('.class'):continue
    try:cp=pool(z.read(n))
    except Exception as e:errors.append([p.name,n,str(e)]);continue
    cn={k:v for k,v in cp.items() if re.search('[\u3400-\u9fff]',v)}
    if cn:candidates[n]=cn
  if not candidates:continue
  classes=list(candidates);counts['classes']+=len(classes)
  outputs={}
  for start in range(0,len(classes),25):
   group=classes[start:start+25]
   result=subprocess.run(['javap','-J-Dfile.encoding=UTF-8','-c','-p','-classpath',str(p)]+[s[:-6].replace('/','.') for s in group],capture_output=True)
   if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
   raw=result.stdout.decode('utf-8')
   chunks=re.split(r'(?=Compiled from ")',raw)
   for chunk in chunks:
    m=re.search(r'(?:class|interface|enum) ([\w.$]+)',chunk)
    if m:outputs[m[1].replace('.','/')+'.class']=chunk
  for n,cp in candidates.items():
   listing=outputs.get(n,'');instructions=[s.strip() for s in listing.splitlines() if re.match(r'\s*\d+:',s)]
   uses={k:[] for k in cp}
   for index,line in enumerate(instructions):
    m=re.match(r'\d+: ldc(?:_w)?\s+#(\d+)\s',line)
    if m and int(m[1]) in uses:uses[int(m[1])].append(instructions[index+1] if index+1<len(instructions) else '')
   for k,old in cp.items():
    new=normalize_text(old)
    if new==old:continue
    direct=bool(uses[k]) and all('net/minecraft/network/chat/Component.m_237113_:' in u for u in uses[k])
    row=dict(jar=p.name,entry=n,constant=k,old=old,new=new,status='direct_literal' if direct else 'needs_context',uses=uses[k])
    rows.append(row);counts[row['status']]+=1
  print(p.name,len(candidates),'classes',flush=True)
 Path('output/hardcoded_display_review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 Path('output/hardcoded_display_scan_summary.json').write_text(json.dumps(dict(counts=dict(counts),errors=errors),ensure_ascii=False,indent=2),encoding='utf-8')
 print(dict(counts),'errors',len(errors),flush=True)
if __name__=='__main__':main()
