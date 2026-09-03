"""Modern spawn timer overlay for Project 1999."""

from __future__ import annotations

import datetime
import hashlib
import re
import string
import time

from PySide6.QtCore import QDateTime, QLocale, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor, QFont, QKeySequence,
    QLinearGradient, QPainter, QPainterPath, QShortcut)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vantage.helpers import config
from vantage.helpers.audio import (
    add_custom_sound_to_combo, play_alert, set_sound_combo_value)
from vantage.helpers.icons import game_icon
from vantage.helpers.log_events import extract_killed_mob
from vantage.helpers.encounter_events import (
    RING_WAR_SCHEDULE_SOURCE, parse_encounter_event,
    ring_war_milestones)
from vantage.helpers.eq_clipboard import set_eq_clipboard
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import store_portable_file
from vantage.helpers.responsive import (
    ResponsiveActionBar, polish_form)
from vantage.helpers.respawn_catalog import (
    CATALOG_SOURCE, CATALOG_SOURCE_URL, NAMED_CATALOG_SOURCE,
    NAMED_CATALOG_SOURCE_URL, RESPAWN_CATALOG, named_spawn_for,
    respawn_for_short_name)
from vantage.helpers.safety_alerts import SafetyAlertState
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.spawn_timer import (
    PHASE_AVAILABLE,
    PHASE_COMBAT,
    PHASE_IDLE,
    PHASE_RESPAWN,
    SpawnTimerState,
    reset_stale_persisted_timers,
    format_seconds,
    parse_duration_input,
    zone_timer_visible,
)
from vantage.helpers.timer_share import (
    TIMER_SHARE_PREFIX,
    TimerShareError,
    build_timer_share_codes,
    decode_timer_share_code,
    extract_timer_share_codes,
    shared_record_to_state,
)


LOG_TIMER_COMMAND = re.compile(
    r"(?:StartTimer|PigTimer)-(?P<duration>\d+(?::\d+){0,2})"
    r"(?:-(?P<label>[A-Za-z0-9_.'`-]+))?",
    re.IGNORECASE)

AUTO_TIMER_COLORS = (
    "#B97252", "#9A7650", "#7B8755", "#4F8378",
    "#657A96", "#806C91", "#995E73", "#8D7048",
)


def extract_log_timer_command(text):
    """Parse the established StartTimer/PigTimer chat command syntax."""
    match = LOG_TIMER_COMMAND.search(str(text or ''))
    if not match:
        return None
    duration = parse_duration_input(
        match.group('duration'), single_unit='seconds')
    if duration <= 0:
        return None
    label = (match.group('label') or 'Log timer').replace(
        '_', ' ').strip().rstrip("'\".,! ")
    return duration, label


def automatic_timer_color(zone, mob):
    digest = hashlib.sha1(
        f"{zone.casefold()}|{mob.casefold()}".encode('utf-8')).digest()
    return AUTO_TIMER_COLORS[digest[0] % len(AUTO_TIMER_COLORS)]

PHASE_TEXT = {
    PHASE_IDLE: "READY",
    PHASE_RESPAWN: "RESPAWN",
    PHASE_COMBAT: "COMBAT",
    PHASE_AVAILABLE: "AVAILABLE",
}


SPAWN_TIMER_WINDOW_STYLE = """
    /* The timer panel is often kept at 60-75% scale over EverQuest.  Avoid
       stacked one-pixel bevels here: fractional transforms make those lines
       look doubled even when the rest of the application is sharp. */
    QWidget#ParserWindow {
        border: none;
        border-radius: 9px;
    }
    QWidget#ParserWindowMenuReal {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #202A31, stop:1 #11181D);
        border: none;
        border-bottom: 1px solid #2B3740;
    }
    QLabel#ParserWindowTitle {
        color: #ECE8DF;
        font-family: "Segoe UI Variable", "Segoe UI";
        font-size: 11px;
        font-weight: 600;
    }
    QFrame#SpawnTimerRow {
        background: transparent;
        border: none;
    }
    QLabel#SpawnTimerName {
        color: #F6F7F7;
        font-family: "Segoe UI Variable", "Segoe UI";
        font-size: 14px;
        font-weight: 600;
    }
    QLabel#SpawnTimerPhase {
        color: #C7CDD0;
        background-color: #222C33;
        border: none;
        border-radius: 5px;
        padding: 1px 6px;
        font-family: "Segoe UI Variable", "Segoe UI";
        font-size: 10px;
        font-weight: 600;
    }
    QLabel#SpawnTimerPhase[Phase="respawn"] {
        color: #E8DAB9;
        background-color: #30291D;
    }
    QLabel#SpawnTimerPhase[Phase="combat"],
    QLabel#SpawnTimerPhase[Phase="available"] {
        color: #C6EDDC;
        background-color: #17342A;
    }
    QLabel#SpawnTimerTime {
        color: #F2F5F6;
        font-family: "Cascadia Mono", "Consolas";
        font-size: 16px;
        font-weight: 600;
    }
    QLabel#SpawnTimerDetail {
        color: #AAB2B6;
        font-family: "Segoe UI Variable", "Segoe UI";
        font-size: 10px;
    }
    QWidget#SpawnTimerActions {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #202B33, stop:1 #11181D);
        border: 1px solid #3D4B55;
        border-radius: 7px;
    }
    QWidget#SpawnTimerActions QPushButton[TimerRowAction="true"] {
        background-color: transparent;
        border: none;
        border-right: 1px solid #334049;
        border-radius: 0;
        min-width: 25px;
        max-width: 25px;
        min-height: 26px;
        max-height: 26px;
        padding: 0;
    }
    QWidget#SpawnTimerActions QPushButton[TimerRowAction="true"]:hover {
        background-color: #2A3740;
        border-right: 1px solid #52616C;
    }
    QWidget#SpawnTimerActions QPushButton[TimerRowAction="true"]:focus {
        background-color: #253139;
        border: 1px solid #B99A60;
    }
    QWidget#SpawnTimerActions QPushButton[TimerRowAction="true"]:pressed {
        background-color: #10171C;
        border: 1px solid #8E794E;
    }
    QWidget#SpawnTimerActions QPushButton[TimerKind="primary"] {
        background-color: #302A1E;
    }
    QWidget#SpawnTimerActions QPushButton[TimerKind="warning"] {
        background-color: #332A18;
    }
    QWidget#SpawnTimerActions QPushButton[TimerKind="danger"] {
        background-color: #351B20;
    }
    QWidget#SpawnTimerActions QPushButton[SegmentEnd="true"] {
        border-right: none;
        border-top-right-radius: 6px;
        border-bottom-right-radius: 6px;
    }
    QSpinBox#SpawnTimerVolume {
        color: #E9E7E1;
        background-color: transparent;
        border: none;
        border-right: 1px solid #334049;
        border-radius: 0;
        min-height: 26px;
        max-height: 26px;
        padding: 0 16px 0 3px;
        font-family: "Segoe UI Variable", "Segoe UI";
        font-size: 10px;
    }
    QSpinBox#SpawnTimerVolume:focus {
        border: 1px solid #B99A60;
    }
    QSpinBox#SpawnTimerVolume::up-button,
    QSpinBox#SpawnTimerVolume::down-button {
        subcontrol-origin: border;
        width: 14px;
        border: none;
        border-left: 1px solid #40505C;
        background-color: transparent;
    }
    QSpinBox#SpawnTimerVolume::up-button {
        subcontrol-position: top right;
    }
    QSpinBox#SpawnTimerVolume::down-button {
        subcontrol-position: bottom right;
    }
"""


