# Analysis scripts

Small Python 3 scripts written while looking for what switches Language Study off. They work
on a stripped 32-bit ARM (Thumb-2) program such as `vendor/sony/bin/HgrmMediaPlayerApp`, taken
out of a firmware image with `tools/ext4_get.py`. No dependencies. They are working tools, not
a polished package: several print "zx300" and "a50" for the first and second file.

| Script | What it does |
|---|---|
| `exidx.py <elf A> <elf B>` | Function boundaries from `.ARM.exidx`; lists functions whose size differs between two builds. Also the ELF helpers the other scripts import |
| `codediff.py <elf A> <elf B>` | Compares the two builds function by function, with branch targets and PC-relative literals resolved, so that shifted addresses do not show up as differences |
| `rodiff.py <elf A> <elf B>` | Byte differences of the data sections, resynchronising over insertions |
| `cg.py <elf> <out.pickle>` | Call graph plus string references for every function |
| `cgq.py` | Helpers to query that call graph, for use with `python3 -i cgq.py <cg.pickle>` (callers of a function, the source file name a function mentions) |
| `dxref.py <elf> <cg.pickle> <out.pickle>` | Data cross-references: which functions take the address of which data |
| `xref.py <elf> <address>...` | Direct callers of, and stored pointers to, each address |
| `qmeta.py <elf> <class name>...` | Prints a Qt class's signals, slots and properties from its meta-object, following its base classes. This is how the Audiobooks player's signals were found |
| `qrc_extract.py <elf> <out dir>` | Extracts the Qt resources (QML files, images) embedded in a program |

Examples:

```sh
python3 tools/re/qmeta.py HgrmMediaPlayerApp dmpapp::LanguageStudyPlayer
python3 tools/re/qrc_extract.py HgrmMediaPlayerApp out/
python3 tools/re/codediff.py zx300/HgrmMediaPlayerApp a50/HgrmMediaPlayerApp
```
