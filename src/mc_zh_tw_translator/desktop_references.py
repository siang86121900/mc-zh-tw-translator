"""Version-aware, fail-closed reference preflight for the desktop application."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from opencc import OpenCC


# OpenCC writes 臺, 巖, 牀… where Taiwan, and Minecraft's official zh_tw, write 台, 岩, 床.
TAIWAN_FORMS = str.maketrans({'臺':'台','巖':'岩','牀':'床','羣':'群','峯':'峰','裏':'裡','爲':'為','啓':'啟','着':'著','綫':'線','衆':'眾'})
S2TWP = OpenCC('s2twp')
S2T = OpenCC('s2t')
# Correct Traditional Chinese words that a character-by-character conversion would take for simplified.
KEPT_WORDS = re.compile('干擾|干涉|干預|若干|相干|皇后|王后|天后|太后|母后|蟻后|蜂后|蛛后|后羿|后土|人云亦云|云云|拮据|前仆後繼|仆倒')
# Simplified forms that Big5 also holds as old or rare characters (云 for 說, 后 for queen…) but that in
# today's Taiwan text are simplified. 伙, 准, 凶, 划, 占, 斗, 皂, 栗, 里 and the like are ordinary Taiwan
# characters and are not listed.
SIMPLIFIED_IN_BIG5 = set('万与么于云仆价优体余儿党凄几厂厘吁后吨听咨咸圣坏复夸宁尸岭帘干并庄异忏怀怜惊愿扑扰挂据昵晒机杠杰'
                         '极构柜栖气泞洁洒洼涂涌淀炖瓮痒确离种筑篱网羡肮胜腊腌苹范茧荐虫虱蚕蚝蜡蝎触赶适')


# One simplified character can stand for several traditional ones (松 pine / 鬆 loose, 只 only / 隻 a
# counter, 发 發 / 髮); the converter picks the wrong one where it knows no phrase. Seen in real modpacks.
COUNTED = '一二兩三四五六七八九十百千萬幾這那每數半\\d'
SLIPS = [(re.compile(a), b) for a, b in (
    ('鬆(?=[木樹果針鼠林脂香])', '松'), ('(?<=[雪赤黑白紅油])鬆(?![散開動弛懈軟緊])', '松'),
    ('(?<!['+COUNTED+'])隻(?=[能有是要會需在對可允讀限剩想為])', '只'), ('只讀', '唯讀'),
    ('幹草', '乾草'), ('吃幹抹淨', '吃乾抹淨'), ('(?<!頭)髮光', '發光'), ('繫結', '綁定'),
    # 钟 is both 鐘 (bell, clock: Netherite Bell, Clockstone) and the 鍾 of 鍾愛 / 鍾情 and names.
    ('(?<!獨)鍾(?![愛情意離馗])', '鐘'),
    # The converter keeps 后, 于, 云 and 范 where its word list sees a name or a queen (蜂后, 妖后, 球后,
    # 于禁, 子云) or a word is split by a line break (小范\n围): in mod text they are 後, 於, 雲 and 範.
    (r'((?:變成|成為|變為)[^，。、\s]{0,6}?)后(?=[，,])', r'\1後'),  # 變成蜜蜂后，獲得… is after, not a queen bee
    ('(?<![皇王天太母蟻蜂蛛影歌])后(?![羿土冠妃宮])', '後'), ('于', '於'), ('(?<![人所云亦])云(?![亦云])', '雲'),
    (r'范(?=\s*[圍疇例本式])', '範'), ('(?<=[規模示防典風])范', '範'),
    # Found by scripts/audit_conversion.py over 406,419 Simplified strings of real modpacks (2026-10-02).
    # 只 after an Arabic numeral is a counter (擊殺 3 只殭屍); the converter only knows 一只, 两只…
    # Not where 只 is "only": 1.20 只支援, 3 只能, 版本 2 只會.
    (r'(?<=\d)(\s?)只(?![能有是要會需在對可允讀限剩想為好得管支用作適顯影保做差計算針給讓])', r'\1隻'),
    # 并 is 並 (and); its word list makes 并为, 并发, 并成 the 併 of 合併. 合併, 吞併, 一併, 併入 and 併發症 stay.
    ('(?<![合吞兼歸一])併(?![購吞攏入肩]|發(?:症|數|量|執|處|連|請|上限))', '並'), ('合並', '合併'),
    # 个中 after a number or 一/另/多 is 個中 (一箇中央 → 一個中央); the idiom 箇中滋味 / 箇中原因 stays.
    ('箇(?=中(?![滋原奧高好緣道玄]))', '個'),
    ('几率', '機率'), ('几(?=[乎個天次種位分歲年秒週])', '幾'),
    # 干 is 乾 (dry) in materials and food (乾牆, 乾泥炭, 乾橡膠, 餅乾, 蘑菇乾); 幹活, 幹得好, 樹幹 stay.
    ('幹(?=[牆玉泥橡香竹耕胡沙淨燥枯涸果肉糧貨])', '乾'), ('幹(?=樹葉)', '乾'), ('(?<=[餅菇排烘曬晾])幹', '乾'),
    ('采(?=[礦蜜掘集收摘伐])', '採'), ('曆史', '歷史'), ('余燼', '餘燼'), ('准備', '準備'), ('熏(?=製)', '燻'),
    ('襬放', '擺放'), ('魷魚須', '魷魚鬚'), ('鬍桃', '胡桃'), ('(?<!夥)伙伴', '夥伴'), ('蘇裡拉', '蘇里拉'), ('颱(?=階)', '台'),
    ('繫列', '系列'), ('(?<=[岩火水冰雷風土光暗毒草電龍鋼])繫(?=命中)', '系'),
    ('姜(?=橙)', '薑'), ('(?<=[醃生])姜', '薑'), ('髮明', '發明'),
    ('(?<=[石木鐵銅金銀鋼玉竹皮紙陶瓷])制(?=[燈工品方祭廚成壁器具])', '製'),
    # 了 after a verb is the particle, not 瞭: 指明了通往, 描述了如何, 被發明了. 瞭解, 瞭望, 明瞭 (clear), 瞭如指掌 stay.
    ('終終界', '終末地'),  # written by versions before 0.27.0, which turned 终末地 (Arknights: Endfield) into 終界 inside the word
    ('(?<=[指表說證發聰])明瞭', '明了'), ('(?<!明)瞭(?![望解然]|如指)', '了'),
    # 回复 that restores HP, hunger or mana is 回復 (Taiwan's Pokémon wording); 回覆 is replying to someone.
    (r'回覆(?=[自對生血飢飽法魔所全滿少量一速能行藥道\d%＋+ＨH]|得|[，。]|$)', '回復'),
    ('(?<=[力命值以會能後時可緩並給來秒每級])回覆', '回復'),
)]
# 输出端口 is mainland players' slang for what deals the damage; the converter's word list makes it a computer
# port (輸出埠). In a fight it is 輸出手段; next to machines, the output side of a block is 輸出端.
PORT = re.compile('(輸[出入])埠')
COMBAT = re.compile('傷害|技能|流派|火球|攻擊|擊殺|法術|武器|魔法|高傷|DPS|打怪|輸出職業')
CLAUSE_END = re.compile('[。！？!?；;，,\\n]')


def fix_port(text: str) -> str:
    def word(m):
        start = max((x.end() for x in CLAUSE_END.finditer(text, 0, m.start())), default=0)
        end = CLAUSE_END.search(text, m.end())
        clause = text[start:end.start() if end else len(text)]
        return m[1]+('手段' if m[1] == '輸出' and COMBAT.search(clause) else '端')
    return PORT.sub(word, text)


def fix_slips(text: str) -> str:
    for pattern, replacement in SLIPS:
        text = pattern.sub(replacement, text)
    return fix_port(text)


# Minecraft's simplified-Chinese names (after character conversion) whose Taiwan official names differ,
# taken from Mojang's zh_cn and zh_tw of 1.21.1. Only words that mean nothing outside Minecraft are
# replaced inside sentences; 力量, 橡木, 中毒 and the like are ordinary words and stay. Longer names
# come first so 下界合金 becomes 獄髓, not 地獄合金.
MC_TERMS = (
    ('下界合金', '獄髓'), ('下界疣', '地獄疙瘩'), ('下界岩', '地獄石'), ('下界磚', '地獄磚'), ('下界之星', '地獄之星'),
    ('下界石英', '地獄石英'), ('下界荒地', '地獄荒原'), ('(?<!上)下界', '地獄'),
    ('末影人', '終界使者'), ('末影螨', '終界蟎'), ('末影蟎', '終界蟎'), ('末影龍火球', '龍炎彈'), ('末影', '終界'), ('(?<!終)末地', '終界'),  # 終末地 is Arknights: Endfield, not the End
    # 群系 alone is mainland players' short form of 生物群系 (海洋群系, 記錄群系); 族群系統 and the like are not it.
    ('生物群系', '生態域'), (r'生物(?=\s+群系)', ''), ('(?<![族人社菌])群系', '生態域'),
    ('失水惡魂', '乾癟幽靈'), ('快樂惡魂', '快樂幽靈'), ('惡魂', '地獄幽靈'),
    ('潛影貝', '界伏蚌'), ('潛影', '界伏'), ('幻翼膜', '夜魅皮膜'), ('幻翼', '夜魅'),
    ('殭屍豬靈', '殭屍化豬布林'), ('豬靈', '豬布林'),
    ('爆裂紫頌果', '爆開的歌萊果'), ('紫頌植株', '歌萊枝'), ('紫頌', '歌萊'),
    ('幽匿塊', '伏聆'), ('幽匿感測體', '伏聆振測器'), ('幽匿催發體', '伏聆觸媒'), ('幽匿尖嘯體', '伏聆嘯口'), ('幽匿', '伏聆'),
    ('凋靈', '凋零'), ('烈焰人', '烈焰使者'), ('烈焰棒', '烈焰桿'), ('熒石粉', '螢石粉'), ('熒石', '螢光石'),
    ('劫掠獸', '劫毀獸'), ('溺屍', '沉屍'), ('刷怪蛋', '生怪蛋'), ('刷怪籠', '生怪磚'),
)
# Names of the game's own structures (structure.minecraft.<id>, shown by the compass mods). Minecraft has no language
# key for them, but its zh_tw names each one in maps and advancements (1.20.1 and 1.21.1): filled_map.village_* (平原村莊地圖…),
# item.minecraft.desert_pyramid_map, jungle_pyramid_map (叢林遺跡地圖), swamp_hut_map, ocean_monument_map (海底遺跡地圖),
# warm_ocean_ruins_map (溫暖海底廢墟地圖), woodland_mansion_map (綠林府邸地圖), mineshaft_map, ancient_city_map,
# trial_explorer_map (試煉密室探險家地圖), advancements find_bastion (堡壘遺蹟), find_fortress (地獄要塞), find_end_city
# (終末都市), selectWorld.mapFeatures.info (村莊、沉船), and biome.minecraft.badlands / cold_ocean (惡地、寒冷海洋).
# Structure sets (the compass's 團體) name the same things in the plural. Names zh_tw does not give are left to other sources.
VANILLA_STRUCTURE_NAMES = {
    'village': '村莊', 'villages': '村莊', 'village_plains': '平原村莊', 'village_desert': '沙漠村莊', 'village_savanna': '莽原村莊',
    'village_snowy': '雪原村莊', 'village_taiga': '針葉林村莊', 'desert_pyramid': '沙漠神殿', 'desert_pyramids': '沙漠神殿',
    'jungle_pyramid': '叢林遺跡', 'jungle_temples': '叢林遺跡', 'swamp_hut': '沼澤小屋', 'swamp_huts': '沼澤小屋',
    'monument': '海底遺跡', 'ocean_monuments': '海底遺跡', 'ocean_ruin': '海底廢墟', 'ocean_ruins': '海底廢墟',
    'ocean_ruin_warm': '溫暖海底廢墟', 'ocean_ruin_cold': '寒冷海底廢墟', 'mansion': '綠林府邸', 'woodland_mansions': '綠林府邸',
    'mineshaft': '礦坑', 'mineshafts': '礦坑', 'mineshaft_mesa': '惡地礦坑', 'ancient_city': '遠古城市', 'ancient_cities': '遠古城市',
    'trial_chambers': '試煉密室', 'bastion_remnant': '堡壘遺蹟', 'fortress': '地獄要塞', 'end_city': '終末都市', 'endcity': '終末都市',
    'end_cities': '終末都市', 'shipwreck': '沉船', 'shipwrecks': '沉船',
}
MC_TERM = re.compile('|'.join(f'(?P<t{i}>{a})' for i, (a, _) in enumerate(MC_TERMS)))
# Ordinary words that are Minecraft names only when they are the whole text (a mod's 地牢監守者 stays).
MC_EXACT = {'監守者': '伏守者', '守衛者': '深海守衛', '遠古守衛者': '遠古深海守衛', '凋靈': '凋零怪', '蠹蟲': '蠹魚'}


def minecraft_terms(text: str) -> str:
    """Minecraft names in Taiwan's official wording (地獄, 終界, 生態域…), in one pass."""
    if not isinstance(text, str) or not text:return text
    if text.strip() in MC_EXACT:return text.replace(text.strip(), MC_EXACT[text.strip()])
    return MC_TERM.sub(lambda m: MC_TERMS[int(m.lastgroup[1:])][1], text)


