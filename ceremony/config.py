"""Persistent settings.

Everything the operator can change lives in one JSON file inside the data directory.
Loading is forgiving: unknown keys are ignored and missing keys fall back to defaults,
so an older settings file keeps working after an upgrade.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

APP_NAME = "GrandOpeningCeremony"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def bundled_path(*parts: str) -> Path:
    """Path to a file shipped with the app (works from source and from a PyInstaller bundle)."""
    base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return base.joinpath(*parts)


def default_data_dir() -> Path:
    env = os.environ.get("CEREMONY_DATA_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


# --- sections -----------------------------------------------------------------


@dataclass
class TextSettings:
    event_name: str = "GRAND OPENING"
    title: str = "Nama Perusahaan Anda"
    subtitle: str = "Peresmian · 10 November 2026"
    idle_instruction: str = "Angkat kedua telapak tangan ke arah kamera untuk memulai"
    listening_instruction: str = "Tepuk tangan {count}x untuk meresmikan"
    countdown_label: str = "Peresmian dimulai dalam"
    countdown_final_text: str = "DIBUKA!"
    closing_title: str = "Resmi Dibuka"
    closing_subtitle: str = "Terima kasih atas kehadiran Anda"


@dataclass
class AppearanceSettings:
    font_family: str = ""  # empty = system default
    background_color: str = "#0B1026"
    background_color_2: str = "#1D2B64"
    text_color: str = "#FFFFFF"
    accent_color: str = "#E8C468"
    background_image: str = ""  # file name inside data/assets
    logo_image: str = ""  # file name inside data/assets
    show_gesture_hints: bool = True


@dataclass
class GestureSettings:
    hi_five_hold_ms: int = 800
    hi_five_require_raised: bool = True
    reset_hold_ms: int = 2000
    reset_hands_required: int = 1  # 1 or 2 fists
    reset_in_listening: bool = True
    reset_in_countdown: bool = False
    reset_in_video: bool = False
    reset_in_finished: bool = True
    listening_timeout_s: int = 15
    max_hands: int = 4
    min_detection_confidence: float = 0.6
    min_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    # Region of interest in normalized camera coordinates; hands outside it are ignored.
    roi_x: float = 0.0
    roi_y: float = 0.0
    roi_w: float = 1.0
    roi_h: float = 1.0


@dataclass
class ClapSettings:
    required_count: int = 2
    max_gap_ms: int = 2500  # count resets if the next clap takes longer than this
    min_interval_ms: int = 180
    contact_ratio: float = 0.75  # palm distance / palm size counted as contact
    release_ratio: float = 1.3  # hands must separate past this before the next clap
    detect_on_tracking_loss: bool = True
    fusion_mode: str = "balanced"  # "strict" | "balanced" | "camera"
    audio_window_ms: int = 150
    audio_offset_ms: int = 70  # how much later the camera sees a clap than the mic hears it
    mic_device: str = ""  # empty = system default
    mic_sensitivity: float = 0.5  # 0 = only very sharp claps, 1 = very sensitive


@dataclass
class CountdownSettings:
    style: str = "ring"  # see ceremony/ui/countdown_styles.py STYLES
    seconds: int = 5
    final_hold_ms: int = 1200
    sound_enabled: bool = True
    effects_volume: float = 0.8


@dataclass
class VideoSettings:
    active_video: str = ""  # file name inside data/videos
    volume: float = 1.0
    after_video: str = "freeze"  # "freeze" | "closing" | "idle" | "loop"
    closing_text_on_freeze: bool = True
    auto_return_idle_s: int = 0  # 0 = stay until reset


@dataclass
class DeviceSettings:
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 30
    mirror_preview: bool = True
    stage_screen: int = -1  # -1 = last screen (usually the projector)
    stage_fullscreen: bool = True


@dataclass
class Settings:
    text: TextSettings = field(default_factory=TextSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    gesture: GestureSettings = field(default_factory=GestureSettings)
    clap: ClapSettings = field(default_factory=ClapSettings)
    countdown: CountdownSettings = field(default_factory=CountdownSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    device: DeviceSettings = field(default_factory=DeviceSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        return _build(cls, data)

    def copy(self) -> Settings:
        return Settings.from_dict(self.to_dict())


def _build(cls: type, data: Any) -> Any:
    obj = cls()
    if not isinstance(data, dict):
        return obj
    hints = get_type_hints(cls)
    for f in fields(cls):
        if f.name not in data:
            continue
        value, hint = data[f.name], hints[f.name]
        if is_dataclass(hint):
            setattr(obj, f.name, _build(hint, value))
            continue
        try:
            if hint is bool:
                value = bool(value)
            elif hint is int:
                value = int(value)
            elif hint is float:
                value = float(value)
            elif hint is str:
                value = str(value)
        except (TypeError, ValueError):
            continue
        setattr(obj, f.name, value)
    return obj


class Store:
    """Owns the data directory: settings.json, videos/ and assets/."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.videos_dir = self.data_dir / "videos"
        self.assets_dir = self.data_dir / "assets"
        self.sounds_dir = self.data_dir / "sounds"
        self.settings_path = self.data_dir / "settings.json"
        for d in (self.videos_dir, self.assets_dir, self.sounds_dir):
            d.mkdir(parents=True, exist_ok=True)

    def load(self) -> Settings:
        try:
            return Settings.from_dict(json.loads(self.settings_path.read_text("utf-8")))
        except FileNotFoundError:
            return Settings()
        except (OSError, ValueError) as err:
            print(f"[settings] could not read {self.settings_path}: {err}; using defaults", file=sys.stderr)
            return Settings()

    def save(self, settings: Settings) -> None:
        tmp = self.settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(self.settings_path)

    def video_path(self, name: str) -> Path | None:
        if not name:
            return None
        p = self.videos_dir / name
        return p if p.is_file() else None

    def video_files(self) -> list[Path]:
        """Uploaded videos, newest first."""
        files = [p for p in self.videos_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    def resolve_video(self, name: str) -> tuple[Path | None, bool]:
        """The video to play: the chosen one, or else the newest upload. Returns (path, chosen_automatically)."""
        chosen = self.video_path(name)
        if chosen:
            return chosen, False
        files = self.video_files()
        return (files[0], True) if files else (None, False)

    def asset_path(self, name: str) -> Path | None:
        if not name:
            return None
        p = self.assets_dir / name
        return p if p.is_file() else None
