"""Function boundaries from .ARM.exidx, and a per-function comparison of two builds."""
import struct, sys

def sections(path):
    d = open(path, 'rb').read()
    shoff, = struct.unpack_from('<I', d, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', d, 0x2E)
    secs = []
    for i in range(shnum):
        name, typ, flags, addr, off, size = struct.unpack_from('<IIIIII', d, shoff + i*shentsize)
        secs.append((name, typ, addr, off, size))
    stroff = secs[shstrndx][3]
    out = {}
    for name, typ, addr, off, size in secs:
        n = d[stroff+name:d.index(b'\0', stroff+name)].decode()
        out[n] = (addr, off, size)
    return d, out

def funcs(path):
    d, s = sections(path)
    addr, off, size = s['.ARM.exidx']
    starts = []
    for i in range(size // 8):
        w, = struct.unpack_from('<I', d, off + 8*i)
        if w & 0x40000000: w |= 0x80000000
        w = w - (1 << 32) if w & 0x80000000 else w
        starts.append((addr + 8*i + w) & ~1)
    return d, s, starts

if __name__ == '__main__':
    da, sa, fa = funcs(sys.argv[1]); db, sb, fb = funcs(sys.argv[2])
    print(len(fa), len(fb), "exidx entries; sorted:", fa == sorted(fa), fb == sorted(fb))
    ta = sa['.text']; tb = sb['.text']
    enda = ta[0] + ta[2]; endb = tb[0] + tb[2]
    print(f".text  zx300 {ta[0]:#x}+{ta[2]:#x}   a50 {tb[0]:#x}+{tb[2]:#x}")
    prev = 0
    for i in range(len(fa)):
        na = (fa[i+1] if i+1 < len(fa) else enda) - fa[i]
        nb = (fb[i+1] if i+1 < len(fb) else endb) - fb[i]
        shift = fb[i] - fa[i]
        if na != nb:
            print(f"#{i:<6} zx300 {fa[i]:#08x} len {na:#06x} | a50 {fb[i]:#08x} len {nb:#06x} | size delta {nb-na:+d} (shift before {shift:+d})")
