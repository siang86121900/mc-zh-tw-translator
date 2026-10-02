"""Conservative JVM display-string proofs; never execute classes from a mod.

Only straight-line literal calls and compiler-generated String[] comment calls
are supported. Every use of a shared constant must have the same safe proof.
"""
import collections
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
        self.cp = {}; self.spans = {}; self.utf = {}; self.codes = []; self.metadata = []; self.bootstrap = []
        # (name, descriptor) -> access flags and the index into codes (None without code), for following a
        # String handed to a method or stored in a field (JarFlow).
        self.methods = {}; self.fields = {}
        self.keys = set()  # texts handed to Component.translatable as the key (filled by proven_strings)
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
        self.access = u2(raw, p); self.name = self.utf[u2(self.cp[u2(raw, p+2)][1], 0)]
        p += 6
        p += 2 + 2*u2(raw, p)
        for member_kind in range(2):
            count = u2(raw, p); p += 2
            for _ in range(count):
                flags,name,desc = struct.unpack_from('>HHH',raw,p)
                if member_kind == 0:self.fields[self.utf[name]] = (flags, self.utf[desc])
                else:self.methods[(self.utf[name], self.utf[desc])] = (flags, len(self.codes))
                private_constant = member_kind == 0 and flags & 0x1a == 0x1a and self.utf[desc] == 'Ljava/lang/String;'
                # A private compile-time constant can accompany inlined ldc uses. Any field access
                # defeats this proof; public/protected constants remain untouched.
                private_constant &= not any(t == 9 and u2(self.cp[u2(v,2)][1],0) == name for t,v in self.cp.values())
                self.metadata.append(raw[p+2:p+6]); p += 6
                before = len(self.codes)
                p = self.attributes(p, private_constant)
                if member_kind == 1 and len(self.codes) == before:self.methods[(self.utf[name], self.utf[desc])] = (flags, None)
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
                if name == 'BootstrapMethods':
                    q = p+2
                    for _ in range(u2(raw, p)):
                        n = u2(raw, q+2); self.bootstrap.append([u2(raw, q+4+2*i) for i in range(n)]); q += 4+2*n
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


TRANSLATABLE = {('net/minecraft/network/chat/Component','translatable'),('net/minecraft/network/chat/Component','m_237115_'),
                ('net/minecraft/network/chat/Component','m_237110_'),('net/minecraft/text/Text','translatable'),
                ('net/minecraft/class_2561','method_43471'),('net/minecraft/class_2561','method_43469')}
KEY = '語系鍵'  # handed to Component.translatable: the game looks the text up as a language key


def key_sink(method):
    """Component.translatable(String) or (String, Object...): the String is a language key."""
    return bool(method) and (method[0],method[1]) in TRANSLATABLE and method[2].startswith('(Ljava/lang/String;')


def params(desc):
    """Slot sizes of a method descriptor's parameters and of its return value (0 for void)."""
    sizes = []; p = 1
    while desc[p] != ')':
        start = p
        while desc[p] == '[':p += 1
        p = desc.index(';',p)+1 if desc[p] == 'L' else p+1
        sizes.append(2 if desc[start:p] in ('J','D') else 1)
    ret = desc[p+1:]
    return sizes, 0 if ret == 'V' else 2 if ret in ('J','D') else 1


def field_size(desc):
    return 2 if desc in ('J','D') else 1


# Operand stack effect in slots (pops, pushes) of the instructions with a fixed one.
EFFECT = {0:(0,0),1:(0,1),9:(0,2),10:(0,2),14:(0,2),15:(0,2),16:(0,1),17:(0,1),18:(0,1),19:(0,1),20:(0,2),
          21:(0,1),22:(0,2),23:(0,1),24:(0,2),25:(0,1),46:(2,1),47:(2,2),48:(2,1),49:(2,2),50:(2,1),51:(2,1),52:(2,1),53:(2,1),
          54:(1,0),55:(2,0),56:(1,0),57:(2,0),58:(1,0),79:(3,0),80:(4,0),81:(3,0),82:(4,0),83:(3,0),84:(3,0),85:(3,0),86:(3,0),
          87:(1,0),88:(2,0),116:(1,1),117:(2,2),118:(1,1),119:(2,2),120:(2,1),121:(3,2),122:(2,1),123:(3,2),124:(2,1),125:(3,2),
          126:(2,1),127:(4,2),128:(2,1),129:(4,2),130:(2,1),131:(4,2),132:(0,0),133:(1,2),134:(1,1),135:(1,2),136:(2,1),137:(2,1),
          138:(2,2),139:(1,1),140:(1,2),141:(1,2),142:(2,1),143:(2,2),144:(2,1),145:(1,1),146:(1,1),147:(1,1),
          148:(4,1),149:(2,1),150:(2,1),151:(4,1),152:(4,1),187:(0,1),188:(1,1),189:(1,1),190:(1,1),193:(1,1)}
