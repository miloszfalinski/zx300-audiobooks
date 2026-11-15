#!/usr/bin/env python3
"""Walk every regular file of an ext4 filesystem inside an image (read-only).

ext4_walk.py <image> <byte offset of the filesystem> hash            -> "<md5>  <size>  <path>" per file
ext4_walk.py <image> <offset> grep <needle> [<needle>...]            -> files containing each needle (bytes, case-sensitive)
ext4_walk.py <image> <offset> get <outdir> <path>...                 -> extract files
"""
import hashlib
import os
import struct
import sys

img, base, cmd, *args = sys.argv[1:]
base = int(base, 0)
f = open(img, "rb")


def pread(off, n):
    f.seek(base + off)
    return f.read(n)


sb = pread(1024, 1024)
assert struct.unpack_from("<H", sb, 0x38)[0] == 0xEF53, "not ext"
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
    return mode, size, raw[0x28:0x28 + 60]


def extents(node):
    magic, entries, _max, depth = struct.unpack_from("<HHHH", node, 0)
    if magic != 0xF30A:
        raise ValueError("not extent-mapped")
    for i in range(entries):
        e = node[12 + 12 * i:24 + 12 * i]
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
        if ln > 32768:
            continue
        off = lblk * BS
        if off >= size:
            continue
        chunk = pread(pblk * BS, ln * BS)
        end = min(size, off + len(chunk))
        out[off:end] = chunk[:end - off]
    return bytes(out)


def walk(ino=2, path=""):
    data = read_data(ino)
    pos = 0
    while pos + 8 <= len(data):
        child, rec_len, name_len, ftype = struct.unpack_from("<IHBB", data, pos)
        if rec_len < 8:
            break
        name = data[pos + 8:pos + 8 + name_len].decode("utf-8", "replace")
        pos += rec_len
        if not child or name in (".", ".."):
            continue
        p = f"{path}/{name}" if path else name
        mode = read_inode(child)[0] & 0xF000
        if mode == 0x4000:
            yield from walk(child, p)
        elif mode == 0x8000:
            yield p, child
        elif mode == 0xA000:
            yield p + " (symlink)", None


if cmd == "hash":
    for p, ino in walk():
        if ino is None:
            print(f"{'-' * 32}  0  {p}")
            continue
        try:
            d = read_data(ino)
        except ValueError:
            print(f"{'?' * 32}  0  {p}")
            continue
        print(f"{hashlib.md5(d).hexdigest()}  {len(d)}  {p}")
elif cmd == "grep":
    needles = [a.encode() for a in args]
    for p, ino in walk():
        if ino is None:
            continue
        try:
            d = read_data(ino)
        except ValueError:
            continue
        hits = [f"{n.decode()}x{d.count(n)}" for n in needles if n in d]
        if hits:
            print(f"{len(d):>9}  {p}  :: {' '.join(hits)}")
elif cmd == "get":
    outdir, *paths = args
    want = set(paths)
    for p, ino in walk():
        if p in want and ino is not None:
            dst = os.path.join(outdir, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(read_data(ino))
            print("got", p)
            want.discard(p)
    for p in sorted(want):
        print("MISSING", p)
