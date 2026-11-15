#!/bin/bash
# Runs inside the build container: the loader and the resume module (Linux builds) loaded
# into the mock player app, through the same library swap as on the player.
set -uo pipefail
cd /work/build/resume/out/host/run
[ -x ./HgrmMediaPlayerApp ] || { echo 'the mock app was not built'; exit 1; }
T=$(mktemp -d)
mkdir "$T/storage" "$T/storage/LEARNING"
export ABR_DIR=$T/storage/audiobook-resume ABR_STORAGE_MARK=$T/storage/LEARNING ABR_MODULE=$PWD/libaudiobookresume.so ABR_HEALTHY_AFTER=6
fail=0
check() { if "$@"; then echo "   ok: $*"; else echo "   FAIL: $*"; fail=1; fi; }
has() { grep -q -- "$1" "$2"; }
hasnt() { ! grep -q -- "$1" "$2"; }
pos() { awk -v id="$1" '$1 == id { print $2 }' "$ABR_DIR/positions.txt"; }

echo "== 1. first run: positions are recorded, a track resumes when it comes back"
./HgrmMediaPlayerApp first > "$T/out1.txt" 2>&1; rc=$?
grep '^MOCK' "$T/out1.txt"
check [ $rc = 0 ]
check has 'reached the original library' "$T/out1.txt"
check [ "$(grep -c 'ReceiveSeek' "$T/out1.txt")" = 1 ]
check has 'ReceiveSeek(origin 0, 65000 ms) on dmpapp::LanguageStudyPlayer' "$T/out1.txt"
echo "   positions.txt:"; sed 's/^/      /' "$ABR_DIR/positions.txt"
check [ "$(pos 200)" = 20000 ]
check [ "$(pos 400)" = 8000 ]
check [ -z "$(pos 300)" ]
check [ "$(pos 100)" -ge 65000 ]
check [ -z "$(pos 7)" ]
check [ "$(cat "$ABR_DIR/starts")" = 0 ]
check has 'module healthy' "$ABR_DIR/log.txt"

echo "== 2. second run with the same storage (as after a reboot)"
./HgrmMediaPlayerApp second > "$T/out2.txt" 2>&1; rc=$?
grep '^MOCK' "$T/out2.txt"
check [ $rc = 0 ]
check [ "$(grep -c 'ReceiveSeek' "$T/out2.txt")" = 2 ]
check has 'ReceiveSeek(origin 0, 20000 ms)' "$T/out2.txt"
check has 'ReceiveSeek(origin 0, 8000 ms)' "$T/out2.txt"
check has 'does not match' "$ABR_DIR/log.txt"
check has 'already at 50000 ms' "$ABR_DIR/log.txt"

echo "== 3. kill switch: the file 'disable'"
touch "$ABR_DIR/disable"; : > "$ABR_DIR/log.txt"
./HgrmMediaPlayerApp second > "$T/out3.txt" 2>&1
check hasnt 'ReceiveSeek' "$T/out3.txt"
check has "'disable' is present" "$ABR_DIR/log.txt"
rm "$ABR_DIR/disable"

echo "== 4. guard: two starts that were never confirmed"
echo 2 > "$ABR_DIR/starts"; : > "$ABR_DIR/log.txt"
./HgrmMediaPlayerApp second > "$T/out4.txt" 2>&1
check hasnt 'ReceiveSeek' "$T/out4.txt"
check has 'guard: the last 2 starts' "$ABR_DIR/log.txt"
check [ "$(cat "$ABR_DIR/starts")" = 2 ]

echo "== 5. a start that ends before it is confirmed leaves the counter raised"
echo 0 > "$ABR_DIR/starts"
ABR_HEALTHY_AFTER=60 ./HgrmMediaPlayerApp idle > "$T/out5.txt" 2>&1
check [ "$(cat "$ABR_DIR/starts")" = 1 ]

echo "== 6. a module that cannot be loaded is refused, the app carries on"
echo 0 > "$ABR_DIR/starts"; : > "$ABR_DIR/log.txt"
ABR_MODULE=/nonexistent/libaudiobookresume.so ./HgrmMediaPlayerApp idle > "$T/out6.txt" 2>&1; rc=$?
check [ $rc = 0 ]
check has 'module not loaded' "$ABR_DIR/log.txt"

echo "== 7. storage not visible (exported over USB): nothing happens, the app carries on"
ABR_STORAGE_MARK=$T/storage/NOT_THERE ABR_DIR=$T/storage/other ./HgrmMediaPlayerApp idle > "$T/out7.txt" 2>&1; rc=$?
check [ $rc = 0 ]
check [ ! -e "$T/storage/other" ]

echo "== 8. in another program the loader does nothing"
cp HgrmMediaPlayerApp "$T/screenshot" && cp lib*.so "$T/" && : > "$ABR_DIR/log.txt"
(cd "$T" && ./screenshot idle > "$T/out8.txt" 2>&1)
check has 'reached the original library' "$T/out8.txt"
check [ ! -s "$ABR_DIR/log.txt" ]

