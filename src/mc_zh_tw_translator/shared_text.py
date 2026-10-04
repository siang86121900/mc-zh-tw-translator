"""Text recipes for patch format 3. Remote data never supplies a write route or a safety proof.

The receiver scans its own files and reuses the ordinary translation stager. Only words travel:
classes, NBT structures and data-pack tasks are reconstructed from the receiver's original files.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import desktop_jobs as jobs
from .deployment import contained, file_hash

FORMAT = 'mctranslator-patch-3'
MAX_UNITS = 200000
MAX_TEXT = 1024 * 1024
ROOTS = ('mods/', 'config/', 'defaultconfigs/', 'kubejs/', 'scripts/', 'resourcepacks/',
         'datapacks/', 'patchouli_books/', 'shaderpacks/', 'tacz/', 'tlm_custom_pack/')
KINDS = {'language', 'book', 'inline_lang', 'data_text', 'embedded_text', 'class_display'} | set(jobs.LOOSE_TEXT_KINDS)
SAVE_NOTE = 'NPC、建築告示牌與書本若已生成進舊存檔，原有文字可能仍是英文；本補丁不修改存檔、交易或任務進度。'


def source_file(source):
    return source.removeprefix('instance!/').split('!/', 1)[0]


def local_versions(instance, home):
    """Only receipts from locally proved recipes, still at their recorded result hash."""
    try:
        data=json.loads((Path(home)/'applied_patches.json').read_text(encoding='utf-8'))
        versions=data.get(str(Path(instance).resolve()).casefold(),{}).get('source_versions',{})
        return {file:pair for file,pair in versions.items() if isinstance(pair,dict)
            and all(re.fullmatch('[0-9a-f]{64}',str(pair.get(k))) for k in ('before','after'))
            and file_hash(contained(instance,file))==pair.get('after')}
    except (OSError,ValueError,TypeError,AttributeError):return {}


def validate(units, clean_path):
    if not isinstance(units, list) or len(units) > MAX_UNITS:
        raise ValueError('補丁的逐句翻譯清單超過上限或格式不正確。')
    seen = set()
    for u in units:
        if not isinstance(u, dict):raise ValueError('補丁的逐句翻譯格式不正確。')
        for field in ('source', 'key', 'kind', 'text', 'original', 'origin'):
            if not isinstance(u.get(field), str) or len(u[field]) > MAX_TEXT:
                raise ValueError('補丁的逐句翻譯欄位不正確：' + field)
        if u['kind'] not in KINDS:raise ValueError('補丁包含不支援的文字種類。')
        if any(u.get(f) is not None and not isinstance(u[f], str) for f in ('current', 'en')):
            raise ValueError('補丁的原文格式不正確。')
        parts=u['source'].removeprefix('instance!/').split('!/')
        for part in parts:clean_path(part)
        if not parts[0].casefold().startswith(ROOTS):raise ValueError('補丁的文字來源不允許寫入。')
        if any(p.casefold() in ('saves', 'backups', 'logs', 'crash-reports') for p in parts[0].split('/')):
            raise ValueError('補丁不允許修改存檔或備份。')
        required=u.get('requires')
        if not isinstance(required, dict) or set(required) != {parts[0]}:
            raise ValueError('補丁的逐句翻譯缺少原檔校驗。')
        for path, h in required.items():
            clean_path(path)
            if not re.fullmatch('[0-9a-f]{64}', str(h)):raise ValueError('補丁的原檔校驗格式不正確。')
        if not re.fullmatch('[0-9a-f]{64}', str(u.get('source_after'))):
            raise ValueError('補丁的結果校驗格式不正確。')
        key=(u['source'].casefold(), u['key'], u['kind'])
        if key in seen:raise ValueError('補丁含重複的文字位置。')
        seen.add(key)
        # A remote source label is information, never a locally confirmed memory.
        if not jobs.validate_text(u['original'],u['text']) or jobs.number_doubt(u['original'],u['text']):
            raise ValueError('補丁的逐句譯文格式或數值和原文不同：' + u['key'])


def applied_rows(instance, home):
    """Newest applied recipe per position, including earlier batches' unchanged translations."""
    found={}
    reports=Path(home)/'output'/Path(instance).name/'報告'
    for path in sorted(reports.glob('*/session.json')):
        try:
            session=json.loads(path.read_text(encoding='utf-8'))
            if Path(session['instance']).resolve()!=Path(instance).resolve() or session.get('status')!='installed':continue
            for row in session['rows']:
                if row.get('installed') and row.get('changed'):
                    key=(row['source'],row['key'],row['kind'])
                    earlier=found.get(key)
                    if earlier:row=dict(row,current=earlier[0].get('current'))
                    found[key]=(row,session.get('source_hashes') or {})
        except (OSError,ValueError,KeyError,TypeError):continue
    return found.values()