for _op in range(2,9):EFFECT[_op] = (0,1)
for _op in (11,12,13):EFFECT[_op] = (0,1)
for _op in list(range(26,30))+list(range(34,38))+list(range(42,46)):EFFECT[_op] = (0,1)
for _op in list(range(30,34))+list(range(38,42)):EFFECT[_op] = (0,2)
for _op in list(range(59,63))+list(range(67,71))+list(range(75,79)):EFFECT[_op] = (1,0)
for _op in list(range(63,67))+list(range(71,75)):EFFECT[_op] = (2,0)
for _op in range(96,116):EFFECT[_op] = (4,2) if _op % 2 else (2,1)  # i/f pop 2 push 1, l/d pop 4 push 2
DUPS = {89:(1,1),90:(2,1),91:(3,1),92:(2,2),93:(3,2),94:(4,2),95:(2,0)}  # slots touched, slots added


class JarFlow:
    """Where a String a class hands on ends up, across the classes of one mod file.

    A mod often passes its tooltip text to a helper (Cobblemon Battle Positions: createBlockItem(block, "Where your
    Pokemon spawns", ...)) that keeps it in a field and shows it with Component.literal in appendHoverText. The text
    counts as shown only when every way it can go ends in a display call: a private, static or final method of this
    mod file whose parameter is only shown, a private or compiler-made field of it that is only read to be shown.
    Anything else (a comparison, a map key, a return value, a method another mod could override) leaves it unproven.
    """
    def __init__(self, read, names):
        self.read = read; self.names = set(names); self.classes = {}; self.memo = {}; self.readers = None

    @classmethod
    def of_zip(cls, z):
        names = [n[:-6] for n in z.namelist() if n.endswith('.class')]
        return cls(lambda name:z.read(name+'.class'), names)

    def cls(self, name):
        if name not in self.names:return None
        if name not in self.classes:
            try:self.classes[name] = ClassFile(self.read(name))
            except (ValueError,KeyError,IndexError,struct.error,UnicodeError):self.classes[name] = None
        return self.classes[name]

    def ops(self, cf, index):
        code, handlers = cf.codes[index]
        return code, list(instructions(code))

    def param(self, owner, name, desc, index, static):
        """What a String parameter of a method of this mod file is used for: a set of reasons, or None."""
        key = ('param', owner, name, desc, index)
        if key in self.memo:return self.memo[key]
        self.memo[key] = None  # a cycle proves nothing
        cf = self.cls(owner); found = None
        if cf and (name, desc) in cf.methods and cf.methods[(name, desc)][1] is not None:
            sizes, _ = params(desc)
            slot = (0 if static else 1)+sum(sizes[:index])
            code, ops = self.ops(cf, cf.methods[(name, desc)][1])
            found = set()
            for i, (pos, op, arg) in enumerate(ops):
                local = arg[-1] if op in (25,58) and len(arg) == 1 else u2(arg,1) if op == 196 and len(arg) >= 3 else None
                if op == 196:op = arg[0]
                if op in (58,) and local == slot or op - 75 == slot and 75 <= op <= 78:found = None;break  # reassigned
                if op == 25 and local == slot or op - 42 == slot and 42 <= op <= 45:
                    reasons = consumer(cf, code, ops, i, self)
                    if not reasons:found = None;break
                    found |= reasons
            found = found or None
        self.memo[key] = found
        return found

    def field(self, owner, name):
        """What a String field of this mod file is read for: a set of reasons, or None."""
        key = ('field', owner, name)
        if key in self.memo:return self.memo[key]
        self.memo[key] = None
        cf = self.cls(owner); found = None
        if cf and name in cf.fields:
            flags, desc = cf.fields[name]
            # Private (nestmates included) or compiler-made (an anonymous class's captured val$...): no other mod reads it.
            if desc == 'Ljava/lang/String;' and flags & 0x1002:
                found = set()
                for reader in self.field_readers(owner, name):
                    rcf = self.cls(reader)
                    if not rcf:found = None;break
                    for index in range(len(rcf.codes)):
                        code, ops = self.ops(rcf, index)
                        for i, (pos, op, arg) in enumerate(ops):
                            if op in (178,180) and field_ref(rcf, u2(arg,0)) == (owner, name):
                                reasons = consumer(rcf, code, ops, i, self)
                                if not reasons:found = None;break
                                found |= reasons
                        if found is None:break
                    if found is None:break
                found = found or None
        self.memo[key] = found
        return found

    def field_readers(self, owner, name):
        """Classes of this mod file that name the field (its class and the nestmates that may read it)."""
        package = owner.rsplit('/',1)[0] if '/' in owner else ''
        found = []
        for other in sorted(self.names):
            if (other.rsplit('/',1)[0] if '/' in other else '') != package:continue  # private/synthetic: same package only
            cf = self.cls(other)
            if cf and any(t == 9 and field_ref(cf, k) == (owner, name) for k,(t,_) in cf.cp.items()):found.append(other)
        return found


