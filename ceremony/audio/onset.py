"""Clap-sound detection from raw microphone blocks.

A hand clap is a very short, broadband transient. Music and speech are mostly steady
or low-frequency, so instead of looking at loudness we look at *spectral flux* above
~1.5 kHz: how much high-frequency energy appeared since the previous block. The
threshold adapts to the recent median, so a loud but steady background (music, crowd
murmur) raises the bar instead of triggering.
"""

from __future__ import annotations

from collections import deque

import numpy as np


class OnsetDetector:
    def __init__(self, samplerate: int = 48000, blocksize: int = 512, sensitivity: float = 0.5):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.window = np.hanning(blocksize).astype(np.float32)
        freqs = np.fft.rfftfreq(blocksize, 1 / samplerate)
        self.band = freqs >= 1500
        self.prev_mag: np.ndarray | None = None
        self.flux_history: deque[float] = deque(maxlen=max(8, int(1.0 * samplerate / blocksize)))
        self.refractory_s = 0.12
        self.last_onset = -1e9
        self.level_db = -120.0
        self.set_sensitivity(sensitivity)

    def set_sensitivity(self, sensitivity: float) -> None:
        s = float(np.clip(sensitivity, 0.0, 1.0))
        # 0 → needs a flux 8x the background; 1 → 2.5x.
        self.ratio = 8.0 - 5.5 * s
        # Absolute floor so near-silence noise never triggers.
        self.floor = 0.02 * (1.6 - s)

    def process(self, block: np.ndarray, t: float) -> bool:
        """Feed one mono float32 block whose start was captured at `t`. Returns True on a clap onset."""
        if len(block) != self.blocksize:
            block = np.resize(block, self.blocksize)
        rms = float(np.sqrt(np.mean(block * block)) + 1e-12)
        self.level_db = 20 * np.log10(rms)

        mag = np.abs(np.fft.rfft(block * self.window))[self.band]
        mag = np.log1p(mag * 10)
        if self.prev_mag is None:
            self.prev_mag = mag
            return False
        flux = float(np.mean(np.maximum(mag - self.prev_mag, 0.0)))
        self.prev_mag = mag

        background = float(np.median(self.flux_history)) if len(self.flux_history) >= 8 else flux
        self.flux_history.append(flux)

        if flux < self.floor or flux < background * self.ratio:
            return False
        if t - self.last_onset < self.refractory_s:
            return False
        self.last_onset = t
        return True
