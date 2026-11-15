#!/bin/sh
# Tests the packed installer and uninstaller (build/install, build/uninstall) against simulated
# player states, using the player's own shell and tools under emulation.
#
#   tools/userdata/test-run.sh [earlier build]
#
# After tools/package.sh; needs Docker running (colima start) and the image that
# tools/resume/build.sh makes. [earlier build]: optional, a folder inside the project laid
# out like build/files with an earlier build of the add-on, to test replacing that one.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
docker run --rm -v "$ROOT":/work -w /work zx300-resume-build tools/userdata/test-in-container.sh "$@"
