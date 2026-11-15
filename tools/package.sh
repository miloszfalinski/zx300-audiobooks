#!/bin/sh
# Packs the installer and the uninstaller.
#
#   tools/package.sh [build directory]        (default: build/ in this project)
#
# Result:
#   <build>/install/NW_WM_FW.UPG      edits Sony's files on the player and adds the two
#                                     libraries of the resume add-on
#   <build>/uninstall/NW_WM_FW.UPG    undoes the edits and removes the added files
#   (next to each: the userdata.tar.gz it carries)
#
# Neither package contains a file of Sony's: see tools/userdata/run.sh.
#
# It refuses to pack unless <build>/files is exactly Sony's files plus the intended edits
# (tools/prepare.sh makes them) and the libraries built by tools/resume/build.sh.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=${1:-$HERE/../build}
BUILD=$(cd "$BUILD" && pwd)
STOCK=$BUILD/stock/files
NEW=$BUILD/files
ETC=vendor/sony/etc
SO=vendor/sony/lib/libInitialObject.so
QM=vendor/sony/translations/HgrmMediaPlayerApp_en_US.qm
APP=vendor/sony/bin/HgrmMediaPlayerApp
XMLS="$ETC/default-capability_w_internal.xml $ETC/default-capability_w_external0.xml
$ETC/default-capability_j_internal.xml $ETC/default-capability_j_external0.xml"
# Audiobooks resume add-on: Sony's libScreenshotShared.so moves
# to a new name, a loader takes its place, and the resume module is added.
CARRIER=vendor/sony/lib/libScreenshotShared.so
ORIGIN=vendor/sony/lib/libScreenshotOrigin.so
RESUME=vendor/sony/lib/libaudiobookresume.so
RESUME_OUT=$BUILD/resume/out/device
# (the order of the steps on the player is set in tools/make_plan.py)

die() { echo "not packaging: $*" >&2; exit 1; }

(cd "$STOCK" && shasum -a 256 -c "$HERE/stock-files.sha256" >/dev/null 2>&1) ||
    die "$STOCK is not Sony's v2.02 files (run tools/prepare.sh)"

# cmp -l prints "<offset, counted from 1> <old byte> <new byte>" in decimal, octal, octal
d=$(cmp -l "$STOCK/$SO" "$NEW/$SO" 2>&1 | awk '{ $1 = $1; print }')
# libInitialObject.so: one byte at file offset 0x60f0, 00 -> 01 (LanguageLearningAvailable)
[ -n "$d" ] || die "$SO is still the stock file"
[ "$d" = "24817 0 1" ] ||
    die "$SO does not differ from stock by the one intended byte (cmp -l: $d)"

for x in $XMLS; do
    d=$(diff "$STOCK/$x" "$NEW/$x" | grep '^[<>]' || true)
    [ "$d" = '>         <learning>\LEARNING\</learning>' ] ||
        die "$x is not the stock file plus the one <learning> line"
done

[ "$(stat -f %z "$STOCK/$QM")" = "$(stat -f %z "$NEW/$QM")" ] || die "$QM changed size"
if cmp -s "$STOCK/$QM" "$NEW/$QM"; then
    echo "label: stock (\"Language Study\")"
else
    left=$(python3 -I "$HERE/qm_rename.py" "$NEW/$QM" /dev/null scan | tail -1)
    [ "$left" = "translations edited: 0" ] || die "$QM is only partly renamed ($left)"
    echo "label: renamed to \"Audiobooks\""
fi