class TimerProgressBar(QProgressBar):
    """Small antialiased progress bar without fractional-scale border noise."""

    def __init__(self, accent, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self.setObjectName("SpawnTimerProgress")
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(9)
        self.setStyleSheet(
            "QProgressBar#SpawnTimerProgress {"
            "background: transparent; border: none; padding: 0; }")

    @property
    def accent(self):
        return self._accent.name().upper()

    def set_accent(self, accent):
        color = QColor(accent)
        if color.isValid() and color != self._accent:
            self._accent = color
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if rect.isEmpty():
            return

        radius = min(4.0, rect.height() / 2.0)
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        painter.fillPath(track, QColor("#0B1116"))

        span = max(1, self.maximum() - self.minimum())
        ratio = max(0.0, min(
            1.0, (self.value() - self.minimum()) / span))
        if ratio <= 0:
            return
        fill_rect = QRectF(rect)
        fill_rect.setWidth(rect.width() * ratio)
        fill = QPainterPath()
        fill.addRoundedRect(fill_rect, radius, radius)
        fill = fill.intersected(track)
        gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.bottomLeft())
        gradient.setColorAt(0.0, self._accent.lighter(116))
        gradient.setColorAt(0.38, self._accent)
        gradient.setColorAt(1.0, self._accent.darker(116))
        painter.fillPath(fill, gradient)


