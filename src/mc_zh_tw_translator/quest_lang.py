"""FTB Quests language files (config/ftbquests/quests/lang/<locale>.snbt).

FTB Quests 2001+ keeps quest text out of the chapter files in one file per language:

    {
        chapter.0A1B.title: "&lFirst Steps"
        quest.0C2D.quest_desc: [
            "Collect some wood."
            ""
            "{image:modid:textures/x.png width:50 height:50}"
        ]
    }

A value is a string or a list of strings (one per line of a quest description). Rows are flat: a
list line is `key[index]`, so every line is translated on its own and the file keeps the English
layout (images, page breaks and empty lines stay where they are). Anything else in the file
(numbers, nested compounds) is refused rather than guessed at.
"""
from __future__ import annotations

import re

KEY = re.compile(r'[A-Za-z0-9._+\-]+')
ESCAPES = {'"': '"', "'": "'", '\\': '\\', 'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f'}
QUEST_LANG = re.compile(r'(?:^|/)ftbquests/quests/lang/(en_us|zh_cn|zh_tw)\.snbt$', re.I)


def parse(text: str) -> dict:
    """key -> str | list[str], in file order. Raises ValueError on anything that is not a language table."""
    pos = 0; n = len(text)

    def skip():
        nonlocal pos
        while pos < n and (text[pos].isspace() or text[pos] == ','): pos += 1

    def string():
        nonlocal pos
        quote = text[pos]; pos += 1; out = []
        while pos < n:
            c = text[pos]
            if c == '\\':
                if pos + 1 >= n: break
                e = text[pos + 1]
                if e == 'u' and re.fullmatch(r'[0-9a-fA-F]{4}', text[pos + 2:pos + 6]):
                    out.append(chr(int(text[pos + 2:pos + 6], 16))); pos += 6; continue
                if e not in ESCAPES: raise ValueError(f'unsupported escape \\{e} at {pos}')
                out.append(ESCAPES[e]); pos += 2; continue
            if c == quote:
                pos += 1; return ''.join(out)
            out.append(c); pos += 1
        raise ValueError('unterminated string')

    skip()
    if pos >= n or text[pos] != '{': raise ValueError('quest language file must start with {')
    pos += 1; table = {}
    while True:
        skip()
        if pos >= n: raise ValueError('missing closing }')
        if text[pos] == '}':
            pos += 1; skip()
            if pos != n: raise ValueError('trailing content after }')
            return table
        if text[pos] in '"\'': key = string()
        else:
            m = KEY.match(text, pos)
            if not m: raise ValueError(f'bad key at {pos}')
            key = m[0]; pos = m.end()
        skip()
        if pos >= n or text[pos] != ':': raise ValueError(f'missing : after {key}')
        if key in table: raise ValueError(f'duplicate key {key}')
        pos += 1; skip()
        if pos < n and text[pos] in '"\'':
            table[key] = string()
        elif pos < n and text[pos] == '[':
            pos += 1; items = []
            while True:
                skip()
                if pos < n and text[pos] == ']': pos += 1; break
                if pos >= n or text[pos] not in '"\'': raise ValueError(f'{key}: list may only hold text')
                items.append(string())
            table[key] = items
        else:
            raise ValueError(f'{key}: value is not text')


def flatten(table: dict) -> dict:
    """key -> str, with list lines as key[index]."""
    flat = {}
    for key, value in table.items():
        if isinstance(value, list):
            for i, line in enumerate(value): flat[f'{key}[{i}]'] = line
        else: flat[key] = value
    return flat


def aligned(english: dict, other: dict) -> dict:
    """`other` flattened, leaving out description lines that cannot be matched to the English line by line
    (the list has a different number of lines, or the English holds a single line there)."""
    flat = {}
    for key, value in other.items():
        mine = english.get(key)
        if isinstance(value, list):
            if not isinstance(mine, list) or len(mine) != len(value): continue
            for i, line in enumerate(value): flat[f'{key}[{i}]'] = line
        elif not isinstance(mine, list):
            flat[key] = value
    return flat


def quote(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t').replace('\r', '\\r') + '"'


def dump(flat: dict, english: dict, existing: dict | None = None) -> str:
    """The zh_tw file: the English layout, each line from `flat` where known, else what the zh_tw file
    held, else the English. Keys only the existing zh_tw file has are kept after the English ones."""
    existing = existing or {}
    lines = ['{']
    order = list(english) + [k for k in existing if k not in english]
    for key in order:
        shape = english.get(key, existing.get(key))
        name = key if KEY.fullmatch(key) else quote(key)
        if isinstance(shape, list):
            old = existing.get(key) if isinstance(existing.get(key), list) else []
            count = max(len(shape), len(old) if key not in english else 0)
            values = [flat.get(f'{key}[{i}]', old[i] if i < len(old) and len(old) == len(shape) else shape[i] if i < len(shape) else old[i])
                      for i in range(count)]
            lines.append(f'\t{name}: [')
            lines += [f'\t\t{quote(v)}' for v in values]
            lines.append('\t]')
        else:
            old = existing.get(key) if isinstance(existing.get(key), str) else None
            lines.append(f'\t{name}: {quote(flat.get(key, old if old is not None else shape))}')
    lines.append('}')
    return '\n'.join(lines) + '\n'
