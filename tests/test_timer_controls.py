import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QSpinBox

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.spawn_timer import (
    PHASE_IDLE, PHASE_RESPAWN, SpawnTimerState, TIMER_MODE_COUNTDOWN)
from vantage.parsers.timers import (
    NAMED_MOB_SUGGESTIONS, SPAWN_TIMER_WINDOW_STYLE, TimerEditDialog,
    TimerProgressBar, TimerRow)


class _Owner:
    def __init__(self):
        self.messages = []
        self.changes = 0

    def announce(self, message):
        self.messages.append(message)

    def state_changed(self):
        self.changes += 1

    def edit_timer(self, _timer_id):
        pass

    def clone_timer(self, _timer_id):
        pass

    def delete_timer(self, _timer_id):
        pass


def _app():
    if 'timers' not in config.data:
        config.data = {}
        config.verify_settings()
    return QApplication.instance() or QApplication([])


def test_restart_runs_immediately_and_clear_is_a_separate_action():
    app = _app()
    timer = SpawnTimerState("Crystal Fang", 1970)
    owner = _Owner()
    row = TimerRow(timer, owner)
    app.processEvents()

    row._restart()
    assert timer.phase == PHASE_RESPAWN
    assert timer.running is True
    assert timer.deadline is not None

    row._clear()
    assert timer.phase == PHASE_IDLE
    assert timer.running is False
    assert timer.deadline is None
    assert "restarted" in owner.messages[0]
    assert "cleared" in owner.messages[1]


def test_every_timer_button_has_an_authored_tooltip():
    app = _app()
    row = TimerRow(SpawnTimerState("Crystal Fang", 1970), _Owner())
    app.processEvents()
    buttons = row.findChildren(QPushButton)

    assert len(buttons) >= 7
    assert all(button.toolTip().strip() for button in buttons)
    assert "Restart" in row.restart_button.accessibleName()
    assert "READY" in row.clear_button.toolTip()


def test_timer_row_actions_keep_a_direct_keyboard_order_without_volume():
    app = _app()
    row = TimerRow(SpawnTimerState("Crystal Fang", 1970), _Owner())
    app.processEvents()
    controls = [
        row.controls.layout().itemAt(index).widget()
        for index in range(row.controls.layout().count())]

    assert len(controls) == 8
    assert all(isinstance(control, QPushButton) for control in controls)
    assert all(
        control.focusPolicy() == Qt.FocusPolicy.StrongFocus
        for control in controls)
    assert [control.accessibleName() for control in controls] == [
        "Start or pause Crystal Fang",
        "Restart Crystal Fang",
        "Clear Crystal Fang",
        "Confirm death of Crystal Fang",
        "Confirm spawn of Crystal Fang",
        "Clone Crystal Fang",
        "Edit Crystal Fang",
        "Delete Crystal Fang",
    ]


def test_individual_volume_remains_in_the_timer_edit_dialog():
    app = _app()
    timer = SpawnTimerState("Crystal Fang", 1970, volume=37)
    dialog = TimerEditDialog(timer)
    app.processEvents()

    assert dialog.volume.accessibleName() == "Individual timer volume"
    assert dialog.volume.toolTip()
    assert dialog.volume.value() == 37
    dialog.volume.setValue(42)
    dialog.apply(timer)
    assert timer.volume == 42
    dialog.close()


def test_timer_editor_supports_general_countdowns_without_mob_only_fields():
    app = _app()
    dialog = TimerEditDialog()
    dialog.timer_mode.setCurrentIndex(
        dialog.timer_mode.findData(TIMER_MODE_COUNTDOWN))
    app.processEvents()

    assert dialog.timer_mode.accessibleName() == "Timer type"
    assert "countdown" in dialog.timer_mode.toolTip().casefold()
    assert dialog._timer_form.labelForField(dialog.respawn).text() == "Duration"
    assert dialog.kill.isEnabled() is False
    assert dialog.smart.isEnabled() is False
    assert dialog.mob_pattern.isEnabled() is False
    assert dialog.death_mob_panel.isEnabled() is False
    assert dialog.death_mob_input.isEnabled() is False
    assert dialog.death_mob_list.isEnabled() is False

    dialog.name.setText("Port cooldown")
    dialog.respawn.setText("10m")
    timer = dialog.apply()
    assert timer.timer_mode == TIMER_MODE_COUNTDOWN
    assert timer.respawn_seconds == 600
    dialog.close()


