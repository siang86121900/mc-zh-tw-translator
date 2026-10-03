"""Player text written straight into data-pack files: structures (.nbt), functions (.mcfunction) and loot tables.

These files hold the words the game shows as written, with no language key: a shop NPC's categories and name
(CobbleDollars' CobbleMerchantShop.Category, CustomName), signs, books placed in a structure, the chat messages
of a function (tellraw / title) and the books it gives, a loot table's item names. A resource pack cannot reach
them, so the text is changed in the file itself, string by string; every other byte stays as it was.

Each piece of text is a unit with a stable key (where it is, counted in file order) and its text. A JSON text
component holding one piece of words is that piece; one with several (a book page with bold and clickable parts)
is the component itself, whose shape (everything but the words) must not change.
"""
import gzip
import io
import json
import re
import struct


# Capsule 1.20.1 (capsule-common.toml lootTemplatesPaths, starterTemplatesPath, prefabsTemplatesPath,
# rewardTemplatesPath) places the structures in config/capsule/ when a capsule is deployed, books and signs included.
STRUCTURE = re.compile(r'(?:^|/)data/[^/]+/structures?/.+\.nbt$|^/?config/capsule/(?:loot|starters|prefabs|rewards)/.+\.nbt$')
FUNCTION = re.compile(r'(?:^|/)data/[^/]+/functions?/.+\.mcfunction$')
# trades: VillagerConfig 4.5 (TradeManager) loads data/<ns>/trades/*.json, whose results are vanilla loot item entries.
# treasurebags_types: Treasure Bags 1.9 (BagType$Serializer) reads "displayName" with Component.Serializer, the bag's name.
LOOT = re.compile(r'(?:^|/)data/[^/]+/(?:loot_tables?|advancements?|item_modifiers?|trades|treasurebags_types)/.+\.json$')
# What makes such a file show words: an item named or given lore, an advancement with a display, a bag's name.
LOOT_WORDS = re.compile(r'"(?:minecraft:)?set_(?:name|lore)"|"display"\s*:|"displayName"\s*:')
WORDS = re.compile(r'[A-Za-z]{2}|[\u3400-\u9fff]')
HAN = re.compile('[\u3400-\u9fff]')

# NBT strings holding a JSON text component: names over entities and blocks, sign lines, item names and lore.
JSON_FIELDS = {'CustomName', 'Text1', 'Text2', 'Text3', 'Text4', 'messages', 'filtered_messages',
               'minecraft:custom_name', 'minecraft:item_name', 'minecraft:lore'}
# NBT strings shown as they are: CobbleDollars shop categories (ShopScreen draws Category.getName), book authors.
PLAIN_FIELDS = {'Category', 'author'}


def is_file(name):
    return bool(STRUCTURE.search(name) or FUNCTION.search(name) or LOOT.search(name) or RCT_TRAINER.search(name)
                or FANCYMENU.search(name) or REI_GROUPS.search(name))


# --- JSON text components -------------------------------------------------------------------------------------

def text_spans(raw):
    """(start, end, value) of the words of a JSON text component, in order: every "text" value and every bare
    string of a component list (["", {"text": "a"}, " and "]). Keys, colours, click and hover targets are not words.
    None when `raw` is not JSON."""
    spans = []; i = [0]; n = len(raw)

    def skip():
        while i[0] < n and raw[i[0]] in ' \t\r\n':i[0] += 1

    def string():
        start = i[0]; i[0] += 1
        while i[0] < n and raw[i[0]] != '"':i[0] += 2 if raw[i[0]] == '\\' else 1
        if i[0] >= n:raise ValueError('unterminated string')
        i[0] += 1
        return start, i[0], json.loads(raw[start:i[0]])

    def value(words):
        skip()
        if i[0] >= n:raise ValueError('unexpected end')
        c = raw[i[0]]
        if c == '"':
            start, end, text = string()
            if words:spans.append((start, end, text))
        elif c == '{':
            i[0] += 1; skip()
            if raw[i[0]] == '}':i[0] += 1;return
            while True:
                skip(); _, _, key = string(); skip()
                if raw[i[0]] != ':':raise ValueError('expected :')
                i[0] += 1
                value(key == 'text' or (key in ('extra', 'with') and 'list'))
                skip()
                if raw[i[0]] == ',':i[0] += 1;continue
                if raw[i[0]] == '}':i[0] += 1;return
                raise ValueError('expected , or }')
        elif c == '[':
            i[0] += 1; skip()
            if raw[i[0]] == ']':i[0] += 1;return
            while True:
                value(bool(words)); skip()
                if raw[i[0]] == ',':i[0] += 1;continue
                if raw[i[0]] == ']':i[0] += 1;return
                raise ValueError('expected , or ]')
        else:
            m = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null').match(raw, i[0])
            if not m:raise ValueError('bad JSON value')
            i[0] = m.end()

    try:
        value(True); skip()
        if i[0] != n:return None
    except (ValueError, IndexError):
        return None
    return spans


