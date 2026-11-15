# Build and install

For a Sony NW-ZX300 with firmware 2.02, from a Mac. Read the warning in the
[README](../README.md) first.

## What you need

- macOS with the Xcode command line tools (`xcode-select --install`). Made on an Apple
  Silicon Mac with macOS 27; not tried elsewhere.
- Python 3 (comes with the command line tools).
- Docker for the add-on build, for example `brew install colima docker`.
- [scsitool-mac](https://github.com/miloszfalinski/scsitool-mac) to start the update on the player.
- About 1.5 GB of disk space and an internet connection for the first build.

The build downloads, and checks against pinned checksums where a checksum exists:

| What | From | Used for |
|---|---|---|
| Sony's NW-ZX300 2.02 updater (119 MB) | `walkman.update.sony.net` | Sony's files to edit, the player's libraries to build and test against |
| nw-installer (pinned commit) | GitHub | `upgtool` source, the install scripts inside the package |
| Crypto++ 8.9.0 | GitHub | needed by `upgtool` |
| fix-coverart 1.0.2 release package | GitHub | six small helper programs for the player, which every nw-installer package carries |
| qtbase 5.3.2 source (47 MB) | `download.qt.io` | QtCore headers of the Qt version on the player |
| Debian 9 with an ARM cross compiler, Qt and qemu-user | Docker Hub, `archive.debian.org` | compiling the add-on and running its tests |

Everything lands in `build/`, which is not part of the repository.

## Build

```sh
tools/prepare.sh
```

Downloads Sony's updater, unpacks the system image, takes out the eight files that matter
and checks each against `tools/stock-files.sha256`. Then makes the edits to copies of them
(see [how-it-works.md](how-it-works.md)). Result: `build/stock/files` (Sony's) and
`build/files` (edited). The first run also builds `upgtool`.

```sh
tools/resume/prepare-inputs.sh
```

Takes the player's shared libraries and its busybox out of the updater, and the QtCore
headers out of the Qt source. Result: `build/resume/devlibs`, `sysroot`, `qt532`.

```sh
colima start
tools/resume/build.sh test
```

Builds the container image on first use, compiles the loader and the resume module for the
player, and runs the tests described in [resume-add-on.md](resume-add-on.md). It must end
with `MOCK TESTS PASSED` and `CHECKS PASSED`. The three libraries are copied into
`build/files`.

```sh
tools/package.sh
```

Checks that `build/files` is Sony's files plus exactly the intended edits and the libraries
just built, then writes:

```
build/install/NW_WM_FW.UPG       the installer
build/uninstall/NW_WM_FW.UPG     the uninstaller
```

```sh
tools/userdata/test-run.sh
```

Runs the installer and the uninstaller, exactly as packed, against simulated players: a
stock one, one with everything installed, half-installed ones, one with an unknown file.
The script runs under the player's own shell (BusyBox 1.23.1 from the firmware) in
emulation, so the commands behave as they will on the player. It must end with
`ALL SCENARIOS PASSED`.

### What is in a package

```
run.sh       the script that runs on the player
plan.txt     the list of edits, with the checksum each result must have
files/       installer only: libaudiobookresume.so and the loader
```

plus nw-installer's own scripts and helper programs around it. No file of Sony's. The
uninstaller's plan contains the few dozen original bytes it puts back.

`tools/make_plan.py` writes the plan by comparing `build/stock/files` with `build/files`,
and applies every edit list to the stock file itself to confirm it gives the edited one.

The same input gives the same package, byte for byte. Checksums are in the README. A
different version of `gzip` could change them without changing what is installed.

## What the installer does on the player

nw-installer's script runs `run.sh` inside the player's updater. It works in two passes:

1. For every file to change, it copies the file from `/system` to a work folder on the
   player's storage, applies the edits there, and compares the checksum of the result with
   the one in the plan. Nothing under `/system` is written in this pass.
2. Only if every result checked out, it copies the results and the two add-on libraries
   into `/system`, then checks all of them once more.

A step whose result is already on the player is skipped, so running the installer twice is
harmless. A player with other firmware, or with a file the plan does not recognise, fails
in the first pass and is left exactly as it was.

It needs about 10 MB of free space on the player's storage while it runs.

Everything it does is written to `upgrade.log` in the top folder of the player's storage.

## Install

1. Charge the player. Connect it and turn on USB Mass Storage.
2. Copy `build/install/NW_WM_FW.UPG` to the top folder of the player's internal storage, next
   to `MUSIC`.
3. In the scsitool-mac folder:

   ```sh
   ./scsitool list_devices
   # 054c:0c70           /dev/disk16         SONY     WALKMAN          1.00

   sudo ./scsitool -s nw-zx300 054c:0c70 get_dnk_prop model_id
   # a read-only question; an answer (0x23000004 on the test player) shows the link works

   sudo ./scsitool -s nw-zx300 054c:0c70 do_fw_upgrade
   ```

4. The player restarts into its updater, installs, and restarts. About a minute. Do not
   disconnect it or switch it off meanwhile.
5. Connect it again and read `upgrade.log`. A first install on a stock player looks like
   this (each line starts with the date):

   ```
   audiobooks: start
   audiobooks: patched: vendor/sony/lib/libInitialObject.so
   audiobooks: patched: vendor/sony/etc/default-capability_w_internal.xml
   audiobooks: patched: vendor/sony/etc/default-capability_w_external0.xml
   audiobooks: patched: vendor/sony/etc/default-capability_j_internal.xml
   audiobooks: patched: vendor/sony/etc/default-capability_j_external0.xml
   audiobooks: patched: vendor/sony/translations/HgrmMediaPlayerApp_en_US.qm
   audiobooks: patched: vendor/sony/bin/HgrmMediaPlayerApp
   audiobooks: patched: vendor/sony/lib/libScreenshotOrigin.so
   audiobooks: copied: vendor/sony/lib/libaudiobookresume.so
   audiobooks: copied: vendor/sony/lib/libScreenshotShared.so
   audiobooks: done: every file is in place
   ```

   `nothing changed: this package only fits NW-ZX300 firmware 2.02` means the first pass
   found something unexpected. The line above it names the file.

The installer leaves a smaller `NW_WM_FW.UPG` (about 7 MB) in the same place. It is not
needed afterwards.

## First use

- The player creates a `LEARNING` folder in the top folder of its internal storage. Put
  audio files there, in folders if you like, and disconnect so that the player updates its
  database. A `LEARNING` folder on the SD card works the same way.
  [preparing-books.md](preparing-books.md) says how to lay the books out. If a book shows
  up without title and playing time, see "Books that show up as Unknown" below.
- **Audiobooks** is a button on the library screen.
- After the first start, the folder `audiobook-resume` appears on the storage. Its
  `log.txt` should begin with lines like

  ```
  loader: module started (rc 0, guard counter 1)
  resume: module version 2 started, 0 stored positions, Qt 5.3.2
  loader: module healthy after 20 s, guard counter reset
  ```

On the test player the `LEARNING` folder appeared by itself on the first start after the
edits. That player was also reset to factory settings once during the work, so it is not
known for certain that a reset is never needed. If the button is there and the library
stays empty, "Rebuild Database" in the player's settings is the first thing to try.

## Books that show up as "Unknown"

If a book is listed as "Unknown" with no playing time although it has tags, the usual
cause is the form of its time headers. An MP4 file (`.m4a`, `.m4b`) states its length in
the `mvhd`, `tkhd`, `mdhd` and `elst` boxes, in a 32-bit or a 64-bit form. The player's
scanner does not accept the 64-bit form: it finds no movie header, gives up on the file
and stores none of its tags. Two common sources of such files:

- some audiobook downloads are written that way to begin with;
- ffmpeg, when a cover picture is copied over from an `.m4b` together with the audio
  (`-map 0:v`): it then counts the length in units of 1/4,410,000 s and switches to 64-bit
  headers for anything longer than about 8 minutes. Attaching the cover from a separate
  picture file avoids that, up to 13.5 hours at 44.1 kHz.

To look at a file and to fix it:

```sh
tools/scancheck/mp4-short-headers.py --show "Book.m4a"      # lists the header versions
tools/scancheck/mp4-short-headers.py "Book.m4a" "Book fixed.m4a"
```

The second command writes a copy with 32-bit headers. Only those few bytes differ: the
audio, the tags and the cover are copied unchanged. It needs nothing but Python 3. A track
longer than 2^32 samples (27 hours at 44.1 kHz) cannot be written with 32-bit headers; the
tool says so, and such a book has to be split.

`.m4b` is not a file name the player looks at. Rename the file to `.m4a`; the contents are
the same format.

## Checking a file before it goes on the player

```sh
tools/scancheck/check.sh "/path/under/your/home/Some Book.m4a"
```

This runs the player's own metadata parser (taken from the firmware, under emulation) on an
MP4-family file (`.m4a`, `.mp4`, `.m4b` content) or an `.mp3` and prints the title, artist
and playing time it returns, ending with READABLE or NOT READABLE. With `-v` it also prints
the firmware's own error messages. It needs the same setup as the add-on build (Docker,
`tools/resume/prepare-inputs.sh`, the container image), and the file has to be somewhere
under your home folder. It reproduces the parser and reports the failure described above;
it does not reproduce the rest of the scanner or the player's storage.

## Undo and recovery

From least to most drastic:

1. **Only the resume add-on off:** create an empty file `disable` in `audiobook-resume`.
   Delete it to switch the add-on on again.
2. **Everything off:** flash `build/uninstall/NW_WM_FW.UPG` the same way as the installer.
   It reverses the edits (from the plan, checked by checksum like the installer) and removes
   the added libraries. The files in `LEARNING` and `audiobook-resume` stay; delete them
   yourself if you want.
3. **Stock firmware:** Sony's 2.02 updater, kept in `build/stock/NW-ZX300_V2_02.dmg`. Its
   update file is `.Data/Device/NW_WM_FW.UPG` inside the image; flashing that file with
   scsitool should work like any other update, but was not tried here.

All three need a player that still starts and connects over USB. If it does not, the only
way back is the MediaTek service mode (on the NW-ZX300: player off, hold Play/Pause and
Volume −, then connect the cable) with a tool such as mtkclient and a full image of the
flash memory that you read **before** you started. Reading such an image worked here;
writing one back was never tried. wampy's
[BACKUP.md](https://github.com/unknown321/wampy/blob/master/BACKUP.md) describes backups in
more detail.