def test_timer_editor_adds_deduplicates_and_deletes_death_matches():
    app = _app()
    timer = SpawnTimerState(
        "Quillmane cycle", 1_920, death_mobs=["Quillmane"])
    dialog = TimerEditDialog(timer)
    dialog.show()
    app.processEvents()

    dialog.death_mob_input.setFocus()
    dialog.death_mob_input.setText("an escaped splitpaw gnoll")
    QTest.keyClick(dialog.death_mob_input, Qt.Key.Key_Return)
    app.processEvents()
    assert dialog._death_mob_names() == [
        "Quillmane", "an escaped splitpaw gnoll"]
    assert dialog.death_mob_input.hasFocus()

    dialog.death_mob_input.setText("QUILLMANE")
    QTest.keyClick(dialog.death_mob_input, Qt.Key.Key_Return)
    app.processEvents()
    assert dialog.death_mob_list.count() == 2
    assert "Already added" in dialog.death_mob_status.text()

    dialog.death_mob_list.setCurrentRow(1)
    dialog.death_mob_list.setFocus()
    QTest.keyClick(dialog.death_mob_list, Qt.Key.Key_Delete)
    app.processEvents()
    assert dialog._death_mob_names() == ["Quillmane"]
    assert dialog.death_mob_list.hasFocus()

    dialog.apply(timer)
    assert timer.death_mobs == ["Quillmane"]
    assert timer.mob_pattern == ""
    assert dialog.death_mob_input.accessibleName()
    assert dialog.death_mob_input.accessibleDescription()
    assert dialog.death_mob_add.toolTip()
    assert dialog.death_mob_remove.toolTip()
    dialog.close()


def test_death_name_completer_searches_all_zones_and_accepts_selection():
    app = _app()
    timer = SpawnTimerState(
        "Crystal Fang", 1_970, zone="Velketor's Labyrinth",
        death_mobs=["Crystal Fang"])
    dialog = TimerEditDialog(timer)
    dialog.show()
    app.processEvents()

    assert tuple(NAMED_MOB_SUGGESTIONS) == tuple(sorted(
        NAMED_MOB_SUGGESTIONS, key=str.casefold))
    assert len(NAMED_MOB_SUGGESTIONS) == len({
        name.casefold() for name in NAMED_MOB_SUGGESTIONS})
    assert "Crystal Fang" in NAMED_MOB_SUGGESTIONS
    assert "Kennel Master Al`ele" in NAMED_MOB_SUGGESTIONS
    assert "Quillmane" in NAMED_MOB_SUGGESTIONS
    dialog.death_mob_completer.setCompletionPrefix("quill")
    matches = [
        dialog.death_mob_completer.completionModel().index(row, 0).data()
        for row in range(
            dialog.death_mob_completer.completionModel().rowCount())]
    assert "Quillmane" in matches
    assert dialog.death_mob_completer.popup().accessibleName()
    assert "every zone" in dialog.death_mob_completer.popup().accessibleDescription()

    dialog.death_mob_input.setFocus()
    dialog.death_mob_input.setText("quill")
    dialog.death_mob_completer.complete()
    app.processEvents()
    popup = dialog.death_mob_completer.popup()
    quillmane_row = matches.index("Quillmane")
    popup.setCurrentIndex(
        dialog.death_mob_completer.completionModel().index(quillmane_row, 0))
    assert popup.isVisible()
    QTest.keyClick(dialog.death_mob_picker, Qt.Key.Key_Down)
    QTest.keyClick(dialog.death_mob_picker, Qt.Key.Key_Return)
    app.processEvents()
    assert dialog._death_mob_names() == ["Crystal Fang", "Quillmane"]
    assert dialog.death_mob_input.text() == ""
    assert dialog.death_mob_status.text() == \
        "2 of 24 death matches saved"
    assert dialog.death_mob_input.hasFocus()
    assert isinstance(dialog.death_mob_picker, QComboBox)
    assert dialog.death_mob_picker.isEditable()
    detect_label = dialog._death_mob_label
    assert detect_label.buddy() is dialog.death_mob_picker
    assert dialog.death_mob_picker.accessibleName().startswith(
        "Detect deaths")
    assert dialog.death_mob_list.accessibleName().startswith(
        "Detect deaths")
    dialog.close()


def test_legacy_pattern_is_preserved_until_exact_list_is_edited():
    app = _app()
    timer = SpawnTimerState(
        "Legacy", 120, mob_pattern=r"^(named one|named two)$")
    dialog = TimerEditDialog(timer)
    app.processEvents()

    assert dialog.death_mob_list.count() == 0
    assert "Legacy death pattern" in dialog.death_mob_status.text()
    dialog.apply(timer)
    assert timer.mob_pattern == r"^(named one|named two)$"
    assert timer.death_mobs == []
    dialog.close()


def test_death_name_limits_are_visible_and_long_input_is_not_truncated():
    app = _app()
    dialog = TimerEditDialog(SpawnTimerState("Camp", 120))
    dialog.show()
    app.processEvents()

    assert "24 entries" in dialog.death_mob_help.text()
    assert "128 characters" in dialog.death_mob_help.text()
    assert dialog.death_mob_help.accessibleName() == ""
    assert "24 entries" in dialog.death_mob_help.accessibleDescription()
    assert "128 characters" in \
        dialog.death_mob_picker.accessibleDescription()
    too_long = "x" * 129
    dialog.death_mob_input.setText(too_long)
    assert dialog._add_death_mob() is False
    assert dialog.death_mob_input.text() == too_long
    assert "129 characters" in dialog.death_mob_status.text()
    assert "maximum is 128" in dialog.death_mob_status.text()
    assert dialog.death_mob_list.count() == 1
    assert dialog.death_mob_list.height() >= 76
    assert dialog._death_suggestion_announce_timer.isActive() is False
    dialog.close()


