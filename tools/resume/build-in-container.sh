#!/bin/bash
# Runs inside the zx300-resume-build container with the project mounted at /work.
# Builds the loader and the resume module twice: for the player (ARM, against the player's
# own libraries) and for this Linux (to run the mock test). Called by tools/resume/build.sh.
set -euo pipefail
cd /work
SRC=tools/resume/src
TEST=tools/resume/test
B=build/resume
DEV=$B/devlibs
QT=$B/qt532
OUT=$B/out
CROSS=arm-linux-gnueabihf-
CFLAGS="-O2 -fPIC -fvisibility=hidden -Wall -Wextra"
CXXFLAGS="$CFLAGS -std=gnu++11 -fno-exceptions -fno-rtti -fno-threadsafe-statics -DQT_NO_DEBUG"

rm -rf $OUT && mkdir -p $OUT/device $OUT/host $OUT/host/run

# --- Qt 5.3.2 headers: add the qconfig.h that Qt's configure would have generated
cp $SRC/qconfig-zx300.h $QT/src/corelib/global/qconfig.h
[ -f $QT/include/QtCore/qconfig.h ] || echo '#include "../../src/corelib/global/qconfig.h"' > $QT/include/QtCore/qconfig.h
# qfeatures.h is generated from qfeatures.txt at Qt build time and only derives further
# QT_NO_* switches from ones already set; none are set here, so it is empty.
[ -f $QT/include/QtCore/qfeatures.h ] || echo '/* no optional features switched off */' > $QT/include/QtCore/qfeatures.h

# --- Sony's library under its new name: same bytes except the name recorded inside it
python3 - "$DEV/sony/libScreenshotShared.so" "$OUT/device/libScreenshotOrigin.so" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
old, new = b'libScreenshotShared.so\0', b'libScreenshotOrigin.so\0'
assert len(old) == len(new) and d.count(old) == 1, "expected the library's own name exactly once"
open(sys.argv[2], 'wb').write(d.replace(old, new))
PY

echo "== player build (ARM)"
${CROSS}gcc $CFLAGS -shared -o $OUT/device/libScreenshotShared.so $SRC/loader.c \
    -Wl,-soname,libScreenshotShared.so -Wl,--no-undefined -Wl,--no-as-needed \
    -L$OUT/device -l:libScreenshotOrigin.so -Wl,--as-needed -ldl -lpthread \
    -Wl,-rpath-link,$DEV/sony:$DEV/lib -Wl,--allow-shlib-undefined
${CROSS}g++ $CXXFLAGS -I$QT/include -I$QT/include/QtCore -c $SRC/resume.cpp -o $OUT/device/resume.o
${CROSS}gcc -shared -o $OUT/device/libaudiobookresume.so $OUT/device/resume.o \
    -Wl,-soname,libaudiobookresume.so -Wl,--no-undefined \
    -L$DEV/sony -l:libQt5Core.so.5 -L$DEV/lib -l:libcxxrt.so.1 -lpthread \
    -Wl,-rpath-link,$DEV/sony:$DEV/lib -Wl,--allow-shlib-undefined
${CROSS}strip --strip-unneeded $OUT/device/libScreenshotShared.so $OUT/device/libaudiobookresume.so
rm $OUT/device/resume.o
ls -l $OUT/device

echo "== Linux build for the mock test"
H=$OUT/host
QTINC=/usr/include/$(gcc -dumpmachine)/qt5
QTFLAGS="-I$QTINC -I$QTINC/QtCore"
QTLIBS=-lQt5Core
g++ -O1 -fPIC -shared -o $H/libScreenshotShared.so $TEST/orig.cpp -Wl,-soname,libScreenshotShared.so     # stand-in for Sony's
/usr/lib/$(gcc -dumpmachine)/qt5/bin/moc $TEST/mockapp.h -o $H/moc_mockapp.cpp
g++ -std=gnu++14 -O1 -fPIC $QTFLAGS -I$TEST -o $H/run/HgrmMediaPlayerApp $TEST/mockapp.cpp $H/moc_mockapp.cpp \
    -L$H -l:libScreenshotShared.so $QTLIBS -Wl,-rpath,'$ORIGIN'
# now the same swap as on the player: the original moves to a new name, the loader takes its place
python3 - "$H/libScreenshotShared.so" "$H/run/libScreenshotOrigin.so" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
old, new = b'libScreenshotShared.so\0', b'libScreenshotOrigin.so\0'
assert d.count(old) == 1
open(sys.argv[2], 'wb').write(d.replace(old, new))
PY
gcc $CFLAGS -shared -o $H/run/libScreenshotShared.so $SRC/loader.c \
    -Wl,-soname,libScreenshotShared.so -Wl,--no-undefined -Wl,--no-as-needed \
    -L$H/run -l:libScreenshotOrigin.so -Wl,--as-needed -ldl -lpthread
g++ $CXXFLAGS $QTFLAGS -shared -o $H/run/libaudiobookresume.so $SRC/resume.cpp \
    -Wl,-soname,libaudiobookresume.so -Wl,--no-undefined $QTLIBS -lpthread -ldl
ls -l $H/run

echo "== ARM mock app, to run the player build under emulation"
# Linked like the real app: against Sony's Qt and Sony's libScreenshotShared.so. At run time
# it gets the files that would be installed: the loader under that name, Sony's library
# under its new name, and the resume module.
E=$OUT/emul
mkdir -p $E/run
/usr/lib/$(gcc -dumpmachine)/qt5/bin/moc $TEST/mockapp.h -o $E/moc_mockapp.cpp
${CROSS}g++ -std=gnu++11 -O1 -fPIC -DMOCK_RESOLVE_ONLY -DQT_NO_DEBUG -I$QT/include -I$QT/include/QtCore -I$TEST \
    -o $E/run/HgrmMediaPlayerApp $TEST/mockapp.cpp $E/moc_mockapp.cpp \
    -L$DEV/sony -l:libQt5Core.so.5 -l:libScreenshotShared.so -ldl -static-libstdc++ -static-libgcc \
    -Wl,--allow-shlib-undefined -Wl,-rpath-link,$B/sysroot/system/vendor/sony/lib:$B/sysroot/system/lib:$DEV/lib
cp $OUT/device/libScreenshotShared.so $OUT/device/libScreenshotOrigin.so $OUT/device/libaudiobookresume.so $E/run/
ls -l $E/run

