"""qmeta.py <elf> <class name>... : dump Qt 5 meta-objects (signals, slots, properties) from a stripped binary, following superclasses."""
import struct, sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import sections
path = sys.argv[1]
d, secs = sections(path)
def off(va):
    for n in ('.rodata', '.data.rel.ro', '.data', '.got', '.text'):
        a, o, s = secs[n]
        if a <= va < a + s: return o + (va - a)
    raise ValueError(hex(va))
def u32(va): return struct.unpack_from('<I', d, off(va))[0]
def i32(va): return struct.unpack_from('<i', d, off(va))[0]
ro_a, ro_o, ro_s = secs['.rodata']; rr_a, rr_o, rr_s = secs['.data.rel.ro']
TYPES = {0:'?',1:'bool',2:'int',3:'uint',4:'qlonglong',5:'qulonglong',6:'double',10:'QString',11:'QStringList',12:'QByteArray',36:'ushort',38:'float',39:'QObject*',41:'QVariant',43:'void',8:'QVariantMap',9:'QVariantList',34:'char',32:'long',35:'ulong',33:'short',37:'uchar',31:'void*',16:'QUrl'}
def find_stringdata(name):
    nb = name.encode() + b'\0'; res = []
    p = d.find(nb, ro_o)
    while p != -1 and p < ro_o + ro_s:
        A = ro_a + (p - ro_o)
        for H in range(A - 4, A - 0x4000, -4):
            if H < ro_a: break
            try:
                if u32(H) == 0xFFFFFFFF and u32(H + 4) == len(name) and i32(H + 12) == A - H: res.append(H); break
            except ValueError: break
        p = d.find(nb, p + 1)
    return res
def find_metaobject(H):
    for o in range(0, rr_s - 23, 4):
        if struct.unpack_from('<I', d, rr_o + o + 4)[0] == H: return rr_a + o
    return None
def s(H, i):
    h = H + 16 * i; return d[off(h + i32(h + 12)):off(h + i32(h + 12)) + u32(h + 4)].decode('latin1')
def tname(H, t): return s(H, t & 0x7FFFFFFF) if t & 0x80000000 else TYPES.get(t, f'type{t}')
def dump(mo, depth=0):
    superp, H, data = u32(mo), u32(mo + 4), u32(mo + 8)
    hdr = [u32(data + 4 * i) for i in range(14)]
    rev, cname, _, _, mcount, mdata, pcount, pdata, _, _, _, _, flags, sigcount = hdr
    print(f"\n{'  ' * depth}class {s(H, cname)}  (metaobject {mo:#x}, static_metacall {u32(mo + 12) & ~1:#x}, {mcount} methods of which {sigcount} signals, {pcount} properties)")
    for i in range(mcount):
        m = data + 4 * (mdata + 5 * i)
        name, argc, params, tag, fl = [u32(m + 4 * k) for k in range(5)]
        p = data + 4 * params
        ret = tname(H, u32(p)); types = [tname(H, u32(p + 4 * (1 + k))) for k in range(argc)]; names = [s(H, u32(p + 4 * (1 + argc + k))) for k in range(argc)]
        kind = {0: 'method', 4: 'SIGNAL', 8: 'slot  ', 12: 'ctor'}[fl & 0x0c]
        acc = {0: 'private', 1: 'protected', 2: 'public'}[fl & 3]
        print(f"{'  ' * depth}  [{i:>2}] {kind} {ret + ' ' if ret != 'void' else ''}{s(H, name)}({', '.join(f'{t} {n}'.strip() for t, n in zip(types, names))})  {acc}")
    for i in range(pcount):
        p = data + 4 * (pdata + 3 * i)
        print(f"{'  ' * depth}  property {tname(H, u32(p + 4))} {s(H, u32(p))}")
    return superp
for name in sys.argv[2:]:
    Hs = find_stringdata(name)
    if not Hs: print(f"{name}: meta string data not found"); continue
    for H in Hs:
        mo = find_metaobject(H)
        if mo is None: print(f"{name}: stringdata at {H:#x} but no metaobject"); continue
        depth = 0
        while mo and rr_a <= mo < rr_a + rr_s:
            mo = dump(mo, depth); depth += 1
        if mo: print(f"{'  ' * depth}(superclass metaobject at {mo:#x} is outside this binary: a Qt class)")
