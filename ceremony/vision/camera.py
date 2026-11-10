"""Camera capture + MediaPipe hand tracking on a background thread."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..config import bundled_path
from .hands import HAND_CONNECTIONS, Hand, HandsFrame, select_pair

MODEL_PATH = bundled_path("models", "hand_landmarker.task")
PREVIEW_INTERVAL = 1 / 20


@dataclass
class TrackerConfig:
    camera_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    max_hands: int = 4
    min_detection_confidence: float = 0.6
    min_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    mirror_preview: bool = True


def _create_landmarker(cfg: TrackerConfig):
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.HandLandmarkerOptions(
        # Loaded from memory: MediaPipe fails on non-ASCII file paths on Windows.
        base_options=BaseOptions(model_asset_buffer=MODEL_PATH.read_bytes()),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=cfg.max_hands,
        min_hand_detection_confidence=cfg.min_detection_confidence,
        min_hand_presence_confidence=cfg.min_presence_confidence,
        min_tracking_confidence=cfg.min_tracking_confidence,
    )
    return vision.HandLandmarker.create_from_options(options)


def _backends() -> list[int]:
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION]
    if sys.platform == "win32":
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF]
    return [cv2.CAP_ANY]


def _open_camera(cfg: TrackerConfig) -> cv2.VideoCapture:
    for backend in _backends():
        cap = cv2.VideoCapture(cfg.camera_index, backend)
        if cap.isOpened():
            break
        cap.release()
    if sys.platform == "win32":
        # Most USB webcams only deliver 720p/1080p at 30 FPS over DirectShow in MJPG.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.height)
    cap.set(cv2.CAP_PROP_FPS, cfg.fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def draw_hands(frame: np.ndarray, hands: list[Hand], target: set[int]) -> None:
    h, w = frame.shape[:2]
    for i, hand in enumerate(hands):
        color = (80, 220, 120) if i in target else (150, 150, 150)
        pts = [(int(x * w), int(y * h)) for x, y, _ in hand.image]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], color, 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(frame, p, 3, (255, 255, 255), -1, cv2.LINE_AA)


class VisionWorker(QThread):
    frame_ready = Signal(object)  # HandsFrame
    preview_ready = Signal(QImage)
    status = Signal(bool, str)
    fps_changed = Signal(float)

    def __init__(self, cfg: TrackerConfig, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._running = True
        self.roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)

    def stop(self) -> None:
        self._running = False
        self.wait(3000)

    def run(self) -> None:
        try:
            landmarker = _create_landmarker(self.cfg)
        except Exception as err:
            self.status.emit(False, f"Model MediaPipe gagal dimuat: {err}")
            return

        cap = None
        last_preview = 0.0
        last_ts_ms = 0
        fps_frames, fps_since = 0, time.perf_counter()
        try:
            while self._running:
                if cap is None or not cap.isOpened():
                    cap = _open_camera(self.cfg)
                    if not cap.isOpened():
                        self.status.emit(False, f"Kamera #{self.cfg.camera_index} tidak bisa dibuka, mencoba lagi…")
                        cap.release()
                        cap = None
                        self.msleep(2000)
                        continue
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    self.status.emit(True, f"Kamera #{self.cfg.camera_index} aktif ({w}×{h})")

                ok, frame = cap.read()
                now = time.perf_counter()
                if not ok or frame is None:
                    self.status.emit(False, "Kamera berhenti mengirim gambar, menyambung ulang…")
                    cap.release()
                    cap = None
                    self.msleep(500)
                    continue

                hands = self._detect(landmarker, frame, now, last_ts_ms)
                last_ts_ms = max(last_ts_ms + 1, int(now * 1000))
                target = select_pair(hands, self.roi)
                h, w = frame.shape[:2]
                self.frame_ready.emit(HandsFrame(now, hands, target, w, h))

                fps_frames += 1
                if now - fps_since >= 1.0:
                    self.fps_changed.emit(fps_frames / (now - fps_since))
                    fps_frames, fps_since = 0, now

                if now - last_preview >= PREVIEW_INTERVAL:
                    last_preview = now
                    self.preview_ready.emit(self._preview(frame, hands, target))
        finally:
            if cap is not None:
                cap.release()
            landmarker.close()

    def _detect(self, landmarker, frame: np.ndarray, now: float, last_ts_ms: int) -> list[Hand]:
        import mediapipe as mp

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = max(last_ts_ms + 1, int(now * 1000))
        result = landmarker.detect_for_video(image, ts)
        h, w = frame.shape[:2]
        hands: list[Hand] = []
        for i, lms in enumerate(result.hand_landmarks):
            img = [(p.x, p.y, p.z) for p in lms]
            world = result.hand_world_landmarks[i] if i < len(result.hand_world_landmarks) else None
            wpts = [(p.x, p.y, p.z) for p in world] if world else img
            cat = result.handedness[i][0] if i < len(result.handedness) and result.handedness[i] else None
            hands.append(
                Hand(img, wpts, cat.category_name if cat else "", cat.score if cat else 1.0, aspect=w / h)
            )
        return hands

    def _preview(self, frame: np.ndarray, hands: list[Hand], target: list[Hand]) -> QImage:
        small = frame
        scale = 640 / frame.shape[1]
        if scale < 1:
            small = cv2.resize(frame, (640, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        draw_hands(small, hands, {i for i, hand in enumerate(hands) if any(hand is t for t in target)})
        h, w = small.shape[:2]
        rx, ry, rw, rh = self.roi
        if (rx, ry, rw, rh) != (0.0, 0.0, 1.0, 1.0):
            cv2.rectangle(small, (int(rx * w), int(ry * h)), (int((rx + rw) * w), int((ry + rh) * h)), (232, 196, 104), 2)
        if self.cfg.mirror_preview:
            small = cv2.flip(small, 1)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
