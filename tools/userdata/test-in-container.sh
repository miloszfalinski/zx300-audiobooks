#!/bin/bash
# Runs inside the zx300-resume-build container (tools/userdata/test-run.sh starts it).
# Executes tools/userdata/run.sh exactly as packed in build/{install,uninstall}/userdata.tar.gz
# with the player's own shell and tools: busybox 1.23.1 from the 2.02 firmware, run under
# qemu-user, both as the shell (ash) and for every applet the script calls. Only BB and SYS
# are redirected, and mount/umount are stubbed. The /system trees are simulated.
#
#   test-in-container.sh [earlier build]    a folder laid out like build/files that holds an
#                                           earlier build of the three add-on libraries
#                                           (path inside the project); used to test replacing it
set -eu
P=/work
ROOT=$P/build/resume/sysroot
BBREAL=$ROOT/system/xbin/busybox
[ -x "$BBREAL" ] || { echo "missing $BBREAL (run tools/resume/prepare-inputs.sh)"; exit 1; }
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
printf '#!/bin/sh\nexec qemu-arm-static -L %s -E LD_LIBRARY_PATH=/system/lib:/lib %s "$@"\n' "$ROOT" "$BBREAL" > "$T/bin/busybox"
chmod +x "$T/bin/busybox"
echo "shell and tools: $("$T/bin/busybox" | head -1)"

L=vendor/sony/lib
APP=vendor/sony/bin/HgrmMediaPlayerApp
SONY="$L/libInitialObject.so vendor/sony/etc/default-capability_w_internal.xml vendor/sony/etc/default-capability_w_external0.xml vendor/sony/etc/default-capability_j_internal.xml vendor/sony/etc/default-capability_j_external0.xml vendor/sony/translations/HgrmMediaPlayerApp_en_US.qm $APP $L/libScreenshotShared.so"
ADDED="$L/libScreenshotOrigin.so $L/libaudiobookresume.so"
ALL="$SONY $ADDED"
NEW=$P/build/files; STOCK=$P/build/stock/files; V1=${1:+$P/$1}

put() { mkdir -p "$1/$(dirname "$3")"; cp "$2/$3" "$1/$3"; }
stock_tree() { rm -rf "$1"; for f in $SONY; do put "$1" "$STOCK" "$f"; done; }
# all edits to Sony's files made, no resume add-on (Sony's screenshot library in place)
uifix_tree() { stock_tree "$1"; for f in $SONY; do [ "$f" = "$L/libScreenshotShared.so" ] || put "$1" "$NEW" "$f"; done; }
# as above, but the app has only one of its two patches (the getter)
first_tree() { uifix_tree "$1"; cp "$STOCK/$APP" "$1/$APP"; printf '\001\040\160\107' | dd of="$1/$APP" bs=1 seek=$((0x1de9c4)) count=4 conv=notrunc 2>/dev/null; }
# all edits made, plus an earlier build of the resume add-on
v1_tree() { uifix_tree "$1"; for f in $ADDED $L/libScreenshotShared.so; do put "$1" "$V1" "$f"; done; }
new_tree() { rm -rf "$1"; for f in $ALL; do put "$1" "$NEW" "$f"; done; }
print() { for f in $ALL; do if [ -e "$1/$f" ]; then md5sum < "$1/$f"; else echo absent; fi; done | md5sum; }
new_tree "$T/ref-new"; NEWP=$(print "$T/ref-new"); stock_tree "$T/ref-stock"; STOCKP=$(print "$T/ref-stock")
state() { s=$(print "$1"); if [ "$s" = "$NEWP" ]; then echo NEW; elif [ "$s" = "$STOCKP" ]; then echo STOCK; else echo other; fi; }
run() { # run <install|uninstall> <system dir> -> the log lines
  W="$T/work"; rm -rf "$W"; mkdir -p "$W"; tar -xzf "$P/build/$1/userdata.tar.gz" -C "$W"
  { echo 'mount() { :; }; umount() { :; }'; sed -e "s|^BB=/xbin/busybox|BB=$T/bin/busybox|" -e "s|^SYS=/system|SYS=$2|" "$W/run.sh"; } > "$W/run-test.sh"
  grep -q "^BB=$T/bin/busybox" "$W/run-test.sh" && grep -q "^SYS=$2" "$W/run-test.sh" || { echo "harness: substitution failed"; exit 1; }
  (cd "$W" && LOG_FILE="$W/log.txt" "$T/bin/busybox" ash "$W/run-test.sh"); sed -E 's/^.* audiobooks: /      /' "$W/log.txt"
  [ ! -e "$W/stage" ] || { echo "      (the stage folder was left behind)"; fail=1; }; }
