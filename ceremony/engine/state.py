"""The ceremony state machine. Pure Python, time is always passed in.

    IDLE ──hi-five──► LISTENING ──N claps──► COUNTDOWN ──► VIDEO ──► FINISHED
      ▲                   │ timeout                                    │
      └───────────────────┴──────────── fist (reset) ◄─────────────────┘

The operator can always advance (Space) or reset (Esc), regardless of gestures.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ..config import Settings


class Phase(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    COUNTDOWN = "countdown"
    VIDEO = "video"
    FINISHED = "finished"


PHASE_LABELS = {
    Phase.IDLE: "Menunggu hi-five",
    Phase.LISTENING: "Mendengarkan tepuk tangan",
    Phase.COUNTDOWN: "Countdown",
    Phase.VIDEO: "Memutar video",
    Phase.FINISHED: "Selesai",
}


@dataclass
class Event:
    kind: str  # "phase" | "clap" | "clap_reset" | "tick" | "reset"
    phase: Phase
    value: int = 0
    source: str = ""


class CeremonyEngine:
    def __init__(self, settings: Settings, has_video: Callable[[], bool] = lambda: True):
        self.settings = settings
        self.has_video = has_video
        self.phase = Phase.IDLE
        self.phase_since = 0.0
        self.clap_count = 0
        self.last_clap_t = 0.0
        self.last_activity = 0.0
        self.last_tick_value: int | None = None
        self.listeners: list[Callable[[Event], None]] = []

    # --- helpers --------------------------------------------------------------

    @property
    def required_claps(self) -> int:
        return max(1, self.settings.clap.required_count)

    def _emit(self, kind: str, value: int = 0, source: str = "") -> None:
        ev = Event(kind, self.phase, value, source)
        for listener in list(self.listeners):
            listener(ev)

    def _enter(self, phase: Phase, now: float, source: str = "") -> None:
        self.phase = phase
        self.phase_since = now
        self.last_activity = now
        if phase in (Phase.IDLE, Phase.LISTENING):
            self.clap_count = 0
        self.last_tick_value = None
        self._emit("phase", source=source)
        if phase == Phase.COUNTDOWN:
            self._tick_countdown(now)

    def reset_allowed(self) -> bool:
        g = self.settings.gesture
        return {
            Phase.IDLE: False,
            Phase.LISTENING: g.reset_in_listening,
            Phase.COUNTDOWN: g.reset_in_countdown,
            Phase.VIDEO: g.reset_in_video,
            Phase.FINISHED: g.reset_in_finished,
        }[self.phase]

    # --- inputs ---------------------------------------------------------------

    def hi_five(self, now: float, source: str = "gesture") -> bool:
        if self.phase != Phase.IDLE:
            return False
        self._enter(Phase.LISTENING, now, source)
        return True

    def clap(self, now: float, source: str = "gesture") -> bool:
        if self.phase != Phase.LISTENING:
            return False
        if self.clap_count and (now - self.last_clap_t) * 1000 > self.settings.clap.max_gap_ms:
            self.clap_count = 0
            self._emit("clap_reset")
        self.clap_count += 1
        self.last_clap_t = now
        self.last_activity = now
        self._emit("clap", self.clap_count, source)
        if self.clap_count >= self.required_claps:
            self._enter(Phase.COUNTDOWN, now, source)
        return True

    def fist(self, now: float, source: str = "gesture") -> bool:
        if not self.reset_allowed():
            return False
        self.reset(now, source)
        return True

    def reset(self, now: float, source: str = "operator") -> None:
        self._emit("reset", source=source)
        self._enter(Phase.IDLE, now, source)

    def advance(self, now: float, source: str = "operator") -> None:
        """Operator override: jump to the next phase."""
        match self.phase:
            case Phase.IDLE:
                self._enter(Phase.LISTENING, now, source)
            case Phase.LISTENING:
                self.clap_count = self.required_claps
                self._enter(Phase.COUNTDOWN, now, source)
            case Phase.COUNTDOWN:
                self._start_video(now, source)
            case Phase.VIDEO:
                self._enter(Phase.FINISHED, now, source)
            case Phase.FINISHED:
                self._enter(Phase.IDLE, now, source)

    def video_ended(self, now: float) -> None:
        if self.phase == Phase.VIDEO:
            self._enter(Phase.FINISHED, now, "video")
            if self.settings.video.after_video == "idle":
                self._enter(Phase.IDLE, now, "video")

    def _start_video(self, now: float, source: str) -> None:
        if self.has_video():
            self._enter(Phase.VIDEO, now, source)
        else:
            self._enter(Phase.FINISHED, now, source)

    # --- time -----------------------------------------------------------------

    def tick(self, now: float) -> None:
        if self.phase == Phase.LISTENING:
            if self.clap_count and (now - self.last_clap_t) * 1000 > self.settings.clap.max_gap_ms:
                self.clap_count = 0
                self.last_activity = now
                self._emit("clap_reset")
            timeout = self.settings.gesture.listening_timeout_s
            if timeout > 0 and now - self.last_activity > timeout:
                self._enter(Phase.IDLE, now, "timeout")
        elif self.phase == Phase.COUNTDOWN:
            self._tick_countdown(now)
            c = self.settings.countdown
            if now - self.phase_since >= c.seconds + c.final_hold_ms / 1000:
                self._start_video(now, "countdown")
        elif self.phase == Phase.FINISHED:
            wait = self.settings.video.auto_return_idle_s
            if wait > 0 and now - self.phase_since >= wait:
                self._enter(Phase.IDLE, now, "auto")

    def countdown_value(self, now: float) -> int:
        """Number to show: seconds..1, then 0 for the final text."""
        remaining = self.settings.countdown.seconds - (now - self.phase_since)
        return max(0, math.ceil(remaining - 1e-9))

    def _tick_countdown(self, now: float) -> None:
        value = self.countdown_value(now)
        if value != self.last_tick_value:
            self.last_tick_value = value
            self._emit("tick", value)

    def listening_remaining(self, now: float) -> float:
        timeout = self.settings.gesture.listening_timeout_s
        return max(0.0, timeout - (now - self.last_activity)) if timeout > 0 else 0.0
