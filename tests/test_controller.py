"""Drives the real controller with synthetic camera frames (no camera, no mic)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ceremony.config import Settings, Store
from ceremony.controller import CeremonyController
from ceremony.engine.state import Phase
from ceremony.vision.hands import HandsFrame
from tests.synthetic import pair

FPS = 30


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Rig:
    def __init__(self, tmp_path, **clap):
        s = Settings()
        s.countdown.seconds = 3
        s.countdown.final_hold_ms = 300
        s.countdown.sound_enabled = False
        for k, v in clap.items():
            setattr(s.clap, k, v)
        self.t = 1000.0
        self.c = CeremonyController(Store(tmp_path), s, start_devices=False)
        self.c.timer.stop()
        self.c.clock = lambda: self.t
        self.c.fusion.audio_available = s.clap.fusion_mode != "camera"
        self.log = []
        self.c.clap_logged.connect(self.log.append)

    def frames(self, target_seq):
        for target in target_seq:
            self.c.on_frame(HandsFrame(self.t, list(target), list(target), 1280, 720))
            self.t += 1 / FPS
            self.c._tick()

    def hold(self, target, seconds):
        self.frames([target] * int(seconds * FPS))

    def clap_cycle(self):
        gaps = [0.45, 0.3, 0.15, 0.04, 0.02, 0.06, 0.2, 0.35, 0.45]
        self.frames([pair(g) for g in gaps])

    @property
    def phase(self):
        return self.c.engine.phase


def test_full_ceremony_from_gestures(app, tmp_path):
    r = Rig(tmp_path, fusion_mode="camera")
    r.hold(pair(0.45), 0.4)
    assert r.phase == Phase.IDLE  # not held long enough yet
    r.hold(pair(0.45), 0.6)
    assert r.phase == Phase.LISTENING

    r.clap_cycle()
    assert r.c.engine.clap_count == 1
    r.clap_cycle()
    assert r.phase == Phase.COUNTDOWN

    r.hold([], 3.5)
    # No video configured → straight to the closing screen.
    assert r.phase == Phase.FINISHED

    r.hold(pair(0.45, "fist"), 2.2)
    assert r.phase == Phase.IDLE


def test_fist_between_claps_does_not_reset(app, tmp_path):
    r = Rig(tmp_path, fusion_mode="camera")
    r.c.simulate_hi_five()
    r.clap_cycle()
    # Hands briefly curl into fists right after a clap.
    r.hold(pair(0.3, "fist"), 0.5)
    assert r.phase == Phase.LISTENING


def test_strict_mode_needs_sound(app, tmp_path):
    r = Rig(tmp_path, fusion_mode="strict", audio_offset_ms=0)
    r.c.simulate_hi_five()
    r.clap_cycle()
    r.hold(pair(0.45), 0.3)
    assert r.c.engine.clap_count == 0
    assert r.log and not r.log[-1].accepted

    # Same clap with a matching sound is counted.
    before = len(r.log)
    gaps = [0.45, 0.3, 0.15, 0.04]
    r.frames([pair(g) for g in gaps[:-1]])
    r.c._on_audio_onset(r.t)
    r.frames([pair(gaps[-1])])
    r.hold(pair(0.45), 0.3)
    assert r.c.engine.clap_count == 1
    assert r.log[before].accepted and r.log[before].audio


def test_crowd_noise_alone_never_counts(app, tmp_path):
    r = Rig(tmp_path, fusion_mode="strict")
    r.c.simulate_hi_five()
    for _ in range(20):
        r.c._on_audio_onset(r.t)
        r.hold(pair(0.45), 0.2)
    assert r.c.engine.clap_count == 0
    assert r.phase == Phase.LISTENING


def test_operator_overrides(app, tmp_path):
    r = Rig(tmp_path)
    r.c.advance()
    assert r.phase == Phase.LISTENING
    r.c.advance()
    assert r.phase == Phase.COUNTDOWN
    r.c.reset()
    assert r.phase == Phase.IDLE


def test_apply_settings_persists(app, tmp_path):
    r = Rig(tmp_path)
    new = r.c.settings.copy()
    new.text.title = "PT Contoh"
    new.clap.required_count = 3
    r.c.apply_settings(new)
    assert Store(tmp_path).load().text.title == "PT Contoh"
    assert r.c.engine.required_claps == 3
    # Saving settings must not switch on hardware when devices are disabled (--no-camera).
    assert r.c.worker is None and not r.c.mic.ok
    r.c.shutdown()


def test_uploaded_but_never_selected_video_still_plays(app, tmp_path):
    # Reproduces the reported bug: a video was uploaded, but active_video was never saved.
    r = Rig(tmp_path)
    (r.c.store.videos_dir / "opening.mov").write_bytes(b"x")
    assert r.c.settings.video.active_video == ""
    path, auto = r.c.active_video()
    assert path.name == "opening.mov" and auto
    r.c.advance()
    r.c.advance()
    r.hold([], 3.5)
    assert r.phase == Phase.VIDEO  # not skipped to the closing screen


def test_explicit_choice_beats_newest_upload(app, tmp_path):
    import os
    import time

    r = Rig(tmp_path)
    chosen = r.c.store.videos_dir / "chosen.mp4"
    newer = r.c.store.videos_dir / "newer.mp4"
    chosen.write_bytes(b"x")
    newer.write_bytes(b"x")
    os.utime(chosen, (time.time() - 100, time.time() - 100))
    r.c.set_active_video("chosen.mp4")
    assert r.c.active_video() == (chosen, False)
    assert Store(tmp_path).load().video.active_video == "chosen.mp4"  # saved immediately
    chosen.unlink()
    assert r.c.active_video() == (newer, True)  # chosen file gone → newest upload


def test_no_videos_means_closing_screen(app, tmp_path):
    r = Rig(tmp_path)
    assert r.c.active_video() == (None, False)
    assert not r.c.has_video()


def test_relaxed_curled_hands_after_claps_do_not_reset(app, tmp_path):
    # Reported: after clapping 2x the ceremony went back to "raise your hands".
    from tests.synthetic import hanging

    r = Rig(tmp_path, fusion_mode="camera")
    r.c.settings.gesture.reset_in_countdown = True  # even when the operator enables it
    r.c.settings.countdown.seconds = 10
    r.c.simulate_hi_five()
    r.clap_cycle()
    r.clap_cycle()
    assert r.phase == Phase.COUNTDOWN
    r.hold([hanging(h) for h in pair(0.6, "fist")], 3.0)
    assert r.phase == Phase.COUNTDOWN


def test_raised_fist_still_resets(app, tmp_path):
    r = Rig(tmp_path)
    r.c.advance()
    r.c.advance()
    r.hold([], 3.5)
    assert r.phase == Phase.FINISHED
    r.hold(pair(0.6, "fist"), 2.2)
    assert r.phase == Phase.IDLE


def test_countdown_is_protected_from_fist_reset_by_default(app, tmp_path):
    r = Rig(tmp_path)
    r.c.settings.countdown.seconds = 10
    r.c.advance()
    r.c.advance()
    r.hold(pair(0.6, "fist"), 3.0)
    assert r.phase == Phase.COUNTDOWN
