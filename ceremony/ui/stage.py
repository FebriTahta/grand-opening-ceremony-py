"""The audience-facing screen: title, gesture prompts, countdown and the opening video."""

from __future__ import annotations

import logging
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QStackedLayout, QWidget

from ..controller import CeremonyController
from ..engine.state import Event, Phase
from .countdown_styles import CountdownFrame, CountdownPainter

log = logging.getLogger("ceremony.video")
REF_W, REF_H = 1920, 1080
FIRST_FRAME_TIMEOUT_S = 5.0
WRAP_CENTER = int(Qt.AlignmentFlag.AlignHCenter.value | Qt.TextFlag.TextWordWrap.value)


def _ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "size", "life", "max_life", "color", "spin")

    def __init__(self, x, y, vx, vy, size, life, color, spin=0.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.size, self.life, self.max_life, self.color, self.spin = size, life, life, color, spin


class StageCanvas(QWidget):
    """Everything except the video itself is painted here, in 1920×1080 reference units."""

    def __init__(self, controller: CeremonyController, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.frozen: QImage | None = None
        self.phase_anim_start = controller.clock()
        self.clap_anim_start = 0.0
        self.tick_anim_start = 0.0
        self.sparkles: list[Particle] = []
        self.confetti: list[Particle] = []
        self._last_step = time.perf_counter()
        self._bg_cache: tuple[str, QImage | None] = ("", None)
        self._logo_cache: tuple[str, QImage | None] = ("", None)
        self.countdown = CountdownPainter(lambda: self.c.settings.appearance)
        for _ in range(70):
            self.sparkles.append(self._new_sparkle(random.uniform(0, REF_H)))

        timer = QTimer(self)
        timer.setInterval(16)
        timer.timeout.connect(self._step)
        timer.start()

    # --- events from the controller ------------------------------------------

    def on_event(self, ev: Event) -> None:
        now = self.c.clock()
        if ev.kind == "phase":
            self.phase_anim_start = now
            if self.c.engine.phase in (Phase.IDLE, Phase.LISTENING):
                cd = self.c.settings.countdown
                self.countdown.prepare(cd.style, cd.seconds, self.c.settings.text.countdown_final_text)
        elif ev.kind == "clap":
            self.clap_anim_start = now
            self._burst(REF_W / 2, REF_H * 0.62, 40, speed=520)
        elif ev.kind == "tick":
            self.tick_anim_start = now
            if ev.value == 0:
                self._burst(REF_W / 2, REF_H / 2, 260, speed=1100)

    # --- animation ------------------------------------------------------------

    def _new_sparkle(self, y: float | None = None) -> Particle:
        accent = QColor(self.c.settings.appearance.accent_color)
        return Particle(
            random.uniform(0, REF_W),
            REF_H + 20 if y is None else y,
            random.uniform(-8, 8),
            random.uniform(-40, -14),
            random.uniform(1.5, 4.5),
            random.uniform(8, 20),
            accent,
        )

    def _burst(self, x: float, y: float, n: int, speed: float) -> None:
        a = self.c.settings.appearance
        palette = [QColor(a.accent_color), QColor(a.text_color), QColor("#FF6B6B"), QColor("#4ECDC4"), QColor("#FFD93D")]
        for _ in range(n):
            ang = random.uniform(0, 2 * math.pi)
            v = random.uniform(0.3, 1.0) * speed
            self.confetti.append(
                Particle(x, y, math.cos(ang) * v, math.sin(ang) * v - speed * 0.3, random.uniform(6, 14),
                         random.uniform(1.6, 3.2), random.choice(palette), random.uniform(-8, 8))
            )  # fmt: skip

    def _step(self) -> None:
        now = time.perf_counter()
        dt = min(0.05, now - self._last_step)
        self._last_step = now
        for p in self.sparkles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt
        self.sparkles = [p if p.life > 0 and p.y > -20 else self._new_sparkle() for p in self.sparkles]
        for p in self.confetti:
            p.vy += 900 * dt
            p.vx *= 1 - 1.2 * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt
        self.confetti = [p for p in self.confetti if p.life > 0 and p.y < REF_H + 40]
        if self.isVisible():
            self.update()

    # --- painting helpers -----------------------------------------------------

    def _font(self, px: float, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0) -> QFont:
        return self.countdown.font(px, weight, spacing)

    def _text(self, p: QPainter, text: str, y: float, font: QFont, color: QColor, max_w: float = REF_W - 200,
              opacity: float = 1.0) -> float:  # fmt: skip
        """Draws centered, word-wrapped text starting at y. Returns the height used."""
        if not text:
            return 0.0
        p.setFont(font)
        rect = QRectF((REF_W - max_w) / 2, y, max_w, REF_H)
        bound = QFontMetricsF(font).boundingRect(QRectF(0, 0, max_w, REF_H), WRAP_CENTER, text)
        p.save()
        p.setOpacity(opacity)
        shadow = QColor(0, 0, 0, 110)
        p.setPen(shadow)
        p.drawText(rect.translated(0, 3), Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, text)
        p.setPen(color)
        p.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, text)
        p.restore()
        return bound.height()

    def _image(self, kind: str) -> QImage | None:
        a = self.c.settings.appearance
        name = a.background_image if kind == "bg" else a.logo_image
        cache = self._bg_cache if kind == "bg" else self._logo_cache
        if cache[0] != name:
            path = self.c.store.asset_path(name)
            img = QImage(str(path)) if path else None
            cache = (name, img if img and not img.isNull() else None)
            if kind == "bg":
                self._bg_cache = cache
            else:
                self._logo_cache = cache
        return cache[1]

    # --- painting -------------------------------------------------------------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        scale = min(self.width() / REF_W, self.height() / REF_H)
        p.translate((self.width() - REF_W * scale) / 2, (self.height() - REF_H * scale) / 2)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, REF_W, REF_H))

        now = self.c.clock()
        phase = self.c.engine.phase
        video = self.c.settings.video
        if phase in (Phase.VIDEO, Phase.FINISHED) and self.frozen is not None and video.after_video != "closing":
            self._paint_frozen(p)
            if video.closing_text_on_freeze or phase == Phase.VIDEO:
                self._paint_closing_overlay(p, now)
        else:
            self._paint_background(p)
            {
                Phase.IDLE: self._paint_idle,
                Phase.LISTENING: self._paint_listening,
                Phase.COUNTDOWN: self._paint_countdown,
                Phase.VIDEO: self._paint_countdown,  # shown until the first video frame arrives
                Phase.FINISHED: self._paint_closing,
            }[phase](p, now)
        self._paint_confetti(p)
        p.end()

    def _paint_background(self, p: QPainter) -> None:
        a = self.c.settings.appearance
        bg = self._image("bg")
        if bg is not None:
            s = max(REF_W / bg.width(), REF_H / bg.height())
            w, h = bg.width() * s, bg.height() * s
            p.drawImage(QRectF((REF_W - w) / 2, (REF_H - h) / 2, w, h), bg)
            p.fillRect(QRectF(0, 0, REF_W, REF_H), QColor(0, 0, 0, 90))
        else:
            g = QLinearGradient(0, 0, REF_W, REF_H)
            g.setColorAt(0, QColor(a.background_color))
            g.setColorAt(1, QColor(a.background_color_2))
            p.fillRect(QRectF(0, 0, REF_W, REF_H), g)
        glow = QRadialGradient(REF_W / 2, REF_H * 0.45, REF_W * 0.5)
        accent = QColor(a.accent_color)
        accent.setAlpha(45)
        glow.setColorAt(0, accent)
        accent.setAlpha(0)
        glow.setColorAt(1, accent)
        p.fillRect(QRectF(0, 0, REF_W, REF_H), glow)
        p.setPen(Qt.PenStyle.NoPen)
        for s in self.sparkles:
            c = QColor(s.color)
            c.setAlphaF(0.55 * min(1.0, s.life / 3) * (0.6 + 0.4 * math.sin(s.life * 3)))
            p.setBrush(c)
            p.drawEllipse(QPointF(s.x, s.y), s.size, s.size)

    def _paint_header(self, p: QPainter, top: float, compact: bool = False) -> float:
        """Logo, event name, title, subtitle. Returns the y below the block."""
        a, t = self.c.settings.appearance, self.c.settings.text
        accent, fg = QColor(a.accent_color), QColor(a.text_color)
        y = top
        logo = self._image("logo")
        if logo is not None:
            h = 110 if compact else 170
            w = logo.width() * h / logo.height()
            if w > 700:
                w, h = 700, logo.height() * 700 / logo.width()
            p.drawImage(QRectF((REF_W - w) / 2, y, w, h), logo)
            y += h + 36
        y += self._text(p, t.event_name, y, self._font(30 if compact else 40, QFont.Weight.DemiBold, 10), accent) + 14
        if t.title:
            y += self._text(p, t.title, y, self._font(64 if compact else 104, QFont.Weight.Bold), fg) + 10
        if t.subtitle and not compact:
            sub = QColor(fg)
            sub.setAlphaF(0.75)
            y += self._text(p, t.subtitle, y, self._font(38), sub)
        return y

    def _pill(self, p: QPainter, text: str, cy: float, icon: str = "", opacity: float = 1.0) -> None:
        a = self.c.settings.appearance
        font = self._font(40, QFont.Weight.Medium)
        fm = QFontMetricsF(font)
        label = f"{icon}  {text}" if icon else text
        w = min(REF_W - 160, fm.horizontalAdvance(label) + 110)
        rect = QRectF((REF_W - w) / 2, cy - 48, w, 96)
        p.save()
        p.setOpacity(opacity)
        bg = QColor(a.text_color)
        bg.setAlpha(28)
        border = QColor(a.accent_color)
        border.setAlpha(150)
        p.setBrush(bg)
        p.setPen(QPen(border, 2))
        p.drawRoundedRect(rect, 48, 48)
        p.setFont(font)
        p.setPen(QColor(a.text_color))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        p.restore()

    def _ring(self, p: QPainter, center: QPointF, radius: float, progress: float, width: float = 12) -> None:
        self.countdown.ring(p, center, radius, progress, width)

    def _paint_idle(self, p: QPainter, now: float) -> None:
        self._paint_header(p, 170)
        if not self.c.settings.appearance.show_gesture_hints:
            return
        progress = self.c.hi_five_hold.progress(now)
        center = QPointF(REF_W / 2, 790)
        breathe = 1 + 0.04 * math.sin(now * 2.4)
        self._ring(p, center, 74 * breathe, progress, 10)
        p.setFont(self._font(80))
        p.setPen(QColor(self.c.settings.appearance.text_color))
        p.drawText(QRectF(center.x() - 100, center.y() - 100, 200, 200), Qt.AlignmentFlag.AlignCenter, "🙌")
        self._pill(p, self.c.settings.text.idle_instruction, 960, opacity=0.75 + 0.25 * math.sin(now * 2.4))

    def _paint_listening(self, p: QPainter, now: float) -> None:
        a, t = self.c.settings.appearance, self.c.settings.text
        intro = _ease_out((now - self.phase_anim_start) / 0.6)
        self._paint_header(p, 120, compact=True)
        need = self.c.engine.required_claps
        count = self.c.engine.clap_count

        p.save()
        p.setOpacity(intro)
        icon_y = 560 - 30 * (1 - intro)
        pop = 1 + 0.35 * (1 - _ease_out((now - self.clap_anim_start) / 0.35))
        p.setFont(self._font(150 * pop))
        p.setPen(QColor(a.text_color))
        p.drawText(QRectF(0, icon_y - 120, REF_W, 240), Qt.AlignmentFlag.AlignCenter, "👏")

        # Clap dots.
        r, gap = 34, 48
        total_w = need * 2 * r + (need - 1) * gap
        x0 = (REF_W - total_w) / 2 + r
        for i in range(need):
            cx = x0 + i * (2 * r + gap)
            c = QPointF(cx, 760)
            filled = i < count
            just = filled and i == count - 1
            k = 1 + (0.5 * (1 - _ease_out((now - self.clap_anim_start) / 0.4)) if just else 0)
            if filled:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(a.accent_color))
                p.drawEllipse(c, r * k, r * k)
                if just:
                    ripple = _ease_out((now - self.clap_anim_start) / 0.6)
                    rc = QColor(a.accent_color)
                    rc.setAlphaF(max(0.0, 1 - ripple))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(rc, 4))
                    p.drawEllipse(c, r + 50 * ripple, r + 50 * ripple)
            else:
                outline = QColor(a.text_color)
                outline.setAlpha(120)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(outline, 4))
                p.drawEllipse(c, r, r)
        p.restore()

        text = t.listening_instruction.replace("{count}", str(need))
        self._pill(p, text, 940, opacity=intro)

    def _paint_countdown(self, p: QPainter, now: float) -> None:
        t, cd = self.c.settings.text, self.c.settings.countdown
        e = self.c.engine
        value = e.countdown_value(now) if e.phase == Phase.COUNTDOWN else 0
        since_tick = now - self.tick_anim_start
        self.countdown.paint_backdrop(p, cd.style, now, max(0.0, 1 - since_tick / (0.5 if value > 0 else 1.5)))
        self._text(p, t.event_name, 70, self._font(32, QFont.Weight.DemiBold, 10), self.countdown.color("accent"))
        if value > 0:
            self._text(p, t.countdown_label, 170, self._font(46, QFont.Weight.Medium), self.countdown.color("text", 0.8))
            elapsed = now - e.phase_since
            frame = CountdownFrame(value, max(1, cd.seconds), elapsed - math.floor(elapsed), since_tick)
            self.countdown.paint(p, cd.style, frame)
        else:
            self.countdown.paint_final(p, t.countdown_final_text, since_tick, cd.style)

    def _paint_closing(self, p: QPainter, now: float) -> None:
        a, t = self.c.settings.appearance, self.c.settings.text
        intro = _ease_out((now - self.phase_anim_start) / 0.8)
        y = 260
        logo = self._image("logo")
        if logo is not None:
            h = 150
            w = logo.width() * h / logo.height()
            p.drawImage(QRectF((REF_W - w) / 2, 140, w, h), logo)
            y = 340
        y += self._text(p, t.event_name, y + 40, self._font(40, QFont.Weight.DemiBold, 10), QColor(a.accent_color), opacity=intro) + 70
        y += self._text(p, t.closing_title, y, self._font(130, QFont.Weight.Black), QColor(a.text_color), opacity=intro) + 20
        y += self._text(p, t.title, y, self._font(56, QFont.Weight.Medium), QColor(a.text_color), opacity=intro) + 30
        sub = QColor(a.text_color)
        sub.setAlphaF(0.75)
        self._text(p, t.closing_subtitle, y, self._font(40), sub, opacity=intro)

    def _paint_frozen(self, p: QPainter) -> None:
        img = self.frozen
        assert img is not None
        s = min(REF_W / img.width(), REF_H / img.height())
        w, h = img.width() * s, img.height() * s
        p.drawImage(QRectF((REF_W - w) / 2, (REF_H - h) / 2, w, h), img)

    def _paint_closing_overlay(self, p: QPainter, now: float) -> None:
        if self.c.engine.phase != Phase.FINISHED:
            return
        a, t = self.c.settings.appearance, self.c.settings.text
        intro = _ease_out((now - self.phase_anim_start) / 1.0)
        g = QLinearGradient(0, REF_H * 0.45, 0, REF_H)
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, int(200 * intro)))
        p.fillRect(QRectF(0, REF_H * 0.45, REF_W, REF_H * 0.55), g)
        y = REF_H - 300 + 30 * (1 - intro)
        y += self._text(p, t.closing_title, y, self._font(100, QFont.Weight.Black), QColor(a.text_color), opacity=intro) + 10
        sub = QColor(a.text_color)
        sub.setAlphaF(0.8)
        self._text(p, t.closing_subtitle, y, self._font(40), sub, opacity=intro)

    def _paint_confetti(self, p: QPainter) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        for c in self.confetti:
            col = QColor(c.color)
            col.setAlphaF(max(0.0, min(1.0, c.life / 0.8)))
            p.save()
            p.translate(c.x, c.y)
            p.rotate(c.spin * (c.max_life - c.life) * 40)
            p.setBrush(col)
            path = QPainterPath()
            path.addRect(QRectF(-c.size / 2, -c.size / 4, c.size, c.size / 2))
            p.drawPath(path)
            p.restore()