def to_taiwan(text: str) -> str:
    """Simplified Chinese to Taiwan wording, written with the character forms Taiwan uses."""
    return minecraft_terms(fix_slips(S2TWP.convert(text).translate(TAIWAN_FORMS)))


def has_simplified(text: str) -> bool:
    """Whether text contains simplified characters; 台, 岩, 床 and similar Taiwan forms do not count.

    A character counts only when Big5, Taiwan's traditional character set, cannot write it and the converter
    would change it. Comparing the whole text before and after conversion took ordinary Taiwan characters
    for simplified, because the converter also rewrites 吃, 背, 游, 秘, 了 into rare variants (喫, 揹, 遊…).
    """
    for ch in KEPT_WORDS.sub('', text):
        if '㐀' <= ch <= '鿿' and S2T.convert(ch) != ch:
            if ch in SIMPLIFIED_IN_BIG5: return True
            try: ch.encode('big5')
            except UnicodeEncodeError: return True
    return False


VERSION = re.compile(r'1\.\d+(?:\.\d+)?')


def launcher_version(instance: Path) -> tuple[str, str]:
    """(Minecraft version, file it came from) as recorded by the launcher, or ('', '')."""
    def read(path):
        return json.loads(path.read_text(encoding='utf-8-sig'))
    readers = (
        ('manifest.json', lambda d: d.get('minecraft', {}).get('version')),              # CurseForge export
        ('minecraftinstance.json', lambda d: d.get('gameVersion')),                        # CurseForge app
        ('mmc-pack.json', lambda d: next((c.get('version') for c in d.get('components', [])
                                          if c.get('uid') == 'net.minecraft'), None)),    # Prism, MultiMC, PolyMC
        ('profile.json', lambda d: d.get('metadata', {}).get('game_version')),            # Modrinth
        ('instance.json', lambda d: d.get('id')),                                          # ATLauncher
    )
    # Prism and MultiMC keep the game in .minecraft/ and their own files one folder up.
    for folder in (instance, instance.parent):
        for filename, pick in readers:
            try:
                value = pick(read(folder/filename))
            except (OSError, ValueError, AttributeError, TypeError):
                continue
            if isinstance(value, str) and VERSION.fullmatch(value):
                return value, filename
    return '', ''


