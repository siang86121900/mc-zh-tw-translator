"""Local, deterministic profile artwork; retain authors' and players' existing images."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import time
from pathlib import Path

from .deployment import apply_reviewed, contained, file_hash

FILE = 'MCTranslator-cover.png'
MAX_BYTES = 8*1024*1024


def valid(raw: bytes) -> bool:
    from PIL import Image
    if not raw or len(raw)>MAX_BYTES:return False
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or not 16<=image.width<=4096 or not 16<=image.height<=4096:return False
            image.verify()
        return True
    except (OSError,ValueError,Image.DecompressionBombError):return False


def original(instance: Path, record: dict) -> bytes | None:
    """Only the image explicitly selected in this profile; never search personal folders."""
    value=record.get('profileImagePath')
    if not isinstance(value,str) or not value or '://' in value:return None
    path=Path(value)
    if not path.is_absolute():path=instance/path
    try:
        if path.is_symlink() or path.stat().st_size>MAX_BYTES:return None
        raw=path.read_bytes()
        return raw if valid(raw) else None
    except OSError:return None


def generate(name: str) -> bytes:
    """Render vector-like landscape and title locally, without an AI account or network."""
    from PIL import Image, ImageDraw, ImageFont
    name=' '.join(str(name).split())[:180] or 'Minecraft'
    digest=hashlib.sha256(name.casefold().encode()).digest()
    palettes=[((17,36,52),(64,198,198)),((32,24,53),(176,130,244)),((38,30,23),(246,178,87)),((19,38,32),(122,210,152))]
    bg,accent=palettes[digest[0]%len(palettes)]
    image=Image.new('RGB',(640,640),bg);draw=ImageDraw.Draw(image)
    for y in range(640):
        mix=y/640
        draw.line((0,y,639,y),fill=tuple(int(c*(1-mix*.35)) for c in bg))
    draw.ellipse((365,62,527,224),fill=accent)
    for layer,y in enumerate((238,298,356)):
        color=tuple(int(c*(.32+layer*.12)) for c in accent)
        points=[(0,430),(0,y+45)]
        for x in range(0,681,80):points.extend([(x,y+digest[(x//80+layer)%32]%85),(x+40,y+digest[(x//80+layer)%32]%85)])
        points.append((640,430));draw.polygon(points,fill=color)
    draw.rectangle((36,36,43,138),fill=accent)
    def font(size):
        for path in ('C:/Windows/Fonts/msjhbd.ttc','C:/Windows/Fonts/segoeuib.ttf','DejaVuSans-Bold.ttf'):
            try:return ImageFont.truetype(path,size)
            except OSError:pass
        return ImageFont.load_default(size=size)
    def lines_for(f):
        lines=['']
        for word in name.split():
            if draw.textlength((lines[-1]+' '+word).strip(),font=f)<=548:lines[-1]=(lines[-1]+' '+word).strip()
            else:
                if lines[-1]:lines.append('')
                for char in word:
                    if draw.textlength(lines[-1]+char,font=f)>548:lines.append('')
                    lines[-1]+=char
        return [line for line in lines if line]
    for size in range(52,11,-2):
        f=font(size);lines=lines_for(f)
        if len(lines)*(size+10)<=174:break
    for i,line in enumerate(lines[:5]):draw.text((44,430+i*(size+10)),line,font=f,fill=(246,248,250))
    draw.rectangle((44,611,130,616),fill=accent)
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


def image_for(instance: Path, record: dict, name: str) -> bytes:
    return original(instance,record) or generate(name)


def existing(instance: Path, home: Path, notify=lambda *_:None, cancelled=lambda:False, listing=None, running=None, pause=time.sleep) -> dict:
    """Fill only missing custom artwork, while CurseForge is closed; changes remain restorable."""
    from . import desktop_jobs as jobs, full_pack
    instance=Path(instance).resolve();profile=contained(instance,'minecraftinstance.json')
    if not profile.is_file():return dict(line='此啟動器沒有 CurseForge 設定檔，未變更封面。')
    record=json.loads(profile.read_text(encoding='utf-8-sig'))
    # Official projects already obtain artwork from CurseForge. Any explicit player image wins.
    if record.get('profileImagePath') or record.get('projectID') or record.get('installedModpack'):
        return dict(line='已保留原作者或你自行設定的封面。')
    if not record.get('guid') or Path(str(record.get('installPath') or '')).resolve()!=instance:
        return dict(line='設定檔位置無法核對，未變更封面。')
    running=running or full_pack.curseforge_running
    start=time.monotonic()
    while running():
        if cancelled() or time.monotonic()-start>3600:return dict(line='整合包內容已處理；封面尚未更新，請關閉 CurseForge 後重新安裝翻譯或更新整合包。')
        notify(96,'請關閉 CurseForge','整合包內容已處理；關閉 CurseForge（包含右下角小圖示）後會自動加入封面。')
        pause(3)
    before=profile.read_bytes();record=json.loads(before.decode('utf-8-sig'))
    if record.get('profileImagePath') or record.get('projectID') or record.get('installedModpack'):return dict(line='已保留原作者或你自行設定的封面。')
    if Path(str(record.get('installPath') or '')).resolve()!=instance:
        raise ValueError('CurseForge 設定檔位置已變動，封面尚未更新。')
    listing=Path(listing or full_pack.curseforge_list());cache=None
    if listing.is_file():
        data=json.loads(listing.read_text(encoding='utf-8-sig'))
        if not isinstance(data,list):raise ValueError('CurseForge 清單格式看不懂，封面尚未更新。')
        found=[r for r in data if isinstance(r,dict) and r.get('guid')==record['guid']]
        if len(found)!=1 or Path(str(found[0].get('installPath') or '')).resolve()!=instance:raise ValueError('CurseForge 清單無法唯一核對這個整合包，封面尚未更新。')
        if found[0].get('profileImagePath'):return dict(line='已保留你自行設定的封面。')
        cache=(data,found[0],file_hash(listing))
    (Path(home)/'tmp').mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=Path(home)/'tmp') as tmp:
        staged=Path(tmp);target=contained(instance,FILE)
        raw=target.read_bytes() if target.is_file() and target.stat().st_size<=MAX_BYTES else b''
        if not valid(raw):raw=generate(record.get('name') or instance.name)
        (staged/FILE).write_bytes(raw);record['profileImagePath']=str(target)
        (staged/profile.name).write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
        rows=[dict(file=n,before=file_hash(contained(instance,n)),after=file_hash(staged/n),reviewed=True,verified=True) for n in (FILE,profile.name)]
        jobs.ensure_game_closed(instance)
        if running() or profile.read_bytes()!=before:raise ValueError('CurseForge 設定已變動，封面尚未更新，請關閉後再試。')
        backup=apply_reviewed(instance,staged,rows,Path(home)/'output')
        try:
            if cache:
                if running():raise ValueError('CurseForge 已重新開啟，封面設定已復原；請關閉後再試。')
                data,selected,old_hash=cache;selected['profileImagePath']=str(target)
                (staged/listing.name).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
                apply_reviewed(listing.parent,staged,[dict(file=listing.name,before=old_hash,after=file_hash(staged/listing.name),reviewed=True,verified=True)],Path(home)/'output')
        except Exception:
            jobs.restore_backup(backup,instance);raise
    return dict(line='已自動加入專屬封面，重新開啟 CurseForge 即可查看；原設定已備份。',backup=str(backup))


def finish(*args,**kwargs):
    from .desktop_jobs import explain_error
    try:return existing(*args,**kwargs)
    except (OSError,ValueError,RuntimeError) as exc:
        return dict(line='整合包內容已處理，但封面尚未完成。'+explain_error(exc),error=True)