class StageWindow(QWidget):
    video_ended = Signal()

    def __init__(self, controller: CeremonyController):
        super().__init__()
        self.c = controller
        self.setWindowTitle("Grand Opening — Stage")
        self.setStyleSheet("background: black;")
        self.resize(1280, 720)

        self.canvas = StageCanvas(controller)
        self.video = QVideoWidget()
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.video)

        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_error)
        self.video.videoSink().videoFrameChanged.connect(self._on_frame)
        self.last_frame: QVideoFrame | None = None
        self.loaded_source = ""
        self.force_windowed = False
        self.media_held = False  # True while the settings dialog may delete/replace video files
        self.waiting_first_frame = False
        self.play_requested_at = 0.0

        self.watchdog = QTimer(self)
        self.watchdog.setInterval(250)
        self.watchdog.timeout.connect(self._check_watchdog)
        self.watchdog.start()

        controller.engine_event.connect(self.canvas.on_event)
        controller.phase_changed.connect(self._on_phase)
        controller.settings_changed.connect(self.preload)
        self.video_ended.connect(controller.video_ended)

        QShortcut(QKeySequence("F"), self, self.toggle_fullscreen)
        self.preload()

    # --- window ---------------------------------------------------------------

    def place(self) -> None:
        screens = QGuiApplication.screens()
        idx = self.c.settings.device.stage_screen
        screen = screens[idx] if -len(screens) <= idx < len(screens) else screens[-1]
        self.setScreen(screen)
        self.move(screen.geometry().topLeft())
        if self.c.settings.device.stage_fullscreen and not self.force_windowed:
            self.setGeometry(screen.geometry())
            self.showFullScreen()
        else:
            self.resize(1280, 720)
            self.move(screen.geometry().center() - self.rect().center())
            self.showNormal()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        # Hide the mouse pointer only when the stage is on the projector.
        self.setCursor(Qt.CursorShape.BlankCursor if self.isFullScreen() else Qt.CursorShape.ArrowCursor)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.resize(1280, 720)
        else:
            self.showFullScreen()

    # --- video ----------------------------------------------------------------

    def preload(self) -> None:
        """Load the active video ahead of time so playback starts instantly."""
        v = self.c.settings.video
        self.audio.setVolume(v.volume)
        if self.media_held:
            return
        self.player.setLoops(QMediaPlayer.Loops.Infinite if v.after_video == "loop" else 1)
        path, _ = self.c.active_video()
        source = str(path) if path else ""
        if source == self.loaded_source:
            return
        self.loaded_source = source
        if self.c.engine.phase == Phase.VIDEO:
            return  # don't swap the source under a running video; it'll apply after reset
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(source) if source else QUrl())
        log.info("video dimuat: %s", source or "(tidak ada)")

    def release_media(self) -> bool:
        """Close the preloaded file so it can be replaced or deleted (Windows locks open files).

        Returns False while a video is playing; it is never interrupted."""
        if self.c.engine.phase == Phase.VIDEO:
            return False
        self.media_held = True
        self.player.stop()
        self.player.setSource(QUrl())
        self.loaded_source = ""
        return True

    def resume_media(self) -> None:
        self.media_held = False
        self.preload()

    def _on_phase(self, phase: Phase) -> None:
        if phase == Phase.VIDEO:
            self.canvas.frozen = None
            self.last_frame = None
            self.waiting_first_frame = True
            self.play_requested_at = time.perf_counter()
            if not self.loaded_source:
                self.preload()
            log.info("memutar video: %s", self.loaded_source or "(tidak ada)")
            self.player.setPosition(0)
            self.player.play()
        elif phase == Phase.FINISHED:
            self._freeze()
            if self.c.settings.video.after_video == "loop" and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.stop()
            self.stack.setCurrentWidget(self.canvas)
        else:
            self.waiting_first_frame = False
            self.player.stop()
            self.canvas.frozen = None
            self.stack.setCurrentWidget(self.canvas)
            if phase == Phase.IDLE:
                self.loaded_source = ""
                self.preload()

    def _on_frame(self, frame: QVideoFrame) -> None:
        if not frame.isValid():
            return
        self.last_frame = frame
        if self.waiting_first_frame and self.c.engine.phase == Phase.VIDEO:
            self.waiting_first_frame = False
            self.stack.setCurrentWidget(self.video)
            log.info("frame video pertama tampil setelah %.2f s", time.perf_counter() - self.play_requested_at)

    def _freeze(self) -> None:
        if self.c.settings.video.after_video in ("freeze", "loop") and self.last_frame is not None:
            img = self.last_frame.toImage()
            self.canvas.frozen = img if not img.isNull() else None
        else:
            self.canvas.frozen = None

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            log.info("status media: %s", status.name)
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.c.engine.phase == Phase.VIDEO:
            self.video_ended.emit()

    def _on_error(self, error, text: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        log.error("video error: %s (%s)", text, error)
        self.c.message.emit(f"Video error: {text}")
        if self.c.engine.phase == Phase.VIDEO:
            self.video_ended.emit()

    def _check_watchdog(self) -> None:
        # Never leave the audience staring at a frozen countdown if the video won't start.
        if self.waiting_first_frame and time.perf_counter() - self.play_requested_at > FIRST_FRAME_TIMEOUT_S:
            self.waiting_first_frame = False
            log.error("video tidak mulai dalam %.0f s — lanjut ke layar penutup", FIRST_FRAME_TIMEOUT_S)
            self.c.message.emit("Video tidak mulai dalam 5 detik — lanjut ke layar penutup")
            self.player.stop()
            self.video_ended.emit()
