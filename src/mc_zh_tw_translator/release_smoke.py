"""Exercise packaged cover imports and cloud installation using synthetic, isolated files."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

from . import covers, full_pack


def check_cover_install(destination: Path) -> dict:
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=True)
    artwork=covers.generate('封面測試 Cover Check')
    if not covers.valid(artwork):raise RuntimeError('封面產生或讀回驗證失敗。')
    image=root/'cover.png';image.write_bytes(artwork)
    if covers.image_for(root,dict(profileImagePath=str(image)),'Other')!=artwork:
        raise RuntimeError('自訂封面讀取失敗。')
    # A legacy cloud archive has no cover: this is the path that failed in v0.38.0.
    jar=io.BytesIO()
    with zipfile.ZipFile(jar,'w') as z:z.writestr('check.txt','synthetic packaging check')
    payload={'mods/check.jar':jar.getvalue(),'options.txt':b'lang:zh_tw\n'}
    manifest=dict(format=full_pack.FORMAT,name='封面測試 Cover Check',gameVersion='1.20.1',loader=dict(name='forge-47.4.10'),
                  files=[dict(path=name,size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),source='zip') for name,raw in payload.items()])
    package=root/'legacy-cloud.zip'
    with zipfile.ZipFile(package,'w') as z:
        for name,raw in payload.items():z.writestr(full_pack.PAYLOAD+name,raw)
        z.writestr(full_pack.MANIFEST,json.dumps(manifest,ensure_ascii=False))
    instances=root/'Instances';instances.mkdir(exist_ok=True)
    listing=root/'MinecraftGameInstance.json'
    other=dict(guid='01234567-89ab-cdef-0123-456789abcdef',installPath=str(instances/'Keep'),name='Keep')
    listing.write_text(json.dumps([other]),encoding='utf-8')
    result=full_pack.install(package,root/'installer-data',listing=listing,running=lambda:False)
    folder=Path(result['folder']);record=json.loads((folder/'minecraftinstance.json').read_bytes())
    if not folder.is_relative_to(instances) or record['profileImagePath']!=str(folder/covers.FILE):
        raise RuntimeError('隔離安裝的封面位置不符。')
    if (folder/covers.FILE).read_bytes()!=artwork or not covers.valid((folder/covers.FILE).read_bytes()):
        raise RuntimeError('隔離安裝未成功產生封面。')
    cache=json.loads(listing.read_bytes())
    if cache!=[other,record]:raise RuntimeError('隔離設定檔的封面登記不符。')
    return dict(cover_generated=True,cover_readback=True,custom_cover_read=True,legacy_cloud_cover_install=True)
