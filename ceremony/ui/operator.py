"""Operator console: camera preview, live detection status, manual overrides."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..controller import CeremonyController, ClapLogEntry
from ..engine.state import PHASE_LABELS, Event, Phase

PHASE_COLORS = {
    Phase.IDLE: "#64748B",
    Phase.LISTENING: "#2563EB",
    Phase.COUNTDOWN: "#D97706",
    Phase.VIDEO: "#16A34A",
    Phase.FINISHED: "#7C3AED",
}

FUSION_LABELS = {
    "balanced": "Seimbang (kamera, suara bantu)",
    "strict": "Ketat (kamera + suara)",
    "camera": "Kamera saja",
}

STYLE = """
QMainWindow, QWidget#root { background: #0F172A; }
QWidget { color: #E2E8F0; font-size: 13px; }
QGroupBox { border: 1px solid #1E293B; border-radius: 10px; margin-top: 14px; padding: 10px; background: #111C33; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #94A3B8; font-weight: 600; }
QPushButton { background: #1E293B; border: 1px solid #334155; border-radius: 8px; padding: 8px 12px; }
QPushButton:hover { background: #273449; }
QPushButton:pressed { background: #334155; }
QPushButton#primary { background: #2563EB; border-color: #3B82F6; font-weight: 600; }
QPushButton#primary:hover { background: #1D4ED8; }
QPushButton#danger { background: #B91C1C; border-color: #DC2626; font-weight: 600; }
QPushButton#danger:hover { background: #991B1B; }
QProgressBar { border: 1px solid #334155; border-radius: 6px; background: #0B1220; height: 14px; text-align: center; color: #CBD5E1; }
QProgressBar::chunk { background: #E8C468; border-radius: 5px; }
QListWidget { background: #0B1220; border: 1px solid #1E293B; border-radius: 8px; font-family: Menlo, Consolas, monospace; font-size: 12px; }
QComboBox { background: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 4px 8px; }
QLabel#muted { color: #94A3B8; }
QScrollBar:vertical { background: #0B1220; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #334155; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""


class DistanceGraph(QWidget):
    """Last 5 s of palm distance with contact/release thresholds, clap marks and audio onsets."""

    def __init__(self, controller: CeremonyController):
        super().__init__()
        self.c = controller
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor("#1E293B"), 1))
        p.setBrush(QColor("#0B1220"))
        p.drawRoundedRect(r, 8, 8)
        now = self.c.clock()
        span, max_ratio = 5.0, 3.0
        plot = r.adjusted(8, 8, -8, -22)

        def x_of(t: float) -> float:
            return plot.right() - (now - t) / span * plot.width()

        def y_of(v: float) -> float:
            return plot.bottom() - min(v, max_ratio) / max_ratio * plot.height()

        for value, color, label in (
            (self.c.clap.release_ratio, "#64748B", "lepas"),
            (self.c.clap.contact_ratio, "#E8C468", "kontak"),
        ):
            p.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
            y = y_of(value)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.drawText(QPointF(plot.left() + 4, y - 3), label)

        path = QPainterPath()
        started = False
        for t, v in self.c.ratio_history:
            if v is None:
                started = False
                continue
            pt = QPointF(x_of(t), y_of(v))
            if started:
                path.lineTo(pt)
            else:
                path.moveTo(pt)
                started = True
        p.setPen(QPen(QColor("#38BDF8"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        for t, accepted in self.c.clap_marks:
            p.setPen(QPen(QColor("#22C55E" if accepted else "#EF4444"), 2))
            x = x_of(t)
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#A78BFA"))
        for t in self.c.audio_onsets:
            p.drawEllipse(QPointF(x_of(t), r.bottom() - 11), 4, 4)

        p.setPen(QColor("#64748B"))
        f = p.font()
        f.setPixelSize(10)
        p.setFont(f)
        p.drawText(QRectF(r.left() + 8, r.bottom() - 18, r.width() - 16, 14), Qt.AlignmentFlag.AlignRight,
                   "biru = jarak telapak · ungu = bunyi tepukan · hijau/merah = clap diterima/ditolak")  # fmt: skip
        p.end()


class LevelMeter(QProgressBar):
    def __init__(self):
        super().__init__()
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.setStyleSheet("QProgressBar::chunk { background: #A78BFA; }")

    def set_db(self, db: float) -> None:
        self.setValue(int(max(0, min(100, (db + 70) / 70 * 100))))


class OperatorWindow(QMainWindow):
    def __init__(self, controller: CeremonyController, stage, open_settings):
        super().__init__()
        self.c = controller
        self.stage = stage
        self.open_settings = open_settings
        self.setWindowTitle("Grand Opening — Operator")
        self.setStyleSheet(STYLE)
        self.resize(1280, 800)

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Left: camera + diagnostics
        left = QVBoxLayout()
        self.preview = QLabel("Menyiapkan kamera…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(560, 315)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background: #020617; border-radius: 10px; color: #64748B;")
        left.addWidget(self.preview, 1)
        self.hands_label = QLabel(objectName="muted")
        left.addWidget(self.hands_label)
        self.graph = DistanceGraph(controller)
        left.addWidget(self.graph)
        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("Mic", objectName="muted"))
        self.level = LevelMeter()
        mic_row.addWidget(self.level, 1)
        left.addLayout(mic_row)
        self.camera_status = QLabel("Kamera: memuat…", objectName="muted")
        self.mic_status = QLabel("Mic: memuat…", objectName="muted")
        self.video_status = QLabel(objectName="muted")
        for w in (self.camera_status, self.mic_status, self.video_status):
            w.setWordWrap(True)
            left.addWidget(w)
        layout.addLayout(left, 3)

        # Right: state + controls
        right = QVBoxLayout()
        right.setSpacing(10)

        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPixelSize(26)
        f.setBold(True)
        self.phase_label.setFont(f)
        self.phase_label.setMinimumHeight(64)
        right.addWidget(self.phase_label)

        status = QGroupBox("Deteksi")
        grid = QGridLayout(status)
        self.hi_five_bar = QProgressBar(maximum=100, format="🙌 Hi-five %p%")
        self.reset_bar = QProgressBar(maximum=100, format="✊ Reset %p%")
        self.reset_bar.setStyleSheet("QProgressBar::chunk { background: #EF4444; }")
        self.clap_label = QLabel()
        f2 = QFont()
        f2.setPixelSize(30)
        f2.setBold(True)
        self.clap_label.setFont(f2)
        self.clap_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeout_bar = QProgressBar(maximum=1000, textVisible=False)
        self.timeout_bar.setFixedHeight(6)
        self.timeout_bar.setStyleSheet("QProgressBar::chunk { background: #2563EB; }")
        self.fusion_combo = QComboBox()
        for key, label in FUSION_LABELS.items():
            self.fusion_combo.addItem(label, key)
        self.fusion_combo.currentIndexChanged.connect(self._fusion_changed)
        grid.addWidget(self.hi_five_bar, 0, 0, 1, 2)
        grid.addWidget(self.reset_bar, 1, 0, 1, 2)
        grid.addWidget(self.clap_label, 2, 0, 1, 2)
        grid.addWidget(self.timeout_bar, 3, 0, 1, 2)
        grid.addWidget(QLabel("Konfirmasi clap", objectName="muted"), 4, 0)
        grid.addWidget(self.fusion_combo, 4, 1)
        right.addWidget(status)

        log_box = QGroupBox("Log tepukan")
        log_layout = QVBoxLayout(log_box)
        self.log = QListWidget()
        self.log.setMinimumHeight(120)
        log_layout.addWidget(self.log)
        right.addWidget(log_box, 1)

        controls = QGroupBox("Kontrol (berlaku kapan saja)")
        cg = QGridLayout(controls)
        self.advance_btn = QPushButton("▶  Lanjut  [Space]", objectName="primary")
        self.reset_btn = QPushButton("⟲  Reset  [Esc]", objectName="danger")
        self.advance_btn.clicked.connect(controller.advance)
        self.reset_btn.clicked.connect(controller.reset)
        cg.addWidget(self.advance_btn, 0, 0)
        cg.addWidget(self.reset_btn, 0, 1)
        sim = [("🙌 Hi-five [H]", controller.simulate_hi_five), ("👏 Clap [C]", controller.simulate_clap),
               ("✊ Batu [B]", controller.simulate_fist)]  # fmt: skip
        sim_row = QHBoxLayout()
        sim_row.addWidget(QLabel("Simulasi:", objectName="muted"))
        for text, fn in sim:
            b = QPushButton(text)
            b.clicked.connect(fn)
            sim_row.addWidget(b)
        cg.addLayout(sim_row, 1, 0, 1, 2)
        right.addWidget(controls)

        tools = QHBoxLayout()
        settings_btn = QPushButton("⚙  Pengaturan")
        settings_btn.clicked.connect(open_settings)
        self.calib_btn = QPushButton("🎯  Kalibrasi audio")
        self.calib_btn.clicked.connect(self._calibrate)
        stage_btn = QPushButton("🖥  Fullscreen stage [F]")
        stage_btn.clicked.connect(stage.toggle_fullscreen)
        for b in (settings_btn, self.calib_btn, stage_btn):
            tools.addWidget(b)
        right.addLayout(tools)
        hint = QLabel("Data: " + str(controller.store.data_dir), objectName="muted")
        hint.setWordWrap(True)
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(hint)
        layout.addLayout(right, 2)

        controller.preview.connect(self._on_preview)
        controller.updated.connect(self._refresh)
        controller.phase_changed.connect(lambda _: self._refresh_phase())
        controller.engine_event.connect(self._on_event)
        controller.clap_logged.connect(self._on_clap)
        controller.camera_status.connect(lambda ok, t: self._status(self.camera_status, ok, t))
        controller.mic_status.connect(lambda ok, t: self._status(self.mic_status, ok, t))
        controller.message.connect(lambda t: self.statusBar().showMessage(t, 6000))
        controller.calibration_finished.connect(self._calibration_done)
        controller.settings_changed.connect(self._sync_settings)
        self.statusBar().setStyleSheet("color: #E8C468;")
        for button in self.findChildren(QPushButton):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fusion_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._pixmap: QPixmap | None = None
        self._sync_settings()
        self._refresh_phase()
        self._phase_timer = QTimer(self)
        self._phase_timer.timeout.connect(self._refresh_phase)
        self._phase_timer.start(500)

    # --- updates --------------------------------------------------------------

    def _on_preview(self, img: QImage) -> None:
        self._pixmap = QPixmap.fromImage(img)
        self.preview.setPixmap(self._pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation))  # fmt: skip

    def _status(self, label: QLabel, ok: bool, text: str) -> None:
        label.setText(("🟢 " if ok else "🔴 ") + text)

    def _sync_settings(self) -> None:
        mode = self.c.settings.clap.fusion_mode
        self.fusion_combo.blockSignals(True)
        self.fusion_combo.setCurrentIndex(max(0, self.fusion_combo.findData(mode)))
        self.fusion_combo.blockSignals(False)
        path, auto = self.c.active_video()
        if path and auto:
            self._status(self.video_status, True, f"Video: {path.name} (dipilih otomatis: unggahan terbaru — "
                         "pilih ★ di Pengaturan › Video untuk memastikan)")  # fmt: skip
        elif path:
            self._status(self.video_status, True, f"Video: {path.name}")
        else:
            self._status(self.video_status, False, "Video: belum ada — tambahkan di Pengaturan › Video; "
                         "tanpa video, setelah countdown langsung ke layar penutup")  # fmt: skip

    def _fusion_changed(self) -> None:
        new = self.c.settings.copy()
        new.clap.fusion_mode = self.fusion_combo.currentData()
        self.c.apply_settings(new)

    def _refresh_phase(self) -> None:
        e = self.c.engine
        color = PHASE_COLORS[e.phase]
        elapsed = int(self.c.clock() - e.phase_since) if e.phase_since else 0
        self.phase_label.setText(f"{PHASE_LABELS[e.phase].upper()}   ·   {elapsed // 60:02d}:{elapsed % 60:02d}")
        self.phase_label.setStyleSheet(f"background: {color}; border-radius: 12px; color: white;")

    def _refresh(self) -> None:
        now = self.c.clock()
        c, e = self.c, self.c.engine
        self.hi_five_bar.setValue(int(c.hi_five_hold.progress(now) * 100))
        self.reset_bar.setValue(int(c.reset_hold.progress(now) * 100))
        need = e.required_claps
        if e.phase == Phase.LISTENING:
            self.clap_label.setText(f"👏  {e.clap_count} / {need}")
            timeout = c.settings.gesture.listening_timeout_s
            self.timeout_bar.setValue(int(e.listening_remaining(now) / timeout * 1000) if timeout else 0)
        else:
            self.clap_label.setText(f"👏  – / {need}")
            self.timeout_bar.setValue(0)
        ratio = c.ratio_history[-1][1] if c.ratio_history else None
        shapes = ", ".join(c.target_shapes) or "–"
        dist = f"{ratio:.2f}" if ratio is not None else "–"
        self.hands_label.setText(
            f"Tangan terlihat: {c.hands_visible}  ·  target: {c.target_count} ({shapes})  ·  "
            f"jarak: {dist}  ·  {c.camera_fps:.0f} FPS"
        )
        self.level.set_db(c.mic_level if c.mic.ok else -120)
        self.graph.update()

    def _on_event(self, ev: Event) -> None:
        if ev.kind == "clap_reset":
            self._log("↺ hitungan clap direset (terlalu lama)", "#F59E0B")
        elif ev.kind == "phase":
            src = f" ({ev.source})" if ev.source else ""
            self._log(f"→ {PHASE_LABELS[ev.phase]}{src}", PHASE_COLORS[ev.phase])

    def _on_clap(self, entry: ClapLogEntry) -> None:
        if entry.simulated:
            text = "👏 SIMULASI " + ("dihitung" if entry.counted else "diabaikan (bukan tahap listening)")
            self._log(text, "#38BDF8")
            return
        eye = "👁 jelas" if entry.strong else "👁 ragu"
        ear = "🔊 ya" if entry.audio else "🔇 tidak"
        if entry.accepted and entry.counted:
            head, color = "✓ DIHITUNG", "#22C55E"
        elif entry.accepted:
            head, color = "· terdeteksi (bukan tahap listening)", "#64748B"
        else:
            head, color = "✗ DITOLAK", "#EF4444"
        self._log(f"{head}  {eye} · {ear} — {entry.reason}", color)

    def _log(self, text: str, color: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        item = QListWidgetItem(f"{stamp}  {text}")
        item.setForeground(QColor(color))
        self.log.insertItem(0, item)
        while self.log.count() > 200:
            self.log.takeItem(self.log.count() - 1)

    # --- calibration ----------------------------------------------------------

    def _calibrate(self) -> None:
        if self.c.calibrator:
            self.c.cancel_calibration()
            self.calib_btn.setText("🎯  Kalibrasi audio")
            return
        if not self.c.mic.ok:
            QMessageBox.warning(self, "Kalibrasi audio", "Mikrofon belum aktif. Pilih mode Seimbang/Ketat dan cek perangkat mic.")
            return
        self.c.start_calibration()
        self.calib_btn.setText("✕  Batal kalibrasi")

    def _calibration_done(self, result) -> None:
        self.calib_btn.setText("🎯  Kalibrasi audio")
        if result is None:
            QMessageBox.warning(self, "Kalibrasi audio", "Tidak ada pasangan tepukan kamera + suara yang cocok.")
        else:
            QMessageBox.information(
                self,
                "Kalibrasi audio",
                f"Selisih kamera vs mic: {result} ms.\nNilai ini sudah disimpan ke pengaturan.",
            )

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._pixmap is not None:
            self.preview.setPixmap(self._pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))  # fmt: skip

    def closeEvent(self, ev):
        if QMessageBox.question(self, "Keluar", "Tutup aplikasi Grand Opening?") != QMessageBox.StandardButton.Yes:
            ev.ignore()
            return
        ev.accept()
        self.stage.close()

