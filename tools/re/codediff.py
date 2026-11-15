"""Compare same-size functions of two builds; report differences that are not
relocation noise (branch targets that map to the same callee, shifted literal offsets)."""
import struct, sys, bisect, collections
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import funcs

pa, pb = sys.argv[1:3]
da, sa, fa = funcs(pa); db, sb, fb = funcs(pb)
ta, tb = sa['.text'], sb['.text']
enda, endb = ta[0] + ta[2], tb[0] + tb[2]
plta, pltb = sa['.plt'], sb['.plt']

def hw(d, addr): return struct.unpack_from('<H', d, addr)[0]   # vaddr == file offset in .text
def w32(d, addr): return struct.unpack_from('<I', d, addr)[0]

def is32(h): return (h >> 11) in (0b11101, 0b11110, 0b11111)

def branch_target(d, addr):
    """Decode BL/BLX/B.W/Bcc.W at addr; return (kind, target) or None."""
    h1, h2 = hw(d, addr), hw(d, addr + 2)
    if (h1 & 0xF800) != 0xF000 or not (h2 & 0x8000): return None
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    if (h2 & 0x5000) == 0x0000:   # conditional B.W
        if ((h1 >> 6) & 0xF) >= 0xE: return None
        imm = (s << 20) | (j2 << 19) | (j1 << 18) | ((h1 & 0x3F) << 12) | ((h2 & 0x7FF) << 1)
        if s: imm -= 1 << 21
        return ('bcc', addr + 4 + imm)
    i1 = 1 - (j1 ^ s); i2 = 1 - (j2 ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if s: imm -= 1 << 25
    if (h2 & 0x5000) == 0x1000: return ('b', addr + 4 + imm)
    if (h2 & 0x5000) == 0x5000: return ('bl', addr + 4 + imm)
    return ('blx', ((addr + 4) & ~3) + imm)

def where(starts, text, plt, t):
    if plt[0] <= t < plt[0] + plt[2]: return ('plt', t - plt[0])
    i = bisect.bisect_right(starts, t) - 1
    if i < 0: return ('pre', t - text[0])
    return (i, t - starts[i])

def literals(d, start, end):
    lit = set(); a = start
    while a < end - 1:
        if a in lit or (a & ~3) in lit and False: pass
        if (a & ~3) in lit and a % 4 in (0, 2): a += 2; continue
        h = hw(d, a)
        if (h & 0xF800) == 0x4800:
            lit.add(((a + 4) & ~3) + (h & 0xFF) * 4)
        elif is32(h) and a + 2 < end:
            h2 = hw(d, a + 2)
            if (h & 0xFF7F) == 0xF85F:      # ldr.w rt,[pc,#+-imm12]
                off = h2 & 0xFFF
                lit.add(((a + 4) & ~3) + (off if h & 0x80 else -off))
            elif (h & 0xFF7F) == 0xED1F or (h & 0xFF7F) == 0xED9F and False:
                pass
            if (h & 0xFE7F) == 0xE85F and False: pass
            a += 4; continue
        a += 2
    return lit

real = []; lit_delta = collections.Counter(); lit_examples = {}; nbr = 0; badbr = []
n_same = 0
for i in range(len(fa)):
    a0, b0 = fa[i], fb[i]
    na = (fa[i+1] if i + 1 < len(fa) else enda) - a0
    nb = (fb[i+1] if i + 1 < len(fb) else endb) - b0
    if na != nb: continue
    A = da[a0:a0+na]; B = db[b0:b0+nb]
    if A == B: n_same += 1; continue
    lit = literals(da, a0, a0 + na)
    litrel = {x - a0 for x in lit}
    p = 0
    while p < na - 1:
        if A[p:p+2] == B[p:p+2]: p += 2; continue
        wp = p & ~3 if (a0 & 3) == 0 else p - ((a0 + p) & 3)
        if (a0 + p) & ~3 in lit:
            base = ((a0 + p) & ~3) - a0
            va, vb = struct.unpack_from('<I', A, base)[0], struct.unpack_from('<I', B, base)[0]
            dlt = (vb - va) & 0xFFFFFFFF
            if dlt & 0x80000000: dlt -= 1 << 32
            lit_delta[dlt] += 1; lit_examples.setdefault(dlt, (i, a0 + base, b0 + base, va, vb))
            p = base + 4; continue
        # try as second half / first half of a 32-bit branch
        done = False
        for q in (p, p - 2):
            if q < 0: continue
            ba = branch_target(da, a0 + q); bb = branch_target(db, b0 + q)
            if ba and bb and ba[0] == bb[0]:
                wa = where(fa, ta, plta, ba[1]); wb = where(fb, tb, pltb, bb[1])
                nbr += 1
                if wa != wb: badbr.append((i, a0 + q, b0 + q, ba, bb, wa, wb))
                p = q + 4; done = True; break
        if done: continue
        real.append((i, a0 + p, b0 + p, A[p:p+2].hex(), B[p:p+2].hex()))
        p += 2

print(f"functions: {len(fa)}; byte-identical: {n_same}")
print(f"branch-target diffs resolved to the same callee: {nbr - len(badbr)}; to a DIFFERENT callee: {len(badbr)}")
for x in badbr[:40]: print("   ", x[0], hex(x[1]), hex(x[2]), x[3][0], hex(x[3][1]), hex(x[4][1]), x[5], x[6])
print("literal-pool word deltas (a50 - zx300): count")
for dlt, c in sorted(lit_delta.items(), key=lambda kv: -kv[1]):
    i, aa, ab, va, vb = lit_examples[dlt]
    print(f"   {dlt:+#x}: {c}   e.g. fn#{i} zx300 {aa:#x}={va:#010x} a50 {ab:#x}={vb:#010x}")
print(f"other (non-branch, non-literal) differing halfwords: {len(real)}")
for r in real[:200]: print(f"   fn#{r[0]} zx300 {r[1]:#x}: {r[3]} | a50 {r[2]:#x}: {r[4]}")
