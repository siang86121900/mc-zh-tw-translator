"""Rebuild review candidates from immutable instance inputs; never install them."""
import argparse
import collections
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

from full_translation_audit import parse, placeholders
from mc_zh_tw_translator.translator import MINECRAFT_GLOSSARY, is_jar_signature_file
from opencc import OpenCC

CC = OpenCC('s2twp')
LANG = re.compile(r'^(.*?/lang/)(en_us|zh_cn|zh_tw)\.(json|lang)$', re.I)
HAN = re.compile('[\u3400-\u9fff]')
FIXES = {
    ('constructionwand', 'constructionwand.networking.wand_undo.failed', 'Failed to undo wand action'): '無法復原建築魔杖的操作',
    ('rarcompat', 'tooltip.relics.feral_claws.ability.claws.description', "Increases the player's attack speed by %1$s%% for each consecutive attack performed within 3 seconds of the last. Otherwise, loses 1 charge per second. Attacking with an unfilled attack speed bar resets the accumulated charges."): '每次在上次攻擊後 3 秒內連續攻擊，都會使玩家的攻擊速度提高 %1$s%%。否則，每秒失去 1 層充能。在攻擊冷卻條尚未蓄滿時攻擊，會重設累積的充能。',
    ('xaeroworldmap', 'gui.xaero_wm_ceiling', '%1$s Ceiling'): '%1$s 天花板',
}

def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2), encoding='utf-8')
def usable(en, v):
    return isinstance(v, str) and bool(HAN.search(v)) and '\ufffd' not in v and (not en or placeholders(en) == placeholders(v))
