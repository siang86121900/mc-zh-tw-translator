import json, re, zipfile
from normalize_zh_tw import normalize_json
from pathlib import Path

INSTANCE=Path(r'C:/Users/User/curseforge/minecraft/Instances/VEFV2.7.1')
SIG=re.compile(r'^META-INF/[^/]+\.(SF|RSA|DSA|EC)$',re.I)

def rewrite(path, changes):
    with zipfile.ZipFile(path) as z:
        files={n:z.read(n) for n in z.namelist() if not SIG.match(n)}
        infos={n:z.getinfo(n) for n in z.namelist() if not SIG.match(n)}
    files.update(changes)
    tmp=path.with_suffix(path.suffix+'.translation.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as w:
        for n,b in files.items(): w.writestr(infos.get(n,n),b)
    tmp.replace(path)

# Simply Swords: use bundled Chinese Patchouli pages and add the missing home page.
p=INSTANCE/'mods/simplyswords-forge-1.56.0-1.20.1.jar'
with zipfile.ZipFile(p) as z:
    changes={}
    for n in z.namelist():
        if '/patchouli_books/runic_grimoire/zh_cn/' in n and n.endswith('.json'):
            changes[n.replace('/zh_cn/','/zh_tw/')]=normalize_json(z.read(n))
    book=next(n for n in z.namelist() if n.endswith('/patchouli_books/runic_grimoire/book.json'))
    root=json.loads(z.read(book).decode('utf-8-sig'))
root['name']='符文魔典'
root['landing_text']='武器製作、符文蝕刻與獨特武器指南。$(br2)$(br2)（本書內容由 OpenAI 的 ChatGPT 協助製作）'
changes[book]=json.dumps(root,ensure_ascii=False,indent=2).encode()
rewrite(p,changes)

# Vinery tooltip/subtitle strings visible in the screenshot.
p=INSTANCE/'mods/letsdo-vinery-forge-1.4.39.jar'
with zipfile.ZipFile(p) as z:
    name='assets/vinery/lang/zh_tw.json'; d=json.loads(z.read(name).decode('utf-8-sig'))
d.update({'subtitles.vinery.drawer_open':'抽屜：開啟','subtitles.vinery.drawer_close':'抽屜：關閉','subtitles.vinery.cabinet_open':'櫃子：開啟','subtitles.vinery.cabinet_close':'櫃子：關閉','tooltip.vinery.age':'年份：%s','tooltip.vinery.next_upgrade':'提升品質剩餘天數：%s'})
rewrite(p,{name:json.dumps(d,ensure_ascii=False,indent=2).encode()})

# Lender's Delight item name visible in the tooltip screenshot.
p=INSTANCE/'mods/lendersdelight-1.20.1-1.0.10.jar'
with zipfile.ZipFile(p) as z:
    name='assets/lendersdelight/lang/zh_tw.json'; d=json.loads(z.read(name).decode('utf-8-sig'))
d['item.lendersdelight.cursium_knife']='柯爾希姆小刀'
rewrite(p,{name:json.dumps(d,ensure_ascii=False,indent=2).encode()})
print('patched screenshot sources')
