#!/bin/sh
# Gathers what tools/resume/build.sh needs, all under <build>/resume/:
#
#   devlibs/lib/      the player's base libraries (glibc 2.23, libc++, libcxxrt, ...), from the
#                     boot image's ramdisk in Sony's NW-ZX300 2.02 updater
#   devlibs/sony/     Sony's libQt5Core.so.5 and libScreenshotShared.so, from the system image
#   sysroot/          a root with all of the player's shared libraries and its busybox, for
#                     running the ARM build and the installer script under emulation
#   qt532/            QtCore headers of Qt 5.3.2 (the version on the player), from qt.io
#
#   tools/resume/prepare-inputs.sh [build directory]     (default: build/ in this project)
#
# Needs <build>/stock/NW-ZX300_V2_02.dmg (tools/prepare.sh downloads and checks it).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
TOOLS=$(cd "$HERE/.." && pwd)
BUILD=${1:-$TOOLS/../build}
BUILD=$(cd "$BUILD" && pwd)
R=$BUILD/resume
DMG=$BUILD/stock/NW-ZX300_V2_02.dmg
QT_URL=https://download.qt.io/archive/qt/5.3/5.3.2/submodules/qtbase-opensource-src-5.3.2.tar.xz
QT_SHA256=9a16095ac46dae99d6ddab8bc07065fbe1c36501ed194a3191d07347d7826cb8
[ -f "$DMG" ] || { echo "missing $DMG (run tools/prepare.sh)" >&2; exit 1; }

W=$(mktemp -d)
mounted=
cleanup() { [ -z "$mounted" ] || hdiutil detach "$W/mnt" -quiet || true; rm -rf "$W"; }
trap cleanup EXIT
mkdir "$W/mnt"
hdiutil attach -readonly -nobrowse -noautoopen -quiet -mountpoint "$W/mnt" "$DMG" 2>/dev/null
mounted=1
cp "$W/mnt/.Data/Device/NW_WM_FW.UPG" "$W/NW_WM_FW.UPG"
hdiutil detach "$W/mnt" -quiet
mounted=
# file 2 of the UPG is the boot image, file 6 the system image
"$TOOLS/upgtool-mac/upgtool" -m nw-zx300 -e -z 6 -o "$W/f" "$W/NW_WM_FW.UPG" >/dev/null

rm -rf "$R/devlibs" "$R/sysroot"
mkdir -p "$R/devlibs/lib" "$R/devlibs/sony" "$R/sysroot/system"

# --- the ramdisk's /lib: regular files and symlinks
python3 -I - "$W/f2.bin" "$R/devlibs" <<'PY'
import gzip, io, os, struct, sys
d = open(sys.argv[1], 'rb').read()
assert d[:8] == b'ANDROID!'
ksz, _, rsz, _, _, _, _, page = struct.unpack_from('<8I', d, 8)
up = lambda x: (x + page - 1) // page * page
rd = d[page + up(ksz):page + up(ksz) + rsz]
if rd[:4] == b'\x88\x16\x88\x58':          # MediaTek header in front of the ramdisk
    rd = rd[512:]
raw = gzip.GzipFile(fileobj=io.BytesIO(rd)).read()
pos = 0; links = {}; n = 0
while raw[pos:pos + 6] == b'070701':
    f = [int(raw[pos + 6 + 8 * i:pos + 14 + 8 * i], 16) for i in range(13)]
    name = raw[pos + 110:pos + 110 + f[11] - 1].decode()
    ds = (pos + 110 + f[11] + 3) & ~3
    data = raw[ds:ds + f[6]]
    pos = (ds + f[6] + 3) & ~3
    if name == 'TRAILER!!!':
        break
    if name.startswith('lib/') and name.count('/') == 1 and f[6]:
        kind = f[1] & 0o170000
        if kind == 0o120000:
            links[name] = data.decode()
        elif kind == 0o100000:
            open(os.path.join(sys.argv[2], name), 'wb').write(data); n += 1
for name, target in links.items():
    os.symlink(target, os.path.join(sys.argv[2], name))
print("ramdisk /lib: %d files, %d links" % (n, len(links)))
PY

# --- every shared library of the system image, the links to the graphics driver, and the
#     busybox that is the updater's shell (tools/userdata/test-run.sh runs the installer with it)
python3 -I "$TOOLS/ext4_walk.py" "$W/f6.bin" 0 hash | awk '{ print $3 }' |
    grep -E '^((lib|vendor/sony/lib)/[^/]+\.so(\.[0-9.]+)?|xbin/busybox)$' > "$W/libs.txt"
# shellcheck disable=SC2046
python3 -I "$TOOLS/ext4_walk.py" "$W/f6.bin" 0 get "$R/sysroot/system" $(cat "$W/libs.txt") >/dev/null
for l in libEGL.so libEGL.so.1 libEGL.so.1.4 libGLESv1_CM.so libGLESv1_CM.so.1 libGLESv1_CM.so.1.1 libGLESv2.so libGLESv2.so.2 libGLESv2.so.2.0; do
    ln -s libMali_linux.so "$R/sysroot/system/lib/$l"
done
cp -R "$R/devlibs/lib" "$R/sysroot/lib"
cp "$R/sysroot/system/vendor/sony/lib/libQt5Core.so.5" "$R/sysroot/system/vendor/sony/lib/libScreenshotShared.so" "$R/devlibs/sony/"
chmod 755 "$R/sysroot/system/xbin/busybox"
echo "system image: $(grep -c '\.so' "$W/libs.txt" | tr -d ' ') libraries and busybox"

# --- QtCore headers of Qt 5.3.2
[ -f "$R/qtbase-5.3.2.tar.xz" ] || curl -fL --progress-bar -o "$R/qtbase-5.3.2.tar.xz" "$QT_URL"
echo "$QT_SHA256  $R/qtbase-5.3.2.tar.xz" | shasum -a 256 -c - >/dev/null
rm -rf "$R/qt532" && mkdir "$R/qt532"
tar -xJf "$R/qtbase-5.3.2.tar.xz" -C "$R/qt532" --strip-components=1 \
    qtbase-opensource-src-5.3.2/include/QtCore qtbase-opensource-src-5.3.2/src/corelib qtbase-opensource-src-5.3.2/LICENSE.LGPL
find "$R/qt532/src/corelib" -type f ! -name '*.h' -delete
find "$R/qt532" -type d -empty -delete
echo "ready: $R (now run tools/resume/build.sh test)"
