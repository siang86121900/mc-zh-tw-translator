"""FTB Backups 2 on published packs (使用者 2026-11-06 同意).

Only audited releases are installed. See docs/translation-reference.md for the
1.0.23 display-only concatenations; this is not a general class-string rewriter.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import struct
import time
import tomllib
import uuid
import zipfile
from pathlib import Path

from . import desktop_jobs as jobs
from .class_text import ClassFile, encode_mutf, check_java
from .deployment import apply_reviewed, file_hash
from .imblocker import jar_ids, numbers, pack_loader
from .sweeper import mod_jars
from .verifier import SIGNATURE_RE, VerifyResult, check_java_zipfs

MOD_ID = 'ftbbackups2'
NAME = 'FTB Backups 2'
PAGE = 'https://www.curseforge.com/minecraft/mc-mods/ftb-backups-2'
CONFIG = 'config/ftbbackups2.json'
MINIMUM_APP_VERSION = '0.42.0'
FILES = (
    ('forge', (1, 20), (1, 20, 1), 4834403, 'ftbbackups2-forge-1.20-1.0.23.jar', 1954591,
     '19cea280a56e533b9669d4f866aef38ebe54f6d8627efe6798016e17b6b4afda'),
)
KNOWN = {f[6]: f[5] for f in FILES}
# Filled from the official download after deterministic, local display-string rewriting.
LOCALIZED_SHA = 'd4b225fb7df23bac7c73698a03acebaa76abb18be063a39c28329e3f91037be8'
LANG = 'assets/ftbbackups/lang/zh_tw.json'
LANG_TEXT = {
    'ftbbackups2.backup.starting': '開始備份世界。',
    'ftbbackups2.backup.failed': '世界備份失敗，請查看伺服器紀錄。',
    'ftbbackups2.backup.finished': '世界備份完成。',
}
# Same values as the approved server, plus the approved 10 GB floor. MB here is
# decimal (the mod multiplies minimum_free_space by 1,000,000).
CONFIG_VALUES = dict(enabled=True, command_permission_level=3, notify_op_only=False,
    do_not_notify=False, retention_mode='MAX_BACKUPS', max_backups=5, keep_latest=5,
    keep_hourly=1, keep_daily=1, keep_weekly=1, keep_monthly=1,
    backup_cron='0 */30 * * * ?', manual_backups_time=0,
    only_if_players_been_online=True, additional_directories=[], additional_files=[],
    display_file_size=False, backup_location='.', backup_format='ZIP',
    minimum_free_space=10000, free_space_if_needed=False, excluded=[],
    preview_dimension='minecraft:overworld')
CONFIG_TEXT = ('// 自動備份：每 30 分鐘、保留最新 5 份；沒人遊玩時略過。\n'
               '// 備份後至少保留 10 GB；空間不足時不額外刪除舊備份。\n'
               + json.dumps(CONFIG_VALUES, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
BACKUP_WORDS = re.compile(r'backup|back.?up|備份|备份', re.I)

# Exact class hashes bind the manually inspected bytecode, including all users
# of each constant. No code, indices, bootstrap arguments or identifiers change.
CLASS_EDITS = {
 'net/creeperhost/ftbbackups/BackupHandler.class': (
  '08296e4d71fa3e3aa1bce041067b84f048eb49e33718f21100f864bde96e39af', {
   'Unable to create backup, Reason: \x01': '無法建立備份，原因：\x01',
   'Invalid world folder': '世界資料夾無效',
   'backup folder path is null': '尚未設定備份資料夾路徑',
   'backup folder does not exist': '備份資料夾不存在',
   'Unable to start new backup as backup is already running': '目前正在備份，無法同時開始另一份備份',
   'Manuel backup was recently taken': '剛剛已經手動備份，請稍後再試',
   'backup thread is somehow still running': '上一個備份工作尚未結束',
   'not enough free space on device': '硬碟可用空間不足',
   ' Size: \x01': '，大小：\x01',
   'Backup finished in \x01\x01': '世界備份完成，耗時 \x01\x01',
  }),
 'net/creeperhost/ftbbackups/commands/BackupCommand.class': (
  'd1116fcb529fccf6dd88b944473e35fa51fd9c86af35fc4a771019ddf754d109', {
   'Unable to create backup, Last backup was taken less than \x01 Minutes ago':
       '無法建立備份，距離上次備份還不到 \x01 分鐘',
  }),
}


def mod_file(entry):
    _, _, _, fid, name, size, sha = entry
    digits = str(fid)
    return dict(projectID=622737, fileID=fid, fileName=name, size=size, sha256=sha,
        url=f'https://mediafilez.forgecdn.net/files/{digits[:4]}/{int(digits[4:])}/{name}', name=NAME, page=PAGE)


def present(instance):
    for path, enabled in mod_jars(instance):
        if MOD_ID in jar_ids(path):
            return dict(file=path.name, enabled=enabled)


def other_backup(instance):
    for path, enabled in mod_jars(instance):
        if enabled and any(BACKUP_WORDS.search(x) for x in jar_ids(path) - {MOD_ID}):
            return f'已有備份模組（{path.name}）'
    for folder in ('config', 'defaultconfigs'):
        root = Path(instance)/folder
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            if BACKUP_WORDS.search(path.name) and path.name != Path(CONFIG).name:
                return f'已有備份設定（{folder}/{path.name}）'
    return ''


def choose(instance):
    kind, mc = pack_loader(instance)
    version = numbers(mc)
    if kind == 'neoforge' and version < (1, 20, 2):
        kind = 'forge'
    for entry in FILES:
        if kind == entry[0] and entry[1] <= version <= entry[2]:
            # These are mandatory in this release. Do not install a mod that
            # would prevent the pack from starting, or replace existing versions.
            versions = {}
            for path, enabled in mod_jars(instance):
                if not enabled:
                    continue
                with zipfile.ZipFile(path) as z:
                    if 'META-INF/mods.toml' in z.namelist():
                        data = tomllib.loads(z.read('META-INF/mods.toml').decode('utf-8-sig'))
                        for mod in data.get('mods', []):
                            versions[mod.get('modId')] = numbers(str(mod.get('version', '')))
            missing = [name for name, low in (('architectury', (9, 0, 7)), ('polylib', (1200, 0, 0)))
                       if not versions.get(name) or versions[name] < low]
            if missing:
                return None, '缺少相容的必要模組：'+ '、'.join(missing)
            return mod_file(entry), ''
    return None, f'尚未核對 Minecraft {mc or "未知"}（{kind or "未知載入器"}）的備份版本；目前支援 1.20～1.20.1 Forge／NeoForge'


def listed(path):
    try:
        sha = file_hash(path)
        return KNOWN.get(sha) == Path(path).stat().st_size or bool(LOCALIZED_SHA and sha == LOCALIZED_SHA)
    except OSError:
        return False


def rewrite_class(raw, expected, edits):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('備份模組程式與已核對的版本不同，沒有修改通知')
    cf = ClassFile(raw)
    if not set(edits) <= set(cf.utf.values()):
        raise ValueError('備份通知原文不同，沒有修改')
    parts = [raw[:10]]
    for index, (start, end) in cf.spans.items():
        text = cf.utf.get(index)
        if text in edits:
            translated = edits[text]
            if re.findall(r'[\x00-\x1f]', text) != re.findall(r'[\x00-\x1f]', translated):
                raise ValueError('備份通知參數不一致')
            encoded = encode_mutf(translated)
            parts.append(b'\x01'+struct.pack('>H', len(encoded))+encoded)
        else:
            parts.append(raw[start:end])
    parts.append(raw[cf.tail:])
    result = b''.join(parts)
    checked = ClassFile(result)
    if result[checked.tail:] != raw[cf.tail:]:
        raise ValueError('備份通知寫回驗證失敗')
    return result


def mixin_conflict(instance, cancelled=lambda: False):
    """Conservative check, including nested jars; unreadable archives stop localization."""
    from full_translation_audit import MIXIN, mixin_targets
    targets = {n[:-6] for n in CLASS_EDITS}
    def inspect(z, depth=0):
        if depth > 4:
            raise ValueError('內嵌模組層數過多，無法確認備份通知能否修改')
        for info in z.infolist():
            if cancelled():
                raise InterruptedError()
            if info.filename.endswith(('.class', '.jar')):
                if info.file_size > 128*1024*1024:
                    raise ValueError('模組內容過大，無法確認備份通知能否修改')
                raw = z.read(info)
                if info.filename.endswith('.jar'):
                    with zipfile.ZipFile(io.BytesIO(raw)) as child:
                        if inspect(child, depth+1):
                            return True
                elif MIXIN in raw and targets & mixin_targets(raw):
                    return True
        return False
    for path, enabled in mod_jars(instance):
        if enabled:
            with zipfile.ZipFile(path) as z:
                if inspect(z):
                    return path.name
    return ''


def stage_chinese_jar(src, dst):
    changed = []
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(dst, 'w') as w:
        if len(z.namelist()) != len(set(z.namelist())) or z.testzip():
            raise ValueError('備份模組壓縮檔內容衝突或損壞')
        for info in z.infolist():
            if SIGNATURE_RE.match(info.filename):
                continue
            raw = z.read(info)
            if info.filename in CLASS_EDITS:
                expected, edits = CLASS_EDITS[info.filename]
                raw = rewrite_class(raw, expected, edits)
                changed.append(raw)
            w.writestr(info, raw)
    if len(changed) != len(CLASS_EDITS):
        raise ValueError('備份模組缺少已核對的程式檔')
    check_java(changed)
    result = VerifyResult()
    check_java_zipfs([dst], result)
    if not result.ok:
        raise ValueError('備份模組未通過 Java 壓縮檔驗證')


def prepare(instance, home, notify=lambda *_: None, cancelled=lambda: False):
    """Config, local display-only class edits and language pack, all restorable."""
    instance = Path(instance).resolve()
    found = present(instance)
    src = instance/'mods'/found['file']
    def snapshot():
        result = {}
        for path, enabled in mod_jars(instance):
            if cancelled():
                raise InterruptedError()
            if enabled:
                result[path.name] = file_hash(path)
        result['launcher'] = file_hash(instance/'minecraftinstance.json')
        return result
    inputs = snapshot()
    if not listed(src):
        raise ValueError('已有其他版本的備份模組，保留原設定；此版本的中文通知尚未核對')
    cf = jobs.is_curseforge(instance)
    if cf is True or (cf and src.name.casefold() in cf):
        raise ValueError('備份模組由 CurseForge 管理，啟動時會還原原檔；保留原設定，中文通知無法完整套用')
    conflict = mixin_conflict(instance, cancelled)
    if conflict:
        raise ValueError(f'{conflict} 的 Mixin 會改動備份模組，保留原設定，沒有修改通知')
    staged = Path(home)/'tmp'/('backup-mod-'+uuid.uuid4().hex[:8])
    staged.mkdir(parents=True)
    records = []
    try:
        before = file_hash(src)
        if before in KNOWN:
            dst = staged/'mods'/src.name
            dst.parent.mkdir()
            stage_chinese_jar(src, dst)
            if LOCALIZED_SHA and file_hash(dst) != LOCALIZED_SHA:
                raise ValueError('備份模組中文通知的校驗結果不同，沒有套用')
            records.append(dict(file='mods/'+src.name, before=before, after=file_hash(dst), reviewed=True, verified=True))
        if not (instance/CONFIG).exists():
            dst = staged/CONFIG
            dst.parent.mkdir(parents=True)
            dst.write_bytes(CONFIG_TEXT)
            records.append(dict(file=CONFIG, before=None, after=file_hash(dst), reviewed=True, verified=True))
        files, sources = jobs.read_resource_pack(instance)
        values = json.loads(files.get(LANG, b'{}'))
        values.update(LANG_TEXT)
        files[LANG] = json.dumps(values, ensure_ascii=False, indent=2).encode('utf-8')
        sources[LANG] = {'mods/'+src.name: records[0]['after'] if records and records[0]['file'].endswith('.jar') else before}
        records += jobs.stage_resource_pack(instance, staged, files, sources)
        for rec in (jobs.options_record(instance, staged, enable_pack=True), jobs.default_packs_record(instance, staged)):
            if rec:
                records.append(rec)
        if cancelled():
            raise InterruptedError()
        if records:
            jobs.require_space(instance, Path(home), [r['file'] for r in records])
            jobs.ensure_game_closed(instance)
            if snapshot() != inputs:
                raise ValueError('核對後模組或啟動器紀錄有變動，沒有寫入備份模組中文設定，請重試')
            return str(apply_reviewed(instance, staged, records, Path(home)/'output', jobs.waiting_note(notify, 100, '備份模組中文設定')))
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def ensure(instance, home, notify=lambda *_: None, cancelled=lambda: False, session=None, pause=time.sleep):
    from . import patches
    instance = Path(instance)
    installed = None
    try:
        if cancelled():
            raise InterruptedError()
        notify(0, '檢查世界備份模組', '核對已有的備份功能、版本與必要模組')
        found = present(instance)
        if found and not found['enabled']:
            return dict(state='disabled', line=f'{NAME} 已停用（{found["file"]}），沒有重新安裝或改設定。')
        if not found:
            if jobs.is_curseforge(instance) is True:
                return dict(state='unsupported', line=f'沒有加裝 {NAME}：CurseForge 紀錄讀不懂，無法確認中文通知能否保留。')
            why = other_backup(instance)
            if why:
                return dict(state='other_backup', line=f'沒有加裝 {NAME}：{why}。')
            mod, why = choose(instance)
            if not mod:
                return dict(state='unsupported', line=f'沒有加裝 {NAME}：{why}。')
            # Check before downloading: an installation must not create an
            # unlocalizable mod and then call it complete.
            if conflict := mixin_conflict(instance, cancelled):
                return dict(state='unsupported', line=f'沒有加裝 {NAME}：{conflict} 的 Mixin 會改動備份程式。')
            installed = patches.install_mods(instance, [mod], home, notify, cancelled, session, pause)
            if not installed['installed'] and not installed['present']:
                reason = installed['skipped'][0]['reason'] if installed['skipped'] else '原因不明'
                return dict(state='failed', line=f'沒有加裝 {NAME}：{reason}')
        existing_config = (instance/CONFIG).exists()
        notify(0, '核對備份模組的繁中通知', '檢查程式用途、Mixin 相容性與 Java 格式')
        batch = prepare(instance, home, notify, cancelled)
        return dict(state='installed' if installed and installed['installed'] else 'present',
            backup=installed['backup'] if installed else None, config_backup=batch,
            line=f'{NAME} 已備妥繁體中文通知。'+('保留原本的備份設定。' if existing_config else
                '每 30 分鐘備份、保留 5 份，沒人遊玩時略過；備份後保留至少 10 GB 空間。')+'可在「備份與還原」復原。')
    except InterruptedError:
        return dict(state='cancelled', backup=(installed or {}).get('backup'), line=f'已停止 {NAME} 設定；已完成的加裝批次可在「備份與還原」復原。')
    except Exception as exc:
        return dict(state='failed', backup=(installed or {}).get('backup'),
            line=f'{NAME} 尚未完成中文設定：{jobs.explain_error(exc)}；已完成的加裝批次可在「備份與還原」復原，其他步驟照常進行。')
