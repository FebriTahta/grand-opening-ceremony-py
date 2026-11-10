"""Static hand-shape classification (ported from the web version's classify.ts)."""

from __future__ import annotations

from dataclasses import dataclass

from .hands import INDEX, MIDDLE, PINKY, RING, THUMB, WRIST, Hand, Point, dist3


def _straightness(points: list[Point], chain: tuple[int, ...]) -> float:
    """Straight-line length of a joint chain divided by its path length: 1 = perfectly straight."""
    path = sum(dist3(points[chain[i - 1]], points[chain[i]]) for i in range(1, len(chain)))
    return 0.0 if path == 0 else dist3(points[chain[0]], points[chain[-1]]) / path


@dataclass
class HandShape:
    thumb: bool
    index: bool
    middle: bool
    ring: bool
    pinky: bool

    @property
    def fingers(self) -> int:
        """Extended fingers, thumb excluded (thumb detection is the least reliable)."""
        return sum((self.index, self.middle, self.ring, self.pinky))

    @property
    def is_open(self) -> bool:
        return self.fingers == 4

    @property
    def is_fist(self) -> bool:
        return self.fingers == 0


def hand_shape(points: list[Point]) -> HandShape:
    """Works on world landmarks, so the result does not depend on how the hand faces the camera."""
    palm = dist3(points[WRIST], points[MIDDLE[0]]) or 1.0

    def finger(chain: tuple[int, ...]) -> bool:
        return (
            _straightness(points, chain) > 0.85
            # A straight but folded-down finger must not count: tip has to be well past the knuckle.
            and dist3(points[WRIST], points[chain[3]]) > dist3(points[WRIST], points[chain[1]]) * 1.15
        )

    tip = points[THUMB[3]]
    thumb = (
        _straightness(points, THUMB[1:]) > 0.85
        and dist3(tip, points[INDEX[0]]) / palm > 0.55
        and dist3(tip, points[PINKY[0]]) > dist3(points[THUMB[2]], points[PINKY[0]])
    )
    return HandShape(thumb, finger(INDEX), finger(MIDDLE), finger(RING), finger(PINKY))


def is_raised_fist(hand: Hand) -> bool:
    """A deliberate "rock" is held up: knuckles clearly above the wrist.

    Hands hanging relaxed after clapping are often curled like a fist, but point down."""
    return hand.image[MIDDLE[0]][1] < hand.image[WRIST][1] - 0.4 * hand.palm_size


def is_raised(hand: Hand) -> bool:
    """Fingers pointing up in the image (middle fingertip above the wrist)."""
    return hand.image[MIDDLE[3]][1] < hand.image[WRIST][1] - 0.5 * hand.palm_size
