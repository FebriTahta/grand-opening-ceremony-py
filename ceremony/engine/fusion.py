"""Combines visual clap candidates with microphone onsets.

The camera is always the gate: a sound alone never produces a clap, so applause or
noise from outside the frame cannot advance the ceremony. Audio only confirms.

    strict   → camera AND sound
    balanced → a clear visual contact is enough; a weak one (inferred from tracking loss) needs sound
    camera   → sound ignored

The camera sees a clap later than the mic hears it, so audio times are compared after
shifting by `offset_ms` (measured with the calibration tool).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..vision.clap import ClapCandidate

MODES = ("strict", "balanced", "camera")


@dataclass
class ClapDecision:
    t: float
    strong: bool
    audio: bool
    accepted: bool
    reason: str


class ClapFusion:
    def __init__(self, mode: str = "balanced", window_ms: int = 150, offset_ms: int = 70):
        self.mode = mode if mode in MODES else "balanced"
        self.window = window_ms / 1000
        self.offset = offset_ms / 1000
        self.audio_available = True
        self._pending: list[ClapCandidate] = []
        self._audio: deque[float] = deque()

    @property
    def effective_mode(self) -> str:
        return self.mode if self.audio_available else "camera"

    def reset(self) -> None:
        self._pending.clear()
        self._audio.clear()

    def add_audio(self, t: float) -> None:
        self._audio.append(t)

    def add_visual(self, candidate: ClapCandidate) -> None:
        self._pending.append(candidate)

    def resolve(self, now: float) -> list[ClapDecision]:
        decisions: list[ClapDecision] = []
        mode = self.effective_mode
        still_pending = []
        for c in self._pending:
            # Wait until any matching sound would have arrived (audio is earlier, so this is short).
            if mode != "camera" and now < c.t + self.window:
                still_pending.append(c)
                continue
            audio = self._take_audio(c.t)
            if mode == "camera":
                accepted, reason = True, "kamera"
            elif mode == "strict":
                accepted, reason = audio, ("kamera + suara" if audio else "tanpa suara")
            elif c.strong:
                accepted, reason = True, ("kamera + suara" if audio else "kamera jelas")
            else:
                accepted, reason = audio, ("kamera + suara" if audio else "kontak ragu, tanpa suara")
            decisions.append(ClapDecision(c.t, c.strong, audio, accepted, reason))
        self._pending = still_pending
        while self._audio and now - self._audio[0] > 2.0:
            self._audio.popleft()
        return decisions

    def _take_audio(self, t_visual: float) -> bool:
        expected = t_visual - self.offset
        best = None
        for a in self._audio:
            if abs(a - expected) <= self.window and (best is None or abs(a - expected) < abs(best - expected)):
                best = a
        if best is None:
            return False
        self._audio.remove(best)  # one sound can confirm only one clap
        return True


class OffsetCalibrator:
    """Measures camera-vs-mic latency from a handful of claps."""

    def __init__(self, needed: int = 6, search_s: float = 0.4):
        self.needed = needed
        self.search = search_s
        self.samples: list[float] = []
        self._audio: deque[float] = deque()
        self._visual: list[float] = []

    def add_audio(self, t: float) -> None:
        self._audio.append(t)

    def add_visual(self, t: float) -> None:
        self._visual.append(t)

    def update(self, now: float) -> None:
        remaining = []
        for v in self._visual:
            if now < v + 0.1:  # give late audio a moment
                remaining.append(v)
                continue
            near = [a for a in self._audio if -self.search <= v - a <= self.search]
            if near:
                a = min(near, key=lambda a: abs(v - a))
                self.samples.append(v - a)
                self._audio.remove(a)
        self._visual = remaining
        while self._audio and now - self._audio[0] > 3.0:
            self._audio.popleft()

    @property
    def done(self) -> bool:
        return len(self.samples) >= self.needed

    def result_ms(self) -> int | None:
        if not self.samples:
            return None
        s = sorted(self.samples)
        return round(s[len(s) // 2] * 1000)