def field_ref(cf, index):
    tag, value = cf.cp.get(index, (None, None))
    if tag != 9:return None
    owner = cf.utf[u2(cf.cp[u2(value, 0)][1], 0)]
    return owner, cf.utf[u2(cf.cp[u2(value, 2)][1], 0)]


def consumer(cf, code, ops, i, flow=None, limit=400, at=None):
    """Reasons ({'玩家顯示文字'} / {KEY}) the one-slot value ops[i] pushes is used for, or None when unproven.

    Follows the value along straight code (and unconditional jumps, as in `cond ? "Required" : "Optional"`) to the
    instruction that takes it off the stack. Branches, returns, copies of the value and unknown calls prove nothing.
    """
    at = at if at is not None else {pos:n for n,(pos,_,_) in enumerate(ops)}
    above = 0; n = i+1; steps = 0
    while n < len(ops) and steps < limit:
        steps += 1
        pos, op, arg = ops[n]
        if op == 196:
            op = arg[0]
            if op == 132:n += 1;continue
        if op in (167,200):
            target = pos+(struct.unpack('>h',arg)[0] if op == 167 else struct.unpack('>i',arg)[0])
            if target not in at:return None
            n = at[target];continue
        if op in DUPS:
            touched, added = DUPS[op]
            if above < touched:return None
            above += added;n += 1;continue
        if op == 192:
            n += 1;continue  # checkcast keeps the value where it is
        if op in EFFECT:
            pops, pushes = EFFECT[op]
        elif op in (178,179,180,181):
            ref = cf.cp[u2(arg,0)][1]; desc = cf.utf[u2(cf.cp[u2(ref,2)][1],2)]
            size = field_size(desc)
            pops, pushes = {178:(0,size),179:(size,0),180:(1,size),181:(1+size,0)}[op]
            if op in (179,181) and above < pops:
                if above != 0 or not flow:return None
                owner, name = field_ref(cf, u2(arg,0))
                return flow.field(owner, name)
        elif op in (182,183,184,185,186):
            if op == 186:
                # invokedynamic: string concatenation or a lambda capturing the value; neither is followed.
                desc = cf.utf[u2(cf.cp[u2(cf.cp[u2(arg,0)][1],2)][1],2)];method = None
            else:
                method = cf.method(u2(arg,0))
                if not method:return None
                desc = method[2]
            sizes, ret = params(desc)
            pops = sum(sizes)+(0 if op in (184,186) else 1); pushes = ret
            if above < pops:
                if op == 186:return None
                # Which parameter the value is: count slots down from the top of the stack.
                depth = 0; index = None
                for k in range(len(sizes)-1,-1,-1):
                    if depth == above and sizes[k] == 1:index = k;break
                    depth += sizes[k]
                if index is None:return None  # the value is the receiver of the call
                if index == 0 and sink(method) and len(sizes) == 1:return {'玩家顯示文字'}
                if index == 0 and key_sink(method):return {KEY}
                if not flow:return None
                owner, name, _ = method
                target = flow.cls(owner)
                if not target or (name, desc) not in target.methods:return None
                flags = target.methods[(name, desc)][0]
                # Only a call that cannot reach another mod's override of the method.
                if op in (182,185) and not (flags & 0x0012 or target.access & 0x0010):return None
                return flow.param(owner, name, desc, index, op == 184)
        else:
            return None  # branches, switches, returns, throw, jsr, multianewarray, monitors
        if above < pops:return None
        above += pushes-pops;n += 1
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


