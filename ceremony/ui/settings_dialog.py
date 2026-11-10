"""Settings editor. Works on a copy; nothing changes until "Simpan"."""

from __future__ import annotations

import math
import shutil
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio.mic import list_input_devices
from ..config import AppearanceSettings, Settings, Store
from .countdown_styles import REF_H, REF_W, STYLE_HINTS, STYLES, CountdownFrame, CountdownPainter
from .operator import FUSION_LABELS, STYLE

VIDEO_FILTER = "Video (*.mp4 *.mov *.m4v *.mkv *.webm *.avi)"
IMAGE_FILTER = "Gambar (*.png *.jpg *.jpeg *.webp *.bmp)"


def _copy_with_progress(parent: QWidget, src: Path, dst: Path) -> bool:
    total = max(1, src.stat().st_size)
    dlg = QProgressDialog(f"Menyalin {src.name}…", "Batal", 0, 1000, parent)
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(300)
    done = 0
    try:
        with src.open("rb") as fi, dst.open("wb") as fo:
            while chunk := fi.read(8 * 1024 * 1024):
                fo.write(chunk)
                done += len(chunk)
                dlg.setValue(int(done / total * 1000))
                QApplication.processEvents()
                if dlg.wasCanceled():
                    raise InterruptedError
        shutil.copystat(src, dst)
        return True
    except (OSError, InterruptedError):
        dst.unlink(missing_ok=True)
        return False
    finally:
        dlg.close()


def _unique_name(directory: Path, name: str) -> str:
    candidate = name
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while (directory / candidate).exists():
        candidate = f"{stem} ({i}){suffix}"
        i += 1
    return candidate


class CountdownPreview(QWidget):
    """Loops a short 3-2-1 countdown in the chosen style, drawn exactly as on the stage."""

    LOOP_SECONDS = 3
    FINAL_SECONDS = 2.5

    def __init__(self, appearance: AppearanceSettings, final_text: str):
        super().__init__()
        self.appearance = appearance
        self.final_text = final_text
        self.style = "ring"
        self.painter = CountdownPainter(lambda: self.appearance)
        self.start = time.perf_counter()
        self.setMinimumHeight(260)
        timer = QTimer(self)
        timer.timeout.connect(self.update)
        timer.start(16)

    def set_style(self, style: str) -> None:
        self.style = style
        self.start = time.perf_counter()  # restart so the change is visible from "3"

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor("#020617"))
        scale = min(self.width() / REF_W, self.height() / REF_H)
        p.translate((self.width() - REF_W * scale) / 2, (self.height() - REF_H * scale) / 2)
        p.scale(scale, scale)
        g = QLinearGradient(0, 0, REF_W, REF_H)
        g.setColorAt(0, QColor(self.appearance.background_color))
        g.setColorAt(1, QColor(self.appearance.background_color_2))
        p.fillRect(QRectF(0, 0, REF_W, REF_H), g)

        t = (time.perf_counter() - self.start) % (self.LOOP_SECONDS + self.FINAL_SECONDS)
        since = t - math.floor(t) if t < self.LOOP_SECONDS else t - self.LOOP_SECONDS
        flash = max(0.0, 1 - since / (0.5 if t < self.LOOP_SECONDS else 1.5))
        self.painter.paint_backdrop(p, self.style, time.perf_counter(), flash)
        if t < self.LOOP_SECONDS:
            p.setFont(self.painter.font(46, QFont.Weight.Medium))
            p.setPen(self.painter.color("text", 0.8))
            p.drawText(QRectF(0, 150, REF_W, 80), Qt.AlignmentFlag.AlignCenter, "Pratinjau")
            frac = t - math.floor(t)
            frame = CountdownFrame(self.LOOP_SECONDS - math.floor(t), self.LOOP_SECONDS, frac, frac)
            self.painter.paint(p, self.style, frame)
        else:
            self.painter.paint_final(p, self.final_text, t - self.LOOP_SECONDS, self.style)
        p.end()


