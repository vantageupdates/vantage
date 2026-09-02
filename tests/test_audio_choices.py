import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox

from vantage.helpers.audio import (
    DEFAULT_SOUND, set_sound_combo_value, sound_display_name)


def _app():
    return QApplication.instance() or QApplication([])


def test_no_sound_remains_silent_when_trigger_is_edited():
    _app()
    combo = QComboBox()
    set_sound_combo_value(combo, "")
    assert combo.currentData() == ""
    assert combo.currentText() == "No sound"
    assert sound_display_name("") == "No sound"

    set_sound_combo_value(combo, DEFAULT_SOUND)
    assert combo.currentData() == DEFAULT_SOUND

