"""Wires camera, microphone, detectors and the state machine together (main thread)."""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from .audio.mic import Microphone
from .config import Settings, Store
from .engine.fusion import ClapDecision, ClapFusion, OffsetCalibrator
from .engine.state import CeremonyEngine, Event, Phase
from .sounds import SoundBank
from .vision.camera import TrackerConfig, VisionWorker
from .vision.clap import ClapDetector
from .vision.classify import hand_shape, is_raised, is_raised_fist
from .vision.gestures import HoldDetector
from .vision.hands import HandsFrame, palm_distance_ratio

TICK_MS = 30
log = logging.getLogger("ceremony")


@dataclass
class ClapLogEntry:
    t: float
    accepted: bool
    strong: bool
    audio: bool
    reason: str
    counted: bool  # accepted AND the engine was listening
    simulated: bool = False


def tracker_config(s: Settings) -> TrackerConfig:
    d, g = s.device, s.gesture
    return TrackerConfig(
        camera_index=d.camera_index,
        width=d.camera_width,
        height=d.camera_height,
        fps=d.camera_fps,
        max_hands=g.max_hands,
        min_detection_confidence=g.min_detection_confidence,
        min_presence_confidence=g.min_presence_confidence,
        min_tracking_confidence=g.min_tracking_confidence,
        mirror_preview=d.mirror_preview,
    )


