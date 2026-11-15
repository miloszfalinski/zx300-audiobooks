/* What does the Sony NW-ZX300 read from this file?
 *
 * Runs the metadata parser of the player's own media scanner (inside libMediaStoreService.so
 * of the stock 2.02 firmware) on MP4-family files (.m4a, .mp4, .m4b content) and .mp3 files and prints what
 * it returns: the same create -> querySize -> fetch calls the scanner makes. The library is
 * loaded from the firmware's files and run under qemu-user; see check.sh.
 *
 * The functions are not exported, so they are called by their file offsets in the stock
 * library. This reproduces the parser only, not the crawler around it or the player's
 * storage: "readable here" means the file's contents are not the problem.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdarg.h>
#include <sys/mman.h>
#include <unistd.h>

#define LIB_INIT        0x628f8     /* parser library: memory pool */
#define MP4_INIT        0x7f394     /* MP4Parser_initialize */
#define FACTORY_CREATE  0x62300     /* GmpMetaParserFactory_create(out, ticket, path, format, charset) */
#define FORMAT_MP4      6
#define FORMAT_MP3      2
#define CHARSET         1
enum { M_INIT, M_1, M_2, M_QUERYSIZE, M_FETCH, M_READ, M_6 };   /* the object's method table */

/* one requested item; the list ends with type 0 */
struct item { uint32_t type, r1, r2, present, value, len, r6, r7; };

static const struct { int type; const char *name; } NAMES[] = {
    { 0x02, "title" }, { 0x03, "album" }, { 0x04, "artist" }, { 0x05, "album artist" },
    { 0x06, "genre" }, { 0x08, "composer" }, { 0x0f, "duration" }, { 0x12, "year" },
    { 0x18, "kbps" }, { 0x19, "sample rate" }, { 0x1b, "channels" }, { 0x25, "cover bytes" },
};

#define LOG_FN          0xc6b04     /* the library's log call: (logger, line, file, func, level, fmt, ...) */

/* The firmware writes its error messages to the player's log. Here its log function is
 * replaced by this one, so that the messages can be shown (-v). */
static int show_log;
static void firmware_log(void *logger, int line, const char *file, const char *func, int level, const char *fmt, ...)
{
    va_list ap;
    const char *name = func ? func : "";
    const char *paren = strchr(name, '(');
    const char *start = paren ? paren : name + strlen(name);

    (void)logger; (void)file; (void)level;
    if (!show_log || !fmt) return;
    while (start > name && start[-1] != ' ' && start[-1] != '*') start--;     /* the bare function name */
    printf("   firmware: %.*s:%d: ", (int)((paren ? paren : name + strlen(name)) - start), start, line);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
}

static void hook_log(uintptr_t base)
{
    uint8_t *at = (uint8_t *)(base + LOG_FN);                 /* Thumb code, 4-byte aligned */
    uintptr_t page = (uintptr_t)at & ~(uintptr_t)(sysconf(_SC_PAGESIZE) - 1);
    uint32_t target = (uint32_t)(uintptr_t)firmware_log;

    if (mprotect((void *)page, 2 * sysconf(_SC_PAGESIZE), PROT_READ | PROT_WRITE | PROT_EXEC) != 0) return;
    at[0] = 0xdf; at[1] = 0xf8; at[2] = 0x00; at[3] = 0xf0;   /* ldr.w pc, [pc] */
    memcpy(at + 4, &target, 4);
    __builtin___clear_cache((char *)at, (char *)at + 8);
}

typedef int (*init_t)(void);
typedef int (*create_t)(void **, void *, const char *, int, int);
typedef int (*items_t)(void *, void *, struct item *);

int main(int argc, char **argv)
{
    void *h = dlopen("libMediaStoreService.so", RTLD_NOW | RTLD_GLOBAL);
    struct link_map *lm;
    uintptr_t base;
    int i, k, rc, verbose = getenv("VERBOSE") != NULL, bad = 0;

    if (!h) { printf("cannot load the player's library: %s\n", dlerror()); return 2; }
    dlinfo(h, RTLD_DI_LINKMAP, &lm);
    base = lm->l_addr;
    setvbuf(stdout, NULL, _IONBF, 0);
    hook_log(base);
    show_log = verbose;
    if (((init_t)(base + LIB_INIT + 1))() || ((init_t)(base + MP4_INIT + 1))()) { printf("parser start-up failed\n"); return 2; }

    for (i = 1; i < argc; i++) {
        void *p = NULL;
        struct item q[0x40], f[0x40];
        uint16_t *text[0x40];
        uint32_t *m, dur = 0;
        int n = 0, nf = 0, t, title = 0;
        const char *ext = strrchr(argv[i], '.');
        int format = getenv("FORMAT") ? atoi(getenv("FORMAT")) : ext && !strcasecmp(ext, ".mp3") ? FORMAT_MP3 : FORMAT_MP4;
        FILE *probe = fopen(argv[i], "rb");

        printf("%s\n", strrchr(argv[i], '/') ? strrchr(argv[i], '/') + 1 : argv[i]);
        if (!probe) { printf("   cannot open the file here (is its folder visible to the container?)\n"); bad = 1; continue; }
        fclose(probe);
        rc = ((create_t)(base + FACTORY_CREATE + 1))(&p, NULL, argv[i], format, CHARSET);
        if (rc || !p) { printf("   NOT READABLE: the parser refused the file (create -> %#x)\n", rc); bad = 1; continue; }
        m = (uint32_t *)p;
        memset(q, 0, sizeof q);
        for (t = 2; t <= 0x38; t++) q[n++].type = t;
        rc = ((items_t)m[M_QUERYSIZE])(p, NULL, q);
        if (rc) { printf("   NOT READABLE: querySize -> %#x\n", rc); bad = 1; continue; }
        memset(f, 0, sizeof f);
        for (k = 0; k < n; k++) {
            if (!q[k].present) continue;
            f[nf].type = q[k].type;
            text[nf] = NULL;
            if (q[k].len) {                       /* text: hand over a buffer of that many UTF-16 units */
                text[nf] = calloc(q[k].len + 8, 2);
                f[nf].value = (uint32_t)(uintptr_t)text[nf];
                f[nf].len = q[k].len;
            }
            nf++;
        }
        rc = ((items_t)m[M_FETCH])(p, NULL, f);
        if (rc) { printf("   NOT READABLE: fetch -> %#x\n", rc); bad = 1; continue; }
        for (k = 0; k < nf; k++) {
            const char *name = NULL;
            unsigned j;

            for (j = 0; j < sizeof NAMES / sizeof NAMES[0]; j++) if (NAMES[j].type == (int)f[k].type) name = NAMES[j].name;
            if (!name && !verbose) continue;
            if (name) printf("   %-13s", name); else printf("   item %#04x    ", f[k].type);
            if (f[k].type == 0x25) printf("%u", f[k].len);
            else if (text[k]) {
                for (j = 0; j < 200 && text[k][j]; j++) putchar(text[k][j] >= 32 && text[k][j] < 127 ? text[k][j] : '?');
                if (f[k].type == 0x02 && text[k][0]) title = 1;
            } else if (f[k].type == 0x0f) {
                dur = f[k].value;
                printf("%u:%02u:%02u (%u ms)", dur / 3600000, dur / 60000 % 60, dur / 1000 % 60, dur);
            } else printf("%u", f[k].value);
            printf("\n");
        }
        if (title && dur) printf("   READABLE: the parser returns a title and a playing time\n");
        else { printf("   PROBLEM: %s%s\n", title ? "" : "no title ", dur ? "" : "no playing time"); bad = 1; }
    }
    return bad;
}
