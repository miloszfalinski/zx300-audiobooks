#!/usr/bin/env python3
"""Replaces a progressive JPEG cover inside an MP4/M4A file with a baseline JPEG.

    mp4-baseline-cover.py <in.m4a> <out.m4a>
    mp4-baseline-cover.py --show <file>...

The Sony NW-ZX300 shows an embedded cover that is a baseline JPEG and does not show one
that is a progressive JPEG. This tool rewrites only the picture: the audio and all other
tags are copied byte for byte.

The picture is converted with jpegtran when it is installed (lossless: the same picture,
stored the other way; `brew install jpeg-turbo`), and otherwise with macOS's sips, which
encodes it again. A file whose cover is already baseline, or that has no JPEG cover, is
copied unchanged.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

COVER_PATH = (b'moov', b'udta', b'meta', b'ilst', b'covr')
OFFSET_PARENTS = (b'moov', b'trak', b'mdia', b'minf', b'stbl')
JPEG_KINDS = {0xc0: 'baseline', 0xc1: 'extended sequential', 0xc2: 'progressive'}


def boxes(d, start, end):
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack_from('>I4s', d, pos)
        hdr = 8
        if size == 1:
            size = struct.unpack_from('>Q', d, pos + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            raise ValueError("damaged box %r at %d" % (typ, pos))
        yield typ, pos, size, hdr
        pos += size


def top_boxes(f, length):
    """(type, position, size) of the boxes of the file, without reading their contents"""
    out = []
    pos = 0
    while pos + 8 <= length:
        f.seek(pos)
        size, typ = struct.unpack('>I4s', f.read(8))
        if size == 1:
            size = struct.unpack('>Q', f.read(8))[0]
        elif size == 0:
            size = length - pos
        if size < 8 or pos + size > length:
            raise ValueError("damaged box %r at %d" % (typ, pos) if pos else "not an MP4 file")
        out.append((typ, pos, size))
        pos += size
    return out


def find_cover(moov):
    """the chain of boxes from moov down to covr, as (position, size, header size), and the
    first picture in it as (position, size, type flag)"""
    chain = []
    start, end = 0, len(moov)
    for want in COVER_PATH:
        for typ, pos, size, hdr in boxes(moov, start, end):
            if typ == want:
                chain.append((pos, size, hdr))
                start, end = pos + hdr + (4 if typ == b'meta' else 0), pos + size
                break
        else:
            return None, None
    for typ, pos, size, hdr in boxes(moov, start, end):
        if typ == b'data' and size >= hdr + 8:
            return chain, (pos, size, hdr, struct.unpack_from('>I', moov, pos + hdr)[0] & 0xffffff)
    return None, None


def describe(picture):
    """(kind, width, height) of a picture"""
    if picture[:8] == b'\x89PNG\r\n\x1a\n':
        width, height = struct.unpack_from('>II', picture, 16)
        return ('interlaced PNG' if picture[28] else 'PNG'), width, height
    if picture[:2] != b'\xff\xd8':
        return 'not a JPEG or PNG', 0, 0
    pos = 2
    while pos + 4 <= len(picture) and picture[pos] == 0xff:
        marker = picture[pos + 1]
        if marker in (0xd8, 0x01) or 0xd0 <= marker <= 0xd7:
            pos += 2
            continue
        length = struct.unpack_from('>H', picture, pos + 2)[0]
        if 0xc0 <= marker <= 0xcf and marker not in (0xc4, 0xc8, 0xcc):
            height, width = struct.unpack_from('>HH', picture, pos + 5)
            return JPEG_KINDS.get(marker, 'JPEG of an unusual kind') + ' JPEG', width, height
        if marker == 0xda:
            break
        pos += 2 + length
    return 'JPEG without a frame header', 0, 0


def to_baseline(picture):
    """the picture as a baseline JPEG, and the name of the program that made it"""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, 'in.jpg'), os.path.join(tmp, 'out.jpg')
        with open(src, 'wb') as f:
            f.write(picture)
        if shutil.which('jpegtran'):
            how = 'jpegtran, lossless'
            subprocess.run(['jpegtran', '-copy', 'all', '-outfile', dst, src], check=True)
        elif shutil.which('sips'):
            # by way of a PNG: straight from a progressive JPEG, sips writes a progressive one again
            how = 'sips, encoded again'
            mid = os.path.join(tmp, 'mid.png')
            subprocess.run(['sips', '-s', 'format', 'png', src, '--out', mid],
                           check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '90', mid, '--out', dst],
                           check=True, stdout=subprocess.DEVNULL)
        else:
            raise ValueError("neither jpegtran nor sips is installed")
        with open(dst, 'rb') as f:
            new = f.read()
    if describe(new)[0] != 'baseline JPEG':
        raise ValueError("the converted picture is not a baseline JPEG")
    return new, how


def shift_offsets(moov, delta):
    """chunk offsets, when the audio data comes after the moov and so moves by delta"""
    def walk(start, end):
        for typ, pos, size, hdr in boxes(moov, start, end):
            if typ in OFFSET_PARENTS:
                walk(pos + hdr, pos + size)
            elif typ in (b'stco', b'co64'):
                count = struct.unpack_from('>I', moov, pos + hdr + 4)[0]
                fmt, width = ('>I', 4) if typ == b'stco' else ('>Q', 8)
                for i in range(count):
                    at = pos + hdr + 8 + i * width
                    value = struct.unpack_from(fmt, moov, at)[0] + delta
                    if not 0 <= value < 1 << (8 * width):
                        raise ValueError("a chunk offset does not fit after the change")
                    struct.pack_into(fmt, moov, at, value)
    walk(0, len(moov))


def read_moov(f, length):
    tops = top_boxes(f, length)
    found = [(pos, size) for typ, pos, size in tops if typ == b'moov']
    if not found:
        raise ValueError("no moov box: not an MP4 file")
    pos, size = found[0]
    f.seek(pos)
    return tops, pos, bytearray(f.read(size))


def show(path):
    with open(path, 'rb') as f:
        tops, pos, moov = read_moov(f, os.path.getsize(path))
    chain, data = find_cover(moov)
    if not data:
        return "no cover in the file"
    dpos, dsize, dhdr, flag = data
    picture = bytes(moov[dpos + dhdr + 8:dpos + dsize])
    kind, width, height = describe(picture)
    return "%s, %d x %d, %d bytes" % (kind, width, height, len(picture))


def convert(src, dst):
    length = os.path.getsize(src)
    with open(src, 'rb') as f:
        tops, moov_pos, moov = read_moov(f, length)
        chain, data = find_cover(moov)
        kind = None
        if data:
            dpos, dsize, dhdr, flag = data
            picture = bytes(moov[dpos + dhdr + 8:dpos + dsize])
            kind = describe(picture)[0]
        if kind != 'progressive JPEG':
            shutil.copyfile(src, dst)
            return "%s, copied unchanged" % ("the cover is a " + kind if kind else "no cover in the file")
        new, how = to_baseline(picture)
        delta = len(new) - len(picture)
        old_size = len(moov)
        moov[dpos + dhdr + 8:dpos + dsize] = new
        for pos, size, hdr in chain + [(dpos, dsize, dhdr)]:      # every box around the picture
            if hdr == 16:
                struct.pack_into('>Q', moov, pos + 8, size + delta)
            else:
                if size + delta >= 1 << 32:
                    raise ValueError("a box grows past 4 GB")
                struct.pack_into('>I', moov, pos, size + delta)
        if any(typ == b'mdat' and pos > moov_pos for typ, pos, size in tops):
            shift_offsets(moov, delta)
        with open(dst, 'wb') as out:
            f.seek(0)
            left = moov_pos
            while left:
                block = f.read(min(left, 1 << 22))
                out.write(block)
                left -= len(block)
            out.write(moov)
            f.seek(moov_pos + old_size)
            shutil.copyfileobj(f, out, 1 << 22)
    return "cover rewritten as baseline JPEG (%s): %d -> %d bytes" % (how, len(picture), len(new))


def main(argv):
    if len(argv) >= 3 and argv[1] == '--show':
        for path in argv[2:]:
            print("%s: %s" % (os.path.basename(path), show(path)))
        return 0
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    src, dst = argv[1], argv[2]
    if os.path.exists(dst):
        sys.stderr.write("%s exists already, not overwriting it\n" % dst)
        return 1
    try:
        print("%s: %s" % (os.path.basename(dst), convert(src, dst)))
    except (ValueError, subprocess.CalledProcessError, struct.error) as e:
        if os.path.exists(dst):
            os.remove(dst)
        sys.stderr.write("%s: %s\n" % (os.path.basename(src), e))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
