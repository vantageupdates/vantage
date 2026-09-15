import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import MethodType

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QRawFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton)

from vantage.helpers import config
from vantage.helpers.game_capture import GameWindowCapture
from vantage.helpers.quickbar_items import QUICKBAR_ITEMS
from vantage.helpers.vitals import (
    MIN_CONFIDENCE, VitalStopTracker, default_vital_bar, default_vital_bars,
    default_vital_stop, denormalize_rect, normalize_rect, preset_percentages,
    read_visible_percent, read_vital_bar, sanitize_vital_bar,
    sanitize_vital_bars)
import vantage.helpers.vitals as vital_helpers_module
from vantage.parsers.vitals import (
    CalibrationControls, CalibrationOverlay, VitalBarDialog, VitalStopDialog,
    Vitals)
import vantage.parsers.vitals as vitals_module


ROOT = Path(__file__).resolve().parents[1]


def _image(width=100, height=12, fill=60, rtl=False):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(12, 14, 18))
    start = width - fill if rtl else 0
    end = width if rtl else fill
    for x in range(start, end):
        for y in range(height):
            image.setPixelColor(x, y, QColor(205, 28, 35))
    return image


_DIGITS = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "%": ("11001", "11010", "00100", "00100", "01000", "10110", "00110"),
}

_EQ_BITMAP_100 = (
    "..#..###...###.",
    "###.#...#.#...#",
    "..#.#...#.#...#",
    "..#.#...#.#...#",
    "..#.#...#.#...#",
    "..#.#...#.#...#",
    "..#.#...#.#...#",
    "..#..###...###.",
)

_EQ_BITMAP_DIGITS = {
    "0": (".###.", "#...#", "#...#", "#...#",
          "#...#", "#...#", "#...#", ".###."),
    "1": ("..#", "###", "..#", "..#", "..#", "..#", "..#", "..#"),
    "2": (".###.", "#...#", "....#", "...#.",
          "..#..", ".#...", "#....", "#####"),
    "3": ("####.", "....#", "....#", ".###.",
          "....#", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.",
          "#####", "...#.", "...#.", "...#."),
    "5": ("#####", "#....", "#....", "####.",
          "....#", "....#", "....#", "####."),
    "6": (".###.", "#....", "#....", "####.",
          "#...#", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "...#.",
          "..#..", "..#..", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.",
          "#...#", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", "#...#",
          ".####", "....#", "....#", ".###."),
    "%": ("##..#", "##.#.", "...#.", "..#..",
          "..#..", ".#...", "#.##.", "#..##"),
}


def _eq_bitmap_100_image(
        canvas, offset, color, bars=(), frame_lines=()):
    """Build privacy-safe fixtures from the exact screenshot glyph mask."""
    image = QImage(canvas[0], canvas[1], QImage.Format.Format_RGB32)
    image.fill(QColor(10, 14, 16))
    for left, top, width, height, bar_color in bars:
        for y in range(top, min(image.height(), top + height)):
            for x in range(left, min(image.width(), left + width)):
                image.setPixelColor(x, y, QColor(bar_color))
    for left, top, width, height, line_color in frame_lines:
        for y in range(top, min(image.height(), top + height)):
            for x in range(left, min(image.width(), left + width)):
                image.setPixelColor(x, y, QColor(line_color))
    left, top = offset
    foreground = QColor(color)
    for y, row in enumerate(_EQ_BITMAP_100):
        for x, pixel in enumerate(row):
            if pixel == "#":
                image.setPixelColor(left + x, top + y, foreground)
    return image


def _eq_bitmap_number_image(
        value, canvas=(54, 24), offset=(4, 8), color="#eceae1",
        include_percent=False, scale=1, bars=(), missing_pixels=()):
    """Build a privacy-safe compact eight-row EQ percentage fixture."""
    image = QImage(canvas[0], canvas[1], QImage.Format.Format_RGB32)
    background = QColor(10, 14, 16)
    image.fill(background)
    for left, top, width, height, bar_color in bars:
        for y in range(top, min(image.height(), top + height)):
            for x in range(left, min(image.width(), left + width)):
                image.setPixelColor(x, y, QColor(bar_color))
    text = str(value) + ("%" if include_percent else "")
    left, top = offset
    foreground = QColor(color)
    cursor = left
    foreground_points = []
    for glyph in text:
        rows = _EQ_BITMAP_DIGITS[glyph]
        for row, bits in enumerate(rows):
            for column, bit in enumerate(bits):
                if bit != "#":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        point = (cursor + column * scale + dx,
                                 top + row * scale + dy)
                        foreground_points.append(point)
                        image.setPixelColor(*point, foreground)
        cursor += (len(rows[0]) + 1) * scale
    for index in missing_pixels:
        point = foreground_points[index % len(foreground_points)]
        image.setPixelColor(*point, background)
    token_width = cursor - left - scale
    return image, (left, top, token_width, 8 * scale)


def _number_image(value, scale=2, color="#f2cf68", include_percent=True):
    text = str(value) + ("%" if include_percent else "")
    glyph_width = 5 * scale
    width = 8 + len(text) * glyph_width + max(0, len(text) - 1) * scale
    height = 8 + 7 * scale
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#101820"))
    foreground = QColor(color)
    x_offset = 4
    for glyph in text:
        for row, bits in enumerate(_DIGITS[glyph]):
            for column, bit in enumerate(bits):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            image.setPixelColor(
                                x_offset + column * scale + dx,
                                4 + row * scale + dy, foreground)
        x_offset += glyph_width + scale
    return image


def _padded_number_image(
        value, canvas=(150, 64), offset=(42, 21), scale=2,
        include_percent=True, frame=True):
    token = _number_image(value, scale=scale, include_percent=include_percent)
    image = QImage(canvas[0], canvas[1], QImage.Format.Format_RGB32)
    image.fill(QColor("#101820"))
    left, top = offset
    for y in range(token.height()):
        for x in range(token.width()):
            image.setPixelColor(left + x, top + y, token.pixelColor(x, y))
    if frame:
        frame_color = QColor("#55606a")
        for x in range(3, image.width() - 3):
            image.setPixelColor(x, 5, frame_color)
            image.setPixelColor(x, image.height() - 6, frame_color)
        for y in range(5, image.height() - 5):
            image.setPixelColor(3, y, frame_color)
            image.setPixelColor(image.width() - 4, y, frame_color)
    return image, token


def _raw_font_number_image(value, font_path, size, color, include_percent=True):
    font = QRawFont(
        str(font_path), size, QFont.HintingPreference.PreferFullHinting)
    text = str(value) + ("%" if include_percent else "")
    glyphs = [font.alphaMapForGlyph(
        index, QRawFont.AntialiasingType.PixelAntialiasing)
        for index in font.glyphIndexesForString(text)]
    width = 8 + sum(glyph.width() + 1 for glyph in glyphs)
    height = 8 + max(glyph.height() for glyph in glyphs)
    background = QColor("#101820")
    foreground = QColor(color)
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(background)
    x_offset = 4
    for glyph in glyphs:
        y_offset = (height - glyph.height()) // 2
        for y in range(glyph.height()):
            for x in range(glyph.width()):
                alpha = glyph.pixelColor(x, y).alpha() / 255.0
                if alpha <= 0:
                    continue
                image.setPixelColor(x_offset + x, y_offset + y, QColor(
                    round(background.red() * (1 - alpha) + foreground.red() * alpha),
                    round(background.green() * (1 - alpha) + foreground.green() * alpha),
                    round(background.blue() * (1 - alpha) + foreground.blue() * alpha)))
        x_offset += glyph.width() + 1
    return image


def _app():
    return QApplication.instance() or QApplication([])


def test_normalized_geometry_survives_window_move_resize_and_is_bounded():
    normalized = normalize_rect((200, 100, 400, 30), (1000, 500))
    assert normalized == [0.2, 0.2, 0.4, 0.06]
    assert denormalize_rect(normalized, (2000, 1000)) == (400, 200, 800, 60)
    assert denormalize_rect([.95, .95, .5, .5], (100, 100)) == (95, 95, 5, 5)