def version_from_mods(instance: Path, limit: int = 80) -> str:
    """The Minecraft version the installed mods ask for, when the launcher left no record.

    Each mod states the oldest Minecraft it runs on; the most common release line wins and, within
    it, the highest of those minimums, because every installed mod has to run on the real version.
    """
    found = []
    for jar in sorted((instance/'mods').glob('*.jar'))[:limit]:
        try:
            with zipfile.ZipFile(jar) as z:
                names = set(z.namelist())
                for meta in ('META-INF/neoforge.mods.toml', 'META-INF/mods.toml'):
                    if meta in names:
                        for block in z.read(meta).decode('utf-8', 'replace').split('[[dependencies.')[1:]:
                            if re.search(r'(?m)^\s*modId\s*=\s*"minecraft"', block):
                                m = re.search(r'(?m)^\s*versionRange\s*=\s*"([^"]*)"', block)
                                v = m and VERSION.search(m[1])
                                if v: found.append(v[0])
                        break
                else:
                    if 'fabric.mod.json' in names:
                        wanted = json.loads(z.read('fabric.mod.json').decode('utf-8-sig')).get('depends', {}).get('minecraft')
                        v = VERSION.search(' '.join(wanted) if isinstance(wanted, list) else str(wanted or ''))
                        if v: found.append(v[0])
        except (OSError, ValueError, zipfile.BadZipFile, AttributeError):
            continue
    if not found:
        return ''
    numbers = lambda v: [int(n) for n in v.split('.')]
    line = lambda v: '.'.join(v.split('.')[:2])
    counts = {}
    for v in found: counts[line(v)] = counts.get(line(v), 0)+1
    best = max(counts, key=lambda k: (counts[k], numbers(k)))
    return max((v for v in found if line(v) == best), key=numbers)