def blank_words(raw):
    """The component with its words emptied: what a translation of it must keep exactly. None when not JSON."""
    spans = text_spans(raw)
    if spans is None:return None
    out = []; last = 0
    for start, end, _ in spans:out += [raw[last:start], '""']; last = end
    return ''.join(out + [raw[last:]])


def component_unit(raw):
    """(text to translate, how it maps back) for a JSON component: its one piece of words, or the whole component
    when it has several. None when it is not JSON or has no words."""
    spans = text_spans(raw)
    if spans is None:return None
    worded = [k for k, (_, _, v) in enumerate(spans) if WORDS.search(v)]
    if not worded:return None
    if len(worded) == 1:return spans[worded[0]][2], ('piece', worded[0])
    return raw, ('whole', None)


def reads_as(found, written):
    """Whether the unit read back from a file (`found`) is the translation `written` there. A whole component
    whose translation leaves words in one piece only (["天空的守護者", ""] for ["Guardian of the ", "Skies"]) is
    read back as that one piece."""
    if found is None:return False
    if found == written:return True
    unit = component_unit(written) if isinstance(written, str) else None
    return bool(unit) and unit[1][0] == 'piece' and unit[0] == found


def put_component(raw, how, text):
    """`raw` with the unit's words replaced by `text` (a piece, or a whole component of the same shape)."""
    spans = text_spans(raw)
    if spans is None:raise ValueError('不是 JSON 文字元件')
    if how[0] == 'piece':
        start, end, _ = spans[how[1]]
        return raw[:start] + json.dumps(text, ensure_ascii=False) + raw[end:]
    if blank_words(text) != blank_words(raw):raise ValueError('譯文改動了文字元件的格式')
    values = [v for _, _, v in text_spans(text)]
    out = []; last = 0
    for (start, end, _), new in zip(spans, values):out += [raw[last:start], json.dumps(new, ensure_ascii=False)]; last = end
    return ''.join(out + [raw[last:]])


# --- structure files (NBT) ------------------------------------------------------------------------------------

def nbt_strings(raw):
    from full_translation_audit import parse_binary_nbt, leaves
    return list(leaves(parse_binary_nbt(raw)))


