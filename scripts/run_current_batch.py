import json, shutil, re, zipfile
from pathlib import Path
from mc_zh_tw_translator.translator import CTE2QuestTranslator, s2tw, is_jar_signature_file

root=Path(__file__).resolve().parents[1]
src=root/'input'; out=root/'output/2026-09-09'
out.mkdir(parents=True,exist_ok=True)
t=CTE2QuestTranslator(engine='none',max_workers=5)
t.translation_cache={}
t.cache_file=out/'translation_cache.json'
for folder in ('config','defaultconfigs','kubejs'):
    shutil.copytree(src/folder,out/folder,dirs_exist_ok=True)
t.translate_jar_folder(str(src/'mods'),str(out/'mods'))
# Include Chinese-only language resources, including translation addon JARs.
for jar in (out/'mods').glob('*.jar'):
    additions={}
    with zipfile.ZipFile(jar) as z:
        for n in z.namelist():
            if not re.search(r'/lang/zh_cn.json$',n,re.I): continue
            target=re.sub('zh_cn.json$','zh_tw.json',n,flags=re.I)
            if target in z.namelist(): continue
            data=json.loads(z.read(n).decode('utf-8-sig'))
            additions[target]=json.dumps({k:s2tw(v) if isinstance(v,str) else v for k,v in data.items()},ensure_ascii=False).encode()
        if additions:
            contents={n:z.read(n) for n in z.namelist() if not is_jar_signature_file(n)}
    if additions:
        with zipfile.ZipFile(jar,'w',zipfile.ZIP_DEFLATED) as z:
            for n,b in (contents|additions).items(): z.writestr(n,b)
for directory in sorted((out/'kubejs/assets').glob('*/lang')):
    def read(name):
        p=directory/name
        return json.loads(p.read_text(encoding='utf-8-sig')) if p.exists() else {}
    en,cn,tw=read('en_us.json'),read('zh_cn.json'),read('zh_tw.json')
    if not en and not cn: continue
    for k,v in cn.items():
        if isinstance(v,str) and (k not in tw or t.is_untranslated(en.get(k,''),tw[k])): tw[k]=s2tw(v)
    t.ref_db.set_namespace(directory.parent.name)
    if en: tw=t.translate_lang_data(en,tw)
    (directory/'zh_tw.json').write_text(json.dumps(tw,ensure_ascii=False,indent=2),encoding='utf-8')
for p in (out/'kubejs/assets').rglob('*.txt'):
    if 'zh_cn' in p.parts:
        target=Path(str(p).replace('\\zh_cn\\','\\zh_tw\\'))
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True); target.write_text(s2tw(p.read_text(encoding='utf-8-sig')),encoding='utf-8')
t.ref_db.set_namespace('')
quest=src/'config/ftbquests/quests'
if quest.exists(): t.translate_folder(str(quest),str(out/'config/ftbquests/quests'))
for p in (out/'config').rglob('zh_cn.*'):
    dst=p.with_name(p.name.replace('zh_cn.','zh_tw.'))
    if not dst.exists(): dst.write_text(s2tw(p.read_text(encoding='utf-8-sig')),encoding='utf-8')
t._save_cache()
print('BATCH COMPLETE',flush=True)
