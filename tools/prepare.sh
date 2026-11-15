#!/bin/sh
# Gets Sony's files out of the NW-ZX300 v2.02 updater and makes the edits to them.
# Every download and every extracted file is checked against a pinned checksum.
#
#   tools/prepare.sh [build directory]        (default: build/ in this project)
#
# Result:
#   <build>/stock/NW-ZX300_V2_02.dmg   Sony's updater (also the way back to stock)
#   <build>/stock/files/...            Sony's files exactly as shipped
#   <build>/files/...                  working copies with the edits:
#                                        libInitialObject.so   1 byte  (creates the LEARNING library)
#                                        4 capability XMLs     1 line  (declares the LEARNING folder)
#                                        English .qm           label "Language Study" -> "Audiobooks"
#                                        HgrmMediaPlayerApp    5 bytes (turns the feature on)
#
# The libraries of the resume add-on are built separately: tools/resume/build.sh.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=${1:-$HERE/../build}
URL=http://walkman.update.sony.net/fw/pc/ZX300/NW-ZX300_V2_02.dmg
DMG_SHA256=7704f294eb7e9532259e4f21c8bde9640913911ad938280d393f73361dfffa89
UPG_SHA256=a7be1b14505a50338caeb5c613a04aa93cdb2f219eb2b97f0243322ffb7d5a68
ETC=vendor/sony/etc
SO=vendor/sony/lib/libInitialObject.so
QM=vendor/sony/translations/HgrmMediaPlayerApp_en_US.qm
APP=vendor/sony/bin/HgrmMediaPlayerApp
CARRIER=vendor/sony/lib/libScreenshotShared.so
XMLS="$ETC/default-capability_w_internal.xml $ETC/default-capability_w_external0.xml
$ETC/default-capability_j_internal.xml $ETC/default-capability_j_external0.xml"

if [ -e "$BUILD/files" ]; then
    echo "$BUILD/files already exists. Not touching it (it may hold the patched library)." >&2
    exit 1
fi
[ -x "$HERE/upgtool-mac/upgtool" ] || "$HERE/upgtool-mac/build.sh"
mkdir -p "$BUILD/stock"
BUILD=$(cd "$BUILD" && pwd)

DMG=$BUILD/stock/NW-ZX300_V2_02.dmg
[ -f "$DMG" ] || curl -fL --progress-bar -o "$DMG" "$URL"
echo "$DMG_SHA256  $DMG" | shasum -a 256 -c - >/dev/null
echo "updater image: checksum ok"

W=$(mktemp -d)
mounted=
cleanup() {
    [ -z "$mounted" ] || hdiutil detach "$W/mnt" -quiet || true
    rm -rf "$W"
}
trap cleanup EXIT
mkdir "$W/mnt"
hdiutil attach -readonly -nobrowse -noautoopen -quiet -mountpoint "$W/mnt" "$DMG" 2>/dev/null
mounted=1
cp "$W/mnt/.Data/Device/NW_WM_FW.UPG" "$W/NW_WM_FW.UPG"
hdiutil detach "$W/mnt" -quiet
mounted=
echo "$UPG_SHA256  $W/NW_WM_FW.UPG" | shasum -a 256 -c - >/dev/null

# file 6 of the UPG is the system partition; file 1 is Sony's list "<size> <md5> <name>"
"$HERE/upgtool-mac/upgtool" -m nw-zx300 -e -z 6 -o "$W/f" "$W/NW_WM_FW.UPG" >/dev/null
want=$(tr -d '\000' < "$W/f1.bin" | awk '$3 == "system.img" { print $2 }')
have=$(md5 -q "$W/f6.bin")
[ -n "$want" ] && [ "$want" = "$have" ] || { echo "system image: md5 $have, Sony lists $want" >&2; exit 1; }
echo "system image: matches Sony's own md5"

rm -rf "$BUILD/stock/files"
# shellcheck disable=SC2086
python3 -I "$HERE/ext4_get.py" "$W/f6.bin" "$BUILD/stock/files" $SO $XMLS $QM $APP $CARRIER >/dev/null
(cd "$BUILD/stock/files" && shasum -a 256 -c "$HERE/stock-files.sha256" >/dev/null)
chmod 755 "$BUILD/stock/files/$SO" "$BUILD/stock/files/$APP" "$BUILD/stock/files/$CARRIER"
echo "stock files: extracted, checksums ok"

cp -R "$BUILD/stock/files" "$BUILD/files"

# step C: one line, right before </path>, exactly as the NW-A50's files have it
for x in $XMLS; do
    python3 -I - "$BUILD/files/$x" <<'PY'
import sys
p = sys.argv[1]
s = open(p, newline="").read()
close = "      </path>\n"
line = "        <learning>\\LEARNING\\</learning>\n"
assert s.count(close) == 1 and "<learning>" not in s, p
open(p, "w", newline="").write(s.replace(close, line + close))
PY
    xmllint --noout "$BUILD/files/$x"
done
echo "capability XMLs: <learning> line added to 4 files"

# step D: label
python3 -I "$HERE/qm_rename.py" "$BUILD/files/$QM" "$BUILD/files/$QM.new" write | tail -2
mv "$BUILD/files/$QM.new" "$BUILD/files/$QM"

# libInitialObject.so: DeviceInfo::LanguageLearningAvailable writes 0; make it write 1
# (file offset 0x60f0, "movs r0,#0" -> "movs r0,#1"; the NW-A50 build has 1 here)
[ "$(xxd -s $((0x60f0)) -l 2 -p "$BUILD/files/$SO")" = 0020 ] || { echo "$SO: unexpected bytes at 0x60f0" >&2; exit 1; }
printf '\001' | dd of="$BUILD/files/$SO" bs=1 seek=$((0x60f0)) count=1 conv=notrunc 2>/dev/null
echo "libInitialObject.so: 1 byte patched"

# HgrmMediaPlayerApp, two places (see tools/package.sh for what they do):
#  0x7e3f1   20 -> 30            feature table: Language Study = true
#  0x1de9c4  80 b5 6f 46 -> 01 20 70 47   isAvailableLangStudy returns 1
[ "$(xxd -s $((0x7e3ee)) -l 4 -p "$BUILD/files/$APP")" = 8df86420 ] || { echo "$APP: unexpected bytes at 0x7e3ee" >&2; exit 1; }
[ "$(xxd -s $((0x1de9c4)) -l 4 -p "$BUILD/files/$APP")" = 80b56f46 ] || { echo "$APP: unexpected bytes at 0x1de9c4" >&2; exit 1; }
printf '\060' | dd of="$BUILD/files/$APP" bs=1 seek=$((0x7e3f1)) count=1 conv=notrunc 2>/dev/null
printf '\001\040\160\107' | dd of="$BUILD/files/$APP" bs=1 seek=$((0x1de9c4)) count=4 conv=notrunc 2>/dev/null
echo "HgrmMediaPlayerApp: 5 bytes patched"

echo
echo "Ready in $BUILD/files. Next: tools/resume/prepare-inputs.sh and tools/resume/build.sh test"
echo "(the resume add-on), then tools/package.sh."
