# Audiobooks for the Sony NW-ZX300

Turns on the "Language Study" mode that Sony left switched off in the NW-ZX300, labels it
**Audiobooks**, and adds what it lacks for books: every track resumes where you left it.

What you get on the player:

- A separate **Audiobooks** library, opened with its own button on the library screen. It
  shows the files in the `LEARNING` folder and is not mixed with music.
- Sony's own Language Study player for them: playback speed, A-B repeat, quick replay
  (jump back a few seconds).
- **Per-track resume.** Each audiobook track comes back at its own position, also after the
  player has been switched off. Music is not touched. (Sony's code keeps one position for the
  whole Audiobooks player and loses it on a restart; a small add-on fixes that.)

No replacement interface, no extra apps, no dependence on the Hold switch. The player looks
and works as before, with one more button.

## Read this first

**This changes firmware files and can leave the player unusable.** It was made for one
player and tested on that one player. Nobody else has run it. You do this at your own risk.

- It fits **NW-ZX300 firmware 2.02 only**. The installer checks every file it is about to
  change and does nothing if anything on the player is not what it expects.
- The build and flash tools are for **macOS** (made on an Apple Silicon Mac).
- Keep Sony's official 2.02 updater. It puts stock firmware back.

## Status

| Part | On a player | Away from a player |
|---|---|---|
| The five edits that turn the feature on (button, library, player screens, playback) | Works | |
| Resume add-on, version 1 | Works: tracks came back at their own positions, also after a restart | Mock and emulation tests pass |
| Resume add-on, version 2 (what this repository builds) | Runs: it loaded, took over the positions version 1 had stored, and records positions, also for books on the SD card. The test of a book coming back at its position is still to be done | Mock and emulation tests pass |
| Installer that edits Sony's files in place (what this repository builds) | Ran once, on a player that already had the five edits: it replaced the two add-on libraries and checked every file. Making the edits themselves has only been done under emulation | Passes 13 scenarios run with the player's own shell under emulation |
| Uninstaller | Not run yet | Same |

"On a player" means one NW-ZX300 (16 GB) with firmware 2.02. The earlier installer, which
was used for everything marked "Works", copied whole files; the one here applies the same
changes as small edits so that no file of Sony's has to be shipped.

## Nothing of Sony's is in here

The repository holds only scripts and the source of the add-on. `tools/prepare.sh` downloads
Sony's updater from Sony's server and checks it against a pinned checksum. The update package
you build contains a script, a list of edits and two small libraries built from the source
here. Sony's files are edited on the player itself.

## Build