def collect(instance, home, files):
    """Only applied, read-back matching text with local proofs; no unverified conversions."""
    groups={};omitted=[];hash_cache={};curseforge=jobs.is_curseforge(instance)
    def omit(row,target,reason):
        title=jobs.book_title(row) if row['kind']=='book' else None
        resource=title[0] if title else jobs.pack_resource(jobs.target_for(row)[1])
        if row['kind']=='class_display' and row.get('tooltips'):resource=row['tooltips'][0][3]
        omitted.append(dict(file=target,reason=reason,resource=resource or '',source=row['source'],
            key=row['key'],original=jobs.original_of(row),text=row.get('proposed')))
    candidates=list(applied_rows(instance,home))
    jobs.check_shown(instance,[row for row,_ in candidates])
    for row, hashes in candidates:
        route=jobs.write_route(row,curseforge)
        target=jobs.RESOURCE_PACK_FILE if route=='pack' else jobs.data_pack_file(instance) if route=='datapack' else jobs.target_for(row)[0]
        if route not in jobs.WRITTEN_ROUTES or target not in files:continue
        if not row.get('supported') or row.get('unverified') or row.get('literal'):
            omit(row,target,'有用途未確認的原地轉換，不放進分享補丁');continue
        source=source_file(row['source']);path=contained(instance,source)
        original=jobs.original_of(row);text=row.get('proposed')
        if not isinstance(text,str) or not jobs.validate_text(original,text):
            omit(row,target,'已套用紀錄的譯文格式與原文不同');continue
        if jobs.number_doubt(original,text):
            omit(row,target,'已套用紀錄的譯文數值與原文不同');continue
        if not row.get('shown'):
            omit(row,target,'已套用紀錄的譯文與目前實際讀取的檔案不同');continue
        before=files.get(source,{}).get('before') or hashes.get(source)
        if not before or not path.is_file():
            omit(row,target,'已套用文字缺少可核對的原檔紀錄');continue
        if source not in hash_cache:hash_cache[source]=file_hash(path)
        groups.setdefault(target,[]).append(dict(source=row['source'],key=row['key'],kind=row['kind'],
            current=row.get('current'),en=row.get('en'),original=original,text=text,
            origin=row.get('origin') or 'shared_translation',requires={source:before},source_after=hash_cache[source]))
    return groups,omitted