def detect_version(instance: Path) -> tuple[str, str]:
    """(Minecraft version, how it was found); the second part is shown in the report."""
    version, source = launcher_version(instance)
    if version:
        return version, source
    version = version_from_mods(instance)
    return (version, '由已安裝模組的需求推測') if version else ('', '')


def minecraft_version(instance: Path) -> str:
    return detect_version(instance)[0]


def build_scoped(raw: bytes, locale: str, progress=lambda _:None, cancelled=lambda:False) -> dict:
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=sorted(z.namelist())
        for i,name in enumerate(names):
            if i%100==0:
                if cancelled():raise InterruptedError('已停止參考庫整理；掃描報告已保留。')
                progress(f'整理參考庫 {locale}：{i:,} / {len(names):,} 個檔案')
            match = re.search(r'(?:^|/)assets/([^/]+)/lang/'+locale+r'\.json$', name)
            namespace = match[1] if match else None
            if not namespace and locale == 'zh_tw':
                match = re.match(r'(.*/Translation/[^/]+)/([^/]+)/zh_tw.json$', name)
                if match:
                    try:
                        meta = json.loads(z.read(match[1]+'/metadata.json'))
                        namespace = meta.get('contents', {}).get('tiers', {}).get(match[2], {}).get('mod_id', meta.get('mod_id'))
                    except (KeyError, ValueError):
                        continue
            if not namespace or z.getinfo(name).file_size > 64*1024*1024:
                continue
            try:
                values = json.loads(z.read(name).decode('utf-8-sig'))
                if not isinstance(values, dict):
                    continue
                result.setdefault(namespace, {}).update({k: to_taiwan(v) if locale=='zh_cn' else v
                                                        for k,v in values.items() if isinstance(v,str)})
                if locale == 'zh_tw':
                    # Keep every version folder's (zh_tw, English) pair so matching can pick the translation
                    # whose English equals the installed mod's text instead of whichever folder sorts last.
                    sibling = name[:-len('zh_tw.json')]+'en_us.json'
                    english = json.loads(z.read(sibling).decode('utf-8-sig')) if sibling in names else {}
                    pairs = result.setdefault('__pairs__', {}).setdefault(namespace, {})
                    for k, v in values.items():
                        if isinstance(v, str):
                            pairs.setdefault(k, []).append((v, english.get(k) if isinstance(english, dict) else None))
            except (ValueError, UnicodeError):
                continue
    if not [k for k in result if not k.startswith('__')]:
        raise ValueError('參考庫中找不到有效語系資料。')
    return result


