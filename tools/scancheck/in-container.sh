#!/bin/bash
# Runs inside the zx300-resume-build container (check.sh starts it): builds scan.c for ARM
# and runs it with the player's own libraries under qemu-user.
set -eu
cd /work
ROOT=/work/build/resume/sysroot
[ -f "$ROOT/system/vendor/sony/lib/libMediaStoreService.so" ] || { echo "missing the player's libraries (run tools/resume/prepare-inputs.sh)"; exit 2; }
mkdir -p build/scancheck
arm-linux-gnueabihf-gcc -O1 -Wall -o build/scancheck/scan tools/scancheck/scan.c -ldl
exec timeout "${LIMIT:-300}" qemu-arm-static -L "$ROOT" -E LD_LIBRARY_PATH=/system/vendor/sony/lib:/system/lib:/lib \
    ${VERBOSE:+-E VERBOSE=1} build/scancheck/scan "$@"
