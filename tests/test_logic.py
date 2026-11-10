import numpy as np

from ceremony.audio.onset import OnsetDetector
from ceremony.config import Settings
from ceremony.engine.fusion import ClapFusion, OffsetCalibrator
from ceremony.engine.state import CeremonyEngine, Phase
from ceremony.vision.clap import ClapCandidate, ClapDetector
from ceremony.vision.gestures import HoldDetector

DT = 1 / 30


def run_ratios(det: ClapDetector, ratios, t0=0.0):
    out = []
    t = t0
    for r in ratios:
        c = det.feed(r, t)
        if c:
            out.append(c)
        t += DT
    return out, t


# --- clap detector --------------------------------------------------------------


def test_two_claps_counted_once_each():
    det = ClapDetector()
    cycle = [2.0, 1.6, 1.1, 0.6, 0.4, 0.5, 0.9, 1.5, 2.0]
    claps, _ = run_ratios(det, cycle + cycle)
    assert len(claps) == 2
    assert all(c.strong for c in claps)


def test_holding_hands_together_is_one_clap():
    det = ClapDetector()
    claps, _ = run_ratios(det, [2.0, 1.0, 0.5] + [0.5, 0.6, 0.55] * 20)
    assert len(claps) == 1


def test_jitter_near_contact_does_not_double_count():
    det = ClapDetector()
    # bounces between contact and just above contact, never past release
    claps, _ = run_ratios(det, [2.0, 0.6, 0.9, 0.6, 1.1, 0.6, 1.2, 0.5])
    assert len(claps) == 1


def test_no_clap_without_arming():
    det = ClapDetector()
    claps, _ = run_ratios(det, [0.5, 0.6, 0.5])  # hands started together
    assert claps == []


def test_tracking_loss_after_fast_approach_is_weak_clap():
    det = ClapDetector()
    claps, _ = run_ratios(det, [2.0, 1.8, 1.4, 1.0, None, None, 1.6, 2.0])
    assert len(claps) == 1 and not claps[0].strong


def test_tracking_loss_while_still_far_is_ignored():
    det = ClapDetector()
    claps, _ = run_ratios(det, [2.5, 2.4, 2.5, None, None])
    assert claps == []


def test_min_interval():
    det = ClapDetector(min_interval_ms=500)
    claps, _ = run_ratios(det, [2.0, 0.5, 2.0, 0.5])  # second contact only ~67 ms later
    assert len(claps) == 1


# --- hold detector ----------------------------------------------------------------


def test_hold_fires_once_and_survives_short_dropout():
    h = HoldDetector(hold_ms=500, grace_ms=150)
    fired = []
    t = 0.0
    seq = [True] * 10 + [False] * 2 + [True] * 10 + [True] * 30
    for v in seq:
        if h.feed(v, t):
            fired.append(t)
        t += DT
    assert len(fired) == 1
    assert 0.49 <= fired[0] <= 0.6


def test_hold_resets_after_release():
    h = HoldDetector(hold_ms=100, grace_ms=50)
    t, fired = 0.0, 0
    for v in [True] * 6 + [False] * 6 + [True] * 6:
        fired += h.feed(v, t)
        t += DT
    assert fired == 2


# --- fusion -----------------------------------------------------------------------


def decide(mode, strong, audio_t=None, t=10.0):
    f = ClapFusion(mode=mode, window_ms=150, offset_ms=70)
    if audio_t is not None:
        f.add_audio(audio_t)
    f.add_visual(ClapCandidate(t, strong, 0.5))
    first = f.resolve(t)
    if mode != "camera":
        assert first == []  # waits for a possible late sound
    return first + f.resolve(t + 1)


def test_fusion_modes():
    t = 10.0
    sound = t - 0.07
    assert decide("strict", True, sound)[0].accepted
    assert not decide("strict", True, None)[0].accepted
    assert decide("balanced", True, None)[0].accepted
    assert not decide("balanced", False, None)[0].accepted
    assert decide("balanced", False, sound)[0].accepted
    assert decide("camera", False, None)[0].accepted


def test_sound_alone_never_counts():
    f = ClapFusion(mode="strict")
    for i in range(10):
        f.add_audio(i * 0.3)
    assert f.resolve(10.0) == []


def test_one_sound_confirms_only_one_clap():
    f = ClapFusion(mode="strict", window_ms=150, offset_ms=0)
    f.add_audio(5.0)
    f.add_visual(ClapCandidate(5.0, True, 0.5))
    f.add_visual(ClapCandidate(5.1, True, 0.5))
    res = f.resolve(6.0)
    assert [d.accepted for d in res] == [True, False]


def test_unavailable_mic_degrades_to_camera():
    f = ClapFusion(mode="strict")
    f.audio_available = False
    f.add_visual(ClapCandidate(1.0, False, 0.5))
    assert f.resolve(1.0)[0].accepted


def test_calibrator_median():
    c = OffsetCalibrator(needed=3)
    for i, lag in enumerate([0.06, 0.08, 0.30]):
        a = i * 1.0
        c.add_audio(a)
        c.add_visual(a + lag)
        c.update(a + 1.0)
    assert c.done and c.result_ms() == 80