def pick_reference(ref: dict, namespace: str, key: str, english):
    """(translation, English matches current version) for one key of a zh_tw reference pack.

    A version whose English equals the installed text wins; otherwise the newest folder is returned
    as an unverified candidate. Packs without English (CFPA zh_cn) report None for the match flag.
    """
    pairs = ref.get('__pairs__', {}).get(namespace, {}).get(key)
    if not pairs:
        value = ref.get(namespace, {}).get(key)
        return value, None
    if isinstance(english, str):
        for zh, en in pairs:
            if isinstance(en, str) and en.strip() == english.strip():
                return zh, True
        return pairs[-1][0], False
    return pairs[-1][0], None


TW_REPO = 'TeamKugimiya/ModsTranslationPack'
PARA_REPO = 'TeamKugimiya/ParaTranslationPack'
CFPA_REPO = 'CFPAOrg/Minecraft-Mod-Language-Package'
ATTEMPTS = 3


class RateLimited(RuntimeError):
    """GitHub's hourly allowance for queries without an account is used up on this network."""
    def __init__(self, reset=None):
        self.reset = reset
        minutes = max(1, round((reset-time.time())/60)) if reset else None
        super().__init__('GitHub 的查詢次數暫時用完（同一個網路每小時 60 次）'
                         + (f'，約 {minutes} 分鐘後恢復。' if minutes else '，請稍後再試。'))


