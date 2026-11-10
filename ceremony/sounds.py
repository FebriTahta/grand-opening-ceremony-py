"""Short UI sound effects, synthesized once into the data directory."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

SR = 44100


def _tone(freqs: list[float], seconds: float, decay: float, volume: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    x = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    env = np.exp(-t / decay) * np.minimum(1, t / 0.004)
    return x * env * volume


def _sequence(parts: list[np.ndarray], gap: float = 0.0) -> np.ndarray:
    silence = np.zeros(int(SR * gap))
    out = []
    for p in parts:
        out += [p, silence]
    return np.concatenate(out)


SOUNDS = {
    "tick": lambda: _tone([880, 1760], 0.18, 0.06),
    "final": lambda: _sequence([_tone([523.25, 659.25, 783.99, 1046.5], 1.6, 0.5, 0.6)]),
    "ack": lambda: _sequence([_tone([659.25], 0.12, 0.05), _tone([987.77], 0.25, 0.1)], 0.02),
    "clap": lambda: _tone([1318.5, 2637], 0.22, 0.07, 0.45),
}


def _write_wav(path: Path, samples: np.ndarray) -> None:
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


class SoundBank:
    def __init__(self, directory: Path):
        self.effects: dict[str, QSoundEffect] = {}
        for name, make in SOUNDS.items():
            path = directory / f"{name}.wav"
            if not path.exists():
                _write_wav(path, make())
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(str(path)))
            self.effects[name] = effect

    def set_volume(self, volume: float) -> None:
        for e in self.effects.values():
            e.setVolume(max(0.0, min(1.0, volume)))

    def play(self, name: str) -> None:
        effect = self.effects.get(name)
        if effect:
            effect.stop()
            effect.play()
