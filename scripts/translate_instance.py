import argparse, json, re, shutil, zipfile
from pathlib import Path
from mc_zh_tw_translator.translator import CTE2QuestTranslator, s2tw, is_jar_signature_file

p=argparse.ArgumentParser(); p.add_argument('src'); p.add_argument('out'); a=p.parse_args()
src,out=Path(a.src),Path(a.out); out.mkdir(parents=True,exist_ok=True)
t=CTE2QuestTranslator(engine='none',max_workers=8); t.cache_file=out/'translation_cache.json'
for name in ('config','defaultconfigs','kubejs','resourcepacks','datapacks'):
    if (src/name).exists(): shutil.copytree(src/name,out/name,dirs_exist_ok=True)
if (src/'mods').exists() and not (out/'mods').exists():
    t.translate_jar_folder(str(src/'mods'),str(out/'mods'))
for directory in sorted((out/'kubejs/assets').glob('*/lang')) if (out/'kubejs/assets').exists() else []:
    def read(n):
        q=directory/n
        if not q.exists(): return {}
        return json.loads(CTE2QuestTranslator._strip_json_comments(q.read_text(encoding='utf-8-sig')))
    en,cn,tw=read('en_us.json'),read('zh_cn.json'),read('zh_tw.json')
    if not en and not cn: continue
    for k,v in cn.items():
        if isinstance(v,str) and (k not in tw or t.is_untranslated(en.get(k,''),tw[k])): tw[k]=s2tw(v)
    t.ref_db.set_namespace(directory.parent.name)
    if en: tw=t.translate_lang_data(en,tw)
    (directory/'zh_tw.json').write_text(json.dumps(tw,ensure_ascii=False,indent=2),encoding='utf-8')
for pth in (out/'kubejs').rglob('*.txt') if (out/'kubejs').exists() else []:
    if 'zh_cn' in pth.parts:
        dst=Path(str(pth).replace('\\zh_cn\\','\\zh_tw\\'))
        if not dst.exists(): dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text(s2tw(pth.read_text(encoding='utf-8-sig')),encoding='utf-8')
for pth in (out/'config').rglob('zh_cn.*') if (out/'config').exists() else []:
    dst=pth.with_name(pth.name.replace('zh_cn.','zh_tw.'))
    if not dst.exists(): dst.write_text(s2tw(pth.read_text(encoding='utf-8-sig')),encoding='utf-8')
t._save_cache(); print('INSTANCE TRANSLATION COMPLETE',flush=True)