fail=0
expect() { if [ "$1" = "$2" ]; then echo "   after: $1   [ok]"; else echo "   after: $1   [EXPECTED $2]"; fail=1; fi; }

# An earlier build of the add-on, to test replacing it: the folder given, or else a copy of
# the current build with one byte changed in the loader and in the module.
if [ -n "$V1" ]; then
    [ -d "$V1/$L" ] || { echo "no $L in $V1"; exit 1; }
    echo "earlier add-on build: $1"
else
    echo "earlier add-on build: none given, using a modified copy of the current one"
    V1=$T/earlier
    for f in $ADDED $L/libScreenshotShared.so; do put "$V1" "$NEW" "$f"; done
    for f in $L/libaudiobookresume.so $L/libScreenshotShared.so; do printf 'Z' | dd of="$V1/$f" bs=1 seek=200 count=1 conv=notrunc 2>/dev/null; done
fi

echo "A. all edits made and an earlier build of the resume add-on + installer"
v1_tree "$T/a"; run install "$T/a"; expect "$(state "$T/a")" NEW
for f in $ADDED $L/libScreenshotShared.so; do [ "$(stat -c %a "$T/a/$f")" = 755 ] || { echo "   wrong mode on $f"; fail=1; }; done
echo "B. stock player + installer"; stock_tree "$T/b"; run install "$T/b"; expect "$(state "$T/b")" NEW
echo "C. installer again"; run install "$T/b"; expect "$(state "$T/b")" NEW
echo "D. all edits made, no add-on + installer"; uifix_tree "$T/d"; run install "$T/d" | tail -5; expect "$(state "$T/d")" NEW
echo "E. app with only one of its two patches, no add-on + installer"; first_tree "$T/e"; run install "$T/e" | tail -6; expect "$(state "$T/e")" NEW
echo "F. an app that is neither Sony's nor ours + installer"; v1_tree "$T/f"; printf 'X' | dd of="$T/f/$APP" bs=1 seek=100 count=1 conv=notrunc 2>/dev/null; b=$(print "$T/f"); run install "$T/f"; if [ "$(print "$T/f")" = "$b" ]; then echo "   after: untouched   [ok]"; else echo "   after: CHANGED"; fail=1; fi
echo "G. a capability file that is neither Sony's nor ours + installer"; stock_tree "$T/g"; echo "<!-- -->" >> "$T/g/vendor/sony/etc/default-capability_w_internal.xml"; b=$(print "$T/g"); run install "$T/g"; if [ "$(print "$T/g")" = "$b" ]; then echo "   after: untouched   [ok]"; else echo "   after: CHANGED"; fail=1; fi
echo "H. uninstaller on the new state"; run uninstall "$T/b"; expect "$(state "$T/b")" STOCK
echo "I. uninstaller on all edits + an earlier build of the add-on"; v1_tree "$T/i"; run uninstall "$T/i" | tail -5; expect "$(state "$T/i")" STOCK
echo "J. uninstaller on all edits, no add-on"; uifix_tree "$T/j"; run uninstall "$T/j" | tail -3; expect "$(state "$T/j")" STOCK
echo "K. uninstaller on an app with only one of its two patches"; first_tree "$T/k"; run uninstall "$T/k" | tail -2; expect "$(state "$T/k")" STOCK
echo "L. uninstaller on a stock player"; stock_tree "$T/l"; run uninstall "$T/l"; expect "$(state "$T/l")" STOCK
echo "M. add-on present but Sony's renamed library missing + uninstaller"; v1_tree "$T/m"; rm "$T/m/$L/libScreenshotOrigin.so"; b=$(print "$T/m"); run uninstall "$T/m"; if [ "$(print "$T/m")" = "$b" ]; then echo "   after: untouched   [ok]"; else echo "   after: CHANGED"; fail=1; fi
[ $fail = 0 ] && echo "ALL SCENARIOS PASSED" || { echo "SOME SCENARIOS FAILED"; exit 1; }