# app: stock plus two patches.
#  - feature table (file offset 0x7e3f1, 20 -> 30): the static initializer stores
#    key 2 (Language Study) with "strb.w r3" (true) instead of "strb.w r2" (false),
#    as the NW-A50 build does. Without it the Language Study screen creator reports
#    "not available" and every one of its screens is replaced by Blank.qml.
#  - isAvailableLangStudy getter (file offset 0x1de9c4, 4 bytes): forced to
#    "movs r0,#1; bx lr". This is what makes the button appear on the home screen.
#    Possibly redundant once the table is right; kept because this pair is the one
#    tested on a player.
da=$(cmp -l "$STOCK/$APP" "$NEW/$APP" 2>&1 | awk '{ $1 = $1; print }')
[ -n "$da" ] || die "$APP is still the stock file"
[ "$da" = "517106 40 60
1960389 200 1
1960390 265 40
1960391 157 160
1960392 106 107" ] || die "$APP does not differ from stock by the 5 bytes of the two app patches (cmp -l: $da)"

# resume add-on: exactly what tools/resume/build.sh built (and tested), and Sony's library
# under its new name differs from Sony's file only in the six letters of its own name
for f in $ORIGIN $RESUME $CARRIER; do
    cmp -s "$RESUME_OUT/$(basename "$f")" "$NEW/$f" ||
        die "$f is not the file built by tools/resume/build.sh (run tools/resume/build.sh test)"
done
[ "$(cmp -l "$STOCK/$CARRIER" "$NEW/$ORIGIN" | wc -l | tr -d ' ')" = 6 ] ||
    die "$ORIGIN is not Sony's $CARRIER with only its recorded name changed"
file -b "$NEW/$CARRIER" "$NEW/$RESUME" | grep -vq 'ELF 32-bit LSB shared object, ARM' &&
    die "the resume libraries are not ARM shared objects"

echo "checks passed: library patched, 4 XMLs edited, app feature table + icon gate patched, resume add-on in place"

W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT

# pack install|uninstall <output directory>
#
# A package holds run.sh, plan.txt (the edits, with a checksum for every result) and, for
# the installer, the two libraries of the resume add-on. None of Sony's files go in: they
# are edited on the player. tools/make_plan.py checks each edit list against the files here.
pack() {
    T=$W/$1
    mkdir -p "$T" "$2"
    cp "$HERE/userdata/run.sh" "$T/run.sh"
    chmod 755 "$T/run.sh"
    python3 -I "$HERE/make_plan.py" "$1" "$STOCK" "$NEW" "$T/plan.txt"
    parts="run.sh plan.txt"
    want=2
    if [ "$1" = install ]; then
        for f in $RESUME $CARRIER; do
            mkdir -p "$T/files/$(dirname "$f")"
            cp "$NEW/$f" "$T/files/$f"
            chmod 755 "$T/files/$f"
        done
        parts="run.sh plan.txt files files/vendor files/vendor/sony files/vendor/sony/lib files/$RESUME files/$CARRIER"
        want=4
    fi
    # Plain ustar, owned by root, none of the "._*" metadata files macOS tar adds. The same
    # input gives the same archive byte for byte: fixed order, fixed dates, no date in the
    # gzip header.
    find "$T" -exec env TZ=UTC touch -t 202601010000 {} +
    # shellcheck disable=SC2086
    COPYFILE_DISABLE=1 tar --format ustar --no-xattrs --no-mac-metadata --no-acls \
        --uid 0 --gid 0 --uname root --gname root \
        -cf - -n -C "$T" $parts | gzip -n -9 > "$2/userdata.tar.gz"
    n=$(tar -tzf "$2/userdata.tar.gz" | grep -vc '/$')
    [ "$n" = "$want" ] || die "$2/userdata.tar.gz holds $n files, expected $want"
    # nothing of Sony's: only the script, the plan and our two libraries
    extra=$(tar -tzf "$2/userdata.tar.gz" | grep -v '/$' |
        grep -vxE "run.sh|plan.txt|files/$RESUME|files/$CARRIER" || true)
    [ -z "$extra" ] || die "$2/userdata.tar.gz holds files that should not be shipped: $extra"
    "$HERE/upgtool-mac/pack.sh" "$2/userdata.tar.gz" "$2"
    # read the UPG back: 10 files, and the last one is the archive just made
    # (a UPG pads each file with zeros to a multiple of 4096 bytes)
    "$HERE/upgtool-mac/upgtool" -n -m nw-zx300 -e -o "$T/f" "$2/NW_WM_FW.UPG" >/dev/null
    [ "$(find "$T" -maxdepth 1 -name 'f*.bin' | wc -l | tr -d ' ')" = 10 ] || die "$2/NW_WM_FW.UPG: wrong file count"
    size=$(stat -f %z "$2/userdata.tar.gz")
    head -c "$size" "$T/f9.bin" | cmp -s - "$2/userdata.tar.gz" || die "$2/NW_WM_FW.UPG does not read back correctly"
    [ "$(tail -c +$((size + 1)) "$T/f9.bin" | tr -d '\000' | wc -c | tr -d ' ')" = 0 ] ||
        die "$2/NW_WM_FW.UPG: unexpected data after the archive"
    # ...and that padded copy must still unpack, as it has to on the player
    [ "$(tar -tzf "$T/f9.bin" 2>/dev/null | grep -vc '/$')" = "$want" ] || die "$2/NW_WM_FW.UPG: archive does not unpack"
}

pack install "$BUILD/install"
pack uninstall "$BUILD/uninstall"
echo
md5 -r "$BUILD/install/NW_WM_FW.UPG" "$BUILD/uninstall/NW_WM_FW.UPG"
