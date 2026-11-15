# The resume add-on

## What it is for

Sony's Language Study player keeps one resume position for the whole mode, and loses it when
the player restarts. For audiobooks that is not enough. Nothing in the stock app stores a
position per track: the media database has a column named `RESUME_POINT`, but no code reads
or writes it. So per-track resume needs a small piece of added code.

The add-on gives each track in **Audiobooks** its own position, kept in a text file on the
player's storage, and puts the track back there when it is played again, also after a
restart. It never acts on the music player.

## The parts

Three files in `/system/vendor/sony/lib`:

| File on the player | What it is |
|---|---|
| `libScreenshotOrigin.so` | Sony's `libScreenshotShared.so` under a new name. Only the name recorded inside it is changed (6 bytes) |
| `libScreenshotShared.so` | The **loader** (C, 10 KB). It depends on `libScreenshotOrigin.so`, so the app still finds Sony's one function there. Its only job is to load the module, behind a guard |
| `libaudiobookresume.so` | The **resume module** (C++ against the player's own Qt 5.3.2, 18 KB) |

Why `libScreenshotShared.so`: the player app loads it at start, it exports a single
function, and nothing else on the player links to it. That makes it a small and safe place
to get code into the app. (wampy replaces the Qt display plugin instead, rebuilt from Sony's
Qt source. That is a much larger build, and a mistake there means no screen.)

Sources: `tools/resume/src/loader.c`, `tools/resume/src/resume.cpp`.

## The loader

It runs when the library is loaded and does nothing unless the process is
`HgrmMediaPlayerApp`. It starts one background thread and returns at once, so the app's
start is not delayed. The thread:

1. waits until the internal storage is visible (`/contents/MUSIC` or `/contents/LEARNING`);
2. uses the folder `/contents/audiobook-resume/`, which is `audiobook-resume` in the top
   folder of the player's storage when it is connected to a computer;
3. stops if a file named `disable` is there (the kill switch);
4. reads the counter file `starts`. If it is 2 or more, the last two starts were not
   confirmed healthy, and it stops (the guard). Otherwise it adds one and writes it back;
5. loads `libaudiobookresume.so` with every symbol resolved up front, so that a missing
   symbol is a refused load and not a crash later;
6. once the module has reported itself healthy for 20 seconds, writes `starts` = 0. If
   the write fails, for example because the storage is with the computer just then, it
   keeps trying.

So a module that breaks the app at start costs at most two bad starts. The third start
runs as if the add-on were not installed.

**What the guard does not cover:** the loader itself. If `libScreenshotShared.so` could not
be loaded at all, the app would not start. The installer therefore checks the checksum of
every file before and after writing it, and `tools/resume/check_elf.py` checks at build
time that everything the two libraries need exists on the player.

## The module

It never searches the app's objects. It registers Qt's signal-spy callbacks
(`qt_register_signal_spy_callbacks`, exported by the player's `libQt5Core.so.5`), which Qt
calls for every signal that is emitted. Of all that it only looks at objects of the class
`dmpapp::LanguageStudyPlayer`, the Audiobooks player. The music player is another class
(`dmpapp::StandardPlayer`) and is ignored.

From the app (decoded with `tools/re/qmeta.py`), that class and its base classes have:

| Name | Kind | Used for |
|---|---|---|
| `notifyTrackChanged(ContentsDBEntryId entry_id)` | signal | which track is current |
| `notifyPlaytime(int32_t playtime_msec, int32_t duration_msec)` | signal | position and length, once a second |
| `notifyPlayState(PlayState play_state)` | signal | 0 stopped, 1 playing, 2 paused; triggers a prompt save |
| `reqPrepareUmount()` | signal | the storage is about to go to the computer |
| `ReceiveSeek(MediaOrigin origin, int32_t offset_msec)` | slot | seek; origin 0 = from the start of the track, which is what the scrub bar sends |

Rules it follows:

- Callbacks only record what they see. They never call into the app.
- The seek is made from a timer on the app's main thread.
- Files are written by a separate thread.

Behaviour:

- While an audiobook track plays, its position is kept in memory and written to
  `positions.txt` every 10 seconds, and shortly after a track change or a pause.
- When a track becomes current and a position of at least 5 seconds is stored for it, the
  module waits for the first position report. If the track started from the beginning
  (under 3 seconds) and its length matches the stored length, it seeks to the stored
  position. If the app resumed the track by itself, the module leaves it alone.
- A track that is played to within 4 seconds of its end has its stored position removed,
  so it starts from the beginning next time.
- If the position jumps back to the start with no track change (you restarted the track,
  or the next track's first report came early), the stored position is kept until the
  track has played on for 5 seconds.
- When the app announces that the storage is about to be unmounted (USB connection), no
  file is touched for 20 seconds, and nothing is written while the storage is away.
- At most 512 tracks are remembered; after that the oldest entry is replaced.

Tracks are identified by their database entry id together with their length. On the test
player, ids looked like `0x89000000 + n` for Audiobooks and `0x10000000 + n` for music, and
stayed the same across a restart and a database update. If a track turns up under a new
id, and exactly one stored position has the very same length, and that stored id has not
been seen since the module started, the position is carried over to the new id. This is
for a rebuilt database or re-copied files. It can pick the wrong track only if two
recordings have the same length to the millisecond.

Why a file and not the player's database: the app's database client has no write call for
it, and "Rebuild Database" would wipe it.

## The folder `audiobook-resume`

| File | Meaning |
|---|---|
| `positions.txt` | one line per track: entry id, position in ms, length in ms, time saved |
| `log.txt` | starts, track changes, resumes, problems. Rolls over to `log.old.txt` |
| `starts` | the guard counter. 0 when the last start was healthy |
| `disable` | create this (empty) to keep the module from being loaded |
| `verbose` | create this (empty) for a detailed log, read at the next start |

If `log.txt` says the guard has switched the module off, delete `starts` to let it try again.

## How it is tested

`tools/resume/build.sh test` runs all of this in the build container:

- **A mock app on Linux** (`tools/resume/test/`) with classes of the same names, signals and
  slot as the player's. Covered: positions recorded; a track resumes when it comes back; a
  second run on the same storage, as after a restart; a finished track starts from the
  beginning; a track the app resumed itself is left alone; a changed length is not resumed;
  renumbered entries; the music player is never sought; the kill switch; the guard; a start
  that is never confirmed; a module that cannot be loaded; storage not visible; another
  program loading the loader; early reports of the next track; the unmount announcement.
- **The ARM files under emulation** (qemu-user) with the player's own dynamic loader,
  glibc 2.23, libc++ and Sony's Qt 5.3.2, and with Sony's real `libScreenshotShared.so`
  under its new name: the app's `screenshot::screenshot()` resolves to
  `libScreenshotOrigin.so`, the module loads, attaches, seeks and saves.
- **A symbol check** (`tools/resume/check_elf.py`): every library the two files need is on
  the player or installed with them, and every imported symbol is exported there with the
  same version.

## On a player

Version 1 ran on one NW-ZX300. Two tracks were played, switched between, and the player
restarted; each came back at its own position. Its log showed:

- The signals arrive as decoded: `notifyTrackChanged`, then `notifyPlaytime(0, length)`,
  then the play state.
- `ReceiveSeek(0, ms)` called directly works; the position report at the target arrives
  inside the call. A fallback through the player screen's scrub-bar slots is built in and
  was never needed.
- After a restart the app announces its last Audiobooks track again at position 0, and the
  module seeks it to the stored position.
- The unmount announcement arrives right when USB storage mode starts.
- The guard counter reached 2 on the second start, because the first start's "healthy"
  write fell into USB storage mode. One more such start would have switched the add-on off.

Version 2, which this repository builds, differs from version 1 in these points:

- the loader retries the "healthy" write until it succeeds (the problem above);
- the loader waits for `MUSIC` or `LEARNING`, so it does not depend on an internal
  `LEARNING` folder;
- the log is short by default, with the detailed one behind the `verbose` file;
- a position under 5 seconds no longer creates an entry;
- positions are carried over when entries are renumbered (see above).

It was installed on the same player over version 1. So far its log shows that it loaded
and took over the five positions version 1 had stored. Books on the SD card have ids of the
same form as those on the internal storage (`0x89000000 + n`), and positions were recorded
for them, including one in a single file of 40 hours. The test of a book coming back at
its position under version 2 had not been done when this was written.

## Not known

- Whether a book on the SD card comes back at its position. Positions are recorded for
  such books, and the module does not care where a track is stored, but the seek back was
  only seen with books on the internal storage.
- Whether the player stays reachable over USB if the player app does not start. This is
  why the loader is kept as small as it is.