def test_visible_number_reader_handles_zero_to_100_sizes_colors_and_optional_percent():
    _app()
    cases = (
        (0, 1, "#ffffff", True),
        (7, 2, "#f2cf68", False),
        (42, 2, "#42e2e8", True),
        (62, 3, "#80ef6a", False),
        (99, 3, "#ff8cc8", True),
        (100, 2, "#ffffff", True),
    )
    for expected, scale, color, with_percent in cases:
        reading = read_visible_percent(
            _number_image(expected, scale, color, with_percent),
            [0, 0, 1, 1])
        assert reading.valid is True, (expected, reading)
        assert reading.percent == float(expected)
        assert reading.confidence >= MIN_CONFIDENCE
        assert reading.source == "number"
    routed = read_vital_bar(_number_image(42), {
        "id": "hp", "name": "HP", "ocr_calibrated": True,
        "rect": [0, 0, 1, 1]})
    assert routed.valid is True and routed.percent == 42.0


def test_visible_number_reader_handles_common_windows_font_shapes():
    _app()
    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    cases = (
        (font_dir / "arial.ttf", 12, 37, "#ffffff", True),
        (font_dir / "tahomabd.ttf", 19, 85, "#f2cf68", False),
        (font_dir / "segoeui.ttf", 26, 100, "#55e4dc", True),
    )
    available = [case for case in cases if case[0].is_file()]
    if not available:
        pytest.skip("Common Windows font files are unavailable")
    for font_path, size, expected, color, with_percent in available:
        reading = read_visible_percent(
            _raw_font_number_image(
                expected, font_path, size, color, with_percent),
            [0, 0, 1, 1])
        assert reading.valid is True, (font_path, expected, reading)
        assert reading.percent == float(expected)


def test_real_eq_bitmap_100_is_available_without_desktop_font_templates(
        monkeypatch):
    class NoGuiApplication:
        @staticmethod
        def instance():
            return None

    monkeypatch.setattr(
        vital_helpers_module, "QGuiApplication", NoGuiApplication)
    vital_helpers_module._ocr_templates.cache_clear()
    try:
        fixtures = (
            _eq_bitmap_100_image(
                (34, 28), (9, 9), "#eceae1",
                bars=((27, 5, 7, 18, "#00e600"),),
                frame_lines=((0, 4, 2, 20, "#e8b83e"),)),
            _eq_bitmap_100_image(
                (30, 26), (7, 11), "#f0f3f7",
                bars=((24, 8, 6, 13, "#00e600"),),
                frame_lines=((0, 22, 30, 2, "#343a3e"),)),
        )
        for image, offset in zip(fixtures, ((9, 9), (7, 11))):
            left, top = offset
            rois = ((0, 0, image.width(), image.height()),
                    (left - 2, top - 2, 19, 12),
                    (left, top, 15, 8))
            for roi in rois:
                reading = read_visible_percent(
                    image,
                    normalize_rect(roi, (image.width(), image.height())))
                assert reading.valid is True, (roi, reading)
                assert reading.percent == 100.0
                assert reading.token_rect == (left, top, 15, 8)
    finally:
        # Do not leave the process-wide template cache in the simulated
        # no-GUI state for later font-rendering tests.
        vital_helpers_module._ocr_templates.cache_clear()


def test_real_eq_blue_and_green_labels_ignore_adjacent_bars_and_stay_ambiguous():
    image = _eq_bitmap_100_image(
        (32, 55), (2, 17), "#45d483",
        bars=((20, 15, 12, 16, "#00df00"),
              (20, 36, 12, 10, "#1a9fff")),
        frame_lines=((0, 47, 32, 2, "#626466"),))
    blue = QColor("#1a9fff")
    for y, row in enumerate(_EQ_BITMAP_100):
        for x, pixel in enumerate(row):
            if pixel == "#":
                image.setPixelColor(2 + x, 38 + y, blue)

    top = read_visible_percent(
        image, normalize_rect((0, 0, 32, 27), (32, 55)))
    bottom = read_visible_percent(
        image, normalize_rect((0, 28, 32, 27), (32, 55)))
    assert top.valid is True and top.percent == 100.0
    assert top.token_rect == (2, 17, 15, 8)
    assert bottom.valid is True and bottom.percent == 100.0
    assert bottom.token_rect == (2, 38, 15, 8)

    combined = read_visible_percent(image, [0, 0, 1, 1])
    assert combined.valid is False
    assert combined.percent is None
    assert "multiple" in combined.message.casefold()


def test_compact_eq_bitmap_alphabet_reads_realistic_values_without_font_data(
        monkeypatch):
    class NoGuiApplication:
        @staticmethod
        def instance():
            return None

    monkeypatch.setattr(
        vital_helpers_module, "QGuiApplication", NoGuiApplication)
    vital_helpers_module._ocr_templates.cache_clear()
    try:
        cases = (
            (7, "#f0f3f7", False, 1),
            (25, "#e6bd48", False, 1),
            (37, "#f0f3f7", False, 1),
            (42, "#45d483", True, 1),
            (68, "#1a9fff", False, 2),
            (99, "#f0f3f7", False, 1),
            (100, "#45d483", False, 1),
        )
        for expected, color, include_percent, scale in cases:
            image, token = _eq_bitmap_number_image(
                expected, canvas=(74, 36), offset=(5, 9), color=color,
                include_percent=include_percent, scale=scale,
                bars=((38, 6, 34, 18, color),))
            loose = read_visible_percent(image, [0, 0, 1, 1])
            tight = read_visible_percent(
                image, normalize_rect(token, (image.width(), image.height())))
            assert loose.valid is True, (expected, "loose", loose)
            assert loose.percent == float(expected)
            assert tight.valid is True, (expected, "tight", tight)
            assert tight.percent == float(expected)
            assert loose.confidence >= MIN_CONFIDENCE
    finally:
        vital_helpers_module._ocr_templates.cache_clear()


def test_compact_eq_templates_do_not_turn_a_colored_bar_into_a_number():
    image = QImage(74, 36, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 14, 16))
    for y in range(9, 17):
        for x in range(5, 69):
            image.setPixelColor(x, y, QColor("#45d483"))
    reading = read_visible_percent(image, [0, 0, 1, 1])
    assert reading.valid is False
    assert reading.percent is None
    assert "unreadable" in reading.message.casefold()


def test_compact_eq_bitmap_reader_tolerates_single_pixel_capture_noise(
        monkeypatch):
    class NoGuiApplication:
        @staticmethod
        def instance():
            return None

    monkeypatch.setattr(
        vital_helpers_module, "QGuiApplication", NoGuiApplication)
    vital_helpers_module._ocr_templates.cache_clear()
    try:
        cases = ((25, (3,), False), (42, (), True), (68, (27,), False))
        for expected, missing, add_speck in cases:
            image, token = _eq_bitmap_number_image(
                expected, canvas=(46, 24), offset=(4, 7),
                color="#eceae1", missing_pixels=missing)
            if add_speck:
                image.setPixelColor(
                    token[0] + token[2] + 2, token[1] + 3,
                    QColor("#eceae1"))
            reading = read_visible_percent(
                image, normalize_rect(
                    (token[0] - 2, token[1] - 2,
                     token[2] + 4, token[3] + 4),
                    (image.width(), image.height())))
            assert reading.valid is True, (expected, reading)
            assert reading.percent == float(expected)
    finally:
        vital_helpers_module._ocr_templates.cache_clear()


