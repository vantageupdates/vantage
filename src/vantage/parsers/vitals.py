"""Read-only visual health/mana monitor for the EverQuest window."""

from __future__ import annotations

import time
import uuid

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor, QKeyEvent, QPainter,
    QPen)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.audio import (
    add_custom_sound_to_combo, play_alert, set_sound_combo_value,
    speak_text, speech_voice_names)
from vantage.helpers.game_capture import GameWindowCapture
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import store_portable_file
from vantage.helpers.responsive import ResponsiveActionBar, polish_form, scrollable
from vantage.helpers.vitals import (
    MIN_CONFIDENCE, VitalReading, VitalStopTracker, analyze_vital_bar,
    default_vital_bar, default_vital_stop, denormalize_rect,
    learn_fill_color, normalize_rect, preset_percentages,
    sanitize_vital_bar, sanitize_vital_bars, sanitize_vital_stop)


TYPE_LABELS = {
    "my_hp": "My HP",
    "my_mana": "My Mana",
    "target_hp": "Target / Mob HP",
    "group_hp": "Group HP",
    "custom": "Custom",
}
DIRECTION_LABELS = {
    "below": "Falls below",
    "above": "Rises above",
    "either": "Crosses either way",
    "full": "Becomes full",
}


def _announce(widget, message):
    widget.setAccessibleDescription(str(message))
    try:
        event = QAccessibleAnnouncementEvent(widget, str(message))
        event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
        QAccessible.updateAccessibility(event)
    except (AttributeError, RuntimeError, TypeError):
        pass


