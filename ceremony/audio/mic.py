"""Microphone input → clap onsets, timestamped on the same clock as camera frames."""

from __future__ import annotations

import time
import warnings

import numpy as np
from PySide6.QtCore import QObject, Signal

from .onset import OnsetDetector

BLOCKSIZE = 512

# sounddevice 0.5.x reshapes buffers in a way NumPy 2.5 warns about on every callback.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="sounddevice")


def list_input_devices() -> list[str]:
    try:
        import sounddevice as sd

        names = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        return list(dict.fromkeys(names))
    except Exception:
        return []


class Microphone(QObject):
    onset = Signal(float)  # perf_counter time of the clap sound
    level = Signal(float)  # dBFS, throttled
    status = Signal(bool, str)  # ok, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream = None
        self._detector: OnsetDetector | None = None
        self._last_level_emit = 0.0
        self.ok = False

    def start(self, device_name: str, sensitivity: float) -> None:
        self.stop()
        try:
            import sounddevice as sd

            device = None
            if device_name:
                for i, d in enumerate(sd.query_devices()):
                    if d["name"] == device_name and d["max_input_channels"] > 0:
                        device = i
                        break
            info = sd.query_devices(device, "input")
            sr = int(info["default_samplerate"]) or 48000
            self._detector = OnsetDetector(sr, BLOCKSIZE, sensitivity)
            self._stream = sd.InputStream(
                device=device,
                channels=1,
                samplerate=sr,
                blocksize=BLOCKSIZE,
                dtype="float32",
                latency="low",
                callback=self._callback,
            )
            self._stream.start()
            self.ok = True
            self.status.emit(True, f"Mic: {info['name']} ({sr} Hz)")
        except Exception as err:  # no device, permission denied, PortAudio missing...
            self._stream = None
            self.ok = False
            self.status.emit(False, f"Mic tidak tersedia: {err}")

    def set_sensitivity(self, sensitivity: float) -> None:
        if self._detector:
            self._detector.set_sensitivity(sensitivity)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self.ok = False

    def _callback(self, indata, frames, time_info, status) -> None:  # PortAudio thread
        now = time.perf_counter()
        try:
            age = time_info.currentTime - time_info.inputBufferAdcTime
        except Exception:
            age = 0.0
        if not 0.0 <= age < 1.0:
            age = frames / (self._detector.samplerate if self._detector else 48000)
        t_block = now - age
        block = np.asarray(indata[:, 0], dtype=np.float32)
        det = self._detector
        if det is None:
            return
        if det.process(block, t_block):
            self.onset.emit(t_block)
        if now - self._last_level_emit > 0.05:
            self._last_level_emit = now
            self.level.emit(det.level_db)