class Form:
    """Small helper that binds widgets to attributes of a settings section."""

    def __init__(self, section):
        self.section = section
        self.widget = QWidget()
        self.layout = QFormLayout(self.widget)
        self.layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.layout.setVerticalSpacing(10)
        self.savers = []

    def header(self, text: str) -> None:
        label = QLabel(f"<b>{text}</b>")
        label.setStyleSheet("color: #E8C468; margin-top: 10px;")
        self.layout.addRow(label)

    def note(self, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("muted")
        self.layout.addRow(label)

    def text(self, attr: str, label: str, placeholder: str = "") -> QLineEdit:
        w = QLineEdit(getattr(self.section, attr))
        w.setPlaceholderText(placeholder)
        self.layout.addRow(label, w)
        self.savers.append(lambda: setattr(self.section, attr, w.text()))
        return w

    def integer(self, attr: str, label: str, lo: int, hi: int, suffix: str = "", step: int = 1) -> QSpinBox:
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setSuffix(suffix)
        w.setValue(getattr(self.section, attr))
        self.layout.addRow(label, w)
        self.savers.append(lambda: setattr(self.section, attr, w.value()))
        return w

    def number(self, attr: str, label: str, lo: float, hi: float, step: float = 0.05, decimals: int = 2) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setSingleStep(step)
        w.setDecimals(decimals)
        w.setValue(getattr(self.section, attr))
        self.layout.addRow(label, w)
        self.savers.append(lambda: setattr(self.section, attr, w.value()))
        return w

    def check(self, attr: str, label: str) -> QCheckBox:
        w = QCheckBox(label)
        w.setChecked(getattr(self.section, attr))
        self.layout.addRow("", w)
        self.savers.append(lambda: setattr(self.section, attr, w.isChecked()))
        return w

    def choice(self, attr: str, label: str, options: dict) -> QComboBox:
        w = QComboBox()
        for key, text in options.items():
            w.addItem(text, key)
        w.setCurrentIndex(max(0, w.findData(getattr(self.section, attr))))
        self.layout.addRow(label, w)
        self.savers.append(lambda: setattr(self.section, attr, w.currentData()))
        return w

    def slider(self, attr: str, label: str) -> QSlider:
        w = QSlider(Qt.Orientation.Horizontal)
        w.setRange(0, 100)
        w.setValue(int(getattr(self.section, attr) * 100))
        value = QLabel()
        w.valueChanged.connect(lambda v: value.setText(f"{v}%"))
        value.setText(f"{w.value()}%")
        row = QHBoxLayout()
        row.addWidget(w, 1)
        row.addWidget(value)
        self.layout.addRow(label, row)
        self.savers.append(lambda: setattr(self.section, attr, w.value() / 100))
        return w

    def color(self, attr: str, label: str) -> None:
        btn = QPushButton()
        state = {"value": getattr(self.section, attr)}

        def paint():
            btn.setText(state["value"].upper())
            fg = "#000" if QColor(state["value"]).lightness() > 140 else "#fff"
            btn.setStyleSheet(f"background: {state['value']}; color: {fg}; border-radius: 6px; padding: 6px;")

        def pick():
            c = QColorDialog.getColor(QColor(state["value"]), self.widget, label)
            if c.isValid():
                state["value"] = c.name()
                paint()

        btn.clicked.connect(pick)
        paint()
        self.layout.addRow(label, btn)
        self.savers.append(lambda: setattr(self.section, attr, state["value"]))

    def save(self) -> None:
        for s in self.savers:
            s()

    def scrolled(self) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(self.widget)
        self.widget.setObjectName("form")
        area.viewport().setObjectName("formViewport")
        return area


class SettingsDialog(QDialog):
    def __init__(self, store: Store, settings: Settings, parent=None, on_active_video=None):
        super().__init__(parent)
        self.store = store
        # Called right away when the active video changes, so uploads count even if the dialog is cancelled.
        self.on_active_video = on_active_video or (lambda name: None)
        self.s = settings.copy()
        self.setWindowTitle("Pengaturan Grand Opening")
        self.setStyleSheet(STYLE + "QDialog { background: #0F172A; } QLineEdit, QSpinBox, QDoubleSpinBox "
                           "{ background: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 4px 6px; }"
                           "QTabBar::tab { background: #1E293B; padding: 8px 14px; border-radius: 6px; margin: 2px; }"
                           "QTabBar::tab:selected { background: #2563EB; } QTabWidget::pane { border: none; }"
                           "QScrollArea { border: none; background: transparent; }"
                           "QWidget#form, QWidget#formViewport { background: #0F172A; }")  # fmt: skip
        self.resize(760, 720)
        self.forms: list[Form] = []

        tabs = QTabWidget()
        tabs.addTab(self._text_tab(), "Teks")
        tabs.addTab(self._appearance_tab(), "Tampilan")
        tabs.addTab(self._video_tab(), "Video")
        tabs.addTab(self._gesture_tab(), "Gesture")
        tabs.addTab(self._clap_tab(), "Clap && Audio")
        tabs.addTab(self._countdown_tab(), "Countdown")
        tabs.addTab(self._device_tab(), "Perangkat")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Simpan")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Batal")
        defaults = buttons.addButton("Kembalikan default", QDialogButtonBox.ButtonRole.ResetRole)
        defaults.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _form(self, section) -> Form:
        f = Form(section)
        self.forms.append(f)
        return f

    def result_settings(self) -> Settings:
        for f in self.forms:
            f.save()
        self.s.video.active_video = self._active_video
        self.s.appearance.background_image = self._images["background_image"]
        self.s.appearance.logo_image = self._images["logo_image"]
        return self.s

    def _restore_defaults(self) -> None:
        if QMessageBox.question(self, "Default", "Kembalikan semua pengaturan ke default? (video yang diunggah tidak dihapus)") \
                == QMessageBox.StandardButton.Yes:  # fmt: skip
            self.s = Settings()
            self._active_video = ""
            self._images = {"background_image": "", "logo_image": ""}
            self.forms.clear()
            self.done(2)

    # --- tabs -----------------------------------------------------------------

    def _text_tab(self) -> QWidget:
        f = self._form(self.s.text)
        f.header("Judul")
        f.text("event_name", "Nama acara", "GRAND OPENING")
        f.text("title", "Judul utama", "Nama perusahaan / gedung")
        f.text("subtitle", "Subjudul", "Tanggal, lokasi, dll.")
        f.header("Instruksi di layar")
        f.text("idle_instruction", "Menunggu hi-five")
        f.text("listening_instruction", "Menunggu tepukan")
        f.note("Gunakan {count} untuk menampilkan jumlah tepukan yang dibutuhkan.")
        f.header("Countdown")
        f.text("countdown_label", "Label di atas angka")
        f.text("countdown_final_text", "Teks di akhir countdown")
        f.header("Penutup (setelah video)")
        f.text("closing_title", "Judul penutup")
        f.text("closing_subtitle", "Subjudul penutup")
        return f.scrolled()

    def _appearance_tab(self) -> QWidget:
        f = self._form(self.s.appearance)
        f.header("Warna")
        f.color("background_color", "Latar (atas-kiri)")
        f.color("background_color_2", "Latar (bawah-kanan)")
        f.color("text_color", "Teks")
        f.color("accent_color", "Aksen")
        f.header("Huruf")
        font = QFontComboBox()
        if self.s.appearance.font_family:
            font.setCurrentText(self.s.appearance.font_family)
        use_default = QCheckBox("Pakai huruf bawaan sistem")
        use_default.setChecked(not self.s.appearance.font_family)
        font.setEnabled(not use_default.isChecked())
        use_default.toggled.connect(lambda on: font.setEnabled(not on))
        f.layout.addRow("Jenis huruf", font)
        f.layout.addRow("", use_default)
        f.savers.append(lambda: setattr(self.s.appearance, "font_family", "" if use_default.isChecked() else font.currentFont().family()))
        f.header("Gambar")
        self._images = {"background_image": self.s.appearance.background_image, "logo_image": self.s.appearance.logo_image}
        for attr, label in (("logo_image", "Logo"), ("background_image", "Gambar latar")):
            f.layout.addRow(label, self._image_picker(attr))
        f.note("Gambar disalin ke folder data aplikasi, jadi file aslinya boleh dipindah.")
        f.check("show_gesture_hints", "Tampilkan petunjuk gesture di layar stage")
        return f.scrolled()

    def _image_picker(self, attr: str) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        name = QLabel(self._images[attr] or "—")
        choose = QPushButton("Pilih…")
        clear = QPushButton("Hapus")

        def pick():
            path, _ = QFileDialog.getOpenFileName(self, "Pilih gambar", "", IMAGE_FILTER)
            if not path:
                return
            src = Path(path)
            dst_name = f"{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
            shutil.copy2(src, self.store.assets_dir / dst_name)
            self._images[attr] = dst_name
            name.setText(f"{src.name}")

        def remove():
            self._images[attr] = ""
            name.setText("—")

        choose.clicked.connect(pick)
        clear.clicked.connect(remove)
        row.addWidget(name, 1)
        row.addWidget(choose)
        row.addWidget(clear)
        return w

    def _video_tab(self) -> QWidget:
        self._active_video = self.s.video.active_video
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel("<b>Daftar video</b> — video aktif (★) diputar setelah countdown. "
                           "Perubahan di daftar ini langsung tersimpan."))
        self.video_list = QListWidget()
        self.video_list.setStyleSheet("font-family: inherit; font-size: 13px;")
        self.video_list.itemDoubleClicked.connect(lambda _: self._set_active())
        v.addWidget(self.video_list, 1)
        row = QHBoxLayout()
        for text, fn in (("➕ Tambah video…", self._import_videos), ("★ Jadikan aktif", self._set_active),
                         ("▶ Pratinjau", self._preview_video), ("🗑 Hapus", self._delete_video)):  # fmt: skip
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self._refresh_videos()

        f = self._form(self.s.video)
        f.header("Pemutaran")
        f.slider("volume", "Volume video")
        f.choice("after_video", "Setelah video selesai", {
            "freeze": "Diam di frame terakhir",
            "closing": "Tampilkan layar penutup",
            "idle": "Kembali ke awal (menunggu hi-five)",
            "loop": "Ulangi video terus (hentikan dengan Lanjut/Reset)",
        })  # fmt: skip
        f.check("closing_text_on_freeze", "Tampilkan teks penutup di atas frame terakhir")
        f.integer("auto_return_idle_s", "Kembali ke awal otomatis setelah", 0, 3600, " detik")
        f.note("0 detik = tetap di layar akhir sampai operator menekan Reset atau gesture batu. "
               "Format paling aman: MP4 (H.264 + AAC).")  # fmt: skip
        v.addWidget(f.widget)
        return page

    def _refresh_videos(self) -> None:
        self.video_list.clear()
        playing, auto = self.store.resolve_video(self._active_video)
        for p in sorted(self.store.video_files(), key=lambda p: p.name.lower()):
            size = p.stat().st_size / (1024 * 1024)
            active = playing is not None and p.name == playing.name
            note = "   (otomatis: unggahan terbaru)" if active and auto else ""
            item = QListWidgetItem(f"{'★ ' if active else '   '}{p.name}   ·   {size:,.1f} MB{note}")
            item.setData(Qt.ItemDataRole.UserRole, p.name)
            if active:
                item.setForeground(QColor("#E8C468"))
            self.video_list.addItem(item)

    def _selected_video(self) -> str | None:
        item = self.video_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _import_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Tambah video", "", VIDEO_FILTER)
        added = []
        for path in paths:
            src = Path(path)
            name = _unique_name(self.store.videos_dir, src.name)
            if _copy_with_progress(self, src, self.store.videos_dir / name):
                added.append(name)
        if added and not self.store.video_path(self._active_video):
            self._activate(added[0])
        self._refresh_videos()

    def _activate(self, name: str) -> None:
        self._active_video = name
        self.on_active_video(name)

    def _set_active(self) -> None:
        name = self._selected_video()
        if name:
            self._activate(name)
            self._refresh_videos()

    def _preview_video(self) -> None:
        name = self._selected_video()
        if name:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.videos_dir / name)))

    def _delete_video(self) -> None:
        name = self._selected_video()
        if not name:
            return
        if QMessageBox.question(self, "Hapus video", f"Hapus '{name}' dari daftar dan dari disk?") != QMessageBox.StandardButton.Yes:
            return
        try:
            (self.store.videos_dir / name).unlink(missing_ok=True)
        except OSError as err:  # Windows: file still open (e.g. by the preview player)
            QMessageBox.warning(self, "Hapus video", f"Video tidak bisa dihapus karena sedang dipakai:\n{err}\n\n"
                                "Tutup jendela pratinjau atau tunggu video selesai, lalu coba lagi.")  # fmt: skip
            return
        if self._active_video == name:
            self._activate("")
        self._refresh_videos()

    def _gesture_tab(self) -> QWidget:
        f = self._form(self.s.gesture)
        f.header("Hi-five dua tangan (mulai)")
        f.integer("hi_five_hold_ms", "Lama ditahan", 100, 5000, " ms", 100)
        f.check("hi_five_require_raised", "Jari harus mengarah ke atas (tangan diangkat)")
        f.header("Tangan batu ✊ (reset)")
        f.integer("reset_hold_ms", "Lama ditahan", 300, 10000, " ms", 100)
        f.choice("reset_hands_required", "Jumlah tangan", {1: "Satu tangan cukup", 2: "Wajib dua tangan (lebih aman)"})
        f.check("reset_in_listening", "Aktif saat menunggu tepukan")
        f.check("reset_in_countdown", "Aktif saat countdown")
        f.check("reset_in_video", "Aktif saat video diputar (tidak disarankan)")
        f.check("reset_in_finished", "Aktif setelah video selesai")
        f.header("Waktu")
        f.integer("listening_timeout_s", "Batal otomatis jika tidak ada tepukan", 0, 600, " detik")
        f.note("0 = tidak pernah batal otomatis.")
        f.header("Deteksi tangan")
        f.integer("max_hands", "Maksimal tangan dilacak", 2, 8)
        f.number("min_detection_confidence", "Ambang deteksi", 0.1, 0.95)
        f.number("min_presence_confidence", "Ambang keberadaan", 0.1, 0.95)
        f.number("min_tracking_confidence", "Ambang pelacakan", 0.1, 0.95)
        f.header("Area deteksi (0–1 dari lebar/tinggi kamera)")
        f.number("roi_x", "Kiri", 0, 1)
        f.number("roi_y", "Atas", 0, 1)
        f.number("roi_w", "Lebar", 0.05, 1)
        f.number("roi_h", "Tinggi", 0.05, 1)
        f.note("Tangan di luar area diabaikan. Dari tangan di dalam area, dua tangan terbesar "
               "(paling dekat kamera) dipakai sebagai tangan VIP. Area tampil sebagai kotak emas di preview.")  # fmt: skip
        return f.scrolled()

    def _clap_tab(self) -> QWidget:
        f = self._form(self.s.clap)
        f.header("Hitungan")
        f.integer("required_count", "Jumlah tepukan untuk mulai", 1, 10)
        f.integer("max_gap_ms", "Jeda maksimal antar tepukan", 500, 10000, " ms", 100)
        f.integer("min_interval_ms", "Jeda minimal antar tepukan", 50, 1000, " ms", 10)
        f.header("Deteksi kamera")
        f.number("contact_ratio", "Ambang kontak (× ukuran telapak)", 0.2, 2.0)
        f.number("release_ratio", "Ambang lepas (× ukuran telapak)", 0.5, 4.0)
        f.check("detect_on_tracking_loss", "Hitung tangan yang hilang saat bersentuhan sebagai kontak (ragu)")
        f.note("Lihat grafik jarak di layar operator saat gladi untuk menyetel ambang.")
        f.header("Konfirmasi suara")
        f.choice("fusion_mode", "Mode", FUSION_LABELS)
        f.note("Suara saja TIDAK PERNAH menghitung tepukan; kamera selalu wajib. "
               "Seimbang: kontak jelas cukup, kontak ragu butuh suara. Ketat: selalu butuh suara.")  # fmt: skip
        mic = QComboBox()
        mic.addItem("Default sistem", "")
        for name in list_input_devices():
            mic.addItem(name, name)
        idx = mic.findData(self.s.clap.mic_device)
        mic.setCurrentIndex(max(idx, 0))
        f.layout.addRow("Mikrofon", mic)
        f.savers.append(lambda: setattr(self.s.clap, "mic_device", mic.currentData()))
        f.slider("mic_sensitivity", "Sensitivitas mic")
        f.integer("audio_window_ms", "Toleransi waktu kamera ↔ suara", 30, 500, " ms", 10)
        f.integer("audio_offset_ms", "Selisih latensi kamera − mic", -200, 400, " ms", 5)
        f.note("Gunakan tombol 'Kalibrasi audio' di layar operator untuk mengukur selisih latensi otomatis.")
        return f.scrolled()

    def _countdown_tab(self) -> QWidget:
        f = self._form(self.s.countdown)
        f.header("Gaya tampilan")
        style = f.choice("style", "Gaya countdown", STYLES)
        hint = QLabel()
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        preview = CountdownPreview(self.s.appearance, self.s.text.countdown_final_text or "DIBUKA!")
        preview.setStyleSheet("border-radius: 10px;")

        def on_style() -> None:
            key = style.currentData()
            preview.set_style(key)
            hint.setText(STYLE_HINTS.get(key, ""))

        style.currentIndexChanged.connect(on_style)
        on_style()
        f.layout.addRow(hint)
        f.layout.addRow(preview)
        f.note("Pratinjau memakai warna dari tab Tampilan yang sudah disimpan.")
        f.header("Waktu & suara")
        f.integer("seconds", "Durasi countdown", 1, 60, " detik")
        f.integer("final_hold_ms", "Tampilkan teks akhir selama", 0, 10000, " ms", 100)
        f.check("sound_enabled", "Efek suara (beep countdown, konfirmasi gesture)")
        f.slider("effects_volume", "Volume efek")
        return f.scrolled()

    def _device_tab(self) -> QWidget:
        f = self._form(self.s.device)
        f.header("Kamera")
        f.integer("camera_index", "Nomor kamera", 0, 9)
        res = QComboBox()
        for w, h in ((640, 480), (1280, 720), (1920, 1080)):
            res.addItem(f"{w} × {h}", (w, h))
        res.setCurrentIndex(max(0, res.findData((self.s.device.camera_width, self.s.device.camera_height))))
        f.layout.addRow("Resolusi", res)

        def save_res():
            self.s.device.camera_width, self.s.device.camera_height = res.currentData()

        f.savers.append(save_res)
        f.integer("camera_fps", "FPS", 15, 120)
        f.check("mirror_preview", "Cerminkan preview di layar operator")
        f.note("0 = kamera bawaan. Kamera USB/capture card biasanya 1 atau 2. 60 FPS membantu tepukan cepat "
               "jika kamera mendukung.")  # fmt: skip
        f.header("Layar stage")
        screen = QComboBox()
        screen.addItem("Layar terakhir (biasanya proyektor)", -1)
        for i, s in enumerate(QGuiApplication.screens()):
            g = s.geometry()
            screen.addItem(f"{i}: {s.name()} ({g.width()}×{g.height()})", i)
        screen.setCurrentIndex(max(0, screen.findData(self.s.device.stage_screen)))
        f.layout.addRow("Tampilkan di", screen)
        f.savers.append(lambda: setattr(self.s.device, "stage_screen", screen.currentData()))
        f.check("stage_fullscreen", "Fullscreen")
        f.note(f"Folder data: {self.store.data_dir}")
        return f.scrolled()
