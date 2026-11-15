/*
 * Audiobooks resume module for the Sony NW-ZX300 (libaudiobookresume.so).
 *
 * Loaded into HgrmMediaPlayerApp by the loader (loader.c). It gives every track of the
 * Audiobooks (Language Study) player its own resume position, kept in a file.
 *
 * How it sees the player: Qt's signal-spy callbacks (qt_register_signal_spy_callbacks,
 * exported by libQt5Core) are called for every signal emission and for every slot called
 * through a connection. Only objects whose class is defined in the app itself are looked
 * at, and of those only the class dmpapp::LanguageStudyPlayer is acted on:
 *
 *   signal notifyTrackChanged(ContentsDBEntryId)       -> which track is current
 *   signal notifyPlaytime(int32_t pos_ms, int32_t len) -> position and length
 *   signal notifyPlayState(PlayState)                  -> logged, triggers a save
 *   slot   ReceiveSeek(MediaOrigin, int32_t ms)        -> origin 0 = from the start
 *
 * Rules:
 *   - callbacks only record; they never call into the app;
 *   - the seek is made from a timer on the app's main thread;
 *   - files are written by a worker thread;
 *   - the music player (another class) is never acted on.
 *
 * See docs/resume-add-on.md.
 */
#include <QtCore/QByteArray>
#include <QtCore/QCoreApplication>
#include <QtCore/QEvent>
#include <QtCore/QMetaMethod>
#include <QtCore/QMetaObject>
#include <QtCore/QObject>
#include <QtCore/QPointer>
#include <QtCore/QThread>

#include <errno.h>
#include <link.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define ABR_VERSION "2"

/* From Qt's private qobject_p.h, unchanged from Qt 5.0 to 5.13. */
struct QSignalSpyCallbackSet {
    typedef void (*BeginCallback)(QObject *caller, int signal_or_method_index, void **argv);
    typedef void (*EndCallback)(QObject *caller, int signal_or_method_index);
    BeginCallback signal_begin_callback, slot_begin_callback;
    EndCallback signal_end_callback, slot_end_callback;
};
void Q_CORE_EXPORT qt_register_signal_spy_callbacks(const QSignalSpyCallbackSet &callback_set);

static const char LS_PLAYER_CLASS[] = "dmpapp::LanguageStudyPlayer";
static const char LS_VM_CLASS[] = "dmpapp::LanguageStudyPlayerViewModel";

enum {
    MIN_RESUME_MS = 5000,       /* shorter stored positions are not worth a seek */
    START_WINDOW_MS = 3000,     /* "the track started from the beginning" */
    END_MARGIN_MS = 5000,       /* do not seek into the last seconds */
    FINISHED_MARGIN_MS = 4000,  /* a track left this close to its end counts as finished */
    LENGTH_TOLERANCE_MS = 2000,
    SAVE_INTERVAL_MS = 10000,
    TICK_MS = 250,
    SEEK_CONFIRM_MS = 3000,
    MAX_ENTRIES = 512,
    LOG_MAX_BYTES = 512 * 1024
};

/* ---------- time ---------- */

static int64_t now_ms()
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* ---------- log: buffered here, written by the worker thread ---------- */

static char g_dir[200];
static pthread_mutex_t g_logmu = PTHREAD_MUTEX_INITIALIZER;
static char g_logbuf[32768];
static size_t g_loglen;
static unsigned g_logdropped;

static bool g_verbose;      /* the file "verbose" was in the folder when the module started */

static void vrlog(const char *fmt, va_list ap)
{
    char line[480], stamp[32];
    time_t t = time(NULL);
    struct tm tmv;
    int n;

    localtime_r(&t, &tmv);
    strftime(stamp, sizeof stamp, "%Y-%m-%d %H:%M:%S", &tmv);
    n = snprintf(line, sizeof line, "%s resume: ", stamp);
    vsnprintf(line + n, sizeof line - n - 1, fmt, ap);
    n = (int)strlen(line);
    line[n++] = '\n';

    pthread_mutex_lock(&g_logmu);
    if (g_loglen + (size_t)n <= sizeof g_logbuf) {
        memcpy(g_logbuf + g_loglen, line, (size_t)n);
        g_loglen += (size_t)n;
    } else {
        ++g_logdropped;
    }
    pthread_mutex_unlock(&g_logmu);
}

/* what matters in daily use: starts, track changes, resumes, problems */
static void rlog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void rlog(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vrlog(fmt, ap);
    va_end(ap);
}