def proven_strings(raw, flow=None):
    """Strings of a class whose every use is shown to the player: {UTF-8 constant index: (text, reason)}.

    `flow` (JarFlow of the mod file) also follows a string handed to a method or stored in a field of that file.
    """
    cf = ClassFile(raw)
    strings = {k:u2(v,0) for k,(t,v) in cf.cp.items() if t == 8}
    uses = {k:[] for k in strings}
    for code, handlers in cf.codes:
        ops = list(instructions(code)); targets = branch_targets(code, ops, handlers)
        at = {pos:n for n,(pos,_,_) in enumerate(ops)}
        safe = {}
        for i, (pos,op,arg) in enumerate(ops):
            if op in (182,183,184,185):
                method = cf.method(u2(arg,0))
                reason = sink(method)
                if reason and i and ops[i-1][1] in (18,19) and pos not in targets:safe[i-1] = reason
                if sink(method,True):safe.update({idx:'設定說明' for idx in comment_loads(cf,ops,i,targets) or []})
        for i, (pos,op,arg) in enumerate(ops):
            if op in (18,19) and i not in safe and (arg[0] if op == 18 else u2(arg,0)) in strings:
                # Through a jump (cond ? "Required" : "Optional") or a helper method and field of the same mod file.
                reasons = consumer(cf, code, ops, i, flow, at=at)
                if reasons == {'玩家顯示文字'}:safe[i] = '玩家顯示文字'
                elif reasons and KEY in reasons:cf.keys.add(cf.utf[strings[arg[0] if op == 18 else u2(arg,0)]])
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


def translation_keys(raw, flow=None):
    """Texts this class hands to Component.translatable as the language key (directly or through a helper of the
    same mod file). Some mods pass the English sentence itself (Cobblemon Additions: "Spawner: %1$s\\nOffset: %2$i");
    a language entry keyed by that sentence shows a translation, the class stays as it is."""
    cf = ClassFile(raw); found = set()
    strings = {k:u2(v,0) for k,(t,v) in cf.cp.items() if t == 8}
    for code, _ in cf.codes:
        ops = list(instructions(code)); at = {pos:n for n,(pos,_,_) in enumerate(ops)}
        for i, (_,op,arg) in enumerate(ops):
            index = (arg[0] if op == 18 else u2(arg,0)) if op in (18,19) else None
            if index in strings and KEY in (consumer(cf, code, ops, i, flow, at=at) or ()):found.add(cf.utf[strings[index]])
    return found


# Calls that compare or look up text: a literal handed to one of them may be matched against data, so its
# characters must stay as they are (javac's switch on a String also ends in equals on each literal).
COMPARE = {'equals','equalsIgnoreCase','hashCode','compareTo','compareToIgnoreCase','contentEquals','startsWith',
           'endsWith','contains','containsKey','containsValue','get','getOrDefault','remove','indexOf','lastIndexOf',
           'matches','regionMatches','areEqual','valueOf','forName','parse','lookup','byName','fromString'}


def plain_strings(raw):
    """String literals that are only loaded (ldc) and kept in no annotation, field or other pool role, for a
    Simplified-to-Traditional conversion whose use is not proven; and the texts this class compares.

    Returns (cf, {UTF-8 constant index: text}, {texts handed to a comparing or lookup call}). A conversion keeps
    the meaning, and the same literal becomes the same text in every class, so names a mod stores and shows
    stay consistent; only text it compares with may not change (excluded jar-wide by the caller).
    """
    cf = ClassFile(raw)
    strings = {k:u2(v,0) for k,(t,v) in cf.cp.items() if t == 8}
    loaded = collections.Counter(); compared = set()
    for code, _ in cf.codes:
        ops = list(instructions(code))
        for i, (_,op,arg) in enumerate(ops):
            if op not in (18,19):continue
            index = arg[0] if op == 18 else u2(arg,0)
            if index not in strings:continue
            loaded[strings[index]] += 1
            for _,later,larg in ops[i+1:i+4]:
                if later in (182,183,184,185):
                    method = cf.method(u2(larg,0))
                    if method and method[1] in COMPARE:compared.add(cf.utf[strings[index]])
                    break
    result = {}
    for utf in set(strings.values()):
        shared = [k for k,v in strings.items() if v == utf]
        protected = any(struct.pack('>H',k) in b for k in [utf]+shared for b in cf.metadata)
        protected |= any(t != 8 and t in (7,12,16,19,20) and struct.pack('>H',utf) in v for t,v in cf.cp.values())
        if loaded[utf] and not protected:result[utf] = cf.utf[utf]
    return cf, result, compared


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


