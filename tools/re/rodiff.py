"""Byte-level diff of one section between two builds, resyncing over insertions."""
import sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import sections

def diff(a, b, base_a, base_b, win=8192, key=24):
    i = j = 0; out = []
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            # fast skip over equal run
            n = 1
            step = 4096
            while i + n + step <= len(a) and j + n + step <= len(b) and a[i+n:i+n+step] == b[j+n:j+n+step]:
                n += step
            while i + n < len(a) and j + n < len(b) and a[i+n] == b[j+n]:
                n += 1
            i += n; j += n; continue
        # mismatch: find the nearest resync point
        best = None
        for d in range(0, win):
            for (di, dj) in ((d, None), (None, d)):
                pass
        found = None
        for skip_a in range(0, 2048):
            k = a[i+skip_a:i+skip_a+key]
            if len(k) < key: break
            p = b.find(k, j, j + 2048 + key)
            if p != -1:
                found = (skip_a, p - j); break
        if not found:
            out.append((i, j, a[i:i+64], b[j:j+64], 'LOST SYNC')); break
        sa, sb_ = found
        out.append((i, j, a[i:i+sa], b[j:j+sb_], ''))
        i += sa; j += sb_
    return out, (len(a) - i, len(b) - j)

if __name__ == '__main__':
    pa, pb, sec = sys.argv[1:4]
    da, sa = sections(pa); db, sb = sections(pb)
    aa, oa, na = sa[sec]; ab, ob, nb = sb[sec]
    A = da[oa:oa+na]; B = db[ob:ob+nb]
    res, tail = diff(A, B, aa, ab)
    print(f"{sec}: zx300 {aa:#x}+{na:#x}  a50 {ab:#x}+{nb:#x}  -> {len(res)} differing regions, tails {tail}")
    for i, j, x, y, note in res:
        print(f"  zx300 {aa+i:#x} ({len(x)} bytes) | a50 {ab+j:#x} ({len(y)} bytes) {note}")
        print(f"     zx300: {x[:96]!r}")
        print(f"     a50  : {y[:96]!r}")
