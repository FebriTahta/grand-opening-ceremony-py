"""Countdown visual styles, shared by the stage and the settings preview.

Everything is drawn in 1920×1080 reference units around CENTER. A style only draws the
number (and its decoration); the label above it and the final text are common.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from ..config import AppearanceSettings

REF_W, REF_H = 1920, 1080
CENTER = QPointF(REF_W / 2, 610)

STYLES = {
    "ring": "Cincin klasik",
    "flip": "Kartu flip",
    "neon": "Neon",
    "minimal": "Minimalis",
    "shockwave": "Gelombang kejut",
    "segments": "Segmen stadion",
    "fiber": "Serat optik",
}

STYLE_HINTS = {
    "ring": "Angka besar dengan cincin yang berkurang setiap detik.",
    "flip": "Kartu angka seperti papan jadwal bandara, berganti dengan animasi lipat.",
    "neon": "Angka bercahaya seperti tabung neon, berkedip saat berganti.",
    "minimal": "Angka tipis raksasa yang meluncur naik, dengan garis progres tipis.",
    "shockwave": "Angka menghentak masuk diiringi gelombang cincin dan kilatan cahaya.",
    "segments": "Lingkaran segmen (satu per detik) yang padam satu per satu, seperti papan skor stadion.",
    "fiber": "Latar ribuan serat optik biru-ungu yang melambai dengan denyut cahaya; angka bercahaya seperti kabel, "
    "dan teks akhir meledak menjadi pancaran serat.",
}

# Fiber-optic palette (independent of the theme colors, to match the blue/violet look).
FIBER_COLORS = ("#2F6BFF", "#3FC8FF", "#6F5BFF", "#A64DFF")


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_out_back(x: float) -> float:
    x = max(0.0, min(1.0, x))
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def _bezier(pts: tuple[QPointF, QPointF, QPointF, QPointF], u: float) -> QPointF:
    a, b, c, d = pts
    v = 1 - u
    return a * (v * v * v) + b * (3 * v * v * u) + c * (3 * v * u * u) + d * (u * u * u)


@dataclass
class _Strand:
    p0: QPointF
    p1: QPointF
    p2: QPointF
    p3: QPointF
    color: int  # index into FIBER_COLORS
    width: float
    layer: int  # strands are pre-rendered into a few layers that drift independently
    phase: float
    speed: float
    pulse: float  # light pulse offset along the strand; < 0 = no pulse
    tip: bool  # glowing end, like a cut fiber


def _fiber_strands() -> list[_Strand]:
    rnd = random.Random(1108)
    strands = []
    # The bundle: sweeps from bottom-left up to the right edge.
    for _ in range(70):
        k = rnd.random()
        strands.append(_Strand(
            QPointF(-200, 900 + 380 * k), QPointF(520, 820 + 260 * k), QPointF(1250, 430 + 150 * k),
            QPointF(2150, 250 + 140 * k + rnd.uniform(-20, 20)),
            rnd.choice((0, 0, 2, 2, 3)) if k > 0.35 else rnd.choice((0, 1, 1, 2)),
            rnd.uniform(1.2, 3.2), int(k > 0.5), rnd.uniform(0, 6.3), rnd.uniform(0.35, 0.7),
            rnd.random() if rnd.random() < 0.35 else -1, False,
        ))  # fmt: skip
    # The fan: loose fibers leaving the bundle and splaying up-left, each ending in a glowing tip.
    for i in range(95):
        sx = rnd.uniform(1300, 2150)
        sy = 480 - 0.17 * (sx - 1300) + rnd.uniform(-30, 30)
        tx = rnd.uniform(-60, 1950)
        ty = rnd.uniform(60, 330) + 0.12 * max(0.0, 900 - tx) * rnd.random()
        strands.append(_Strand(
            QPointF(sx, sy), QPointF(sx - 0.35 * (sx - tx), sy - 40), QPointF(tx + 0.25 * (sx - tx), ty + 120),
            QPointF(tx, ty), rnd.choice((0, 1, 1, 2, 3)), rnd.uniform(0.8, 1.8), 2 + i % 2,
            rnd.uniform(0, 6.3), rnd.uniform(0.4, 0.9), rnd.random() if rnd.random() < 0.25 else -1, True,
        ))  # fmt: skip
    return strands


FIBER_LAYERS = 4


def _layer_offset(layer: int, t: float) -> QPointF:
    """Slow drift of one fiber layer; layers move out of step, which reads as the fibers swaying."""
    if layer < 2:  # the bundle rolls up and down
        return QPointF(6 * math.sin(t * 0.5 + layer), 14 * math.sin(t * 0.7 + layer * 1.9))
    return QPointF(18 * math.sin(t * 0.45 + layer * 2.3), 12 * math.cos(t * 0.6 + layer))


@dataclass
class CountdownFrame:
    value: int  # number on screen, total..1
    total: int  # countdown length in seconds
    frac: float  # 0..1, how much of the current second has passed
    since_tick: float  # seconds since the number changed

    @property
    def previous(self) -> int | None:
        """The number shown just before this one (counting down), if any."""
        return self.value + 1 if self.value < self.total else None

    @property
    def overall(self) -> float:
        """0..1 of the whole countdown remaining."""
        return max(0.0, min(1.0, (self.value - self.frac) / max(1, self.total)))


class CountdownPainter:
    def __init__(self, appearance: Callable[[], AppearanceSettings]):
        self._appearance = appearance
        self._strands = _fiber_strands()
        self._sprites: dict[str, QImage] = {}
        self._fiber_cache: list[QImage] = []
        self._burst_cache: tuple[QImage, list[tuple[QPointF, str, float]]] | None = None
        self._wire_cache: dict[tuple[str, int, str], tuple[QImage, QRectF, QPainterPath]] = {}

    # --- shared helpers -------------------------------------------------------

    @property
    def a(self) -> AppearanceSettings:
        return self._appearance()

    def font(self, px: float, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0) -> QFont:
        family = self.a.font_family
        f = QFont(family) if family else QFont()
        f.setPixelSize(max(1, int(px)))
        f.setWeight(weight)
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        return f

    def color(self, which: str, alpha: float = 1.0) -> QColor:
        c = QColor(self.a.accent_color if which == "accent" else self.a.text_color)
        c.setAlphaF(max(0.0, min(1.0, alpha)))
        return c

    def ring(self, p: QPainter, center: QPointF, radius: float, progress: float, width: float = 12) -> None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.color("text", 0.16), width))
        p.drawEllipse(center, radius, radius)
        if progress > 0:
            pen = QPen(self.color("accent"), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
            p.drawArc(rect, 90 * 16, int(-progress * 360 * 16))

    def _number(self, p: QPainter, text: str, center: QPointF, font: QFont, color: QColor, shadow: bool = True) -> None:
        box = QRectF(center.x() - 600, center.y() - 400, 1200, 800)
        p.setFont(font)
        if shadow:
            p.setPen(QColor(0, 0, 0, int(90 * color.alphaF())))
            p.drawText(box.translated(0, 4), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(color)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _glow(self, p: QPainter, center: QPointF, radius: float, color: str, alpha: float) -> None:
        """Soft round light, drawn from a cached sprite (much cheaper than a gradient per dot)."""
        sprite = self._sprites.get(color)
        if sprite is None:
            sprite = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
            sprite.fill(Qt.GlobalColor.transparent)
            sp = QPainter(sprite)
            g = QRadialGradient(32, 32, 32)
            g.setColorAt(0, QColor(255, 255, 255))
            g.setColorAt(0.18, QColor(color).lighter(150))
            c = QColor(color)
            c.setAlphaF(0.35)
            g.setColorAt(0.45, c)
            c.setAlphaF(0)
            g.setColorAt(1, c)
            sp.fillRect(QRectF(0, 0, 64, 64), g)
            sp.end()
            self._sprites[color] = sprite
        p.save()
        p.setOpacity(p.opacity() * max(0.0, min(1.0, alpha)))
        p.drawImage(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius), sprite)
        p.restore()

    def _fitted_font(self, text: str, px: float) -> QFont:
        font = self.font(px, QFont.Weight.Black)
        width = QFontMetricsF(font).horizontalAdvance(text)
        if width > REF_W - 160:
            font.setPixelSize(int(px * (REF_W - 160) / width))
        return font

    def _text_path(self, text: str, font: QFont, center: QPointF) -> QPainterPath:
        path = QPainterPath()
        path.addText(0, 0, font, text)
        r = path.boundingRect()
        path.translate(center.x() - r.center().x(), center.y() - r.center().y())
        return path

    # --- entry points ---------------------------------------------------------

    def prepare(self, style: str, total: int, final_text: str) -> None:
        """Builds a style's cached images ahead of time, so the first countdown frames don't stutter."""
        if style != "fiber":
            return
        self._fiber_layers()
        self._fiber_burst()
        for value in range(max(1, total), max(0, total - 10), -1):
            img = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
            wp = QPainter(img)
            self._wire_text(wp, str(value), self.font(400, QFont.Weight.Black), 0, 0)
            if value == total:
                self._wire_text(wp, final_text, self._fitted_font(final_text, 200), 0, 0)
            wp.end()

    def paint_backdrop(self, p: QPainter, style: str, t: float, flash: float = 0.0) -> None:
        """Full-screen layer behind the label and number; only some styles have one.

        t is a continuous clock in seconds; flash (0..1) brightens it, e.g. right after a tick.
        """
        if style == "fiber":
            self._fiber_backdrop(p, t, flash)

    def paint(self, p: QPainter, style: str, f: CountdownFrame) -> None:
        getattr(self, f"_paint_{style}", self._paint_ring)(p, f)

    def paint_final(self, p: QPainter, text: str, since: float, style: str = "") -> None:
        if style == "fiber":
            self._fiber_final(p, text, since)
            return
        p.save()
        p.translate(REF_W / 2, REF_H / 2)
        s = 0.6 + 0.4 * ease_out(since / 0.6)
        p.scale(s, s)
        font = self._fitted_font(text, 200)
        p.setFont(font)
        p.setPen(QColor(0, 0, 0, 100))
        p.drawText(QRectF(-REF_W / 2, -297, REF_W, 600), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(self.color("accent"))
        p.drawText(QRectF(-REF_W / 2, -300, REF_W, 600), Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    # --- styles ---------------------------------------------------------------

    def _paint_ring(self, p: QPainter, f: CountdownFrame) -> None:
        self.ring(p, CENTER, 300, 1 - f.frac, 14)
        k = ease_out(f.since_tick / 0.45)
        p.save()
        p.translate(CENTER)
        s = 1.35 - 0.35 * k
        p.scale(s, s)
        p.setOpacity(0.25 + 0.75 * k)
        self._number(p, str(f.value), QPointF(0, 0), self.font(400, QFont.Weight.Black), self.color("text"))
        p.restore()

    def _paint_flip(self, p: QPainter, f: CountdownFrame) -> None:
        new, old = str(f.value), (str(f.previous) if f.previous is not None else None)
        digits = max(len(new), len(old or ""))
        w, h = 430 + 300 * (digits - 1), 600
        card = QRectF(CENTER.x() - w / 2, CENTER.y() - h / 2, w, h)
        mid = card.center().y()
        top, bottom = QRectF(card.left(), card.top(), w, h / 2), QRectF(card.left(), mid, w, h / 2)
        font = self.font(480, QFont.Weight.Bold)
        a = min(1.0, f.since_tick / 0.5) if old is not None else 1.0

        def face(rect: QRectF, text: str, shade: float = 0.0) -> None:
            """Draws the half of a card (with its half of the number) that falls inside rect."""
            p.save()
            p.setClipRect(rect)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(18, 22, 38, 235))
            p.drawRoundedRect(card, 40, 40)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(QRectF(card.left(), card.top(), w, h / 2), 40, 40)
            p.setFont(font)
            p.setPen(self.color("text"))
            p.drawText(card, Qt.AlignmentFlag.AlignCenter, text)
            if shade:
                p.setBrush(QColor(0, 0, 0, int(160 * shade)))
                p.drawRect(rect)
            p.restore()

        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(card.translated(0, 18), 40, 40)  # drop shadow
        p.restore()

        # Static halves: the new top is already revealed behind the flap; the old bottom stays until the flap lands.
        face(top, new)
        face(bottom, new if a >= 1 or old is None else old)
        if old is not None and a < 1:
            p.save()
            p.translate(0, mid)
            if a < 0.5:  # old top half folds down towards the hinge
                p.scale(1, math.cos(a / 0.5 * math.pi / 2))
                p.translate(0, -mid)
                face(top, old, shade=a / 0.5 * 0.6)
            else:  # new bottom half unfolds from the hinge
                p.scale(1, math.sin((a - 0.5) / 0.5 * math.pi / 2))
                p.translate(0, -mid)
                face(bottom, new, shade=(1 - (a - 0.5) / 0.5) * 0.6)
            p.restore()

        # Hinge line and side pins.
        p.setPen(QPen(QColor(0, 0, 0, 200), 8))
        p.drawLine(QPointF(card.left(), mid), QPointF(card.right(), mid))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color("accent"))
        for x in (card.left() - 4, card.right() - 10):
            p.drawRoundedRect(QRectF(x, mid - 30, 14, 60), 7, 7)

        # Overall progress bar under the card.
        bar = QRectF(CENTER.x() - 300, card.bottom() + 40, 600, 10)
        p.setBrush(self.color("text", 0.18))
        p.drawRoundedRect(bar, 5, 5)
        p.setBrush(self.color("accent"))
        p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * f.overall, bar.height()), 5, 5)

    def _paint_neon(self, p: QPainter, f: CountdownFrame) -> None:
        accent = self.color("accent")
        # Neon tubes flicker for a moment when the number changes, then settle with a slow hum.
        t = f.since_tick
        flicker = 1.0 if t > 0.28 else (0.25 if int(t * 40) % 3 == 0 else 0.9)
        glow = flicker * (0.85 + 0.15 * math.sin(f.frac * 2 * math.pi * 2))

        halo = QRadialGradient(CENTER, 420)
        h = QColor(accent)
        h.setAlphaF(0.22 * glow)
        halo.setColorAt(0, h)
        h.setAlphaF(0)
        halo.setColorAt(1, h)
        p.fillRect(QRectF(CENTER.x() - 420, CENTER.y() - 420, 840, 840), halo)

        # Thin tube ring that drains with the second.
        rect = QRectF(CENTER.x() - 320, CENTER.y() - 320, 640, 640)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((26, 0.10), (14, 0.22), (5, 0.9)):
            c = QColor(accent)
            c.setAlphaF(alpha * glow)
            pen = QPen(c, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, int(-(1 - f.frac) * 360 * 16))

        path = self._text_path(str(f.value), self.font(400, QFont.Weight.Bold), CENTER)
        for width, alpha in ((60, 0.06), (36, 0.12), (20, 0.25), (9, 0.6)):
            c = QColor(accent)
            c.setAlphaF(alpha * glow)
            pen = QPen(c, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.strokePath(path, pen)
        core = QColor(255, 255, 255)
        core.setAlphaF(0.35 + 0.65 * flicker)
        p.fillPath(path, core)
        edge = QColor(accent).lighter(130)
        edge.setAlphaF(flicker)
        p.strokePath(path, QPen(edge, 3))

    def _paint_minimal(self, p: QPainter, f: CountdownFrame) -> None:
        font = self.font(560, QFont.Weight.ExtraLight)
        k = ease_out(f.since_tick / 0.55)
        if f.previous is not None and k < 1:
            p.save()
            p.setOpacity((1 - k) ** 3)
            self._number(p, str(f.previous), QPointF(CENTER.x(), CENTER.y() - 320 * k), font, self.color("text"), False)
            p.restore()
        p.save()
        p.setOpacity(k**2 if f.previous is not None else min(1.0, 0.3 + k))
        self._number(p, str(f.value), QPointF(CENTER.x(), CENTER.y() + 220 * (1 - k)), font, self.color("text"), False)
        p.restore()

        y = 960
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color("text", 0.15))
        p.drawRect(QRectF(360, y, 1200, 4))
        p.setBrush(self.color("accent"))
        p.drawRect(QRectF(360, y, 1200 * f.overall, 4))
        p.drawEllipse(QPointF(360 + 1200 * f.overall, y + 2), 9, 9)

    def _paint_shockwave(self, p: QPainter, f: CountdownFrame) -> None:
        t = f.since_tick
        accent = self.color("accent")
        flash = max(0.0, 1 - t / 0.35)
        if flash > 0:
            g = QRadialGradient(CENTER, 900)
            c = QColor(accent)
            c.setAlphaF(0.35 * flash)
            g.setColorAt(0, c)
            c.setAlphaF(0)
            g.setColorAt(1, c)
            p.fillRect(QRectF(0, 0, REF_W, REF_H), g)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            w = ease_out((t - i * 0.12) / 0.9)
            if 0 < w < 1:
                c = QColor(accent)
                c.setAlphaF(0.8 * (1 - w))
                p.setPen(QPen(c, 14 * (1 - w) + 2))
                r = 180 + 620 * w
                p.drawEllipse(CENTER, r, r)
        p.save()
        p.translate(CENTER)
        s = 2.2 - 1.2 * ease_out_back(t / 0.4)
        p.scale(s, s)
        p.setOpacity(min(1.0, t / 0.12 + 0.1))
        p.rotate(-6 * max(0.0, 1 - t / 0.25))
        glow = QColor(accent)
        glow.setAlphaF(0.55)
        p.setFont(self.font(420, QFont.Weight.Black))
        box = QRectF(-600, -400, 1200, 800)
        p.setPen(glow)
        p.drawText(box.translated(0, 10), Qt.AlignmentFlag.AlignCenter, str(f.value))
        p.setPen(self.color("text"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, str(f.value))
        p.restore()

    def _paint_segments(self, p: QPainter, f: CountdownFrame) -> None:
        n = max(1, min(f.total, 60))
        r, width = 310, 34
        gap = 10 if n <= 12 else 4 if n <= 30 else 2  # degrees
        span = 360 / n - gap
        rect = QRectF(CENTER.x() - r, CENTER.y() - r, 2 * r, 2 * r)
        lit = (f.value - f.frac) * n / max(1, f.total)  # segments still on; the current one is fractional
        for i in range(n):
            start = 90 - i * 360 / n - gap / 2  # clockwise from 12 o'clock
            remaining = lit - (n - 1 - i)  # the last segments switch off first
            if remaining >= 1:
                c = self.color("accent")
            elif remaining > 0:
                c = self.color("accent", 0.15 + 0.85 * remaining)
            else:
                c = self.color("text", 0.12)
            pen = QPen(c, width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            p.setPen(pen)
            p.drawArc(rect, int(start * 16), int(-span * 16))
        k = ease_out(f.since_tick / 0.3)
        p.save()
        p.translate(CENTER)
        s = 1.15 - 0.15 * k
        p.scale(s, s)
        self._number(p, str(f.value), QPointF(0, 0), self.font(330, QFont.Weight.Bold), self.color("text"))
        p.restore()
        p.setFont(self.font(30, QFont.Weight.DemiBold, 6))
        p.setPen(self.color("accent", 0.9))
        p.drawText(QRectF(CENTER.x() - 200, CENTER.y() + 150, 400, 50), Qt.AlignmentFlag.AlignCenter, "DETIK")

    # --- fiber optic ----------------------------------------------------------

    def _fiber_layers(self) -> list[QImage]:
        """Stroking ~170 long antialiased curves costs tens of ms, so they are drawn once and only moved per frame."""
        if not self._fiber_cache:
            for layer in range(FIBER_LAYERS):
                img = QImage(REF_W, REF_H, QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(Qt.GlobalColor.transparent)
                lp = QPainter(img)
                lp.setRenderHint(QPainter.RenderHint.Antialiasing)
                lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
                for s in self._strands:
                    if s.layer != layer:
                        continue
                    path = QPainterPath(s.p0)
                    path.cubicTo(s.p1, s.p2, s.p3)
                    c = QColor(FIBER_COLORS[s.color])
                    c.setAlphaF(0.07)
                    lp.setPen(QPen(c, s.width * 5))
                    lp.drawPath(path)
                    c.setAlphaF(0.55 if s.tip else 0.45)
                    lp.setPen(QPen(c, s.width))
                    lp.drawPath(path)
                lp.end()
                self._fiber_cache.append(img)
        return self._fiber_cache

    def _fiber_backdrop(self, p: QPainter, t: float, flash: float) -> None:
        p.save()
        # Deepen the background so the fibers read like light in the dark.
        shade = QLinearGradient(0, 0, 0, REF_H)
        shade.setColorAt(0, QColor(2, 4, 20, 190))
        shade.setColorAt(1, QColor(6, 4, 30, 150))
        p.fillRect(QRectF(0, 0, REF_W, REF_H), shade)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        bright = 0.75 + 0.25 * flash
        offsets = [_layer_offset(i, t) for i in range(FIBER_LAYERS)]
        p.setOpacity(bright)
        for img, off in zip(self._fiber_layers(), offsets, strict=True):
            p.drawImage(off, img)
        p.setOpacity(1)
        for s in self._strands:
            color, off = FIBER_COLORS[s.color], offsets[s.layer]
            if s.pulse >= 0:
                u = (s.pulse + t * s.speed * (0.25 + 0.5 * flash)) % 1.0
                self._glow(p, _bezier((s.p0, s.p1, s.p2, s.p3), u) + off, 22, color, 1.0 - abs(2 * u - 1) ** 3)
            if s.tip:
                twinkle = 0.65 + 0.35 * math.sin(t * 3 + s.phase * 5)
                self._glow(p, s.p3 + off, 22, color, twinkle * bright)
        p.restore()

    def _wire_text(self, p: QPainter, text: str, font: QFont, t: float, energy: float) -> None:
        """Text drawn around the origin as a glowing fiber: halo, translucent core, bright edge and running lights."""
        key = (text, font.pixelSize(), font.family())
        if key not in self._wire_cache:
            if len(self._wire_cache) > 64:
                self._wire_cache.clear()
            # Merge overlapping glyph contours so only the outer edge is wired.
            path = self._text_path(text, font, QPointF(0, 0))
            path.setFillRule(Qt.FillRule.WindingFill)
            path = path.simplified()
            r = path.boundingRect()
            box = r.adjusted(-50, -50, 50, 50)
            img = QImage(int(box.width()) + 1, int(box.height()) + 1, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            wp = QPainter(img)
            wp.setRenderHint(QPainter.RenderHint.Antialiasing)
            wp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            wp.translate(-box.topLeft())
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            for i, color in enumerate(FIBER_COLORS):
                grad.setColorAt(i / (len(FIBER_COLORS) - 1), QColor(color))
            for width, alpha in ((70, 0.05), (40, 0.1), (20, 0.22), (9, 0.5)):
                wp.setOpacity(alpha)
                pen = QPen(grad, width)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                wp.strokePath(path, pen)
            wp.setOpacity(0.35)
            wp.fillPath(path, grad)
            wp.setOpacity(1)
            edge = QPen(QColor(205, 235, 255), 4)
            edge.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            wp.strokePath(path, edge)
            wp.end()
            self._wire_cache[key] = (img, box, path)
        img, box, path = self._wire_cache[key]
        r = path.boundingRect()
        p.save()
        # Dark pool behind the shape keeps it readable over the fibers.
        p.save()
        p.translate(r.center())
        p.scale(r.width() * 0.8 + 100, r.height() * 1.1 + 100)  # unit circle -> ellipse around the text
        pool = QRadialGradient(QPointF(0, 0), 1)
        pool.setColorAt(0, QColor(2, 4, 18, int(200 * energy)))
        pool.setColorAt(0.6, QColor(2, 4, 18, int(120 * energy)))
        pool.setColorAt(1, QColor(2, 4, 18, 0))
        p.fillRect(QRectF(-1, -1, 2, 2), pool)
        p.restore()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setOpacity(p.opacity() * energy)
        p.drawImage(box.topLeft(), img)
        for i in range(10):
            u = (i / 10 + t * 0.18) % 1.0
            self._glow(p, path.pointAtPercent(u), 26, FIBER_COLORS[i % len(FIBER_COLORS)], 1)
        p.restore()

    def _paint_fiber(self, p: QPainter, f: CountdownFrame) -> None:
        t = (f.total - f.value) + f.frac  # seconds since the countdown started
        k = ease_out_back(f.since_tick / 0.45)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Three thin wires around the number that drain with the second, each with a light at its head.
        for i, (radius, color) in enumerate(((318, FIBER_COLORS[1]), (332, FIBER_COLORS[0]), (346, FIBER_COLORS[3]))):
            rect = QRectF(CENTER.x() - radius, CENTER.y() - radius, 2 * radius, 2 * radius)
            c = QColor(color)
            c.setAlphaF(0.12)
            p.setPen(QPen(c, 3))
            p.drawEllipse(rect)
            span = (1 - f.frac) * 360
            for width, alpha in ((16, 0.12), (4, 0.85)):
                c.setAlphaF(alpha)
                pen = QPen(c, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rect, int((90 + i * 7) * 16), int(-span * 16))
            if span > 0:
                a = math.radians(90 + i * 7 - span)
                self._glow(p, QPointF(CENTER.x() + radius * math.cos(a), CENTER.y() - radius * math.sin(a)), 30, color, 1)
        p.restore()

        p.save()
        p.translate(CENTER)
        s = 1.3 - 0.3 * k
        p.scale(s, s)
        self._wire_text(p, str(f.value), self.font(400, QFont.Weight.Black), t, min(1.0, 0.3 + f.since_tick / 0.2))
        p.restore()

    def _fiber_burst(self) -> tuple[QImage, list[tuple[QPointF, str, float]]]:
        """Fibers shooting out from the center, pre-rendered at full reach; returns (image, [(head, color, size)])."""
        if self._burst_cache is None:
            rnd = random.Random(2611)
            img = QImage(REF_W, REF_H, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            bp = QPainter(img)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            bp.translate(REF_W / 2, REF_H / 2)
            heads = []
            for _ in range(120):
                angle = rnd.uniform(0, 2 * math.pi)
                bend = rnd.uniform(-0.3, 0.3)
                color = rnd.choice(FIBER_COLORS)
                start = rnd.uniform(60, 160)
                a0, a1 = QPointF(math.cos(angle), math.sin(angle)), QPointF(math.cos(angle + bend), math.sin(angle + bend))
                # Keep every fiber inside the image, so its edge never shows while the burst is scaled down.
                room = min((REF_W / 2 - 50) / max(1e-3, abs(a1.x())), (REF_H / 2 - 50) / max(1e-3, abs(a1.y())))
                reach = rnd.uniform(0.5, 1.0) * (room - start)
                head = a1 * (start + reach)
                path = QPainterPath(a0 * start)
                path.quadTo(a0 * (start + reach * 0.6), head)
                c = QColor(color)
                c.setAlphaF(0.08)
                bp.setPen(QPen(c, 9))
                bp.drawPath(path)
                c.setAlphaF(0.6)
                bp.setPen(QPen(c, rnd.uniform(1.2, 2.6)))
                bp.drawPath(path)
                heads.append((head, color, rnd.uniform(16, 30)))
            bp.end()
            self._burst_cache = (img, heads)
        return self._burst_cache

    def _fiber_final(self, p: QPainter, text: str, since: float) -> None:
        center = QPointF(REF_W / 2, REF_H / 2)
        burst = 0.08 + 0.92 * ease_out(since / 1.1)
        fade = max(0.0, 1 - max(0.0, since - 1.2) / 1.5)
        if fade > 0:
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            flash = QRadialGradient(center, 1000)
            c = QColor(FIBER_COLORS[1])
            c.setAlphaF(0.4 * max(0.0, 1 - since / 0.5))
            flash.setColorAt(0, c)
            c.setAlphaF(0)
            flash.setColorAt(1, c)
            p.fillRect(QRectF(0, 0, REF_W, REF_H), flash)
            img, heads = self._fiber_burst()
            p.save()
            p.translate(center)
            p.scale(burst, burst)
            p.setOpacity(fade)
            p.drawImage(QPointF(-REF_W / 2, -REF_H / 2), img)
            p.restore()
            for head, color, size in heads:
                self._glow(p, center + head * burst, size, color, fade)
            p.restore()

        p.save()
        p.translate(center)
        s = 0.6 + 0.4 * ease_out_back(since / 0.6)
        p.scale(s, s)
        self._wire_text(p, text, self._fitted_font(text, 200), since, min(1.0, since / 0.25))
        p.restore()
