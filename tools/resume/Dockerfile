# Build environment for the Audiobooks resume add-on (see docs/resume-add-on.md).
# Debian 9: its ARM cross toolchain targets glibc 2.24 with gcc 6, close to the player's
# glibc 2.23, and its Qt 5.7 has the same signal-spy interface as the player's Qt 5.3.2,
# so the mock test on Linux exercises the same code path. qemu-user runs the ARM builds
# with the player's own loader and libraries (build/resume/sysroot).
FROM debian:stretch
RUN sed -i 's|deb.debian.org|archive.debian.org|g; s|security.debian.org/debian-security|archive.debian.org/debian-security|g; /stretch-updates/d' /etc/apt/sources.list && \
    apt-get -o Acquire::Check-Valid-Until=false update && \
    apt-get install -y --no-install-recommends \
        g++-arm-linux-gnueabihf g++ make binutils file xz-utils ca-certificates wget python3 \
        qtbase5-dev qtbase5-dev-tools qemu-user-static && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /work