def nbt_units(raw):
    """[(key, text, place)] of a structure file. place = (NBT path, how): how is 'plain', a component mapping, or
    ('command', unit index) for a command block's command."""
    units = []
    for path, field, value in nbt_strings(raw):
        if not isinstance(value, str) or not WORDS.search(value):continue
        keys = [p for p in path if isinstance(p, str)]
        # A book saved before 1.20.5 keeps "tag": {"title", "pages": [...]} (Pixelmon's boat_pirate journal); the
        # game's data fixer turns it into written_book_content, reading a page that is not JSON as literal text.
        old_book = 'tag' in keys and field in ('title', 'pages')
        if field in PLAIN_FIELDS or (field == 'raw' and 'title' in keys) or (old_book and field == 'title'):
            units.append((json.dumps(list(path), ensure_ascii=False), value, (path, ('plain', None))))
        elif field in JSON_FIELDS or (field == 'raw' and 'pages' in keys) or (field in ('Name', 'Lore') and 'display' in keys) or old_book:
            unit = component_unit(value)
            if unit:units.append((json.dumps(list(path), ensure_ascii=False), unit[0], (path, unit[1])))
            elif not_json(value):
                # Text that is not JSON is read as written: an old book's page ('"In the treasury…"\n\n"Let the…"',
                # Dungeons Arise), a name saved as bare words (cobblemon-additions' shopkeeper "Arborist", CTOV's
                # "[Energy Detector]"). A page stays plain text; a name is written back as a JSON string.
                units.append((json.dumps(list(path), ensure_ascii=False), value, (path, ('plain' if old_book else 'quote', None))))
        elif field == 'Command':
            for k, (text, how) in enumerate(command_units(value)):
                units.append((json.dumps(list(path) + [k], ensure_ascii=False), text, (path, ('command', k))))
    return units


def not_json(value):
    try:json.loads(value)
    except ValueError:return True
    return False


def rewrite_nbt(raw, changes):
    """`raw` with each unit {key: (expected text, new text)} replaced; fails when the file changed since the scan."""
    from full_translation_audit import rewrite_binary_nbt
    places = {key: (text, place) for key, text, place in nbt_units(raw)}
    values = {tuple(path): value for path, _, value in nbt_strings(raw)}
    replace = {}
    for key, (expected, new) in changes.items():
        if key not in places or places[key][0] != expected:raise ValueError('結構檔的文字已變動，請重新翻譯')
        safe(new)
        path, how = places[key][1]; path = tuple(path)
        old = replace.get(path, (values[path], values[path]))
        if how[0] == 'plain':value = new
        elif how[0] == 'quote':value = json.dumps(new, ensure_ascii=False)
        elif how[0] == 'command':value = put_command(old[1], how[1], new)
        else:value = put_component(old[1], how, new)
        replace[path] = (values[path], value)
    return rewrite_binary_nbt(raw, replace) if replace else raw


def safe(text):
    # NBT and class strings are Modified UTF-8: characters outside the BMP and NUL would be written differently.
    if any(ord(c) > 0xFFFF or c == '\0' for c in text):raise ValueError('譯文含有遊戲檔案無法保存的字元')


# --- functions (.mcfunction) and command block commands ---------------------------------------------------------

# SNBT keys whose quoted value is a JSON component (an item's name and lore, a book's pages, an entity's name), and
# those whose value is shown as it is (a book's title and author).
SNBT_JSON = {'custom_name', 'item_name', 'lore', 'pages', 'raw', 'CustomName', 'Name', 'Lore', 'text'}
SNBT_PLAIN = {'title', 'author'}
QUOTED = re.compile(r"""'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*\"""")


def snbt_unquote(s):
    return re.sub(r'\\(.)', r'\1', s[1:-1])


def snbt_quote(value, quote):
    return quote + value.replace('\\', '\\\\').replace(quote, '\\' + quote) + quote


def command_parts(line):
    """[(start, end, kind, raw)] of the texts of one command: the JSON of tellraw / title, and quoted SNBT values
    under the keys above (kind 'json' or 'plain'). raw is the text as the game reads it (quotes and escapes removed)."""
    parts = []
    s = line.lstrip()
    if s.startswith('#') or not s:return parts
    m = re.match(r'\s*/?(?:execute\b.*?\brun\s+)?(tellraw|title)\s+', line)
    if m:
        i = m.end()
        if line[i:i+1] == '@':
            i += 2
            if line[i:i+1] == '[':
                depth = 0
                while i < len(line):
                    depth += {'[': 1, ']': -1}.get(line[i], 0); i += 1
                    if depth == 0:break
        else:
            while i < len(line) and not line[i].isspace():i += 1
        if m[1] == 'title':
            mode = re.match(r'\s+(title|subtitle|actionbar)\b', line[i:])
            if not mode:return parts
            i += mode.end()
        body = line[i:].strip()
        if body:
            begin = line.index(body, i)
            parts.append((begin, begin + len(body), 'json', body))
        return parts
    for q in QUOTED.finditer(line):
        before = line[:q.start()].rstrip()
        key = re.search(r'([A-Za-z_:]+)\s*[:=]\s*\[?(?:\s*(?:\'(?:\\.|[^\'\\])*\'|"(?:\\.|[^"\\])*")\s*,)*\s*$', before)
        if not key:continue
        name = key[1].split(':')[-1]
        if name in SNBT_JSON:parts.append((q.start(), q.end(), 'json', snbt_unquote(q[0])))
        elif name in SNBT_PLAIN:parts.append((q.start(), q.end(), 'plain', snbt_unquote(q[0])))
    return parts