echo "== 8a. position reports of the next track that arrive before its track change"
echo 0 > "$ABR_DIR/starts"; rm -f "$ABR_DIR/positions.txt"
./HgrmMediaPlayerApp early > "$T/out8a.txt" 2>&1
check [ "$(pos 600)" = 40000 ]
check [ "$(pos 601)" = 9000 ]

echo "== 8b. when the app announces that the storage will be unmounted, files are left alone"
echo 0 > "$ABR_DIR/starts"; rm -f "$ABR_DIR/positions.txt"; : > "$ABR_DIR/log.txt"
./HgrmMediaPlayerApp umount > "$T/out8b.txt" 2>&1
check has 'track changed: entry 500' "$ABR_DIR/log.txt"     # before the announcement: written
check hasnt 'entry 501' "$ABR_DIR/log.txt"                  # after it: held back, in the file neither
check [ -z "$(pos 501)" ]

echo "== 8c. new entry ids after a database rebuild: a position is carried over by length"
echo 0 > "$ABR_DIR/starts"; printf '200 20000 300000 1\n400 8000 100000 1\n' > "$ABR_DIR/positions.txt"
./HgrmMediaPlayerApp renumber > "$T/out8c.txt" 2>&1; rc=$?
grep '^MOCK' "$T/out8c.txt"
check [ $rc = 0 ]
check [ -z "$(pos 200)" ]
check [ "$(pos 900)" -ge 20000 ]
check [ "$(pos 901)" = 9000 ]
check [ "$(pos 400)" = 8000 ]

echo "== 8d. the log is short by default and detailed with the file 'verbose'"
echo 0 > "$ABR_DIR/starts"; : > "$ABR_DIR/log.txt"
./HgrmMediaPlayerApp second > /dev/null 2>&1
check hasnt 'resume: position [0-9]' "$ABR_DIR/log.txt"     # the per-second reports
check hasnt 'resume: resume:' "$ABR_DIR/log.txt"
check [ "$(grep -c '' "$ABR_DIR/log.txt")" -lt 40 ]
touch "$ABR_DIR/verbose"; : > "$ABR_DIR/log.txt"
./HgrmMediaPlayerApp second > /dev/null 2>&1
check has 'resume: position [0-9]' "$ABR_DIR/log.txt"
check has 'play state' "$ABR_DIR/log.txt"
rm "$ABR_DIR/verbose"

echo "== 9. the ARM files under emulation, with the player's own loader, C library and Qt 5.3.2"
SYS=/work/build/resume/sysroot
E=/work/build/resume/out/emul/run
T2=$(mktemp -d); mkdir -p "$T2/storage/LEARNING"
D2=$T2/storage/audiobook-resume
emu() {
    (cd "$E" && qemu-arm-static -L "$SYS" \
        -E LD_LIBRARY_PATH="$E:/system/vendor/sony/lib:/system/lib:/lib" \
        -E ABR_DIR="$D2" -E ABR_STORAGE_MARK="$T2/storage/LEARNING" \
        -E ABR_MODULE="$E/libaudiobookresume.so" -E ABR_HEALTHY_AFTER=6 ./HgrmMediaPlayerApp "$@")
}
if [ -x "$E/HgrmMediaPlayerApp" ] && [ -d "$SYS/system" ]; then
    emu first > "$T2/out1.txt" 2>&1; rc=$?
    grep -E '^MOCK|rror|annot' "$T2/out1.txt" | head -12
    check [ $rc = 0 ]
    check has 'resolved to .*libScreenshotOrigin.so' "$T2/out1.txt"
    check has 'ReceiveSeek(origin 0, 65000 ms) on dmpapp::LanguageStudyPlayer' "$T2/out1.txt"
    check [ "$(grep -c 'ReceiveSeek' "$T2/out1.txt")" = 1 ]
    check has 'Qt 5.3.2' "$D2/log.txt"
    check has 'module healthy' "$D2/log.txt"
    check [ "$(awk '$1 == 200 { print $2 }' "$D2/positions.txt")" = 20000 ]
    emu second > "$T2/out2.txt" 2>&1; rc=$?
    grep -E '^MOCK' "$T2/out2.txt"
    check [ $rc = 0 ]
    check [ "$(grep -c 'ReceiveSeek' "$T2/out2.txt")" = 2 ]
    echo "   log written by the ARM module (first lines):"; sed -n '1,14p' "$D2/log.txt" | sed 's/^/      /'
else
    echo "   FAIL: emulation inputs missing (build/resume/sysroot or the ARM mock app)"; fail=1
fi
[ $fail = 0 ] && echo "MOCK TESTS PASSED" || { echo "MOCK TESTS FAILED"; echo "--- out1"; tail -5 "$T/out1.txt"; echo "--- log"; tail -40 "$ABR_DIR/log.txt"; exit 1; }