def network_message(exc) -> str:
    """Why a download or lookup failed, in words a player can act on."""
    if isinstance(exc, RateLimited):
        return str(exc)
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return '連線逾時，網路可能不穩，請稍後再試。'
    if isinstance(exc, requests.exceptions.SSLError):
        return '安全連線失敗，請確認電腦的日期時間正確，或暫時關閉會攔截連線的軟體後再試。'
    if isinstance(exc, requests.ConnectionError):
        return '無法連上網路，請檢查網路連線後再試。'
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        if code == 404: return '找不到要下載的檔案，來源可能已更名或移除。'
        if code >= 500: return f'對方伺服器暫時故障（代碼 {code}），請稍後再試。'
        return f'對方伺服器拒絕了要求（代碼 {code}），請稍後再試。'
    if isinstance(exc, requests.RequestException):
        return '下載中斷，請檢查網路後再試。'
    return str(exc)


def rate_limited(response):
    if response.status_code in (403, 429) and response.headers.get('X-RateLimit-Remaining') == '0':
        reset = response.headers.get('X-RateLimit-Reset', '')
        raise RateLimited(int(reset) if reset.isdigit() else None)


def refresh(instance: Path, cache: Path, progress, cancelled) -> tuple[list[dict], dict]:
    version, version_source = detect_version(instance)
    if not version:
        raise ValueError('無法辨識這個模組包的 Minecraft 版本。請選擇模組包的根資料夾（裡面有 mods），'
                         '並確認 mods 裡已經有模組。')
    family = '-'.join(version.split('.')[:2])
    asset_name = f'Minecraft-Mod-Language-Modpack-{family}.zip'
    cache.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers['User-Agent'] = 'MCTranslator-References'

    def attempt(description, action):
        """Bounded retries for failures that usually pass: dropped connections, timeouts, server errors."""
        for n in range(1, ATTEMPTS+1):
            if cancelled():
                raise InterruptedError('已停止，遊戲原檔未修改。')
            try:
                return action()
            except (requests.ConnectionError, requests.Timeout, TimeoutError, requests.HTTPError) as exc:
                code = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else 0
                if n == ATTEMPTS or (isinstance(exc, requests.HTTPError) and code < 500):
                    raise
                wait = 2*n
                progress(f'{description}：連線不穩，{wait} 秒後重試（第 {n+1} 次，最多 {ATTEMPTS} 次）')
                until = time.monotonic()+wait
                while time.monotonic() < until:
                    if cancelled():
                        raise InterruptedError('已停止，遊戲原檔未修改。')
                    time.sleep(.2)

    def fetch(url, description, binary=False):
        def action():
            progress(description+'…（連線逾時會保留報告並停止）')
            started = time.monotonic()
            with session.get(url, timeout=(10, 20), stream=True) as r:
                rate_limited(r)
                r.raise_for_status()
                total = int(r.headers.get('Content-Length', 0)); chunks = []; received = 0; last = 0
                for block in r.iter_content(256*1024):
                    if cancelled(): raise InterruptedError('已停止下載，掃描報告已保留。')
                    if time.monotonic()-started > 300: raise TimeoutError('參考庫下載超過 5 分鐘，請檢查網路後重試。')
                    received += len(block)
                    if received > 256*1024*1024: raise ValueError('參考庫超過大小上限，已停止。')
                    chunks.append(block)
                    if time.monotonic()-last >= .5:
                        suffix = f' / {total/1048576:.1f} MB' if total else ' MB'
                        progress(f'{description}：{received/1048576:.1f}'+suffix)
                        last = time.monotonic()
            return b''.join(chunks)
        raw = attempt(description, action)
        return raw if binary else json.loads(raw)

    confirmed = {}  # how each source's latest version was confirmed, kept in the report

    def latest_commit(repo, name):
        """Newest commit of the main branch. Asked the way git itself asks, which has no hourly
        allowance; GitHub's query service is the second choice."""
        try:
            raw = fetch(f'https://github.com/{repo}.git/info/refs?service=git-upload-pack', '查詢'+name+'最新版', binary=True)
            found = re.search(rb'([0-9a-f]{40}) refs/heads/main\n', raw)
            if not found: raise ValueError('回應裡沒有 main 分支')
            confirmed[name] = 'git'
            return found[1].decode()
        except InterruptedError:
            raise
        except Exception:
            sha = fetch(f'https://api.github.com/repos/{repo}/commits/main', '查詢'+name+'最新版（備援）')['sha']
            confirmed[name] = 'api'
            return sha

    release = []  # the query service's asset list, asked for at most once

    def from_api(name):
        if not release:
            release.append(fetch(f'https://api.github.com/repos/{CFPA_REPO}/releases/tags/autobuild', '查詢簡中參考庫最新版（備援）'))
        x = next((x for x in release[0]['assets'] if x['name'] == name), None)
        return x and dict(name=name, identity=str(x['id'])+'-'+x['updated_at'], updated=x['updated_at'], url=x['browser_download_url'])

    def latest_asset(name):
        """One CFPA download as it is published right now, or None when that version has none.

        The download's own headers say when it last changed, so no query allowance is spent.
        """
        url = f'https://github.com/{CFPA_REPO}/releases/download/autobuild/{name}'
        try:
            def action():
                with session.head(url, timeout=(10, 20), allow_redirects=True) as r:
                    if r.status_code == 404: return None
                    r.raise_for_status()
                    return dict(r.headers)
            headers = attempt('查詢 '+name, action)
            if headers is None:
                return None
            headers = {k.lower(): v for k, v in headers.items()}
            marks = [headers.get(k, '') for k in ('etag', 'last-modified', 'content-length')]
            if not (marks[0] or marks[1]): raise ValueError('下載位置沒有提供更新時間')
            confirmed[name] = 'download'
            return dict(name=name, identity='|'.join(marks), updated=marks[1], url=url)
        except InterruptedError:
            raise
        except Exception:
            found = from_api(name)
            confirmed[name] = 'api'
            return found

    progress('確認最新繁中與簡中參考庫…')
    try:
        commit = latest_commit(TW_REPO, '繁中參考庫')
        asset = latest_asset(asset_name)
    except InterruptedError:
        raise
    except Exception as exc:
        raise ValueError('無法確認參考庫是不是最新版，這次沒有開始翻譯，遊戲檔案也沒有修改。'+network_message(exc)) from exc
    if not asset:
        raise ValueError(f'簡中參考庫（CFPA）沒有提供 Minecraft {version} 的版本，已停止正式翻譯。')
    specs = [('tw', commit, f'https://codeload.github.com/{TW_REPO}/zip/{commit}', 'zh_tw'),
             ('cn', asset['identity'], asset['url'], 'zh_cn')]
    dbs, hashes, sources, notes, used = [], {}, [], [], set()

    def load(kind, identity, url, locale, name):
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        rawpath = cache/f'{kind}-{key}.zip'
        if rawpath.exists():
            raw = rawpath.read_bytes()
        else:
            progress('下載'+name+'…')
            raw = fetch(url, '下載'+name, binary=True)
        progress('解析'+name+'…')
        db = build_scoped(raw, locale, progress, cancelled)
        if not rawpath.exists():
            tmp = rawpath.with_suffix('.download')
            tmp.write_bytes(raw)
            tmp.replace(rawpath)
        used.add(rawpath.name)
        dbs.append(db); sources.append(kind)
        hashes[kind] = hashlib.sha256(raw).hexdigest()

    # Primary references must be confirmed latest; failures stop the translation (AGENTS.md).
    for kind, identity, url, locale in specs:
        try:
            load(kind, identity, url, locale, '繁中參考庫' if kind == 'tw' else '簡中參考庫')
        except InterruptedError:
            raise
        except (requests.RequestException, TimeoutError) as exc:
            raise ValueError('參考庫下載失敗，這次沒有開始翻譯，遊戲檔案也沒有修改。'+network_message(exc)) from exc
    # Supplementary sources only add coverage; if one is unavailable it is skipped and noted.
    para_commit = None
    try:
        para_commit = latest_commit(PARA_REPO, 'ParaTranslationPack')
        load('para', para_commit, f'https://codeload.github.com/{PARA_REPO}/zip/{para_commit}', 'zh_tw', 'ParaTranslationPack')
    except InterruptedError:
        raise
    except Exception as exc:
        notes.append('ParaTranslationPack 暫時無法取得：'+network_message(exc)[:120])
    older = []
    minor = int(family.split('-')[1])
    for n in range(minor-1, max(11, minor-7), -1):  # the three newest older versions that CFPA publishes
        if len(older) == 3: break
        name = f'Minecraft-Mod-Language-Modpack-1-{n}.zip'
        try:
            x = latest_asset(name)
            if not x: continue
            load('cn-1-'+str(n), x['identity'], x['url'], 'zh_cn', '跨版本簡中參考庫 '+name)
            older.append(x)
        except InterruptedError:
            raise
        except Exception as exc:
            notes.append(f'{name} 暫時無法取得：{network_message(exc)[:120]}')
    vanilla = official_vanilla(version, fetch, cache, progress)
    if vanilla:
        dbs.append(vanilla); sources.append('vanilla')
    else:
        notes.append('找不到官方 Minecraft 繁中語系檔，本次沒有使用官方譯名。')
    if version_source.startswith('由'):
        notes.append(f'啟動器沒有記錄 Minecraft 版本，{version_source}為 {version}。')
    # Downloads of earlier versions are no longer the latest and are never read again.
    for stale in list(cache.glob('*.zip'))+list(cache.glob('*.download')):
        if stale.name not in used:
            try: stale.unlink()
            except OSError: pass
    return dbs, dict(checked_at=datetime.now(timezone.utc).isoformat(), minecraft=version, minecraft_source=version_source,
                     ref_commit=commit, cfpa_asset=asset_name, cfpa_updated=asset['updated'],
                     para_commit=para_commit, cross_version_assets=[x['name'] for x in older],
                     vanilla=vanilla.get('__source__') if vanilla else None, sources=sources, notes=notes,
                     confirmed_by=confirmed,
                     sha256=hashes, entries=[sum(len(v) for k,v in x.items() if not k.startswith('__')) for x in dbs])


