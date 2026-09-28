"""Validate ELA staged display-only modifications and record genuine backups."""
import hashlib,json,re,shutil,sys,zipfile
from pathlib import Path
from full_translation_audit import parse,parse_binary_nbt
from mc_zh_tw_translator.verifier import verify_outputs
from ela_stage_classes import rewrite

BASE=Path('C:/Users/User/curseforge/minecraft/Instances/ELA')
OUT=Path('output/ELA');STAGE=OUT/'staged';BACK=Path('input/ELA')
def sha(b):return hashlib.sha256(b).hexdigest()
def equal_nontext(a,b,path=()):
    assert type(a)==type(b),(path,'type')
    if isinstance(a,dict):
        assert a.keys()==b.keys(),(path,'keys')
        for k in a:equal_nontext(a[k],b[k],path+(k,))
    elif isinstance(a,list):
        assert len(a)==len(b),(path,'length')
        for i,(x,y) in enumerate(zip(a,b)):equal_nontext(x,y,path+(i,))
    elif a!=b:
        assert isinstance(a,str),(path,'non-string changed')
        assert any(k in {'text','title','subtitle','description','landing_text','displayName','customTooltips','Name','Lore','tooltip_list','name'} for k in path),(path,'non-display changed',a,b)

manifest=[];changed_jars=0;checks={}
class_rows=json.loads((OUT/'class_changes.json').read_text()) if (OUT/'class_changes.json').exists() else []
class_edits={}
for r in class_rows:class_edits.setdefault(r['source'],{})[r['index']]=r
for p in sorted(STAGE.rglob('*')):
    if not p.is_file():continue
    rel=p.relative_to(STAGE);live=BASE/rel;old=live.read_bytes() if live.exists() else None;new=p.read_bytes()
    if old==new:continue
    if p.suffix=='.jar':
        assert old is not None
        with zipfile.ZipFile(live) as a,zipfile.ZipFile(p) as b:
            an=set(a.namelist());bn=set(b.namelist());assert len(bn)==len(b.namelist())
            for n in an-bn:assert re.fullmatch(r'META-INF/[^/]+\.(SF|RSA|DSA|EC)',n,re.I),n
            for n in bn:
                if n in an and a.read(n)==b.read(n):continue
                if n.endswith('.class'):
                    edits=class_edits.get(rel.as_posix()+'!/'+n)
                    assert edits and rewrite(a.read(n),edits)==b.read(n),(rel,n,'unapproved class edit')
                    continue
                assert '/lang/zh_tw.json' in n or '/zh_tw/' in n or n.endswith('/book.json'),(rel,n)
                if n.endswith('.json'):json.loads(b.read(n).decode('utf-8-sig'))
                if n in an and '/lang/' not in n:equal_nontext(parse(a.read(n)),parse(b.read(n)))
        changed_jars+=1
    elif p.suffix=='.data':equal_nontext(parse_binary_nbt(old),parse_binary_nbt(new))
    elif p.suffix=='.json':
        json.loads(new.decode('utf-8-sig'))
        if old is not None and '/lang/' not in rel.as_posix():
            if rel.as_posix()=='vaultpatcher/modules/spellbladenext-2.4.0+1.20.1.json':
                a=parse(old);b=parse(new)
                for x,y in zip(a,b):
                    for xp,yp in zip(x.get('pairs',[]),y.get('pairs',[])):
                        assert xp['key']==yp['key'];xp['value']=yp['value']
                assert a==b
            else:equal_nontext(parse(old),parse(new))
    elif p.suffix in ('.js','.snbt'):
        pattern=r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27|`(?:\\.|[^`\\])*`'
        a=old.decode('utf-8-sig');b=new.decode('utf-8-sig')
        assert re.sub(pattern,'STR',a)==re.sub(pattern,'STR',b),('logic',rel)
        aa=re.findall(pattern,a);bb=re.findall(pattern,b);assert len(aa)==len(bb)
        for x,y in zip(aa,bb):
            if x==y:continue
            assert not x.startswith('//') and not x.startswith('/*'),('comment changed',rel)
            assert re.findall(r'\$\{[^}]+\}',x)==re.findall(r'\$\{[^}]+\}',y),('template logic',rel)
            assert re.findall(r'\b[a-z0-9_.-]+:[a-z0-9_/.-]+\b',x)==re.findall(r'\b[a-z0-9_.-]+:[a-z0-9_/.-]+\b',y),('ids',rel)
        if p.suffix=='.snbt':
            for field in ('StructureName','id','command','icon','type','filename'):
                pat=rf'\b{field}:\s*("(?:\\.|[^"\\])*")'
                assert re.findall(pat,a)==re.findall(pat,b),(field,rel)
    else:raise ValueError(('unexpected staged file',rel))
    backup=BACK/rel
    if old is not None:
        if backup.exists():assert sha(backup.read_bytes())==sha(old),('source changed',rel)
        else:backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(old)
    manifest.append(dict(path=rel.as_posix(),before_sha256=sha(old) if old is not None else None,after_sha256=sha(new),size=len(new)))

# Build the full 27-JAR result from true originals and verified staged changes.
for p in (BASE/'mods').glob('*.jar'):
    src=STAGE/'mods'/p.name
    shutil.copy2(src if src.exists() else BACK/'mods'/p.name,OUT/'mods'/p.name)
assert len(list((BASE/'mods').glob('*.jar')))==len(list((OUT/'mods').glob('*.jar')))
result=verify_outputs(OUT/'mods',BACK/'mods')
checks=dict(ok=result.ok,errors=result.errors,warnings=result.warnings,changed_jars=changed_jars,changed_files=len(manifest),validated='display fields, script structure, SNBT protected fields, NBT non-display values and numeric types; Java ZipFS and book coverage')
(OUT/'validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False));sys.exit(0 if result.ok else 1)
