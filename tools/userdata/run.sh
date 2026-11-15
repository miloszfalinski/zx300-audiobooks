#!/bin/sh
# Applies (or undoes) the Audiobooks changes on a Sony NW-ZX300 with firmware 2.02.
#
# The package carries none of Sony's files. Sony's files are changed where they are, from a
# list of small edits, and the result of every edit is checked against a known checksum
# before anything on the player is written. The only whole files in the package are the two
# libraries of the resume add-on, which are not Sony's.
#
# nw-installer's install.sh runs this inside the updater, as
#   cd /contents/userdata && LOG_FILE=/contents/upgrade.log /bin/sh /contents/userdata/run.sh
# Errors printed by commands are not kept anywhere, so every result is written to LOG_FILE:
# read upgrade.log on the player's storage afterwards.
#
#   plan.txt   what to do, one step per line (written by tools/package.sh):
#                edit <path> <md5 of the result> <path to start from>
#                  put <offset> <bytes>     overwrite at <offset>
#                  add <offset> <bytes>     insert before <offset>
#                  cut <offset> <count>     take <count> bytes out at <offset>
#                end
#                copy <path> <md5>          put files/<path> there
#                remove <path>
#              <bytes> is written for printf: every byte as \NNN in octal.
#              A step whose result is already on the player is skipped.
#   files/     the files for the copy steps, laid out as under /system
#
# Two passes. The first builds every result in ./stage, away from /system, and checks it.
# Only if all of them check out does the second pass write to /system. So a player on other
# firmware, or with a file this package does not recognise, is left exactly as it was.
BB=/xbin/busybox
SYS=/system
: "${LOG_FILE:=/contents/upgrade.log}"
STAGE=./stage

log() { echo "$(date) audiobooks: $1" >> "$LOG_FILE"; }

# md5 of a file, empty if it cannot be read
md5of() {
    set -- $($BB md5sum "$1" 2>/dev/null)
    echo "$1"
}

# apply one edit line to the file $1
apply() {
    f=$1 op=$2 off=$3 arg=$4
    case "$op" in
        put)
            $BB printf "$arg" | $BB dd of="$f" bs=1 seek="$off" conv=notrunc 2>/dev/null
            ;;
        add)
            $BB dd if="$f" of="$f.part" bs=1 count="$off" 2>/dev/null &&
                $BB printf "$arg" >> "$f.part" &&
                $BB dd if="$f" bs=1 skip="$off" 2>/dev/null >> "$f.part" &&
                $BB mv "$f.part" "$f"
            ;;
        cut)
            $BB dd if="$f" of="$f.part" bs=1 count="$off" 2>/dev/null &&
                $BB dd if="$f" bs=1 skip="$((off + arg))" 2>/dev/null >> "$f.part" &&
                $BB mv "$f.part" "$f"
            ;;
        *)
            return 1
            ;;
    esac
}

# First pass. Builds ./stage/<n> for every step that has work to do and prints one line per
# problem. Nothing under /system is written.
stage() {
    n=0
    cur=
    while read -r kind a b c; do
        case "$kind" in
            edit)
                n=$((n + 1)); cur=; ok=1
                if test "$(md5of "$SYS/$a")" != "$b"; then
                    if $BB cp "$SYS/$c" "$STAGE/$n" 2>/dev/null; then
                        cur=$STAGE/$n; path=$a; want=$b; from=$c
                    else
                        log "not found on the player: $c"
                        echo x
                    fi
                fi
                ;;
            put|add|cut)
                if test -n "$cur"; then apply "$cur" "$kind" "$a" "$b" || ok=0; fi
                ;;
            end)
                if test -n "$cur"; then
                    if test "$ok" != 1 || test "$(md5of "$cur")" != "$want"; then
                        log "unknown version on the player: $from (md5 $(md5of "$SYS/$from"))"
                        echo x
                    fi
                fi
                cur=
                ;;
            copy)
                n=$((n + 1))
                if test "$(md5of "files/$a")" != "$b"; then
                    log "damaged in this package: $a"
                    echo x
                fi
                ;;
            remove)
                n=$((n + 1))
                ;;
        esac
    done < plan.txt
}

# Second pass. Writes what the first pass prepared.
commit() {
    n=0
    while read -r kind a b c; do
        case "$kind" in
            edit|copy)
                n=$((n + 1))
                if test "$kind" = edit; then src=$STAGE/$n; word=patched; else src=files/$a; word=copied; fi
                if test "$(md5of "$SYS/$a")" != "$b" && test -f "$src"; then
                    $BB cp "$src" "$SYS/$a"
                    case "$a" in
                        *.so|*/bin/*) $BB chmod 0755 "$SYS/$a" ;;
                        *)            $BB chmod 0644 "$SYS/$a" ;;
                    esac
                    log "$word: $a"
                fi
                ;;
            remove)
                n=$((n + 1))
                if test -e "$SYS/$a"; then
                    $BB rm -f "$SYS/$a"
                    log "removed: $a"
                fi
                ;;
        esac
    done < plan.txt
}

# prints the paths that are not as the plan wants them
pending() {
    while read -r kind a b c; do
        case "$kind" in
            edit|copy) test "$(md5of "$SYS/$a")" = "$b" || echo "$a" ;;
            remove)    test ! -e "$SYS/$a" || echo "$a" ;;
        esac
    done < plan.txt
}

log "start"
if ! test -s plan.txt; then
    log "this package is incomplete, nothing changed"
    exit 0
fi

mount -t ext4 -o rw /emmc@android $SYS

$BB rm -rf "$STAGE"
$BB mkdir -p "$STAGE"
if test -n "$(stage)"; then
    log "nothing changed: this package only fits NW-ZX300 firmware 2.02"
    $BB rm -rf "$STAGE"
    umount $SYS
    exit 0
fi

commit
sync
$BB rm -rf "$STAGE"

left=$(pending)
if test -z "$left"; then
    log "done: every file is in place"
else
    for path in $left; do
        log "FAILED, not in place: $path"
    done
fi

umount $SYS
