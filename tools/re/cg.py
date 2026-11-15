"""cg.py <elf> : build a call graph + string references for a stripped Thumb-2 PIC binary; pickle it."""
import struct, sys, bisect, pickle, collections
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import funcs
from codediff_lib import branch_target

path = sys.argv[1]
d, s, ex = funcs(path)
t0, _, tn = s['.text']; tend = t0 + tn
ro0, _, ron = s['.rodata']; roend = ro0 + ron
def hw(a): return struct.unpack_from('<H', d, a)[0]
def is32(h): return (h >> 11) in (0b11101, 0b11110, 0b11111)

# pass 1: function starts = exidx starts + BL targets + code pointers in relro/data
starts = set(ex)
a = t0
while a < tend - 3:
    h = hw(a)
    if (h & 0xF800) == 0xF000:
        bt = branch_target(d, a)
        if bt and bt[0] == 'bl' and t0 <= bt[1] < tend: starts.add(bt[1])
    a += 2
ptrs = collections.defaultdict(list)
for sec in ('.data.rel.ro', '.data', '.init_array'):
    va, off, n = s[sec]
    for p in range(0, n - 3, 4):
        v = struct.unpack_from('<I', d, off + p)[0]
        if v & 1 and t0 <= v - 1 < tend:
            starts.add(v - 1); ptrs[v - 1].append(va + p)
starts = sorted(starts)

def cstr(addr):
    if not (ro0 <= addr < roend): return None
    e = d.find(b'\0', addr, addr + 400)
    if e == -1 or e == addr: return None
    b = d[addr:e]
    if all(0x20 <= c < 0x7f or c in (9, 10) for c in b): return b.decode()
    return None

calls = collections.defaultdict(set)     # caller fn -> {(site, kind, target)}
callers = collections.defaultdict(set)   # target -> {(caller fn, site, kind)}
strs = collections.defaultdict(list)     # fn -> [(site, string)]
for idx, f0 in enumerate(starts):
    f1 = starts[idx + 1] if idx + 1 < len(starts) else tend
    lit = set(); reg = {}
    a = f0
    while a < f1 - 1:
        if (a & ~3) in lit: a += 2; continue
        h = hw(a)
        if (h & 0xF800) == 0x4800:                     # ldr rt,[pc,#imm8*4]
            la = ((a + 4) & ~3) + (h & 0xFF) * 4; lit.add(la)
            if la + 4 <= len(d): reg[(h >> 8) & 7] = struct.unpack_from('<I', d, la)[0]
            a += 2; continue
        if (h & 0xFF78) == 0x4478:                     # add rdn, pc
            r = (h & 7) | ((h >> 4) & 8)
            if r in reg:
                v = (reg.pop(r) + a + 4) & 0xFFFFFFFF
                st = cstr(v)
                if st is not None: strs[f0].append((a, st))
            a += 2; continue
        if is32(h) and a + 2 < f1:
            h2 = hw(a + 2)
            if (h & 0xFF7F) == 0xF85F:                 # ldr.w rt,[pc,#imm12]
                off = h2 & 0xFFF; la = ((a + 4) & ~3) + (off if h & 0x80 else -off); lit.add(la)
                if 0 <= la and la + 4 <= len(d): reg[(h2 >> 12) & 15] = struct.unpack_from('<I', d, la)[0]
            elif (h & 0xF800) == 0xF000 and (h2 & 0x8000):
                bt = branch_target(d, a)
                if bt and bt[0] in ('bl', 'blx', 'b'):
                    tgt = bt[1]
                    if bt[0] != 'b' or not (f0 <= tgt < f1):
                        calls[f0].add((a, bt[0], tgt)); callers[tgt].add((f0, a, bt[0]))
            a += 4; continue
        a += 2
pickle.dump({'starts': starts, 'calls': dict(calls), 'callers': dict(callers), 'strs': dict(strs), 'ptrs': dict(ptrs)}, open(sys.argv[2], 'wb'))
print(f"functions {len(starts)}; with string refs {len(strs)}; call edges {sum(len(v) for v in calls.values())}")
