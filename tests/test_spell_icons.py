import hashlib
import datetime
import copy
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame

from vantage.helpers import config
from vantage.helpers.spell_icons import spell_icon_pixmap
from vantage.parsers.spells import (
    SpellWidget, _spell_icon_accent, _spell_icon_coordinates, _spell_target_sort_key,
    _spell_widget_sort_key,
    create_spell_book, spell_progress_palette, spell_progress_stylesheet,
    spell_school_name, spell_warning_state)


def test_velious_zero_based_sheet_mapping():
    assert _spell_icon_coordinates(0) == (1, 0, 0)
    assert _spell_icon_coordinates(35) == (1, 200, 200)
    assert _spell_icon_coordinates(36) == (2, 0, 0)
    assert _spell_icon_coordinates(143) == (4, 200, 200)
    assert _spell_icon_coordinates(215) == (6, 200, 200)


def test_velious_gem_sheet_integrity():
    sheet = Path("data/spells/spells04.png")
    digest = hashlib.sha256(sheet.read_bytes()).hexdigest().upper()

    assert digest == "FE05B9B3132E3E8DEFB453D5B5AF164DAA75F149118F76ADEE5F85873033739B"


def test_velious_gem_sheet_is_full_color_not_monochrome():
    image = QImage("data/spells/spells04.png")
    sampled = {
        (image.pixelColor(x, y).red(), image.pixelColor(x, y).green(),
         image.pixelColor(x, y).blue())
        for y in range(0, image.height(), 4)
        for x in range(0, image.width(), 4)
    }

    assert len(sampled) > 500
    assert any(max(color) - min(color) > 80 for color in sampled)


def test_velious_spell_icons_keep_crisp_art_with_rounded_corners():
    app = QApplication.instance() or QApplication([])
    image = spell_icon_pixmap(143, 20).toImage()

    assert app is not None
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(10, 10).alpha() == 255


def test_spell_icon_accent_stays_dark_enough_for_overlay_text():
    # The label spans filled and unfilled pixels, so every icon-derived fill
    # keeps enough luminance headroom for the same off-white text.
    for icon_index in (0, 5, 18, 42, 77, 118, 146):
        assert _spell_icon_accent(icon_index).value() <= 122


def test_spell_warning_has_yellow_and_fast_red_stages():
    assert spell_warning_state(41, 40, False, 0.0) == (
        False, False, False, 1000)
    assert spell_warning_state(40, 40, False, 1.0) == (
        True, False, True, 1000)
    assert spell_warning_state(20, 40, False, 0.25) == (
        True, True, True, 250)
    assert spell_warning_state(20, 40, True, 0.25) == (
        True, True, False, 1000)


def test_visible_game_spells_use_the_exact_icon_ids():
    spell_book, _, _ = create_spell_book()

    assert spell_book["Clarity II"].spell_icon == 143
    assert spell_book["Illusion: Werewolf"].spell_icon == 43
    assert spell_book["See Invisible"].spell_icon == 138
    assert spell_book["Visions of Grandeur"].spell_icon == 155


def test_client_spell_skill_field_maps_the_five_casting_schools():
    spell_book, _, _ = create_spell_book()

    expected = {
        "Cancel Magic": (4, "Abjuration"),
        "Clarity II": (5, "Alteration"),
        "Summon Food": (14, "Conjuration"),
        "See Invisible": (18, "Divination"),
        "Shock of Lightning": (24, "Evocation"),
    }
    for name, (skill, school) in expected.items():
        assert spell_book[name].skill == skill
        assert spell_school_name(spell_book[name]) == school
    # Bar colors now follow the exact icon artwork, independently of the
    # textual casting-school classification.
    assert len({
        spell_progress_palette(spell_book[name]) for name in expected
    }) >= 3


def test_current_p99_spell_index_maps_spirit_of_wolf():
    spell_book, _, _ = create_spell_book()

    assert spell_book["Spirit of Wolf"].spell_icon == 155


class _TargetType:

    def __init__(self, value):
        self.value = value

    def property(self, _name):
        return self.value


def _target(name, target_type, activity):
    return SimpleNamespace(
        name=name,
        last_activity_order=activity,
        target_label=_TargetType(target_type))


def test_recently_affected_mob_sorts_first_inside_enemy_section():
    older = _target("A crystalline watcher", 2, 4)
    latest = _target("A crystalline devourer", 2, 9)
    you = _target("__you__", 0, 1)

    assert sorted(
        [older, latest, you], key=_spell_target_sort_key) == [
            you, latest, older]


