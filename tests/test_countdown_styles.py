"""Every countdown style must paint without errors in every situation the stage can hit."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from ceremony.config import AppearanceSettings, Settings
from ceremony.ui.countdown_styles import STYLES, CountdownFrame, CountdownPainter


@pytest.fixture(scope="module")
def painter():
    _ = QApplication.instance() or QApplication([])
    a = AppearanceSettings()
    return CountdownPainter(lambda: a)


@pytest.mark.parametrize("style", list(STYLES))
@pytest.mark.parametrize(("value", "total"), [(5, 5), (1, 5), (1, 1), (10, 10), (9, 10), (60, 60), (37, 60)])
@pytest.mark.parametrize("since", [0.0, 0.1, 0.3, 0.6, 0.99])
def test_style_paints(painter, style, value, total, since):
    img = QImage(480, 270, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.scale(0.25, 0.25)
    painter.paint_backdrop(p, style, 1234.5 + since, 1 - since)
    painter.paint(p, style, CountdownFrame(value, total, since, since))
    painter.paint_final(p, "DIBUKA!", since, style)
    painter.paint_final(p, "DIBUKA!", 2.0 + since, style)
    p.end()


def test_unknown_style_falls_back_to_ring(painter):
    img = QImage(480, 270, QImage.Format.Format_RGB32)
    p = QPainter(img)
    painter.paint(p, "does-not-exist", CountdownFrame(3, 5, 0.5, 0.5))
    p.end()


def test_default_style_is_known():
    assert Settings().countdown.style in STYLES


@pytest.mark.parametrize("style", list(STYLES))
def test_prepare_warms_without_errors(painter, style):
    painter.prepare(style, 60, "DIBUKA!")
    painter.prepare(style, 1, "")
