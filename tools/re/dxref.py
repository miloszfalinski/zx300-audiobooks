"""dxref.py <elf> <cg.pickle> <out.pickle> : data cross-references (PC-relative 'ldr rX,[pc]; add rX,pc' pairs, GOT-resolved)."""
import struct, sys, bisect, pickle, collections
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import funcs
path = sys.argv[1]
d, s, ex = funcs(path)
t0, _, tn = s['.text']; tend = t0 + tn
G = pickle.load(open(sys.argv[2], 'rb')); starts = G['starts']
got_va, got_off, got_n = s['.got']
def hw(a): return struct.unpack_from('<H', d, a)[0]
def is32(h): return (h >> 11) in (0b11101, 0b11110, 0b11111)
def got_deref(v):
    if got_va <= v < got_va + got_n: return struct.unpack_from('<I', d, got_off + (v - got_va))[0]
    return None
refs = collections.defaultdict(set)      # address -> {(function, site, via_got)}
for idx, f0 in enumerate(starts):
    f1 = starts[idx + 1] if idx + 1 < len(starts) else tend
    lit = set(); reg = {}; a = f0
    while a < f1 - 1:
        if (a & ~3) in lit: a += 2; continue
        h = hw(a)
        if (h & 0xF800) == 0x4800:
            la = ((a + 4) & ~3) + (h & 0xFF) * 4; lit.add(la)
            if la + 4 <= len(d): reg[(h >> 8) & 7] = struct.unpack_from('<I', d, la)[0]
            a += 2; continue
        if (h & 0xFF78) == 0x4478:
            r = (h & 7) | ((h >> 4) & 8)
            if r in reg:
                v = (reg.pop(r) + a + 4) & 0xFFFFFFFF
                if 0x88a000 <= v < 0x8b9000:
                    refs[v].add((f0, a, False))
                    g = got_deref(v)
                    if g: refs[g].add((f0, a, True))
            a += 2; continue
        if is32(h) and a + 2 < f1:
            h2 = hw(a + 2)
            if (h & 0xFF7F) == 0xF85F:
                off = h2 & 0xFFF; la = ((a + 4) & ~3) + (off if h & 0x80 else -off); lit.add(la)
                if 0 <= la and la + 4 <= len(d): reg[(h2 >> 12) & 15] = struct.unpack_from('<I', d, la)[0]
            a += 4; continue
        a += 2
pickle.dump(dict(refs), open(sys.argv[3], 'wb'))
print("data addresses referenced:", len(refs))
