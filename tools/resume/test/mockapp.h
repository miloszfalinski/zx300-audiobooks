// Test stand-in for the player app: classes with the same names, signals and slot as the
// ones the resume module looks for (decoded from HgrmMediaPlayerApp with qmeta.py).
#pragma once
#include <QObject>
#include <cstdint>

typedef quint32 ContentsDBEntryId;
enum MediaOrigin { kOriginBegin = 0, kOriginCurrent = 1 };
enum PlayState { kStopped = 0, kPlaying = 1, kPaused = 2 };

namespace dmpapp {

class AudioSourceBase : public QObject
{
    Q_OBJECT
signals:
    void reqPrepareUmount();
    void resFinalize(bool res);
    void notifyInactivated();
    void notifyTrackChanged(ContentsDBEntryId entry_id);
    void notifyPlaytime(int32_t playtime_msec, int32_t duration_msec);
    void notifyPlayState(PlayState play_state);
};

class PlayerBase : public AudioSourceBase
{
    Q_OBJECT
public:
    int32_t pos = 0, dur = 0;
    int seeks = 0;
    int32_t last_seek = -1;
signals:
    void notifyPlayerActiveStatusChanged();
    void notifyReady();
public slots:
    virtual void ReceiveSeek(MediaOrigin origin, int32_t offset_msec);
};

class StandardPlayer : public PlayerBase
{
    Q_OBJECT
signals:
    void notifySettingsChanged(int item_id);
public slots:
    void ReceiveSeek(MediaOrigin origin, int32_t offset_msec) override;
};

class LanguageStudyPlayer : public StandardPlayer
{
    Q_OBJECT
signals:
    void playSpeedChanged(int32_t play_speed);
};

} // namespace dmpapp

// runs the scenario: one step after another, each after its own delay
class Driver : public QObject
{
    Q_OBJECT
public slots:
    void next();
    void run();
};
