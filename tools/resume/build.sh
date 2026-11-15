#!/bin/sh
# Builds the Audiobooks resume add-on (see docs/resume-add-on.md).
#
#   tools/resume/build.sh            build for the player and for the Linux mock test
#   tools/resume/build.sh test       build, then run the mock test and the checks against
#                                    the player's libraries
#
# Needs a running Docker daemon (colima start). Inputs under build/resume/:
#   devlibs/   libraries taken from the player's firmware (its /lib and Sony's Qt)
#   qt532/     QtCore headers from qtbase 5.3.2
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
IMAGE=zx300-resume-build
docker image inspect $IMAGE >/dev/null 2>&1 || docker build -q -t $IMAGE "$HERE"
run() { docker run --rm -v "$ROOT":/work -w /work $IMAGE "$@"; }
run tools/resume/build-in-container.sh
if [ "${1:-}" = test ]; then
    run tools/resume/test/run-tests.sh
    run python3 tools/resume/check_elf.py build/resume/out/device build/resume/devlibs
fi
# what tools/package.sh packs
mkdir -p "$ROOT/build/files/vendor/sony/lib"
for f in libScreenshotOrigin.so libaudiobookresume.so libScreenshotShared.so; do
    cp "$ROOT/build/resume/out/device/$f" "$ROOT/build/files/vendor/sony/lib/$f"
    chmod 755 "$ROOT/build/files/vendor/sony/lib/$f"
done
echo "copied the three libraries to build/files/vendor/sony/lib/"
