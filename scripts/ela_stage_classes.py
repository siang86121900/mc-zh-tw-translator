"""Patch only ELA class constants whose complete load sites have display evidence."""
import hashlib,json,re,struct,subprocess,zipfile
from pathlib import Path
from ela_class_review import pool
from ela_stage import BASE,OUT,STAGE,convert,tokens

def digest(b):return hashlib.sha256(b).hexdigest()
def rewrite(b,edits):
    cp,end=pool(b);parts=[b[:10]]
    for i,(tag,value,a,z) in cp.items():
        if i not in edits:parts.append(b[a:z]);continue
        assert tag==1 and edits[i]['old']==value
        v=edits[i]['new'].encode('utf-8','surrogatepass').replace(b'\0',b'\xc0\x80')
        parts.append(b'\x01'+struct.pack('>H',len(v))+v)
    result=b''.join(parts)+b[end:];other,end2=pool(result)
    assert b[end:]==result[end2:] and cp.keys()==other.keys()
    for i,(tag,value,a,z) in cp.items():
        if i not in edits:
            _,_,aa,zz=other[i];assert b[a:z]==result[aa:zz]
        else:assert other[i][1]==edits[i]['new']
    return result

if __name__=='__main__':
    rows=json.loads((OUT/'class_review/uses.json').read_text());source_rows=json.loads((OUT/'chinese_class.json').read_text(encoding='utf-8'))
    sources={r['source'].split('/')[-1]:r['source'] for r in source_rows};approved=[];pending=[];byjar={}
    allow=re.compile(r'(?:QuestObjective\$Builder\.text:|QuestDefinition\$Builder\.(?:title|shortDescription|description):|Method chapterTitle:|Method proofItem:|Method targetCompletionObjective:|Method buildNpcVisitQuest:|Method registerSecondRoundWorldHuntQuest:|InterfaceMethod net/minecraft/network/chat/Component\.m_237113_:|Method sendMessage:)')
    for r in rows:
        new=convert(r['old'])
        if new==r['old']:continue
        if not r['uses'] or not all(allow.search(u[-1]) for u in r['uses']):pending.append(r);continue
        assert tokens(r['old'])==tokens(new)
        assert re.findall('[\x00-\x02]',r['old'])==re.findall('[\x00-\x02]',new)
        assert re.findall(r'\d+',r['old'])==re.findall(r'\d+',new)
        source=sources[r['file']];jar,entry=source.split('!/',1);r.update(new=new,source=source,evidence='all load sites target reviewed display method or display-only helper',review='usage_reviewed; translated wording still subject to context review')
        byjar.setdefault(jar,{}).setdefault(entry,{})[r['index']]=r;approved.append(r)
    for jar,classes in byjar.items():
        original=BASE/jar;stage=STAGE/jar;src=stage if stage.exists() else original
        with zipfile.ZipFile(original) as z0,zipfile.ZipFile(src) as z:
            updates={}
            for entry,edits in classes.items():
                b=z0.read(entry);new=rewrite(b,edits);updates[entry]=new
                for r in edits.values():r.update(jar_sha256=digest(original.read_bytes()),class_sha256=digest(b),new_class_sha256=digest(new))
                parsed=OUT/'class_review'/('translated_'+entry.split('/')[-1]);parsed.write_bytes(new)
                p=subprocess.run(['javap','-p',str(parsed.resolve())],capture_output=True)
                assert p.returncode==0,(entry,p.stderr)
            temp=stage.with_suffix('.tmp');temp.parent.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as w:
                for i in z.infolist():
                    if re.fullmatch(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)',i.filename,re.I):continue
                    w.writestr(i,updates.get(i.filename,z.read(i.filename)))
        temp.replace(stage)
    (OUT/'class_changes.json').write_text(json.dumps(approved,ensure_ascii=True,indent=2),encoding='utf-8')
    (OUT/'class_pending.json').write_text(json.dumps(pending,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps(dict(constants=len(approved),unique_texts=len(set(r['old'] for r in approved)),classes=sum(map(len,byjar.values())),jars=len(byjar),pending=len(pending))))
