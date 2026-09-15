"""Modern shared timer workspaces for Project 1999."""

from __future__ import annotations

import datetime
import hashlib
import math
import re
import string
import time
import uuid

from PySide6.QtCore import QDateTime, QEvent, QLocale, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor, QFont, QKeySequence,
    QLinearGradient, QPainter, QPainterPath, QShortcut)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
    NAMED_CATALOG_SOURCE_URL, NAMED_SPAWN_CATALOG, RESPAWN_CATALOG,
    named_spawn_for,
    respawn_for_short_name)
from vantage.helpers.safety_alerts import SafetyAlertState
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.spawn_timer import (
    PHASE_AVAILABLE,
    PHASE_COMBAT,
    PHASE_IDLE,
    PHASE_RESPAWN,
    SpawnTimerState,
    TIMER_MODE_COOLDOWN,
    TIMER_MODE_COUNTDOWN,
    TIMER_MODE_SPAWN,
    MAX_DEATH_MOB_NAME_LENGTH,
    MAX_DEATH_MOBS,
    normalize_death_mobs,
    reset_stale_persisted_timers,
    format_seconds,
    parse_duration_input,
    zone_timer_visible,
)
from vantage.helpers.timer_share import (
    TIMER_SHARE_PREFIXES,
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


NAMED_MOB_SUGGESTIONS = tuple(sorted(
    {
        entry.npc_name.strip().casefold(): entry.npc_name.strip()
        for entry in NAMED_SPAWN_CATALOG.values()
        if entry.npc_name.strip()
    }.values(), key=str.casefold))

AUTO_TIMER_COLORS = (
    "#B97252", "#9A7650", "#7B8755", "#4F8378",
    "#657A96", "#806C91", "#995E73", "#8D7048",
)
MAX_CROSS_ZONE_WATCHES = 64


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
            QSize(500, 580), parent, minimum_size=QSize(200, 232))
        self.timer = timer
        self.color = timer.color if timer else "#B38C52"
        self.setWindowTitle("Edit Smart Timer" if timer else "New Smart Timer")

        form = polish_form(QFormLayout())
        self._timer_form = form
        form.setSpacing(5)
        self.name = QLineEdit(timer.name if timer else "")
        self.name.setPlaceholderText("Example: Quillmane")
        self.name.setToolTip(
            "A short label shown on the timer row, overlays, and phone view")
        form.addRow("Name", self.name)

        self.timer_mode = QComboBox()
        self.timer_mode.addItem("Spawn / respawn", TIMER_MODE_SPAWN)
        self.timer_mode.addItem("General countdown", TIMER_MODE_COUNTDOWN)
        self.timer_mode.addItem("Reusable cooldown", TIMER_MODE_COOLDOWN)
        current_mode = getattr(timer, "timer_mode", TIMER_MODE_SPAWN)
        selected_mode = self.timer_mode.findData(current_mode)
        self.timer_mode.setCurrentIndex(max(0, selected_mode))
        self.timer_mode.setAccessibleName("Timer type")
        self.timer_mode.setToolTip(
            "Choose a mob spawn cycle, a one-time general countdown, or a "
            "cooldown that can be restarted whenever it is used")
        form.addRow("Timer type", self.timer_mode)

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
            "Play and display a warning this many seconds before the timer "
            "finishes or the spawn becomes available")
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
            "Only match death lines while this zone is active. Blank allows "
            "detection in any zone, but the row appears only under All saved "
            "timers unless a window explicitly watches it.")
        form.addRow("Zone", self.zone)

        # ``mob_pattern`` remains hidden for saved pre-list timers. New input
        # is stored as a full name or distinctive multi-word match phrase.
        self.mob_pattern = QLineEdit(timer.mob_pattern if timer else "")
        self.mob_pattern.hide()
        self._death_list_changed = False
        initial_death_mobs = normalize_death_mobs(
            getattr(timer, "death_mobs", []) if timer else [])
        if (timer and not initial_death_mobs and
                not str(getattr(timer, "mob_pattern", "") or "").strip()):
            initial_death_mobs = normalize_death_mobs([timer.name])

        self.death_mob_panel = QWidget()
        self.death_mob_panel.setMinimumHeight(164)
        self.death_mob_panel.setAccessibleName("Detect deaths")
        self.death_mob_panel.setAccessibleDescription(
            "Adds full mob or placeholder names, or distinctive multi-word "
            "phrases, that can restart this timer")
        death_layout = QVBoxLayout(self.death_mob_panel)
        death_layout.setContentsMargins(0, 0, 0, 0)
        death_layout.setSpacing(4)
        death_input_row = QHBoxLayout()
        death_input_row.setContentsMargins(0, 0, 0, 0)
        death_input_row.setSpacing(4)
        self.death_mob_picker = QComboBox()
        self.death_mob_picker.setEditable(True)
        self.death_mob_picker.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert)
        self.death_mob_picker.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.death_mob_picker.setMinimumContentsLength(12)
        self.death_mob_picker.addItems(NAMED_MOB_SUGGESTIONS)
        self.death_mob_picker.setCurrentIndex(-1)
        self.death_mob_picker.setAccessibleName(
            "Detect deaths: named mob or custom placeholder")
        self.death_mob_picker.setAccessibleDescription(
            "Editable named-mob picker. Type to search all bundled P99 "
            "nameds, use Arrow keys to choose a suggestion, or type a "
            "custom placeholder; press Enter to add it. Save up to 24 full "
            "names or distinctive multi-word phrases of no more than 128 "
            "characters each.")
        self.death_mob_input = self.death_mob_picker.lineEdit()
        self.death_mob_input.setPlaceholderText("Named mob or custom PH")
        self.death_mob_input.setAccessibleName(
            "Detect deaths: mob or placeholder name to add")
        self.death_mob_input.setAccessibleDescription(
            "Type a full mob or placeholder name, or a distinctive phrase of "
            "two or more words. Suggestions search all named mobs in "
            "Vantage's P99 catalog, regardless of selected zone. Use Arrow "
            "keys to select a suggestion and Enter to add.")
        self.death_mob_input.setToolTip(
            "Add a full name or distinctive multi-word phrase. Type to search "
            "every bundled P99 named mob, or enter a custom placeholder; "
            "press Enter to add.")
        self.death_mob_picker.setToolTip(self.death_mob_input.toolTip())
        self.death_mob_completer = self.death_mob_picker.completer()
        self.death_mob_completer.setCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self.death_mob_completer.setFilterMode(
            Qt.MatchFlag.MatchContains)
        self.death_mob_completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion)
        self.death_mob_completer.setMaxVisibleItems(10)
        completion_popup = self.death_mob_completer.popup()
        completion_popup.setAccessibleName("P99 named mob suggestions")
        completion_popup.setAccessibleDescription(
            "Filtered suggestions from every zone; use Arrow keys and Enter "
            "to add one to this timer.")
        self.death_mob_input.returnPressed.connect(
            self._death_mob_return_pressed)
        self.death_mob_completer.activated[str].connect(
            self._add_death_mob_suggestion)
        self.death_mob_picker.installEventFilter(self)
        self.death_mob_input.installEventFilter(self)
        death_input_row.addWidget(self.death_mob_picker, 1)

        self.death_mob_add = QPushButton("Add")
        self.death_mob_add.setAccessibleName(
            "Add death detection name or phrase")
        self.death_mob_add.setAccessibleDescription(
            "Adds the typed catalog suggestion, custom placeholder, or "
            "distinctive multi-word phrase for this timer")
        self.death_mob_add.setToolTip(
            "Add the typed named mob or custom placeholder to this timer")
        self.death_mob_add.clicked.connect(self._add_death_mob)
        death_input_row.addWidget(self.death_mob_add)
        self.death_mob_remove = QPushButton("Remove")
        self.death_mob_remove.setAccessibleName(
            "Remove selected death detection name")
        self.death_mob_remove.setAccessibleDescription(
            "Removes the selected mob or placeholder match from this "
            "timer without changing other entries")
        self.death_mob_remove.setToolTip(
            "Remove the selected match; Delete works from the list too")
        self.death_mob_remove.clicked.connect(self._remove_death_mob)
        death_input_row.addWidget(self.death_mob_remove)
        death_layout.addLayout(death_input_row)

        self.death_mob_list = QListWidget()
        self.death_mob_list.setMinimumHeight(76)
        self.death_mob_list.setMaximumHeight(88)
        self.death_mob_list.setAccessibleName(
            "Detect deaths: mob and placeholder match list")
        self.death_mob_list.setAccessibleDescription(
            "Each complete name can restart this timer. Select a name and "
            "press Delete or Remove to stop matching it.")
        self.death_mob_list.setToolTip(
            "Full names and distinctive phrases that restart this timer from "
            "an EverQuest death line")
        self.death_mob_list.installEventFilter(self)
        self.death_mob_list.currentRowChanged.connect(
            self._refresh_death_mob_actions)
        for mob_name in initial_death_mobs:
            self.death_mob_list.addItem(mob_name)
        death_layout.addWidget(self.death_mob_list)

        self.death_mob_help = QLabel(
            "Full names or 2+ word partial phrases · up to 24 entries · "
            "128 characters each · all P99 nameds or any custom PH")
        self.death_mob_help.setWordWrap(True)
        self.death_mob_help.setAccessibleDescription(
            "Detect deaths instructions: full names or distinctive partial "
            "phrases of two or more words; up to 24 entries; all P99 nameds "
            "or any custom placeholder")
        self.death_mob_help.setToolTip(
            "Full names match exactly; partial phrases need two or more "
            "contiguous words from the EverQuest death-line name")
        death_layout.addWidget(self.death_mob_help)

        self.death_mob_status = QLabel()
        self.death_mob_status.setAccessibleName("Death detection list status")
        self.death_mob_status.setAccessibleDescription(
            "Reports death-name or phrase additions, removals, duplicates, "
            "and limits")
        self.death_mob_status.setToolTip(
            "Status for this timer's death detection names and phrases")
        death_layout.addWidget(self.death_mob_status)
        form.addRow("Detect deaths", self.death_mob_panel)
        detect_label = form.labelForField(self.death_mob_panel)
        if detect_label is not None:
            detect_label.setBuddy(self.death_mob_picker)
        self._death_suggestion_announce_timer = QTimer(self)
        self._death_suggestion_announce_timer.setSingleShot(True)
        self._death_suggestion_announce_timer.setInterval(350)
        self._death_suggestion_announce_timer.timeout.connect(
            self._announce_death_mob_status)
        self.finished.connect(
            lambda _result: self._death_suggestion_announce_timer.stop())
        self.death_mob_input.textChanged.connect(
            self._death_mob_input_changed)
        self._refresh_death_mob_actions()
        if timer and str(getattr(timer, "mob_pattern", "") or "").strip():
            self._set_death_mob_status(
                "Legacy death pattern remains active until this list changes")
        else:
            self._set_death_mob_count_status()
        self.timer_mode.currentIndexChanged.connect(
            self._timer_mode_changed)
        self._timer_mode_changed()

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
            "Inherit Settings › Sounds, turn this timer off, or choose an "
            "individual built-in/portable sound override")
        configured_sound = timer.sound_path if timer else None
        set_sound_combo_value(self.sound, configured_sound or "")
        self.sound.insertItem(0, "Use Smart Timer notification route", None)
        if configured_sound is None:
            self.sound.setCurrentIndex(0)
        browse = QPushButton("WAV…")
        browse.setIcon(game_icon("copy"))
        browse.setToolTip(
            "Add a royalty-free WAV file to Vantage's portable sound gallery")
        browse.clicked.connect(self._browse_sound)
        test = QPushButton("Test")
        test.setIcon(game_icon("play"))
        test.setAccessibleName("Test this timer notification")
        test.setToolTip(
            "Test the selected inherited, Off, or individual timer delivery "
            "at this timer's volume")
        sound_row.addWidget(self.sound)
        sound_actions = ResponsiveActionBar(88)
        sound_actions.addWidget(browse)
        sound_actions.addWidget(test)
        sound_row.addWidget(sound_actions)
        self.sound_test_status = QLabel("Test status · ready")
        self.sound_test_status.setAccessibleName("Timer notification test status")
        self.sound_test_status.setToolTip(
            "Reports whether the test played sound or voice, is Off, was "
            "blocked, or is unavailable")
        self.sound_test_status.setWordWrap(True)
        sound_row.addWidget(self.sound_test_status)
        form.addRow("Alarm gallery", sound_panel)

        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setValue(
            timer.volume if timer else config.data['timers']['volume'])
        self.volume.setAccessibleName("Individual timer volume")
        self.volume.setToolTip(
            "Volume for this timer only; 0 mutes its alarm")
        test.clicked.connect(self._test_notification)
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

    def _test_notification(self):
        """Test the exact effective timer route without creating a rail event."""
        app = QApplication.instance()
        selected = (None if self.sound.currentIndex() == 0 else
                    str(self.sound.currentData() or ""))
        result = None
        if app is not None and hasattr(app, "notify_event"):
            result = app.notify_event(
                "smart_timer", "Smart Timer test",
                voice_text="Smart Timer test", overlay=False, register=False,
                sound_override=selected, volume=self.volume.value(), repeat=2,
                channel="timers", allow_hidden=True)
        elif selected:
            played = play_alert(
                selected, self.volume.value(), 2,
                source=f"Test · timer {self.name.text().strip() or 'new'}",
                allow_hidden=True)
            result = type("Result", (), {
                "delivery": "sound", "state": (
                    "played" if played else "unavailable"), "reason": ""})()

        delivery = getattr(result, "delivery", "off")
        state = getattr(result, "state", "off")
        reason = str(getattr(result, "reason", "") or "").strip()
        if delivery == "off":
            message = "Test status · Off — this timer will not play audio"
        elif state == "played":
            message = f"Test status · {delivery} played"
        elif state == "blocked":
            message = f"Test status · blocked" + (f" · {reason}" if reason else "")
        else:
            message = f"Test status · {delivery} unavailable"
        self.sound_test_status.setText(message)
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.sound_test_status, message))
        except (AttributeError, RuntimeError):
            pass
        return result

    @staticmethod
    def _normalize_duration(field):
        seconds = parse_duration_input(field.text())
        if seconds > 0:
            field.setText(format_seconds(seconds))

    def _death_mob_names(self):
        return normalize_death_mobs([
            self.death_mob_list.item(index).text()
            for index in range(self.death_mob_list.count())])

    def _set_death_mob_status(self, message, announce=False):
        message = str(message or "").strip()
        self.death_mob_status.setText(message)
        self.death_mob_status.setAccessibleDescription(message)
        if announce:
            self._announce_death_mob_status()

    def _announce_death_mob_status(self):
        message = self.death_mob_status.text().strip()
        if not message:
            return
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(
                    self.death_mob_status, message))
        except (AttributeError, RuntimeError):
            pass

    def _set_death_mob_count_status(self, announce=False):
        count = self.death_mob_list.count()
        message = (
            f"0 of {MAX_DEATH_MOBS} saved · the timer name matches exactly"
            if not count else
            f"{count} of {MAX_DEATH_MOBS} death "
            f"match{'es' if count != 1 else ''} saved")
        self._set_death_mob_status(message, announce=announce)

    def _death_mob_input_changed(self, text):
        self._refresh_death_mob_actions()
        query = str(text or "").strip()
        if not query:
            self._death_suggestion_announce_timer.stop()
            self._set_death_mob_count_status()
            return
        self.death_mob_completer.setCompletionPrefix(query)
        suggestions = self.death_mob_completer.completionCount()
        saved = self.death_mob_list.count()
        if suggestions:
            message = (
                f"{suggestions} named suggestion"
                f"{'s' if suggestions != 1 else ''} · {saved} of "
                f"{MAX_DEATH_MOBS} saved · use Arrow keys and Enter")
        else:
            message = (
                f"No catalog suggestion · {saved} of {MAX_DEATH_MOBS} "
                "saved · Enter adds this custom PH")
        self._set_death_mob_status(message)
        self._death_suggestion_announce_timer.start()

    def _refresh_death_mob_actions(self, *_args):
        self.death_mob_add.setEnabled(bool(
            self.death_mob_input.text().strip()))
        self.death_mob_remove.setEnabled(
            self.death_mob_list.currentRow() >= 0)

    def _add_death_mob_suggestion(self, name):
        selected = str(name or "")
        # QCompleter writes its selected text back into the line edit after
        # emitting activated(). Commit on the next event-loop turn so the
        # successful add can clear the field once, after that write.
        QTimer.singleShot(
            0, lambda: self._commit_death_mob_suggestion(selected))

    def _commit_death_mob_suggestion(self, name):
        self.death_mob_input.setText(name)
        return self._add_death_mob()

    def _death_mob_return_pressed(self):
        """Let an active completer selection own Enter exactly once."""
        popup = self.death_mob_completer.popup()
        if popup.isVisible() and popup.currentIndex().isValid():
            return False
        return self._add_death_mob()

    def _add_death_mob(self):
        self._death_suggestion_announce_timer.stop()
        raw_name = " ".join(self.death_mob_input.text().split())
        if len(raw_name) > MAX_DEATH_MOB_NAME_LENGTH:
            self._set_death_mob_status(
                f"Name is {len(raw_name)} characters · maximum is "
                f"{MAX_DEATH_MOB_NAME_LENGTH}; shorten it before adding",
                announce=True)
            self.death_mob_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        values = normalize_death_mobs([raw_name])
        if not values:
            self._set_death_mob_status(
                "Type a mob or placeholder name to add", announce=True)
            self.death_mob_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        name = values[0]
        existing = {
            self.death_mob_list.item(index).text().casefold(): index
            for index in range(self.death_mob_list.count())
        }
        if name.casefold() in existing:
            row = existing[name.casefold()]
            self.death_mob_list.setCurrentRow(row)
            self._set_death_mob_status(
                f"Already added: {self.death_mob_list.item(row).text()}",
                announce=True)
            self.death_mob_input.selectAll()
            self.death_mob_input.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        if self.death_mob_list.count() >= MAX_DEATH_MOBS:
            self._set_death_mob_status(
                f"Limit reached · remove one of {MAX_DEATH_MOBS} names",
                announce=True)
            self.death_mob_list.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        self.death_mob_list.addItem(name)
        self.death_mob_list.setCurrentRow(self.death_mob_list.count() - 1)
        self.death_mob_input.clear()
        self._death_list_changed = True
        self._set_death_mob_count_status(announce=True)
        self.death_mob_input.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _remove_death_mob(self):
        row = self.death_mob_list.currentRow()
        if row < 0:
            self._set_death_mob_status(
                "Select a death name to remove", announce=True)
            self.death_mob_list.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        removed = self.death_mob_list.takeItem(row)
        removed_name = removed.text() if removed is not None else ""
        self._death_list_changed = True
        if self.death_mob_list.count():
            self.death_mob_list.setCurrentRow(
                min(row, self.death_mob_list.count() - 1))
            self.death_mob_list.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.death_mob_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self._set_death_mob_status(
            f"Removed {removed_name} · " + (
                f"{self.death_mob_list.count()} death match"
                f"{'es' if self.death_mob_list.count() != 1 else ''} remain"
                if self.death_mob_list.count() else
                "the timer name now matches exactly"),
            announce=True)
        self._refresh_death_mob_actions()
        return True

    def eventFilter(self, watched, event):
        if (watched in (
                getattr(self, 'death_mob_picker', None),
                getattr(self, 'death_mob_input', None)) and
                event.type() == QEvent.Type.KeyPress):
            popup = self.death_mob_completer.popup()
            if popup.isVisible() and event.key() in (
                    Qt.Key.Key_Down, Qt.Key.Key_Up):
                model = self.death_mob_completer.completionModel()
                count = model.rowCount()
                if count:
                    current = popup.currentIndex().row()
                    if event.key() == Qt.Key.Key_Down:
                        row = 0 if current < 0 else min(count - 1, current + 1)
                    else:
                        row = count - 1 if current < 0 else max(0, current - 1)
                    index = model.index(row, 0)
                    popup.setCurrentIndex(index)
                    popup.scrollTo(index)
                return True
            if popup.isVisible() and event.key() in (
                    Qt.Key.Key_Return, Qt.Key.Key_Enter):
                index = popup.currentIndex()
                if index.isValid():
                    selected = str(index.data() or "")
                    popup.hide()
                    self._add_death_mob_suggestion(selected)
                    return True
            if popup.isVisible() and event.key() == Qt.Key.Key_Escape:
                popup.hide()
                return True
        if (watched is getattr(self, 'death_mob_list', None) and
                event.type() == QEvent.Type.KeyPress and
                event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)):
            self._remove_death_mob()
            return True
        return super().eventFilter(watched, event)

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
        if (self.timer_mode.currentData() == TIMER_MODE_SPAWN and
                parse_duration_input(self.kill.text()) <= 0):
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
        timer.timer_mode = str(
            self.timer_mode.currentData() or TIMER_MODE_SPAWN)
        timer.respawn_seconds = parse_duration_input(self.respawn.text())
        timer.kill_seconds = parse_duration_input(self.kill.text())
        timer.warning_seconds = self.warning.value()
        timer.smart = self.smart.isChecked()
        timer.zone = self.zone.text().strip()
        timer.death_mobs = self._death_mob_names()
        if self._death_list_changed or timer.death_mobs:
            timer.mob_pattern = ""
        else:
            timer.mob_pattern = self.mob_pattern.text().strip()
        timer.color = self.color
        selected = self.sound.currentData()
        timer.sound_path = None if self.sound.currentIndex() == 0 else str(
            selected or "")
        timer.volume = self.volume.value()
        return timer

    def _timer_mode_changed(self, *_args):
        """Keep the editor concise and avoid mob-only wording for general timers."""
        spawn_mode = self.timer_mode.currentData() == TIMER_MODE_SPAWN
        # QFormLayout owns the generated label widgets, so update them through
        # the fields rather than depending on insertion row numbers.
        form = self._timer_form
        duration_label = form.labelForField(self.respawn)
        if duration_label is not None:
            duration_label.setText("Respawn time" if spawn_mode else "Duration")
        for field in (
                self.kill, self.smart, self.mob_pattern,
                self.death_mob_panel):
            field.setEnabled(spawn_mode)
        kill_label = form.labelForField(self.kill)
        smart_label = form.labelForField(self.smart)
        detect_label = form.labelForField(self.death_mob_panel)
        for label in (kill_label, smart_label, detect_label):
            if label is not None:
                label.setEnabled(spawn_mode)
        self.respawn.setToolTip(
            "Time until the next spawn: 3 means 3 minutes; 3:50 and "
            "1:03:50 are also accepted" if spawn_mode else
            "Length of this timer: 3 means 3 minutes; 3:50 and 1:03:50 "
            "are also accepted")