def test_two_different_compact_eq_numbers_remain_ambiguous(monkeypatch):
    class NoGuiApplication:
        @staticmethod
        def instance():
            return None

    monkeypatch.setattr(
        vital_helpers_module, "QGuiApplication", NoGuiApplication)
    vital_helpers_module._ocr_templates.cache_clear()
    try:
        image, _token = _eq_bitmap_number_image(
            25, canvas=(100, 38), offset=(5, 5), color="#45d483")
        second, _second_token = _eq_bitmap_number_image(
            68, canvas=(18, 8), offset=(0, 0), color="#1a9fff")
        background = QColor(10, 14, 16)
        for y in range(second.height()):
            for x in range(second.width()):
                color = second.pixelColor(x, y)
                if color != background:
                    image.setPixelColor(68 + x, 23 + y, color)
        reading = read_visible_percent(image, [0, 0, 1, 1])
        assert reading.valid is False
        assert reading.percent is None
        assert "multiple" in reading.message.casefold()
    finally:
        vital_helpers_module._ocr_templates.cache_clear()


def test_visible_number_reader_never_turns_unreadable_pixels_into_zero():
    _app()
    blank = QImage(60, 22, QImage.Format.Format_RGB32)
    blank.fill(QColor("#101820"))
    reading = read_visible_percent(blank, [0, 0, 1, 1])
    assert reading.valid is False
    assert reading.percent is None
    assert "unreadable" in reading.message.casefold()


def test_visible_number_reader_auto_finds_offset_token_inside_padded_framed_roi():
    _app()
    image, token = _padded_number_image(62)
    reading = read_visible_percent(image, [0, 0, 1, 1])
    assert reading.valid is True
    assert reading.percent == 62.0
    assert reading.token_rect
    left, top, width, height = reading.token_rect
    assert 42 <= left < 42 + token.width()
    assert 21 <= top < 21 + token.height()
    assert width < image.width() / 2
    assert height < image.height() / 2


def test_visible_number_reader_rejects_two_plausible_percentages_as_ambiguous():
    _app()
    first, _token = _padded_number_image(
        62, canvas=(190, 64), offset=(18, 21), frame=False)
    second = _number_image(48, scale=2)
    for y in range(second.height()):
        for x in range(second.width()):
            first.setPixelColor(123 + x, 21 + y, second.pixelColor(x, y))
    reading = read_visible_percent(first, [0, 0, 1, 1])
    assert reading.valid is False
    assert reading.percent is None
    assert "multiple" in reading.message.casefold()


def test_numeric_migration_keeps_ocr_roi_and_clears_legacy_bar_roi():
    numeric_rect = [.1, .2, .08, .04]
    migrated = sanitize_vital_bar({
        "id": "hp", "name": "HP", "read_mode": "number",
        "rect": numeric_rect, "color": [205, 28, 35],
        "direction": "rtl", "tolerance": 120,
    })
    assert migrated["rect"] == numeric_rect
    assert migrated["ocr_calibrated"] is True
    legacy = sanitize_vital_bar({
        "id": "hp-old", "name": "HP old", "read_mode": "fill",
        "rect": [0, 0, 1, .05], "color": [205, 28, 35],
        "direction": "ltr", "tolerance": 64,
    })
    assert legacy["rect"] == []
    assert legacy["ocr_calibrated"] is False
    assert not ({"read_mode", "color", "direction", "tolerance"} & migrated.keys())
    assert not ({"read_mode", "color", "direction", "tolerance"} & legacy.keys())

    persisted = sanitize_vital_bar(migrated)
    assert persisted["rect"] == numeric_rect
    assert persisted["ocr_calibrated"] is True


def test_full_alert_silence_defaults_migrate_and_preserve_explicit_values():
    defaults = default_vital_bars()
    assert [bar["silence_full_alerts"] for bar in defaults] == [
        False, False, True, False]

    # Existing target profiles without the field migrate safely, while other
    # overlay types retain the original full-health alert behavior.
    assert sanitize_vital_bar({
        "id": "old-target", "type": "target_hp",
    })["silence_full_alerts"] is True
    assert sanitize_vital_bar({
        "id": "old-player", "type": "my_hp",
    })["silence_full_alerts"] is False

    opted_in = sanitize_vital_bar({
        "id": "player", "type": "my_hp", "silence_full_alerts": True,
    })
    opted_out = sanitize_vital_bar({
        "id": "target", "type": "target_hp", "silence_full_alerts": False,
    })
    assert opted_in["silence_full_alerts"] is True
    assert opted_out["silence_full_alerts"] is False

    # Sanitization persists an explicit preference, so changing Type later
    # cannot silently replace the user's choice with that type's default.
    opted_in["type"] = "custom"
    opted_out["type"] = "group_hp"
    assert sanitize_vital_bar(opted_in)["silence_full_alerts"] is True
    assert sanitize_vital_bar(opted_out)["silence_full_alerts"] is False

    round_trip = sanitize_vital_bars(json.loads(json.dumps([
        opted_in, opted_out])))
    assert [bar["silence_full_alerts"] for bar in round_trip] == [True, False]


def test_one_poll_monitors_every_enabled_saved_bar_from_the_same_frame():
    image = _number_image(64, scale=3)
    bars = default_vital_bars()
    for bar in bars:
        bar["ocr_calibrated"] = True
        bar["rect"] = [0, 0, 1, 1]

    class Capture:
        def image_frame(self, **_kwargs):
            return ({"available": True, "message": "Reading"}, image,
                    (0, 0, image.width(), image.height()))

    class Tracker:
        def __init__(self):
            self.seen = []

        def update(self, bar_id, percent, stops, confidence):
            self.seen.append((bar_id, percent, confidence))
            return []

    owner = type("Owner", (), {})()
    owner._capture = Capture()
    owner._bars = bars
    owner._cards = {}
    owner._readings = {}
    owner._tracker = Tracker()
    owner._last_live_frame = None
    owner._last_live_rect = ()
    owner._last_live_at = 0.0
    statuses = []
    owner._set_status = statuses.append
    owner._deliver_stop = lambda *_args: None

    Vitals.poll_now(owner)

    assert list(owner._readings) == [
        "my-hp", "my-mana", "target-hp", "group-hp"]
    assert [row[0] for row in owner._tracker.seen] == list(owner._readings)
    assert all(reading.valid for reading in owner._readings.values())
    assert statuses == ["ACTIVE · 4 live readings"]


def test_presets_and_crossing_hysteresis_cooldown_are_deterministic():
    assert preset_percentages("quarters") == [25, 50, 75, 100]
    assert preset_percentages("every10") == list(range(10, 101, 10))
    stop = default_vital_stop(50, "below")
    stop.update({"id": "low", "hysteresis": 3, "cooldown": 30})
    tracker = VitalStopTracker()
    assert tracker.update("hp", 60, [stop], now=0) == []
    assert [event[1] for event in tracker.update("hp", 49, [stop], now=1)] == ["below"]
    assert tracker.update("hp", 51, [stop], now=2) == []
    assert tracker.update("hp", 55, [stop], now=3) == []
    assert tracker.update("hp", 49, [stop], now=4) == []
    assert tracker.update("hp", 55, [stop], now=31) == []
    assert [event[1] for event in tracker.update("hp", 49, [stop], now=32)] == ["below"]
    # Untrusted frames neither alert nor mutate the crossing state.
    assert tracker.update("hp", 80, [stop], confidence=.2, now=80) == []


def test_vitals_config_defaults_and_corruption_are_sanitized(tmp_path, monkeypatch):
    original = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    try:
        config.data = {
            "vitals": {
                "bars": [{
                    "id": "bad id", "name": "", "type": "unknown",
                    "rect": [2, -1, 99, 0], "color": [-2, 999, "x"],
                    "direction": "up", "tolerance": 999,
                    "stops": [{
                        "percent": -50, "direction": "sideways",
                        "delivery": "voice", "volume": 900,
                        "pitch": -99, "cooldown": 99999,
                    }],
                }],
                "poll_ms": 1,
                "sounds_when_hidden": "yes",
            }
        }
        config.verify_settings()
        vitals = config.data["vitals"]
        bar = vitals["bars"][0]
        stop = bar["stops"][0]
        assert vitals["poll_ms"] == 200
        assert vitals["sounds_when_hidden"] is True
        assert bar["type"] == "custom" and bar["rect"] == []
        assert bar["ocr_calibrated"] is False
        assert not ({"read_mode", "color", "direction", "tolerance"} & bar.keys())
        assert stop["percent"] == 0 and stop["direction"] == "below"
        assert stop["delivery"] == "tts"
        assert stop["volume"] == 100 and stop["pitch"] == -10
        assert stop["cooldown"] == 3600

        config.data = {}
        config.verify_settings()
        assert [bar["type"] for bar in config.data["vitals"]["bars"]] == [
            "my_hp", "my_mana", "target_hp", "group_hp"]
        assert all(bar["ocr_calibrated"] is False
                   for bar in config.data["vitals"]["bars"])
        assert config.data["vitals"]["toggled"] is False
    finally:
        config.data = original


