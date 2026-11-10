"""Synthetic MediaPipe-style hand landmarks for tests (image coords: x right, y down)."""

from ceremony.vision.hands import Hand

KNUCKLE_X = (-0.030, -0.010, 0.010, 0.028)  # index, middle, ring, pinky relative to wrist
SEG = 0.032


def make_hand(cx: float, cy: float, shape: str = "open", scale: float = 1.0, side: int = 1) -> Hand:
    """shape: "open" (all fingers up), "fist" (all folded). `side` mirrors the thumb (+1 right, -1 left)."""
    s = scale
    pts = [(0.0, 0.0, 0.0)] * 21
    pts[0] = (cx, cy, 0.0)
    # Thumb sticks out sideways when open, tucked across the palm in a fist.
    if shape == "open":
        thumb = [(cx + side * 0.025 * s, cy - 0.02 * s), (cx + side * 0.045 * s, cy - 0.035 * s),
                 (cx + side * 0.062 * s, cy - 0.05 * s), (cx + side * 0.078 * s, cy - 0.065 * s)]  # fmt: skip
    else:
        thumb = [(cx + side * 0.02 * s, cy - 0.02 * s), (cx + side * 0.025 * s, cy - 0.045 * s),
                 (cx + side * 0.01 * s, cy - 0.06 * s), (cx - side * 0.005 * s, cy - 0.065 * s)]  # fmt: skip
    for i, (x, y) in enumerate(thumb):
        pts[1 + i] = (x, y, 0.0)
    for f, kx in enumerate(KNUCKLE_X):
        base = 5 + 4 * f
        mx, my = cx + kx * s, cy - 0.09 * s
        pts[base] = (mx, my, 0.0)
        if shape == "open":
            for j in range(1, 4):
                pts[base + j] = (mx, my - SEG * j * s, 0.0)
        else:
            # Curl forward (towards the camera) and back down onto the palm.
            pts[base + 1] = (mx, my - 0.025 * s, -0.02 * s)
            pts[base + 2] = (mx, my - 0.005 * s, -0.04 * s)
            pts[base + 3] = (mx, my + 0.02 * s, -0.03 * s)
    return Hand(image=pts, world=pts, handedness="Right" if side > 0 else "Left", aspect=1.0)


def pair(gap: float, shape: str = "open", cy: float = 0.6) -> list[Hand]:
    """Two hands whose palm centers are `gap` apart (normalized units), left to right."""
    return [make_hand(0.5 - gap / 2, cy, shape, side=-1), make_hand(0.5 + gap / 2, cy, shape, side=1)]


def hanging(hand: Hand) -> Hand:
    """The same hand pointing down (arm relaxed at the side): mirrored vertically around the wrist."""
    wy = hand.image[0][1]
    pts = [(x, 2 * wy - y, z) for x, y, z in hand.image]
    return Hand(image=pts, world=pts, handedness=hand.handedness, aspect=hand.aspect)
