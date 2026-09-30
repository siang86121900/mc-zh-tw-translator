"""Conservative JVM display-string proofs; never execute classes from a mod.

Only straight-line literal calls and compiler-generated String[] comment calls
are supported. Every use of a shared constant must have the same safe proof.
"""
import re
import struct


def u2(b, p):
    return struct.unpack_from('>H', b, p)[0]


def decode_mutf(b):
    return b.replace(b'\xc0\x80', b'\x00').decode('utf-8', 'surrogatepass').encode('utf-16', 'surrogatepass').decode('utf-16')


def encode_mutf(s):
    units = s.encode('utf-16-be')
    return ''.join(chr(u2(units, i)) for i in range(0, len(units), 2)).encode('utf-8', 'surrogatepass').replace(b'\x00', b'\xc0\x80')


class ClassFile:
    def __init__(self, raw):
        if raw[:4] != b'\xca\xfe\xba\xbe':
            raise ValueError('不是 Java class')
        self.raw = raw
        self.cp = {}; self.spans = {}; self.utf = {}; self.codes = []; self.metadata = []
        p = 10; k = 1
        while k < u2(raw, 8):
            start = p; tag = raw[p]; p += 1
            if tag == 1:
                size = u2(raw, p); p += 2
                self.utf[k] = decode_mutf(raw[p:p+size]); p += size
                value = self.utf[k]
            else:
                size = {3:4,4:4,5:8,6:8,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}[tag]
                value = raw[p:p+size]; p += size
            self.cp[k] = (tag, value); self.spans[k] = (start, p)
            k += 2 if tag in (5, 6) else 1
        self.tail = p
        p += 6
        p += 2 + 2*u2(raw, p)
        for member_kind in range(2):
            count = u2(raw, p); p += 2
            for _ in range(count):
                flags,name,desc = struct.unpack_from('>HHH',raw,p)
                private_constant = member_kind == 0 and flags & 0x1a == 0x1a and self.utf[desc] == 'Ljava/lang/String;'
                # A private compile-time constant can accompany inlined ldc uses. Any field access
                # defeats this proof; public/protected constants remain untouched.
                private_constant &= not any(t == 9 and u2(self.cp[u2(v,2)][1],0) == name for t,v in self.cp.values())
                self.metadata.append(raw[p+2:p+6]); p += 6
                p = self.attributes(p, private_constant)
        p = self.attributes(p)
        if p != len(raw):raise ValueError('class 長度不符')

    def attributes(self, p, private_constant=False):
        raw = self.raw; count = u2(raw, p); p += 2
        for _ in range(count):
            name = self.utf[u2(raw, p)]; size = struct.unpack_from('>I', raw, p+2)[0]
            p += 6; end = p+size
            if end > len(raw):raise ValueError('class 屬性截斷')
            if name == 'Code':
                length = struct.unpack_from('>I', raw, p+4)[0]
                code = raw[p+8:p+8+length]; q = p+8+length
                handlers = u2(raw, q); q += 2
                targets = {u2(raw, q+i*8+4) for i in range(handlers)}
                self.codes.append((code, targets))
                if self.attributes(q+handlers*8) != end:raise ValueError('Code 長度不符')
            elif name == 'ConstantValue' and private_constant:
                if size != 2:raise ValueError('ConstantValue 長度不符')
            elif name not in ('LineNumberTable','LocalVariableTable','LocalVariableTypeTable','StackMapTable','SourceFile',
                              'InnerClasses','EnclosingMethod','NestHost','NestMembers','PermittedSubclasses','Exceptions'):
                self.metadata.append(raw[p:end])
            p = end
        return p

    def method(self, index):
        tag, value = self.cp[index]
        if tag not in (10, 11):return None
        owner = self.utf[u2(self.cp[u2(value, 0)][1], 0)]
        pair = self.cp[u2(value, 2)][1]
        return owner, self.utf[u2(pair, 0)], self.utf[u2(pair, 2)]


def instructions(code):
    p = 0
    while p < len(code):
        start = p; op = code[p]; p += 1
        if op in (170, 171):
            p = (p+3)&~3
            if op == 170:
                low, high = struct.unpack_from('>ii', code, p+4)
                if not 0 <= high-low <= len(code):raise ValueError('tableswitch')
                p += 12+4*(high-low+1)
            else:
                count = struct.unpack_from('>i', code, p+4)[0]
                if not 0 <= count <= len(code):raise ValueError('lookupswitch')
                p += 8+8*count
        elif op == 196:p += 5 if code[p] == 132 else 3
        elif op in (16,18,188) or 21 <= op <= 25 or 54 <= op <= 58 or op == 169:p += 1
        elif op in (17,19,20,132) or 153 <= op <= 168 or 178 <= op <= 184 or op in (187,189,192,193,198,199):p += 2
        elif op == 197:p += 3
        elif op in (185,186,200,201):p += 4
        elif op > 201:raise ValueError('未知位元碼')
        if p > len(code):raise ValueError('位元碼截斷')
        yield start, op, code[start+1:p]


