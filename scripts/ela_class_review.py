"""Extract constant-pool strings and every javap load site for ELA review."""
import collections,json,re,struct
from pathlib import Path

def pool(b):
    entries={};p=10;i=1;count=struct.unpack_from('>H',b,8)[0]
    sizes={3:4,4:4,5:8,6:8,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}
    while i<count:
        start=p;tag=b[p];p+=1
        if tag==1:
            n=struct.unpack_from('>H',b,p)[0];p+=2;raw=b[p:p+n];p+=n
            value=raw.replace(b'\xc0\x80',b'\0').decode('utf-8','surrogatepass')
        else:
            n=sizes[tag];raw=b[p:p+n];p+=n;value=struct.unpack('>H',raw)[0] if tag==8 else None
        entries[i]=(tag,value,start,p)
        i+=2 if tag in (5,6) else 1
    return entries,p

if __name__=='__main__':
    out=Path('output/ELA/class_review');rows=[]
    for p in out.glob('*.class'):
        cp,_=pool(p.read_bytes());lines=p.with_suffix('.javap.txt').read_text(encoding='utf-8',errors='replace').splitlines()
        for index,(tag,s,start,end) in cp.items():
            if tag!=1 or not re.search('[\u3400-\u9fff]',s):continue
            refs=[i for i,v in cp.items() if v[0]==8 and v[1]==index];uses=[]
            for i,line in enumerate(lines):
                if any(re.search(r'\bldc(?:_w)?\s+#'+str(k)+r'\s',line) for k in refs):
                    # Record all bytecode instructions until the next invoke.
                    excerpt=[]
                    for x in lines[i:i+35]:
                        excerpt.append(x.strip())
                        if re.search(r'\binvoke(?:static|virtual|interface|special|dynamic)\b',x):break
                    uses.append(excerpt)
            rows.append(dict(file=p.name,index=index,old=s,uses=uses))
    (out/'uses.json').write_text(json.dumps(rows,ensure_ascii=True,indent=2),encoding='utf-8')
    groups=collections.Counter(u[-1].split('//')[-1].strip() for r in rows for u in r['uses'])
    print(*groups.most_common(),sep='\n');print('strings',len(rows),'no loads',sum(not r['uses'] for r in rows))