Needs: macOS, the Xcode command line tools, Python 3, and Docker (for example
[colima](https://github.com/abiosoft/colima)) for the add-on, which is compiled and tested in
a Linux container.

```sh
tools/prepare.sh                   # Sony's updater, its files, and the edits to them
tools/resume/prepare-inputs.sh     # the player's libraries and the Qt 5.3.2 headers
colima start
tools/resume/build.sh test         # builds and tests the resume add-on
tools/package.sh                   # build/install/NW_WM_FW.UPG, build/uninstall/NW_WM_FW.UPG
tools/userdata/test-run.sh         # runs the installer against simulated players
```

Ten to fifteen minutes the first time, most of it downloads. The same source gives the same
packages byte for byte. Built on macOS 27 they have these MD5 checksums:

```
9cc3764b65660e34e1a9fbb7045517b1  build/install/NW_WM_FW.UPG
daedc55fe31582c93e43426b43cd4f13  build/uninstall/NW_WM_FW.UPG
```

Details: [docs/build-and-install.md](docs/build-and-install.md).

## Install

A Walkman starts a firmware update when the computer sends it one special command. On a Mac
that takes [scsitool-mac](https://github.com/miloszfalinski/scsitool-mac).

1. Connect the player with USB Mass Storage on.
2. Copy `build/install/NW_WM_FW.UPG` to the top folder of the player's internal storage
   (next to `MUSIC`).
3. Send the command:

   ```sh
   ./scsitool list_devices                                   # shows the id, e.g. 054c:0c70
   sudo ./scsitool -s nw-zx300 054c:0c70 get_dnk_prop model_id    # read-only test first
   sudo ./scsitool -s nw-zx300 054c:0c70 do_fw_upgrade
   ```

4. The player restarts, installs, and restarts again. About a minute.
5. Connect it again and open `upgrade.log` in the top folder of its storage. A good run ends
   with `audiobooks: done: every file is in place`. If it says `nothing changed`, the lines
   above it say which file did not match, and the player is as it was.

Then put audio files into the `LEARNING` folder (the player creates it) and open
**Audiobooks** from the library screen. [docs/preparing-books.md](docs/preparing-books.md)
says how to lay the books out: one file per book or per chapter, which tags the library
shows, file names, covers.

## Undo

- Flash `build/uninstall/NW_WM_FW.UPG` the same way. It reverses every edit and removes the
  added files.
- Or run Sony's 2.02 updater.
- To switch off only the resume add-on without flashing: create an empty file named `disable`
  in the folder `audiobook-resume` on the player's storage.

## How it works

Sony builds one player app for several models and switches features per model. On the
NW-ZX300, Language Study is switched off in three places; the NW-A50 firmware, where the
feature is on, shows what each should be. Five small edits (6 bytes in two programs, one
line in four settings files, and the English label) turn it on.
[docs/how-it-works.md](docs/how-it-works.md) has every edit, how it was found, and the
complete list of feature switches that differ between the two models.

The resume add-on is a 10 KB loader and an 18 KB module that run inside the player app,
watch the Audiobooks player through Qt's own signal hook, and keep positions in a text file.
[docs/resume-add-on.md](docs/resume-add-on.md) describes it and its safety guard.

## Limits

- English label only. Other interface languages keep "Language Study" (the feature works
  the same).
- File formats are those of the music player. The player skips files named `.m4b`; renamed
  to `.m4a` they are read.
- The player app has no chapter feature. Chapter marks inside a file are not shown.
- Skipping is Sony's quick replay, not 15 or 30 seconds.
- No bookmarks inside a track.
- A position is stored per track. A book in one long file is one track.
- A `LEARNING` folder on the SD card works too: twelve books there, up to 40 hours in one
  file, were listed with their titles.
- Covers have to be inside the file, and the player does not show progressive JPEG covers.
  `tools/scancheck/mp4-baseline-cover.py` converts them to baseline JPEG. See
  [docs/preparing-books.md](docs/preparing-books.md).
- The player cannot read MP4 files whose time headers are in the 64-bit form ("version 1"
  `mvhd`, `tkhd`, `mdhd`, `elst`). Such a file is listed as "Unknown" with no playing time,
  whatever its tags say. Some audiobook downloads have these headers, and ffmpeg writes
  them when it copies a cover picture over from an `.m4b` together with audio longer than
  about 8 minutes. `tools/scancheck/mp4-short-headers.py` rewrites the headers as 32-bit
  without touching the audio, and `tools/scancheck/check.sh` tells whether the player's
  parser will read a file. See [docs/build-and-install.md](docs/build-and-install.md).
  A track longer than 2^32 samples (27 hours at 44.1 kHz) cannot be fixed that way.

## Thanks

- [Rockbox](https://www.rockbox.org/): `upgtool` and `scsitool`, and the knowledge about
  Sony's update format behind them.
- [unknown321](https://github.com/unknown321): [nw-installer](https://github.com/unknown321/nw-installer),
  whose update scripts and helper programs carry this package onto the player, and
  [wampy](https://github.com/unknown321/wampy), which showed that code can run inside the
  player app and reach its objects through Qt.

## Licence

The scripts and the add-on source in this repository: GNU General Public License, version 3
or later (see `LICENSE`).

The update package that the build produces also contains nw-installer's install scripts and
helper programs. Those are under nw-installer's licence, the GPL version 3 with the Commons
Clause, which forbids selling them.

Not affiliated with Sony. "Walkman" is Sony's trademark.