def read_lang(b, suffix):
    if suffix == 'json': return parse(b)
    return dict(line.split('=', 1) for line in b.decode('utf-8-sig').splitlines() if '=' in line and not line.lstrip().startswith('#'))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('instance', type=Path)
    ap.add_argument('destination', type=Path)
    a = ap.parse_args()
    base = Path(__file__).resolve().parents[1]
    out = a.destination.resolve()
    if out.exists(): raise RuntimeError('Use a fresh destination to preserve previous evidence')
    snapshot = base/'input'/'Tensura Neo Otherworld'/'source_20260928'
    if not snapshot.exists():
        snapshot.mkdir(parents=True)
        for name in ('mods', 'kubejs', 'config', 'defaultconfigs', 'resourcepacks', 'datapacks', 'scripts', 'patchouli_books'):
            if (a.instance/name).exists(): shutil.copytree(a.instance/name, snapshot/name)
    manifest = {p.relative_to(snapshot).as_posix(): sha(p.read_bytes()) for p in snapshot.rglob('*') if p.is_file()}
    for n,h in manifest.items():
        if sha((a.instance/n).read_bytes()) != h: raise RuntimeError('Instance changed since snapshot: '+n)
    out.mkdir(parents=True)
    dump(out/'source_hashes.json', manifest)
    refs = [json.loads((base/'data'/n).read_text(encoding='utf-8')) for n in ('ref_pack_scoped.json','cfpa_scoped.json')]
    dump(out/'reference_versions.json', {n: json.loads((base/'data'/n).read_text(encoding='utf-8')) for n in ('ref_pack_version.json','cfpa_asset_metadata.json')})
    rows, errors, changes = [], [], []
    # Only automatically loaded KubeJS assets are eligible as cross-file sources.
    instance_cn = {}
    for p in (snapshot/'kubejs'/'assets').glob('*/lang/zh_cn.json'):
        try: instance_cn[p.parent.parent.name] = (p.relative_to(snapshot).as_posix(), parse(p.read_bytes()))
        except Exception as e: errors.append([str(p), str(e)])
    openloader_cn = {}
    for p in (snapshot/'config'/'openloader').rglob('*.zip'):
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                m = re.fullmatch(r'assets/([^/]+)/lang/zh_cn.json',n)
                if m:
                    try: openloader_cn[m[1]]=(p.relative_to(snapshot).as_posix()+'!/'+n,parse(z.read(n)))
                    except Exception as e: errors.append([str(p),n,str(e)])

    def collection(label, names, read):
        generated = {}
        groups = {}
        for n in sorted(names):
            m = LANG.match(n)
            if m: groups.setdefault((m[1],m[3]), {})[m[2].lower()] = n
        for (prefix, suffix), paths in groups.items():
            langs = {}
            for lang,n in paths.items():
                try: langs[lang] = read_lang(read(n), suffix) if read(n).strip() else {}
                except Exception as e: errors.append([label+'!/'+n,str(e)])
            en, cn, tw = (langs.get(x,{}) for x in ('en_us','zh_cn','zh_tw'))
            ns_match = re.search(r'(?:^|/)assets/([^/]+)/lang/$', prefix)
            ns = ns_match[1] if ns_match else ''
            result = dict(tw)
            for key in sorted(en.keys() | cn.keys() | tw.keys()):
                original = en.get(key, cn.get(key, tw.get(key)))
                if not isinstance(original, str):
                    result[key] = original
                    continue
                old = tw.get(key)
                options = [('existing_zh_tw', old, paths.get('zh_tw')),
                           ('same_source_zh_cn', cn.get(key), paths.get('zh_cn'))]
                ip, idata = instance_cn.get(ns, ('',{}))
                if ns and label != 'instance': options.append(('instance_zh_cn', idata.get(key),ip))
                op,odata = openloader_cn.get(ns,('',{}))
                if ns: options.append(('instance_zh_cn',odata.get(key),op))
                options += [('reference_pack_or_cfpa', ref.get(ns,{}).get(key), refname) for ref,refname in zip(refs,('ref_pack_scoped.json','cfpa_scoped.json'))] if ns else []
                options.append(('glossary', MINECRAFT_GLOSSARY.get(original.lower()),'MINECRAFT_GLOSSARY'))
                value, source, evidence = original, 'untranslated', None
                for typ,candidate,ev in options:
                    if usable(en.get(key), candidate):
                        value = CC.convert(candidate) if typ in ('same_source_zh_cn','instance_zh_cn') else candidate
                        if usable(en.get(key), value): source,evidence = typ,ev; break
                correction = FIXES.get((ns,key,en.get(key)))
                if correction:
                    value, source, evidence = correction, 'manual', 'Exact namespace/key/English reviewed against original'
                result[key] = value
                row = dict(file=label+'!/'+prefix+'zh_tw.'+suffix,key=key,namespace=ns,en=en.get(key),zh_cn=cn.get(key),before=old,after=value,source=source,evidence=evidence,reviewed=source=='manual',changed=value!=old)
                row['fingerprint'] = sha(json.dumps(row, ensure_ascii=False, sort_keys=True).encode())
                rows.append(row)
            target=prefix+'zh_tw.'+suffix
            if result != tw or 'zh_tw' not in paths:
                generated[target] = (json.dumps(result,ensure_ascii=False,indent=2) if suffix=='json' else '\n'.join(k+'='+str(v) for k,v in result.items())+'\n').encode('utf-8')
        # Create book language paths without translating IDs or non-display fields.
        # Keep existing translations; absent resources remain explicit untranslated candidates.
        for n in sorted(names):
            if not re.search(r'/(?:patchouli_books|book|books)/', '/'+n, re.I): continue
            if '/en_us/' not in n.lower() or not n.lower().endswith(('.json','.txt')): continue
            target=re.sub('/en_us/','/zh_tw/',n,flags=re.I)
            if target not in names:
                generated[target]=read(n)
                rows.append(dict(file=label+'!/'+target,source='untranslated_book',changed=True,reviewed=False,evidence=n))
        return generated

    archives = sorted(p for p in snapshot.rglob('*') if p.suffix.lower() in ('.jar','.zip'))
    for i,p in enumerate(archives,1):
        rel=p.relative_to(snapshot)
        with zipfile.ZipFile(p) as z:
            names=z.namelist()
            duplicates = {n for n,c in collections.Counter(names).items() if c>1}
            for n in duplicates:
                if len({sha(z.read(info)) for info in z.infolist() if info.filename==n})!=1:
                    raise RuntimeError('Conflicting duplicate ZIP entry: '+str(rel)+'!/'+n)
            updates=collection(rel.as_posix(),set(names),z.read)
            dst=out/'candidate'/rel
            dst.parent.mkdir(parents=True,exist_ok=True)
            if not updates and not duplicates: shutil.copy2(p,dst)
            else:
                with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as w:
                    seen=set()
                    for info in z.infolist():
                        if info.filename not in seen and info.filename not in updates and not is_jar_signature_file(info.filename): w.writestr(info,z.read(info))
                        seen.add(info.filename)
                    for n,b in updates.items(): w.writestr(n,b)
                changes.append(dict(file=rel.as_posix(),before=manifest[rel.as_posix()],after=sha(dst.read_bytes()),resources=sorted(updates)))
        if i%50==0: print('Archives',i,'/',len(archives),flush=True)
    loose={p.relative_to(snapshot).as_posix():p for p in snapshot.rglob('*') if p.is_file() and p.suffix.lower() not in ('.jar','.zip')}
    updates=collection('instance',set(loose),lambda n:loose[n].read_bytes())
    for n,p in loose.items():
        dst=out/'candidate'/n; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dst)
    for n,b in updates.items():
        dst=out/'candidate'/n; dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(b)
        changes.append(dict(file=n,before=manifest.get(n),after=sha(b)))
    with (out/'provenance.jsonl').open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    counts=collections.Counter(r['source'] for r in rows)
    for key in ('same_source_zh_cn','instance_zh_cn','translation_memory','reference_pack_or_cfpa','glossary','api','manual'): counts.setdefault(key,0)
    summary=dict(source_counts=counts,changed_strings=sum(r.get('changed',False) for r in rows),changed_files=len(changes),errors=errors,installed=False,complete=False,limitations=['Automatic source matches require content review','Non-language config, quests, scripts and class candidates remain pending','Book fallbacks preserve English where no reviewed translation exists'])
    dump(out/'changes.json',changes); dump(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