def command_units(line):
    """[(text, how)] of one command line, in order (see command_parts)."""
    units = []
    for start, end, kind, raw in command_parts(line):
        if kind == 'plain':
            if WORDS.search(raw):units.append((raw, (start, 'plain', None)))
            continue
        unit = component_unit(raw)
        if unit:units.append((unit[0], (start, unit[1][0], unit[1][1])))
    return units


def put_command(line, index, text):
    """The command line with unit `index` replaced by `text`."""
    parts = {start: (end, kind, raw) for start, end, kind, raw in command_parts(line)}
    _, (start, mode, piece) = command_units(line)[index]
    end, kind, raw = parts[start]
    new = text if mode == 'plain' else put_component(raw, (mode, piece), text)
    body = line[start:end]
    if body[:1] in ('"', "'") and (kind == 'plain' or body != raw):new = snbt_quote(new, body[0])
    return line[:start] + new + line[end:]


def function_units(text):
    units = []
    for n, line in enumerate(text.split('\n')):
        for k, (value, _) in enumerate(command_units(line)):units.append((json.dumps([n, k]), value, (n, k)))
    return units


def rewrite_function(text, changes):
    lines = text.split('\n'); places = {key: (value, place) for key, value, place in function_units(text)}
    for key, (expected, new) in sorted(changes.items(), key=lambda x: json.loads(x[0]), reverse=True):
        if key not in places or places[key][0] != expected:raise ValueError('函式檔的文字已變動，請重新翻譯')
        n, k = places[key][1]
        lines[n] = put_command(lines[n], k, new)
    return '\n'.join(lines)


# --- loot tables -----------------------------------------------------------------------------------------------

class _Str(str):
    """A JSON string value that remembers where it sits in the file (plain_loot_spans)."""


def _positioned(raw):
    """The JSON value of `raw` with every string a _Str carrying .start and .end; raises ValueError when not JSON."""
    i = [0]; n = len(raw)

    def skip():
        while i[0] < n and raw[i[0]] in ' \t\r\n':i[0] += 1

    def value():
        skip()
        if i[0] >= n:raise ValueError('unexpected end')
        c = raw[i[0]]
        if c == '"':
            start = i[0]; i[0] += 1
            while i[0] < n and raw[i[0]] != '"':i[0] += 2 if raw[i[0]] == '\\' else 1
            if i[0] >= n:raise ValueError('unterminated string')
            i[0] += 1
            s = _Str(json.loads(raw[start:i[0]])); s.start, s.end = start, i[0]
            return s
        if c in '{[':
            i[0] += 1; skip(); close = '}' if c == '{' else ']'
            out = {} if c == '{' else []
            if raw[i[0]] == close:i[0] += 1;return out
            while True:
                if c == '{':
                    key = value(); skip()
                    if raw[i[0]] != ':':raise ValueError('expected :')
                    i[0] += 1; out[str(key)] = value()
                else:out.append(value())
                skip()
                if raw[i[0]] == ',':i[0] += 1;continue
                if raw[i[0]] == close:i[0] += 1;return out
                raise ValueError('bad JSON')
        m = re.compile(r'-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null').match(raw, i[0])
        if not m:raise ValueError('bad JSON value')
        i[0] = m.end()
        return None

    found = value(); skip()
    if i[0] != n:raise ValueError('trailing data')
    return found