def test_target_hp_is_a_default_and_existing_profiles_receive_it_once(
        tmp_path, monkeypatch):
    original = config.data
    monkeypatch.setattr(config, "_filename", str(tmp_path / "config.json"))
    try:
        defaults = default_vital_bars()
        assert [(bar["name"], bar["type"]) for bar in defaults] == [
            ("My HP", "my_hp"), ("My Mana", "my_mana"),
            ("Target / Mob HP", "target_hp"),
            ("Group HP", "group_hp")]

        config.data = {
            "vitals": {
                "bars": [defaults[0]],
                "defaults_version": 0,
            }
        }
        config.verify_settings()
        assert [bar["type"] for bar in config.data["vitals"]["bars"]] == [
            "my_hp", "target_hp"]
        config.data["vitals"]["bars"] = [defaults[0]]
        config.verify_settings()
        assert [bar["type"] for bar in config.data["vitals"]["bars"]] == [
            "my_hp"]
    finally:
        config.data = original


def test_raw_capture_uses_direct_eq_window_while_vantage_is_foreground():
    capture = object.__new__(GameWindowCapture)
    capture._lock = threading.Lock()
    capture._supported = True
    capture._enabled = False
    capture._target = ""
    capture._last_title = ""
    capture._last_message = ""
    capture._fps = 5
    capture._quality_profile = "hd"
    capture._max_width = 1920
    capture._quality = 86
    capture._find_window = lambda: (123, "EverQuest")
    capture._is_window_minimized = lambda _hwnd: False
    capture._game_is_foreground = lambda _hwnd: False
    capture._capture_image = lambda _hwnd: (_image(), (0, 0, 100, 12))
    status, image, rect = capture.image_frame(
        require_enabled=False, require_foreground=True)
    assert status["available"] is True
    assert not image.isNull() and rect == (0, 0, 100, 12)

    capture._game_is_foreground = lambda _hwnd: False
    status, image, rect = capture.image_frame(
        require_enabled=False, require_foreground=False)
    assert status["available"] is True
    assert not image.isNull() and rect == (0, 0, 100, 12)


def test_screen_fallback_remains_blocked_when_eq_is_not_foreground():
    capture = object.__new__(GameWindowCapture)
    capture._capture_error = ""
    capture._game_is_foreground = lambda _hwnd: False
    assert capture._screen_fallback_allowed(123) is False
    assert "safe WinEQ screen fallback" in capture._capture_error

    capture._game_is_foreground = lambda _hwnd: True
    assert capture._screen_fallback_allowed(123) is True


def test_vitals_contains_no_game_input_automation_path():
    source = inspect.getsource(vitals_module).casefold()
    forbidden = ("sendinput", "postmessage", "mouse_event", "keybd_event")
    assert all(token not in source for token in forbidden)


def test_vitals_has_no_fill_reader_or_obsolete_reading_mode_route():
    helper_source = inspect.getsource(vital_helpers_module)
    parser_source = inspect.getsource(vitals_module)
    assert "def analyze_vital_bar" not in helper_source
    assert "def learn_fill_color" not in helper_source
    assert "READ_MODES" not in helper_source
    assert "READ_MODE_LABELS" not in parser_source
    assert "fill_direction" not in parser_source
    assert "color tolerance" not in parser_source.casefold()


def test_quickbar_catalog_exposes_independent_vitals_action_with_unique_icon():
    matches = [item for item in QUICKBAR_ITEMS if item[0] == "vitals"]
    assert matches == [("vitals", "Vitals Monitor", "ph-vitals", "windows")]
    keys = [item[0] for item in QUICKBAR_ITEMS]
    assert keys.index("timers") == keys.index("spells") + 1


def test_numeric_and_keyboard_calibration_are_equivalent_and_bounded(monkeypatch):
    _app()
    announcements = []
    monkeypatch.setattr(
        "vantage.parsers.vitals._announce",
        lambda _widget, message: announcements.append(message))
    bounds = QRect(100, 200, 800, 600)
    controls = CalibrationControls(bounds, QRect(180, 260, 160, 18))
    seen = []
    controls.geometry_changed.connect(lambda rect: seen.append(QRect(rect)))
    controls.x.setValue(90)
    assert seen[-1] == QRect(190, 260, 160, 18)
    controls.nudge(-1, 1)
    assert controls.absolute_rect() == QRect(189, 261, 160, 18)
    assert controls.x.accessibleName() == "Calibration X coordinate"

    overlay = CalibrationOverlay(bounds, QRect(180, 260, 160, 18))
    before = overlay.geometry()
    overlay.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Right,
        Qt.KeyboardModifier.NoModifier))
    QTest.qWait(220)
    assert overlay.geometry().x() == before.x() + 1
    assert announcements and "Calibration area" in announcements[-1]
    assert "Preview invalidated" in announcements[-1]
    overlay.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Down,
        Qt.KeyboardModifier.AltModifier))
    assert overlay.geometry().height() == before.height() + 1
    assert "Arrow keys" in overlay.accessibleDescription()

    cancelled = []
    overlay.cancel_requested.connect(lambda: cancelled.append(True))
    overlay.keyPressEvent(QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier))
    assert cancelled == [True]
    overlay.close()
    controls.close()


def test_numeric_calibration_requires_a_valid_announced_preview_before_save(
        monkeypatch):
    _app()
    announcements = []
    monkeypatch.setattr(
        "vantage.parsers.vitals._announce",
        lambda _widget, message: announcements.append(message))
    image = _number_image(62, scale=3, include_percent=False)
    bounds = QRect(100, 200, image.width(), image.height())
    selected = QRect(bounds)
    bar = sanitize_vital_bar({
        "id": "my-hp", "name": "My HP"})
    owner = type("Owner", (), {})()
    owner._bars = [bar]
    owner._bar_index = lambda bar_id: 0 if bar_id == "my-hp" else -1
    owner._calibration_context = ("my-hp", image, bounds)
    owner._calibration_sample = MethodType(Vitals._calibration_sample, owner)
    controls = CalibrationControls(bounds, selected)
    owner._calibration_controls = controls

    controls.show()
    _app().processEvents()
    controls.fine_tune_button.setChecked(True)
    _app().processEvents()
    controls.x.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(controls.x, Qt.Key.Key_Tab)
    assert controls.focusWidget() is controls.y
    assert controls._save_button.isEnabled() is False
    assert "loosely around one visible" in controls.findChildren(QLabel)[0].text().casefold()
    assert controls.fine_tune_button.accessibleName() == (
        "Fine position (optional)")
    assert "Toggle coordinates" in (
        controls.fine_tune_button.accessibleDescription())
    assert controls.preview_button.accessibleName() == (
        "Validate vital reading preview")
    Vitals._preview_calibration(owner, "my-hp", selected)
    assert controls._save_button.isEnabled() is True
    assert "Detected 62%" in controls.status.text()
    assert "fitted reading area" in controls.status.text()
    assert announcements[-1] == controls.status.text()

    controls.nudge(1, 0)
    assert controls._save_button.isEnabled() is False
    assert "validate" in controls.status.text().casefold()

    blank = QImage(image.size(), image.format())
    blank.fill(QColor("#101820"))
    owner._calibration_context = ("my-hp", blank, bounds)
    Vitals._preview_calibration(owner, "my-hp", selected)
    assert controls._save_button.isEnabled() is False
    assert "Invalid preview" in controls.status.text()
    controls.close()


