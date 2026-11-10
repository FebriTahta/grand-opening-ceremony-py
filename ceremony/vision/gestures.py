"""Turns noisy per-frame booleans into a single "held long enough" event."""

from __future__ import annotations


class HoldDetector:
    """Fires once when a condition has held for `hold_ms`.

    Short dropouts (up to `grace_ms`) don't restart the timer, so a single misclassified
    frame doesn't cost the user the whole hold. After firing, the condition must be gone
    for `grace_ms` before the detector can fire again — holding never repeats.
    """

    def __init__(self, hold_ms: int, grace_ms: int = 150):
        self.hold_ms = hold_ms
        self.grace_ms = grace_ms
        self._since: float | None = None
        self._last_true: float | None = None
        self._fired = False

    def reset(self) -> None:
        self._since = None
        self._last_true = None
        self._fired = False

    def feed(self, active: bool, now: float) -> bool:
        """Returns True exactly once per completed hold."""
        if active:
            if self._since is None:
                self._since = now
            self._last_true = now
        elif self._last_true is None or (now - self._last_true) * 1000 > self.grace_ms:
            self._since = None
            self._last_true = None
            self._fired = False
            return False

        if not self._fired and self._since is not None and (now - self._since) * 1000 >= self.hold_ms:
            self._fired = True
            return True
        return False

    def progress(self, now: float) -> float:
        if self._fired:
            return 1.0
        if self._since is None:
            return 0.0
        return 1.0 if self.hold_ms <= 0 else min(1.0, (now - self._since) * 1000 / self.hold_ms)