def test_full_death_name_list_has_non_overlapping_full_width_layout():
    app = _app()
    timer = SpawnTimerState(
        "Large camp", 120,
        death_mobs=[f"placeholder {index}" for index in range(24)])
    dialog = TimerEditDialog(timer)
    dialog.show()
    app.processEvents()

    panel = dialog.death_mob_panel
    assert panel.height() >= panel.minimumSizeHint().height()
    assert dialog.death_mob_list.geometry().bottom() < \
        dialog.death_mob_help.geometry().top()
    assert dialog.death_mob_help.geometry().bottom() < \
        dialog.death_mob_status.geometry().top()
    assert dialog.death_mob_list.width() == panel.contentsRect().width()

    dialog.death_mob_input.setText("quil")
    assert dialog._death_suggestion_announce_timer.isActive()
    dialog.close()
    app.processEvents()
    assert dialog._death_suggestion_announce_timer.isActive() is False


def test_completed_countdown_row_shows_done_and_starts_again():
    app = _app()
    timer = SpawnTimerState(
        "Gate rotation", 30, timer_mode=TIMER_MODE_COUNTDOWN)
    timer.start(10)
    timer.tick(40)
    owner = _Owner()
    row = TimerRow(timer, owner)
    app.processEvents()

    assert timer.running is False
    assert row.phase_label.text() == "DONE"
    assert row.play_button.toolTip() == "Start Gate rotation again"
    assert row.play_button.icon().cacheKey() == game_icon("play").cacheKey()

    row._toggle()

    assert timer.running is True
    assert timer.phase == PHASE_RESPAWN
    assert owner.changes == 1
    row.close()


def test_timer_row_uses_border_light_crisp_controls():
    app = _app()
    previous = config.data['timers']['compact']
    config.data['timers']['compact'] = False
    row = TimerRow(
        SpawnTimerState("Crystal Fang", 1970, volume=37), _Owner())
    row.resize(510, row.sizeHint().height())
    row.show()
    app.processEvents()

    assert "QFrame#SpawnTimerRow" in SPAWN_TIMER_WINDOW_STYLE
    assert "background: transparent;\n        border: none;" in \
        SPAWN_TIMER_WINDOW_STYLE
    assert isinstance(row.progress, TimerProgressBar)
    assert row.progress.height() == 9
    assert "border: none" in row.progress.styleSheet()
    assert row.progress.accent == row.timer.color.upper()
    assert all(
        button.property("TimerRowAction") is True
        for button in row.findChildren(QPushButton))
    assert all(
        button.iconSize() == QSize(16, 16)
        for button in row.findChildren(QPushButton))
    assert row.controls.layout().spacing() == 0
    assert row.controls.size() == TimerRow.CONTROLS_SIZE
    assert TimerRow.CONTROLS_SIZE == QSize(210, 28)
    assert row.minimumHeight() == TimerRow.DETAILED_MINIMUM_HEIGHT
    assert not hasattr(row, "volume")
    assert row.controls.findChildren(QSpinBox) == []
    assert "vol " not in row.detail_label.text().casefold()
    assert row.timer.volume == 37
    row.close()
    row.deleteLater()
    app.processEvents()
    config.data['timers']['compact'] = previous


def test_compact_timer_controls_cannot_be_compressed_below_their_buttons():
    app = _app()
    previous = config.data['timers']['compact']
    config.data['timers']['compact'] = True
    try:
        row = TimerRow(SpawnTimerState("Crystal Eyes", 1970), _Owner())
        # Reproduce a panel trying to squeeze its timer rows while being
        # shortened. The row must enforce enough space for the full segmented
        # control instead of painting it under the following card.
        row.resize(510, 30)
        row.show()
        app.processEvents()

        assert row.height() >= TimerRow.COMPACT_MINIMUM_HEIGHT
        assert row.controls.height() == TimerRow.CONTROLS_SIZE.height()
        previous_right = -1
        for index in range(row.controls.layout().count()):
            control = row.controls.layout().itemAt(index).widget()
            assert control.geometry().bottom() < row.controls.height()
            assert control.geometry().left() > previous_right
            previous_right = control.geometry().right()
        assert previous_right < row.controls.width()
        assert row.controls.geometry().bottom() < row.height()
        row.close()
        row.deleteLater()
        app.processEvents()
    finally:
        config.data['timers']['compact'] = previous


def test_timer_row_and_progress_render_at_fractional_scale():
    app = _app()
    timer = SpawnTimerState("Fractional scale", 1800)
    timer.start()
    row = TimerRow(timer, _Owner())
    row.resize(510, row.sizeHint().height())
    row.progress.setValue(62)
    row.show()
    app.processEvents()

    image = QImage(360, 90, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#00000000"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(0.70, 0.70)
    row.render(painter, QPoint())
    painter.end()

    assert not image.isNull()
    assert image.width() == 360
    assert any(
        QColor(image.pixel(x, 30)).alpha() > 0
        for x in range(5, image.width() - 5))
    row.close()
    row.deleteLater()
    app.processEvents()
