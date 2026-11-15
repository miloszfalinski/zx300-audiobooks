#!/usr/bin/env python3
"""Copy named files out of an ext4 image, read-only, without mounting it.

macOS cannot mount ext4, and this needs nothing installed. It handles what a
freshly built firmware image contains: extent-mapped regular files, no journal
replay. Anything else (symlinks, block-mapped files) is refused, not guessed.

usage: ext4_get.py <image> <outdir> <path/inside/image>...

Each file is written to <outdir>/<path/inside/image>, and one line per file is
printed: octal mode, size, path.
"""
import os
import struct
import sys

if len(sys.argv) < 4:
    sys.exit(__doc__)
img_path, outdir, wanted = sys.argv[1], sys.argv[2], sys.argv[3:]
f = open(img_path, "rb")


def pread(off, n):
    f.seek(off)
    return f.read(n)


sb = pread(1024, 1024)
if struct.unpack_from("<H", sb, 0x38)[0] != 0xEF53:
    sys.exit(f"{img_path}: not an ext2/3/4 image")
BS = 1024 << struct.unpack_from("<I", sb, 0x18)[0]
first_data_block = struct.unpack_from("<I", sb, 0x14)[0]
inodes_per_group = struct.unpack_from("<I", sb, 0x28)[0]
inode_size = struct.unpack_from("<H", sb, 0x58)[0]
incompat = struct.unpack_from("<I", sb, 0x60)[0]
desc_size = struct.unpack_from("<H", sb, 0xFE)[0] if incompat & 0x80 else 32
gdt_off = (first_data_block + 1) * BS


def read_inode(ino):
    g, idx = divmod(ino - 1, inodes_per_group)
    gd = pread(gdt_off + g * desc_size, desc_size)
    tbl = struct.unpack_from("<I", gd, 8)[0]
    if desc_size >= 64:
        tbl |= struct.unpack_from("<I", gd, 0x28)[0] << 32
    raw = pread(tbl * BS + idx * inode_size, inode_size)
    mode = struct.unpack_from("<H", raw, 0)[0]
    size = struct.unpack_from("<I", raw, 4)[0] | (struct.unpack_from("<I", raw, 0x6C)[0] << 32)
    return mode, size, raw[0x28 : 0x28 + 60]


def extents(node):
    magic, entries, _max, depth = struct.unpack_from("<HHHH", node, 0)
    if magic != 0xF30A:
        raise ValueError("not extent-mapped")
    for i in range(entries):
        e = node[12 + 12 * i : 24 + 12 * i]
        if depth == 0:
            lblk, ln, hi, lo = struct.unpack("<IHHI", e)
            yield lblk, ln, (hi << 32) | lo
        else:
            _lblk, lo, hi, _ = struct.unpack("<IIHH", e)
            yield from extents(pread(((hi << 32) | lo) * BS, BS))


def read_data(ino):
    _mode, size, iblock = read_inode(ino)
    out = bytearray(size)
    for lblk, ln, pblk in extents(iblock):
        if ln > 32768:  # uninitialised extent: reads as zeros
            continue
        off = lblk * BS
        if off >= size:
            continue
        chunk = pread(pblk * BS, ln * BS)
        end = min(size, off + len(chunk))
        out[off:end] = chunk[: end - off]
    return bytes(out)


def lookup(dir_ino, name):
    data = read_data(dir_ino)
    pos = 0
    while pos + 8 <= len(data):
        child, rec_len, name_len, _ftype = struct.unpack_from("<IHBB", data, pos)
        if rec_len < 8:
            break
        if child and data[pos + 8 : pos + 8 + name_len] == name.encode():
            return child
        pos += rec_len
    return None


failed = False
for path in wanted:
    parts = [p for p in path.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        sys.exit(f"{path}: not a plain path")
    ino = 2  # root directory
    for i, part in enumerate(parts):
        if read_inode(ino)[0] & 0xF000 != 0x4000:
            ino = None
            break
        ino = lookup(ino, part)
        if ino is None:
            break
    if ino is None:
        print(f"MISSING\t{path}", file=sys.stderr)
        failed = True
        continue
    mode, size, _ = read_inode(ino)
    if mode & 0xF000 != 0x8000:
        print(f"NOT A REGULAR FILE\t{path}", file=sys.stderr)
        failed = True
        continue
    try:
        data = read_data(ino)
    except ValueError as e:
        print(f"UNSUPPORTED ({e})\t{path}", file=sys.stderr)
        failed = True
        continue
    dst = os.path.join(outdir, *parts)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as o:
        o.write(data)
    print(f"{mode & 0o7777:o}\t{size}\t{path}")
sys.exit(1 if failed else 0)