def test_closing_calibration_restores_focus_to_invoking_bar_action():
    _app()
    focused = []
    button = QPushButton("Calibrate")
    owner = type("Owner", (), {})()
    owner._calibration_context = ("my-hp", QImage(), QRect())
    owner._calibration_overlay = None
    owner._calibration_controls = None
    owner._calibration_focus_target = ("my-hp", "calibrate")
    owner._cards = {
        "my-hp": type("Card", (), {
            "action_buttons": {"calibrate": button}})()}
    owner._add_button = QPushButton("Add")
    owner.isVisible = lambda: True
    owner._focus_embedded_control = lambda control: focused.append(control)
    owner.poll_now = lambda: None
    owner._clear_calibration_refs = MethodType(
        Vitals._clear_calibration_refs, owner)

    Vitals._finish_calibration(owner)
    QTest.qWait(10)

    assert focused == [button]
    assert owner._calibration_focus_target is None


def test_apply_calibration_revalidates_and_refuses_an_unreadable_number():
    _app()
    blank = QImage(80, 24, QImage.Format.Format_RGB32)
    blank.fill(QColor("#101820"))
    bounds = QRect(0, 0, blank.width(), blank.height())
    bar = sanitize_vital_bar({
        "id": "my-hp", "name": "My HP"})
    owner = type("Owner", (), {})()
    owner._bars = [bar]
    owner._bar_index = lambda bar_id: 0 if bar_id == "my-hp" else -1
    owner._calibration_context = ("my-hp", blank, bounds)
    owner._calibration_sample = MethodType(Vitals._calibration_sample, owner)
    owner._calibration_controls = CalibrationControls(
        bounds, bounds)
    owner._finish_calibration = lambda: None
    owner._persist = lambda: (_ for _ in ()).throw(
        AssertionError("invalid calibration must not persist"))

    Vitals._apply_calibration(owner, "my-hp", bounds)

    assert owner._bars[0]["rect"] == []
    assert owner._calibration_controls._save_button.isEnabled() is False
    assert "not saved" in owner._calibration_controls.status.text().casefold()
    owner._calibration_controls.close()


def test_apply_valid_numeric_calibration_marks_and_persists_ocr_roi():
    _app()
    image = _number_image(75, scale=2)
    bounds = QRect(20, 30, image.width(), image.height())
    bar = sanitize_vital_bar({"id": "my-hp", "name": "My HP"})
    calls = []
    owner = type("Owner", (), {})()
    owner._bars = [bar]
    owner._bar_index = lambda bar_id: 0 if bar_id == "my-hp" else -1
    owner._calibration_context = ("my-hp", image, bounds)
    owner._calibration_sample = MethodType(Vitals._calibration_sample, owner)
    owner._calibration_controls = CalibrationControls(bounds, bounds)
    owner._tracker = type("Tracker", (), {
        "reset_bar": lambda _self, bar_id: calls.append(("reset", bar_id))})()
    owner._persist = lambda: calls.append(("persist", None))
    owner._rebuild_cards = lambda target: calls.append(("rebuild", target))
    owner._finish_calibration = lambda: calls.append(("finish", None))
    owner._set_status = lambda status: calls.append(("status", status))
    owner.poll_now = lambda: None

    Vitals._apply_calibration(owner, "my-hp", bounds)

    saved = owner._bars[0]["rect"]
    # This fixture is already cropped to the number plus only four pixels of
    # canvas, so the stable margin correctly saturates at the image bounds.
    assert saved == [0.0, 0.0, 1.0, 1.0]
    assert read_vital_bar(image, owner._bars[0]).percent == 75.0
    assert owner._bars[0]["ocr_calibrated"] is True
    assert ("persist", None) in calls
    assert any(call[0] == "status" and "validated 75% visible number" in call[1]
               for call in calls)
    owner._calibration_controls.close()


def test_loose_calibration_persists_a_fitted_offset_token_rect():
    _app()
    image, _token = _padded_number_image(
        83, canvas=(180, 72), offset=(68, 25), frame=True)
    bounds = QRect(300, 400, image.width(), image.height())
    bar = sanitize_vital_bar({"id": "my-hp", "name": "My HP"})
    owner = type("Owner", (), {})()
    owner._bars = [bar]
    owner._bar_index = lambda bar_id: 0 if bar_id == "my-hp" else -1
    owner._calibration_context = ("my-hp", image, bounds)
    owner._calibration_sample = MethodType(Vitals._calibration_sample, owner)
    owner._calibration_controls = CalibrationControls(bounds, bounds)
    owner._tracker = type("Tracker", (), {"reset_bar": lambda *_args: None})()
    owner._persist = lambda: None
    owner._rebuild_cards = lambda _target: None
    owner._finish_calibration = lambda: None
    owner._set_status = lambda _status: None
    owner.poll_now = lambda: None

    Vitals._apply_calibration(owner, "my-hp", bounds)

    saved = owner._bars[0]["rect"]
    x, y, width, height = denormalize_rect(
        saved, (image.width(), image.height()))
    assert x > 0 and y > 0
    assert width < image.width() / 2 and height < image.height() / 2
    assert x <= 68 + 4 and y <= 25 + 4
    reading = read_vital_bar(image, owner._bars[0])
    assert reading.valid is True and reading.percent == 83.0
    owner._calibration_controls.close()


def test_calibration_saves_drift_tolerant_roi_and_survives_reload_recalibration(
        monkeypatch):
    _app()
    foreground = "#45d483"
    initial, token = _eq_bitmap_number_image(
        25, canvas=(120, 44), offset=(28, 14), color=foreground,
        bars=((40, 10, 70, 16, foreground),))
    bounds = QRect(300, 400, initial.width(), initial.height())
    bar = sanitize_vital_bar({"id": "my-hp", "name": "My HP"})
    persisted = []
    monkeypatch.setitem(config.data, "vitals", {"bars": []})

    def capture_save():
        persisted[:] = json.loads(json.dumps(
            config.data["vitals"]["bars"]))

    monkeypatch.setattr(config, "save", capture_save)
    owner = type("Owner", (), {})()
    owner._bars = [bar]
    owner._bar_index = lambda bar_id: 0 if bar_id == "my-hp" else -1
    owner._calibration_context = ("my-hp", initial, bounds)
    owner._calibration_sample = MethodType(Vitals._calibration_sample, owner)
    owner._calibration_controls = CalibrationControls(bounds, bounds)
    owner._tracker = type(
        "Tracker", (), {"reset_bar": lambda *_args: None})()
    owner._persist = MethodType(Vitals._persist, owner)
    owner._rebuild_cards = lambda _target: None
    owner._finish_calibration = lambda: None
    owner._set_status = lambda _status: None
    owner.poll_now = lambda: None

    Vitals._apply_calibration(owner, "my-hp", bounds)

    saved = owner._bars[0]["rect"]
    saved_pixels = denormalize_rect(
        saved, (initial.width(), initial.height()))
    saved_x, saved_y, saved_width, saved_height = saved_pixels
    token_x, token_y, token_width, token_height = token
    assert saved_x <= token_x - 5
    assert saved_y <= token_y - 4
    assert saved_x + saved_width >= token_x + token_width + 5
    assert saved_y + saved_height >= token_y + token_height + 4
    assert saved_width < initial.width() / 3
    assert saved_height < initial.height() / 2
    assert persisted and persisted[0]["ocr_calibrated"] is True

    # The live frame moves two pixels in both axes, loses one captured stroke
    # pixel, and still places a same-color bar within the saved padded ROI.
    shifted, _shifted_token = _eq_bitmap_number_image(
        25, canvas=(120, 44), offset=(30, 16), color=foreground,
        bars=((42, 12, 70, 16, foreground),), missing_pixels=(3,))
    restored = sanitize_vital_bars(
        json.loads(json.dumps(persisted)))[0]
    shifted_reading = read_vital_bar(shifted, restored)
    assert shifted_reading.valid is True
    assert shifted_reading.percent == 25.0

    # Repositioning an already persisted monitor uses the padded selection,
    # validates the new frame, and saves another stable normalized ROI.
    owner._bars = [restored]
    owner._calibration_context = ("my-hp", shifted, bounds)
    relative = denormalize_rect(
        restored["rect"], (shifted.width(), shifted.height()))
    selected = QRect(
        bounds.x() + relative[0], bounds.y() + relative[1],
        relative[2], relative[3])
    Vitals._apply_calibration(owner, "my-hp", selected)
    recalibrated = sanitize_vital_bars(
        json.loads(json.dumps(persisted)))[0]
    final, _final_token = _eq_bitmap_number_image(
        25, canvas=(120, 44), offset=(29, 15), color=foreground,
        bars=((41, 11, 70, 16, foreground),))
    final_reading = read_vital_bar(final, recalibrated)
    assert final_reading.valid is True
    assert final_reading.percent == 25.0
    owner._calibration_controls.close()


