#!/bin/sh
# Pack a userdata.tar.gz (run.sh + files, see nw-installer) into a flashable
# NW_WM_FW.UPG, natively on macOS: no Docker, no cross toolchain.
#
#   ./pack.sh <userdata.tar.gz> [output directory]      (MODEL=nw-zx300 by default)
#
# The UPG also carries six small ARM helper programs that run on the player.
# nw-installer cross-compiles them in Docker; here they are taken out of the
# official fix-coverart release UPG instead (they are the same in every
# nw-installer based release). install.sh and update.sh come from the pinned
# nw-installer checkout made by build.sh.
set -eu
[ $# -ge 1 ] || { echo "usage: $0 <userdata.tar.gz> [output directory]" >&2; exit 2; }
USERDATA=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
OUT=${2:-.}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
MODEL=${MODEL:-nw-zx300}
cd "$(dirname "$0")"
[ -x ./upgtool ] || ./build.sh
B="$PWD/build"
REF_URL=https://github.com/unknown321/fix-coverart/releases/download/v1.0.2/nw-zx300.tar.gz
REF_SHA256=199d3d6ae3ce6c9495eed5caa8fb82917e159de96666fcd308582347851862df
HELPERS="cpiostrip mtkheader cpio gzip abootimg upgtool"

if [ ! -f "$B/helpers/upgtool-linux-arm5" ]; then
    mkdir -p "$B/ref" "$B/helpers"
    curl -fsSL -o "$B/ref/nw-zx300.tar.gz" "$REF_URL"
    echo "$REF_SHA256  $B/ref/nw-zx300.tar.gz" | shasum -a 256 -c -
    tar -xzf "$B/ref/nw-zx300.tar.gz" -C "$B/ref"
    ./upgtool -n -m nw-zx300 -e -o "$B/ref/f" "$B/ref/NW_WM_FW.UPG" >/dev/null
    # order inside the UPG: install.sh, empty.txt, the six helpers, update.sh, userdata
    i=2
    for name in $HELPERS; do
        cp "$B/ref/f$i.bin" "$B/helpers/$name-linux-arm5"
        i=$((i + 1))
    done
fi

W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
cp "$B/nw-installer/installer/install.sh" "$B/nw-installer/installer/empty.txt" \
    "$B/nw-installer/installer/update.sh" "$B"/helpers/*-linux-arm5 "$W/"
cp "$USERDATA" "$W/userdata.tar.gz"
# the file order is fixed, install.sh on the player reads them by index
(cd "$W" && "$OLDPWD/upgtool" -n -c "$OUT/NW_WM_FW.UPG" -m "$MODEL" \
    install.sh empty.txt \
    cpiostrip-linux-arm5 mtkheader-linux-arm5 cpio-linux-arm5 gzip-linux-arm5 \
    abootimg-linux-arm5 upgtool-linux-arm5 \
    update.sh userdata.tar.gz >/dev/null)
echo "wrote $OUT/NW_WM_FW.UPG ($MODEL)"