def test_spell_rows_sort_by_soonest_expiry_then_name():
    now = __import__('datetime').datetime.now()
    later = SimpleNamespace(
        end_time=now + __import__('datetime').timedelta(seconds=90),
        spell=SimpleNamespace(name='Root'))
    sooner_b = SimpleNamespace(
        end_time=now + __import__('datetime').timedelta(seconds=20),
        spell=SimpleNamespace(name='Tashanian'))
    sooner_a = SimpleNamespace(
        end_time=sooner_b.end_time,
        spell=SimpleNamespace(name='Malo'))

    assert sorted(
        [later, sooner_b, sooner_a], key=_spell_widget_sort_key) == [
            sooner_a, sooner_b, later]


def test_spell_progress_palette_is_stable_colorful_and_icon_driven():
    beneficial = SimpleNamespace(
        name="Spirit of Wolf", spell_icon=155, type=1, resist_type=0,
        skill=5)
    evocation = SimpleNamespace(
        name="Shock of Lightning", spell_icon=24, type=0, resist_type=3,
        skill=24)

    assert spell_progress_palette(beneficial) == spell_progress_palette(
        beneficial)
    assert spell_progress_palette(beneficial) != spell_progress_palette(
        evocation)
    for palette in (spell_progress_palette(beneficial),
                    spell_progress_palette(evocation)):
        for color in palette[:3]:
            red, green, blue = (
                int(color[index:index + 2], 16) for index in (1, 3, 5))
            assert max(red, green, blue) - min(red, green, blue) >= 20
    assert all(
        max(int(color[index:index + 2], 16) for index in (1, 3, 5)) < 180
        for color in spell_progress_palette(beneficial)[:3])
    style = spell_progress_stylesheet(beneficial)
    assert "qlineargradient" not in style
    assert "background-color" in style
    assert "Pulse" in style
    assert 'QProgressBar[Faded="true"]' in style
    assert "#D13E48" in style
    assert "min-height: 20px" in style
    assert "max-height: 20px" in style
    assert "padding: 0px" in style
    assert "border-radius: 5px" in style
    assert "#9A6515" in style
    assert "#BC353C" in style
    assert "box-shadow" not in style


def test_spell_row_is_two_pixels_shorter_without_clipping_the_progress_bar():
    app = QApplication.instance() or QApplication([])
    original = copy.deepcopy(config.data)
    try:
        config.data.setdefault("general", {})["reduce_motion"] = True
        config.data.setdefault("spells", {}).update({
            "level": 60,
            "use_secondary": [],
            "use_secondary_all": False,
            "fade_warning_seconds": 40,
        })
        spell_book, _, _ = create_spell_book()
        widget = SpellWidget(
            spell_book["Clarity II"], datetime.datetime.now())

        assert app is not None
        assert isinstance(widget, QFrame)
        assert widget.height() == 26
        assert widget.progress.height() == 22
        assert widget.progress.height() <= widget.height()
        assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert "Shift+F10" in widget.accessibleDescription()

        # Regression guard: QToolButton cannot safely host this custom-painted
        # bar. At the same narrow width used by the in-game overlay, the grab
        # must contain both colored progress pixels and bright painted text.
        widget.resize(180, 26)
        widget.show()
        app.processEvents()
        image = widget.grab().toImage()
        progress_rect = widget.progress.geometry()
        pixels = [
            image.pixelColor(x, y)
            for y in range(progress_rect.top(), progress_rect.bottom() + 1)
            for x in range(progress_rect.left(), progress_rect.right() + 1)]
        assert progress_rect.width() >= 130
        assert sum(color.value() >= 190 for color in pixels) >= 20
        assert sum(
            color.saturation() >= 35 and color.value() >= 35
            for color in pixels) >= 100

        menu_calls = []
        widget._sound_menu = lambda position: menu_calls.append(position)
        widget.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier))
        assert len(menu_calls) == 1
        widget.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_F10,
            Qt.KeyboardModifier.ShiftModifier))
        assert len(menu_calls) == 2

        widget.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Delete,
            Qt.KeyboardModifier.NoModifier))
        assert widget._removed is True

        widget.deleteLater()
    finally:
        config.data = original


def test_spell_row_single_click_focuses_and_double_click_removes():
    app = QApplication.instance() or QApplication([])
    config.verify_settings()
    original = copy.deepcopy(config.data)
    try:
        config.data.setdefault("spells", {}).update({
            "level": 60,
            "use_secondary": [],
            "use_secondary_all": False,
            "fade_warning_seconds": 40,
        })
        spell_book, _, _ = create_spell_book()
        widget = SpellWidget(
            spell_book["Clarity II"], datetime.datetime.now())
        menu_calls = []
        widget._sound_menu = lambda position: menu_calls.append(position)
        widget.resize(180, 26)
        widget.show()
        app.processEvents()

        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert widget.hasFocus() is True
        assert menu_calls == []
        assert widget._removed is False

        QTest.mouseDClick(widget, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert widget._removed is True
    finally:
        config.data = original