def test_stop_editor_exposes_delivery_sound_tts_off_and_tokens(monkeypatch):
    _app()
    monkeypatch.setattr(
        "vantage.parsers.vitals.speech_voice_names", lambda: ["Voice One"])
    dialog = VitalStopDialog({
        "delivery": "tts", "tts_text": "{name} {percent} {direction}",
        "voice": "Voice One", "volume": 42, "pitch": -3,
    })
    assert [dialog.delivery.itemData(index) for index in range(3)] == [
        "sound", "tts", "off"]
    assert dialog.delivery.currentData() == "tts"
    assert dialog.tts_text.toolTip().find("{name}") >= 0
    value = dialog.value()
    assert value["voice"] == "Voice One"
    assert value["volume"] == 42 and value["pitch"] == -3
    assert dialog.sound.accessibleName() == "Vital alert sound gallery"
    dialog.show()
    _app().processEvents()
    dialog.delivery.setCurrentIndex(dialog.delivery.findData("sound"))
    _app().processEvents()
    assert dialog.volume.isVisibleTo(dialog)
    dialog.delivery.setCurrentIndex(dialog.delivery.findData("tts"))
    _app().processEvents()
    assert dialog.volume.isVisibleTo(dialog)
    dialog.close()


def test_vital_bar_has_one_numeric_reading_flow_and_no_obsolete_controls():
    _app()
    dialog = VitalBarDialog(default_vital_bars()[0])
    description = dialog.enabled.accessibleDescription()
    assert "Direct capture can continue while Vantage is in focus" in description
    assert "safe screen capture may require EverQuest" in description
    assert not hasattr(dialog, "read_mode")
    assert not hasattr(dialog, "fill_direction")
    assert not hasattr(dialog, "tolerance")
    visible_copy = " ".join(
        label.text() for label in dialog.findChildren(QLabel)).casefold()
    assert all(term not in visible_copy
               for term in ("bar fill", "color tolerance", "legacy", "fallback"))
    dialog.close()


@pytest.mark.parametrize("bar_type", [
    "my_hp", "my_mana", "target_hp", "group_hp", "custom",
])
def test_overlay_editor_exposes_accessible_full_alert_silence_for_every_type(
        bar_type):
    app = _app()
    bar = default_vital_bar("test", "Test overlay", bar_type)
    dialog = VitalBarDialog(bar)
    dialog.show()
    app.processEvents()

    control = dialog.silence_full_alerts
    assert control.text() == "Mute sound and speech at 100%"
    assert control.accessibleName() == "Mute sound and speech at 100%"
    description = control.accessibleDescription()
    assert "Sound and text-to-speech" in description
    assert "this overlay reads 100%" in description
    assert "Visual notifications" in description
    assert "lower alert stops remain active" in description
    assert dialog.silence_full_label.text() == "Full-health audio"
    assert dialog.silence_full_label.buddy() is control
    assert control.isChecked() is (bar_type == "target_hp")

    dialog.name.setFocus(Qt.FocusReason.TabFocusReason)
    for expected in (dialog.kind, dialog.enabled, control, dialog.stop_list):
        QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
        app.processEvents()
        assert dialog.focusWidget() is expected

    control.setChecked(not control.isChecked())
    saved_choice = control.isChecked()
    dialog.kind.setCurrentIndex(dialog.kind.findData(
        "custom" if bar_type == "target_hp" else "target_hp"))
    assert dialog.value()["silence_full_alerts"] is saved_choice
    dialog.close()


def test_target_full_alert_silence_mutes_audio_but_preserves_visual_and_lower(
        monkeypatch):
    notifications = []
    deliveries = []

    class OverlayApp:
        def show_overlay_notification(self, *args, **kwargs):
            notifications.append((args, kwargs))

    class FakeApplication:
        @staticmethod
        def instance():
            return OverlayApp()

    monkeypatch.setattr(vitals_module, "QApplication", FakeApplication)
    owner = type("Owner", (), {})()
    owner._play_delivery = lambda *args: deliveries.append(args) or True
    bar = sanitize_vital_bar({
        "id": "target", "name": "Target HP", "type": "target_hp",
        "stops": [
            dict(default_vital_stop(75, "below", 0), cooldown=0),
            dict(default_vital_stop(50, "below", 1), cooldown=0,
                 delivery="tts"),
            dict(default_vital_stop(100, "full", 2), cooldown=0),
        ],
    })
    tracker = VitalStopTracker()

    def update(percent, now):
        events = tracker.update(
            bar["id"], percent, bar["stops"], confidence=1.0, now=now)
        for stop, crossed in events:
            Vitals._deliver_stop(owner, bar, stop, percent, crossed)
        return [crossed for _stop, crossed in events]

    assert update(80, 0) == []
    assert update(74, 1) == ["below"]
    assert update(49, 2) == ["below"]
    assert len(notifications) == 2 and len(deliveries) == 2

    # The tracker emits and advances its full state. The accessible visual
    # notification remains, while the Sound route is muted. Holding at 100
    # cannot create a stale second alert.
    assert update(100, 3) == ["full"]
    assert update(100, 4) == []
    assert len(notifications) == 3 and len(deliveries) == 2

    # Damage rearms the tracker. Muting applies equally to a TTS full stop,
    # while its visual notice remains; disabling the per-overlay choice then
    # restores the speech delivery too.
    bar["stops"][2]["delivery"] = "tts"
    assert update(96, 5) == []
    assert update(100, 6) == ["full"]
    assert len(notifications) == 4 and len(deliveries) == 2
    bar["silence_full_alerts"] = False
    assert update(96, 7) == []
    assert update(100, 8) == ["full"]
    assert len(notifications) == 5 and len(deliveries) == 3
    assert deliveries[-1][0]["delivery"] == "tts"


def test_overlay_name_validation_is_visible_associated_and_keyboard_focused():
    app = _app()
    dialog = VitalBarDialog(default_vital_bars()[0])
    dialog.show()
    app.processEvents()
    assert dialog.windowTitle() == "Edit overlay"
    assert dialog.name_label.text() == "Overlay name"
    assert dialog.name_label.buddy() is dialog.name
    assert dialog.name.accessibleName() == "Overlay name"
    save = dialog.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Save)
    assert save.text() == "Save overlay"
    assert save.accessibleName() == "Save overlay"

    dialog.name.setText("   ")
    dialog.stop_list.setFocus()
    dialog._validate()
    app.processEvents()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.name.hasFocus()
    assert dialog.name_error.isVisibleTo(dialog)
    assert dialog.name_error.text() == "Enter an overlay name."
    assert dialog.name_error.accessibleName() == "Overlay name error"
    assert "Error: Enter an overlay name." in (
        dialog.name.accessibleDescription())

    dialog.name.setText("Raid target HP")
    app.processEvents()
    assert not dialog.name_error.isVisibleTo(dialog)
    assert dialog.name_error.text() == ""
    assert not dialog.name.accessibleDescription().startswith("Error:")
    QTest.keyClick(dialog.name, Qt.Key.Key_Tab)
    app.processEvents()
    assert dialog.kind.hasFocus()
    dialog.close()


