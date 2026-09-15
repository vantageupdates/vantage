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
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.audio import (
    add_custom_sound_to_combo, play_alert, set_sound_combo_value,
    speak_text, speech_voice_names)
from vantage.helpers.game_capture import GameWindowCapture
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import store_portable_file
from vantage.helpers.responsive import ResponsiveActionBar, polish_form, scrollable
from vantage.helpers.vitals import (
    MIN_CONFIDENCE, VitalReading, VitalStopTracker, default_vital_bar,
    default_vital_stop, denormalize_rect, normalize_rect, preset_percentages,
    read_vital_bar, read_visible_percent,
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
        self.setAccessibleName("Visible percentage calibration overlay")
        self.setAccessibleDescription(
            "Place this overlay over the visible HP or mana number. Drag to "
            "move; drag an edge to resize. Arrow keys move one pixel; Shift "
            "plus arrow moves ten; Alt plus arrow resizes.")
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
            "Arrow keys move; Alt plus arrow resizes. "
            "Preview invalidated; validate again before saving.")
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
        self._schedule_geometry_announcement()
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
    preview_requested = Signal(QRect)
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
        self.setWindowTitle("Calibrate visible percentage number")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(360)
        intro = QLabel(
            "Place the gold rectangle loosely around one visible HP or mana "
            "percentage. Vantage will find the digits, with or without the % "
            "sign, and fit the saved area automatically.")
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

        self.status = QLabel("Calibration ready · preview not validated")
        self.status.setObjectName("InlineStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Calibration status")
        self.status.setAccessibleDescription(self.status.text())
        preview = QPushButton("Validate preview")
        preview.setAccessibleName("Validate vital reading preview")
        preview.setToolTip(
            "Read the selected pixels and verify a percentage before saving")
        preview.clicked.connect(
            lambda: self.preview_requested.emit(self.absolute_rect()))
        self.preview_button = preview
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "Save calibration")
        buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip(
            "Save this validated reading area")
        self._save_button = buttons.button(
            QDialogButtonBox.StandardButton.Save)
        self._save_button.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            "Cancel calibration without changing the saved bar")
        buttons.accepted.connect(
            lambda: self.use_requested.emit(self.absolute_rect()))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.status)
        layout.addWidget(preview)
        self.fine_tune_button = QPushButton("Fine position (optional)")
        self.fine_tune_button.setCheckable(True)
        self.fine_tune_button.setAccessibleName(
            "Fine position (optional)")
        self.fine_tune_button.setAccessibleDescription(
            "Toggle coordinates, size, and one-pixel nudge buttons for keyboard adjustment")
        layout.addWidget(self.fine_tune_button)
        self.fine_tune_host = QWidget()
        fine_layout = QVBoxLayout(self.fine_tune_host)
        fine_layout.setContentsMargins(0, 0, 0, 0)
        host = QWidget()
        host.setLayout(form)
        fine_layout.addWidget(host)
        fine_layout.addWidget(nudge)
        self.fine_tune_host.hide()
        self.fine_tune_button.toggled.connect(self.fine_tune_host.setVisible)
        layout.addWidget(self.fine_tune_host)
        layout.addWidget(buttons)
        self.set_absolute_rect(initial, invalidate=False)

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

    def set_absolute_rect(self, rect, invalidate=True):
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
        if not invalidate:
            message += " · preview not validated"
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        if invalidate:
            self.invalidate_preview()

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

    def invalidate_preview(self):
        self._save_button.setEnabled(False)
        message = "Area changed · validate the preview before saving"
        self.status.setText(message)
        self.status.setAccessibleDescription(message)

    def set_preview(self, message, valid):
        message = str(message)
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        self._save_button.setEnabled(bool(valid))
        _announce(self.status, message)


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
            "When checked, Vantage reads the visible percentage number inside "
            "this bar's saved overlay area. "
            "Direct capture can continue while Vantage is in focus; safe "
            "screen capture may require EverQuest in the foreground.")
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Enabled", self.enabled)

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
            "stops": [dict(stop) for stop in self._stops],
        })
        return sanitize_vital_bar(result, 0)


