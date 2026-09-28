import json, hashlib, io, zipfile, re
from pathlib import Path
import requests
from opencc import OpenCC

root = Path(__file__).resolve().parents[1] / 'data'
cc = OpenCC('s2twp')
def get(url):
    r = requests.get(url, timeout=180); r.raise_for_status(); return r
def save(name, obj):
    (root/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
commit = get('https://api.github.com/repos/TeamKugimiya/ModsTranslationPack/commits/main').json()
sha = commit['sha']
print('Reference commit', sha, flush=True)
raw = get(f'https://codeload.github.com/TeamKugimiya/ModsTranslationPack/zip/{sha}').content
def build(raw, lang, convert=False):
    flat, scoped = {}, {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in sorted(z.namelist()):
            m = re.search(r'assets/([^/]+)/lang/'+lang+r'\.json$', name, re.I)
            namespace = m[1] if m else None
            if not m and lang == 'zh_tw':
                t = re.match(r'(.*/Translation/[^/]+)/([^/]+)/zh_tw.json$', name)
                if t:
                    try:
                        meta = json.loads(z.read(t[1]+'/metadata.json'))
                        namespace = meta.get('contents',{}).get('tiers',{}).get(t[2],{}).get('mod_id',meta.get('mod_id'))
                    except Exception: pass
            if not namespace: continue
            try: data = json.loads(z.read(name).decode('utf-8-sig'))
            except Exception: continue
            ns = scoped.setdefault(namespace, {})
            for k,v in data.items():
                if isinstance(v,str): ns[k] = cc.convert(v) if convert else v
            flat.update(ns)
    return flat, scoped
flat, scoped = build(raw, 'zh_tw')
assert flat
save('ref_pack.json', flat); save('ref_pack_scoped.json', scoped)
save('ref_pack_version.json', {'commit':sha,'commit_date':commit['commit']['committer']['date'],'entries':len(flat),'scoped_entries':sum(map(len,scoped.values()))})
release = get('https://api.github.com/repos/CFPAOrg/Minecraft-Mod-Language-Package/releases/tags/autobuild').json()
asset = next(a for a in release['assets'] if a['name']=='Minecraft-Mod-Language-Modpack-1-20.zip')
raw = get(asset['browser_download_url']).content
flat, scoped = build(raw, 'zh_cn', True)
assert flat
(root/'cfpa_zh_cn.zip').write_bytes(raw)
save('cfpa_cache.json',flat); save('cfpa_scoped.json',scoped)
save('cfpa_asset_metadata.json',{'asset':asset['name'],'asset_updated_at':asset['updated_at'],'sha256':hashlib.sha256(raw).hexdigest(),'entries':len(flat),'scoped_entries':sum(map(len,scoped.values()))})
print((root/'ref_pack_version.json').read_text(), (root/'cfpa_asset_metadata.json').read_text(), flush=True)
