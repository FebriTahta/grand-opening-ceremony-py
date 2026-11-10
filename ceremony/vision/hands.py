"""Hand observations and the geometry used by every detector.

Landmarks follow MediaPipe's 21-point hand model. Image landmarks are normalized to
[0, 1]; `aspect` (width / height) is applied before measuring 2D distances so that
horizontal and vertical distances are comparable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float, float]

WRIST = 0
THUMB = (1, 2, 3, 4)
INDEX = (5, 6, 7, 8)
MIDDLE = (9, 10, 11, 12)
RING = (13, 14, 15, 16)
PINKY = (17, 18, 19, 20)
PALM_POINTS = (WRIST, INDEX[0], MIDDLE[0], RING[0], PINKY[0])

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)  # fmt: skip


def dist3(a: Point, b: Point) -> float:
    return math.dist(a, b)


@dataclass
class Hand:
    image: list[Point]  # normalized image landmarks
    world: list[Point]  # metric, rotation independent landmarks (falls back to image)
    handedness: str = ""
    score: float = 1.0
    aspect: float = 16 / 9

    def xy(self, i: int) -> tuple[float, float]:
        x, y, _ = self.image[i]
        return x * self.aspect, y

    @property
    def palm_center(self) -> tuple[float, float]:
        pts = [self.xy(i) for i in PALM_POINTS]
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)

    @property
    def palm_size(self) -> float:
        """Wrist to middle-finger knuckle in aspect-corrected image units."""
        return math.dist(self.xy(WRIST), self.xy(MIDDLE[0])) or 1e-6

    @property
    def normalized_center(self) -> tuple[float, float]:
        cx, cy = self.palm_center
        return cx / self.aspect, cy


@dataclass
class HandsFrame:
    """One processed camera frame."""

    t: float  # time.perf_counter() when the frame was captured
    hands: list[Hand] = field(default_factory=list)
    target: list[Hand] = field(default_factory=list)  # the performer's hands (0-2), left to right
    width: int = 0
    height: int = 0


def palm_distance_ratio(a: Hand, b: Hand) -> float:
    """Distance between palm centers relative to the average palm size."""
    size = (a.palm_size + b.palm_size) / 2
    return math.dist(a.palm_center, b.palm_center) / size


def select_pair(hands: list[Hand], roi: tuple[float, float, float, float]) -> list[Hand]:
    """Pick the hands that belong to the person performing the ceremony.

    Hands outside the region of interest are dropped; of the rest, the largest two
    (closest to the camera) win. Returns 0, 1 or 2 hands, ordered left to right.
    """
    rx, ry, rw, rh = roi
    inside = []
    for h in hands:
        x, y = h.normalized_center
        if rx <= x <= rx + rw and ry <= y <= ry + rh:
            inside.append(h)
    inside.sort(key=lambda h: h.palm_size, reverse=True)
    picked = inside[:2]
    if len(picked) == 2:
        # A far-away hand next to a close one is almost always someone else's.
        small, big = sorted((picked[0].palm_size, picked[1].palm_size))
        if small < big * 0.45:
            picked = picked[:1]
    picked.sort(key=lambda h: h.palm_center[0])
    return picked
