# Putting books on the player

How to lay out audiobook files so that the **Audiobooks** library lists them with their
names and each book comes back where you left it.

## In short

- Books go in the `LEARNING` folder, in the top folder of the internal storage or of the
  SD card.
- **One file per book** suits the resume add-on best: the book is one track with one stored
  position.
- Give every file a **title**, an **album** and an **artist** tag. The library is built from
  the tags. Folder names and file names are not shown anywhere.
- Use `.m4a` or `.mp3`. The player skips a file named `.m4b`; rename it to `.m4a`.
- Put the cover inside the file, as a **baseline JPEG**. A `cover.jpg` in the folder does
  nothing.
- Run every MP4 file through `tools/scancheck/mp4-short-headers.py` before you copy it. It
  removes the one thing in such files that makes the player list a book as "Unknown".

```
LEARNING/
    First Book/
        First Book.m4a          tags: title "First Book", album "First Book", artist "Author Name"
    Second Book/
        Second Book.m4a
```

## Where the files go

The player creates `LEARNING` in the top folder of its internal storage, next to `MUSIC`, on
the first start after the install. On an SD card, create a folder of that name in the top
folder of the card if it is not there.

Copy the books in with the player in USB Mass Storage mode, then disconnect. The player
updates its database, and the books appear under **Audiobooks**. The two libraries are
separate: what is in `LEARNING` is listed in Audiobooks and not in the music library.

Folders inside `LEARNING` are for your own order on the computer. The Audiobooks library
has five lists (All Songs, Albums, Artists, Playlists, Recently added) and no folder view.
Files directly in `LEARNING` and files one folder down were both listed on the test player.
Deeper folders were not tried.

File names: leave out the characters that the player's file systems do not allow,
`: \ / * ? " < > |`. A colon in a book's title is the usual case. Apostrophes are fine.

File size: the internal storage of the test player is FAT32, where one file has to be
smaller than 4 GB. Its SD card was exFAT, which has no such limit.

## One file per book, or one file per chapter

The resume add-on stores a position per track, and a track is a file. The player itself
remembers only which Audiobooks track was played last.

| | One file per book | One file per chapter |
|---|---|---|
| Coming back to a book | Open it and it continues where you stopped, however many other books you heard in between | Every chapter has its own position, but you have to find the chapter you were in yourself, unless it was the last thing played in Audiobooks |
| Moving around in the book | Scrub bar and quick replay only | Chapters are tracks, so you can pick one from the list |
| Chapter marks inside the file | Not shown. The player app has no chapter feature | Not needed |
| When it is played to the end | The stored position is removed, and the book starts from the beginning next time | The same, per chapter |

If you listen to several books in turn, one file per book is the layout that makes
resume do what you expect. The price is the scrub bar: in a book of many hours a small
movement is several minutes.

A middle way is a few long parts per book. Each part then has its own position.

For a book in several files, number the file names (`01 ...`, `02 ...`) and set the track
number tags to match. Which of the two the player orders by, and whether it plays on into
the next file by itself, was not checked.

## Tags

The player's parser reads these from a file: title, album, artist, album artist, genre,
composer, year, and the cover picture. The lists in Audiobooks show the title (All Songs),
the album (Albums) and the artist (Artists). A file whose tags the player cannot read is
listed as "Unknown".

For a book in one file:

| Tag | Put there |
|---|---|
| Title | the book's title |
| Album | the book's title again |
| Artist | the author |

Audiobook downloads usually come tagged like this already, and then nothing needs changing.
On the test player the tags were left as downloaded (album "Title (Unabridged)", artist and
album artist the author), and every book was listed as one entry.

For a book in several files, give all of them the same album and artist, and each its own
title.

## File types

The player's scanner looks at files with these endings: `.mp3`, `.m4a`, `.mp4`, `.aac`,
`.flac`, `.wav`, `.aif`, `.aiff`, `.ape`, `.dsf`, `.dff`, `.wma`, `.oma`, `.ogg`, `.3gp`.
`.m4b` is not among them, and an `.m4b` file copied to the test player never appeared in
the library. It is an ordinary MP4 audio file under another name, so renaming it to `.m4a`
is enough. Nothing has to be converted and no quality is lost.

