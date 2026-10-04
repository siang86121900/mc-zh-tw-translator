"""The game's multiplayer server list (servers.dat), so a translation card can add the translator's server.

servers.dat is uncompressed NBT: a root compound holding a list "servers" of compounds with "name" and "ip"
(plus "icon", "acceptTextures", "hidden"). Everything is read into tagged values and written back the same
way, so the servers already listed (a modpack's own list, with icons) stay byte for byte.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

FILE = 'servers.dat'
DEFAULT_PORT = 25565
MAX_NAME = 32
ADDRESS = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?')
MAX_DEPTH = 64
END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTES, STRING, LIST, COMPOUND, INTS, LONGS = range(13)
FIXED = {BYTE: '>b', SHORT: '>h', INT: '>i', LONG: '>q', FLOAT: '>f', DOUBLE: '>d'}


def checked(server):
    """The server a catalog card names, as (name, address), or None when it is missing or not a plain address."""
    if not isinstance(server, dict):return None
    name, address = str(server.get('name') or '').strip(), str(server.get('address') or '').strip()
    if not name or len(name) > MAX_NAME or any(ord(c) < 32 or c in '§\x7f' for c in name):return None
    if not ADDRESS.fullmatch(address):return None
    port = address.rpartition(':')[2] if ':' in address else str(DEFAULT_PORT)
    if not 0 < int(port) < 65536:return None
    return name, address


def same_address(a: str, b: str) -> bool:
    def norm(x):
        host, _, port = x.strip().lower().partition(':')
        return host.rstrip('.'), int(port or DEFAULT_PORT)
    try:return norm(a) == norm(b)
    except ValueError:return False


class Reader:
    def __init__(self, raw):self.raw = raw;self.at = 0

    def take(self, n):
        if n < 0 or self.at+n > len(self.raw):raise ValueError('servers.dat 內容不完整')
        part = self.raw[self.at:self.at+n];self.at += n
        return part

    def unpack(self, fmt):return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def text(self):return self.take(self.unpack('>H'))  # kept as raw (modified UTF-8) bytes

    def value(self, kind, depth=0):
        if depth > MAX_DEPTH:raise ValueError('servers.dat 層數過多')
        if kind in FIXED:return self.unpack(FIXED[kind])
        if kind == BYTES:return self.take(self.unpack('>i'))
        if kind == STRING:return self.text()
        if kind == LIST:
            inner = self.unpack('>b');count = self.unpack('>i')
            return (inner, [self.value(inner, depth+1) for _ in range(max(0, count))])
        if kind == COMPOUND:
            items = []
            while (tag := self.unpack('>b')) != END:
                items.append((tag, self.text(), self.value(tag, depth+1)))
            return items
        if kind in (INTS, LONGS):
            count = self.unpack('>i');size = 4 if kind == INTS else 8
            return self.take(count*size)
        raise ValueError('servers.dat 有不認得的資料類型')


def read(raw: bytes):
    """(root name, root compound items); raises ValueError for anything that is not a servers.dat."""
    r = Reader(raw)
    if r.unpack('>b') != COMPOUND:raise ValueError('servers.dat 格式不對')
    name = r.text();items = r.value(COMPOUND)
    if r.at != len(raw):raise ValueError('servers.dat 結尾有多餘資料')
    return name, items


def write_value(kind, value, out):
    if kind in FIXED:out.append(struct.pack(FIXED[kind], value))
    elif kind == BYTES:out.append(struct.pack('>i', len(value)));out.append(value)
    elif kind == STRING:out.append(struct.pack('>H', len(value)));out.append(value)
    elif kind == LIST:
        inner, values = value;out.append(struct.pack('>bi', inner, len(values)))
        for v in values:write_value(inner, v, out)
    elif kind == COMPOUND:
        for tag, name, v in value:
            out.append(struct.pack('>bH', tag, len(name)));out.append(name);write_value(tag, v, out)
        out.append(b'\x00')
    elif kind in (INTS, LONGS):out.append(struct.pack('>i', len(value)//(4 if kind == INTS else 8)));out.append(value)


def write(name: bytes, items) -> bytes:
    out = [struct.pack('>bH', COMPOUND, len(name)), name]
    write_value(COMPOUND, items, out)
    return b''.join(out)


def java_utf(text: str) -> bytes:
    """Java's modified UTF-8: NUL and characters outside the BMP are written as Java would."""
    out = bytearray()
    for unit in struct.unpack(f'>{len(text.encode("utf-16-be"))//2}H', text.encode('utf-16-be')):
        if 0 < unit < 0x80:out.append(unit)
        elif unit < 0x800:out += bytes((0xC0 | unit >> 6, 0x80 | unit & 0x3F))
        else:out += bytes((0xE0 | unit >> 12, 0x80 | unit >> 6 & 0x3F, 0x80 | unit & 0x3F))
    return bytes(out)


def entries(raw: bytes):
    """[(name, address)] of the listed servers, for reports and tests."""
    _, items = read(raw)
    found = next((v for t, n, v in items if t == LIST and n == b'servers'), (COMPOUND, []))
    result = []
    for server in found[1] if found[0] == COMPOUND else []:
        fields = {n: v for t, n, v in server if t == STRING}
        result.append((fields.get(b'name', b'').decode('utf-8', 'replace'), fields.get(b'ip', b'').decode('utf-8', 'replace')))
    return result


def with_server(raw: bytes | None, name: str, address: str) -> bytes | None:
    """servers.dat with the server first in the list; None when that address is already listed."""
    root, items = read(raw) if raw else (b'', [])
    at = next((i for i, (t, n, _) in enumerate(items) if n == b'servers'), None)
    if at is not None and (items[at][0] != LIST or items[at][2][0] not in (COMPOUND, END)):
        raise ValueError('servers.dat 的伺服器清單格式不對')
    servers = list(items[at][2][1]) if at is not None else []
    for server in servers:
        ip = next((v for t, n, v in server if t == STRING and n == b'ip'), b'')
        if same_address(ip.decode('utf-8', 'replace'), address):return None
    # First, where the player looks; the modpack's own servers follow unchanged.
    servers.insert(0, [(STRING, b'ip', java_utf(address)), (STRING, b'name', java_utf(name))])
    items = list(items)
    if at is None:items.append((LIST, b'servers', (COMPOUND, servers)))
    else:items[at] = (LIST, b'servers', (COMPOUND, servers))
    return write(root, items)


def server_record(instance: Path, staged: Path, server, file_hash):
    """The apply_reviewed record adding the card's server to this instance's list; None when nothing changes."""
    found = checked(server)
    if not found:return None
    src = Path(instance)/FILE
    raw = src.read_bytes() if src.is_file() else None
    new = with_server(raw, *found)
    if new is None:return None
    dst = Path(staged)/FILE;dst.write_bytes(new)
    return dict(file=FILE, before=file_hash(src) if raw is not None else None, after=file_hash(dst), reviewed=True, verified=True)