# --- engine -----------------------------------------------------------------------


def make_engine(**clap):
    s = Settings()
    for k, v in clap.items():
        setattr(s.clap, k, v)
    s.countdown.seconds = 3
    s.countdown.final_hold_ms = 500
    events = []
    e = CeremonyEngine(s)
    e.listeners.append(lambda ev: events.append((ev.kind, ev.phase, ev.value)))
    return e, events


def test_full_flow():
    e, events = make_engine()
    assert not e.clap(0.0)  # ignored while idle
    e.hi_five(1.0)
    assert e.phase == Phase.LISTENING
    e.clap(2.0)
    assert e.phase == Phase.LISTENING and e.clap_count == 1
    e.clap(2.5)
    assert e.phase == Phase.COUNTDOWN
    ticks = []
    t = 2.5
    while e.phase == Phase.COUNTDOWN and t < 10:
        t += 0.05
        e.tick(t)
    ticks = [v for k, _, v in events if k == "tick"]
    assert ticks == [3, 2, 1, 0]
    assert e.phase == Phase.VIDEO
    e.video_ended(t + 5)
    assert e.phase == Phase.FINISHED
    assert e.fist(t + 6)
    assert e.phase == Phase.IDLE


def test_clap_gap_resets_count():
    e, _ = make_engine(max_gap_ms=1000)
    e.hi_five(0)
    e.clap(1.0)
    e.tick(2.5)
    assert e.clap_count == 0
    e.clap(3.0)
    assert e.phase == Phase.LISTENING and e.clap_count == 1


def test_fist_ignored_during_video_by_default():
    e, _ = make_engine()
    e.hi_five(0)
    e.advance(0)  # → countdown
    e.advance(0)  # → video
    assert e.phase == Phase.VIDEO
    assert not e.fist(1)
    assert e.phase == Phase.VIDEO


def test_listening_timeout():
    e, _ = make_engine()
    e.settings.gesture.listening_timeout_s = 5
    e.hi_five(0)
    e.tick(4.9)
    assert e.phase == Phase.LISTENING
    e.tick(5.1)
    assert e.phase == Phase.IDLE


def test_no_video_skips_to_finished():
    e, _ = make_engine()
    e.has_video = lambda: False
    e.hi_five(0)
    e.advance(0)
    e.advance(0)
    assert e.phase == Phase.FINISHED


def test_settings_roundtrip_and_tolerance():
    s = Settings()
    s.clap.required_count = 3
    s2 = Settings.from_dict({**s.to_dict(), "unknown": 1, "text": {"title": 5, "bogus": "x"}})
    assert s2.clap.required_count == 3
    assert s2.text.title == "5"


# --- audio onsets -----------------------------------------------------------------


def synth(seconds, sr, claps_at, music=True, seed=0):
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    x = 0.003 * rng.standard_normal(n)
    if music:
        # loud, steady tonal music with a bass line
        x += 0.25 * np.sin(2 * np.pi * 110 * t) + 0.12 * np.sin(2 * np.pi * 440 * t) + 0.05 * np.sin(2 * np.pi * 880 * t)
    for c in claps_at:
        i = int(c * sr)
        length = int(0.03 * sr)
        burst = rng.standard_normal(length) * np.exp(-np.arange(length) / (0.006 * sr))
        x[i : i + length] += 0.5 * burst
    return x.astype(np.float32)


def detect(x, sr, bs=512, sensitivity=0.5):
    d = OnsetDetector(sr, bs, sensitivity)
    hits = []
    for i in range(0, len(x) - bs, bs):
        if d.process(x[i : i + bs], i / sr):
            hits.append(i / sr)
    return hits


def test_onsets_found_over_music():
    sr = 48000
    claps = [1.5, 2.0, 3.2]
    hits = detect(synth(4.0, sr, claps), sr)
    assert len(hits) == 3
    for c, h in zip(claps, hits):
        assert abs(c - h) < 0.03


def test_no_onsets_from_steady_music():
    sr = 48000
    assert detect(synth(4.0, sr, []), sr) == []


# --- hand shapes (synthetic landmarks) ----------------------------------------------

from ceremony.vision.classify import hand_shape, is_raised
from ceremony.vision.hands import palm_distance_ratio, select_pair
from tests.synthetic import make_hand, pair


def test_open_and_fist_shapes():
    open_hand = make_hand(0.5, 0.6, "open")
    fist = make_hand(0.5, 0.6, "fist")
    assert hand_shape(open_hand.world).is_open
    assert hand_shape(fist.world).is_fist
    assert is_raised(open_hand)


def test_pair_selection_prefers_big_hands_inside_roi():
    near = pair(0.4)
    far = make_hand(0.1, 0.3, "open", scale=0.3)
    assert select_pair([far, *near], (0, 0, 1, 1)) == near
    assert select_pair([*near], (0.0, 0.0, 0.5, 1.0)) == near[:1]


def test_palm_distance_ratio_scales_with_gap():
    assert palm_distance_ratio(*pair(0.4)) > 3
    assert palm_distance_ratio(*pair(0.02)) < 0.75
