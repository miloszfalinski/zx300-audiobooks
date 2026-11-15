#!/usr/bin/env python3
"""Rewrites the 64-bit time headers of an MP4/M4A file as 32-bit ones.

    mp4-short-headers.py <in.m4a> <out.m4a>
    mp4-short-headers.py --show <file>...

The Sony NW-ZX300's media scanner does not read "version 1" (64-bit) mvhd / tkhd / mdhd /
elst boxes: it drops all tags of such a file, which then shows up as "Unknown" with no
playing time. ffmpeg writes version 1 in some cases although every value would fit in
32 bits, for example when a cover picture is copied over from an .m4b together with the
audio (it then counts the length of the file in very small units). This tool rewrites those
boxes as version 0. If the length of the file does not fit in 32 bits in the units the file
uses, the units of the movie header are changed to those of the first track (exact), or to
milliseconds if that is still too long. Nothing else changes: the audio, the tags and the
cover are copied byte for byte. It refuses only if a track itself is too long for 32 bits
(2^32 samples: 27 hours at 44.1 kHz).
"""
import os
import struct
import sys

CONTAINERS = (b'moov', b'trak', b'mdia', b'edts')
TIMED = (b'mvhd', b'tkhd', b'mdhd', b'elst')


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


MILLISECONDS = 1000


def movie_times(d, start, end, out):
    """every length that is counted in the movie header's units: mvhd, tkhd, elst entries"""
    for typ, pos, size, hdr in boxes(d, start, end):
        body = d[pos + hdr:pos + size]
        if typ in CONTAINERS:
            movie_times(d, pos + hdr, pos + size, out)
        elif typ == b'mvhd':
            out['timescale'] = struct.unpack_from('>I', body, 20 if body[0] == 1 else 12)[0]
            out['lengths'].append(struct.unpack_from('>Q', body, 24)[0] if body[0] == 1 else struct.unpack_from('>I', body, 16)[0])
        elif typ == b'mdhd':
            out.setdefault('track_units', struct.unpack_from('>I', body, 20 if body[0] == 1 else 12)[0])
        elif typ == b'tkhd':
            out['lengths'].append(struct.unpack_from('>Q', body, 28)[0] if body[0] == 1 else struct.unpack_from('>I', body, 20)[0])
        elif typ == b'elst':
            for i in range(struct.unpack_from('>I', body, 4)[0]):
                out['lengths'].append(struct.unpack_from('>Q', body, 8 + 20 * i)[0] if body[0] == 1 else struct.unpack_from('>I', body, 8 + 12 * i)[0])
    return out