Only MP3 files and AAC audio in `.m4a` files were tried in Audiobooks. The files have to be
free of copy protection.

## Covers

The player shows the cover that is stored inside the file. A picture file next to the audio
(`cover.jpg`, `folder.jpg`) is not used: on the test player a book with no cover inside and
a `cover.jpg` beside it showed no cover, and neither name occurs in any program on the
player.

The picture inside has to be a **baseline** JPEG. The player does not show a
**progressive** JPEG. Twelve books were on the test player, each with a 2400 x 2400 JPEG
cover inside. The two whose cover is baseline showed it. The ten whose cover is progressive
showed none, and after their covers were converted with the tool below, all twelve showed
their covers.

To see what a file has, and to convert it:

```sh
tools/scancheck/mp4-baseline-cover.py --show "First Book.m4a"
# First Book.m4a: progressive JPEG, 2400 x 2400, 146893 bytes

tools/scancheck/mp4-baseline-cover.py "First Book.m4a" "First Book with baseline cover.m4a"
```

The second command writes a copy in which only the picture is stored the other way. The
audio and all other tags are copied byte for byte. With `jpegtran` installed
(`brew install jpeg-turbo`) the conversion is lossless, the same picture to the pixel.
Without it the tool uses macOS's `sips`, which encodes the picture again. A file whose cover
is already baseline is copied unchanged.

Write the new file to a folder on the computer and copy it to the player afterwards.
Writing straight to the SD card failed on the test setup.

## The time headers: run the tool before copying

An MP4 file states its length in a 32-bit or a 64-bit form. The player does not accept the
64-bit form and then lists the file as "Unknown" with no playing time, whatever its tags
say. Some audiobook downloads are written that way, and so is the output of ffmpeg in some
cases. [build-and-install.md](build-and-install.md#books-that-show-up-as-unknown) has the
details.

One command covers both the renaming and the headers:

```sh
tools/scancheck/mp4-short-headers.py "First Book.m4b" "First Book.m4a"
```

If the file has 64-bit headers, the copy gets 32-bit ones, and the audio, the tags and the
cover are copied byte for byte. If it has none, the copy is identical to the original and
the tool says `no 64-bit time headers, copied unchanged`. It needs only Python 3.

To be sure about a file before it goes on the player:

```sh
tools/scancheck/check.sh "/path/under/your/home/First Book.m4a"
```

This runs the player's own parser on the file, on the Mac, and prints the title, the
artist and the playing time the player will get, ending with `READABLE` or `NOT READABLE`.
It needs the build setup described in [build-and-install.md](build-and-install.md). It does
not tell whether the cover will be shown.

If you make the files with ffmpeg and want a cover in them, take the cover from a separate
picture file. Copying the cover stream over from an `.m4b` together with the audio is what
makes ffmpeg write 64-bit headers for anything longer than about 8 minutes.

## Limits

- A track longer than 2^32 audio samples (27 hours at 44.1 kHz, 54 hours at 22.05 kHz)
  cannot have 32-bit headers. Split such a book.
- The resume add-on remembers 512 tracks. After that the oldest position is replaced.
- A position under 5 seconds is not stored.

## What this is based on

- **From the firmware:** the list of file endings, the five lists of the Audiobooks
  library, the absence of a chapter feature and of folder cover names, and the tags the
  parser reads.
- **The player's parser run on a Mac:** twelve books in one file each, the longest 40
  hours, AAC in MP4. Ten were readable as downloaded, two had 64-bit headers and were
  readable after the header tool.
- **On the test player:**
  - Those twelve books, one file each in a folder of its own on an exFAT SD card, were all
    listed with their titles. The largest file is 1.16 GB.
  - Files with 64-bit headers were listed as "Unknown", and `.m4b` files not at all.
  - Covers: two of twelve shown at first, all twelve after the ten progressive ones were
    converted to baseline. `cover.jpg` had no effect.
  - Positions were recorded for books on the card, the 40-hour one among them.
  - Two tracks on the internal storage each came back at their own position, also after a
    restart.
- **Not tried yet:** a book coming back at its position from the SD card, folders more
  than one level deep, and the order of a book in several files.
