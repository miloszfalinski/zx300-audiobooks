# How Language Study is switched off on the NW-ZX300, and the five edits

Firmware compared: NW-ZX300 2.02 and NW-A50 1.02. The NW-A50 has Language Study; the NW-ZX300
does not show it. Both run the same player app, `HgrmMediaPlayerApp` (Qt 5.3.2, QML), built
per model.

All offsets below are file offsets in the stock NW-ZX300 2.02 files. Paths are under `/system`.

## The five edits

| # | File | Change | What it does |
|---|---|---|---|
| 1 | `vendor/sony/lib/libInitialObject.so` | offset `0x60f0`: `00` → `01` | `DeviceInfo::LanguageLearningAvailable` reports "available", so the player creates the `LEARNING` folder and its library |
| 2 | `vendor/sony/etc/default-capability_{w,j}_{internal,external0}.xml` (4 files) | one line added before `</path>`: `<learning>\LEARNING\</learning>` | declares the `LEARNING` folder to the storage layer, for the internal storage and the SD card |
| 3 | `vendor/sony/translations/HgrmMediaPlayerApp_en_US.qm` | 9 strings, same length | the label "Language Study" becomes "Audiobooks" |
| 4 | `vendor/sony/bin/HgrmMediaPlayerApp` | offset `0x1de9c4`: `80 b5 6f 46` → `01 20 70 47` | the app's "is Language Study available" getter returns true: the button appears and the `LEARNING` folder is indexed |
| 5 | `vendor/sony/bin/HgrmMediaPlayerApp` | offset `0x7e3f1`: `20` → `30` | Language Study is true in the app's feature table: its screens are loaded instead of an empty one |

Edits 1, 2 and 5 make the NW-ZX300 files equal to the NW-A50's at those places. MD5 of the
app: stock `bc91510ff924d28288986289182dedc2`, with edits 4 and 5
`e77dcd59f829b0ee3d12b5cdfdb9c069`.

`tools/prepare.sh` makes all five from Sony's updater. `tools/package.sh` refuses to pack
unless the files differ from Sony's by exactly these edits.

### 1. The library flag

`libInitialObject.so` is the same on both models except for one instruction in
`DeviceInfo::LanguageLearningAvailable(available_t*)`: `movs r0,#0` on the NW-ZX300,
`movs r0,#1` on the NW-A50. The library uses the result when it sets up a storage: with 1
it creates the `LEARNING` folder and library node. On the test player the folder appeared on
the first start after the edit.

### 2. The capability files

Each of the four files gets, inside `<filesystem><path>`, the line the NW-A50's files have:

```xml
      <path>
        <sound>\MUSIC\</sound>
        <learning>\LEARNING\</learning>
      </path>
```

The player copies the matching file to the top folder of each storage as
`default-capability.xml`, and after the edit both the internal storage and the SD card
carry the new line. A `LEARNING` folder on the card is listed in Audiobooks like the
internal one.

### 3. The label

The visible name is not in the program. It is nine translated strings in the Qt translation
file. `tools/qm_rename.py` replaces each with a text of the same length, padded with spaces,
so that nothing in the file's index moves and no Qt tool is needed:

| Before | After |
|---|---|
| `Language Study` (the button and the title) | `Audiobooks` |
| `Language Study Settings` (2 places) | `Audiobooks Settings` |
| `Move Songs to Language Study` (4 menu entries) | `Move Songs to Audiobooks` |
| `...the language study library...` (2 messages) | `...the audiobooks library...` |

Only the English file is changed. For another language, add that language's wording to
the list in the script and run it on that language's `.qm`.

### 4 and 5. The app

Edits 1 and 2 alone give a `LEARNING` folder and no way to open it: the button is decided
inside the app.

The app has a table of 55 feature switches, built by a static initializer at
`0x7e3d8`-`0x7e5a6`. Each entry is one instruction that stores a register holding 0 or 1:

```
0x7e3ee:  8d f8 64 20    strb.w r2, [sp, #0x64]     ; key 2, r2 = 0   (NW-ZX300)
          8d f8 64 30    strb.w r3, [sp, #0x64]     ; key 2, r3 = 1   (NW-A50)
```

Key 0 is the FM radio, 1 the recorder, 2 Language Study, 3 the DAC mode. 27 of the 55 differ
between the two models; [feature-table.tsv](feature-table.tsv) lists them all.

The table is read in two ways, and that is why two edits were needed:

- **Through the Feature object.** At start the table is copied into an object, and QML
  asks that object through getters. The one for Language Study is at `0x1de9c4`
  (`isAvailableLangStudy`, `hasFeatureLanguageStudy`). Edit 4 makes it `movs r0,#1; bx lr`.
  With only this edit the button appears, the folder is indexed and tracks play, but every
  Language Study screen is black inside its frame.
- **Straight from the table.** Each group of screens has a "creator" object that maps a
  screen to its QML file. Before it looks the screen up, the base class asks the creator
  whether its feature exists. For Language Study that is `movs r0,#2; b 0x151874` (at
  `0x309aac`), and `0x151874` looks the key up in the table itself, not in the Feature
  object. If the answer is no, the creator returns `qrc:/components/Blank.qml`, an empty
  item. The window around it comes from another table with no such check, which is why
  the title bar and the player bar were drawn around a black area. Edit 5 makes the table
  entry true.

With the table entry true, edit 4 is probably not needed any more, because the Feature
object copies the table. That was not tried: the pair is what runs on the test player.

The FM radio and the recorder (keys 0 and 1) go through the same two paths.

## What else differs between the two models

The two system images hold 1,597 files with the same path; 1,540 are identical. In the app:

- Function by function (10,144 functions in both builds, boundaries taken from
  `.ARM.exidx`, branch targets and literal offsets resolved so that shifted addresses do
  not count), the only real differences are the feature table above and a few getters for
  the copyright years and the model name.
- All strings and all embedded resources (38 resource trees: 312 QML files and 809 images)
  are identical apart from the model name and copyright texts. The Language Study screens
  and artwork are all present in the NW-ZX300 build; nothing had to be added.
- `ScreenSettings.json` (screens and transitions) is the same file on both.

Other libraries that differ per model (`libDmpFeature.so`, `libDmpConfig.so`,
`libPathMgrServiceFw.so`, `libSoundService.so`, one byte in `libConfigurationService.so`)
hold audio hardware settings and defaults. None of them concerns Language Study.

## Tools used

In `tools/`:

- `ext4_get.py`, `ext4_walk.py`: list, search and extract the files of a system image
  without mounting it.
- `re/`: small scripts for comparing two builds of a stripped ARM (Thumb-2) program and for
  reading Qt structures out of it. See [tools/re/README.md](../tools/re/README.md).
