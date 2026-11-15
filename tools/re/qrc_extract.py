"""qrc_extract.py <elf> <outdir> : find Qt resource (rcc) trees embedded in .rodata and extract every file."""
import os, re, struct, sys, zlib
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from exidx import sections

path, outdir = sys.argv[1:3]
d, secs = sections(path)
ro_va, ro_off, ro_n = secs['.rodata']
R = d[ro_off:ro_off + ro_n]

def qt_hash(s):
    h = 0
    for ch in s:
        h = ((h << 4) + ord(ch)) & 0xFFFFFFFF
        h ^= (h & 0xF0000000) >> 23
        h &= 0x0FFFFFFF
    return h

def parse_tree(T, esz):
    """Return list of entries reachable from root, or None."""
    ents = {}
    def ent(i):
        o = T + i * esz
        if o + esz > len(R): raise ValueError
        name, flags = struct.unpack_from('>IH', R, o)
        if flags & ~0x3: raise ValueError
        if flags & 2:
            cnt, first = struct.unpack_from('>II', R, o + 6)
            return ('d', name, cnt, first)
        country, lang, data = struct.unpack_from('>HHI', R, o + 6)
        return ('f', name, flags & 1, data)
    todo = [0]; seen = set()
    try:
        while todo:
            i = todo.pop()
            if i in seen: continue
            seen.add(i)
            e = ent(i); ents[i] = e
            if e[0] == 'd':
                if e[2] > 20000 or e[3] > 200000: return None
                todo.extend(range(e[3], e[3] + e[2]))
            if len(seen) > 200000: return None
    except (ValueError, struct.error):
        return None
    if sorted(ents) != list(range(len(ents))): return None
    return ents

def name_at(B, off):
    o = B + off
    if o < 0 or o + 6 > len(R): return None
    ln, h = struct.unpack_from('>HI', R, o)
    if not 0 < ln < 512 or o + 6 + 2 * ln > len(R): return None
    try: s = R[o + 6:o + 6 + 2 * ln].decode('utf-16-be')
    except UnicodeDecodeError: return None
    if not all(0x20 <= ord(c) < 0x7f and c not in '/\\' for c in s): return None
    return s if qt_hash(s) == h else None

found = 0
for m in re.finditer(rb'\x00\x00\x00\x00\x00\x02\x00\x00..\x00\x00\x00\x01', R, re.S):
    T = m.start()
    for esz in (14, 22):
        ents = parse_tree(T, esz)
        if not ents or len(ents) < 3: continue
        name_offs = sorted({e[1] for i, e in ents.items() if i != 0})
        files = sorted((e[3], i) for i, e in ents.items() if e[0] == 'f')
        if not files: continue
        # layout A: struct, names, data back to back (what this toolchain emits)
        B = D = None
        offs = [o for o, _ in files]
        def chain_ok(cand):
            for k in range(len(offs) - 1):
                if cand + offs[k] + 4 > len(R) or struct.unpack_from('>I', R, cand + offs[k])[0] + 4 + offs[k] != offs[k + 1]: return False
            return cand + offs[-1] + 4 <= len(R)
        for pad in range(0, 17):
            cand = T + len(ents) * esz + pad
            if all(name_at(cand, o) is not None for o in name_offs):
                B = cand; break
        if B is not None:
            last = max(name_offs)
            ln = struct.unpack_from('>H', R, B + last)[0]
            end = B + last + 6 + 2 * ln
            for pad in range(0, 17):
                if chain_ok(end + pad): D = end + pad; break
        if B is None or D is None:
            # layout B: data, names, struct (rcc's usual order)
            B = D = None
            for cand in range(T - 6, max(0, T - 4_000_000), -1):
                if name_at(cand, name_offs[0]) is None: continue
                if all(name_at(cand, o) is not None for o in name_offs): B = cand; break
            if B is None: continue
            for cand in range(B - 4, max(0, B - 8_000_000), -1):
                if chain_ok(cand): D = cand; break
            if D is None: continue
        found += 1
        root = os.path.join(outdir, f"tree{found}")
        print(f"tree{found}: struct @ va {ro_va + T:#x} (entry {esz}B, {len(ents)} nodes, {len(files)} files) names @ {ro_va + B:#x} data @ {ro_va + D:#x}")
        def walk(i, prefix):
            e = ents[i]
            nm = '' if i == 0 else name_at(B, e[1])
            p = prefix + '/' + nm if nm else prefix
            if e[0] == 'd':
                for c in range(e[3], e[3] + e[2]): walk(c, p)
            else:
                o = D + e[3]
                ln = struct.unpack_from('>I', R, o)[0]
                raw = R[o + 4:o + 4 + ln]
                if e[2]: raw = zlib.decompress(raw[4:])
                dest = root + p
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, 'wb').write(raw)
        try:
            walk(0, '')
        except Exception as ex:
            print('   extraction failed:', ex); found -= 1; continue
        break
print("trees extracted:", found)