def prepare(instance, home, units, notify, work, cancelled, pack_base=None):
    """Re-prove each position locally, then stage it without writing game files or using AI."""
    from .patches import edit_safe
    if not units:return dict(records=[],rows=[],already=[],skipped=[],staged=None)
    notify(5,'核對分享的文字用途','重新讀取原檔；不使用 AI，也不重新選擇譯文')
    session=jobs.plan(instance,home,notify,cancelled,
        references=([{},{}],{'mode':'shared_text','note':'安裝已翻好的文字，不重新查找翻譯來源'}))
    if session.get('status') in ('blocked','cancelled'):
        if cancelled():raise InterruptedError('已停止，分享的逐句翻譯尚未寫入。')
        raise ValueError('無法核對分享的文字用途，尚未寫入。'+str(session.get('errors') or ''))
    index={(r['source'],r['key'],r['kind']):r for r in session['rows']}
    for row in session['rows']:row['reviewed']=False
    accepted=[];already=[];skipped=[];hashes={};versions=local_versions(instance,home);curseforge=jobs.is_curseforge(instance)
    already_candidates=[]
    for u in units:
        if cancelled():raise InterruptedError('已停止，分享的逐句翻譯尚未寫入。')
        source=source_file(u['source']);path=contained(instance,source)
        if source not in hashes:hashes[source]=file_hash(path) if path.is_file() else None
        row=index.get((u['source'],u['key'],u['kind']))
        why=''
        original_match=hashes[source]==u['requires'][source] or versions.get(source,{}).get('before')==u['requires'][source]
        after_match=hashes[source]==u['source_after'] and row and row.get('current')==u['text']
        if hashes[source]==u['source_after'] and hashes[source]!=u['requires'][source] and (row or u['kind'] in ('class_display','embedded_text')):
            # The translator's translated file (the translator's own computer, or the patch installed before),
            # where a rescan may list no row for text already in Chinese. A claimed hash proves nothing by itself:
            # it counts only when the words read back from that place are the translation. On the translator's own
            # computer the backup record also matches the original (original_match), which must not send these
            # lines to the checks below (COBBLEVERSE 2026-10-04: 11 lines called "cannot be proven safe").
            candidate=dict(row or {},source=u['source'],key=u['key'],kind=u['kind'],proposed=u['text'])
            already_candidates.append((u,candidate));continue
        if not original_match and not after_match:why='原檔版本和分享者不同'
        elif not row or not row.get('supported') or row.get('unverified') or row.get('literal'):why='本機無法證明這個文字位置可安全改寫'
        elif jobs.write_route(row,curseforge) not in jobs.WRITTEN_ROUTES:why='本機啟動器或資料包載入方式不允許寫入'
        elif row['kind']=='class_display' and jobs.class_name(row) in session['mixin_targets']:why='其他模組的 Mixin 需要原程式文字'
        elif row.get('current')==u['text']:
            candidate=dict(row,proposed=u['text'])
            already_candidates.append((u,candidate));continue
        elif row.get('current')!=u['current'] or jobs.original_of(row)!=u['original'] or row.get('en')!=u['en']:
            why='原句或上下文和分享時不同'
        elif jobs.convertible(row) and not edit_safe('config/decoded.txt',row['current'],u['text']):
            why='設定或腳本的原地轉換只能改中文字'
        elif not jobs.row_fits(row,u['text']) or jobs.number_doubt(jobs.original_of(row),u['text']):why='譯文格式或數值與本機原文不同'
        if why:
            skipped.append(dict(file=u['source'],key=u['key'],reason=why));continue
        row.update(proposed=u['text'],origin='shared_translation' if u['origin'] in jobs.USER_ORIGINS else u['origin'],evidence='shared_patch',reviewed=True,
                   review_method='shared_patch',changed=True,installed=False)
        accepted.append(row)
    jobs.check_shown(instance,[row for _,row in already_candidates])
    for u,row in already_candidates:
        if row.get('shown'):already.append(u['source']+' / '+u['key'])
        else:skipped.append(dict(file=u['source'],key=u['key'],reason='譯文未在實際讀取的檔案中啟用'))
    result=dict(records=[],rows=accepted,already=already,skipped=skipped,staged=None,session=session)
    if accepted:
        staged=jobs.stage_and_apply(session,home,notify,work,stage_only=True,pack_base=pack_base)
        result.update(staged=staged['staged'],records=staged['records'],rows=staged['rows'])
        selected={id(r) for r in staged['rows']}
        result['skipped'] += [dict(file=r['source'],key=r['key'],reason='本機套用檢查拒絕此文字') for r in accepted if id(r) not in selected]
    return result


def copy_staged(result, staged, records):
    """Combine the prepared recipes with the legacy payload before one atomic deployment."""
    generated=result.get('staged')
    for record in result['records']:
        if record['file'] in ('options.txt', jobs.DEFAULT_OPTIONS_FILE):continue
        target=contained(staged,record['file']);target.parent.mkdir(parents=True,exist_ok=True)
        if record.get('after') is not None:shutil.copyfile(contained(generated,record['file']),target)
        records[:]=[r for r in records if r['file']!=record['file']]
        records.append(record)