def plain_loot_spans(raw):
    """(start, end, value) of item names and lore written as plain strings, in file order: the vanilla set_name
    function's "name": "§7Brock's Gym" and set_lore's "lore": ["…"]. A plain string is a literal text component, shown
    as written (VillagerConfig trades hand these functions to vanilla loot, COBBLEVERSE kanto_cartographer); the item
    entry's own "name" (minecraft:map) is an id and is never one of them."""
    try:tree = _positioned(raw)
    except (ValueError, IndexError):return []
    spans = []

    def walk(node):
        if isinstance(node, dict):
            function = str(node.get('function') or '').removeprefix('minecraft:')
            if function == 'set_name' and isinstance(node.get('name'), _Str):spans.append(node['name'])
            if function == 'set_lore' and isinstance(node.get('lore'), list):
                spans.extend(x for x in node['lore'] if isinstance(x, _Str))
            # An advancement's "display": {"title": "Blinded by the lights"} (Beautify 2.0.2, VEFV2.7.1): a plain string
            # is a literal component, as with set_name.
            display = node.get('display')
            if isinstance(display, dict) and ('icon' in display or 'frame' in display):
                spans.extend(display[k] for k in ('title', 'description') if isinstance(display.get(k), _Str))
            for x in node.values():walk(x)
        elif isinstance(node, list):
            for x in node:walk(x)
    walk(tree)
    return sorted(((s.start, s.end, str(s)) for s in spans), key=lambda x: x[0])


def loot_units(raw):
    """[(key, text, index)]: each "text" value of the components a loot table gives its items (set_name, set_lore)
    or an advancement shows (display title and description), one piece at a time, so the rest of the file keeps its
    bytes. Components written as a language key ("translate") have no words here. Names and lore written as plain
    strings follow with keys ["plain", n], so the keys of the "text" pieces stay what earlier runs wrote."""
    if not LOOT_WORDS.search(raw):return []
    spans = text_spans(raw)
    units = [(json.dumps([k]), v, k) for k, (_, _, v) in enumerate(spans or []) if WORDS.search(v)]
    return units + [(json.dumps(['plain', k]), v, ('plain', k)) for k, (_, _, v) in enumerate(plain_loot_spans(raw))
                    if WORDS.search(v)]


def rewrite_loot(raw, changes):
    spans = text_spans(raw) or []; plain = plain_loot_spans(raw)
    places = {key: (text, k) for key, text, k in loot_units(raw)}
    edits = {}
    for key, (expected, new) in changes.items():
        if key not in places or places[key][0] != expected:raise ValueError('戰利品表的文字已變動，請重新翻譯')
        k = places[key][1]
        start, end, _ = plain[k[1]] if isinstance(k, tuple) else spans[k]
        edits[start] = (end, new)
    out = []; last = 0
    for start in sorted(edits):
        end, new = edits[start]
        out += [raw[last:start], json.dumps(new, ensure_ascii=False)]; last = end
    return ''.join(out + [raw[last:]])


# --- Radical Cobblemon Trainers: trainer names ---------------------------------------------------------------------

# RCT 0.18 shows a trainer's "name" through rctapi Text.getComponent: Component.literal unless the name is written as
# {"translatable": key}. A plain string or {"literal": ...} is shown as written above the trainer and in battle.
RCT_TRAINER = re.compile(r'(?:^|/)data/rctmod/trainers/.+\.json$')
STRING = r'"(?:\\.|[^"\\])*"'


def trainer_span(raw):
    """(start, end, name) of a trainer file's shown name, or None (no name, or one written as a language key)."""
    try:name = json.loads(raw).get('name')
    except (ValueError, AttributeError):return None
    m = re.search(r'"name"\s*:\s*(' + STRING + r'|\{[^{}]*\})', raw)
    if not m:return None
    if isinstance(name, str):
        if json.loads(m[1]) != name:return None
        return m.start(1), m.end(1), name
    if isinstance(name, dict) and isinstance(name.get('literal'), str) and not name.get('translatable'):
        inner = re.search(r'"literal"\s*:\s*(' + STRING + ')', m[1])
        if inner and json.loads(inner[1]) == name['literal']:
            return m.start(1) + inner.start(1), m.start(1) + inner.end(1), name['literal']
    return None