def shorten(typ, body, scale):
    """body = box payload starting at the version byte; returns the version 0 payload.
    scale = (new, old) movie time units, or None to leave the units alone"""
    version, flags = body[0], body[1:4]
    if version not in (0, 1):
        raise ValueError("%s has version %d" % (typ.decode(), version))
    wide = version == 1
    head = b'\x00' + flags

    def movie(v):                                    # a length in movie units
        if scale and v != 0xffffffff and v != 0xffffffffffffffff:
            v = (v * scale[0] + scale[1] // 2) // scale[1]
        if v >= 1 << 32:
            raise ValueError("a length (%d) does not fit in 32 bits" % v)
        return v

    if typ == b'mvhd':
        created, modified, timescale, duration = struct.unpack_from('>QQIQ' if wide else '>IIII', body, 4)
        rest = body[32:] if wide else body[20:]
        return head + struct.pack('>IIII', created & 0xffffffff, modified & 0xffffffff, scale[0] if scale else timescale, movie(duration)) + rest
    if typ == b'mdhd':
        created, modified, timescale, duration = struct.unpack_from('>QQIQ' if wide else '>IIII', body, 4)
        rest = body[32:] if wide else body[20:]
        if duration >= 1 << 32:
            raise ValueError("a track is too long for 32-bit headers (%d units of 1/%d s). "
                             "Split the file or re-encode it at a lower sample rate." % (duration, timescale))
        return head + struct.pack('>IIII', created & 0xffffffff, modified & 0xffffffff, timescale, duration) + rest
    if typ == b'tkhd':
        created, modified, track_id, reserved, duration = struct.unpack_from('>QQIIQ' if wide else '>IIIII', body, 4)
        rest = body[36:] if wide else body[24:]
        return head + struct.pack('>IIIII', created & 0xffffffff, modified & 0xffffffff, track_id, reserved, movie(duration)) + rest
    count = struct.unpack_from('>I', body, 4)[0]                 # elst
    out = head + struct.pack('>I', count)
    for i in range(count):
        length, start, rate = struct.unpack_from('>Qq4s', body, 8 + 20 * i) if wide else struct.unpack_from('>Ii4s', body, 8 + 12 * i)
        if not -(1 << 31) <= start < 1 << 31:
            raise ValueError("an edit list start (%d) does not fit in 32 bits" % start)
        out += struct.pack('>Ii4s', movie(length), start, rate)
    return out


def rebuild(d, start, end, changed, scale):
    out = b''
    for typ, pos, size, hdr in boxes(d, start, end):
        body = d[pos + hdr:pos + size]
        if typ in CONTAINERS:
            body = rebuild(d, pos + hdr, pos + size, changed, scale)
        elif typ in TIMED:
            new = shorten(typ, body, scale)
            if new != body:
                changed.append(typ.decode())
            body = new
        out += struct.pack('>I4s', len(body) + 8, typ) + body
    return out


def versions(d, start, end, out):
    for typ, pos, size, hdr in boxes(d, start, end):
        if typ in CONTAINERS:
            versions(d, pos + hdr, pos + size, out)
        elif typ in TIMED:
            out.append("%s v%d" % (typ.decode(), d[pos + hdr]))
    return out


def shift_offsets(moov, delta):
    """chunk offsets, when the audio data comes after the moov and so moves by delta"""
    moov = bytearray(moov)

    def walk(start, end):
        for typ, pos, size, hdr in boxes(moov, start, end):
            if typ in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                walk(pos + hdr, pos + size)
            elif typ in (b'stco', b'co64'):
                count = struct.unpack_from('>I', moov, pos + hdr + 4)[0]
                fmt, width = ('>I', 4) if typ == b'stco' else ('>Q', 8)
                for i in range(count):
                    at = pos + hdr + 8 + width * i
                    struct.pack_into(fmt, moov, at, struct.unpack_from(fmt, moov, at)[0] + delta)
    walk(0, len(moov))
    return bytes(moov)


def top_level(path):
    """(type, offset, size) of the top-level boxes, without reading the audio data"""
    out = []
    size_of_file = os.path.getsize(path)
    with open(path, 'rb') as f:
        pos = 0
        while pos + 8 <= size_of_file:
            f.seek(pos)
            h = f.read(16)
            size, typ = struct.unpack('>I4s', h[:8])
            if size == 1:
                size = struct.unpack('>Q', h[8:16])[0]
            elif size == 0:
                size = size_of_file - pos
            if size < 8:
                raise ValueError("damaged box at %d" % pos)
            out.append((typ, pos, size))
            pos += size
    return out


def read_moov(path):
    for typ, pos, size in top_level(path):
        if typ == b'moov':
            with open(path, 'rb') as f:
                f.seek(pos)
                return pos, f.read(size)
    raise ValueError("no moov box: not an MP4 file?")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == '--show':
        for p in sys.argv[2:]:
            pos, moov = read_moov(p)
            print("%s: %s" % (os.path.basename(p), ', '.join(versions(moov, 8, len(moov), []))))
        return 0
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src, dst = sys.argv[1:]
    if os.path.exists(dst):
        print("%s exists, not overwriting it" % dst, file=sys.stderr)
        return 1
    pos, moov = read_moov(src)
    changed = []
    times = movie_times(moov, 8, len(moov), {'timescale': 0, 'lengths': []})
    scale = None
    if any(v >= 1 << 32 for v in times['lengths']):         # too long in the file's units: use coarser ones
        for units in (times.get('track_units', 0), MILLISECONDS):
            if units and all(v * units // times['timescale'] < (1 << 32) - 1 for v in times['lengths']):
                scale = (units, times['timescale'])
                break
        else:
            raise ValueError("the file is too long for 32-bit headers even in milliseconds")
    body = rebuild(moov, 8, len(moov), changed, scale)
    new = struct.pack('>I4s', len(body) + 8, b'moov') + body
    delta = len(new) - len(moov)
    after = [t for t, p, s in top_level(src) if p > pos and t == b'mdat']
    if after and delta:
        new = shift_offsets(new, delta)
    with open(src, 'rb') as f, open(dst, 'wb') as g:
        left = pos
        while left:
            chunk = f.read(min(left, 1 << 20))
            g.write(chunk)
            left -= len(chunk)
        g.write(new)
        f.seek(pos + len(moov))
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            g.write(chunk)
    if changed:
        print("%s: rewrote %s as 32-bit%s (%d bytes shorter)" % (os.path.basename(dst), ', '.join(changed),
              ", lengths now in units of 1/%d s" % scale[0] if scale else "", -delta))
    else:
        print("%s: no 64-bit time headers, copied unchanged" % os.path.basename(dst))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)
