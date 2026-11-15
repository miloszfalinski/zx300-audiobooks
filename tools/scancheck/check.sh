#!/bin/sh
# What does the NW-ZX300's media scanner read from these files?
#
#   tools/scancheck/check.sh [-v] <file>...        .m4a / .mp4 / .m4b content, or .mp3
#
# Runs the player's own metadata parser (stock 2.02 firmware) on each file, under emulation,
# and prints the title, artist, playing time and so on that it returns. "READABLE" means the
# contents of the file are fine for the player. It does not reproduce the rest of the
# scanner or the player's storage. -v also prints the items without a name.
#
# Needs Docker running (colima start), the image tools/resume/build.sh makes, and
# build/resume/sysroot from tools/resume/prepare-inputs.sh.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
VERBOSE=
[ "${1:-}" = -v ] && { VERBOSE=1; shift; }
[ $# -ge 1 ] || { sed -n '2,11p' "$0" | cut -c3-; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker is not running (colima start)" >&2; exit 1; }
status=0
for f in "$@"; do
    if [ ! -f "$f" ]; then echo "$f: not a file" >&2; status=1; continue; fi
    dir=$(cd "$(dirname "$f")" && pwd -P)
    case "$dir/" in
        "$HOME"/*) ;;
        *) echo "$f: this folder is outside your home folder, which the container cannot see." >&2
           echo "   Copy the file somewhere under $HOME and run again." >&2; status=1; continue ;;
    esac
    docker run --rm ${VERBOSE:+-e VERBOSE=1} -v "$ROOT":/work -v "$dir":/book:ro -w /work \
        zx300-resume-build tools/scancheck/in-container.sh "/book/$(basename "$f")" || status=1
done
exit $status