def trainer_units(raw):
    span = trainer_span(raw)
    return [('["name"]', span[2], span)] if span and WORDS.search(span[2]) else []


def rewrite_trainer(raw, changes):
    units = {key: (text, span) for key, text, span in trainer_units(raw)}
    for key, (expected, new) in changes.items():
        if key not in units or units[key][0] != expected:raise ValueError('訓練家資料的名稱已變動，請重新翻譯')
        start, end, _ = units[key][1]
        raw = raw[:start] + json.dumps(new, ensure_ascii=False) + raw[end:]
    return raw


# --- FancyMenu layouts -------------------------------------------------------------------------------------------

# FancyMenu draws a layout's button labels, their hover descriptions and the text of a text element (source_mode =
# direct) as written in config/fancymenu/customization/*.txt: no language key, whatever the game's language
# (COBBLEVERSE's "Start a Server"): English is translated, Simplified Chinese converted, both written in place. The
# config reader leaves these files to this one, so a translated line is the same row on a rerun.
FANCYMENU = re.compile(r'(?:^|/)config/fancymenu/customization/[^/]+\.txt$', re.I)
FANCYMENU_FIELDS = {'label', 'hoverlabel', 'hover_label', 'description', 'tooltip', 'text', 'title'}
FANCYMENU_FILE = re.compile(r'\.(?:png|jpe?g|gif|webp|txt|md|json|ogg|mp4|apng)\b', re.I)
FANCYMENU_LINE = re.compile(r'^(\s*)([A-Za-z_]+)(\s*=\s*)(.*?)\s*$')
# What a translation must keep of a FancyMenu text: placeholders ({"placeholder":"loadedmods"}), colour and line
# codes (%#FF5555%, %#%, %n%), markdown link targets ((click:open_changelogs)) and resource sources ([source:local]).
FANCYMENU_MARK = re.compile(r'%!![^%]*%[^%]*%!!%|\{"placeholder".*?\}(?:\})*|%#?[0-9A-Fa-f]{0,8}%|%n%|\]\([^)]*\)|\[source:[^\]]*\]')


def fancymenu_marks(text):
    return sorted(FANCYMENU_MARK.findall(text or ''))


def fancymenu_units(text):
    """[(key, text, (start, end))] of the shown words of a FancyMenu layout, keyed by line number. A source is shown
    text in a text element (source_mode = direct), or Chinese of an older layout; a picture's source never is."""
    lines = text.splitlines(True); starts = [0]
    for line in lines: starts.append(starts[-1] + len(line))
    blocks = []; current = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.endswith('{'): current = []; blocks.append(current); continue
        if s == '}': current = None; continue
        m = FANCYMENU_LINE.match(line.rstrip('\r\n'))
        if m and current is not None: current.append((i, m))
    found = []
    for block in blocks:
        direct = any(m[2] == 'source_mode' and m[4] == 'direct' for _, m in block)
        for i, m in block:
            field, value = m[2], m[4]
            if not (field in FANCYMENU_FIELDS or (field == 'source' and (direct or HAN.search(value)))):continue
            # A placeholder's own arguments are not the value (Pixelmon: "Latest Pixelmon: {…"source":"…/update.json"}").
            if (value.startswith('[source:') or re.match(r'(?i)https?://', value)
                    or (field == 'source' and FANCYMENU_FILE.search(FANCYMENU_MARK.sub(' ', value)))):continue
            # Words a player reads once the marks are taken out (a version line of placeholders only is not).
            if not WORDS.search(FANCYMENU_MARK.sub(' ', value)):continue
            start = starts[i] + m.start(4)
            found.append((str(i + 1), value, (start, start + len(value))))
    return found