# Reference packs that are already Traditional Chinese written by people (vs. converted zh_cn).
HUMAN_TW_KINDS = ('tw', 'para')


def launcher_roots() -> list[Path]:
    home = Path.home(); appdata = Path(__import__('os').environ.get('APPDATA', home/'AppData/Roaming'))
    return [home/'curseforge/minecraft/Install', appdata/'.minecraft', appdata/'PrismLauncher', appdata/'ModrinthApp/meta']


def official_vanilla(version: str, fetch, cache: Path, progress) -> dict:
    """Mojang's own zh_tw (and en_us) for this Minecraft version, from a local launcher or Mojang's servers.

    Returned as {'minecraft': {key: zh_tw}, '__terms__': {english text: zh_tw}, '__source__': where}.
    """
    cached = cache/f'vanilla-{version}.json'
    if cached.exists():
        try: return json.loads(cached.read_text(encoding='utf-8'))
        except ValueError: pass
    zh = en = None; source = ''
    for root in launcher_roots():
        try:
            meta = json.loads((root/'versions'/version/f'{version}.json').read_text(encoding='utf-8'))
            index = json.loads((root/'assets/indexes'/f"{meta['assetIndex']['id']}.json").read_text(encoding='utf-8'))
            digest = index['objects']['minecraft/lang/zh_tw.json']['hash']
            zh = json.loads((root/'assets/objects'/digest[:2]/digest).read_text(encoding='utf-8'))
            with zipfile.ZipFile(root/'versions'/version/f'{version}.jar') as z:
                en = json.loads(z.read('assets/minecraft/lang/en_us.json').decode('utf-8'))
            source = str(root); break
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue
    if zh is None:
        try:
            progress('下載官方 Minecraft 繁中語系檔…')
            manifest = fetch('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json', '查詢 Minecraft 版本清單')
            meta = fetch(next(v['url'] for v in manifest['versions'] if v['id'] == version), '查詢 Minecraft 版本資料')
            index = fetch(meta['assetIndex']['url'], '查詢官方資源索引')
            digest = index['objects']['minecraft/lang/zh_tw.json']['hash']
            zh = json.loads(fetch(f'https://resources.download.minecraft.net/{digest[:2]}/{digest}', '下載官方繁中語系檔', binary=True))
            jar = fetch(meta['downloads']['client']['url'], '下載官方英文語系（遊戲本體）', binary=True)
            with zipfile.ZipFile(io.BytesIO(jar)) as z:
                en = json.loads(z.read('assets/minecraft/lang/en_us.json').decode('utf-8'))
            source = 'Mojang 官方伺服器'
        except InterruptedError:
            raise
        except Exception:
            return {}
    terms = {}
    for key, text in en.items():
        # Whole-string names only (items, blocks, mobs, effects...), so short UI words keep their mod context.
        if isinstance(text, str) and isinstance(zh.get(key), str) and re.match(r'(?:block|item|entity|effect|enchantment|biome)\.minecraft\.', key):
            terms.setdefault(text.strip().casefold(), zh[key])
    result = {'minecraft': {k: v for k, v in zh.items() if isinstance(v, str)}, '__terms__': terms, '__source__': source}
    try: cached.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except OSError: pass
    return result