class VitalsActionBar(ResponsiveActionBar):
    """Responsive actions that never impose their wide layout on a scroll page."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(self._min_cell_width, hint.height())


class VitalsSetupGuide(QFrame):
    """A short three-step guide that reflows instead of clipping."""

    STEPS = (
        ("1", "Place overlay over %"),
        ("2", "Validate reading"),
        ("3", "Set alert stops"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SpawnTimerRow")
        self.setAccessibleName("Vitals setup: three steps")
        self.setAccessibleDescription(
            "; ".join(f"Step {number}: {text}"
                      for number, text in self.STEPS))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 6, 7, 6)
        layout.setSpacing(4)
        title = QLabel("QUICK SETUP")
        title.setObjectName("TimerBadge")
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignLeft)
        self.step_bar = ResponsiveActionBar(150, spacing=4)
        self.step_labels = []
        for number, text in self.STEPS:
            step = QFrame()
            step.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row = QHBoxLayout(step)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(5)
            badge = QLabel(number)
            badge.setObjectName("TimerBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setMinimumWidth(22)
            label = QLabel(text)
            label.setWordWrap(True)
            label.setAccessibleName(f"Step {number}: {text}")
            label.setAccessibleDescription(f"Vitals setup step {number} of 3")
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label, 1)
            self.step_labels.append(label)
            self.step_bar.addWidget(step)
        layout.addWidget(self.step_bar)


class VitalCard(QFrame):
    calibrate_requested = Signal(str)
    edit_requested = Signal(str)
    remove_requested = Signal(str)
    enabled_changed = Signal(str, bool)

    def __init__(self, bar, parent=None):
        super().__init__(parent)
        self.bar_id = bar["id"]
        self._bar = dict(bar)
        self.setObjectName("SpawnTimerRow")
        self.setAccessibleName(f"{bar['name']} vital bar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(5)
        heading = QHBoxLayout()
        self.name_label = QLabel(bar["name"])
        self.name_label.setObjectName("SpawnTimerName")
        self.type_label = QLabel(TYPE_LABELS.get(bar["type"], "Custom").upper())
        self.type_label.setObjectName("SpawnTimerPhase")
        heading.addWidget(self.name_label, 1)
        heading.addWidget(self.type_label)
        layout.addLayout(heading)

        reading_row = QHBoxLayout()
        reading_row.setSpacing(7)
        self.value_label = QLabel("—%")
        self.value_label.setObjectName("SpawnTimerTime")
        self.value_label.setAccessibleName(f"{bar['name']} current percentage")
        self.state_label = QLabel("SETUP")
        self.state_label.setObjectName("SpawnTimerPhase")
        self.state_label.setAccessibleName(f"{bar['name']} monitor state")
        reading_row.addWidget(self.value_label)
        reading_row.addWidget(self.state_label)
        reading_row.addStretch(1)
        layout.addLayout(reading_row)

        self.detail = QLabel("Next: place the overlay over the visible % number")
        self.detail.setObjectName("SpawnTimerDetail")
        self.detail.setWordWrap(True)
        self.detail.setAccessibleName(f"{bar['name']} reading details")
        layout.addWidget(self.detail)
        actions = VitalsActionBar(120)
        self.action_buttons = {}
        self.enabled = QCheckBox()
        self.enabled.setChecked(bar["enabled"])
        self.enabled.setAccessibleName(f"Monitor {bar['name']}")
        self.enabled.setToolTip(
            "Turn read-only monitoring and alert stops on or off for this value")
        self.enabled.toggled.connect(self._enabled_toggled)
        self._sync_enabled_text(self.enabled.isChecked())
        self.action_buttons["monitor"] = self.enabled
        actions.addWidget(self.enabled)
        calibration_help = (
            "Place the overlay loosely around the visible number; Vantage "
            "will find and fit the percentage")
        calibration_label = (
            "Reposition overlay" if bar.get("rect") else "Calibrate")
        for key, label, callback, description in (
                ("calibrate", calibration_label, self.calibrate_requested,
                 calibration_help),
                ("edit", "Alert stops", self.edit_requested,
                 "Configure thresholds and Sound/WAV, Text to speech, or Off"),
                ("remove", "Remove", self.remove_requested,
                 "Remove this saved vital bar after confirmation")):
            button = QPushButton(label)
            button.setAccessibleName(f"{label} {bar['name']}")
            button.setAccessibleDescription(description)
            button.setToolTip(description)
            button.clicked.connect(
                lambda _checked=False, signal=callback: signal.emit(self.bar_id))
            if key == "calibrate":
                button.setObjectName("PrimaryAction")
            elif key == "remove":
                # Destructive but visually tertiary; confirmation remains.
                button.setFlat(True)
            self.action_buttons[key] = button
            actions.addWidget(button)
        layout.addWidget(actions)
        QWidget.setTabOrder(self.enabled, self.action_buttons["calibrate"])
        QWidget.setTabOrder(
            self.action_buttons["calibrate"], self.action_buttons["edit"])
        QWidget.setTabOrder(
            self.action_buttons["edit"], self.action_buttons["remove"])
        self.set_reading(None)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def _sync_enabled_text(self, enabled):
        self.enabled.setText("Monitoring on" if enabled else "Monitoring off")

    def _enabled_toggled(self, enabled):
        self._sync_enabled_text(enabled)
        self.enabled_changed.emit(self.bar_id, enabled)

    def set_reading(self, reading):
        if reading is not None and reading.valid:
            value = f"{reading.percent:.0f}%"
            state = "LIVE"
            detail = (
                "Visible number · "
                f"confidence {reading.confidence * 100:.0f}%")
        else:
            message = reading.message if reading is not None else "No reading"
            value = "—%"
            if not self.enabled.isChecked():
                state = "PAUSED"
                detail = "Monitoring is off · turn it on to read and alert"
            elif not self._bar.get("rect"):
                state = "SETUP"
                detail = "Next: place the overlay over the visible % number"
            else:
                state = "NO READING"
                detail = message
        self.value_label.setText(value)
        self.state_label.setText(state)
        self.detail.setText(detail)
        self.detail.setAccessibleDescription(detail)
        self.value_label.setAccessibleDescription(
            f"{state}. {detail}")
        self.state_label.setAccessibleDescription(detail)
        self.setAccessibleDescription(
            f"{self.name_label.text()}, {value}, {state}. {detail}")


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
        self._calibration_focus_target = None
        self._last_live_frame = None
        self._last_live_rect = ()
        self._last_live_at = 0.0
        self._capture = GameWindowCapture(
            config.data.get("mobile", {}).get("eq_executable", ""),
            profile="native")
        super().__init__()
        self.setWindowTitle("Vantage Vitals Monitor")
        self._title.setText("Vitals")
        self._title.setToolTip(
            "Read visible HP and mana percentages and run configured alerts")
        self._status_badge = QLabel("WAIT")
        self._status_badge.setObjectName("TimerBadge")
        self._status_badge.setAccessibleName("Vitals Monitor status")
        self.menu_area.addWidget(self._status_badge)

        self._guide = VitalsSetupGuide()
        self.content.addWidget(self._guide)
        self._capture_hint = QLabel(
            "Read-only EQ capture · Alerts pause if EverQuest is minimized "
            "or unavailable.")
        self._capture_hint.setObjectName("InlineStatus")
        self._capture_hint.setWordWrap(True)
        self._capture_hint.setAccessibleDescription(self._capture_hint.text())
        self.content.addWidget(self._capture_hint)

        content_actions = VitalsActionBar(135, spacing=4)
        self._add_button = QPushButton("Add monitor")
        self._add_button.setObjectName("PrimaryAction")
        self._add_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._add_button.setMaximumWidth(220)
        self._add_button.setAccessibleName("Add vital monitor")
        self._add_button.setAccessibleDescription(
            "Add another visible percentage and configure its alert stops")
        self._add_button.setToolTip(
            "Add another visible percentage number and configure its alerts")
        self._add_button.clicked.connect(self._add_bar)
        content_actions.addWidget(self._add_button)
        self._monitor_count = QLabel()
        self._monitor_count.setObjectName("InlineStatus")
        self._monitor_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._monitor_count.setAccessibleName("Configured monitor count")
        content_actions.addWidget(self._monitor_count)
        self._content_actions = content_actions
        self.content.addWidget(content_actions)

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
        state = value.split(" ·", 1)[0].strip().upper()
        self._status_badge.setText({
            "NO READING": "WAIT",
            "ACTIVE": "LIVE",
            "CALIBRATING": "SETUP",
        }.get(state, state[:8]))
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
                widget.hide()
                widget.deleteLater()
        self._cards = {}
        self._monitor_count.setText(
            f"{len(self._bars)} monitor" + ("s" if len(self._bars) != 1 else ""))
        self._monitor_count.setAccessibleDescription(self._monitor_count.text())
        if not self._bars:
            empty = QFrame()
            empty.setObjectName("SpawnTimerRow")
            empty.setAccessibleName("No vital monitors configured")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(10, 12, 10, 12)
            title = QLabel("No monitors yet")
            title.setObjectName("SpawnTimerName")
            detail = QLabel(
                "Choose Add monitor, then place the overlay loosely around an "
                "HP or mana percentage.")
            detail.setObjectName("SpawnTimerDetail")
            detail.setWordWrap(True)
            empty_layout.addWidget(title)
            empty_layout.addWidget(detail)
            self._bar_layout.insertWidget(0, empty)
        for bar in self._bars:
            card = VitalCard(bar)
            card.calibrate_requested.connect(self._start_calibration)
            card.edit_requested.connect(self._edit_bar)
            card.remove_requested.connect(self._remove_bar)
            card.enabled_changed.connect(self._set_bar_enabled)
            self._bar_layout.insertWidget(self._bar_layout.count() - 1, card)
            self._cards[bar["id"]] = card
            card.set_reading(self._readings.get(bar["id"]))
        if self._bars:
            first_card = self._cards[self._bars[0]["id"]]
            QWidget.setTabOrder(self._add_button, first_card.enabled)
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
        calibration = getattr(self, '_calibration_context', None)
        if calibration is not None:
            index = self._bar_index(calibration[0])
            name = self._bars[index]['name'] if index >= 0 else 'vital bar'
            self._set_status(f"CALIBRATING · {name}")
            return
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
                reading = read_vital_bar(image, bar)
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
            self._set_status("NO READING · calibrate a percentage number")

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
        # Replacing one modeless calibration must not queue focus restoration
        # to the old card after the new dialog has focused its X field.
        self._finish_calibration(restore_focus=False)
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
                max(46, round(bounds.width() * .08)),
                max(14, round(bounds.height() * .035)))
        overlay = CalibrationOverlay(bounds, initial)
        controls = CalibrationControls(bounds, initial, self)
        overlay.rect_changed.connect(controls.set_absolute_rect)
        controls.geometry_changed.connect(overlay.set_calibration_geometry)
        controls.preview_requested.connect(
            lambda rect: self._preview_calibration(bar_id, rect))
        controls.use_requested.connect(
            lambda rect: self._apply_calibration(bar_id, rect))
        overlay.cancel_requested.connect(self._finish_calibration)
        controls.rejected.connect(self._finish_calibration)
        controls.destroyed.connect(lambda: self._clear_calibration_refs())
        self._calibration_overlay = overlay
        self._calibration_controls = controls
        self._calibration_context = (bar_id, image, bounds)
        self._calibration_focus_target = (bar_id, "calibrate")
        self._set_status(f"CALIBRATING · {self._bars[index]['name']}")
        overlay.show()
        overlay.raise_()
        controls.show()
        controls.raise_()
        controls.activateWindow()
        controls.preview_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _calibration_sample(self, bar_id, absolute_rect):
        context = self._calibration_context
        index = self._bar_index(bar_id)
        if context is None or index < 0:
            return (None, [])
        _context_id, image, bounds = context
        relative = (
            absolute_rect.x() - bounds.x(), absolute_rect.y() - bounds.y(),
            absolute_rect.width(), absolute_rect.height())
        normalized = normalize_rect(relative, (bounds.width(), bounds.height()))
        reading = read_visible_percent(image, normalized)
        if not reading.valid or not reading.token_rect:
            return (reading, normalized)
        token_x, token_y, token_width, token_height = reading.token_rect
        margin = max(2, min(6, round(token_height * .16)))
        left = max(0, token_x - margin)
        top = max(0, token_y - margin)
        right = min(image.width(), token_x + token_width + margin)
        bottom = min(image.height(), token_y + token_height + margin)
        fitted = normalize_rect(
            (left, top, right - left, bottom - top),
            (image.width(), image.height()))
        return (reading, fitted)

    def _preview_calibration(self, bar_id, absolute_rect):
        reading, _normalized = self._calibration_sample(bar_id, absolute_rect)
        controls = self._calibration_controls
        if controls is None or reading is None:
            return
        if reading.valid:
            controls.set_preview(
                f"Detected {reading.percent:.0f}% · confidence "
                f"{reading.confidence * 100:.0f}% · fitted reading area ready to save",
                True)
        else:
            controls.set_preview(
                f"Invalid preview · {reading.message}. "
                "Place the rectangle loosely around only one percentage and try again.",
                False)

    def _apply_calibration(self, bar_id, absolute_rect):
        context = self._calibration_context
        index = self._bar_index(bar_id)
        if context is None or index < 0:
            self._finish_calibration()
            return
        reading, normalized = self._calibration_sample(
            bar_id, absolute_rect)
        if reading is None or not reading.valid:
            controls = self._calibration_controls
            if controls is not None:
                message = (
                    "Calibration not saved · " +
                    (reading.message if reading is not None else
                     "preview unavailable"))
                controls.set_preview(message, False)
            return
        self._bars[index]["rect"] = normalized
        self._bars[index]["ocr_calibrated"] = True
        self._tracker.reset_bar(bar_id)
        self._persist()
        self._rebuild_cards((bar_id, "calibrate"))
        self._finish_calibration()
        result = f"validated {reading.percent:.0f}% visible number"
        self._set_status(
            f"NO READING · calibrated {self._bars[index]['name']} "
            f"({result}); return to EverQuest")
        QTimer.singleShot(0, self.poll_now)

    def _clear_calibration_refs(self):
        self._calibration_overlay = None
        self._calibration_controls = None
        self._calibration_context = None
        self._calibration_focus_target = None

    def _finish_calibration(self, restore_focus=True):
        had_context = self._calibration_context is not None
        focus_target = self._calibration_focus_target
        overlay, controls = self._calibration_overlay, self._calibration_controls
        self._clear_calibration_refs()
        if overlay is not None:
            overlay.dismiss()
            overlay.deleteLater()
        if controls is not None:
            controls.close()
            controls.deleteLater()
        if restore_focus and focus_target and self.isVisible():
            bar_id, action = focus_target
            card = self._cards.get(bar_id)
            control = card.action_buttons.get(action) if card else self._add_button
            QTimer.singleShot(0, lambda: self._focus_embedded_control(control))
        if had_context:
            QTimer.singleShot(0, self.poll_now)

    def _parser_settings_config_update_watcher(self):
        super()._parser_settings_config_update_watcher()
        self._capture.set_executable(
            config.data.get("mobile", {}).get("eq_executable", ""))
        self._poll_timer.setInterval(config.data["vitals"]["poll_ms"])

    def closeEvent(self, event):
        self._finish_calibration(restore_focus=False)
        super().closeEvent(event)

    def hideEvent(self, event):
        self._finish_calibration(restore_focus=False)
        super().hideEvent(event)