def test_runtime_delivery_passes_sound_and_tts_profile_controls(monkeypatch):
    played = []
    spoken = []
    monkeypatch.setattr(
        "vantage.parsers.vitals.play_alert",
        lambda *args, **kwargs: played.append((args, kwargs)) or True)
    monkeypatch.setattr(
        "vantage.parsers.vitals.speak_text",
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True)
    owner = type("Owner", (), {
        "_active_character": "Mindflux", "_active_server": "Green"})()
    sound = default_vital_stop(25)
    sound.update({"delivery": "sound", "sound": "builtin:soft-tick",
                  "volume": 37})
    assert Vitals._play_delivery(owner, sound, "My HP", 24, "below")
    assert played[0][0][:2] == ("builtin:soft-tick", 37)
    assert played[0][1]["channel"] == "vitals"
    assert played[0][1]["character"] == "Mindflux"
    assert played[0][1]["server"] == "Green"
    assert played[0][1]["allow_hidden"] is False

    voice = dict(sound)
    voice.update({
        "delivery": "tts", "tts_text": "{name}: {percent}, {direction}",
        "voice": "Narrator", "volume": 52, "pitch": 6})
    assert Vitals._play_delivery(owner, voice, "My Mana", 49.6, "above")
    assert spoken[0][0][:2] == ("My Mana: 50, above", 52)
    assert spoken[0][1]["voice_name"] == "Narrator"
    assert spoken[0][1]["pitch"] == 6
    assert spoken[0][1]["channel"] == "vitals"


def test_monitor_state_transitions_are_announced_once(monkeypatch):
    _app()
    announcements = []
    monkeypatch.setattr(
        "vantage.parsers.vitals._announce",
        lambda _widget, message: announcements.append(message))
    emitted = []
    owner = type("Owner", (), {})()
    owner._status_text = "NO READING · waiting"
    owner._status_badge = QLabel("NO READING")
    owner.status_changed = type("Signal", (), {
        "emit": lambda _self: emitted.append(True)})()
    Vitals._set_status(owner, "ACTIVE · 2 live readings")
    Vitals._set_status(owner, "ACTIVE · 2 live readings")
    assert announcements == ["ACTIVE · 2 live readings"]
    assert emitted == [True]


def test_existing_overlay_can_be_renamed_without_changing_monitor_data(
        tmp_path):
    script = r'''
import copy
import json
from PySide6.QtWidgets import QDialog
from vantage.helpers import config
from vantage.helpers.application import VantageApp
from vantage.parsers.vitals import VitalBarDialog

config.data["general"]["startup_window_state"] = "normal"
app = VantageApp([])
vitals = app._parsers_dict["vitals"]
bar_id = vitals._bars[0]["id"]
vitals._bars[0]["ocr_calibrated"] = True
vitals._bars[0]["rect"] = [0.11, 0.22, 0.19, 0.08]
vitals._persist()
vitals._rebuild_cards()
before = copy.deepcopy(vitals._bars[0])

def rename_and_accept(dialog):
    dialog.name.setText("Spiritflux target HP")
    dialog._validate()
    return dialog.result()

VitalBarDialog.exec = rename_and_accept
vitals._edit_bar(bar_id)
app.processEvents()
after = copy.deepcopy(vitals._bars[0])
card = vitals._cards[bar_id]
print(json.dumps({
    "accepted": after["name"] == "Spiritflux target HP",
    "stored_name": config.data["vitals"]["bars"][0]["name"],
    "card_label": card.name_label.text(),
    "card_accessible": card.accessibleName(),
    "edit_text": card.action_buttons["edit"].text(),
    "edit_accessible": card.action_buttons["edit"].accessibleName(),
    "same_id": after["id"] == before["id"],
    "same_rect": after["rect"] == before["rect"],
    "same_stops": after["stops"] == before["stops"],
    "same_type": after["type"] == before["type"],
    "same_enabled": after["enabled"] == before["enabled"],
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {
        "accepted": True,
        "stored_name": "Spiritflux target HP",
        "card_label": "Spiritflux target HP",
        "card_accessible": "Spiritflux target HP vital bar",
        "edit_text": "Edit overlay",
        "edit_accessible": "Edit overlay Spiritflux target HP",
        "same_id": True,
        "same_rect": True,
        "same_stops": True,
        "same_type": True,
        "same_enabled": True,
    }


def test_vitals_mini_replica_rollup_and_expanded_size_restore(tmp_path):
    script = r'''
import json
from PySide6.QtTest import QTest
from vantage.helpers import config
from vantage.helpers.application import VantageApp

config.data["general"]["startup_window_state"] = "normal"
app = VantageApp([])
vitals = app._parsers_dict["vitals"]
vitals._set_collapsed(False)
vitals.show()
vitals._set_replica_scale(0.35)
QTest.qWait(30)
app.processEvents()
mini = [vitals.width(), vitals.height()]
mini_scale = vitals._scale_view.transform().m11()
roll_name = vitals._roll_button.accessibleName()
vitals._focus_embedded_control(vitals._roll_button)
roll_focused = vitals._surface.focusWidget() is vitals._roll_button

vitals._set_collapsed(True)
QTest.qWait(30)
app.processEvents()
rolled = [vitals.width(), vitals.height()]
content_hidden = all(
    not vitals.content.itemAt(index).widget().isVisible()
    for index in range(1, vitals.content.count())
    if vitals.content.itemAt(index).widget() is not None)
saved_while_rolled = config.data["vitals"]["geometry"][2:]
expand_name = vitals._roll_button.accessibleName()
collapsed_saved = config.data["vitals"]["collapsed"]

