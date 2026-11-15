#!/bin/sh
# Build upgtool (Sony NW_WM_FW.UPG packer/unpacker) natively on macOS.
# Source: nw-installer's copy of Rockbox's upgtool, which knows the ZX300 keys
# and writes the same UPG layout as the nw-installer releases.
# Needs only the Xcode command line tools. Result: ./upgtool
set -eu
cd "$(dirname "$0")"
NW_INSTALLER_COMMIT=a032942e622f0d61b026e21c2379fcb618dcdbea
CRYPTOPP_ZIP=cryptopp890.zip
CRYPTOPP_SHA256=4cc0ccc324625b80b695fcd3dee63a66f1a460d3e51b71640cdbfc4cd1a3779c
B="$PWD/build"
mkdir -p "$B"

if [ ! -d "$B/nw-installer/.git" ]; then
    git init -q "$B/nw-installer"
    git -C "$B/nw-installer" remote add origin https://github.com/unknown321/nw-installer
fi
git -C "$B/nw-installer" fetch -q --depth 1 origin "$NW_INSTALLER_COMMIT"
git -C "$B/nw-installer" checkout -q --detach FETCH_HEAD

if [ ! -f "$B/cryptopp/libcryptopp.a" ]; then
    curl -fsSL -o "$B/$CRYPTOPP_ZIP" \
        "https://github.com/weidai11/cryptopp/releases/download/CRYPTOPP_8_9_0/$CRYPTOPP_ZIP"
    echo "$CRYPTOPP_SHA256  $B/$CRYPTOPP_ZIP" | shasum -a 256 -c -
    rm -rf "$B/cryptopp"
    unzip -q -d "$B/cryptopp" "$B/$CRYPTOPP_ZIP"
    make -C "$B/cryptopp" -j"$(sysctl -n hw.ncpu)" libcryptopp.a >/dev/null
fi

# mg.cpp includes <cryptopp/...>, so the include root is the build directory
SRC="$B/nw-installer/tools/upgtool/upgtools"
make -C "$SRC" clean veryclean >/dev/null
make -C "$SRC" CC=cc CXX=c++ LD=c++ \
    CFLAGS="-I$B -std=gnu11 -D_DARWIN_C_SOURCE -w" CXXFLAGS="-I$B -std=c++17 -w" \
    LDFLAGS="-L$B/cryptopp" LDLIBS="-lcryptopp -lz -lpthread" >/dev/null
cp "$SRC/upgtool" ./upgtool
echo "built $PWD/upgtool"
