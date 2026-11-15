import struct
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