class CeremonyController(QObject):
    phase_changed = Signal(object)  # Phase
    engine_event = Signal(object)  # Event
    clap_logged = Signal(object)  # ClapLogEntry
    updated = Signal()  # periodic, for live indicators
    preview = Signal(QImage)
    camera_status = Signal(bool, str)
    mic_status = Signal(bool, str)
    settings_changed = Signal()
    calibration_finished = Signal(object)  # int | None (ms)
    message = Signal(str)

    def __init__(self, store: Store, settings: Settings, *, start_devices: bool = True):
        super().__init__()
        self.store = store
        self.settings = settings
        # perf_counter, not monotonic: on Windows (Python 3.12) monotonic only ticks every ~15.6 ms.
        # Camera frames and mic onsets are stamped with the same clock.
        self.clock = time.perf_counter  # replaceable in tests
        self.engine = CeremonyEngine(settings, has_video=self.has_video)
        self.engine.listeners.append(self._on_engine_event)
        self.sounds = SoundBank(store.sounds_dir)

        self.clap = ClapDetector()
        self.fusion = ClapFusion()
        self.hi_five_hold = HoldDetector(settings.gesture.hi_five_hold_ms)
        self.reset_hold = HoldDetector(settings.gesture.reset_hold_ms)
        self.calibrator: OffsetCalibrator | None = None
        self._configure_detectors()

        # Live diagnostics for the operator console.
        self.ratio_history: deque[tuple[float, float | None]] = deque()
        self.audio_onsets: deque[float] = deque()
        self.clap_marks: deque[tuple[float, bool]] = deque()
        self.hands_visible = 0
        self.target_count = 0
        self.target_shapes: list[str] = []
        self.camera_fps = 0.0
        self.camera_ok = False
        self.mic_level = -120.0
        self.last_frame_t = 0.0

        self.worker: VisionWorker | None = None
        self.mic = Microphone(self)
        self.mic.onset.connect(self._on_audio_onset)
        self.mic.level.connect(self._on_mic_level)
        self.mic.status.connect(self._on_mic_status)

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.devices_enabled = start_devices  # False with --no-camera: never touch camera or mic
        if start_devices:
            self.start_camera()
            self.start_mic()

    # --- devices --------------------------------------------------------------

    def start_camera(self) -> None:
        self.stop_camera()
        self.worker = VisionWorker(tracker_config(self.settings))
        self.worker.roi = self._roi()
        self.worker.frame_ready.connect(self.on_frame)
        self.worker.preview_ready.connect(self.preview)
        self.worker.status.connect(self._on_camera_status)
        self.worker.fps_changed.connect(self._on_fps)
        self.worker.start()

    def stop_camera(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.camera_ok = False

    def start_mic(self) -> None:
        c = self.settings.clap
        if c.fusion_mode == "camera":
            self.mic.stop()
            self.fusion.audio_available = False
            self.mic_status.emit(True, "Mic tidak dipakai (mode Kamera saja)")
            return
        self.mic.start(c.mic_device, c.mic_sensitivity)

    def shutdown(self) -> None:
        self.timer.stop()
        self.stop_camera()
        self.mic.stop()

    def _on_camera_status(self, ok: bool, text: str) -> None:
        if (ok, text) != getattr(self, "_last_camera_status", None):
            self._last_camera_status = (ok, text)
            (log.info if ok else log.warning)("kamera: %s", text)
        self.camera_ok = ok
        self.camera_status.emit(ok, text)

    def _on_mic_status(self, ok: bool, text: str) -> None:
        self.fusion.audio_available = ok
        if not ok and self.settings.clap.fusion_mode != "camera":
            text += " — otomatis memakai mode Kamera saja"
        (log.info if ok else log.warning)("mic: %s", text)
        self.mic_status.emit(ok, text)

    def log_startup(self) -> None:
        s = self.settings
        path, auto = self.active_video()
        video = f"{path.name}{' (otomatis: unggahan terbaru)' if auto else ''}" if path else "TIDAK ADA"
        log.info("data: %s", self.store.data_dir)
        log.info("video setelah countdown: %s · setelah video: %s", video, s.video.after_video)
        log.info("clap: %d× · mode %s · kontak %.2f / lepas %.2f · timeout %ds",
                 s.clap.required_count, s.clap.fusion_mode, s.clap.contact_ratio, s.clap.release_ratio,
                 s.gesture.listening_timeout_s)  # fmt: skip
        g = s.gesture
        phases = [n for n, on in (("listening", g.reset_in_listening), ("countdown", g.reset_in_countdown),
                                  ("video", g.reset_in_video), ("selesai", g.reset_in_finished)) if on]  # fmt: skip
        log.info("reset batu: %d tangan, tahan %d ms, aktif di: %s", g.reset_hands_required, g.reset_hold_ms,
                 ", ".join(phases) or "-")  # fmt: skip

    def _on_fps(self, fps: float) -> None:
        self.camera_fps = fps

    def _on_mic_level(self, db: float) -> None:
        self.mic_level = db

    # --- settings -------------------------------------------------------------

    def _roi(self) -> tuple[float, float, float, float]:
        g = self.settings.gesture
        return (g.roi_x, g.roi_y, g.roi_w, g.roi_h)

    def _configure_detectors(self) -> None:
        s = self.settings
        self.clap.contact_ratio = s.clap.contact_ratio
        self.clap.release_ratio = max(s.clap.release_ratio, s.clap.contact_ratio + 0.1)
        self.clap.min_interval_ms = s.clap.min_interval_ms
        self.clap.detect_on_tracking_loss = s.clap.detect_on_tracking_loss
        self.fusion.mode = s.clap.fusion_mode
        self.fusion.window = s.clap.audio_window_ms / 1000
        self.fusion.offset = s.clap.audio_offset_ms / 1000
        self.hi_five_hold.hold_ms = s.gesture.hi_five_hold_ms
        self.reset_hold.hold_ms = s.gesture.reset_hold_ms
        self.sounds.set_volume(s.countdown.effects_volume)

    def apply_settings(self, new: Settings) -> None:
        old = self.settings
        self.settings = new
        self.engine.settings = new
        self.store.save(new)
        self._configure_detectors()
        if not self.devices_enabled:
            self.settings_changed.emit()
            return
        if tracker_config(old) != tracker_config(new) or self.worker is None:
            self.start_camera()
        elif self.worker is not None:
            self.worker.roi = self._roi()
        if (old.clap.mic_device, old.clap.fusion_mode == "camera") != (
            new.clap.mic_device,
            new.clap.fusion_mode == "camera",
        ) or not self.mic.ok:
            self.start_mic()
        else:
            self.mic.set_sensitivity(new.clap.mic_sensitivity)
        self.settings_changed.emit()

    def save_settings(self) -> None:
        self.store.save(self.settings)

    def active_video(self) -> tuple[Path | None, bool]:
        """(path, chosen_automatically) of the video that plays after the countdown."""
        return self.store.resolve_video(self.settings.video.active_video)

    def has_video(self) -> bool:
        return self.active_video()[0] is not None

    def set_active_video(self, name: str) -> None:
        """Video library changes apply immediately, like the file copy itself."""
        self.settings.video.active_video = name
        self.save_settings()
        self.settings_changed.emit()

    # --- inputs ---------------------------------------------------------------

    def on_frame(self, frame: HandsFrame) -> None:
        now = frame.t
        self.last_frame_t = now
        self.hands_visible = len(frame.hands)
        target = frame.target
        self.target_count = len(target)
        shapes = [hand_shape(h.world) for h in target]
        self.target_shapes = ["terbuka" if s.is_open else "batu" if s.is_fist else f"{s.fingers} jari" for s in shapes]

        ratio = palm_distance_ratio(target[0], target[1]) if len(target) == 2 else None
        self.ratio_history.append((now, ratio))

        candidate = self.clap.feed(ratio, now)
        if candidate:
            self.fusion.add_visual(candidate)
            if self.calibrator:
                self.calibrator.add_visual(candidate.t)

        g = self.settings.gesture
        phase = self.engine.phase

        hi_five = (
            phase == Phase.IDLE
            and len(shapes) == 2
            and all(s.is_open for s in shapes)
            and (not g.hi_five_require_raised or all(is_raised(h) for h in target))
            and ratio is not None
            and ratio > self.clap.release_ratio
        )
        if self.hi_five_hold.feed(hi_five, now):
            self.engine.hi_five(now, "gesture")

        fists = sum(s.is_fist and is_raised_fist(h) for s, h in zip(shapes, target))
        # A hand half-closed between claps must not be read as the reset gesture.
        clapping = self.clap.hands_close() or now - self.clap.last_clap_t < 0.7
        reset = self.engine.reset_allowed() and fists >= max(1, g.reset_hands_required) and not clapping
        if self.reset_hold.feed(reset, now):
            self.engine.fist(now, "gesture")

    def _on_audio_onset(self, t: float) -> None:
        self.audio_onsets.append(t)
        self.fusion.add_audio(t)
        if self.calibrator:
            self.calibrator.add_audio(t)

    # --- operator -------------------------------------------------------------

    def advance(self) -> None:
        self.engine.advance(self.clock(), "operator")

    def reset(self) -> None:
        self.engine.reset(self.clock(), "operator")

    def simulate_hi_five(self) -> None:
        if not self.engine.hi_five(self.clock(), "simulasi"):
            self.message.emit("Hi-five hanya berlaku saat menunggu (IDLE)")

    def simulate_clap(self) -> None:
        now = self.clock()
        counted = self.engine.clap(now, "simulasi")
        self.clap_logged.emit(ClapLogEntry(now, True, True, False, "simulasi", counted, simulated=True))
        if not counted:
            self.message.emit("Clap hanya dihitung saat mendengarkan (LISTENING)")

    def simulate_fist(self) -> None:
        if not self.engine.fist(self.clock(), "simulasi"):
            self.message.emit("Reset dengan batu tidak aktif di tahap ini (lihat Pengaturan › Gesture)")

    def video_ended(self) -> None:
        self.engine.video_ended(self.clock())

    def start_calibration(self) -> None:
        self.calibrator = OffsetCalibrator()
        self.message.emit("Kalibrasi: tepuk tangan 6x di depan kamera dengan jeda ±1 detik")

    def cancel_calibration(self) -> None:
        self.calibrator = None

    # --- engine & time --------------------------------------------------------

    def _on_engine_event(self, ev: Event) -> None:
        if ev.kind == "phase":
            log.info("FASE → %s (oleh: %s)", ev.phase.value.upper(), ev.source or "-")
        elif ev.kind == "clap":
            log.info("clap dihitung %d/%d (%s)", ev.value, self.engine.required_claps, ev.source)
        elif ev.kind == "clap_reset":
            log.info("hitungan clap direset: jeda antar tepukan > %d ms", self.settings.clap.max_gap_ms)
        elif ev.kind == "reset":
            log.info("RESET (oleh: %s) dari fase %s", ev.source, ev.phase.value)
        elif ev.kind == "tick":
            log.debug("countdown %d", ev.value)
        sounds_on = self.settings.countdown.sound_enabled
        if ev.kind == "phase":
            self.hi_five_hold.reset()
            self.reset_hold.reset()
            if ev.phase == Phase.LISTENING:
                self.fusion.reset()
                if sounds_on:
                    self.sounds.play("ack")
            self.phase_changed.emit(ev.phase)
        elif ev.kind == "clap" and sounds_on:
            self.sounds.play("clap")
        elif ev.kind == "tick" and sounds_on:
            self.sounds.play("final" if ev.value == 0 else "tick")
        self.engine_event.emit(ev)

    def _tick(self) -> None:
        now = self.clock()
        for d in self.fusion.resolve(now):
            self._apply_decision(d)
        if self.calibrator:
            self.calibrator.update(now)
            if self.calibrator.done:
                result = self.calibrator.result_ms()
                self.calibrator = None
                if result is not None:
                    self.settings.clap.audio_offset_ms = int(max(-200, min(400, result)))
                    self.fusion.offset = self.settings.clap.audio_offset_ms / 1000
                    self.save_settings()
                    self.settings_changed.emit()
                self.calibration_finished.emit(result)
        self.engine.tick(now)

        for q in (self.ratio_history, self.audio_onsets, self.clap_marks):
            while q and now - (q[0][0] if isinstance(q[0], tuple) else q[0]) > 5.0:
                q.popleft()
        if self.camera_ok and self.last_frame_t and now - self.last_frame_t > 2.0:
            self.camera_fps = 0.0
        self.updated.emit()

    def _apply_decision(self, d: ClapDecision) -> None:
        counted = d.accepted and self.engine.clap(self.clock(), "gesture")
        log.info("tepukan terdeteksi: %s · kamera %s · suara %s · %s%s",
                 "DITERIMA" if d.accepted else "DITOLAK", "jelas" if d.strong else "ragu",
                 "ya" if d.audio else "tidak", d.reason,
                 "" if counted or not d.accepted else f" · tidak dihitung (fase {self.engine.phase.value})")  # fmt: skip
        self.clap_marks.append((d.t, d.accepted))
        self.clap_logged.emit(ClapLogEntry(d.t, d.accepted, d.strong, d.audio, d.reason, counted))