class TimerWatchDialog(UniformScaleDialog):
    """Choose explicit cross-zone timer rows for one timer window."""

    def __init__(
            self, timers, selected_zone, watched_timer_ids=(), parent=None):
        super().__init__(
            QSize(560, 470), parent, minimum_size=QSize(224, 188))
        self.setWindowTitle("Watch Timers in This Window")
        self.selected_zone = str(selected_zone or "").strip()
        self._timers = tuple(sorted(
            (timer for timer in timers if timer is not None),
            key=lambda timer: (
                str(timer.zone or "").casefold(), timer.name.casefold())))
        known_ids = {timer.timer_id for timer in self._timers}
        self._checked_ids = {
            str(timer_id) for timer_id in watched_timer_ids
            if str(timer_id) in known_ids}

        layout = QVBoxLayout(self.scaled_surface)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)

        zone_label = self.selected_zone or "All saved timers"
        instructions_text = (
            f"Showing {zone_label}. Check timers from other zones to keep "
            "them visible in this window. Their saved zone and timer state "
            "do not change.")
        instructions = QLabel(instructions_text)
        instructions.setWordWrap(True)
        instructions.setAccessibleDescription(instructions_text)
        instructions.setToolTip(
            "A watch changes only this window's visible rows; it never copies "
            "or moves a timer")
        layout.addWidget(instructions)

        search_label = QLabel("Search saved timers")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Timer name, origin zone, or source")
        self.search.setAccessibleName("Search all saved timers")
        self.search.setAccessibleDescription(
            "Filters timers from every saved zone without changing which "
            "timers are checked")
        self.search.setToolTip(
            "Filter the complete saved-timer list by name, origin zone, or "
            "source")
        search_label.setBuddy(self.search)
        layout.addWidget(search_label)
        layout.addWidget(self.search)

        self.timer_list = QListWidget()
        self.timer_list.setMinimumHeight(250)
        self.timer_list.setAccessibleName(
            "Saved timers available to watch in this window")
        self.timer_list.setAccessibleDescription(
            "Check external-zone timers with Space. Timers already included "
            "by the selected zone remain selectable for review, but their "
            "checked state is read-only because no watch is needed.")
        self.timer_list.setToolTip(
            "Origin zone is shown on every row. Press Space to watch or stop "
            "watching an enabled row in this window.")
        self.timer_list.itemChanged.connect(self._item_changed)
        layout.addWidget(self.timer_list, 1)

        self.status = QLabel()
        self.status.setAccessibleName("Cross-zone watch status")
        self.status.setAccessibleDescription(
            "Reports search results and the number of explicitly watched "
            "external timers")
        self.status.setToolTip(
            "Current saved-timer search and watch-selection summary")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel)
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        apply_button.setText("Apply")
        apply_button.setObjectName("PrimaryAction")
        apply_button.setToolTip(
            "Apply these watched timers to this timer window only")
        cancel_button.setText("Cancel")
        cancel_button.setToolTip(
            "Discard watch changes and return to the timer window")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._search_announce_timer = QTimer(self)
        self._search_announce_timer.setSingleShot(True)
        self._search_announce_timer.setInterval(350)
        self._search_announce_timer.timeout.connect(
            self._announce_current_status)
        self.finished.connect(
            lambda _result: self._search_announce_timer.stop())
        self.search.textChanged.connect(self._search_changed)
        self._rebuild_list()
        QTimer.singleShot(
            0, lambda: self.search.setFocus(
                Qt.FocusReason.OtherFocusReason))

    def _is_included_by_zone(self, timer):
        return zone_timer_visible(timer.zone, self.selected_zone)

    def _matches_search(self, timer, query):
        if not query:
            return True
        return query in " ".join((
            timer.name,
            str(timer.zone or "Unassigned"),
            str(timer.source or "User-created"))).casefold()

    def _search_changed(self, *_args):
        self._rebuild_list()
        self._search_announce_timer.start()

    def _announce_current_status(self):
        message = self.status.text()
        if message:
            try:
                QAccessible.updateAccessibility(
                    QAccessibleAnnouncementEvent(self.status, message))
            except (AttributeError, RuntimeError, TypeError):
                pass

    def _rebuild_list(self, *_args):
        query = self.search.text().strip().casefold()
        matches = [
            timer for timer in self._timers
            if self._matches_search(timer, query)]
        self.timer_list.blockSignals(True)
        self.timer_list.clear()
        for timer in matches:
            origin_zone = str(timer.zone or "").strip() or "Unassigned"
            included = self._is_included_by_zone(timer)
            suffix = " · Included by selected zone" if included else ""
            text = f"{timer.name} · {origin_zone}{suffix}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, timer.timer_id)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, text)
            item.setData(
                Qt.ItemDataRole.AccessibleDescriptionRole,
                f"{timer.name}, origin zone {origin_zone}. " + (
                    "Already included by the selected zone; no watch is "
                    "needed." if included else
                    "Press Space to toggle Watch in this window."))
            item.setToolTip(
                f"Origin zone: {origin_zone}\n" + (
                    "Already visible because it belongs to the selected zone"
                    if included else
                    "Check to watch this timer in this window"))
            item.setCheckState(
                Qt.CheckState.Checked if (
                    included or timer.timer_id in self._checked_ids) else
                Qt.CheckState.Unchecked)
            if included:
                item.setFlags(
                    (item.flags() | Qt.ItemFlag.ItemIsEnabled |
                     Qt.ItemFlag.ItemIsSelectable) &
                    ~Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(
                    item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.timer_list.addItem(item)
        self.timer_list.blockSignals(False)
        self._set_status(
            f"{len(matches)} of {len(self._timers)} saved timers shown · "
            f"{len(self._checked_ids)} explicitly watched")

    def _item_changed(self, item):
        timer_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not timer_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            if (timer_id not in self._checked_ids and
                    len(self._checked_ids) >= MAX_CROSS_ZONE_WATCHES):
                self.timer_list.blockSignals(True)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.timer_list.blockSignals(False)
                self._set_status(
                    f"Watch limit reached · remove one of "
                    f"{MAX_CROSS_ZONE_WATCHES} selections", announce=True)
                return
            self._checked_ids.add(timer_id)
        else:
            self._checked_ids.discard(timer_id)
        self._set_status(
            f"{len(self._checked_ids)} timer"
            f"{'s' if len(self._checked_ids) != 1 else ''} explicitly "
            "watched in this window", announce=True)

    def _set_status(self, message, announce=False):
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        if announce:
            try:
                QAccessible.updateAccessibility(
                    QAccessibleAnnouncementEvent(self.status, message))
            except (AttributeError, RuntimeError, TypeError):
                pass

    def selected_timer_ids(self):
        """Return a stable, bounded selection in saved-timer order."""
        return [
            timer.timer_id for timer in self._timers
            if timer.timer_id in self._checked_ids
        ][:MAX_CROSS_ZONE_WATCHES]


class TimerRow(QFrame):
    COMPACT_MINIMUM_HEIGHT = 40
    DETAILED_MINIMUM_HEIGHT = 82
    CONTROLS_SIZE = QSize(184, 28)

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

        self.killed_button = QPushButton()
        self._polish_action(self.killed_button, "warning")
        self.killed_button.setIcon(game_icon("kill"))
        self.killed_button.setObjectName("WarningAction")
        self.killed_button.setAccessibleName(f"Confirm death of {timer.name}")
        self.killed_button.setToolTip("Mob killed: start respawn")
        self.killed_button.clicked.connect(self._killed)
        controls_layout.addWidget(self.killed_button)

        self.spawned_button = QPushButton()
        self._polish_action(self.spawned_button, "primary")
        self.spawned_button.setIcon(game_icon("spawn"))
        self.spawned_button.setObjectName("PrimaryAction")
        self.spawned_button.setAccessibleName(f"Confirm spawn of {timer.name}")
        self.spawned_button.setToolTip("Mob spawned: start estimated kill time")
        self.spawned_button.clicked.connect(self._spawned)
        controls_layout.addWidget(self.spawned_button)

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
        if (self.timer.timer_mode != TIMER_MODE_SPAWN and
                self.timer.phase == PHASE_AVAILABLE):
            self.timer.start()
        elif self.timer.running:
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
            f"{self.timer.name}: " + (
                "respawn countdown restarted"
                if self.timer.timer_mode == TIMER_MODE_SPAWN else
                "timer restarted"))
        self.owner.state_changed()

    def _clear(self):
        self.timer.reset()
        self.owner.announce(f"{self.timer.name}: countdown cleared to READY")
        self.owner.state_changed()

    def _spawned(self):
        self.timer.mark_spawned()
        self.owner.announce(f"{self.timer.name}: spawn confirmed")
        self.owner.state_changed()

    def refresh(self):
        timer = self.timer
        watched_elsewhere = bool(
            getattr(self.owner, "_is_cross_zone_watch", lambda _timer: False)(
                timer))
        origin_zone = str(timer.zone or "").strip() or "Unassigned"
        self.name_label.setText(
            f"{timer.name} · {origin_zone}" if watched_elsewhere else
            timer.name)
        self.name_label.setToolTip(
            f"Watched from origin zone: {origin_zone}"
            if watched_elsewhere else
            "Timer name; edit the timer to change it")
        self.setAccessibleName(
            f"Watched timer {timer.name} from {origin_zone}"
            if watched_elsewhere else f"Timer for {timer.name}")
        self.setAccessibleDescription(
            f"Shown by an explicit cross-zone watch in this window; saved "
            f"origin zone {origin_zone}."
            if watched_elsewhere else
            f"Timer included in the "
            f"{getattr(self.owner, '_selected_zone', '') or 'all saved'} "
            "timer view.")
        phase_text = PHASE_TEXT.get(timer.phase, timer.phase.upper())
        if timer.timer_mode == TIMER_MODE_COUNTDOWN:
            phase_text = (
                "DONE" if timer.phase == PHASE_AVAILABLE else
                "COUNTDOWN" if timer.phase == PHASE_RESPAWN else phase_text)
        elif timer.timer_mode == TIMER_MODE_COOLDOWN:
            phase_text = (
                "READY" if timer.phase == PHASE_AVAILABLE else
                "COOLDOWN" if timer.phase == PHASE_RESPAWN else phase_text)
        self.phase_label.setText(phase_text)
        if timer.source == RING_WAR_SCHEDULE_SOURCE:
            self.phase_label.setText("EVENT")
        self.phase_label.setProperty("Phase", timer.phase)
        self.phase_label.setStyle(self.phase_label.style())
        remaining = timer.remaining()
        if (not timer.running and timer.phase != PHASE_IDLE and not (
                timer.timer_mode != TIMER_MODE_SPAWN and
                timer.phase == PHASE_AVAILABLE)):
            self.phase_label.setText("PAUSED")
        self.time_label.setText("--:--" if remaining is None else format_seconds(remaining))
        self.progress.setValue(timer.progress_percent())
        self.progress.setAccessibleDescription(
            f"{self.phase_label.text()}, {self.time_label.text()} remaining"
        )
        smart = "AUTO-KILL" if timer.smart else "LOG KILL"
        zone = f" · {timer.zone}" if timer.zone else ""
        source = f" · {timer.source}" if timer.source else ""
        if timer.source == RING_WAR_SCHEDULE_SOURCE:
            self.detail_label.setText(
                f"LOCAL LOG · RING WAR · {timer.source}")
        elif timer.timer_mode != TIMER_MODE_SPAWN:
            mode_label = (
                "COUNTDOWN" if timer.timer_mode == TIMER_MODE_COUNTDOWN
                else "REUSABLE COOLDOWN")
            self.detail_label.setText(
                f"{mode_label} · duration {format_seconds(timer.respawn_seconds)} · "
                f"completed {timer.cycles}{zone}{source}")
        elif timer.automatic:
            self.detail_label.setText(
                f"AUTO LOG · {smart} · cycle {timer.cycles}{zone}{source}")
        else:
            self.detail_label.setText(
                f"{smart} · kill {format_seconds(timer.kill_seconds)} · "
                f"cycle {timer.cycles}{zone}{source}")
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
            f"Start {timer.name} again"
            if (timer.timer_mode != TIMER_MODE_SPAWN and
                timer.phase == PHASE_AVAILABLE) else
            f"Start {timer.name} from READY"
            if timer.phase == PHASE_IDLE else
            f"Resume {timer.name} from its preserved remaining time")
        self.killed_button.setVisible(
            timer.timer_mode == TIMER_MODE_SPAWN)
        self.spawned_button.setVisible(
            timer.timer_mode == TIMER_MODE_SPAWN)
        control_count = 7 if timer.timer_mode == TIMER_MODE_SPAWN else 5
        self.controls.setFixedSize(control_count * 26 + 2, 28)
        compact = bool(getattr(
            self.owner, "is_compact",
            config.data['timers']['compact']))
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

    MAX_SECONDARY_WINDOWS = 16

    def __init__(self, controller=None, instance_id=None):
        self._controller = controller or self
        self._is_primary = controller is None
        self.instance_id = "primary" if self._is_primary else str(instance_id)
        if self._is_primary:
            self.name = "timers"
            self._views = [self]
            self._secondary_views = {}
        else:
            self.name = f"timer_view_{self.instance_id}"
            self._ensure_secondary_settings()
        super().__init__()
        # This panel is commonly downscaled over the game.  Its local style
        # deliberately replaces bevel stacks with antialiased, border-light
        # geometry without changing any other Vantage window.
        self.setStyleSheet(SPAWN_TIMER_WINDOW_STYLE)
        window_number = (
            1 if self._is_primary else
            len(self._controller._secondary_views) + 2)
        self.setWindowTitle(
            "Smart Timers" if self._is_primary else
            f"Smart Timers · Window {window_number}")
        self._title.setText(
            "Timers" if self._is_primary else f"Timers {window_number}")
        timer_scroll = self._scale_view.verticalScrollBar()
        timer_scroll.setAccessibleName("Scroll Smart Timer rows")
        timer_scroll.setToolTip(
            "Scroll saved timer rows when the complete zone list is taller "
            "than the available screen")
        # QGraphicsView recalculates its scrollbar range after proxy/layout
        # updates.  A single queued ensureVisible() can therefore run before
        # the new range exists, or be undone by a later range reset.  Keep one
        # bounded reveal cycle for the currently focused timer action so the
        # final settled viewport, rather than the first layout pass, wins.
        self._active_timer_focus_control = None
        self._pending_timer_focus_control = None
        self._manual_timer_scroll_value = None
        self._setting_timer_scroll_value = False
        self._timer_focus_reveal_passes = 0
        self._timer_focus_reveal_timer = QTimer(self)
        self._timer_focus_reveal_timer.setSingleShot(True)
        self._timer_focus_reveal_timer.timeout.connect(
            self._reveal_pending_timer_control)
        timer_scroll.rangeChanged.connect(self._timer_scroll_range_changed)
        timer_scroll.valueChanged.connect(self._timer_scroll_value_changed)
        timer_scroll.actionTriggered.connect(
            self._timer_scroll_action_triggered)
        self._current_zone = (
            config.data['maps'].get('last_zone', '') if self._is_primary else
            self._controller._current_zone)
        self._selected_zone = str(
            self._view_settings().get('view_zone') or
            self._current_zone or '').strip()
        self._missing_zone_notified = None
        self._required_timer_height = 360
        self._states = {} if self._is_primary else self._controller._states
        self._rows = {}
        self._safety = (
            SafetyAlertState(
                config.data['timers'].get('death_loop_deaths', 4),
                config.data['timers'].get('death_loop_seconds', 120))
            if self._is_primary else None)

        add = QPushButton()
        add.setIcon(game_icon("add"))
        add.setObjectName("PrimaryAction")
        add.setAccessibleName("Add timer")
        add.setToolTip(
            "Add a named Smart Timer with editable respawn, kill estimate, color, sound, and volume")
        add.clicked.connect(self.add_timer)
        self.menu_area.addWidget(add)

        self.new_window_button = QPushButton()
        self.new_window_button.setIcon(game_icon("ph-stack"))
        self.new_window_button.setProperty('HeaderAlwaysVisible', True)
        self.new_window_button.setAccessibleName("Open another timer window")
        self.new_window_button.setAccessibleDescription(
            "Opens another independent view of the same saved timers. Each "
            "window keeps its own size, position, zone filter, and compact mode.")
        self.new_window_button.setToolTip(
            "Open another Smart Timer window (Ctrl+Shift+N)\n"
            "Use separate views for spawns, cooldowns, events, or any other "
            "timers. All views share the same timer state.")
        self.new_window_button.clicked.connect(
            self._controller.create_secondary_window)
        self.menu_area.addWidget(self.new_window_button)
        self._new_window_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+N"), self)
        self._new_window_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut)
        self._new_window_shortcut.activated.connect(
            self._controller.create_secondary_window)

        self.compact = QPushButton()
        self.compact.setIcon(game_icon("compact"))
        self.compact.setCheckable(True)
        self.compact.setChecked(bool(self._view_settings()['compact']))
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
        self.zone_filter.setAccessibleDescription(
            "Choose one exact origin zone, or All saved timers. Unassigned "
            "and other-zone timers only appear in a named view when explicitly "
            "watched for this window.")
        self.zone_filter.setToolTip(
            'Show only timers assigned to one exact zone, or choose All saved '
            'timers. Use Watch timers to add explicit cross-zone rows.')
        self.zone_filter.setMinimumContentsLength(8)
        self.zone_filter.currentIndexChanged.connect(
            self._zone_filter_changed)
        self.menu_area.addWidget(self.zone_filter)

        self.watch_button = QPushButton()
        self.watch_button.setIcon(game_icon("follow"))
        self.watch_button.setAccessibleName(
            "Watch timers from other zones in this window")
        self.watch_button.setAccessibleDescription(
            "Opens a searchable checklist of every saved timer and its origin "
            "zone. Checked external timers appear only in this timer window.")
        self.watch_button.setToolTip(
            "Watch timers from other zones in this window\n"
            "Search all saved timers, check external rows, and keep their "
            "original zones and shared timer state unchanged.")
        self.watch_button.clicked.connect(self.edit_cross_zone_watches)
        self.menu_area.addWidget(self.watch_button)

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
            "24 hours. Ordinary one-name codes remain compatible with older "
            "Vantage releases; multi-name death lists require current Vantage.")
        self.share_button.setToolTip(
            "Copy this zone's visible timers as one or more compact codes "
            "(Ctrl+Shift+S).\n"
            "Send every code by /tell, /say, Discord, or another message. The "
            "receiver only needs Vantage and /log on.\n"
            "Their Vantage detects the codes in the log—no import dialog—then "
            "uses the creation time to adjust elapsed time and automatically "
            "adds or refreshes the timers in the correct zone. Codes expire "
            "after 24 hours. Multi-name death lists require current Vantage; "
            "ordinary one-name codes remain compatible with older releases.")
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
        self.mobile_button.setVisible(self._is_primary)

        self.remove_window_button = QPushButton()
        self.remove_window_button.setIcon(game_icon("delete"))
        self.remove_window_button.setObjectName("DangerAction")
        self.remove_window_button.setAccessibleName(
            "Close and remove this extra timer window")
        self.remove_window_button.setToolTip(
            "Remove only this extra view. Saved timers remain available in "
            "the other Smart Timer windows.")
        self.remove_window_button.clicked.connect(
            lambda: self._controller.remove_secondary_window(
                self.instance_id))
        self.remove_window_button.setVisible(not self._is_primary)
        self.menu_area.addWidget(self.remove_window_button)

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
        # Keep one logical timer canvas. The surrounding graphics view only
        # scrolls when the complete zone list is physically taller than the
        # screen; ordinary lists remain fixed and fully visible.
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

        if self._is_primary:
            self._load()
        else:
            for timer in self._states.values():
                self._add_row(timer)
        self._refresh_zone_filter(self._selected_zone)
        if self._is_primary:
            QApplication.instance().aboutToQuit.connect(
                self.record_session_closed)
            QApplication.instance()._signals["maps"].new_zone.connect(
                self._zone_changed)
        self._ticker = QTimer(self)
        # Second precision is enough for P99 spawns and avoids needless repaints.
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        if self._is_primary:
            self._ticker.start()
            self._restore_secondary_windows()
        else:
            self._controller._register_secondary_view(self)

    def _view_settings(self):
        return config.data['timers' if self._is_primary else self.name]

    def _ensure_secondary_settings(self):
        """Seed a normal ParserWindow settings section for one extra view."""
        if self._is_primary:
            return config.data['timers']
        settings = config.data.get(self.name)
        if isinstance(settings, dict):
            return settings
        primary = config.data.get('timers', {})
        existing_views = tuple(self._controller._secondary_views.values())
        anchor = (
            existing_views[-1]._view_settings() if existing_views else
            primary)
        geometry = list(anchor.get('geometry', [620, 0, 520, 360]))
        geometry[0] = int(geometry[0]) + 28
        geometry[1] = int(geometry[1]) + 28
        settings = {
            'geometry': geometry,
            'toggled': True,
            'opacity': int(primary.get('opacity', 92)),
            'clickthrough': False,
            'auto_hide_menu': bool(primary.get('auto_hide_menu', False)),
            'always_on_top': bool(primary.get('always_on_top', True)),
            'frameless': bool(primary.get('frameless', True)),
            'collapsed': False,
            'compact': bool(primary.get('compact', False)),
            'view_zone': str(primary.get('view_zone', '') or ''),
            'watch_timer_ids': [],
        }
        config.data[self.name] = settings
        return settings

    def _register_secondary_view(self, view):
        if not self._is_primary:
            return self._controller._register_secondary_view(view)
        self._secondary_views[view.instance_id] = view
        if view not in self._views:
            self._views.append(view)

    def _restore_secondary_windows(self):
        if not self._is_primary:
            return []
        restored = []
        for record in config.data['timers'].get('instances', []):
            instance_id = str(
                record.get('id') if isinstance(record, dict) else record)
            if not instance_id or instance_id in self._secondary_views:
                continue
            restored.append(SpawnTimers(self, instance_id))
        return restored

    def create_secondary_window(self):
        """Create a view only; the primary remains the sole log parser."""
        if not self._is_primary:
            return self._controller.create_secondary_window()
        if len(self._secondary_views) >= self.MAX_SECONDARY_WINDOWS:
            self.announce(
                f"SMART TIMERS · maximum {self.MAX_SECONDARY_WINDOWS} extra "
                "windows reached")
            return None
        instance_id = uuid.uuid4().hex[:12]
        while instance_id in self._secondary_views:
            instance_id = uuid.uuid4().hex[:12]
        config.data['timers'].setdefault('instances', []).append(
            {'id': instance_id})
        view = SpawnTimers(self, instance_id)
        view.finish_startup(show_on_launch=True)
        view.raise_()
        view.activateWindow()
        QTimer.singleShot(
            0, lambda: view.zone_filter.setFocus(
                Qt.FocusReason.OtherFocusReason))
        config.save()
        self.announce(
            f"SMART TIMERS · Window {len(self._views)} opened · shared "
            "timers, independent layout and filter")
        return view

    def remove_secondary_window(self, instance_id):
        """Remove one extra view without deleting or changing timer state."""
        if not self._is_primary:
            return self._controller.remove_secondary_window(instance_id)
        instance_id = str(instance_id or '')
        view = self._secondary_views.pop(instance_id, None)
        if view is None:
            return False
        view._geometry_save_timer.stop()
        view.hide()
        if view in self._views:
            self._views.remove(view)
        config.data['timers']['instances'] = [
            record for record in config.data['timers'].get('instances', [])
            if str(record.get('id') if isinstance(record, dict) else record)
            != instance_id]
        config.data.pop(view.name, None)
        view.deleteLater()
        if not self.isVisible():
            self._fit_to_available_screen()
            self.show()
            self._toggled = True
            config.data['timers']['toggled'] = True
        self.raise_()
        self.activateWindow()
        self._set_header_revealed(True)
        QTimer.singleShot(
            0, lambda: self.new_window_button.setFocus(
                Qt.FocusReason.OtherFocusReason))
        config.save()
        self.announce(
            "SMART TIMERS · extra window removed; saved timers kept")
        return True

    @property
    def secondary_windows(self):
        controller = self if self._is_primary else self._controller
        return tuple(controller._secondary_views.values())

    @property
    def is_compact(self):
        return bool(self._view_settings().get('compact', False))

    def _settings_section(self):
        return "Smart Timers"

    def finish_startup(self, show_on_launch=None):
        super().finish_startup(show_on_launch=show_on_launch)
        if self._is_primary:
            for view in self.secondary_windows:
                view.finish_startup(show_on_launch=bool(
                    view._view_settings().get('toggled', False)))

    def closeEvent(self, event):
        if not self._is_primary:
            # QApplication closes tool windows during update/restart even
            # when config.APP_EXIT has not been set, and Qt does not expose a
            # dependable distinction from a native framed-window close here.
            # Preserve the open state; the explicit header button is the clear
            # and durable way to remove an extra view.
            self._save_geometry()
            event.accept()
            return
        super().closeEvent(event)

    def mobile_snapshot(self):
        """Small immutable shape consumed by the isolated mobile server."""
        timers = []
        for timer in self._states.values():
            if not self._row_matches_zone(timer):
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
                "timer_mode": timer.timer_mode,
                "duration": format_seconds(timer.respawn_seconds),
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
            if (timer.timer_mode != TIMER_MODE_SPAWN and
                    timer.phase == PHASE_AVAILABLE):
                timer.start()
                verb = "started"
            elif timer.running:
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
            if (timer.source == 'Log command' and
                    'timer_mode' not in values):
                timer.timer_mode = TIMER_MODE_COUNTDOWN
                migrated = True
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

    def refresh_synced_content(self):
        """Replace the live rows after Device Sync applies a newer snapshot."""
        if not self._is_primary:
            return self._controller.refresh_synced_content()
        incoming = config.data.get('timers', {}).get('items', [])
        if not isinstance(incoming, list):
            incoming = []
        current = [timer.to_dict() for timer in self._states.values()]
        if incoming == current:
            self._reload_synced_view_preferences()
            return 0
        for timer_id in list(self._states):
            self._remove_timer(timer_id, clean_watches=False)
        restored = 0
        cleaned = []
        for values in incoming:
            try:
                timer = SpawnTimerState.from_dict(values)
            except (TypeError, ValueError):
                continue
            self._register_timer(timer)
            cleaned.append(timer.to_dict())
            restored += 1
        config.data['timers']['items'] = cleaned
        self._reload_synced_view_preferences()
        self.status.setText(
            f"DEVICE SYNC · {restored} Smart Timer"
            f"{'s' if restored != 1 else ''} loaded")
        return restored

    def _reload_synced_view_preferences(self):
        """Apply synced per-window filters without touching shared timers."""
        controller = self if self._is_primary else self._controller
        for view in tuple(controller._views):
            settings = view._view_settings()
            view._selected_zone = str(
                settings.get('view_zone') or '').strip()
            view.compact.setChecked(bool(settings.get('compact', False)))
            view._refresh_zone_filter(view._selected_zone)

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
        self.zone_filter.addItem('All saved timers', '')
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
        self._view_settings()['view_zone'] = self._selected_zone
        self._apply_zone_filter()

    def _clean_watched_timer_ids(self, save=False):
        settings = self._view_settings()
        raw = settings.get('watch_timer_ids', [])
        if not isinstance(raw, list):
            raw = []
        valid_ids = set(self._states)
        cleaned = []
        seen = set()
        for raw_timer_id in raw:
            timer_id = str(raw_timer_id or '').strip()[:96]
            if (not timer_id or timer_id not in valid_ids or
                    timer_id in seen):
                continue
            seen.add(timer_id)
            cleaned.append(timer_id)
            if len(cleaned) >= MAX_CROSS_ZONE_WATCHES:
                break
        changed = settings.get('watch_timer_ids') != cleaned
        settings['watch_timer_ids'] = cleaned
        if changed and save:
            config.save()
        return tuple(cleaned)

    def _is_cross_zone_watch(self, timer):
        return bool(
            timer and self._selected_zone and
            not zone_timer_visible(timer.zone, self._selected_zone) and
            timer.timer_id in self._clean_watched_timer_ids())

    def edit_cross_zone_watches(self):
        """Edit this view's explicit external timer selection."""
        current = self._clean_watched_timer_ids(save=True)
        dialog = TimerWatchDialog(
            self._states.values(), self._selected_zone, current, self)
        accepted = dialog.exec()
        if accepted:
            self._view_settings()['watch_timer_ids'] = \
                dialog.selected_timer_ids()
            config.save()
            self._apply_zone_filter()
            watched = sum(
                self._is_cross_zone_watch(timer)
                for timer in self._states.values())
            self.announce(
                f"WATCH VIEW · {watched} external timer"
                f"{'s' if watched != 1 else ''} shown with "
                f"{self._selected_zone or 'All saved timers'}")
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(
            0, lambda: self.watch_button.setFocus(
                Qt.FocusReason.OtherFocusReason))
        return bool(accepted)

    def _zone_filter_changed(self, _index):
        self._selected_zone = str(
            self.zone_filter.currentData() or '').strip()
        self._view_settings()['view_zone'] = self._selected_zone
        config.save()
        self._apply_zone_filter()
        visible = sum(
            self._row_matches_zone(timer)
            for timer in self._states.values())
        self.status.setText(
            f"ZONE VIEW · {self._selected_zone or 'All saved timers'} · "
            f"{visible} saved timer{'s' if visible != 1 else ''}")

    def _apply_zone_filter(self):
        self._clean_watched_timer_ids(save=True)
        for timer_id, row in self._rows.items():
            timer = self._states.get(timer_id)
            row.setVisible(self._row_matches_zone(timer))
            if timer is not None:
                row.refresh()
        self._schedule_timer_canvas()

    def _row_matches_zone(self, timer):
        return bool(timer and (
            zone_timer_visible(timer.zone, self._selected_zone) or
            timer.timer_id in self._clean_watched_timer_ids()))

    def _add_row(self, timer):
        if timer.timer_id in self._rows:
            return self._rows[timer.timer_id]
        row = TimerRow(timer, self)
        self._rows[timer.timer_id] = row
        self._layout.insertWidget(self._layout.count() - 1, row)
        for button in row.findChildren(QPushButton):
            button.installEventFilter(self)
        row.setVisible(self._row_matches_zone(timer))
        self._schedule_timer_canvas()
        return row

    def _register_timer(self, timer):
        controller = self if self._is_primary else self._controller
        controller._states[timer.timer_id] = timer
        for view in tuple(controller._views):
            view._add_row(timer)
        return timer

    def _refresh_all_view_filters(self):
        controller = self if self._is_primary else self._controller
        for view in tuple(controller._views):
            view._refresh_zone_filter(view._selected_zone)

    def _refresh_all_rows(self, layout_changed=False):
        """Repaint shared timer state without needlessly rebuilding layout."""
        controller = self if self._is_primary else self._controller
        for view in tuple(controller._views):
            for row in view._rows.values():
                row.refresh()
            if layout_changed:
                view._schedule_timer_canvas()

    def _schedule_timer_canvas(self):
        if hasattr(self, "_canvas_update_timer"):
            self._canvas_update_timer.start(0)

    def _sync_timer_canvas(self):
        """Keep every zone row visible, using scroll only past screen height."""
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
        self._required_timer_height = max(
            1, header_height + list_height + status_height)
        logical_height = max(360, self._required_timer_height)
        self._set_design_size(QSize(520, logical_height))
        # The authored design may retain comfortable empty space, but the
        # resize floor follows the actual rows in this zone. Recompute it even
        # when the design size itself did not change.
        self._set_scaled_minimum_size()
        self._update_uniform_scale()
        self._schedule_viewport_rows()

    def _minimum_logical_surface_height(self):
        """Keep every row in the selected zone inside the live viewport."""
        # A rolled panel contains only its header. Re-expanding the protected
        # timer canvas here would vertically center the header inside a hidden
        # 360 px surface and make the 24 px strip appear broken.
        return 1 if self._collapsed else max(
            1, int(getattr(
                self, '_required_timer_height', self._design_size.height())))

    def _set_scaled_minimum_size(self):
        """Make the vertical resize floor track all visible timer rows."""
        if self._collapsed:
            return
        minimum_scale = self._effective_minimum_scale()
        minimum_width = max(
            round(self._design_size.width() * minimum_scale),
            int(self._minimum_readable_width))
        # ParserWindow scales this canvas from its width. At the current width,
        # this is the exact physical height required by the header, status, and
        # every row in the selected zone.
        width_scale = max(
            minimum_scale,
            max(self.width(), minimum_width) /
            max(1, self._design_size.width()))
        required_height = math.ceil(
            self._minimum_logical_surface_height() * width_scale)
        screen = (
            QApplication.screenAt(self.frameGeometry().center()) or
            QApplication.primaryScreen())
        if screen is not None:
            native_chrome = max(
                0, self.frameGeometry().height() - self.height())
            screen_limit = max(
                96, screen.availableGeometry().height() - native_chrome)
        else:
            screen_limit = required_height
        minimum_height = min(required_height, screen_limit)
        overflow = required_height > screen_limit
        self._scale_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if overflow else
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(minimum_width, minimum_height)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.FocusIn
                and isinstance(watched, QPushButton)
                and self._timer_host.isAncestorOf(watched)):
            new_timer_focus = watched is not self._active_timer_focus_control
            self._active_timer_focus_control = watched
            if (new_timer_focus or
                    self._pending_timer_focus_control is watched):
                if new_timer_focus:
                    self._manual_timer_scroll_value = None
                # Reveal synchronously too: a full-suite/offscreen event loop
                # can stop a qWait immediately after a late scale pass, before
                # even a zero-delay timer receives its turn.
                self._ensure_timer_control_visible(watched)
                self._schedule_timer_control_reveal(watched)
        elif (event.type() == QEvent.Type.FocusOut and
              watched is self._active_timer_focus_control):
            # Scaling a QGraphicsProxyWidget can emit a transient FocusOut /
            # FocusIn pair for the same logical button. Check after that event
            # turn so only a real departure clears the navigation identity.
            QTimer.singleShot(
                0, lambda control=watched:
                self._clear_inactive_timer_focus(control))
        return super().eventFilter(watched, event)

    def _clear_inactive_timer_focus(self, control):
        if self._active_timer_focus_control is not control:
            return
        try:
            still_focused = (
                control.hasFocus() or self._surface.focusWidget() is control)
        except RuntimeError:
            still_focused = False
        if not still_focused:
            self._active_timer_focus_control = None
            self._manual_timer_scroll_value = None

    def _schedule_timer_control_reveal(self, control):
        """Keep a focused row revealed until proxy scrollbar layout settles."""
        if control is None:
            return
        self._pending_timer_focus_control = control
        self._timer_focus_reveal_passes = max(
            self._timer_focus_reveal_passes, 7)
        # The first pass runs after the FocusIn/layout event completes.  Later
        # passes cover deferred QGraphicsProxyWidget geometry/range updates.
        if not self._timer_focus_reveal_timer.isActive():
            self._timer_focus_reveal_timer.start(0)

    def _timer_scroll_range_changed(self, _minimum, _maximum):
        if self._pending_timer_focus_control is not None:
            self._timer_focus_reveal_passes = max(
                self._timer_focus_reveal_passes, 2)
            if not self._timer_focus_reveal_timer.isActive():
                self._timer_focus_reveal_timer.start(0)

    def _timer_scroll_value_changed(self, value):
        if (self._pending_timer_focus_control is not None and
                not self._timer_focus_reveal_timer.isActive()):
            self._timer_focus_reveal_timer.start(0)
        manual = self._manual_timer_scroll_value
        if (manual is not None and not self._setting_timer_scroll_value and
                int(value) != int(manual)):
            # QGraphicsProxyWidget may auto-scroll its focused child well after
            # the user's scrollbar action. Restore that explicit user choice
            # synchronously so a late proxy event cannot win the event turn.
            scroll = self._scale_view.verticalScrollBar()
            self._setting_timer_scroll_value = True
            try:
                scroll.setValue(max(
                    scroll.minimum(), min(scroll.maximum(), int(manual))))
            finally:
                self._setting_timer_scroll_value = False

    def _timer_scroll_action_triggered(self, _action):
        """Let an explicit scrollbar action override focus auto-reveal."""
        scroll = self._scale_view.verticalScrollBar()
        self._timer_focus_reveal_timer.stop()
        self._pending_timer_focus_control = None
        self._timer_focus_reveal_passes = 0
        self._manual_timer_scroll_value = int(scroll.sliderPosition())

    def _reveal_pending_timer_control(self):
        control = self._pending_timer_focus_control
        if control is None:
            return
        try:
            valid = (
                control.isVisibleTo(self._surface) and
                self._timer_host.isAncestorOf(control))
        except RuntimeError:
            valid = False
        if not valid:
            self._pending_timer_focus_control = None
            self._timer_focus_reveal_passes = 0
            return
        self._ensure_timer_control_visible(control)
        self._timer_focus_reveal_passes -= 1
        if self._timer_focus_reveal_passes > 0:
            # A short bounded settling window is long enough for the deferred
            # graphics-view range pass without creating a persistent snap-back
            # when the user later scrolls manually.
            self._timer_focus_reveal_timer.start(12)
        else:
            self._pending_timer_focus_control = None

    def _ensure_timer_control_visible(self, control):
        """Reveal a keyboard-focused row when the screen-height cap scrolls."""
        if (not control or not control.isVisibleTo(self._surface)
                or self._scale_view.verticalScrollBarPolicy() !=
                Qt.ScrollBarPolicy.ScrollBarAsNeeded):
            return False
        logical_rect = QRectF(
            control.mapTo(self._surface, control.rect().topLeft()),
            control.size())
        scene_rect = self._scale_proxy.mapRectToScene(logical_rect)
        self._scale_view.ensureVisible(scene_rect, 8, 8)
        # ensureVisible() normally updates the bar synchronously.  On the
        # offscreen backend and under a busy event loop its range can settle a
        # turn later, so verify the mapped proxy rect and correct any residual
        # vertical delta using the now-current scrollbar range.
        viewport = self._scale_view.viewport().rect().adjusted(8, 8, -8, -8)
        mapped = self._scale_view.mapFromScene(scene_rect).boundingRect()
        scroll = self._scale_view.verticalScrollBar()
        target = scroll.value()
        if mapped.top() < viewport.top():
            target += mapped.top() - viewport.top()
        elif mapped.bottom() > viewport.bottom():
            target += mapped.bottom() - viewport.bottom()
        if target != scroll.value():
            scroll.setValue(max(
                scroll.minimum(), min(scroll.maximum(), int(round(target)))))
            mapped = self._scale_view.mapFromScene(scene_rect).boundingRect()
        return viewport.contains(mapped)

    def _update_uniform_scale(self):
        scroll = self._scale_view.verticalScrollBar()
        preserved_scroll = scroll.value()
        pending_focus = getattr(
            self, '_pending_timer_focus_control', None)
        self._set_scaled_minimum_size()
        super()._update_uniform_scale()
        self._schedule_viewport_rows()
        if pending_focus is not None:
            # ParserWindow pins the vertical range to its minimum while it
            # applies the new transform. Correct that reset before returning;
            # the bounded queued cycle then covers any later proxy relayout.
            self._ensure_timer_control_visible(pending_focus)
            self._schedule_timer_control_reveal(pending_focus)
        else:
            # A periodic row refresh is not a new keyboard navigation event.
            # Preserve the user's chosen viewport instead of snapping back to
            # either the focused row or the top once the FocusIn settle cycle
            # has completed.
            scroll.setValue(max(
                scroll.minimum(), min(scroll.maximum(), preserved_scroll)))

    def _schedule_viewport_rows(self):
        timer = getattr(self, '_viewport_rows_timer', None)
        if timer is not None:
            timer.start(0)

    def _apply_viewport_capacity(self):
        """Apply only the zone filter; resizing never hides matching rows."""
        for timer_id, row in self._rows.items():
            matches = self._row_matches_zone(self._states.get(timer_id))
            row.setVisible(matches)

    def add_timer(self):
        dialog = TimerEditDialog(parent=self)
        dialog.zone.setText(string.capwords(
            self._selected_zone or self._current_zone))
        if dialog.exec():
            timer = dialog.apply()
            self._register_timer(timer)
            self._refresh_all_view_filters()
            self.state_changed(layout_changed=True)

    def edit_timer(self, timer_id):
        timer = self._states[timer_id]
        dialog = TimerEditDialog(timer, self)
        if dialog.exec():
            dialog.apply(timer)
            self._refresh_all_view_filters()
            self.state_changed(layout_changed=True)

    def delete_timer(self, timer_id):
        timer = self._states[timer_id]
        answer = QMessageBox.question(
            self,
            "Delete Timer",
            f"Delete {timer.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller._remove_timer(timer_id)
            self.state_changed()
            self._refresh_all_view_filters()

    def state_changed(self, layout_changed=False):
        if not self._is_primary:
            return self._controller.state_changed(layout_changed)
        self._save()
        self._refresh_all_rows(layout_changed)

    def _save(self):
        self.checkpoint_runtime_state()

    def checkpoint_runtime_state(self):
        """Synchronously preserve Smart Timers before an app handoff."""
        if not self._is_primary:
            return self._controller.checkpoint_runtime_state()
        config.data['timers']['items'] = [timer.to_dict() for timer in self._states.values()]
        config.save()
        return len(config.data['timers']['items'])

    def checkpoint_view_geometries(self):
        controller = self if self._is_primary else self._controller
        for view in tuple(controller._views):
            view._save_geometry()

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
        zone = self._selected_zone or "All saved timers"
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
            self._register_timer(incoming)
            return "added"
        # Timing is handed off, while the receiver keeps local alert choices.
        for field in (
                "name", "respawn_seconds", "kill_seconds", "warning_seconds",
                "smart", "zone", "mob_pattern", "death_mobs", "source",
                "automatic",
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
        self._view_settings()['compact'] = self.compact.isChecked()
        config.save()
        for row in self._rows.values():
            row.refresh()
        self._schedule_timer_canvas()

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
                message = (
                    f"{timer.name}: due now" if schedule_due else
                    f"{timer.name}: due in {remaining} s"
                    if schedule_warning else event.message)
                if event.kind in ("spawn", "warning", "complete", "ready"):
                    route = (
                        "raid_encounter" if
                        timer.source == RING_WAR_SCHEDULE_SOURCE else
                        "smart_timer")
                    QApplication.instance().notify_event(
                        route, message, title="Vantage",
                        overlay_id="timers",
                        sound_override=timer.sound_path,
                        volume=timer.volume,
                        repeat=2 if event.kind in (
                            "spawn", "complete", "ready") else 1,
                        channel="timers")
                else:
                    self.announce(message)
                if schedule_due:
                    completed_schedule_ids.append(timer.timer_id)
        for timer_id in completed_schedule_ids:
            self._remove_timer(timer_id)
        refresh_all = getattr(self, '_refresh_all_rows', None)
        if callable(refresh_all):
            refresh_all()
        else:
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
        QApplication.instance().notify_event(
            "raid_encounter", message, title="Vantage",
            overlay_id="timers", volume=config.data['timers']['volume'],
            repeat=2, channel="timers")

    def _safety_alert(self, alert):
        if alert.kind != 'death_loop' or not config.data['timers'].get(
                'death_loop_enabled', True):
            return
        self.status.setText(alert.message)
        QApplication.instance().notify_event(
            "death_loop", alert.message, title="Vantage · Death-loop warning",
            overlay_id="alerts", text_color="#E08372",
            volume=config.data['timers']['volume'], repeat=2,
            channel="timers")

    def _remove_timer(self, timer_id, clean_watches=True):
        if not self._is_primary:
            return self._controller._remove_timer(
                timer_id, clean_watches=clean_watches)
        for view in tuple(self._views):
            row = view._rows.pop(timer_id, None)
            if row is not None:
                row.setParent(None)
                row.deleteLater()
            view._schedule_timer_canvas()
        removed = self._states.pop(timer_id, None)
        if clean_watches:
            for view in tuple(self._views):
                view._clean_watched_timer_ids()
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
                sound_path=None,
                volume=config.data['timers']['volume'],
                source=RING_WAR_SCHEDULE_SOURCE,
                automatic=True)
            timer.start(event_time)
            self._register_timer(timer)
        self._encounter_alert(
            f"Ring War schedule started · {len(milestones)} milestones",
            "Ring War")
        self.state_changed()

    def _zone_changed(self, zone):
        self._current_zone = str(zone or '').strip()
        self._missing_zone_notified = None
        self._refresh_zone_filter(self._current_zone)
        for view in self.secondary_windows:
            view._current_zone = self._current_zone
            view._refresh_zone_filter(view._selected_zone)
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
            mob_pattern="",
            death_mobs=[mob],
            sound_path=None,
            volume=config.data['timers']['volume'],
            source=NAMED_CATALOG_SOURCE,
            automatic=True,
        )
        # A death line is the anchor: the newly created timer is running from
        # this exact log timestamp, never left idle in READY.
        timer.mark_killed(event_time)
        self._register_timer(timer)
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
                sound_path=None,
                volume=config.data['timers']['volume'],
                source='Log command',
                timer_mode=TIMER_MODE_COUNTDOWN)
            self._register_timer(timer)
        else:
            timer.respawn_seconds = duration
            timer.warning_seconds = min(30, max(1, duration // 10))
        timer.start(event_time)
        self.announce(
            f'{label}: log command timer started · {format_seconds(duration)}')
        self.state_changed()

    def parse(self, timestamp, text):
        if not self._is_primary:
            return
        if text.startswith("You have entered "):
            self._zone_changed(text[17:].rstrip('.'))
        event_time = (
            timestamp.timestamp()
            if isinstance(timestamp, datetime.datetime) else time.time())
        if any(prefix in text for prefix in TIMER_SHARE_PREFIXES):
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