class TimerEditDialog(UniformScaleDialog):
    def __init__(self, timer=None, parent=None):
        super().__init__(
            QSize(500, 420), parent, minimum_size=QSize(200, 168))
        self.timer = timer
        self.color = timer.color if timer else "#B38C52"
        self.setWindowTitle("Edit Smart Timer" if timer else "New Smart Timer")

        form = polish_form(QFormLayout())
        form.setSpacing(5)
        self.name = QLineEdit(timer.name if timer else "")
        self.name.setPlaceholderText("Example: Quillmane")
        self.name.setToolTip(
            "A short label shown on the timer row, overlays, and phone view")
        form.addRow("Name", self.name)

        self.respawn = QLineEdit(format_seconds(timer.respawn_seconds) if timer else "00:32:00")
        self.respawn.setPlaceholderText("3 = 3 min · 3:50 · 1:03:50")
        self.respawn.setToolTip(
            "Time until the next spawn: 3 means 3 minutes; 3:50 and 1:03:50 are also accepted")
        self.respawn.editingFinished.connect(
            lambda: self._normalize_duration(self.respawn))
        form.addRow("Respawn time", self.respawn)

        self.kill = QLineEdit(format_seconds(timer.kill_seconds) if timer else "01:00")
        self.kill.setPlaceholderText("3 = 3 min · 3:50")
        self.kill.setToolTip(
            "Estimated time to kill the mob: 3 means 3 minutes; 3:50 means 3 minutes 50 seconds")
        self.kill.editingFinished.connect(
            lambda: self._normalize_duration(self.kill))
        form.addRow("Estimated kill time", self.kill)

        self.warning = QSpinBox()
        self.warning.setRange(0, 600)
        self.warning.setSuffix(" s")
        self.warning.setValue(timer.warning_seconds if timer else 30)
        self.warning.setToolTip(
            "Play and display the fading warning this many seconds before spawn")
        form.addRow("Advance warning", self.warning)

        self.smart = QCheckBox("Assume kill when the estimate ends")
        self.smart.setChecked(timer.smart if timer else True)
        self.smart.setToolTip(
            "After the estimated kill time, automatically begin the next "
            "respawn cycle. A manual action always overrides the estimate.")
        form.addRow("Smart mode", self.smart)

        self.zone = QLineEdit(timer.zone if timer else "")
        self.zone.setPlaceholderText("Blank = all zones")
        self.zone.setToolTip(
            "Only match death lines while this zone is active; leave blank "
            "to use the timer in every zone")
        form.addRow("Zone", self.zone)

        self.mob_pattern = QLineEdit(timer.mob_pattern if timer else "")
        self.mob_pattern.setPlaceholderText("Regex or mob name")
        self.mob_pattern.setToolTip(
            "Mob name or regular expression matched against EverQuest death "
            "lines; blank uses the timer name")
        form.addRow("Detect death", self.mob_pattern)

        color_row = QHBoxLayout()
        self.color_preview = QPushButton(self.color)
        self.color_preview.setAccessibleName("Choose timer color")
        self.color_preview.setToolTip(
            "Choose the progress-bar and timer accent color")
        self.color_preview.clicked.connect(self._pick_color)
        color_row.addWidget(self.color_preview)
        form.addRow("Color", color_row)
        self._update_color_preview()

        sound_panel = QWidget()
        sound_row = QVBoxLayout(sound_panel)
        sound_row.setContentsMargins(0, 0, 0, 0)
        sound_row.setSpacing(5)
        self.sound = QComboBox()
        self.sound.setAccessibleName("Timer sound gallery")
        self.sound.setToolTip(
            "Choose the alarm played for this timer from the built-in or "
            "portable sound gallery")
        set_sound_combo_value(
            self.sound, timer.sound_path if timer else "builtin:spawn-horn")
        browse = QPushButton("WAV…")
        browse.setIcon(game_icon("copy"))
        browse.setToolTip(
            "Add a royalty-free WAV file to Vantage's portable sound gallery")
        browse.clicked.connect(self._browse_sound)
        test = QPushButton("Test")
        test.setIcon(game_icon("play"))
        test.setToolTip("Test this sound at the timer's individual volume")
        sound_row.addWidget(self.sound)
        sound_actions = ResponsiveActionBar(88)
        sound_actions.addWidget(browse)
        sound_actions.addWidget(test)
        sound_row.addWidget(sound_actions)
        form.addRow("Alarm gallery", sound_panel)

        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setValue(
            timer.volume if timer else config.data['timers']['volume'])
        self.volume.setAccessibleName("Individual timer volume")
        self.volume.setToolTip(
            "Volume for this timer only; 0 mutes its alarm")
        test.clicked.connect(lambda: play_alert(
            self.sound.currentData(), self.volume.value(), 2,
            source=f"Test · timer {self.name.text().strip() or 'new'}"))
        form.addRow("This timer's volume", self.volume)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_button.setText("Save")
        save_button.setObjectName("PrimaryAction")
        save_button.setToolTip("Save this Smart Timer and close the editor")
        cancel_button.setText("Cancel")
        cancel_button.setToolTip("Discard changes and close the editor")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(5)
        form_host = QWidget()
        form_host.setLayout(form)
        layout.addWidget(form_host, 1)
        layout.addWidget(buttons)

    def _pick_color(self):
        selected = QColorDialog.getColor(QColor(self.color), self, "Timer Color")
        if selected.isValid():
            self.color = selected.name()
            self._update_color_preview()

    def _update_color_preview(self):
        self.color_preview.setText(self.color.upper())
        foreground = "#0C0E11" if QColor(self.color).lightness() > 145 else "#F4F0E7"
        self.color_preview.setStyleSheet(
            f"background:{self.color}; color:{foreground}; border:none; border-radius:7px;"
        )

    def _browse_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Alarm", "", "WAV Audio (*.wav)")
        if path:
            add_custom_sound_to_combo(self.sound, store_portable_file(path))

    @staticmethod
    def _normalize_duration(field):
        seconds = parse_duration_input(field.text())
        if seconds > 0:
            field.setText(format_seconds(seconds))

    def _validate(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name Required", "Enter a name for the timer.")
            self.name.setFocus()
            return
        if parse_duration_input(self.respawn.text()) <= 0:
            QMessageBox.warning(
                self, "Invalid Respawn Time",
                "Use 3 for three minutes, 3:50, or 1:03:50.")
            self.respawn.setFocus()
            return
        if parse_duration_input(self.kill.text()) <= 0:
            QMessageBox.warning(
                self, "Invalid Kill Time",
                "Use 3 for three minutes, 3:50, or 1:03:50.")
            self.kill.setFocus()
            return
        self.accept()

    def apply(self, timer=None):
        timer = timer or SpawnTimerState(
            self.name.text(), parse_duration_input(self.respawn.text()))
        timer.name = self.name.text().strip()
        timer.respawn_seconds = parse_duration_input(self.respawn.text())
        timer.kill_seconds = parse_duration_input(self.kill.text())
        timer.warning_seconds = self.warning.value()
        timer.smart = self.smart.isChecked()
        timer.zone = self.zone.text().strip()
        timer.mob_pattern = self.mob_pattern.text().strip()
        timer.color = self.color
        timer.sound_path = str(self.sound.currentData() or "builtin:spawn-horn")
        timer.volume = self.volume.value()
        return timer


class TimerRow(QFrame):
    COMPACT_MINIMUM_HEIGHT = 40
    DETAILED_MINIMUM_HEIGHT = 82
    CONTROLS_SIZE = QSize(242, 28)

    def __init__(self, timer, owner):
        super().__init__()
        self.timer = timer
        self.owner = owner
        self.setObjectName("SpawnTimerRow")
        crisp_font = QFont(self.font())
        crisp_font.setFamilies(["Segoe UI Variable", "Segoe UI"])
        crisp_font.setHintingPreference(
            QFont.HintingPreference.PreferVerticalHinting)
        crisp_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        self.setFont(crisp_font)
        self.setAccessibleName(f"Timer for {timer.name}")
        self.setToolTip(
            f"{timer.name} · right-click for window position, layer, and "
            "transparency options")
        self.setMinimumHeight(self.COMPACT_MINIMUM_HEIGHT)

        root = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._root_layout = root
        root.setContentsMargins(5, 4, 5, 4)
        root.setSpacing(4)

        info_widget = QWidget()
        self.info_widget = info_widget
        info_widget.setMinimumWidth(0)
        info_widget.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info = QVBoxLayout()
        info_widget.setLayout(info)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        headline = QHBoxLayout()
        self.name_label = QLabel(timer.name)
        self.name_label.setObjectName("SpawnTimerName")
        self.name_label.setMinimumWidth(0)
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.name_label.setToolTip(
            "Timer name; edit the timer to change it")
        self.phase_label = QLabel()
        self.phase_label.setObjectName("SpawnTimerPhase")
        self.phase_label.setToolTip(
            "Current Smart Timer phase: ready, respawn, combat, available, "
            "or paused")
        self.time_label = QLabel()
        self.time_label.setObjectName("SpawnTimerTime")
        self.time_label.setToolTip(
            "Time remaining in the current phase")
        headline.addWidget(self.name_label, 1)
        headline.addWidget(self.phase_label)
        headline.addWidget(self.time_label)
        info.addLayout(headline)

        self.progress = TimerProgressBar(timer.color)
        self.progress.setAccessibleName(f"Progress for {timer.name}")
        self.progress.setToolTip(
            "Visual progress through the current timer phase")
        self._visual_state = None
        self._pulse_on = False
        info.addWidget(self.progress)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("SpawnTimerDetail")
        self.detail_label.setWordWrap(True)
        info.addWidget(self.detail_label)
        root.addWidget(info_widget, 1)

        controls = QFrame()
        controls.setObjectName("SpawnTimerActions")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(1, 1, 1, 1)
        controls_layout.setSpacing(0)
        self.controls = controls
        self.play_button = QPushButton()
        self._polish_action(self.play_button)
        self.play_button.setIcon(game_icon("play"))
        self.play_button.setAccessibleName(f"Start or pause {timer.name}")
        self.play_button.setToolTip(
            f"Start, pause, or resume {timer.name} without changing its phase")
        self.play_button.clicked.connect(self._toggle)
        controls_layout.addWidget(self.play_button)

        self.restart_button = QPushButton()
        self._polish_action(self.restart_button)
        self.restart_button.setIcon(game_icon("refresh"))
        self.restart_button.setAccessibleName(f"Restart {timer.name}")
        self.restart_button.setToolTip(
            "Restart the complete respawn countdown immediately")
        self.restart_button.clicked.connect(self._restart)
        controls_layout.addWidget(self.restart_button)

        self.clear_button = QPushButton()
        self._polish_action(self.clear_button)
        self.clear_button.setIcon(game_icon("stop"))
        self.clear_button.setAccessibleName(f"Clear {timer.name}")
        self.clear_button.setToolTip(
            "Clear the countdown and return to READY without deleting it")
        self.clear_button.clicked.connect(self._clear)
        controls_layout.addWidget(self.clear_button)

        killed = QPushButton()
        self._polish_action(killed, "warning")
        killed.setIcon(game_icon("kill"))
        killed.setObjectName("WarningAction")
        killed.setAccessibleName(f"Confirm death of {timer.name}")
        killed.setToolTip("Mob killed: start respawn")
        killed.clicked.connect(self._killed)
        controls_layout.addWidget(killed)

        spawned = QPushButton()
        self._polish_action(spawned, "primary")
        spawned.setIcon(game_icon("spawn"))
        spawned.setObjectName("PrimaryAction")
        spawned.setAccessibleName(f"Confirm spawn of {timer.name}")
        spawned.setToolTip("Mob spawned: start estimated kill time")
        spawned.clicked.connect(self._spawned)
        controls_layout.addWidget(spawned)

        self.volume = QSpinBox()
        self.volume.setObjectName("SpawnTimerVolume")
        self.volume.setRange(0, 100)
        self.volume.setSuffix("%")
        self.volume.setValue(timer.volume)
        self.volume.setProperty("IntegratedRocker", True)
        self.volume.setAccessibleName(f"Volume for {timer.name}")
        self.volume.setToolTip(
            f"Individual alarm volume for {timer.name}")
        self.volume.setFixedWidth(58)
        self.volume.editingFinished.connect(self._volume_changed)
        controls_layout.addWidget(self.volume)

        edit = QPushButton()
        self._polish_action(edit)
        edit.setIcon(game_icon("edit"))
        edit.setAccessibleName(f"Edit {timer.name}")
        edit.setToolTip(
            f"Edit {timer.name}: name, durations, smart reset, color, sound, and volume")
        edit.clicked.connect(lambda: owner.edit_timer(timer.timer_id))
        controls_layout.addWidget(edit)

        delete = QPushButton()
        self._polish_action(delete, "danger")
        delete.setIcon(game_icon("delete"))
        delete.setObjectName("DangerAction")
        delete.setProperty("SegmentEnd", True)
        delete.setAccessibleName(f"Delete {timer.name}")
        delete.setToolTip(f"Delete {timer.name} after confirmation")
        delete.clicked.connect(lambda: owner.delete_timer(timer.timer_id))
        controls_layout.addWidget(delete)
        # Keep every action in one dense logical row. The outer window scales
        # this whole row with the rest of the timer canvas.
        # The segmented controls contain 26 px buttons plus one logical pixel
        # of frame inset on every side.  A width-only constraint lets Qt
        # compress this wrapper below 28 px when the outer panel is shortened,
        # clipping the buttons behind the next timer card.
        controls.setFixedSize(self.CONTROLS_SIZE)
        root.addWidget(controls, 0, Qt.AlignmentFlag.AlignRight)

        self.refresh()

    @staticmethod
    def _polish_action(button, kind="normal"):
        button.setProperty("TimerRowAction", True)
        button.setProperty("TimerKind", kind)
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(26, 26)

    def _toggle(self):
        if self.timer.running:
            self.timer.pause()
        elif self.timer.phase == PHASE_IDLE:
            self.timer.start()
        else:
            self.timer.resume()
        self.owner.state_changed()

    def _killed(self):
        self.timer.mark_killed()
        self.owner.announce(f"{self.timer.name}: death confirmed")
        self.owner.state_changed()

    def _restart(self):
        self.timer.restart()
        self.owner.announce(
            f"{self.timer.name}: respawn countdown restarted")
        self.owner.state_changed()

    def _clear(self):
        self.timer.reset()
        self.owner.announce(f"{self.timer.name}: countdown cleared to READY")
        self.owner.state_changed()

    def _spawned(self):
        self.timer.mark_spawned()
        self.owner.announce(f"{self.timer.name}: spawn confirmed")
        self.owner.state_changed()

    def _volume_changed(self):
        self.timer.volume = self.volume.value()
        self.owner.state_changed()

    def refresh(self):
        timer = self.timer
        self.name_label.setText(timer.name)
        self.phase_label.setText(PHASE_TEXT.get(timer.phase, timer.phase.upper()))
        if timer.source == RING_WAR_SCHEDULE_SOURCE:
            self.phase_label.setText("EVENT")
        self.phase_label.setProperty("Phase", timer.phase)
        self.phase_label.setStyle(self.phase_label.style())
        remaining = timer.remaining()
        if not timer.running and timer.phase != PHASE_IDLE:
            self.phase_label.setText("PAUSED")
        self.time_label.setText("--:--" if remaining is None else format_seconds(remaining))
        self.progress.setValue(timer.progress_percent())
        self.progress.setAccessibleDescription(
            f"{PHASE_TEXT.get(timer.phase, timer.phase)}, {self.time_label.text()} remaining"
        )
        smart = "AUTO-KILL" if timer.smart else "LOG KILL"
        zone = f" · {timer.zone}" if timer.zone else ""
        source = f" · {timer.source}" if timer.source else ""
        if timer.source == RING_WAR_SCHEDULE_SOURCE:
            self.detail_label.setText(
                f"LOCAL LOG · RING WAR · {timer.source}")
        elif timer.automatic:
            self.detail_label.setText(
                f"AUTO LOG · {smart} · cycle {timer.cycles}{zone}{source}")
        else:
            self.detail_label.setText(
                f"{smart} · kill {format_seconds(timer.kill_seconds)} · "
                f"vol {timer.volume}% · cycle {timer.cycles}{zone}{source}")
        self.detail_label.setToolTip(
            f"Named source: {timer.source}\n{NAMED_CATALOG_SOURCE_URL}\n"
            f"Timing source: {CATALOG_SOURCE}\n{CATALOG_SOURCE_URL}"
            if timer.source == NAMED_CATALOG_SOURCE else
            f"Respawn source: {timer.source}\n{CATALOG_SOURCE_URL}"
            if timer.source == CATALOG_SOURCE else
            f"Respawn source: {timer.source}" if timer.source else
            "User-created timer")
        self.play_button.setIcon(game_icon("pause" if timer.running else "play"))
        self.play_button.setToolTip(
            f"Pause {timer.name} and preserve its remaining time"
            if timer.running else
            f"Start {timer.name} from READY"
            if timer.phase == PHASE_IDLE else
            f"Resume {timer.name} from its preserved remaining time")
        compact = bool(config.data['timers']['compact'])
        self.detail_label.setVisible(not compact)
        self._root_layout.setDirection(
            QBoxLayout.Direction.LeftToRight
            if compact else QBoxLayout.Direction.TopToBottom)
        self._root_layout.setAlignment(
            self.controls,
            Qt.AlignmentFlag.AlignRight |
            (Qt.AlignmentFlag.AlignVCenter if compact else
             Qt.AlignmentFlag.AlignBottom))
        self.setMinimumHeight(
            self.COMPACT_MINIMUM_HEIGHT
            if compact else self.DETAILED_MINIMUM_HEIGHT)

        warning = bool(
            timer.running and timer.phase == PHASE_RESPAWN and
            remaining is not None and 0 < remaining <= timer.warning_seconds)
        spawn_window = timer.running and timer.phase in (
            PHASE_COMBAT, PHASE_AVAILABLE)
        alert_state = "warning" if warning else "spawn" if spawn_window else "normal"
        self._pulse_on = (
            False if config.data['general'].get('reduce_motion') else
            not self._pulse_on if alert_state != "normal" else False)
        pulse = self._pulse_on
        visual_state = (alert_state, pulse, timer.color)
        if visual_state != self._visual_state:
            self._visual_state = visual_state
            self.setProperty("AlertState", alert_state)
            self.setProperty("Pulse", pulse)
            accent = (
                "#FFD166" if warning and pulse else
                "#6EE7B7" if spawn_window and pulse else
                "#3FA77D" if spawn_window else timer.color)
            self.progress.set_accent(accent)
            self.update()

    def paintEvent(self, _event):
        """Paint one soft card, avoiding doubled one-pixel QSS outlines."""
        state = self.property("AlertState") or "normal"
        pulse = bool(self.property("Pulse"))
        if state == "warning":
            top, bottom = (
                ("#3A2B15", "#211A10") if pulse else
                ("#252018", "#151719"))
        elif state == "spawn":
            top, bottom = (
                ("#17352C", "#10241F") if pulse else
                ("#1B2928", "#12191C"))
        elif self.underMouse():
            top, bottom = "#253039", "#151C21"
        else:
            top, bottom = "#1D272E", "#11171C"

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 7.0, 7.0)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(top))
        gradient.setColorAt(1.0, QColor(bottom))
        painter.fillPath(shape, gradient)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class SpawnTimers(ParserWindow):
    _keep_header_readable = True
    _minimum_readable_width = 300

    def __init__(self):
        self.name = "timers"
        super().__init__()
        # This panel is commonly downscaled over the game.  Its local style
        # deliberately replaces bevel stacks with antialiased, border-light
        # geometry without changing any other Vantage window.
        self.setStyleSheet(SPAWN_TIMER_WINDOW_STYLE)
        self.setWindowTitle("Smart Spawn Timers")
        self._current_zone = config.data['maps'].get('last_zone', '')
        self._selected_zone = str(
            config.data['timers'].get('view_zone') or
            self._current_zone or '').strip()
        self._missing_zone_notified = None
        self._states = {}
        self._rows = {}
        self._safety = SafetyAlertState(
            config.data['timers'].get('death_loop_deaths', 4),
            config.data['timers'].get('death_loop_seconds', 120))

        add = QPushButton()
        add.setIcon(game_icon("add"))
        add.setObjectName("PrimaryAction")
        add.setAccessibleName("Add timer")
        add.setToolTip(
            "Add a named Smart Timer with editable respawn, kill estimate, color, sound, and volume")
        add.clicked.connect(self.add_timer)
        self.menu_area.addWidget(add)

        self.compact = QPushButton()
        self.compact.setIcon(game_icon("compact"))
        self.compact.setCheckable(True)
        self.compact.setChecked(config.data['timers']['compact'])
        self.compact.setAccessibleName("Toggle compact mode")
        self.compact.setToolTip(
            "Switch timer rows between detailed and minimum-space presentations")
        self.compact.clicked.connect(self._toggle_compact)
        self.menu_area.addWidget(self.compact)

        self.zone_filter = QComboBox()
        self.zone_filter.setObjectName('SpawnTimerZoneFilter')
        # Zone selection is core timer context, not an optional header action.
        # Keep it directly discoverable even when the scaled overlay is at its
        # minimum supported width; secondary actions can use header overflow.
        self.zone_filter.setProperty('HeaderAlwaysVisible', True)
        self.zone_filter.setAccessibleName('Timer zone view')
        self.zone_filter.setToolTip(
            'Show the saved timer rows for one zone; global timers appear in '
            'every zone and rows remain saved until you delete them')
        self.zone_filter.setMinimumContentsLength(8)
        self.zone_filter.currentIndexChanged.connect(
            self._zone_filter_changed)
        self.menu_area.addWidget(self.zone_filter)

        self.share_button = QPushButton()
        self.share_button.setIcon(game_icon("export"))
        # Sharing is a primary camp hand-off workflow.  Do not silently move it
        # into the generic overflow menu on narrow or rolled-up timer headers.
        self.share_button.setProperty('HeaderAlwaysVisible', True)
        self.share_button.setAccessibleName("Share visible zone timers by code")
        self.share_button.setAccessibleDescription(
            "Copies the currently visible zone timers as compact codes. Send "
            "every code to another player. With Vantage running and EverQuest "
            "logging enabled, their app detects the codes in the log, adjusts "
            "for elapsed time, and automatically adds or refreshes the timers "
            "in the correct zone without an import dialog. Codes expire after "
            "24 hours.")
        self.share_button.setToolTip(
            "Copy this zone's visible timers as one or more compact codes "
            "(Ctrl+Shift+S).\n"
            "Send every code by /tell, /say, Discord, or another message. The "
            "receiver only needs Vantage and /log on.\n"
            "Their Vantage detects the codes in the log—no import dialog—then "
            "uses the creation time to adjust elapsed time and automatically "
            "adds or refreshes the timers in the correct zone. Codes expire "
            "after 24 hours.")
        self.share_button.clicked.connect(self.share_visible_timers)
        self.menu_area.addWidget(self.share_button)
        self._share_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+S"), self)
        self._share_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._share_shortcut.activated.connect(self.share_visible_timers)

        self.mobile_button = QPushButton()
        self.mobile_button.setIcon(game_icon("mobile"))
        self.mobile_button.setProperty('HeaderPriority', 100)
        self.mobile_button.setAccessibleName("View Vantage on your phone")
        self.mobile_button.setToolTip(
            "Create a QR code for timers, market, and EverQuest Live")
        self.mobile_button.clicked.connect(
            lambda: QApplication.instance().show_mobile_share())
        self.menu_area.addWidget(self.mobile_button)

        host = QWidget()
        host.setObjectName("SpawnTimerCanvas")
        host.setAccessibleName("Complete Smart Timer list")
        host.setToolTip(
            "Every timer stays on this single surface and scales with the window")
        self._timer_host = host
        self._layout = QVBoxLayout(host)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(3)
        self._layout.addStretch(1)
        # This is intentionally not a QScrollArea. The timer list is one fixed
        # logical canvas; adding rows lengthens that canvas and the outer
        # graphics view scales the complete replica without scrollbars.
        self.content.addWidget(host, 1)

        self.status = QLabel("Smart timers ready · automatic log timers: nameds only")
        self.status.setObjectName("SpawnTimerStatus")
        self.status.setAccessibleName("Timer status")
        self.status.setToolTip(
            "Latest Smart Timer action or automatic log event")
        self.content.addWidget(self.status)

        self._canvas_update_timer = QTimer(self)
        self._canvas_update_timer.setSingleShot(True)
        self._canvas_update_timer.timeout.connect(self._sync_timer_canvas)
        self._viewport_rows_timer = QTimer(self)
        self._viewport_rows_timer.setSingleShot(True)
        self._viewport_rows_timer.timeout.connect(
            self._apply_viewport_capacity)

        self._load()
        self._refresh_zone_filter(self._selected_zone)
        QApplication.instance().aboutToQuit.connect(
            self.record_session_closed)
        QApplication.instance()._signals["maps"].new_zone.connect(
            self._zone_changed)
        self._ticker = QTimer(self)
        # Second precision is enough for P99 spawns and avoids needless repaints.
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    def mobile_snapshot(self):
        """Small immutable shape consumed by the isolated mobile server."""
        timers = []
        for timer in self._states.values():
            if not zone_timer_visible(timer.zone, self._selected_zone):
                continue
            remaining = timer.remaining()
            timers.append({
                "timer_id": timer.timer_id,
                "name": timer.name,
                "phase": timer.phase,
                "running": timer.running,
                "remaining": "--:--" if remaining is None else format_seconds(remaining),
                "progress": timer.progress_percent(),
                "color": timer.color,
                "smart": timer.smart,
                "kill": format_seconds(timer.kill_seconds),
                "cycles": timer.cycles,
                "zone": timer.zone,
                "source": timer.source,
                "automatic": timer.automatic,
            })
        zones = [
            str(self.zone_filter.itemData(index) or "")
            for index in range(self.zone_filter.count())]
        return {
            "version": 2,
            "timers": timers,
            "timer_zone": self._selected_zone,
            "timer_zones": zones,
            "generated_at": int(time.time()),
        }

    def mobile_action(self, action, target):
        """Apply one phone-side action to Vantage, never to EverQuest."""
        action = str(action or "").strip().casefold()
        target = str(target or "").strip()
        if action == "zone":
            selected = 0
            for index in range(self.zone_filter.count()):
                if str(self.zone_filter.itemData(index) or "").casefold() == \
                        target.casefold():
                    selected = index
                    break
            self.zone_filter.setCurrentIndex(selected)
            return

        timer = self._states.get(target)
        if timer is None:
            return
        if action == "toggle":
            if timer.running:
                timer.pause()
                verb = "paused"
            elif timer.phase == PHASE_IDLE:
                timer.start()
                verb = "started"
            else:
                timer.resume()
                verb = "resumed"
        elif action == "restart":
            timer.restart()
            verb = "restarted"
        elif action == "clear":
            timer.reset()
            verb = "cleared to READY"
        else:
            return
        self.announce(f"{timer.name}: {verb} from phone")
        self.state_changed()

    def _load(self):
        reset_stale_persisted_timers(config.data['timers'])
        migrated = False
        for values in config.data['timers']['items']:
            try:
                timer = SpawnTimerState.from_dict(values)
            except (TypeError, ValueError):
                continue
            if timer.automatic and timer.source == CATALOG_SOURCE:
                named, _entry = self._named_respawn_entry(
                    timer.name, timer.zone)
                if not named:
                    timer.automatic = False
                    timer.source = 'Saved zone timer'
                    migrated = True
                else:
                    timer.source = NAMED_CATALOG_SOURCE
                    migrated = True
            self._states[timer.timer_id] = timer
            self._add_row(timer)
        # Persist the live-session marker even when no countdown changed. A
        # crash then preserves rows instead of reusing an older clean-close
        # timestamp and resetting them by mistake.
        self._save()

    def record_session_closed(self):
        """Anchor the next startup's offline-age check to a clean exit."""
        config.data['timers']['last_session_closed_at'] = time.time()
        config.save()

    def _refresh_zone_filter(self, preferred=None):
        preferred = str(
            self._selected_zone if preferred is None else preferred).strip()
        zones = {}
        for zone in (self._current_zone, preferred):
            zone = str(zone or '').strip()
            if zone:
                zones.setdefault(zone.casefold(), zone)
        for timer in self._states.values():
            zone = str(timer.zone or '').strip()
            if zone:
                zones.setdefault(zone.casefold(), zone)

        self.zone_filter.blockSignals(True)
        self.zone_filter.clear()
        self.zone_filter.addItem('All zones', '')
        for zone in sorted(zones.values(), key=str.casefold):
            self.zone_filter.addItem(zone, zone)
        selected = 0
        for index in range(self.zone_filter.count()):
            if str(self.zone_filter.itemData(index) or '').casefold() == \
                    preferred.casefold():
                selected = index
                break
        self.zone_filter.setCurrentIndex(selected)
        self.zone_filter.blockSignals(False)
        self._selected_zone = str(
            self.zone_filter.currentData() or '').strip()
        config.data['timers']['view_zone'] = self._selected_zone
        self._apply_zone_filter()

    def _zone_filter_changed(self, _index):
        self._selected_zone = str(
            self.zone_filter.currentData() or '').strip()
        config.data['timers']['view_zone'] = self._selected_zone
        config.save()
        self._apply_zone_filter()
        visible = sum(
            self._row_matches_zone(timer)
            for timer in self._states.values())
        self.status.setText(
            f"ZONE VIEW · {self._selected_zone or 'All zones'} · "
            f"{visible} saved timer{'s' if visible != 1 else ''}")

    def _apply_zone_filter(self):
        for timer_id, row in self._rows.items():
            timer = self._states.get(timer_id)
            row.setVisible(self._row_matches_zone(timer))
        self._schedule_timer_canvas()

    def _row_matches_zone(self, timer):
        return bool(
            timer and zone_timer_visible(
                timer.zone, self._selected_zone))

    def _add_row(self, timer):
        row = TimerRow(timer, self)
        self._rows[timer.timer_id] = row
        self._layout.insertWidget(self._layout.count() - 1, row)
        row.setVisible(self._row_matches_zone(timer))
        self._schedule_timer_canvas()

    def _schedule_timer_canvas(self):
        if hasattr(self, "_canvas_update_timer"):
            self._canvas_update_timer.start(0)

    def _sync_timer_canvas(self):
        """Fit every logical timer row on one surface, never in a scroller."""
        margins = self._layout.contentsMargins()
        rows = tuple(
            row for timer_id, row in self._rows.items()
            if self._row_matches_zone(self._states.get(timer_id)))
        rows_height = sum(max(
            row.minimumHeight(), row.minimumSizeHint().height(),
            row.sizeHint().height()) for row in rows)
        if len(rows) > 1:
            rows_height += self._layout.spacing() * (len(rows) - 1)
        list_height = margins.top() + margins.bottom() + rows_height
        header_height = max(
            self._menu.minimumSizeHint().height(), self._menu.sizeHint().height())
        status_height = max(
            self.status.minimumSizeHint().height(), self.status.sizeHint().height())
        logical_height = max(
            360, header_height + list_height + status_height)
        self._set_design_size(QSize(520, logical_height))
        self._schedule_viewport_rows()

    def _minimum_logical_surface_height(self):
        """Clip a short viewport; never squeeze timer cards into each other."""
        # A rolled panel contains only its header. Re-expanding the protected
        # timer canvas here would vertically center the header inside a hidden
        # 360 px surface and make the 24 px strip appear broken.
        return 1 if self._collapsed else self._design_size.height()

    def _update_uniform_scale(self):
        super()._update_uniform_scale()
        self._schedule_viewport_rows()

    def _schedule_viewport_rows(self):
        timer = getattr(self, '_viewport_rows_timer', None)
        if timer is not None:
            timer.start(0)

    def _apply_viewport_capacity(self):
        """Show only complete rows in a short, scroll-free timer viewport."""
        if not self._scale_view or not self._scale_proxy:
            return
        scale = float(self._scale_view.transform().m11())
        if scale <= 0:
            return

        zone_rows = []
        for timer_id, row in self._rows.items():
            matches = self._row_matches_zone(self._states.get(timer_id))
            row.setVisible(matches)
            if matches:
                zone_rows.append(row)

        # First lay out the complete zone list on its protected logical canvas.
        # Then hide the suffix that would be physically clipped by this viewport.
        self._surface.layout().activate()
        self._layout.activate()
        logical_bottom = int(
            self._scale_view.viewport().height() / scale) - 1
        suffix_started = False
        focus = QApplication.focusWidget()
        focus_was_hidden = False
        visible_rows = []
        for row in zone_rows:
            top = row.mapTo(self._surface, row.rect().topLeft()).y()
            fits = not suffix_started and top + row.height() - 1 <= logical_bottom
            suffix_started = suffix_started or not fits
            if (not fits and focus is not None and
                    (focus is row or row.isAncestorOf(focus))):
                focus_was_hidden = True
            row.setVisible(fits)
            if fits:
                visible_rows.append(row)
        if focus_was_hidden:
            # Never strand keyboard focus inside a suffix row that just became
            # invisible. Keep the user in the timer list when possible.
            destination = (
                visible_rows[-1].play_button if visible_rows else
                self.zone_filter)
            destination.setFocus(Qt.FocusReason.OtherFocusReason)

    def add_timer(self):
        dialog = TimerEditDialog(parent=self)
        dialog.zone.setText(string.capwords(
            self._selected_zone or self._current_zone))
        if dialog.exec():
            timer = dialog.apply()
            self._states[timer.timer_id] = timer
            self._add_row(timer)
            self._refresh_zone_filter(timer.zone)
            self.state_changed()

    def edit_timer(self, timer_id):
        timer = self._states[timer_id]
        dialog = TimerEditDialog(timer, self)
        if dialog.exec():
            dialog.apply(timer)
            self._rows[timer_id].progress.set_accent(timer.color)
            self._refresh_zone_filter(timer.zone)
            self.state_changed()

    def delete_timer(self, timer_id):
        timer = self._states[timer_id]
        answer = QMessageBox.question(
            self,
            "Delete Timer",
            f"Delete {timer.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            row = self._rows.pop(timer_id)
            row.setParent(None)
            row.deleteLater()
            self._states.pop(timer_id)
            self.state_changed()
            self._refresh_zone_filter(self._selected_zone)
            self._schedule_timer_canvas()

    def state_changed(self):
        self._save()
        for row in self._rows.values():
            row.refresh()
        self._schedule_timer_canvas()

    def _save(self):
        self.checkpoint_runtime_state()

    def checkpoint_runtime_state(self):
        """Synchronously preserve Smart Timers before an app handoff."""
        config.data['timers']['items'] = [timer.to_dict() for timer in self._states.values()]
        config.save()
        return len(config.data['timers']['items'])

    @staticmethod
    def _share_time_label(epoch):
        return QLocale.system().toString(
            QDateTime.fromSecsSinceEpoch(int(epoch)),
            QLocale.FormatType.ShortFormat)

    def _remember_share_packet(self, packet_id):
        seen = config.data['timers'].setdefault('seen_share_ids', [])
        packet_id = str(packet_id or '')
        if packet_id in seen:
            return False
        seen.append(packet_id)
        del seen[:-256]
        return True

    def share_visible_timers(self):
        """Copy this zone view as codes safe for EQ Titanium chat."""
        timers = [
            timer for timer_id, timer in self._states.items()
            if timer_id in self._rows and self._row_matches_zone(timer)]
        try:
            exported = build_timer_share_codes(timers)
        except TimerShareError as error:
            self.announce(f"SHARE TIMERS · {error}")
            return False
        copied = set_eq_clipboard("\n".join(exported.codes))
        if not copied:
            self.announce(
                "SHARE TIMERS FAILED · clipboard unavailable; try again")
            return False
        for packet_id in exported.packet_ids:
            self._remember_share_packet(packet_id)
        config.save()
        zone = self._selected_zone or "All zones"
        line_text = (
            "1 chat code" if len(exported.codes) == 1 else
            f"{len(exported.codes)} chat-code lines; send each line")
        self.announce(
            f"SHARED · {exported.timer_count} timer"
            f"{'s' if exported.timer_count != 1 else ''} · {zone} · "
            f"{line_text} copied · {self._share_time_label(exported.generated_at)}")
        return True

    def _merge_shared_timer(self, incoming):
        key = (incoming.zone.strip().casefold(), incoming.name.casefold())
        existing = next((
            timer for timer in self._states.values()
            if (timer.zone.strip().casefold(), timer.name.casefold()) == key),
            None)
        if existing is None:
            self._states[incoming.timer_id] = incoming
            self._add_row(incoming)
            return "added"
        # Timing is handed off, while the receiver keeps local alert choices.
        for field in (
                "name", "respawn_seconds", "kill_seconds", "warning_seconds",
                "smart", "zone", "mob_pattern", "source", "automatic",
                "phase", "running", "phase_started_at", "deadline",
                "paused_remaining", "cycles", "warning_sent"):
            setattr(existing, field, getattr(incoming, field))
        return "updated"

    def _import_shared_timer_code(self, code, event_time):
        try:
            packet = decode_timer_share_code(code, received_at=event_time)
        except TimerShareError as error:
            self.announce(
                f"TIMER SHARE REJECTED · {error}; ask the sender to share again")
            return False
        if packet.packet_id in config.data['timers'].get(
                'seen_share_ids', []):
            return False

        outcomes = []
        for record in packet.timers:
            incoming = shared_record_to_state(
                record, packet, event_time,
                volume=config.data['timers']['volume'])
            outcomes.append(self._merge_shared_timer(incoming))
        self._remember_share_packet(packet.packet_id)
        self._refresh_zone_filter(self._selected_zone)
        self.state_changed()
        added = outcomes.count("added")
        updated = outcomes.count("updated")
        zones = sorted({record.zone for record in packet.timers if record.zone})
        hidden_zone = (
            zones[0] if len(zones) == 1 and self._selected_zone and
            zones[0].casefold() != self._selected_zone.casefold() else "")
        clock_note = (
            f" · sender clock ahead {packet.future_clock_skew_seconds}s"
            if packet.future_clock_skew_seconds else "")
        location_note = f" · saved under {hidden_zone}" if hidden_zone else ""
        self.announce(
            f"IMPORTED · {len(packet.timers)} shared timer"
            f"{'s' if len(packet.timers) != 1 else ''} · {added} added · "
            f"{updated} updated · adjusted {packet.age_seconds}s · "
            f"shared {self._share_time_label(packet.generated_at)}"
            f"{location_note}{clock_note}")
        return True

    def _toggle_compact(self):
        config.data['timers']['compact'] = self.compact.isChecked()
        self.state_changed()

    def _tick(self):
        changed = False
        completed_schedule_ids = []
        for timer in list(self._states.values()):
            events = timer.tick()
            changed = changed or bool(events)
            for event in events:
                schedule_due = (
                    timer.source == RING_WAR_SCHEDULE_SOURCE and
                    event.kind == "spawn")
                schedule_warning = (
                    timer.source == RING_WAR_SCHEDULE_SOURCE and
                    event.kind == "warning")
                remaining = max(1, int(timer.remaining() or 1))
                self.announce(
                    f"{timer.name}: due now" if schedule_due else
                    f"{timer.name}: due in {remaining} s"
                    if schedule_warning else
                    event.message)
                if event.kind in ("spawn", "warning"):
                    if (timer.source != RING_WAR_SCHEDULE_SOURCE or
                            config.data['timers'].get(
                                'encounter_sound_enabled', False)):
                        play_alert(
                            timer.sound_path, timer.volume,
                            2 if event.kind == "spawn" else 1,
                            source=(f"Timer · {timer.name} · " +
                                    ("due" if schedule_due else
                                     "spawn" if event.kind == "spawn" else
                                     "advance warning")),
                            channel="timers")
                if schedule_due:
                    completed_schedule_ids.append(timer.timer_id)
        for timer_id in completed_schedule_ids:
            self._remove_timer(timer_id)
        for row in self._rows.values():
            row.refresh()
        if changed:
            self._save()

    def announce(self, message):
        self.status.setText(message)
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.status, str(message)))
        except (AttributeError, RuntimeError, TypeError):
            pass
        QApplication.instance().show_overlay_notification(
            "Vantage", message, msecs=3500, overlay_id="timers")

    def _encounter_alert(self, message, source):
        self.announce(message)
        if config.data['timers'].get('encounter_sound_enabled', False):
            play_alert(
                'builtin:warden-bell', config.data['timers']['volume'], 2,
                source=f"Encounter · {source}", channel="timers")

    def _safety_alert(self, alert):
        enabled = config.data['timers'].get(
            'afk_attacked_enabled' if alert.kind == 'afk_attacked' else
            'death_loop_enabled', True)
        if not enabled:
            return
        self.status.setText(alert.message)
        QApplication.instance().show_overlay_notification(
            "Vantage · Safety", alert.message, msecs=6500,
            overlay_id="alerts", text_color="#E08372")
        if config.data['timers'].get('safety_sound_enabled', False):
            play_alert(
                'builtin:danger-double', config.data['timers']['volume'], 2,
                source=("Safety · attacked while tabbed out"
                        if alert.kind == 'afk_attacked' else
                        "Safety · death loop"), channel="timers")

    def _remove_timer(self, timer_id):
        row = self._rows.pop(timer_id, None)
        if row is not None:
            row.setParent(None)
            row.deleteLater()
        removed = self._states.pop(timer_id, None)
        self._schedule_timer_canvas()
        return removed

    def _start_ring_war_schedule(self, event_time):
        for timer_id, timer in list(self._states.items()):
            if timer.source == RING_WAR_SCHEDULE_SOURCE:
                self._remove_timer(timer_id)
        milestones = ring_war_milestones()
        for milestone in milestones:
            timer = SpawnTimerState(
                name=milestone.timer_name,
                respawn_seconds=milestone.seconds,
                kill_seconds=1,
                warning_seconds=30,
                color="#657A96" if milestone.is_break else "#4F8378",
                smart=False,
                zone=string.capwords(self._current_zone),
                sound_path="builtin:warden-bell",
                volume=config.data['timers']['volume'],
                source=RING_WAR_SCHEDULE_SOURCE,
                automatic=True)
            timer.start(event_time)
            self._states[timer.timer_id] = timer
            self._add_row(timer)
        self._encounter_alert(
            f"Ring War schedule started · {len(milestones)} milestones",
            "Ring War")
        self.state_changed()

    def _zone_changed(self, zone):
        self._current_zone = str(zone or '').strip()
        self._missing_zone_notified = None
        self._refresh_zone_filter(self._current_zone)
        config.save()
        entry = self._respawn_entry()
        if entry and entry.seconds:
            self.status.setText(
                f"AUTO NAMEDS · {string.capwords(self._current_zone)} · "
                f"{entry.timer_text} · {len(RESPAWN_CATALOG)} zones")

    def _catalog_context(self, zone=''):
        # Local import avoids making the catalog depend on the map renderer.
        from vantage.parsers.maps.mapdata import MapData

        canonical = MapData.resolve_zone_name(zone or self._current_zone)
        if not canonical:
            return '', '', None
        if not zone:
            self._current_zone = canonical
        short_name = MapData.get_zone_dict().get(canonical)
        return canonical, short_name, respawn_for_short_name(short_name)

    def _respawn_entry(self):
        return self._catalog_context()[2]

    def _named_respawn_entry(self, mob, zone=''):
        _canonical, short_name, entry = self._catalog_context(zone)
        return named_spawn_for(short_name, mob), entry

    def _create_automatic_timer(self, mob, event_time):
        named, entry = self._named_respawn_entry(mob)
        if not named:
            return False
        if not entry or entry.seconds is None:
            zone_key = self._current_zone.casefold()
            if self._missing_zone_notified != zone_key:
                self._missing_zone_notified = zone_key
                self.announce(
                    f"{string.capwords(self._current_zone) or 'Current zone'}: "
                    "no published respawn; no timer was invented")
            return False

        respawn_seconds = named.respawn_seconds or entry.seconds
        timer = SpawnTimerState(
            name=mob,
            respawn_seconds=respawn_seconds,
            kill_seconds=60,
            warning_seconds=30,
            color=automatic_timer_color(self._current_zone, mob),
            smart=False,
            zone=string.capwords(self._current_zone),
            mob_pattern=rf"^{re.escape(mob)}$",
            sound_path="builtin:spawn-horn",
            volume=config.data['timers']['volume'],
            source=NAMED_CATALOG_SOURCE,
            automatic=True,
        )
        # A death line is the anchor: the newly created timer is running from
        # this exact log timestamp, never left idle in READY.
        timer.mark_killed(event_time)
        self._states[timer.timer_id] = timer
        self._add_row(timer)
        detail = f" · {entry.note}" if entry.note else ""
        self.announce(
            f"{mob}: named timer {format_seconds(respawn_seconds)} started · "
            f"{string.capwords(self._current_zone)}{detail}")
        return True

    def _start_log_command_timer(self, duration, label, event_time):
        timer = next((
            state for state in self._states.values()
            if state.source == 'Log command' and
            state.name.casefold() == label.casefold() and
            str(state.zone or '').strip().casefold() == string.capwords(
                self._current_zone).casefold()), None)
        if timer is None:
            timer = SpawnTimerState(
                name=label,
                respawn_seconds=duration,
                kill_seconds=60,
                warning_seconds=min(30, max(1, duration // 10)),
                color=automatic_timer_color(self._current_zone, label),
                smart=False,
                zone=string.capwords(self._current_zone),
                sound_path='builtin:spawn-horn',
                volume=config.data['timers']['volume'],
                source='Log command')
            self._states[timer.timer_id] = timer
            self._add_row(timer)
        else:
            timer.respawn_seconds = duration
            timer.warning_seconds = min(30, max(1, duration // 10))
        timer.start(event_time)
        self.announce(
            f'{label}: log command timer started · {format_seconds(duration)}')
        self.state_changed()

    def parse(self, timestamp, text):
        if text.startswith("You have entered "):
            self._zone_changed(text[17:].rstrip('.'))
        event_time = (
            timestamp.timestamp()
            if isinstance(timestamp, datetime.datetime) else time.time())
        if TIMER_SHARE_PREFIX in text:
            codes = extract_timer_share_codes(text)
            if not codes:
                self.announce(
                    "TIMER SHARE REJECTED · incomplete code; ask the sender "
                    "to share again")
                return
            for code in codes:
                self._import_shared_timer_code(code, event_time)
            return
        self._safety.configure(
            config.data['timers'].get('death_loop_deaths', 4),
            config.data['timers'].get('death_loop_seconds', 120))
        focused = False
        if ('You' in text or 'YOU' in text):
            focus_probe = getattr(
                QApplication.instance(), 'is_everquest_foreground', None)
            focused = bool(focus_probe()) if callable(focus_probe) else False
        for alert in self._safety.ingest(timestamp, text, focused):
            self._safety_alert(alert)
        if config.data['timers'].get('encounter_events_enabled', True):
            encounter = parse_encounter_event(text)
            if encounter:
                if encounter.kind == 'ring_war':
                    self._start_ring_war_schedule(event_time)
                else:
                    self._encounter_alert(
                        encounter.message,
                        'FTE' if encounter.kind == 'fte' else 'server quake')
                return
        command = extract_log_timer_command(text)
        if command:
            self._start_log_command_timer(*command, event_time)
            return
        mob = extract_killed_mob(text)
        if not mob:
            return
        changed = False
        matched_timer = False
        for timer in self._states.values():
            if timer.matches_kill(mob, self._current_zone):
                if (timer.automatic and timer.source in (
                        CATALOG_SOURCE, NAMED_CATALOG_SOURCE)):
                    named, entry = self._named_respawn_entry(mob)
                    if not named:
                        continue
                    if named.respawn_seconds:
                        timer.respawn_seconds = named.respawn_seconds
                    elif entry and entry.seconds:
                        timer.respawn_seconds = entry.seconds
                timer.mark_killed(event_time)
                changed = True
                matched_timer = True
        if matched_timer:
            self.announce(f"{mob}: death detected; timer restarted")
        elif config.data['timers'].get('auto_from_log', True):
            changed = self._create_automatic_timer(mob, event_time)
        if changed:
            self.state_changed()