/* detail for looking into a problem: only with the file "verbose" in the folder */
static void vlog(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void vlog(const char *fmt, ...)
{
    va_list ap;
    if (!g_verbose)
        return;
    va_start(ap, fmt);
    vrlog(fmt, ap);
    va_end(ap);
}

static bool is_dir(const char *p)
{
    struct stat st;
    return stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}

/* Set when the app tells its players that the storage is about to be unmounted (it is then
   handed to the computer over USB). An open file of ours at that moment could get in the
   way, so no file is touched for a while; after that the folder is simply gone until the
   storage is back, and is_dir() says so. */
static volatile int64_t g_io_hold_until;

static bool storage_usable()
{
    return now_ms() >= g_io_hold_until && is_dir(g_dir);
}

static void flush_log()
{
    static char out[sizeof g_logbuf];
    char p[260], old[260];
    struct stat st;
    size_t n;
    unsigned dropped;
    FILE *f;

    if (!storage_usable())
        return;                         /* storage exported over USB: keep buffering */
    pthread_mutex_lock(&g_logmu);
    n = g_loglen;
    memcpy(out, g_logbuf, n);
    g_loglen = 0;
    dropped = g_logdropped;
    g_logdropped = 0;
    pthread_mutex_unlock(&g_logmu);
    if (!n && !dropped)
        return;
    snprintf(p, sizeof p, "%s/log.txt", g_dir);
    if (stat(p, &st) == 0 && st.st_size > LOG_MAX_BYTES) {
        snprintf(old, sizeof old, "%s/log.old.txt", g_dir);
        rename(p, old);
    }
    f = fopen(p, "a");
    if (!f)
        return;
    fwrite(out, 1, n, f);
    if (dropped)
        fprintf(f, "(%u log lines dropped)\n", dropped);
    fclose(f);
}

/* ---------- state, all under g_mu ---------- */

struct Entry {
    uint32_t id;
    int32_t pos;
    int32_t dur;
    int64_t when;       /* wall clock, seconds */
};

static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static Entry g_tab[MAX_ENTRIES];
static int g_n;
static bool g_dirty, g_prompt;
static int64_t g_last_save_ms;

/* the current Audiobooks track */
static bool c_have;         /* its entry id is known */
static bool c_frozen;       /* do not store positions until the next track change */
static bool c_restarted;    /* the position jumped back to the start without a track change */
static bool c_first;        /* no position report with a length yet since the track change */
static uint32_t c_id;
static int32_t c_pos = -1, c_dur;

enum RestoreState { RS_NONE, RS_WAIT_FIRST, RS_REQUESTED, RS_ISSUED };
static RestoreState r_state = RS_NONE;
static int32_t r_target, r_dur;
static int r_attempts;
static int64_t r_issued_ms;

static unsigned g_nsignals, g_nslots, g_ls_events, g_ls_playtime, g_ls_other_logged;
static bool g_warned_noid;

/* entry ids announced since the module started: those are certainly still valid */
enum { MAX_SEEN = 128 };
static uint32_t g_seen[MAX_SEEN];
static int g_nseen;

static bool seen_this_session(uint32_t id)
{
    for (int i = 0; i < g_nseen; ++i)
        if (g_seen[i] == id)
            return true;
    return false;
}

static Entry *find_entry(uint32_t id)
{
    for (int i = 0; i < g_n; ++i)
        if (g_tab[i].id == id)
            return &g_tab[i];
    return 0;
}

static void remove_entry(uint32_t id)
{
    Entry *e = find_entry(id);
    if (!e)
        return;
    *e = g_tab[--g_n];
    g_dirty = true;
}

static void upsert_entry(uint32_t id, int32_t pos, int32_t dur)
{
    Entry *e = find_entry(id);
    if (!e) {
        if (g_n == MAX_ENTRIES) {       /* full: replace the oldest */
            e = &g_tab[0];
            for (int i = 1; i < g_n; ++i)
                if (g_tab[i].when < e->when)
                    e = &g_tab[i];
        } else {
            e = &g_tab[g_n++];
        }
        e->id = id;
    }
    e->pos = pos;
    e->dur = dur;
    e->when = (int64_t)time(NULL);
    g_dirty = true;
}

static void on_track(uint32_t id)
{
    rlog("track changed: entry %u (was %u at %d of %d ms)", id, c_have ? c_id : 0u, c_pos, c_dur);
    if (c_have && !c_frozen && c_dur > 0 && c_pos >= 0 && c_dur - c_pos <= FINISHED_MARGIN_MS) {
        remove_entry(c_id);
        rlog("entry %u was played to its end, stored position removed", c_id);
    }
    if (id && !seen_this_session(id))
        g_seen[g_nseen < MAX_SEEN ? g_nseen++ : MAX_SEEN - 1] = id;
    c_have = id != 0;
    c_id = id;
    c_pos = -1;
    c_dur = 0;
    c_frozen = false;
    c_restarted = false;
    c_first = true;
    r_state = RS_NONE;
    Entry *e = c_have ? find_entry(id) : 0;
    if (e && e->pos >= MIN_RESUME_MS) {
        r_state = RS_WAIT_FIRST;
        r_target = e->pos;
        r_dur = e->dur;
        r_attempts = 0;
        rlog("entry %u has a stored position: %d of %d ms", id, e->pos, e->dur);
    }
    g_prompt = true;
}

static void on_playtime(int32_t pos, int32_t dur)
{
    ++g_ls_playtime;
    vlog("position %d of %d ms (entry %u)", pos, dur, c_have ? c_id : 0u);
    if (!c_have) {
        if (!g_warned_noid) {
            g_warned_noid = true;
            rlog("position reports before any track change: the entry is unknown, nothing stored");
        }
        return;
    }
    if (c_frozen || dur <= 0 || pos < 0)
        return;

    if (c_first) {
        /* Entry ids are renumbered when the database is rebuilt or files are copied again.
           If this id is new, and exactly one stored position has this very length and
           belongs to an id that has not shown up since the module started, take it to be
           the same recording under its old number and carry the position over. */
        c_first = false;
        if (r_state == RS_NONE && !find_entry(c_id)) {
            Entry *same = 0;
            int n = 0;
            for (int i = 0; i < g_n; ++i)
                if (g_tab[i].dur == dur) {
                    same = &g_tab[i];
                    ++n;
                }
            if (n == 1 && !seen_this_session(same->id)) {
                rlog("entry %u is new but has the length of stored entry %u (%d ms): taking over its position %d ms",
                     c_id, same->id, dur, same->pos);
                same->id = c_id;
                g_dirty = true;
                if (same->pos >= MIN_RESUME_MS) {
                    r_state = RS_WAIT_FIRST;
                    r_target = same->pos;
                    r_dur = same->dur;
                    r_attempts = 0;
                }
            }
        }
    }

    if (r_state == RS_WAIT_FIRST) {
        int32_t d = dur - r_dur;
        if (d < -LENGTH_TOLERANCE_MS || d > LENGTH_TOLERANCE_MS) {
            rlog("stored length %d ms does not match %d ms, not resuming", r_dur, dur);
            r_state = RS_NONE;
        } else if (pos >= START_WINDOW_MS) {
            rlog("the track is already at %d ms, leaving it", pos);
            r_state = RS_NONE;
        } else if (r_target > dur - END_MARGIN_MS) {
            r_state = RS_NONE;
        } else {
            r_state = RS_REQUESTED;
            rlog("entry %u started at %d ms, will seek to %d ms", c_id, pos, r_target);
            return;
        }
    } else if (r_state == RS_REQUESTED) {
        return;                         /* the timer has not made the seek yet */
    } else if (r_state == RS_ISSUED) {
        if (pos < r_target - 3000)
            return;                     /* the seek has not landed yet: do not store this */
        rlog("confirmed, now at %d ms", pos);
        r_state = RS_NONE;
    }

    if (c_dur > 0) {
        int32_t d = dur - c_dur;
        if (d < -LENGTH_TOLERANCE_MS || d > LENGTH_TOLERANCE_MS) {
            rlog("length changed from %d to %d ms without a track change, "
                 "nothing stored until the next track change", c_dur, dur);
            c_frozen = true;
            return;
        }
    }
    /* A jump back to the start with no track change is either the listener restarting the
       track or the first report of the next track arriving before its track change. Only
       the first may replace the stored position, so wait until it has played on a little. */
    if (pos < START_WINDOW_MS && c_pos > 10000 && !c_restarted) {
        c_restarted = true;
        rlog("position went back to %d ms without a track change, stored position kept for now", pos);
    }
    if (c_restarted) {
        if (pos < MIN_RESUME_MS)
            return;
        c_restarted = false;
    }
    c_pos = pos;
    c_dur = dur;
    if (pos >= MIN_RESUME_MS || find_entry(c_id))
        upsert_entry(c_id, pos, dur);
}

/* ---------- positions file ---------- */

static void load_positions()
{
    char p[260], line[128];
    FILE *f;

    snprintf(p, sizeof p, "%s/positions.txt", g_dir);
    f = fopen(p, "r");
    if (!f)
        return;
    while (g_n < MAX_ENTRIES && fgets(line, sizeof line, f)) {
        unsigned id;
        int pos, dur;
        long long when = 0;
        if (line[0] == '#')
            continue;
        if (sscanf(line, "%u %d %d %lld", &id, &pos, &dur, &when) >= 3 && id && pos >= 0 && dur > 0 && !find_entry(id)) {
            Entry *e = &g_tab[g_n++];
            e->id = id;
            e->pos = pos;
            e->dur = dur;
            e->when = when;
        }
    }
    fclose(f);
}

/* called by the worker thread; true when there is nothing left to write */
static bool save_positions()
{
    static char out[MAX_ENTRIES * 48 + 128];
    char p[260], tmp[260];
    int64_t now = now_ms();
    size_t n = 0;
    FILE *f;

    if (!storage_usable())
        return false;
    pthread_mutex_lock(&g_mu);
    if (!g_dirty) {
        g_prompt = false;
        pthread_mutex_unlock(&g_mu);
        return true;
    }
    if (!g_prompt && now - g_last_save_ms < SAVE_INTERVAL_MS) {
        pthread_mutex_unlock(&g_mu);
        return false;
    }
    n += (size_t)snprintf(out + n, sizeof out - n, "# audiobook resume positions: entry_id position_ms length_ms saved_at\n");
    for (int i = 0; i < g_n; ++i)
        n += (size_t)snprintf(out + n, sizeof out - n, "%u %d %d %lld\n", g_tab[i].id, g_tab[i].pos, g_tab[i].dur, (long long)g_tab[i].when);
    g_dirty = false;
    g_prompt = false;
    g_last_save_ms = now;
    pthread_mutex_unlock(&g_mu);

    bool ok = false;
    if (storage_usable()) {
        snprintf(p, sizeof p, "%s/positions.txt", g_dir);
        snprintf(tmp, sizeof tmp, "%s/positions.tmp", g_dir);
        f = fopen(tmp, "w");
        if (f) {
            ok = fwrite(out, 1, n, f) == n;
            ok = fclose(f) == 0 && ok;
            if (ok)
                ok = rename(tmp, p) == 0;
        }
    }
    if (!ok) {                          /* e.g. storage exported over USB: try again later */
        pthread_mutex_lock(&g_mu);
        g_dirty = true;
        pthread_mutex_unlock(&g_mu);
    }
    return ok;
}

/* ---------- which objects to look at ---------- */

enum Kind { K_LS_PLAYER = 1, K_OTHER_PLAYER, K_LS_VM };

struct ClassInfo {
    char name[80];
    int kind;
    int si_track, si_playtime, si_state;    /* signal indices, -1 if absent */
    int si_umount;                          /* reqPrepareUmount() */
    int logged;
};

static ClassInfo *const UNINTERESTING = (ClassInfo *)1;
static const void *g_app_lo, *g_app_hi;     /* address range of the app's own image */

enum { CACHE_SIZE = 1024, CACHE_PROBES = 16 };
static struct { const void *vptr; ClassInfo *ci; } g_cache[CACHE_SIZE];

static ClassInfo *cache_lookup(const void *vptr)
{
    unsigned h = (unsigned)((uintptr_t)vptr >> 3);
    for (int k = 0; k < CACHE_PROBES; ++k) {
        unsigned i = (h + (unsigned)k) & (CACHE_SIZE - 1);
        if (g_cache[i].vptr == vptr)
            return g_cache[i].ci;
        if (!g_cache[i].vptr)
            return 0;
    }
    return 0;
}

static void cache_insert(const void *vptr, ClassInfo *ci)
{
    unsigned h = (unsigned)((uintptr_t)vptr >> 3);
    for (int k = 0; k < CACHE_PROBES; ++k) {
        unsigned i = (h + (unsigned)k) & (CACHE_SIZE - 1);
        if (!g_cache[i].vptr) {
            g_cache[i].ci = ci;
            __sync_synchronize();
            g_cache[i].vptr = vptr;
            return;
        }
    }
}

static ClassInfo *classify(QObject *o, const void *vptr)
{
    const QMetaObject *mo = o->metaObject();
    const char *cn = mo ? mo->className() : 0;
    int kind = 0, si_track = -1, si_playtime = -1, si_state = -1, si_umount = -1;

    if (cn && strcmp(cn, LS_VM_CLASS) == 0) {
        kind = K_LS_VM;
    } else if (cn) {
        /* Signal indices count the signals of the whole class chain, base class first,
           which is the order QMetaObject::method() walks them in. */
        int sig = 0;
        for (int i = 0, n = mo->methodCount(); i < n; ++i) {
            QMetaMethod m = mo->method(i);
            if (m.methodType() != QMetaMethod::Signal)
                continue;
            QByteArray s = m.methodSignature();
            if (s == "notifyTrackChanged(ContentsDBEntryId)")
                si_track = sig;
            else if (s == "notifyPlaytime(int32_t,int32_t)")
                si_playtime = sig;
            else if (s == "notifyPlayState(PlayState)")
                si_state = sig;
            else if (s == "reqPrepareUmount()")
                si_umount = sig;
            ++sig;
        }
        if (si_playtime >= 0)
            kind = strcmp(cn, LS_PLAYER_CLASS) == 0 ? K_LS_PLAYER : K_OTHER_PLAYER;
    }
    if (!kind) {
        cache_insert(vptr, UNINTERESTING);
        return UNINTERESTING;
    }
    ClassInfo *ci = (ClassInfo *)calloc(1, sizeof *ci);
    if (!ci)
        return UNINTERESTING;
    strncpy(ci->name, cn, sizeof ci->name - 1);
    ci->kind = kind;
    ci->si_track = si_track;
    ci->si_playtime = si_playtime;
    ci->si_state = si_state;
    ci->si_umount = si_umount;
    cache_insert(vptr, ci);
    vlog("found class %s (%s), signal indices: track %d, position %d, state %d",
         cn, kind == K_LS_PLAYER ? "the Audiobooks player" : kind == K_LS_VM ? "the Audiobooks player screen" : "another player, ignored",
         si_track, si_playtime, si_state);
    return ci;
}

static ClassInfo *class_of(QObject *o)
{
    const void *vptr = *reinterpret_cast<const void *const *>(o);
    if (vptr < g_app_lo || vptr >= g_app_hi)
        return UNINTERESTING;           /* a Qt or QML class: never touched */
    ClassInfo *ci = cache_lookup(vptr);
    return ci ? ci : classify(o, vptr);
}

/* text for the first three arguments, read as 32-bit integers */
static void format_args(char *out, size_t n, const QMetaMethod &m, void **argv)
{
    size_t len = 0;
    out[0] = '\0';
    for (int i = 0; i < m.parameterCount() && i < 3 && argv && argv[i + 1]; ++i)
        len += (size_t)snprintf(out + len, n - len, "%s%d", i ? ", " : "", *reinterpret_cast<const int32_t *>(argv[i + 1]));
}

static QMetaMethod signal_at(const QMetaObject *mo, int signal_index)
{
    int sig = 0;
    for (int i = 0, n = mo->methodCount(); i < n; ++i) {
        QMetaMethod m = mo->method(i);
        if (m.methodType() != QMetaMethod::Signal)
            continue;
        if (sig++ == signal_index)
            return m;
    }
    return QMetaMethod();
}

/* ---------- the spy callbacks: record only ---------- */

static QObject *volatile g_player_raw;
static QObject *volatile g_vm_raw;

static void spy_signal(QObject *sender, int signal_index, void **argv)
{
    ++g_nsignals;
    if (signal_index <= 1) {            /* QObject::destroyed */
        if (sender == g_player_raw)
            g_player_raw = 0;
        if (sender == g_vm_raw)
            g_vm_raw = 0;
        return;
    }
    ClassInfo *ci = class_of(sender);
    if (ci == UNINTERESTING || ci->kind == K_LS_VM)
        return;

    if (signal_index == ci->si_umount) {    /* any player: the storage is about to go */
        if (now_ms() >= g_io_hold_until)
            vlog("the app is preparing to unmount the storage, files left alone for 20 s");
        g_io_hold_until = now_ms() + 20000;
    }

    bool track = signal_index == ci->si_track;
    bool playtime = signal_index == ci->si_playtime;
    bool state = signal_index == ci->si_state;

    if (ci->kind == K_OTHER_PLAYER) {
        if (g_verbose && (track || playtime || state) && ci->logged < 6) {
            char args[64];
            QMetaMethod m = signal_at(sender->metaObject(), signal_index);
            format_args(args, sizeof args, m, argv);
            ++ci->logged;
            rlog("ignored: %s emitted %s [%s]", ci->name, m.methodSignature().constData(), args);
        }
        return;
    }

    g_player_raw = sender;
    if (!track && !playtime && !state) {
        if (g_verbose && g_ls_other_logged < 200) {
            char args[64];
            QMetaMethod m = signal_at(sender->metaObject(), signal_index);
            format_args(args, sizeof args, m, argv);
            ++g_ls_other_logged;
            rlog("Audiobooks player emitted %s [%s]", m.methodSignature().constData(), args);
        }
        return;
    }
    if (!argv || !argv[1] || (playtime && !argv[2]))
        return;

    pthread_mutex_lock(&g_mu);
    ++g_ls_events;
    if (track) {
        on_track(*reinterpret_cast<const uint32_t *>(argv[1]));
    } else if (playtime) {
        on_playtime(*reinterpret_cast<const int32_t *>(argv[1]), *reinterpret_cast<const int32_t *>(argv[2]));
    } else {
        vlog("play state %d", *reinterpret_cast<const int32_t *>(argv[1]));
        g_prompt = true;
    }
    pthread_mutex_unlock(&g_mu);
}

static void spy_slot(QObject *receiver, int method_index, void **argv)
{
    ++g_nslots;
    ClassInfo *ci = class_of(receiver);
    if (ci == UNINTERESTING || ci->kind == K_OTHER_PLAYER)
        return;
    if (ci->kind == K_LS_VM)
        g_vm_raw = receiver;
    if (!g_verbose || ci->logged >= 200)
        return;
    QMetaMethod m = receiver->metaObject()->method(method_index);
    QByteArray sig = m.methodSignature();
    if (sig.startsWith("OnNotifyPlaytime") || sig.startsWith("updatedProperty"))
        return;
    char args[64];
    format_args(args, sizeof args, m, argv);
    ++ci->logged;
    rlog("%s: slot %s [%s]", ci->name, sig.constData(), args);
}

/* ---------- main-thread timer: the only place that calls into the app ---------- */

static QPointer<QObject> *g_player, *g_vm;
static QObject *g_player_seen, *g_vm_seen;
static unsigned g_ticks;
static int64_t g_last_tick_ms, g_last_beat_ms;

static bool seek_player(QObject *player, int32_t ms)
{
    int origin = 0;                     /* MediaOrigin: 0 = from the start of the track */
    if (player->thread() != QThread::currentThread()) {
        rlog("the Audiobooks player lives in another thread, cannot call it");
        return false;
    }
    return QMetaObject::invokeMethod(player, "ReceiveSeek", Qt::DirectConnection,
                                     QGenericArgument("MediaOrigin", &origin), QGenericArgument("int32_t", &ms));
}

/* what the scrub bar does: pressed, then released at a position */
static bool seek_screen(QObject *vm, int32_t ms)
{
    int t = ms;
    if (vm->thread() != QThread::currentThread())
        return false;
    QMetaObject::invokeMethod(vm, "OnScrubBarPressed", Qt::DirectConnection);
    return QMetaObject::invokeMethod(vm, "OnScrubBarReleased", Qt::DirectConnection, QGenericArgument("int", &t));
}

static void tick()
{
    int64_t now = now_ms();
    bool act = false, second = false;
    int32_t target = 0;

    ++g_ticks;
    g_last_tick_ms = now;

    QObject *raw = g_player_raw;
    if (raw != g_player_seen) {
        *g_player = raw;
        g_player_seen = raw;
    }
    raw = g_vm_raw;
    if (raw != g_vm_seen) {
        *g_vm = raw;
        g_vm_seen = raw;
    }

    pthread_mutex_lock(&g_mu);
    if (r_state == RS_REQUESTED) {
        act = true;
    } else if (r_state == RS_ISSUED && now - r_issued_ms > SEEK_CONFIRM_MS) {
        if (r_attempts < 2) {
            act = second = true;
        } else {
            rlog("the seek did not take effect, giving up for this track (stored position kept)");
            r_state = RS_NONE;
            c_frozen = true;
        }
    }
    target = r_target;
    pthread_mutex_unlock(&g_mu);

    if (act) {
        /* g_mu is not held here: the call below makes the app emit signals, which come
           back into spy_signal. */
        QObject *player = g_player->data();
        QObject *vm = g_vm->data();
        const char *how = "nothing to call";
        bool ok = false;
        if (second && vm) {
            how = "the player screen (OnScrubBarReleased)";
            ok = seek_screen(vm, target);
        } else if (player) {
            how = "the player (ReceiveSeek)";
            ok = seek_player(player, target);
        }
        rlog("seek to %d ms through %s: %s", target, how, ok ? "call made" : "call refused");
        pthread_mutex_lock(&g_mu);
        if (r_state == RS_REQUESTED || r_state == RS_ISSUED) {
            r_state = RS_ISSUED;
            r_issued_ms = now;
            ++r_attempts;
        }
        pthread_mutex_unlock(&g_mu);
    }

    if (g_verbose && now - g_last_beat_ms >= 120000) {
        g_last_beat_ms = now;
        rlog("alive: %u signals and %u slot calls seen, %u from the Audiobooks player, %d positions stored",
             g_nsignals, g_nslots, g_ls_events, g_n);
    }
}

class Ticker : public QObject
{
protected:
    bool event(QEvent *e)
    {
        if (e->type() == QEvent::User) {
            startTimer(TICK_MS);
            vlog("timer started on the app's main thread");
            return true;
        }
        return QObject::event(e);
    }
    void timerEvent(QTimerEvent *) { tick(); }
};

/* ---------- worker thread ---------- */

static void *worker(void *)
{
    /* The app object exists long before this module is loaded, but do not assume it. */
    while (!QCoreApplication::instance())
        usleep(200 * 1000);
    QCoreApplication *app = QCoreApplication::instance();
    Ticker *t = new Ticker;
    t->moveToThread(app->thread());
    QCoreApplication::postEvent(t, new QEvent(QEvent::User));

    for (;;) {
        sleep(2);
        save_positions();
        flush_log();
    }
    return 0;
}

static int phdr_cb(struct dl_phdr_info *info, size_t, void *)
{
    uintptr_t lo = ~(uintptr_t)0, hi = 0;
    for (int i = 0; i < info->dlpi_phnum; ++i) {
        const ElfW(Phdr) *ph = &info->dlpi_phdr[i];
        if (ph->p_type != PT_LOAD)
            continue;
        uintptr_t a = info->dlpi_addr + ph->p_vaddr;
        if (a < lo)
            lo = a;
        if (a + ph->p_memsz > hi)
            hi = a + ph->p_memsz;
    }
    g_app_lo = (const void *)lo;
    g_app_hi = (const void *)hi;
    return 1;                           /* the first object is the program itself */
}

/* ---------- entry points for the loader ---------- */

extern "C" __attribute__((visibility("default"))) int abr_start(const char *dir)
{
    static bool started;
    pthread_t t;
    pthread_attr_t attr;

    if (started)
        return 0;
    if (!dir || strlen(dir) >= sizeof g_dir)
        return 1;
    strcpy(g_dir, dir);
    dl_iterate_phdr(phdr_cb, 0);
    if (!g_app_hi)
        return 2;

    char vp[260];
    snprintf(vp, sizeof vp, "%s/verbose", g_dir);
    struct stat vst;
    g_verbose = stat(vp, &vst) == 0;
    load_positions();
    g_last_beat_ms = now_ms();
    g_player = new QPointer<QObject>();
    g_vm = new QPointer<QObject>();
    rlog("module version " ABR_VERSION " started, %d stored positions, Qt %s%s", g_n, qVersion(),
         g_verbose ? ", verbose log (remove the file 'verbose' to turn it off)" : "");

    QSignalSpyCallbackSet set = { spy_signal, spy_slot, 0, 0 };
    qt_register_signal_spy_callbacks(set);

    if (pthread_attr_init(&attr) != 0)
        return 3;
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    int rc = pthread_create(&t, &attr, worker, 0);
    pthread_attr_destroy(&attr);
    if (rc != 0)
        return 4;
    started = true;
    return 0;
}

/* 1 when the main-thread timer has run within the last five seconds */
extern "C" __attribute__((visibility("default"))) int abr_healthy(void)
{
    return g_ticks > 0 && now_ms() - g_last_tick_ms < 5000;
}
