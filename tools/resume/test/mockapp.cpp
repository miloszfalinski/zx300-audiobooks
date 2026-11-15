// Mock of the player app for testing the loader and the resume module off the player.
// Usage: HgrmMediaPlayerApp <scenario>   (scenario: first | second | idle)
// Builds against Qt 5.7 (Linux test) and against Qt 5.3.2 (ARM build run under emulation
// with the player's own libraries).
#include "mockapp.h"
#include <QCoreApplication>
#include <QTimer>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <functional>
#include <vector>

namespace screenshot { void screenshot(); }

namespace dmpapp {
void PlayerBase::ReceiveSeek(MediaOrigin origin, int32_t offset_msec)
{
    std::printf("MOCK: ReceiveSeek(origin %d, %d ms) on %s\n", (int)origin, offset_msec, metaObject()->className());
    ++seeks;
    last_seek = offset_msec;
    if (origin == kOriginBegin)
        pos = offset_msec;
}
void StandardPlayer::ReceiveSeek(MediaOrigin origin, int32_t offset_msec) { PlayerBase::ReceiveSeek(origin, offset_msec); }
}

using dmpapp::LanguageStudyPlayer;
using dmpapp::StandardPlayer;

struct Step { int wait_ms; std::function<void()> run; };

static std::vector<Step> steps;
static size_t step_no;
static int bad;
static const char *scenario = "first";
static LanguageStudyPlayer *ls;
static StandardPlayer *music;

void Driver::next()
{
    if (step_no == steps.size()) {
        if (music->seeks) {
            std::printf("MOCK: FAIL the music player was sought\n");
            ++bad;
        }
        std::printf("MOCK: scenario %s done, %d seeks, %s\n", scenario, ls->seeks, bad ? "FAILED" : "OK");
        QCoreApplication::exit(bad ? 1 : 0);
        return;
    }
    QTimer::singleShot(steps[step_no].wait_ms, this, SLOT(run()));
}

void Driver::run()
{
    steps[step_no++].run();
    next();
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (argc > 1)
        scenario = argv[1];

#ifdef MOCK_RESOLVE_ONLY
    // Sony's real function grabs the screen; here it is enough that the symbol resolves,
    // and to see which library it resolved to.
    Dl_info info;
    void (*fp)() = &screenshot::screenshot;
    if (dladdr(reinterpret_cast<void *>(fp), &info) && info.dli_fname)
        std::printf("MOCK: screenshot::screenshot() resolved to %s\n", info.dli_fname);
#else
    screenshot::screenshot();
#endif

    ls = new LanguageStudyPlayer;
    music = new StandardPlayer;
    std::vector<int32_t> expected;      // seek targets the module is expected to make, in order

    // play the current Audiobooks track for n reports, one second of track per report
    auto play = [&](int n) {
        for (int i = 0; i < n; ++i)
            steps.push_back({40, [] { emit ls->notifyPlaytime(ls->pos, ls->dur); ls->pos += 1000; }});
    };
    auto track = [&](quint32 id, int32_t dur, int32_t start) {
        steps.push_back({300, [=] { ls->pos = start; ls->dur = dur; emit ls->notifyTrackChanged(id); emit ls->notifyPlayState(kPlaying); }});
    };
    auto expect_seek = [&](int32_t target) {
        expected.push_back(target);
        int n = (int)expected.size();
        steps.push_back({0, [=] {
            if (ls->seeks != n || ls->last_seek != target) {
                std::printf("MOCK: FAIL expected seek #%d to %d, have %d seeks, last %d\n", n, target, ls->seeks, ls->last_seek);
                ++bad;
            }
        }});
    };
    auto expect_no_new_seek = [&] {
        int n = (int)expected.size();
        steps.push_back({0, [=] {
            if (ls->seeks != n) { std::printf("MOCK: FAIL unexpected seek to %d\n", ls->last_seek); ++bad; }
        }});
    };
    auto music_noise = [&] {
        steps.push_back({40, [] { emit music->notifyTrackChanged(7); emit music->notifyPlaytime(1000, 200000); emit music->notifyPlaytime(90000, 200000); }});
    };
    auto pause = [&](int ms) { steps.push_back({ms, [] {}}); };

    pause(1500);                                        // let the module attach
    if (!std::strcmp(scenario, "first")) {
        track(100, 600000, 0); play(66); expect_no_new_seek();          // 100 left at 65 s
        music_noise();
        track(200, 300000, 0); play(21); expect_no_new_seek();          // 200 left at 20 s
        track(100, 600000, 0); play(15); expect_seek(65000);            // back to 100: resumes
        music_noise();
        track(300, 30000, 0); play(31); expect_no_new_seek();           // 300 played to its end
        track(400, 100000, 0); play(9); expect_no_new_seek();           // 400 left at 8 s
        steps.push_back({40, [] { emit ls->notifyPlayState(kPaused); }});
        pause(2500);                                                    // time for the save
    } else if (!std::strcmp(scenario, "second")) {                      // a later run: "after a reboot"
        track(200, 300000, 0); play(15); expect_seek(20000);
        track(400, 100000, 0); play(15); expect_seek(8000);
        track(300, 30000, 0); play(10); expect_no_new_seek();           // finished earlier: from the start
        track(100, 600000, 50000); play(5); expect_no_new_seek();       // the app resumed it itself
        track(200, 999000, 0); play(10); expect_no_new_seek();          // same id, other length
        music_noise();
        pause(2500);
    } else if (!std::strcmp(scenario, "early")) {                       // reports of the next track before its track change
        track(600, 500000, 0); play(41);                                // 600 left at 40 s
        steps.push_back({40, [] { ls->pos = 0; emit ls->notifyPlaytime(0, 500000); emit ls->notifyPlaytime(1000, 500000); }});
        track(601, 500000, 2000); play(8);                              // 601 has the same length
        steps.push_back({40, [] { emit ls->notifyPlayState(kPaused); }});
        pause(3000);
    } else if (!std::strcmp(scenario, "renumber")) {                    // the database was rebuilt: new ids
        track(900, 300000, 0); play(15); expect_seek(20000);            // was entry 200
        track(901, 123456, 0); play(10); expect_no_new_seek();          // nothing stored with this length
        steps.push_back({40, [] { emit ls->notifyPlayState(kPaused); }});
        pause(3000);
    } else if (!std::strcmp(scenario, "umount")) {                      // USB connection announced
        track(500, 400000, 0); play(31);
        steps.push_back({40, [] { emit music->reqPrepareUmount(); }});
        track(501, 400000, 0); play(41);                                // must not reach the file
        pause(3000);
    } else {
        pause(4000);
    }

    Driver driver;
    driver.next();
    return app.exec();
}