THROWABLE = re.compile(r'(?:Exception|Error|Throwable)$')
LOGGERS = {'Lorg/slf4j/Logger;','Lorg/apache/logging/log4j/Logger;','Ljava/util/logging/Logger;'}
LOGGER_OWNERS = {'org/slf4j/Logger','org/apache/logging/log4j/Logger','java/util/logging/Logger'}
LOG_METHODS = {'trace','debug','info','warn','error','fatal','log','warning','severe','fine','finer','finest','config'}


def developer_strings(raw):
    """UTF-8 constant indexes of text used only as an exception message or a log line, never shown in play.

    A use counts when the string (or the string-concatenation recipe holding it, where character U+0001 marks
    the values) is passed straight to `new SomethingException(...)` or to a Logger call. One use of any
    other kind keeps the string among the candidates that need checking.
    """
    cf = ClassFile(raw)
    def class_name(index):
        return cf.utf.get(u2(cf.cp[index][1], 0), '') if cf.cp.get(index, (0,))[0] == 7 else ''
    def field_type(index):
        tag, value = cf.cp.get(index, (0, b''))
        return cf.utf.get(u2(cf.cp[u2(value, 2)][1], 2), '') if tag == 9 else ''
    def consumer(op):
        if op[1] not in (182, 183, 185):return ''
        method = cf.method(u2(op[2], 0))
        if not method:return ''
        owner, name, desc = method
        if op[1] == 183 and name == '<init>' and THROWABLE.search(owner) and desc.startswith('(Ljava/lang/String;'):return 'error'
        if owner in LOGGER_OWNERS and name in LOG_METHODS and desc.startswith('(Ljava/lang/String;'):return 'log'
        return ''
    uses = {}
    for code, handlers in cf.codes:
        ops = list(instructions(code))
        for i, op in enumerate(ops):
            if op[1] in (18, 19):
                tag, value = cf.cp.get(ldc_index(op), (0, b''))
                if tag != 8:continue
                index = u2(value, 0)
                # new X; dup; "message" … <init> — or LOGGER; "message" … log call.
                developer = (i >= 2 and ops[i-1][1] == 89 and ops[i-2][1] == 187 and THROWABLE.search(class_name(u2(ops[i-2][2], 0))))
                developer = developer or (i >= 1 and ops[i-1][1] in (178, 180) and field_type(u2(ops[i-1][2], 0)) in LOGGERS)
                developer = developer or (i+1 < len(ops) and consumer(ops[i+1]) != '')
                uses.setdefault(index, []).append(bool(developer))
            elif op[1] == 186:
                tag, value = cf.cp.get(u2(op[2], 0), (0, b''))
                if tag != 18:continue
                args = cf.bootstrap[u2(value, 0)] if u2(value, 0) < len(cf.bootstrap) else []
                developer = i+1 < len(ops) and consumer(ops[i+1]) != ''
                for arg in args:
                    if cf.cp.get(arg, (0,))[0] == 8:uses.setdefault(u2(cf.cp[arg][1], 0), []).append(developer)
    return {index for index, found in uses.items() if found and all(found)}


def ldc_index(op):
    _,code,arg = op
    return arg[0] if code == 18 else u2(arg,0)


def integer(op):
    _,code,arg = op
    if 3 <= code <= 8:return code-3
    if code == 16:return struct.unpack('>b',arg)[0]
    if code == 17:return struct.unpack('>h',arg)[0]
    return None


def rewrite(raw, rows, flow=None):
    cf, safe = proven_strings(raw, flow); edits = {}
    plain = plain_strings(raw) if any(row.get('literal') for row in rows) else None
    for row in rows:
        index = int(row['key'])
        if row.get('literal'):
            # Simplified Chinese whose use is not proven: only its characters change, and only while it is still
            # a plain literal that this class never compares.
            _, texts, compared = plain
            if texts.get(index) != row['current'] or row['current'] in compared:raise ValueError('程式文字用途或原文已變動，請重新翻譯')
        elif index not in safe or safe[index][0] != row['current']:raise ValueError('程式文字用途或原文已變動，請重新翻譯')
        value = row['proposed']
        if re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value) != re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',row['current']):raise ValueError('程式文字控制字元不一致')
        encoded = encode_mutf(value)
        if len(encoded)>65535:raise ValueError('程式文字超過 Java 長度限制')
        edits[index] = b'\x01'+struct.pack('>H',len(encoded))+encoded
    parts = [raw[:10]]
    for k,(start,end) in cf.spans.items():parts.append(edits.get(k,raw[start:end]))
    parts.append(raw[cf.tail:]); output = b''.join(parts)
    checked, _ = proven_strings(output, flow)
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
