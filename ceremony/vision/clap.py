"""Visual clap detection.

A clap is a full cycle: hands apart → palms meet → hands apart again. Distance is the
gap between palm centers divided by palm size, so it doesn't depend on how far the
person stands from the camera.

    ratio
    release ─────┐        ┌─────┐        ┌───   (must pass this to re-arm)
    contact ─ ─ ─│─ ─ ─ ─ │─ ─ ─│─ ─ ─ ─ │─ ─
                 └───●────┘     └───●────┘
                   clap 1         clap 2

When palms touch, MediaPipe often loses one hand (it's hidden behind the other) or
merges both into one. Losing a hand right after a fast approach therefore also counts,
but as a *weak* candidate that audio may be asked to confirm.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class ClapCandidate:
    t: float
    strong: bool  # True = contact seen with both hands visible; False = inferred from tracking loss
    ratio: float


class ClapDetector:
    def __init__(
        self,
        contact_ratio: float = 0.75,
        release_ratio: float = 1.3,
        min_interval_ms: int = 180,
        detect_on_tracking_loss: bool = True,
    ):
        self.contact_ratio = contact_ratio
        self.release_ratio = release_ratio
        self.min_interval_ms = min_interval_ms
        self.detect_on_tracking_loss = detect_on_tracking_loss
        self.armed = False
        self.last_ratio: float | None = None
        self._history: deque[tuple[float, float]] = deque()  # (t, ratio) with both hands visible
        self._last_clap_t = -1e9
        self._last_pair_t = -1e9

    def reset(self) -> None:
        self.armed = False
        self.last_ratio = None
        self._history.clear()
        self._last_pair_t = -1e9

    @property
    def last_clap_t(self) -> float:
        return self._last_clap_t

    def hands_close(self) -> bool:
        return self.last_ratio is not None and self.last_ratio < self.release_ratio

    def feed(self, ratio: float | None, now: float) -> ClapCandidate | None:
        """Feed the palm-distance ratio of the target pair, or None when fewer than two hands are visible."""
        if ratio is None:
            self.last_ratio = None
            return self._on_lost(now)

        self.last_ratio = ratio
        self._last_pair_t = now
        self._history.append((now, ratio))
        while self._history and now - self._history[0][0] > 0.5:
            self._history.popleft()

        if ratio > self.release_ratio:
            self.armed = True
            return None
        if self.armed and ratio < self.contact_ratio:
            return self._emit(now, strong=True, ratio=ratio)
        return None

    def _on_lost(self, now: float) -> ClapCandidate | None:
        if not (self.detect_on_tracking_loss and self.armed and self._history):
            return None
        last_t, last_ratio = self._history[-1]
        if now - last_t > 0.2 or last_ratio > self.release_ratio * 1.1:
            return None
        # Require a real approach: the gap must have shrunk noticeably over the last moments.
        earlier = [r for t, r in self._history if last_t - t >= 0.08]
        peak = max(earlier) if earlier else last_ratio
        if peak - last_ratio < 0.25:
            return None
        candidate = self._emit(now, strong=False, ratio=last_ratio)
        self._history.clear()
        return candidate

    def _emit(self, now: float, strong: bool, ratio: float) -> ClapCandidate | None:
        self.armed = False
        if (now - self._last_clap_t) * 1000 < self.min_interval_ms:
            return None
        self._last_clap_t = now
        return ClapCandidate(now, strong, ratio)