class CalibrationOverlay(QWidget):
    """The only on-game calibration surface; never sends game input."""

    rect_changed = Signal(QRect)
    cancel_requested = Signal()

    def __init__(self, bounds, initial, parent=None):
        super().__init__(parent)
        self._bounds = QRect(bounds)
        self._press_global = QPoint()
        self._press_geometry = QRect()
        self._resize_edges = set()
        self._owner_closing = False
        self._pending_announcement = ""
        self._announce_timer = QTimer(self)
        self._announce_timer.setSingleShot(True)
        self._announce_timer.setInterval(180)
        self._announce_timer.timeout.connect(self._announce_geometry)
        self.setObjectName("VitalsCalibrationOverlay")
        self.setWindowTitle("Vitals calibration rectangle")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Vitals calibration rectangle")
        self.setAccessibleDescription(
            "Drag to move. Drag an edge to resize. Arrow keys move one pixel; "
            "Shift plus arrow moves ten; Alt plus arrow resizes.")
        self.setToolTip(self.accessibleDescription())
        self.setMinimumSize(8, 6)
        self.setGeometry(self._bounded(QRect(initial)))

    def _bounded(self, rect):
        width = max(8, min(rect.width(), self._bounds.width()))
        height = max(6, min(rect.height(), self._bounds.height()))
        x = max(self._bounds.left(), min(
            rect.x(), self._bounds.right() - width + 1))
        y = max(self._bounds.top(), min(
            rect.y(), self._bounds.bottom() - height + 1))
        return QRect(x, y, width, height)

    def set_calibration_geometry(self, rect):
        rect = self._bounded(QRect(rect))
        if rect != self.geometry():
            self.setGeometry(rect)
            self.rect_changed.emit(QRect(rect))

    def _schedule_geometry_announcement(self):
        rect = self.geometry()
        self._pending_announcement = (
            f"Calibration area {rect.x()}, {rect.y()}, "
            f"{rect.width()} by {rect.height()} pixels. "
            "Arrow keys move; Alt plus arrow resizes.")
        self._announce_timer.start()

    def _announce_geometry(self):
        if self._pending_announcement:
            _announce(self, self._pending_announcement)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(212, 173, 84, 34))
        painter.setPen(QPen(QColor("#F0C765"), 3))
        painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = event.position().toPoint()
        margin = min(9, max(4, min(self.width(), self.height()) // 4))
        self._resize_edges = set()
        if point.x() <= margin:
            self._resize_edges.add("left")
        if point.x() >= self.width() - margin:
            self._resize_edges.add("right")
        if point.y() <= margin:
            self._resize_edges.add("top")
        if point.y() >= self.height() - margin:
            self._resize_edges.add("bottom")
        self._press_global = event.globalPosition().toPoint()
        self._press_geometry = self.geometry()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press_geometry.isNull():
            return super().mouseMoveEvent(event)
        delta = event.globalPosition().toPoint() - self._press_global
        rect = QRect(self._press_geometry)
        if not self._resize_edges:
            rect.translate(delta)
        else:
            if "left" in self._resize_edges:
                rect.setLeft(rect.left() + delta.x())
            if "right" in self._resize_edges:
                rect.setRight(rect.right() + delta.x())
            if "top" in self._resize_edges:
                rect.setTop(rect.top() + delta.y())
            if "bottom" in self._resize_edges:
                rect.setBottom(rect.bottom() + delta.y())
        self.set_calibration_geometry(rect.normalized())
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self._press_geometry = QRect()
        self._resize_edges = set()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._owner_closing = True
            self.cancel_requested.emit()
            event.accept()
            return
        moves = {
            Qt.Key.Key_Left: QPoint(-1, 0),
            Qt.Key.Key_Right: QPoint(1, 0),
            Qt.Key.Key_Up: QPoint(0, -1),
            Qt.Key.Key_Down: QPoint(0, 1),
        }
        delta = moves.get(event.key())
        if delta is None:
            return super().keyPressEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta *= 10
        rect = self.geometry()
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            rect.setSize(QSize(
                max(8, rect.width() + delta.x()),
                max(6, rect.height() + delta.y())))
        else:
            rect.translate(delta)
        self.set_calibration_geometry(rect)
        self._schedule_geometry_announcement()
        event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            return
        super().keyReleaseEvent(event)

    def closeEvent(self, event):
        self._announce_timer.stop()
        if not self._owner_closing:
            self._owner_closing = True
            self.cancel_requested.emit()
        super().closeEvent(event)

    def dismiss(self):
        self._owner_closing = True
        self.close()


class CalibrationControls(QDialog):
    """Keyboard/numeric companion to the visual calibration rectangle."""

    geometry_changed = Signal(QRect)
    use_requested = Signal(QRect)

    def __init__(self, bounds, initial, parent=None):
        super().__init__(parent)
        self._bounds = QRect(bounds)
        self._syncing = False
        self._announce_timer = QTimer(self)
        self._announce_timer.setSingleShot(True)
        self._announce_timer.setInterval(220)
        self._announce_timer.timeout.connect(
            lambda: _announce(self.status, self.status.text()))
        self.setObjectName("VitalsCalibrationControls")
        self.setWindowTitle("Calibrate vital bar")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(360)
        intro = QLabel(
            "Place the gold rectangle over only the filled bar. Drag it, use "
            "arrow keys, or enter exact coordinates below.")
        intro.setWordWrap(True)
        intro.setAccessibleDescription(intro.text())

        form = polish_form(QFormLayout())
        self.x = self._spin("Calibration X coordinate")
        self.y = self._spin("Calibration Y coordinate")
        self.width_value = self._spin("Calibration width", minimum=8)
        self.height_value = self._spin("Calibration height", minimum=6)
        self.x.setRange(0, max(0, bounds.width() - 8))
        self.y.setRange(0, max(0, bounds.height() - 6))
        self.width_value.setRange(8, bounds.width())
        self.height_value.setRange(6, bounds.height())
        form.addRow("X", self.x)
        form.addRow("Y", self.y)
        form.addRow("Width", self.width_value)
        form.addRow("Height", self.height_value)
        for control in (self.x, self.y, self.width_value, self.height_value):
            control.valueChanged.connect(self._values_changed)

        nudge = ResponsiveActionBar(70)
        for text, dx, dy in (("← Left", -1, 0), ("Right →", 1, 0),
                             ("↑ Up", 0, -1), ("Down ↓", 0, 1)):
            button = QPushButton(text)
            button.setAccessibleName(f"Nudge calibration {text.replace('← ', '').replace(' →', '').replace('↑ ', '').replace(' ↓', '')}")
            button.setToolTip("Move the calibration rectangle one pixel")
            button.clicked.connect(
                lambda _checked=False, x=dx, y=dy: self.nudge(x, y))
            nudge.addWidget(button)

        self.status = QLabel("Calibration ready")
        self.status.setObjectName("InlineStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Calibration status")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "Use this area")
        buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip(
            "Save the rectangle and learn its fill color")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Cancel calibration without changing the saved bar")
        buttons.accepted.connect(
            lambda: self.use_requested.emit(self.absolute_rect()))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        host = QWidget()
        host.setLayout(form)
        layout.addWidget(host)
        layout.addWidget(nudge)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        self.set_absolute_rect(initial)

    @staticmethod
    def _spin(name, minimum=0):
        control = QSpinBox()
        control.setMinimum(minimum)
        control.setAccessibleName(name)
        control.setToolTip(name + " in EverQuest window pixels")
        return control

    def absolute_rect(self):
        return QRect(
            self._bounds.x() + self.x.value(),
            self._bounds.y() + self.y.value(),
            self.width_value.value(), self.height_value.value())

    def set_absolute_rect(self, rect):
        rect = QRect(rect).intersected(self._bounds)
        if rect.width() < 8 or rect.height() < 6:
            return
        self._syncing = True
        self.x.setValue(rect.x() - self._bounds.x())
        self.y.setValue(rect.y() - self._bounds.y())
        self.width_value.setValue(rect.width())
        self.height_value.setValue(rect.height())
        self._syncing = False
        message = (
            f"Area {self.x.value()}, {self.y.value()}, "
            f"{rect.width()} by {rect.height()} pixels")
        self.status.setText(message)
        self.status.setAccessibleDescription(message)

    def _values_changed(self):
        if not self._syncing:
            self.geometry_changed.emit(self.absolute_rect())
            self.set_absolute_rect(self.absolute_rect())
            self._announce_timer.start()

    def nudge(self, dx, dy):
        rect = self.absolute_rect()
        rect.translate(int(dx), int(dy))
        rect = rect.intersected(self._bounds)
        self.set_absolute_rect(rect)
        self.geometry_changed.emit(self.absolute_rect())
        self._announce_timer.stop()
        _announce(self.status, self.status.text())


class VitalStopDialog(QDialog):
    """Edit one threshold and its explicit sound/TTS/off delivery."""

    def __init__(self, stop=None, parent=None, test_callback=None):
        super().__init__(parent)
        self._stop = sanitize_vital_stop(stop or {}, 0)
        self._test_callback = test_callback
        self.setWindowTitle("Vital alert stop")
        self.setMinimumSize(430, 360)
        form = polish_form(QFormLayout())

        self.percent = QSpinBox()
        self.percent.setRange(0, 100)
        self.percent.setSuffix(" %")
        self.percent.setValue(self._stop["percent"])
        self.percent.setAccessibleName("Alert threshold percent")
        form.addRow("Threshold", self.percent)
        self.direction = QComboBox()
        for value, label in DIRECTION_LABELS.items():
            self.direction.addItem(label, value)
        self.direction.setCurrentIndex(max(0, self.direction.findData(
            self._stop["direction"])))
        self.direction.setAccessibleName("Threshold crossing direction")
        self.direction.setToolTip(
            "Choose whether the alert fires below, above, either way, or at full")
        form.addRow("When", self.direction)

        self.hysteresis = QSpinBox()
        self.hysteresis.setRange(0, 15)
        self.hysteresis.setSuffix(" %")
        self.hysteresis.setValue(self._stop["hysteresis"])
        self.hysteresis.setAccessibleName("Alert hysteresis percent")
        self.hysteresis.setToolTip(
            "Distance the value must move away before this stop can fire again")
        form.addRow("Hysteresis", self.hysteresis)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 3600)
        self.cooldown.setSuffix(" s")
        self.cooldown.setValue(self._stop["cooldown"])
        self.cooldown.setAccessibleName("Alert cooldown seconds")
        self.cooldown.setToolTip("Minimum seconds between alerts from this stop")
        form.addRow("Cooldown", self.cooldown)

        self.delivery = QComboBox()
        self.delivery.addItem("Sound / WAV", "sound")
        self.delivery.addItem("Text to speech", "tts")
        self.delivery.addItem("Off", "off")
        self.delivery.setCurrentIndex(max(0, self.delivery.findData(
            self._stop["delivery"])))
        self.delivery.setAccessibleName("Vital alert delivery")
        form.addRow("Delivery", self.delivery)

        self.delivery_stack = QStackedWidget()
        sound_page = QWidget()
        sound_layout = QVBoxLayout(sound_page)
        sound_layout.setContentsMargins(0, 0, 0, 0)
        self.sound = QComboBox()
        set_sound_combo_value(self.sound, self._stop["sound"])
        self.sound.setAccessibleName("Vital alert sound gallery")
        upload = QPushButton("Add WAV…")
        upload.setAccessibleName("Add custom WAV for this vital alert")
        upload.setToolTip("Copy a WAV into Vantage's portable sound gallery")
        upload.clicked.connect(self._browse_sound)
        sound_layout.addWidget(self.sound)
        sound_layout.addWidget(upload)
        self.delivery_stack.addWidget(sound_page)

        tts_page = QWidget()
        tts_form = polish_form(QFormLayout(tts_page))
        self.tts_text = QLineEdit(self._stop["tts_text"])
        self.tts_text.setAccessibleName("Vital alert speech message")
        self.tts_text.setToolTip(
            "Tokens: {name}, {percent}, and {direction}")
        self.voice = QComboBox()
        self.voice.addItem("Default Windows voice", "")
        for name in speech_voice_names():
            self.voice.addItem(name, name)
        wanted_voice = self.voice.findData(self._stop["voice"])
        self.voice.setCurrentIndex(max(0, wanted_voice))
        self.voice.setAccessibleName("Windows speech voice")
        self.pitch = QSpinBox()
        self.pitch.setRange(-10, 10)
        self.pitch.setValue(self._stop["pitch"])
        self.pitch.setAccessibleName("Vital alert speech pitch")
        tts_form.addRow("Message", self.tts_text)
        tts_form.addRow("Voice", self.voice)
        tts_form.addRow("Pitch", self.pitch)
        self.delivery_stack.addWidget(tts_page)

        off_page = QLabel("This stop remains saved but produces no audio.")
        off_page.setWordWrap(True)
        off_page.setAccessibleDescription(off_page.text())
        self.delivery_stack.addWidget(off_page)
        form.addRow("Options", self.delivery_stack)
        self.delivery.currentIndexChanged.connect(
            lambda: self.delivery_stack.setCurrentIndex(
                self.delivery.currentIndex()))
        self.delivery_stack.setCurrentIndex(self.delivery.currentIndex())

        # Volume applies equally to a gallery/custom WAV and TTS, so it must
        # remain visible for every audible delivery instead of living inside
        # the speech-only page.
        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setValue(self._stop["volume"])
        self.volume.setAccessibleName("Vital alert volume")
        self.volume.setToolTip(
            "Per-stop volume before character profile and master volume")
        form.addRow("Volume", self.volume)

        test = QPushButton("Test delivery")
        test.setAccessibleName("Test this vital alert delivery")
        test.clicked.connect(self._test)
        self.test_status = QLabel("Test status · ready")
        self.test_status.setAccessibleName("Vital alert test status")
        self.test_status.setWordWrap(True)
        form.addRow(test, self.test_status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save stop")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        host = QWidget()
        host.setLayout(form)
        root.addWidget(scrollable(host))
        root.addWidget(buttons)

    def _browse_sound(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose vital alert", "", "WAV Audio (*.wav)")
        if path:
            add_custom_sound_to_combo(self.sound, store_portable_file(path))

    def value(self):
        stop = dict(self._stop)
        stop.update({
            "percent": self.percent.value(),
            "direction": self.direction.currentData(),
            "hysteresis": self.hysteresis.value(),
            "cooldown": self.cooldown.value(),
            "delivery": self.delivery.currentData(),
            "sound": str(self.sound.currentData() or ""),
            "tts_text": self.tts_text.text().strip(),
            "voice": str(self.voice.currentData() or ""),
            "volume": self.volume.value(),
            "pitch": self.pitch.value(),
        })
        return sanitize_vital_stop(stop, 0)

    def _test(self):
        played = bool(self._test_callback and self._test_callback(
            self.value(), "Vital bar", 50, "below"))
        message = "Test status · played" if played else (
            "Test status · Off" if self.delivery.currentData() == "off" else
            "Test status · blocked or unavailable")
        self.test_status.setText(message)
        _announce(self.test_status, message)


class VitalBarDialog(QDialog):
    """Edit a vital bar and its bounded list of threshold stops."""

    def __init__(self, bar=None, parent=None, test_callback=None):
        super().__init__(parent)
        self._bar = sanitize_vital_bar(bar or default_vital_bar(), 0)
        self._stops = [dict(stop) for stop in self._bar["stops"]]
        self._test_callback = test_callback
        self.setWindowTitle("Edit vital bar")
        self.setMinimumSize(460, 470)
        form = polish_form(QFormLayout())
        self.name = QLineEdit(self._bar["name"])
        self.name.setMaxLength(80)
        self.name.setAccessibleName("Vital bar name")
        self.kind = QComboBox()
        for value, label in TYPE_LABELS.items():
            self.kind.addItem(label, value)
        self.kind.setCurrentIndex(max(0, self.kind.findData(self._bar["type"])))
        self.kind.setAccessibleName("Vital bar type")
        self.enabled = QCheckBox("Monitor this bar")
        self.enabled.setChecked(self._bar["enabled"])
        self.enabled.setAccessibleDescription(
            "When checked, Vantage reads the calibrated pixels while EQ is foreground")
        self.fill_direction = QComboBox()
        self.fill_direction.addItem("Left to right", "ltr")
        self.fill_direction.addItem("Right to left", "rtl")
        self.fill_direction.setCurrentIndex(max(
            0, self.fill_direction.findData(self._bar["direction"])))
        self.fill_direction.setAccessibleName("Vital fill direction")
        self.tolerance = QSpinBox()
        self.tolerance.setRange(10, 180)
        self.tolerance.setValue(self._bar["tolerance"])
        self.tolerance.setAccessibleName("Fill color tolerance")
        self.tolerance.setToolTip(
            "Higher values tolerate more shading; recalibrate before increasing")
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Enabled", self.enabled)
        form.addRow("Fill", self.fill_direction)
        form.addRow("Color tolerance", self.tolerance)

        stops_label = QLabel("Alert stops")
        stops_label.setObjectName("SettingsHeader")
        stops_label.setAccessibleDescription(
            "Saved thresholds. Use Add or a preset, then edit delivery per stop.")
        self.stop_list = QListWidget()
        self.stop_list.setObjectName("VitalsStopList")
        self.stop_list.setAccessibleName("Vital alert stops")
        self.stop_list.setAccessibleDescription(
            "Select a stop, then choose Edit or Remove. Delete also removes the selected stop.")
        self.stop_list.itemDoubleClicked.connect(lambda _item: self._edit_stop())
        self._refresh_stops()

        stop_actions = ResponsiveActionBar(92)
        for label, callback, description in (
                ("Add stop", self._add_stop, "Add a custom threshold and delivery"),
                ("Edit", self._edit_stop, "Edit the selected threshold"),
                ("Remove", self._remove_stop, "Remove the selected threshold"),
                ("25/50/75/100", lambda: self._add_preset("quarters"),
                 "Add quarter thresholds"),
                ("Every 10%", lambda: self._add_preset("every10"),
                 "Add thresholds from ten through one hundred percent")):
            button = QPushButton(label)
            button.setAccessibleName(label)
            button.setToolTip(description)
            button.clicked.connect(callback)
            stop_actions.addWidget(button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save bar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        page = QWidget()
        layout = QVBoxLayout(page)
        form_host = QWidget()
        form_host.setLayout(form)
        layout.addWidget(form_host)
        layout.addWidget(stops_label)
        layout.addWidget(self.stop_list, 1)
        layout.addWidget(stop_actions)
        root = QVBoxLayout(self)
        root.addWidget(scrollable(page), 1)
        root.addWidget(buttons)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_Delete and
                self.stop_list.hasFocus()):
            self._remove_stop()
            event.accept()
            return
        super().keyPressEvent(event)

    def _refresh_stops(self):
        selected = self.stop_list.currentRow()
        self.stop_list.clear()
        for stop in self._stops:
            label = (
                f"{DIRECTION_LABELS[stop['direction']]} {stop['percent']}% · "
                f"{stop['delivery'].upper()} · {stop['cooldown']}s cooldown")
            item = QListWidgetItem(label)
            item.setToolTip(label + f" · {stop['hysteresis']}% hysteresis")
            item.setData(Qt.ItemDataRole.UserRole, stop["id"])
            self.stop_list.addItem(item)
        if self._stops:
            self.stop_list.setCurrentRow(max(0, min(selected, len(self._stops) - 1)))

    def _add_stop(self):
        stop = default_vital_stop(25, "below", len(self._stops))
        stop["id"] = "stop-" + uuid.uuid4().hex[:10]
        dialog = VitalStopDialog(stop, self, self._test_callback)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._stops.append(dialog.value())
            self._refresh_stops()

    def _edit_stop(self):
        row = self.stop_list.currentRow()
        if row < 0:
            return
        dialog = VitalStopDialog(
            self._stops[row], self, self._test_callback)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._stops[row] = dialog.value()
            self._refresh_stops()

    def _remove_stop(self):
        row = self.stop_list.currentRow()
        if row >= 0:
            self._stops.pop(row)
            self._refresh_stops()
            self.stop_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _add_preset(self, name):
        existing = {(stop["percent"], stop["direction"]) for stop in self._stops}
        for percent in preset_percentages(name):
            direction = "full" if percent == 100 else "below"
            if (percent, direction) in existing or len(self._stops) >= 32:
                continue
            stop = default_vital_stop(percent, direction, len(self._stops))
            stop["id"] = "stop-" + uuid.uuid4().hex[:10]
            self._stops.append(stop)
        self._refresh_stops()

    def _validate(self):
        if not self.name.text().strip():
            self.name.setFocus(Qt.FocusReason.OtherFocusReason)
            _announce(self.name, "Enter a name for this vital bar")
            return
        self.accept()

    def value(self):
        result = dict(self._bar)
        result.update({
            "name": self.name.text().strip(),
            "type": self.kind.currentData(),
            "enabled": self.enabled.isChecked(),
            "direction": self.fill_direction.currentData(),
            "tolerance": self.tolerance.value(),
            "stops": [dict(stop) for stop in self._stops],
        })
        return sanitize_vital_bar(result, 0)


class VitalCard(QFrame):
    calibrate_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)
    enabled_changed = Signal(str, bool)

    def __init__(self, bar, parent=None):
        super().__init__(parent)
        self.bar_id = bar["id"]
        self.setObjectName("TimerCard")
        self.setAccessibleName(f"{bar['name']} vital bar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        self.name_label = QLabel(bar["name"])
        self.name_label.setObjectName("TimerName")
        self.type_label = QLabel(TYPE_LABELS.get(bar["type"], "Custom").upper())
        self.type_label.setObjectName("TimerBadge")
        heading.addWidget(self.name_label, 1)
        heading.addWidget(self.type_label)
        layout.addLayout(heading)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("NO READING")
        self.progress.setAccessibleName(f"{bar['name']} percentage")
        self.progress.setAccessibleDescription("No visual reading yet")
        layout.addWidget(self.progress)
        self.detail = QLabel("Not calibrated")
        self.detail.setObjectName("InlineStatus")
        self.detail.setWordWrap(True)
        self.detail.setAccessibleName(f"{bar['name']} reading status")
        layout.addWidget(self.detail)
        actions = ResponsiveActionBar(92)
        self.action_buttons = {}
        self.enabled = QCheckBox("Monitor")
        self.enabled.setChecked(bar["enabled"])
        self.enabled.setAccessibleName(f"Monitor {bar['name']}")
        self.enabled.toggled.connect(
            lambda value: self.enabled_changed.emit(self.bar_id, value))
        self.action_buttons["monitor"] = self.enabled
        actions.addWidget(self.enabled)
        for key, label, callback, description in (
                ("calibrate", "Calibrate", self.calibrate_requested,
                 "Select this bar's pixels in EverQuest"),
                ("edit", "Edit alerts", self.edit_requested,
                 "Edit this bar and its alert stops"),
                ("remove", "Remove", self.remove_requested,
                 "Remove this saved vital bar after confirmation")):
            button = QPushButton(label)
            button.setAccessibleName(f"{label} {bar['name']}")
            button.setToolTip(description)
            button.clicked.connect(
                lambda _checked=False, signal=callback: signal.emit(self.bar_id))
            self.action_buttons[key] = button
            actions.addWidget(button)
        layout.addWidget(actions)

    def set_reading(self, reading):
        if reading is not None and reading.valid:
            value = max(0, min(1000, round(reading.percent * 10)))
            self.progress.setValue(value)
            self.progress.setFormat(f"{reading.percent:.1f}%")
            detail = f"Live reading · confidence {reading.confidence * 100:.0f}%"
        else:
            message = reading.message if reading is not None else "No reading"
            self.progress.setValue(0)
            self.progress.setFormat("NO READING")
            detail = message
        self.detail.setText(detail)
        self.detail.setAccessibleDescription(detail)
        self.progress.setAccessibleDescription(detail)


class Vitals(ParserWindow):
    """Continuously monitors explicitly calibrated EQ pixels, read-only."""

    name = "vitals"
    _allow_clickthrough = False
    _minimum_readable_width = 240
    status_changed = Signal()

    def __init__(self):
        self._bars = sanitize_vital_bars(config.data["vitals"].get("bars"))
        config.data["vitals"]["bars"] = self._bars
        self._cards = {}
        self._readings = {}
        self._tracker = VitalStopTracker()
        self._status_text = "NO READING · waiting for EverQuest"
        self._calibration_overlay = None
        self._calibration_controls = None
        self._calibration_context = None
        self._last_live_frame = None
        self._last_live_rect = ()
        self._last_live_at = 0.0
        self._capture = GameWindowCapture(
            config.data.get("mobile", {}).get("eq_executable", ""),
            profile="native")
        super().__init__()
        self.setWindowTitle("Vantage Vitals Monitor")
        self._title.setText("Vitals Monitor")
        self._title.setToolTip("Read-only monitor of calibrated EverQuest bars")
        self._status_badge = QLabel("NO READING")
        self._status_badge.setObjectName("TimerBadge")
        self._status_badge.setAccessibleName("Vitals Monitor status")
        self.menu_area.addWidget(self._status_badge)
        self._add_button = QPushButton("+ Bar")
        self._add_button.setAccessibleName("Add custom vital bar")
        self._add_button.setToolTip("Add a visual bar and calibrate its pixels")
        self._add_button.clicked.connect(self._add_bar)
        self.menu_area.addWidget(self._add_button)

        intro = QLabel(
            "All enabled bars are monitored together from one read-only EQ "
            "frame. Calibrate one bar at a time. Alerts pause whenever "
            "EverQuest is minimized, unavailable, or not foreground.")
        intro.setObjectName("InlineStatus")
        intro.setWordWrap(True)
        intro.setAccessibleDescription(intro.text())
        self.content.addWidget(intro)
        self._bar_page = QWidget()
        self._bar_layout = QVBoxLayout(self._bar_page)
        self._bar_layout.setContentsMargins(5, 5, 5, 5)
        self._bar_layout.setSpacing(5)
        self._bar_layout.addStretch(1)
        self._scroll = scrollable(self._bar_page, "VitalsScroll")
        self._scroll.setAccessibleName("Configured vital bars")
        self.content.addWidget(self._scroll, 1)
        self._rebuild_cards()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(config.data["vitals"]["poll_ms"])
        self._poll_timer.timeout.connect(self.poll_now)
        self._poll_timer.start()
        QTimer.singleShot(0, self.poll_now)

    def parse(self, _timestamp, _text):
        """Vitals intentionally ignores log text and never controls the game."""

    def _update_uniform_scale(self):
        """Reflow Vitals at 240 px instead of shrinking controls to 43%."""
        if self._collapsed:
            return super()._update_uniform_scale()
        scale_view = getattr(self, "_scale_view", None)
        scale_proxy = getattr(self, "_scale_proxy", None)
        if scale_view is None or scale_proxy is None:
            return
        viewport = scale_view.viewport().size()
        logical_width = max(240, viewport.width())
        logical_height = max(1, viewport.height())
        if (logical_width != self._logical_surface_width or
                logical_height != self._logical_surface_height):
            self._logical_surface_width = logical_width
            self._logical_surface_height = logical_height
            self._surface.setFixedSize(logical_width, logical_height)
            self._resize_scale_proxy(logical_width, logical_height)
        self._scale_scene.setSceneRect(QRectF(
            0, 0, logical_width, logical_height))
        scale_view.resetTransform()
        self._update_header_scale_compensation(1.0)
        scale_view.horizontalScrollBar().setValue(
            scale_view.horizontalScrollBar().minimum())
        scale_view.verticalScrollBar().setValue(
            scale_view.verticalScrollBar().minimum())
        self._layout_resize_handles()

    def quickbar_status(self):
        return self._status_text

    def _set_status(self, value):
        value = str(value or "NO READING")
        if value == self._status_text:
            return
        self._status_text = value
        self._status_badge.setText(value.split(" ·", 1)[0])
        self._status_badge.setToolTip(value)
        _announce(self._status_badge, value)
        self.status_changed.emit()

    def _bar_index(self, bar_id):
        return next((index for index, bar in enumerate(self._bars)
                     if bar["id"] == bar_id), -1)

    def _rebuild_cards(self, focus_target=None):
        if focus_target is None:
            focused = self._surface.focusWidget() or QApplication.focusWidget()
            for bar_id, card in self._cards.items():
                for action, control in card.action_buttons.items():
                    if focused is control:
                        focus_target = (bar_id, action)
                        break
                if focus_target:
                    break
        while self._bar_layout.count() > 1:
            item = self._bar_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = {}
        for bar in self._bars:
            card = VitalCard(bar)
            card.calibrate_requested.connect(self._start_calibration)
            card.edit_requested.connect(self._edit_bar)
            card.remove_requested.connect(self._remove_bar)
            card.enabled_changed.connect(self._set_bar_enabled)
            self._bar_layout.insertWidget(self._bar_layout.count() - 1, card)
            self._cards[bar["id"]] = card
            card.set_reading(self._readings.get(bar["id"]))
        if focus_target:
            def restore_focus():
                bar_id, action = focus_target
                card = self._cards.get(bar_id)
                control = card.action_buttons.get(action) if card else None
                if control is None:
                    control = self._add_button
                self._focus_embedded_control(control)
            QTimer.singleShot(0, restore_focus)

    def _focus_embedded_control(self, control):
        if control is None or not control.isVisibleTo(self._surface):
            return False
        self._surface.setFocusProxy(control)
        self._scale_scene.setActivePanel(self._scale_proxy)
        self._scale_proxy.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._scale_scene.setFocusItem(
            self._scale_proxy, Qt.FocusReason.OtherFocusReason)
        self._scale_proxy.setFocus(Qt.FocusReason.OtherFocusReason)
        self._surface.setFocus(Qt.FocusReason.OtherFocusReason)
        control.setFocus(Qt.FocusReason.OtherFocusReason)
        return control.hasFocus() or self._surface.focusWidget() is control

    def _persist(self):
        config.data["vitals"]["bars"] = [dict(bar) for bar in self._bars]
        config.save()

    def _add_bar(self):
        bar = default_vital_bar(
            "vital-" + uuid.uuid4().hex[:12], "Custom bar", "custom")
        dialog = VitalBarDialog(bar, self, self._test_delivery)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._bars.append(dialog.value())
            self._persist()
            self._rebuild_cards((self._bars[-1]["id"], "calibrate"))

    def _edit_bar(self, bar_id):
        index = self._bar_index(bar_id)
        if index < 0:
            return
        dialog = VitalBarDialog(self._bars[index], self, self._test_delivery)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._bars[index] = dialog.value()
            self._tracker.reset_bar(bar_id)
            self._persist()
            self._rebuild_cards((bar_id, "edit"))

    def _remove_bar(self, bar_id):
        index = self._bar_index(bar_id)
        if index < 0:
            return
        name = self._bars[index]["name"]
        answer = QMessageBox.question(
            self, "Remove vital bar",
            f"Remove {name} and all of its alert stops?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        remaining_id = (
            self._bars[index + 1]["id"] if index + 1 < len(self._bars) else
            self._bars[index - 1]["id"] if index > 0 else "")
        self._bars.pop(index)
        self._readings.pop(bar_id, None)
        self._tracker.reset_bar(bar_id)
        self._persist()
        self._rebuild_cards((remaining_id, "monitor"))

    def _set_bar_enabled(self, bar_id, enabled):
        index = self._bar_index(bar_id)
        if index >= 0:
            self._bars[index]["enabled"] = bool(enabled)
            self._tracker.reset_bar(bar_id)
            self._persist()

    def poll_now(self):
        status, image, _window_rect = self._capture.image_frame(
            require_enabled=False, require_foreground=True)
        if not status.get("available"):
            message = str(status.get("message") or "No visual reading")
            self._set_status("NO READING · " + message)
            for bar in self._bars:
                reading = VitalReading(None, 0.0, False, message)
                self._readings[bar["id"]] = reading
                card = self._cards.get(bar["id"])
                if card is not None:
                    card.set_reading(reading)
            return
        self._last_live_frame = image.copy()
        self._last_live_rect = tuple(_window_rect)
        self._last_live_at = time.monotonic()
        valid_count = 0
        low_count = 0
        for bar in self._bars:
            if not bar["enabled"]:
                reading = VitalReading(None, 0.0, False, "Monitoring is off")
            else:
                reading = analyze_vital_bar(
                    image, bar["rect"], bar["color"], bar["direction"],
                    bar["tolerance"])
            self._readings[bar["id"]] = reading
            card = self._cards.get(bar["id"])
            if card is not None:
                card.set_reading(reading)
            if reading.valid:
                valid_count += 1
                for stop, crossed in self._tracker.update(
                        bar["id"], reading.percent, bar["stops"],
                        reading.confidence):
                    self._deliver_stop(bar, stop, reading.percent, crossed)
            elif bar["enabled"] and bar["rect"]:
                low_count += 1
        if valid_count:
            self._set_status(f"ACTIVE · {valid_count} live reading" +
                             ("s" if valid_count != 1 else ""))
        elif low_count:
            self._set_status("NO READING · low confidence; alerts paused")
        else:
            self._set_status("NO READING · calibrate a bar")

    def _deliver_stop(self, bar, stop, percent, crossed):
        message = (
            f"{bar['name']} {crossed} {stop['percent']}% · now {percent:.0f}%")
        app = QApplication.instance()
        if app is not None and hasattr(app, "show_overlay_notification"):
            app.show_overlay_notification(
                "Vantage · Vitals", message, msecs=5500,
                overlay_id="alerts", quickbar_channel="vitals")
        self._play_delivery(stop, bar["name"], percent, crossed)

    def _play_delivery(self, stop, name, percent, crossed):
        delivery = stop.get("delivery", "off")
        source = f"Vitals · {name} {crossed} {stop.get('percent', percent)}%"
        if delivery == "sound":
            return play_alert(
                stop.get("sound", ""), stop.get("volume", 80),
                source=source, character=getattr(self, "_active_character", ""),
                server=getattr(self, "_active_server", ""), channel="vitals",
                allow_hidden=False)
        if delivery == "tts":
            text = str(stop.get("tts_text", "") or "").replace(
                "{name}", str(name)).replace(
                "{percent}", str(round(float(percent)))).replace(
                "{direction}", str(crossed))
            return speak_text(
                text, stop.get("volume", 80), source=source,
                character=getattr(self, "_active_character", ""),
                server=getattr(self, "_active_server", ""), channel="vitals",
                allow_hidden=False, voice_name=stop.get("voice", ""),
                pitch=stop.get("pitch", 0))
        return False

    def _test_delivery(self, stop, name, percent, crossed):
        return self._play_delivery(stop, name, percent, crossed)

    def _start_calibration(self, bar_id):
        index = self._bar_index(bar_id)
        if index < 0:
            return
        self._finish_calibration()
        status, image, window_rect = self._capture.image_frame(
            require_enabled=False, require_foreground=False)
        if (not status.get("available") and self._last_live_frame is not None
                and not self._last_live_frame.isNull()
                and self._last_live_rect
                and time.monotonic() - self._last_live_at <= 10.0):
            image = self._last_live_frame.copy()
            window_rect = self._last_live_rect
            status = {"available": True, "message": "Using recent live frame"}
        if not status.get("available") or image.isNull() or not window_rect:
            message = str(status.get("message") or "EverQuest is unavailable")
            self._set_status("NO READING · " + message)
            QMessageBox.information(
                self, "Calibration unavailable",
                message + "\n\nBring EverQuest to the foreground, then choose Calibrate again.")
            return
        bounds = QRect(*window_rect)
        saved = denormalize_rect(
            self._bars[index]["rect"], (bounds.width(), bounds.height()))
        if saved[2] >= 8 and saved[3] >= 6:
            initial = QRect(
                bounds.x() + saved[0], bounds.y() + saved[1],
                saved[2], saved[3])
        else:
            initial = QRect(
                bounds.x() + round(bounds.width() * .2),
                bounds.y() + round(bounds.height() * .2),
                max(80, round(bounds.width() * .2)),
                max(10, round(bounds.height() * .025)))
        overlay = CalibrationOverlay(bounds, initial)
        controls = CalibrationControls(bounds, initial, self)
        overlay.rect_changed.connect(controls.set_absolute_rect)
        controls.geometry_changed.connect(overlay.set_calibration_geometry)
        controls.use_requested.connect(
            lambda rect: self._apply_calibration(bar_id, rect))
        overlay.cancel_requested.connect(self._finish_calibration)
        controls.rejected.connect(self._finish_calibration)
        controls.destroyed.connect(lambda: self._clear_calibration_refs())
        self._calibration_overlay = overlay
        self._calibration_controls = controls
        self._calibration_context = (bar_id, image, bounds)
        self._set_status(f"CALIBRATING · {self._bars[index]['name']}")
        overlay.show()
        overlay.raise_()
        controls.show()
        controls.raise_()
        controls.activateWindow()
        controls.x.setFocus(Qt.FocusReason.OtherFocusReason)

    def _apply_calibration(self, bar_id, absolute_rect):
        context = self._calibration_context
        index = self._bar_index(bar_id)
        if context is None or index < 0:
            self._finish_calibration()
            return
        _context_id, image, bounds = context
        relative = (
            absolute_rect.x() - bounds.x(), absolute_rect.y() - bounds.y(),
            absolute_rect.width(), absolute_rect.height())
        normalized = normalize_rect(relative, (bounds.width(), bounds.height()))
        color, confidence = learn_fill_color(
            image, normalized, self._bars[index]["direction"])
        if not color:
            controls = self._calibration_controls
            if controls is not None:
                message = (
                    "No fill color found. Put the rectangle inside a visible, "
                    "partly filled colored bar.")
                controls.status.setText(message)
                _announce(controls.status, message)
            return
        self._bars[index]["rect"] = normalized
        self._bars[index]["color"] = color
        self._tracker.reset_bar(bar_id)
        self._persist()
        self._rebuild_cards((bar_id, "calibrate"))
        self._finish_calibration()
        self._set_status(
            f"NO READING · calibrated {self._bars[index]['name']} "
            f"({confidence * 100:.0f}% color sample); return to EverQuest")
        QTimer.singleShot(0, self.poll_now)

    def _clear_calibration_refs(self):
        self._calibration_overlay = None
        self._calibration_controls = None
        self._calibration_context = None

    def _finish_calibration(self):
        had_context = self._calibration_context is not None
        overlay, controls = self._calibration_overlay, self._calibration_controls
        self._clear_calibration_refs()
        if overlay is not None:
            overlay.dismiss()
            overlay.deleteLater()
        if controls is not None:
            controls.close()
            controls.deleteLater()
        if had_context:
            QTimer.singleShot(0, self.poll_now)

    def _parser_settings_config_update_watcher(self):
        super()._parser_settings_config_update_watcher()
        self._capture.set_executable(
            config.data.get("mobile", {}).get("eq_executable", ""))
        self._poll_timer.setInterval(config.data["vitals"]["poll_ms"])

    def closeEvent(self, event):
        self._finish_calibration()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._finish_calibration()
        super().hideEvent(event)
