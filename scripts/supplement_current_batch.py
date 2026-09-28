"""Fill untranslated display resources in the existing output, atomically per JAR."""
import json, re, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from mc_zh_tw_translator.translator import CTE2QuestTranslator, s2tw, is_jar_signature_file
from normalize_zh_tw import normalize_text

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/2026-09-09'
t=CTE2QuestTranslator(engine='none',max_workers=8)
t.cache_file=OUT/'supplement_cache.json'
t.translation_cache={}
if t.cache_file.exists(): t._load_cache()
report=[]
FIELDS={'name','text','title','landing_text','header','subtitle','description'}

def decode(b):
    return b.decode('utf-16' if b.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')

def parse(b):
    return json.loads(t._strip_json_comments(decode(b)))

def eligible(en,tw,key=''):
    if not isinstance(en,str) or not re.search('[A-Za-z]{3}',en): return False
    if isinstance(tw,str) and re.search('[\u3400-\u9fff]',tw) and tw!=en: return False
    if re.search(r'^(itemGroup[.:]|creativetab[.:])',key,re.I): return False
    if re.fullmatch(r'(?:[A-Z0-9_ +/.-]+|https?://\S+|[\w.-]+:[\w/.-]+)',en): return False
    if re.fullmatch(r'[\w-]+(?:\.[\w-]+){2,}',en): return False
    return True

def translate(en,tw=None,cn=None,key=''):
    if not eligible(en,tw,key): return tw if tw is not None else en
    if isinstance(cn,str) and re.search('[\u3400-\u9fff]',cn): return normalize_text(s2tw(cn))
    ref=t.ref_db.lookup(key) if key else None
    if isinstance(ref,str) and re.search('[\u3400-\u9fff]',ref): return normalize_text(ref)
    clean,fmt=t.clean_for_translation(en)
    value=t.translate_text(clean)
    # Never publish API results that lose protected formatting or parameters.
    if any(value.count(tok)!=clean.count(tok) for tok,_ in fmt.get('tokens',[])):
        report.append({'kind':'format_retry','key':key,'en':en})
        return tw if tw is not None else en
    return normalize_text(t.restore_formatting(value,en,fmt))

def merge(en,tw,cn,field=''):
    if isinstance(en,dict):
        result=dict(tw) if isinstance(tw,dict) else dict(en)
        for k,v in en.items(): result[k]=merge(v,tw.get(k) if isinstance(tw,dict) else None,cn.get(k) if isinstance(cn,dict) else None,k)
        return result
    if isinstance(en,list): return [merge(v,tw[i] if isinstance(tw,list) and i<len(tw) else None,cn[i] if isinstance(cn,list) and i<len(cn) else None,field) for i,v in enumerate(en)]
    if field in FIELDS: return translate(en,tw,cn)
    return tw if tw is not None else en

def resources(content,label):
    changes={}
    for name in list(content):
        if not re.search(r'/lang/en_us\.json$',name,re.I): continue
        ns=name.split('/lang/')[0].split('/')[-1]; t.ref_db.set_namespace(ns)
        target=re.sub('en_us.json$','zh_tw.json',name,flags=re.I)
        cnpath=re.sub('en_us.json$','zh_cn.json',name,flags=re.I)
        try:
            en=parse(content[name]); tw=parse(content[target]) if target in content else {}; cn=parse(content[cnpath]) if cnpath in content else {}
            todo=[(k,v) for k,v in en.items() if eligible(v,tw.get(k),k)]
            print(label,ns,'pending',len(todo),flush=True)
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(lambda kv:(kv[0],translate(kv[1],tw.get(kv[0]),cn.get(kv[0]),kv[0])),todo))
            new=dict(tw); new.update(results)
            if new!=tw: changes[target]=json.dumps(new,ensure_ascii=False,indent=2).encode()
        except Exception as e: report.append({'file':label+':'+name,'error':str(e)})
    t.ref_db.set_namespace('')
    for name in list(content):
        is_book=bool(re.search(r'/(patchouli_books|book|books)/',name))
        home=is_book and name.endswith('/book.json') and not re.search(r'/(en_us|zh_tw|zh_cn)/',name)
        if not is_book or not ('/en_us/' in name or home): continue
        if not name.endswith(('.json','.txt')): continue
        target=name.replace('/en_us/','/zh_tw/'); cnpath=name.replace('/en_us/','/zh_cn/')
        try:
            if name.endswith('.json'):
                en=parse(content[name]); tw=parse(content[target]) if target in content and not home else {}; cn=parse(content[cnpath]) if cnpath in content and not home else {}
                new=merge(en,tw,cn)
                if new!=tw: changes[target]=json.dumps(new,ensure_ascii=False,indent=2).encode()
            else:
                en=decode(content[name]); tw=decode(content[target]) if target in content else None; cn=decode(content[cnpath]) if cnpath in content else None
                new=translate(en,tw,cn)
                if new!=tw: changes[target]=new.encode()
        except Exception as e: report.append({'file':label+':'+name,'error':str(e)})
    return changes

completed_path=OUT/'supplement_completed.json'
completed=set(json.loads(completed_path.read_text()) if completed_path.exists() else [])
for i,p in enumerate(sorted((OUT/'mods').glob('*.jar')),1):
    if p.name in completed: continue
    print('JAR',i,425,p.name,flush=True)
    with zipfile.ZipFile(p) as z:
        selected={n:z.read(n) for n in z.namelist() if ('/lang/' in n or re.search(r'/(patchouli_books|book|books)/',n)) and n.endswith(('.json','.txt'))}
        changes=resources(selected,p.name)
        if changes:
            temp=p.with_suffix('.supplement.tmp')
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as w:
                for item in z.infolist():
                    if is_jar_signature_file(item.filename): continue
                    w.writestr(item,changes.pop(item.filename,z.read(item.filename)))
                for n,b in changes.items(): w.writestr(n,b)
    if 'temp' in locals() and temp.exists(): temp.replace(p)
    t._save_cache(); completed.add(p.name)
    completed_path.write_text(json.dumps(sorted(completed)),encoding='utf-8')
    (OUT/'supplement_issues.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

base=OUT/'kubejs'
content={p.relative_to(base).as_posix():p.read_bytes() for folder in ('assets','data') for p in (base/folder).rglob('*') if p.is_file() and p.suffix in ('.json','.txt')}
for name,b in resources(content,'kubejs').items():
    p=base/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b)
t._save_cache()
(OUT/'supplement_issues.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUPPLEMENT COMPLETE',flush=True)
