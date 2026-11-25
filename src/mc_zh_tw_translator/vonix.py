"""Vonix Guardian on published packs (使用者 2026-11-26 指定；AGENTS.md「Ledger」).

Server-side block/container/inventory logger with rollback (MIT). Players do not
need it; the dedicated server and the single-player host run it. Chat replies are
mostly hardcoded English: vonix_text.TEXT lists the display-only constants,
reviewed against the 2.3.2 source, and CLASS_EDITS binds each class to its
SHA-256. The localized jar is rebuilt on each computer from the CurseForge
download, never shared as class files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import time
import uuid
import zipfile
from pathlib import Path

from . import desktop_jobs as jobs
from .backup_mod import rewrite_class
from .class_text import ClassFile, check_java
from .deployment import apply_reviewed, file_hash
from .imblocker import jar_ids, numbers, pack_loader
from .sweeper import mod_jars
from .verifier import SIGNATURE_RE, VerifyResult, check_java_zipfs
from .vonix_text import TEXT

MOD_ID = 'vonixguardian'
NAME = 'Vonix Guardian'
PROJECT = 1672865
PAGE = 'https://www.curseforge.com/minecraft/mc-mods/vonix-guardian'
CONFIG = 'config/vonixguardian/config.json'
MINIMUM_APP_VERSION = '0.46.0'
FILES = (
    ('forge', (1, 20, 1), (1, 20, 1), 9629497, 'vonixguardian-forge-1.20.1-2.3.2.jar', 20641840,
     '9aac07021df7e596d26a5ec9c5734acee9f27f4b18ce0c86ec35763151d3bd34'),
)
KNOWN = {f[6]: f[5] for f in FILES}
CLASS_HASHES = {
 'network/vonix/guardian/core/command/LookupText.class': '1b75feb0169fc89719c24cfb3eccac0c8ce9221b87e689d42c4cc5789017020b',
 'network/vonix/guardian/core/query/InspectorLookup.class': 'd00b7e5cd673cdce3885dce558fed7b3038bce2cc5305e5888b0d801bddbbb23',
 'network/vonix/guardian/mc/v1_20_1/common/LookupFormatter.class': '057c7fcda08c9c24556ac605b7883a4b51a8edca93a217ff62f443c2feb5907b',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Lookup.class': 'debbb9f9c726dabe0b2cf69b88af5d83e57e66d0ed663c81efd374a2cb52cb09',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Inspect.class': 'eea77589b6f2c729feda29aa5298956cac22c66a3d8b00fbdb929dacac915be2',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Near.class': 'f532a8b0a3199d0d00515da449c0231c1a44db14677986cecee06ebf5984eb13',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Give.class': '995372c17034e237af17c9601340d28af23b2742417a620e5cf4f4a7b5c26efb',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Teleport.class': '6c44b13e8215d95dd4b80b634af20d59393bb6ca8a7680911c80840d7568b830',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Undo.class': '1b66cb705333065c903de7d78aeb7424c3791c7afbab74d5c0a2fc5abb98e794',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Preview.class': '84a1c5f9606dd4e5a7b1b7f2c00f9c1b2c90a48e33e5ef4c63e45d8fb78f1981',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Rollback.class': '9af4a6b03a717d3a4ad390ca02b3b6c239c9f4ef3253986eae4c7776c1f75812',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Restore.class': '55906ac5714f4b06649f169900525d98cbb873c2983e47c9ab7fccf8332df30f',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Purge.class': '9fc1928351c11a32a0f0a9735f1d8ec7321458651bf26ed4dab6fbe90031aebe',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Batch.class': 'e6ff1b7d859aa8c52bc3a22b5c9eb083c512fdfd04e9f34d83edf6768c420e9f',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Reload.class': 'e2d28f02f38be1066d87341d31ee66d1d11eb2ef844877f3d120c145b8793e02',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Config.class': 'dd0fe022201b38ac8426a074beb380b0b5b4fc0a7613701e35fcfea5cfdf6c7f',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$EntityLog.class': 'c94d1ceef3da47ef0e640db76f2ed6f9d239a2320e17d58e11c515a13f18ff77',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$Consumer.class': 'e49b4dcd74f10741339627fb985c96f703ad1adf8f177669b8e763bf6a63786e',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands$MigrateDb.class': '48aeef1ba7512e78e3f9cb5efdb028958ecd684d07da0da0671bd56e89259f17',
 'network/vonix/guardian/mc/v1_20_1/common/GuardianCommands.class': '88a2efd352a17716efed568e8bfb751f24c63a4d483c75083cbe3b15341589c0',
 'network/vonix/guardian/core/command/MutationOutcomeFormatter.class': 'b36881379682f334590c677afc8355f081bbe3b928b0df03c5216c0ba8352b60',
 'network/vonix/guardian/core/rollback/RollbackResult.class': '3888e5358328fd35480fd4921548c1b256bcf7be32982e65145b462281fe3bdc',
 'network/vonix/guardian/core/rollback/RollbackBatches.class': 'd66acb0c18abde07fa0d3e633e87e7bb813c67cd119324aef5e2edc6ac60b14e',
 'network/vonix/guardian/core/command/PurgeReport.class': 'f698ed2f77acfeccf385872e0a378b85ca1736298d2806e50e1ccf8070f1e853',
 'network/vonix/guardian/core/command/OperatorText.class': '43d6bb361526af3fef253b6b0ba480b5e04d0ada63e742e730ce82ef40929188',
 'network/vonix/guardian/core/rollback/PurgeScope.class': '6b1845deaabdfc2c757d754d44deb1cc09a43f09b5a5f07c453928034c9db77f',
 'network/vonix/guardian/core/command/CommandSpec.class': 'a7d7e6b5e1a7dbfab5dc3ffc36ac6f3ffc014e37720821efde5b0c48f8e02cec',
 'network/vonix/guardian/core/command/CommandHelp.class': '2bfdf4d92fd338c8f833a16b5aaec62044ea1c28397e5267a5553c8bd4b566f4',
}
CLASS_EDITS = {name: (CLASS_HASHES[name], edits) for name, edits in TEXT.items()}
# Vonix Guardian 2.3.2 writes these defaults on first start; a partial file stops it from
# booting (ConfigLoader validation), so a new install gets the whole file with zh_tw.
DEFAULT_CONFIG = {
 "database": {
  "type": "sqlite",
  "file": "vonixguardian.db",
  "jdbcUrl": None,
  "user": None,
  "password": None,
  "migrationTarget": None,
  "hikari": {
   "maxPoolSize": 10,
   "connectionTimeoutMs": 30000,
   "maxLifetimeMs": 1800000,
   "leakDetectionMs": 0
  },
  "logSql": False,
  "updateSchema": None
 },
 "queue": {
  "maxSize": 50000,
  "flushIntervalMs": 5000,
  "batchSize": 1000
 },
 "logFile": {
  "enabled": True,
  "directory": "logs/vonixguardian",
  "gzipRotated": True,
  "retentionDays": 30,
  "forceSyncOnFlush": False
 },
 "actions": {
  "logBlocks": True,
  "logContainers": True,
  "logItems": True,
  "logEntities": True,
  "logExplosions": True,
  "logChat": True,
  "logCommands": True,
  "logSessions": True,
  "logSigns": True,
  "logInteractions": True,
  "logWorldEvents": True,
  "worldBlacklist": [],
  "blockBlacklist": [
   "minecraft:air"
  ],
  "sourceBlacklist": [],
  "itemBlacklist": [],
  "entityBlacklist": [],
  "entityBlockChangeCoalesceWindowMs": 500,
  "entityBlockChangeMaxTracked": 8192,
  "entityChangeAllowlist": [],
  "entityChangeLogAllEntities": False,
  "logNaturalBreaks": True,
  "logTreeGrowth": True,
  "logMushroomGrowth": True,
  "logVineGrowth": True,
  "logSculkSpread": True,
  "logPortals": True,
  "logWaterFlow": False,
  "logLavaFlow": False,
  "logFireExtinguish": True,
  "logCampfireStart": True,
  "logHopperMetaFilter": False,
  "logDuplicateSuppression": True,
  "logCancelledChat": False,
  "mixinHotEvents": True,
  "actionTypeBlacklist": []
 },
 "permissions": {
  "useLuckPerms": True,
  "defaultOpLevel": 3,
  "perNodeOpLevels": {}
 },
 "lookup": {
  "defaultPageSize": 7,
  "maxRadius": 10000,
  "maxResultRows": 100000,
  "maxConcurrent": 4
 },
 "privacy": {
  "hashIps": False,
  "salt": "vonix-guardian-default-salt-CHANGE-ME"
 },
 "purge": {
  "minAgeSecondsConsole": 86400,
  "minAgeSecondsInGame": 2592000,
  "autoPurgeSeconds": 0,
  "autoPurgeTime": "03:30"
 },
 "storage": {
  "persistNbt": True
 },
 "rollback": {
  "explosionSupplementalReach": 16,
  "mutationBatchSize": 1000,
  "requireConfirm": False
 },
 "theme": "aqua",
 "language": "zh_tw"
}
# Filled from the official download after the deterministic local rewrite.
LOCALIZED_SHA = 'ecd6e18b880f0bc280792f47892c33f6f45d72224deb699568ee61ac38a6c8f8'


def mod_file(entry):
    _, _, _, fid, name, size, sha = entry
    digits = str(fid)
    return dict(projectID=PROJECT, fileID=fid, fileName=name, size=size, sha256=sha,
        url=f'https://mediafilez.forgecdn.net/files/{digits[:4]}/{int(digits[4:])}/{name}', name=NAME, page=PAGE)


def present(instance):
    for path, enabled in mod_jars(instance):
        if MOD_ID in jar_ids(path):
            return dict(file=path.name, enabled=enabled)


LOGGER_IDS = {'ledger', 'grieflogger', 'neoprotect', 'coreprotect', 'coreprotectneo', 'evoprotect', 'forgeprotect',
              'prismmod', 'blocklogger', 'modlog'}


def other_logger(instance):
    """Another block/container logger (Indexor's modId is ledger). Never two loggers."""
    for path, enabled in mod_jars(instance):
        found = jar_ids(path) & LOGGER_IDS
        if found:
            return f'已有紀錄模組（{path.name}{"，已停用" if not enabled else ""}）'
    return ''


def choose(instance):
    kind, mc = pack_loader(instance)
    version = numbers(mc)
    if kind == 'neoforge' and version < (1, 20, 2):
        kind = 'forge'
    for entry in FILES:
        if kind == entry[0] and entry[1] <= version <= entry[2]:
            return mod_file(entry), ''
    return None, f'Vonix Guardian 的繁中尚未核對 Minecraft {mc or "未知"}（{kind or "未知載入器"}）版本；目前支援 1.20.1 Forge／NeoForge'


def localized_hash():
    return LOCALIZED_SHA


def listed(path):
    try:
        sha = file_hash(path)
        return KNOWN.get(sha) == Path(path).stat().st_size or bool(LOCALIZED_SHA and sha == LOCALIZED_SHA)
    except OSError:
        return False


def safe_edits(raw, edits):
    """Edited Utf8 entries may only back String constants, never names or descriptors."""
    cf = ClassFile(raw)
    used = {}
    for tag, value in cf.cp.values():
        if tag in (7, 8, 16, 19, 20):
            used.setdefault(struct.unpack('>H', value[:2])[0], set()).add(tag)
        elif tag == 12:
            for i in struct.unpack('>HH', value):
                used.setdefault(i, set()).add(12)
    names = set(cf.fields) | {n for n, _ in cf.methods}
    for index, text in cf.utf.items():
        if text in edits and (used.get(index, set()) - {8} or text in names):
            raise ValueError('紀錄模組的文字同時是程式名稱，沒有修改')


def stage_chinese_jar(src, dst):
    changed = []
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(dst, 'w') as w:
        if len(z.namelist()) != len(set(z.namelist())) or z.testzip():
            raise ValueError('紀錄模組壓縮檔內容衝突或損壞')
        for info in z.infolist():
            if SIGNATURE_RE.match(info.filename):
                continue
            raw = z.read(info)
            if info.filename in CLASS_EDITS:
                expected, edits = CLASS_EDITS[info.filename]
                safe_edits(raw, edits)
                raw = rewrite_class(raw, expected, edits)
                changed.append(raw)
            w.writestr(info, raw)
    if len(changed) != len(CLASS_EDITS):
        raise ValueError('紀錄模組缺少已核對的程式檔')
    check_java(changed)
    result = VerifyResult()
    check_java_zipfs([dst], result)
    if not result.ok:
        raise ValueError('紀錄模組未通過 Java 壓縮檔驗證')


def config_text(existing=None):
    """zh_tw for the query-error bundle the mod ships; other keys keep the existing or default values."""
    data = json.loads(json.dumps(existing or DEFAULT_CONFIG))
    data['language'] = 'zh_tw'
    return (json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode('utf-8')


def prepare(instance, home, notify=lambda *_: None, cancelled=lambda: False):
    """Local display-only class edits and the language setting, one restorable batch."""
    from full_translation_audit import MIXIN, mixin_targets
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
        launcher = instance/'minecraftinstance.json'
        result['launcher'] = file_hash(launcher) if launcher.exists() else None
        return result
    inputs = snapshot()
    if not listed(src):
        raise ValueError('已有其他版本的 Vonix Guardian，保留原檔；此版本的繁中尚未核對')
    cf = jobs.is_curseforge(instance)
    if cf is True or (cf and src.name.casefold() in cf):
        raise ValueError('Vonix Guardian 由 CurseForge 管理，啟動時會還原原檔，繁中無法保留')
    targets = {n[:-6] for n in CLASS_EDITS}
    for path, enabled in mod_jars(instance):
        if enabled and path != src:
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.filename.endswith('.class') and info.file_size < 64*1024*1024:
                        raw = z.read(info)
                        if MIXIN in raw and targets & mixin_targets(raw):
                            raise ValueError(f'{path.name} 的 Mixin 會改動 Vonix Guardian，沒有修改文字')
    staged = Path(home)/'tmp'/('vonix-'+uuid.uuid4().hex[:8])
    staged.mkdir(parents=True)
    records = []
    try:
        before = file_hash(src)
        if before in KNOWN:
            dst = staged/'mods'/src.name
            dst.parent.mkdir()
            stage_chinese_jar(src, dst)
            if LOCALIZED_SHA and file_hash(dst) != LOCALIZED_SHA:
                raise ValueError('Vonix Guardian 繁中版的校驗結果不同，沒有套用')
            records.append(dict(file='mods/'+src.name, before=before, after=file_hash(dst), reviewed=True, verified=True))
        config = instance/CONFIG
        existing = None
        if config.exists():
            existing = json.loads(config.read_text(encoding='utf-8'))
        if not existing or existing.get('language') != 'zh_tw':
            dst = staged/CONFIG
            dst.parent.mkdir(parents=True)
            dst.write_bytes(config_text(existing))
            records.append(dict(file=CONFIG, before=file_hash(config) if config.exists() else None,
                                after=file_hash(dst), reviewed=True, verified=True))
        if cancelled():
            raise InterruptedError()
        if records:
            jobs.require_space(instance, Path(home), [r['file'] for r in records])
            jobs.ensure_game_closed(instance)
            if snapshot() != inputs:
                raise ValueError('核對後模組或啟動器紀錄有變動，沒有寫入 Vonix Guardian 繁中，請重試')
            return str(apply_reviewed(instance, staged, records, Path(home)/'output', jobs.waiting_note(notify, 100, 'Vonix Guardian 繁中')))
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def ensure(instance, home, notify=lambda *_: None, cancelled=lambda: False, session=None, pause=time.sleep):
    from . import patches
    instance = Path(instance)
    installed = None
    try:
        if cancelled():
            raise InterruptedError()
        notify(0, '檢查取放紀錄模組', '核對已有的紀錄模組與版本')
        found = present(instance)
        if found and not found['enabled']:
            return dict(state='disabled', line=f'{NAME} 已停用（{found["file"]}），沒有重新安裝。')
        if not found:
            if jobs.is_curseforge(instance) is True:
                return dict(state='unsupported', line=f'沒有加裝 {NAME}：CurseForge 紀錄讀不懂，無法確認繁中能否保留。')
            why = other_logger(instance)
            if why:
                return dict(state='other_logger', line=f'沒有加裝 {NAME}：{why}。')
            mod, why = choose(instance)
            if not mod:
                return dict(state='unsupported', line=f'沒有加裝 {NAME}：{why}。')
            installed = patches.install_mods(instance, [mod], home, notify, cancelled, session, pause)
            if not installed['installed'] and not installed['present']:
                reason = installed['skipped'][0]['reason'] if installed['skipped'] else '原因不明'
                return dict(state='failed', line=f'沒有加裝 {NAME}：{reason}')
        notify(0, '核對取放紀錄模組的繁中', '檢查程式用途、Mixin 相容性與 Java 格式')
        batch = prepare(instance, home, notify, cancelled)
        return dict(state='installed' if installed and installed['installed'] else 'present',
            backup=installed['backup'] if installed else None, config_backup=batch,
            line=f'{NAME} 已備妥繁體中文：管理員可用 /vg lookup 查誰在什麼時間拿了什麼。可在「備份與還原」復原。')
    except InterruptedError:
        return dict(state='cancelled', backup=(installed or {}).get('backup'), line=f'已停止 {NAME} 設定；已完成的加裝批次可在「備份與還原」復原。')
    except Exception as exc:
        return dict(state='failed', backup=(installed or {}).get('backup'),
            line=f'{NAME} 尚未完成繁中設定：{jobs.explain_error(exc)}；已完成的加裝批次可在「備份與還原」復原，其他步驟照常進行。')
