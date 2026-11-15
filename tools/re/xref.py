"""xref.py <binary> <target vaddr>... : direct BL/B.W callers and data pointers to each target."""
import struct, sys, bisect
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import funcs
from codediff_lib import branch_target

path = sys.argv[1]; targets = [int(x, 0) & ~1 for x in sys.argv[2:]]
d, s, f = funcs(path)
t0, _, tn = s['.text']
hits = {t: [] for t in targets}
a = t0
while a < t0 + tn - 3:
    h = struct.unpack_from('<H', d, a)[0]
    if (h & 0xF800) == 0xF000:
        bt = branch_target(d, a)
        if bt and bt[1] in hits: hits[bt[1]].append((a, bt[0]))
    a += 2
for t in targets:
    print(f"== {t:#x}: {len(hits[t])} direct branch sites")
    for a, k in hits[t]:
        i = bisect.bisect_right(f, a) - 1
        print(f"   {k:<3} at {a:#x}  in fn#{i} {f[i]:#x}+{a - f[i]:#x}")
    for sec in ('.data.rel.ro', '.data', '.init_array', '.got'):
        va, off, n = s[sec]
        for p in range(0, n - 3, 4):
            if struct.unpack_from('<I', d, off + p)[0] == (t | 1):
                print(f"   pointer in {sec} at {va + p:#x}")
