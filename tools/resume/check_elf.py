#!/usr/bin/env python3
"""Checks the ARM builds of the loader and the resume module against the player's own libraries.

Run inside the build container (tools/resume/build.sh test does that):
    check_elf.py <dir with the built .so files> <devlibs dir>

Fails unless, for each built library:
  - every library it needs exists on the player (or is one of the files installed with it);
  - every symbol it imports is exported by one of those, with the same version;
  - it is an ARM hard-float shared object, like the player's libraries.
"""
import os, re, subprocess, sys

READELF = 'arm-linux-gnueabihf-readelf'
out_dir, dev = sys.argv[1], sys.argv[2]

def readelf(*args):
    return subprocess.run([READELF, '-W', *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True).stdout

def soname(path):
    m = re.search(r'\(SONAME\)\s+Library soname: \[(.+?)\]', readelf('-d', path))
    return m.group(1) if m else os.path.basename(path)

def needed(path):
    return re.findall(r'\(NEEDED\)\s+Shared library: \[(.+?)\]', readelf('-d', path))

def dynsyms(path):
    """-> (defined {name: {versions}}, undefined [(name, version or None, weak)])"""
    defined, undefined = {}, []
    for line in readelf('--dyn-syms', path).splitlines():
        f = line.split()
        if len(f) < 8 or not f[0].rstrip(':').isdigit():
            continue
        bind, ndx, name = f[4], f[6], f[7]
        ver = None
        if '@' in name:
            name, ver = re.split(r'@+', name, 1)
        if ndx == 'UND':
            if name:
                undefined.append((name, ver, bind == 'WEAK'))
        elif bind in ('GLOBAL', 'WEAK'):
            defined.setdefault(name, set()).add(ver)
    return defined, undefined

# everything the player provides, by soname
player = {}
for root, _, files in os.walk(dev):
    for fn in files:
        p = os.path.join(root, fn)
        if os.path.islink(p) or '.so' not in fn:
            continue
        with open(p, 'rb') as fh:
            if fh.read(4) != b'\x7fELF':
                continue
        player[soname(p)] = p
built = {soname(os.path.join(out_dir, fn)): os.path.join(out_dir, fn) for fn in sorted(os.listdir(out_dir)) if fn.endswith('.so')}
print("built:", ", ".join("{} (soname {})".format(os.path.basename(p), s) for s, p in built.items()))

ok = True
for name in ('libScreenshotShared.so', 'libaudiobookresume.so'):
    path = built[name]
    print("\n== " + os.path.basename(path))
    attrs = readelf('-A', path)
    hdr = readelf('-h', path)
    hard = 'Tag_ABI_VFP_args: VFP registers' in attrs
    arm = 'Machine:' in hdr and 'ARM' in hdr and 'DYN (Shared object file)' in hdr
    print("   ARM shared object: {}; hard-float calling convention: {}".format(arm, hard))
    ok &= arm and hard
    libs = needed(path)
    providers = {}
    for lib in libs:
        where = built.get(lib) or player.get(lib)
        print("   needs {:<26} {}".format(lib, 'installed with it' if lib in built else 'on the player' if where else 'MISSING'))
        if not where:
            ok = False
            continue
        providers[lib] = dynsyms(where)[0]
    # a library's dependencies are in scope too (the original library needs Qt etc.), but
    # only direct providers are accepted here, which is stricter than the dynamic loader
    _, und = dynsyms(path)
    missing = []
    for sym, ver, weak in und:
        hit = [lib for lib, d in providers.items() if sym in d and (ver is None or ver in d[sym] or None in d[sym])]
        if not hit and not weak:
            missing.append(sym + ('@' + ver if ver else ''))
    print("   imports {} symbols; not provided by the player: {}".format(len(und), missing or 'none'))
    ok &= not missing
    vers = sorted(set(v for _, v, _ in und if v))
    print("   symbol versions required: " + (', '.join(vers) or 'none'))
print("\nCHECKS PASSED" if ok else "\nCHECKS FAILED")
sys.exit(0 if ok else 1)