vitals._set_collapsed(False)
QTest.qWait(30)
app.processEvents()
expanded = [vitals.width(), vitals.height()]
expanded_scale = vitals._scale_view.transform().m11()
print(json.dumps({
    "design": [vitals._design_size.width(), vitals._design_size.height()],
    "mini": mini,
    "mini_scale": mini_scale,
    "roll_name": roll_name,
    "roll_focused": roll_focused,
    "rolled": rolled,
    "content_hidden": content_hidden,
    "saved_while_rolled": saved_while_rolled,
    "expand_name": expand_name,
    "collapsed_saved": collapsed_saved,
    "expanded": expanded,
    "expanded_scale": expanded_scale,
    "expanded_saved": config.data["vitals"]["geometry"][2:],
    "expanded_collapsed": config.data["vitals"]["collapsed"],
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    expected_mini = [
        round(result["design"][0] * 0.35),
        round(result["design"][1] * 0.35)]
    assert result["mini"] == expected_mini
    assert result["mini_scale"] == pytest.approx(0.35, abs=0.01)
    assert result["roll_name"] == "Roll up panel"
    assert result["roll_focused"] is True
    assert result["rolled"][1] <= 24
    assert result["content_hidden"] is True
    assert result["saved_while_rolled"] == expected_mini
    assert result["expand_name"] == "Expand panel"
    assert result["collapsed_saved"] is True
    assert result["expanded"] == expected_mini
    assert result["expanded_scale"] == pytest.approx(0.35, abs=0.01)
    assert result["expanded_saved"] == expected_mini
    assert result["expanded_collapsed"] is False


def test_direct_background_frame_drives_reading_and_calibration_status(tmp_path):
    script = r'''
import json
from PySide6.QtGui import QColor, QImage
from vantage.helpers.application import VantageApp

class DirectEverQuestCapture:
    def __init__(self):
        self.image = QImage(100, 30, QImage.Format.Format_RGB32)
        self.image.fill(QColor(12, 14, 18))
        glyphs = {
            "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
            "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
            "%": ("11001", "11010", "00100", "00100", "01000", "10110", "00110"),
        }
        x_offset = 6
        for glyph in "64%":
            for row, bits in enumerate(glyphs[glyph]):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        for dy in range(2):
                            for dx in range(2):
                                self.image.setPixelColor(
                                    x_offset + column * 2 + dx,
                                    7 + row * 2 + dy, QColor(242, 207, 104))
            x_offset += 12
    def image_frame(self, **_kwargs):
        # Models PrintWindow/window-DC success while the Vantage panel owns
        # foreground focus.
        return ({"available": True, "message": "Direct EQ capture"},
                self.image.copy(), (40, 50, 100, 30))
    def set_executable(self, _path):
        pass

app = VantageApp([])
vitals = app._parsers_dict["vitals"]
vitals._capture = DirectEverQuestCapture()
vitals._bars[0]["ocr_calibrated"] = True
vitals._bars[0]["rect"] = [0, 0, 1, 1]
for bar in vitals._bars[1:]:
    bar["enabled"] = False
vitals.poll_now()
active = vitals.quickbar_status()
reading = vitals._readings["my-hp"]
vitals._start_calibration("my-hp")
app.processEvents()
calibrating = vitals.quickbar_status()
controls_visible = vitals._calibration_controls.isVisible()
overlay_visible = vitals._calibration_overlay.isVisible()
focus_name = vitals._calibration_controls.focusWidget().accessibleName()
vitals._start_calibration("my-mana")
app.processEvents()
replacement_bar = vitals._calibration_context[0]
replacement_focus = vitals._calibration_controls.focusWidget().accessibleName()
vitals._finish_calibration()
app.processEvents()
vitals.close()
app.processEvents()
print(json.dumps({
    "active": active,
    "percent": reading.percent,
    "valid": reading.valid,
    "calibrating": calibrating,
    "controls_visible": controls_visible,
    "overlay_visible": overlay_visible,
    "focus_name": focus_name,
    "replacement_bar": replacement_bar,
    "replacement_focus": replacement_focus,
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["active"] == "ACTIVE · 1 live reading"
    assert result["valid"] is True and result["percent"] == 64.0
    assert result["calibrating"] == "CALIBRATING · My HP"
    assert result["controls_visible"] is True
    assert result["overlay_visible"] is True
    assert result["focus_name"] == "Validate vital reading preview"
    assert result["replacement_bar"] == "my-mana"
    assert result["replacement_focus"] == "Validate vital reading preview"


def test_application_registers_and_quickbar_toggles_vitals(tmp_path):
    script = r'''
import json
from PySide6.QtGui import QFont, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QProgressBar
from vantage.helpers.application import VantageApp

class NoReading:
    def image_frame(self, **_kwargs):
        return ({"available": False, "message": "EQ is not foreground"}, QImage(), ())
    def set_executable(self, _path):
        pass

app = VantageApp([])
vitals = app._parsers_dict["vitals"]
bar = app._parsers_dict["quickbar"]
vitals._capture = NoReading()
vitals.poll_now()
bar.refresh_state()
before = vitals.isVisible()
bar._trigger("vitals")
app.processEvents()
opened = (vitals.isVisible(), bar._buttons["vitals"].isChecked())
vitals.resize(240, 600)
app.processEvents()
vitals._update_uniform_scale()
card = vitals._cards["my-hp"]
large_font = QFont(card.font())
large_font.setPointSize(15)
for control in [vitals._add_button, *card.action_buttons.values()]:
    control.setFont(large_font)
app.processEvents()
card_actions = card.action_buttons
action_rects = [control.geometry() for control in card_actions.values()]
actions_do_not_overlap = all(
    not first.intersects(second)
    for index, first in enumerate(action_rects)
    for second in action_rects[index + 1:])
text_fits = all(
    control.width() >= control.fontMetrics().horizontalAdvance(control.text()) + 12
    for control in [vitals._add_button, *card_actions.values()])
visible_copy = " ".join(
    label.text() for label in vitals._surface.findChildren(type(vitals._status_badge)))
vitals._focus_embedded_control(vitals._add_button)
vitals._surface.focusNextChild()
tab_after_add = vitals._surface.focusWidget().accessibleName()
responsive = {
    "width": vitals.width(),
    "surface_width": vitals._surface.width(),
    "scale": vitals._scale_view.transform().m11(),
    "button_height": vitals._cards["my-hp"].action_buttons["edit"].height(),
}
hierarchy = {
    "add_in_header": vitals.menu_area.indexOf(vitals._add_button) >= 0,
    "add_in_content": vitals._content_actions.isAncestorOf(vitals._add_button),
    "add_visible": vitals._add_button.isVisibleTo(vitals._surface),
    "add_text": vitals._add_button.text(),
    "guide": [label.text() for label in vitals._guide.step_labels],
    "guide_columns": vitals._guide.step_bar._columns,
    "has_long_copy": "All enabled numbers are read together" in visible_copy,
    "has_progress": bool(card.findChildren(QProgressBar)),
    "value_object": card.value_label.objectName(),
    "state": card.state_label.text(),
    "detail": card.detail.text(),
    "actions": [control.text() for control in card_actions.values()],
    "card_count": len(vitals._cards),
    "actions_do_not_overlap": actions_do_not_overlap,
    "text_fits": text_fits,
    "tab_after_add": tab_after_add,
}
edit = vitals._cards["my-hp"].action_buttons["edit"]
vitals._focus_embedded_control(edit)
vitals._rebuild_cards()
QTest.qWait(20)
app.processEvents()
focused = vitals._surface.focusWidget()
restored_focus = focused.accessibleName() if focused is not None else ""
QMessageBox.question = staticmethod(
    lambda *_args: QMessageBox.StandardButton.Yes)
vitals._remove_bar("my-hp")
QTest.qWait(20)
app.processEvents()
focused = vitals._surface.focusWidget()
remove_focus = focused.accessibleName() if focused is not None else ""
vitals._rebuild_cards(("my-mana", "calibrate"))
QTest.qWait(20)
app.processEvents()
focused = vitals._surface.focusWidget()
calibration_focus = focused.accessibleName() if focused is not None else ""
bar._trigger("vitals")
app.processEvents()
closed = (vitals.isVisible(), bar._buttons["vitals"].isChecked())
print(json.dumps({
    "registered": vitals in app._parsers,
    "before": before, "opened": opened, "closed": closed,
    "tooltip": bar._buttons["vitals"].toolTip(),
    "status": vitals.quickbar_status(),
    "responsive": responsive,
    "hierarchy": hierarchy,
    "restored_focus": restored_focus,
    "remove_focus": remove_focus,
    "calibration_focus": calibration_focus,
}))
app.quit()
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["registered"] is True and result["before"] is False
    assert result["opened"] == [True, True]
    assert result["closed"] == [False, False]
    assert result["status"].startswith("NO READING")
    assert "NO READING" in result["tooltip"]
    assert result["responsive"] == {
        "width": 240, "surface_width": 560,
        "scale": pytest.approx(240 / 560, abs=0.01),
        "button_height": result["responsive"]["button_height"]}
    assert result["responsive"]["button_height"] >= 30
    assert result["hierarchy"] == {
        "add_in_header": False,
        "add_in_content": True,
        "add_visible": True,
        "add_text": "Add monitor",
        "guide": [
            "Place overlay over %", "Validate reading", "Set alert stops"],
        "guide_columns": 3,
        "has_long_copy": False,
        "has_progress": False,
        "value_object": "SpawnTimerTime",
        "state": "SETUP",
        "detail": "Next: place the overlay over the visible % number",
        "actions": [
            "Monitoring on", "Calibrate", "Edit overlay", "Remove"],
        "card_count": 4,
        "actions_do_not_overlap": True,
        "text_fits": True,
        "tab_after_add": "Monitor My HP",
    }
    assert result["restored_focus"] == "Edit overlay My HP"
    assert result["remove_focus"] == "Monitor My Mana"
    assert result["calibration_focus"] == "Calibrate My Mana"
