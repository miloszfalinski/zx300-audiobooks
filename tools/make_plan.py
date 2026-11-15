#!/usr/bin/env python3
"""Writes plan.txt for tools/userdata/run.sh: the steps that turn Sony's files on the player
into the modified ones (install) or back (uninstall), as small edits with checksums.

    make_plan.py install|uninstall <stock dir> <modified dir> <plan.txt>

No file content of Sony's goes into an install plan except the bytes that the edits write,
which are ours. An uninstall plan carries the few original bytes it has to put back.
Every edit list is applied here to the starting file and compared with the target before it
is written out, so a plan that this script produces is known to give the right result.
"""
import hashlib
import sys

ETC = 'vendor/sony/etc/'
PATCHED = [                                     # Sony's files that are edited in place
    'vendor/sony/lib/libInitialObject.so',
    ETC + 'default-capability_w_internal.xml',
    ETC + 'default-capability_w_external0.xml',
    ETC + 'default-capability_j_internal.xml',
    ETC + 'default-capability_j_external0.xml',
    'vendor/sony/translations/HgrmMediaPlayerApp_en_US.qm',
    'vendor/sony/bin/HgrmMediaPlayerApp',
]
CARRIER = 'vendor/sony/lib/libScreenshotShared.so'   # Sony's; our loader takes its place
ORIGIN = 'vendor/sony/lib/libScreenshotOrigin.so'    # Sony's library under its new name
RESUME = 'vendor/sony/lib/libaudiobookresume.so'     # ours


def md5(b):
    return hashlib.md5(b).hexdigest()


def octal(b):
    return ''.join('\\%03o' % x for x in b)


def edits(a, b):
    """Edit steps that turn bytes a into bytes b, highest offset first."""
    out = []
    if len(a) == len(b):
        i = 0
        while i < len(a):
            if a[i] == b[i]:
                i += 1
                continue
            j = i + 1
            # one run: stretch over gaps of up to 3 equal bytes
            while j < len(a) and (a[j] != b[j] or a[j:j + 4] != b[j:j + 4]):
                j += 1
            while a[j - 1] == b[j - 1]:
                j -= 1
            out.append(('put', i, b[i:j]))
            i = j
    else:
        p = 0
        while p < min(len(a), len(b)) and a[p] == b[p]:
            p += 1
        s = 0
        while s < min(len(a), len(b)) - p and a[len(a) - 1 - s] == b[len(b) - 1 - s]:
            s += 1
        if len(a) - s > p:
            out.append(('cut', p, len(a) - s - p))
        if len(b) - s > p:
            out.append(('add', p, b[p:len(b) - s]))
    out.sort(key=lambda e: -e[1])
    # stable sort keeps "cut" before "add" at the same offset, which is the order they need
    return out


def apply(a, steps):
    a = bytearray(a)
    for op, off, arg in steps:
        if op == 'put':
            a[off:off + len(arg)] = arg
        elif op == 'add':
            a[off:off] = arg
        else:
            del a[off:off + arg]
    return bytes(a)


def edit_block(path, start_path, start, target):
    steps = edits(start, target)
    assert apply(start, steps) == target, path
    lines = ['edit %s %s %s' % (path, md5(target), start_path)]
    for op, off, arg in steps:
        lines.append('  %s %d %s' % (op, off, arg if op == 'cut' else octal(arg)))
    lines.append('end')
    return lines


def main():
    mode, stock_dir, new_dir, out = sys.argv[1:5]
    read = lambda d, p: open(d + '/' + p, 'rb').read()
    stock = {p: read(stock_dir, p) for p in PATCHED + [CARRIER]}
    new = {p: read(new_dir, p) for p in PATCHED + [CARRIER, ORIGIN, RESUME]}
    lines = []
    if mode == 'install':
        for p in PATCHED:
            lines += edit_block(p, p, stock[p], new[p])
        # what the loader needs goes in before the loader itself
        lines += edit_block(ORIGIN, CARRIER, stock[CARRIER], new[ORIGIN])
        lines.append('copy %s %s' % (RESUME, md5(new[RESUME])))
        lines.append('copy %s %s' % (CARRIER, md5(new[CARRIER])))
    elif mode == 'uninstall':
        for p in PATCHED:
            lines += edit_block(p, p, new[p], stock[p])
        # Sony's library goes back under its own name before the added files are removed
        lines += edit_block(CARRIER, ORIGIN, new[ORIGIN], stock[CARRIER])
        lines.append('remove %s' % ORIGIN)
        lines.append('remove %s' % RESUME)
    else:
        sys.exit('install or uninstall')
    open(out, 'w').write('\n'.join(lines) + '\n')
    n = sum(1 for l in lines if l.startswith('  '))
    size = sum(len(l) for l in lines)
    print('%s plan: %d steps, %d edits, %d bytes' % (mode, sum(1 for l in lines if l[0] != ' ' and l != 'end'), n, size))


if __name__ == '__main__':
    main()
