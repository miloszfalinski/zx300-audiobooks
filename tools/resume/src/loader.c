/*
 * Loader for the Audiobooks resume module on the Sony NW-ZX300.
 *
 * Installed as /system/vendor/sony/lib/libScreenshotShared.so. Sony's own library of that
 * name is installed next to it as libScreenshotOrigin.so and is a dependency of this file,
 * so the player app still finds screenshot::screenshot() there. This file adds nothing to
 * that; its only job is to load libaudiobookresume.so into the player app, carefully:
 *
 *   - only in the process HgrmMediaPlayerApp;
 *   - from a background thread, so the app's start is not delayed;
 *   - not if <dir>/disable exists (kill switch, can be created over USB);
 *   - not if the last GUARD_LIMIT starts were not confirmed healthy (file <dir>/starts);
 *   - with RTLD_NOW, so a missing symbol is a refused load and not a crash later.
 *
 * See docs/resume-add-on.md.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define APP_NAME     "HgrmMediaPlayerApp"
#define DEFAULT_DIR  "/contents/audiobook-resume"
/* either of these exists when the internal storage is mounted */
#define DEFAULT_MARK  "/contents/MUSIC"
#define DEFAULT_MARK2 "/contents/LEARNING"
#define DEFAULT_MOD  "/system/vendor/sony/lib/libaudiobookresume.so"
#define GUARD_LIMIT  2
#define HEALTHY_AFTER_S 20
#define LOG_MAX_BYTES (256 * 1024)

static const char *g_dir = DEFAULT_DIR;

static void path(char *out, size_t n, const char *name) { snprintf(out, n, "%s/%s", g_dir, name); }

static void logline(const char *fmt, ...)
{
    char p[300], old[300], msg[400], stamp[32];
    struct stat st;
    time_t now = time(NULL);
    struct tm tmv;
    va_list ap;
    FILE *f;

    path(p, sizeof p, "log.txt");
    if (stat(p, &st) == 0 && st.st_size > LOG_MAX_BYTES) {
        path(old, sizeof old, "log.old.txt");
        rename(p, old);
    }
    f = fopen(p, "a");
    if (!f)
        return;
    localtime_r(&now, &tmv);
    strftime(stamp, sizeof stamp, "%Y-%m-%d %H:%M:%S", &tmv);
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    fprintf(f, "%s loader: %s\n", stamp, msg);
    fclose(f);
}

static int exists(const char *p)
{
    struct stat st;
    return stat(p, &st) == 0;
}

static int is_dir(const char *p)
{
    struct stat st;
    return stat(p, &st) == 0 && S_ISDIR(st.st_mode);
}

/* the counter in <dir>/starts; 0 when the file is missing or unreadable */
static int read_starts(void)
{
    char p[300];
    int n = 0;
    FILE *f;

    path(p, sizeof p, "starts");
    f = fopen(p, "r");
    if (!f)
        return 0;
    if (fscanf(f, "%d", &n) != 1 || n < 0)
        n = 0;
    fclose(f);
    return n;
}

static int write_starts(int n)
{
    char p[300];
    FILE *f;

    path(p, sizeof p, "starts");
    f = fopen(p, "w");
    if (!f)
        return -1;
    fprintf(f, "%d\n", n);
    return fclose(f);
}

static void *run(void *unused)
{
    const char *mark = getenv("ABR_STORAGE_MARK");
    const char *mod = getenv("ABR_MODULE");
    char p[300];
    int starts;
    void *h;
    int (*start)(const char *);
    int (*healthy)(void);
    int rc, wait_s, waited, reported = 0;

    (void)unused;
    if (!mod)
        mod = DEFAULT_MOD;

    /* The storage is not there while it is exported over USB; wait for it. */
    while (!(mark ? is_dir(mark) : is_dir(DEFAULT_MARK) || is_dir(DEFAULT_MARK2)))
        sleep(3);

    if (mkdir(g_dir, 0777) != 0 && errno != EEXIST)
        return NULL;                    /* nowhere to keep the guard: do nothing */

    path(p, sizeof p, "disable");
    if (exists(p)) {
        logline("the file 'disable' is present, module not loaded");
        return NULL;
    }

    starts = read_starts();
    if (starts >= GUARD_LIMIT) {
        logline("guard: the last %d starts were not confirmed healthy, module not loaded. "
                "Delete the file 'starts' to try again.", starts);
        return NULL;
    }
    if (write_starts(starts + 1) != 0) {
        logline("cannot write the guard file (%s), module not loaded", strerror(errno));
        return NULL;
    }

    h = dlopen(mod, RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        logline("module not loaded: %s", dlerror());
        return NULL;
    }
    start = (int (*)(const char *))dlsym(h, "abr_start");
    healthy = (int (*)(void))dlsym(h, "abr_healthy");
    if (!start || !healthy) {
        logline("module has no abr_start/abr_healthy, not started");
        return NULL;
    }
    rc = start(g_dir);
    logline("module started (rc %d, guard counter %d)", rc, starts + 1);
    if (rc != 0)
        return NULL;

    /* Confirm the start once the module has been healthy for a while. The write can fail
       (the storage may be with the computer over USB just then), so keep trying: a start
       that stayed up must not count against the guard. */
    wait_s = getenv("ABR_HEALTHY_AFTER") ? atoi(getenv("ABR_HEALTHY_AFTER")) : HEALTHY_AFTER_S;
    for (waited = 0; waited < 6 * 3600; waited += 2) {
        sleep(2);
        if (waited + 2 < wait_s)
            continue;
        if (!healthy()) {
            if (!reported) {
                reported = 1;
                logline("module not healthy after %d s, guard counter stays at %d for now", waited + 2, starts + 1);
            }
            continue;
        }
        if (is_dir(g_dir) && write_starts(0) == 0) {
            logline("module healthy after %d s, guard counter reset", waited + 2);
            break;
        }
    }
    return NULL;
}

static int is_player_app(void)
{
    char buf[256];
    const char *base;
    ssize_t n = readlink("/proc/self/exe", buf, sizeof buf - 1);

    if (n <= 0)
        return 0;
    buf[n] = '\0';
    base = strrchr(buf, '/');
    base = base ? base + 1 : buf;
    return strcmp(base, APP_NAME) == 0;
}

__attribute__((constructor)) static void abr_loader_init(void)
{
    pthread_t t;
    pthread_attr_t attr;
    const char *dir;

    if (!is_player_app())
        return;
    dir = getenv("ABR_DIR");
    if (dir)
        g_dir = dir;
    if (pthread_attr_init(&attr) != 0)
        return;
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&t, &attr, run, NULL);
    pthread_attr_destroy(&attr);
}