BUILDERS = {'net/minecraftforge/common/ForgeConfigSpec$Builder',
            'net/neoforged/neoforge/common/ModConfigSpec$Builder'}


def sink(method, array=False):
    if not method:return None
    owner, name, desc = method
    if owner in BUILDERS and name == 'comment' and desc == ('([Ljava/lang/String;)' if array else '(Ljava/lang/String;)')+'L'+owner+';':
        return '設定說明'
    literals = {('net/minecraft/network/chat/Component','literal'),
                ('net/minecraft/network/chat/Component','m_237113_'),
                ('net/minecraft/text/Text','literal'),('net/minecraft/class_2561','method_43470')}
    returns = {'net/minecraft/network/chat/MutableComponent','net/minecraft/text/MutableText','net/minecraft/class_5250'}
    if not array and (owner,name) in literals and desc in {'(Ljava/lang/String;)L'+r+';' for r in returns}:return '玩家顯示文字'
    return None


def branch_targets(code, ops, handlers):
    targets = set(handlers)
    for pos, op, arg in ops:
        if 153 <= op <= 168 or op in (198,199):targets.add(pos+struct.unpack('>h',arg)[0])
        elif op in (200,201):targets.add(pos+struct.unpack('>i',arg)[0])
        elif op in (170,171):
            q = (pos+4)&~3
            targets.add(pos+struct.unpack_from('>i',code,q)[0])
            if op == 170:
                low,high = struct.unpack_from('>ii',code,q+4)
                targets.update(pos+struct.unpack_from('>i',code,q+12+4*i)[0] for i in range(high-low+1))
            else:
                count = struct.unpack_from('>i',code,q+4)[0]
                targets.update(pos+struct.unpack_from('>i',code,q+12+8*i)[0] for i in range(count))
    return targets


def comment_loads(cf, ops, i, targets):
    """Op indices of the ldc instructions whose strings the comment call at ops[i] receives, in order; None if unproven."""
    method = cf.method(u2(ops[i][2],0))
    if sink(method):
        return [i-1] if i and ops[i-1][1] in (18,19) and ops[i][0] not in targets else None
    if not sink(method,True):return None
    # javac varargs: count, anewarray String, (dup, index, ldc, aastore)*, comment.
    j = i-1; loads = []
    while j >= 3 and ops[j][1] == 83 and ops[j-1][1] in (18,19) and ops[j-3][1] == 89:
        if integer(ops[j-2]) is None:break
        loads.append((j-1,integer(ops[j-2]))); j -= 4
    if j >= 1 and ops[j][1] == 189 and cf.utf.get(u2(cf.cp[u2(ops[j][2],0)][1],0)) == 'java/lang/String':
        count = integer(ops[j-1])
        if count == len(loads) and [n for _,n in reversed(loads)] == list(range(count)) and not any(x[0] in targets for x in ops[j:i+1]):
            return [idx for idx,_ in reversed(loads)]
    return None


def proven_strings(raw):
    cf = ClassFile(raw)
    strings = {k:u2(v,0) for k,(t,v) in cf.cp.items() if t == 8}
    uses = {k:[] for k in strings}
    for code, handlers in cf.codes:
        ops = list(instructions(code)); targets = branch_targets(code, ops, handlers)
        safe = {}
        for i, (pos,op,arg) in enumerate(ops):
            if op in (182,183,184,185):
                method = cf.method(u2(arg,0))
                reason = sink(method)
                if reason and i and ops[i-1][1] in (18,19) and pos not in targets:safe[i-1] = reason
                if sink(method,True):safe.update({idx:'設定說明' for idx in comment_loads(cf,ops,i,targets) or []})
        for i,(_,op,arg) in enumerate(ops):
            if op in (18,19):
                index = arg[0] if op == 18 else u2(arg,0)
                if index in strings:uses[index].append(safe.get(i))
    result = {}
    for index, utf in strings.items():
        shared = [k for k,v in strings.items() if v == utf]
        all_uses = [x for k in shared for x in uses[k]]
        # Constants in annotations/fields/bootstrap arguments or another pool role are not display-only.
        protected = any(struct.pack('>H',k) in b for k in [utf]+shared for b in cf.metadata)
        protected |= any(t != 8 and t in (7,12,16,19,20) and struct.pack('>H',utf) in v for t,v in cf.cp.values())
        if all_uses and all(all_uses) and not protected:
            result[utf] = (cf.utf[utf], '、'.join(sorted(set(all_uses))))
    return cf, result


DEFINES = ('define','defineInRange','defineList','defineListAllowEmpty','defineEnum','defineInList')
RELOAD = {25,42,43,44,45,178,180,87}  # aload(_n), getstatic, getfield, pop: the builder put back on the stack


