"""Application entry point: `uv run ceremony` or `python -m ceremony`."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from .config import Store
from .controller import CeremonyController
from .ui.operator import OperatorWindow
from .ui.settings_dialog import SettingsDialog
from .ui.stage import StageWindow


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Grand Opening Ceremony")
    p.add_argument("--data-dir", type=Path, help="folder for settings, videos and images")
    p.add_argument("--windowed", action="store_true", help="open the stage as a normal window (for testing)")
    p.add_argument("--no-camera", action="store_true", help="don't start camera/mic (keyboard simulation only)")
    return p.parse_args(argv)


def setup_logging(log_dir: Path) -> Path:
    """Every gesture, clap decision, phase change and video event goes to logs/ceremony.log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "ceremony.log"
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger("ceremony")
    root.setLevel(logging.INFO)
    root.handlers[:] = [file_handler, console]
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Grand Opening Ceremony")

    store = Store(args.data_dir)
    log_path = setup_logging(store.data_dir / "logs")
    logging.getLogger("ceremony").info("=== Grand Opening Ceremony dimulai · log: %s", log_path)
    settings = store.load()
    store.save(settings)  # writes a complete file on first run so it's easy to inspect

    controller = CeremonyController(store, settings, start_devices=not args.no_camera)
    controller.log_startup()
    stage = StageWindow(controller)
    stage.force_windowed = args.windowed

    def open_settings() -> None:
        stage.release_media()  # lets the video library delete/replace files on Windows
        dlg = SettingsDialog(store, controller.settings, operator, on_active_video=controller.set_active_video)
        result = dlg.exec()
        if result in (1, 2):  # saved, or restored defaults
            old_device = controller.settings.device
            new = dlg.result_settings()
            controller.apply_settings(new)
            if (old_device.stage_screen, old_device.stage_fullscreen) != (new.device.stage_screen, new.device.stage_fullscreen):
                stage.place()
        stage.resume_media()

    operator = OperatorWindow(controller, stage, open_settings)

    # Global shortcuts work from either window.
    for window in (operator, stage):
        for key, fn in (
            ("Space", controller.advance),
            ("Escape", controller.reset),
            ("H", controller.simulate_hi_five),
            ("C", controller.simulate_clap),
            ("B", controller.simulate_fist),
        ):
            QShortcut(QKeySequence(key), window, fn)
    QShortcut(QKeySequence("F"), operator, stage.toggle_fullscreen)
    QShortcut(QKeySequence("Ctrl+,"), operator, open_settings)

    operator.show()
    stage.place()
    operator.raise_()
    operator.activateWindow()

    app.aboutToQuit.connect(controller.shutdown)
    # Let Ctrl+C in the terminal quit cleanly.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(250)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