def rewrite_fancymenu(text, changes):
    units = {key: (value, span) for key, value, span in fancymenu_units(text)}
    for key, (expected, new) in sorted(changes.items(), key=lambda kv: -units.get(kv[0], (None, (0, 0)))[1][0]):
        if key not in units or units[key][0] != expected:raise ValueError('FancyMenu 版面的文字已變動，請重新翻譯')
        if '\n' in new or '\r' in new or fancymenu_marks(new) != fancymenu_marks(expected):
            raise ValueError('譯文改動了 FancyMenu 的換行、顏色或佔位符')
        start, end = units[key][1]
        text = text[:start] + new + text[end:]
    return text


# --- REI custom collapsible groups -----------------------------------------------------------------------------------

# REI 16 (CollapsibleEntryRegistryImpl) turns each custom group's "name" into Component.literal: the title shown over a
# collapsed stack. The group is known by its "id" (custom:<uuid>), so the name is words only (COBBLEVERSE: 271 groups).
REI_GROUPS = re.compile(r'(?:^|/)config/roughlyenoughitems/collapsible\.json5?$')


def rei_spans(raw):
    """(start, end, value) of each custom group's name; [] when the file is not plain JSON (json5 comments)."""
    try:tree = _positioned(raw)
    except (ValueError, IndexError):return []
    groups = tree.get('customGroups') if isinstance(tree, dict) else None
    return [(g['name'].start, g['name'].end, str(g['name'])) for g in groups or []
            if isinstance(g, dict) and isinstance(g.get('name'), _Str)]


def rei_units(raw):
    return [(json.dumps(['customGroups', k, 'name']), v, k) for k, (_, _, v) in enumerate(rei_spans(raw)) if WORDS.search(v)]


def rewrite_rei(raw, changes):
    spans = rei_spans(raw); places = {key: (text, k) for key, text, k in rei_units(raw)}
    out = []; last = 0
    for key, (expected, new) in sorted(changes.items(), key=lambda x: places.get(x[0], ('', -1))[1]):
        if key not in places or places[key][0] != expected:raise ValueError('REI 分組名稱已變動，請重新翻譯')
        start, end, _ = spans[places[key][1]]
        out += [raw[last:start], json.dumps(new, ensure_ascii=False)]; last = end
    return ''.join(out + [raw[last:]])


# --- one entry point ---------------------------------------------------------------------------------------------

def units(name, raw):
    """[(key, text)] of a data-pack file (bytes), [] for other files; raises ValueError on an unreadable file."""
    if STRUCTURE.search(name):return [(k, t) for k, t, _ in nbt_units(raw)]
    if FUNCTION.search(name):return [(k, t) for k, t, _ in function_units(raw.decode('utf-8-sig'))]
    if LOOT.search(name):return [(k, t) for k, t, _ in loot_units(raw.decode('utf-8-sig'))]
    if RCT_TRAINER.search(name):return [(k, t) for k, t, _ in trainer_units(raw.decode('utf-8-sig'))]
    if FANCYMENU.search(name):return [(k, t) for k, t, _ in fancymenu_units(raw.decode('utf-8-sig'))]
    if REI_GROUPS.search(name):return [(k, t) for k, t, _ in rei_units(raw.decode('utf-8-sig'))]
    return []


def rewrite(name, raw, changes):
    """The file with {key: (expected, new)} written in; the same bytes when nothing changes."""
    if not changes:return raw
    for _, new in changes.values():safe(new)
    if STRUCTURE.search(name):return rewrite_nbt(raw, changes)
    text = raw.decode('utf-8-sig'); bom = raw.startswith(b'\xef\xbb\xbf')
    if FUNCTION.search(name):out = rewrite_function(text, changes)
    elif LOOT.search(name):out = rewrite_loot(text, changes)
    elif RCT_TRAINER.search(name):out = rewrite_trainer(text, changes)
    elif FANCYMENU.search(name):out = rewrite_fancymenu(text, changes)
    elif REI_GROUPS.search(name):out = rewrite_rei(text, changes)
    else:raise ValueError('不支援的檔案：' + name)
    return (b'\xef\xbb\xbf' if bom else b'') + out.encode('utf-8')