def config_tooltips(raw):
    """Where config screens can show a Chinese version of each proven comment string, without touching the class.

    NeoForge's own config screen and Configured (Forge and NeoForge) look up '<key>.tooltip' in the language
    files before showing a value's comment. <key> is what the mod passed to Builder.translation(); without
    one, NeoForge's screen uses '<modid>.configuration.<value name>' and Configured shows only the comment.
    Only straight-line chains comment → [translation / restart flags] → define("name", ...) are read.

    Returns {UTF-8 constant index (the row key proven_strings uses): [(kind, text, part, parts)]}: kind 'key' with the mod's translation key,
    or 'name' with the value name the caller combines with the mod id. A comment given as several strings
    is shown joined with newlines; part is this string's place among them.
    """
    cf = ClassFile(raw); result = {}
    for code, handlers in cf.codes:
        ops = list(instructions(code)); targets = branch_targets(code, ops, handlers)
        pending = None  # [comment ldc op indices, translation key, op index after the last builder call]
        for i, (pos,op,arg) in enumerate(ops):
            if pos in targets:pending = None
            if op not in (182,183,184,185):continue
            method = cf.method(u2(arg,0))
            if not method or method[0] not in BUILDERS:continue
            owner, name, desc = method
            if name == 'comment':
                loads = comment_loads(cf, ops, i, targets)
                pending = [loads, None, i+1] if loads else None
            elif pending and name == 'translation' and desc == '(Ljava/lang/String;)L'+owner+';' and ops[i-1][1] in (18,19) and i-1 >= pending[2]:
                pending[1] = cf.utf[u2(cf.cp[ldc_index(ops[i-1])][1],0)]; pending[2] = i+1
            elif pending and name in ('worldRestart','gameRestart') and desc == '()L'+owner+';':
                pending[2] = i+1
            elif pending and name in DEFINES and desc.startswith('(Ljava/lang/String;'):
                # The value name is the first argument: the constant loaded right after the builder is back on the stack.
                j = pending[2]
                while j < i and ops[j][1] in RELOAD:j += 1
                if j < i and ops[j][1] in (18,19) and cf.cp[ldc_index(ops[j])][0] == 8:
                    value = cf.utf[u2(cf.cp[ldc_index(ops[j])][1],0)]
                    entry = ('key', pending[1]) if pending[1] else ('name', value)
                    loads = pending[0]
                    for part, k in enumerate(loads):
                        result.setdefault(u2(cf.cp[ldc_index(ops[k])][1],0), []).append((*entry, part, len(loads)))
                pending = None
            else:
                pending = None  # push (a section), a List-path define or anything else: not a proven value comment
    return result


def ldc_index(op):
    _,code,arg = op
    return arg[0] if code == 18 else u2(arg,0)


def integer(op):
    _,code,arg = op
    if 3 <= code <= 8:return code-3
    if code == 16:return struct.unpack('>b',arg)[0]
    if code == 17:return struct.unpack('>h',arg)[0]
    return None


def rewrite(raw, rows):
    cf, safe = proven_strings(raw); edits = {}
    for row in rows:
        index = int(row['key'])
        if index not in safe or safe[index][0] != row['current']:raise ValueError('程式文字用途或原文已變動，請重新翻譯')
        value = row['proposed']
        if re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value) != re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',row['current']):raise ValueError('程式文字控制字元不一致')
        encoded = encode_mutf(value)
        if len(encoded)>65535:raise ValueError('程式文字超過 Java 長度限制')
        edits[index] = b'\x01'+struct.pack('>H',len(encoded))+encoded
    parts = [raw[:10]]
    for k,(start,end) in cf.spans.items():parts.append(edits.get(k,raw[start:end]))
    parts.append(raw[cf.tail:]); output = b''.join(parts)
    checked, _ = proven_strings(output)
    if output[checked.tail:] != raw[cf.tail:] or any(checked.utf[k] != r['proposed'] for r in rows for k in [int(r['key'])]):raise ValueError('程式文字寫回驗證失敗')
    return output


def check_java(classes):
    """Parse only staged, changed classes with Java; a JDK is not required."""
    import base64
    import subprocess
    import tempfile
    from pathlib import Path
    from .verifier import _java_executable
    from .class_text_check import CLASS_BYTES
    java = _java_executable()
    if not java:raise ValueError('找不到 Java，無法驗證設定說明與程式顯示文字；譯文已保存，請安裝模組包需要的 Java 後重試套用。')
    with tempfile.TemporaryDirectory(prefix='mctranslator-class-') as folder:
        root = Path(folder)
        (root/'ClassTextCheck.class').write_bytes(base64.b64decode(CLASS_BYTES))
        paths = []
        for i,content in enumerate(classes):
            p=root/f'check-{i}.class';p.write_bytes(content);paths.append(str(p.resolve()))
        (root/'paths.txt').write_text('\n'.join(paths),encoding='utf-8')
        try:
            proc=subprocess.run([java,'-cp',str(root),'ClassTextCheck',str(root/'paths.txt')],
                                capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise ValueError('Java 未能完成程式文字驗證；譯文已保留，遊戲檔案尚未修改。') from exc
        if proc.returncode:raise ValueError('程式文字未通過 Java 格式驗證；譯文已保留，遊戲檔案尚未修改。')
