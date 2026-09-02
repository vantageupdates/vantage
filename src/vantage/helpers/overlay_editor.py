"""Editor for Vantage's user-defined notification overlay registry."""

from copy import deepcopy

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.notification_overlay import (
    FONT_WEIGHTS, OVERLAY_TYPES, POSITIONS, reroute_overlay_references)
from vantage.helpers.scaled_dialog import UniformScaleDialog


class ColorButton(QPushButton):
    def __init__(self, value="#0B0D10", parent=None):
        super().__init__(parent)
        self._value = "#0B0D10"
        self.setToolTip("Choose this overlay color")
        self.clicked.connect(self._choose)
        self.set_value(value)

    def value(self):
        return self._value

    def set_value(self, value):
        color = QColor(str(value or "#0B0D10"))
        if not color.isValid():
            color = QColor("#0B0D10")
        self._value = color.name().upper()
        self.setText(self._value)
        foreground = "#111318" if color.lightness() > 145 else "#F4EBD8"
        self.setStyleSheet(
            f"background-color: {self._value}; color: {foreground};")

    def _choose(self):
        color = QColorDialog.getColor(QColor(self._value), self, "Overlay color")
        if color.isValid():
            self.set_value(color.name())


class OverlayManagerDialog(UniformScaleDialog):
    """Create, edit, duplicate, route, arrange, and delete overlays."""

    def __init__(self, manager, parent=None):
        super().__init__(
            QSize(830, 570), parent, minimum_size=QSize(249, 171),
            initial_size=QSize(664, 456))
        self.manager = manager
        self._draft = deepcopy(config.data["general"]["notification_overlays"])
        self._current_id = ""
        self._loading = False
        self.setObjectName("OverlayManagerDialog")
        self.setWindowTitle("Vantage · Overlay Manager")
        root = QVBoxLayout(self.scaled_surface)
        intro = QLabel(
            "Each trigger can route to its own text or timer overlay. "
            "Overlays are independent, always-on-top, movable, resizable, "
            "lockable, and click-through while you play.")
        intro.setObjectName("TriggerTokenLegend")
        intro.setWordWrap(True)
        root.addWidget(intro)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        browser = QWidget()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        self.overlay_list = QListWidget()
        self.overlay_list.setAccessibleName("Notification overlays")
        self.overlay_list.setToolTip(
            "Select an overlay to edit its independent behavior")
        self.overlay_list.currentItemChanged.connect(self._selection_changed)
        browser_layout.addWidget(self.overlay_list, 1)

        add_row = QHBoxLayout()
        add_text = QPushButton("Text")
        add_text.setIcon(game_icon("add"))
        add_text.setToolTip("Create a fading text notification overlay")
        add_text.clicked.connect(lambda: self._add("text"))
        add_timer = QPushButton("Timer")
        add_timer.setIcon(game_icon("timer"))
        add_timer.setToolTip("Create a countdown overlay with timer bars")
        add_timer.clicked.connect(lambda: self._add("timer"))
        add_row.addWidget(add_text)
        add_row.addWidget(add_timer)
        browser_layout.addLayout(add_row)

        item_row = QHBoxLayout()
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.setIcon(game_icon("copy"))
        self.duplicate_button.setToolTip(
            "Copy this overlay without copying its screen position")
        self.duplicate_button.clicked.connect(self._duplicate)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerAction")
        self.delete_button.setIcon(game_icon("delete"))
        self.delete_button.setToolTip(
            "Delete this overlay and reroute its triggers to another overlay")
        self.delete_button.clicked.connect(self._delete)
        item_row.addWidget(self.duplicate_button)
        item_row.addWidget(self.delete_button)
        browser_layout.addLayout(item_row)
        splitter.addWidget(browser)

        editor = QWidget()
        self.editor_page = editor
        editor.setObjectName("OverlayEditorPage")
        form = QFormLayout(editor)
        form.setContentsMargins(8, 0, 0, 0)
        form.setSpacing(7)

        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setToolTip("Name shown in trigger routes and the on-screen editor")
        form.addRow("Name", self.name)
        self.overlay_type = QComboBox()
        for label, value in OVERLAY_TYPES:
            self.overlay_type.addItem(label, value)
        self.overlay_type.setToolTip(
            "Text overlays fade; timer overlays can show countdown bars")
        self.overlay_type.currentIndexChanged.connect(self._type_changed)
        form.addRow("Kind", self.overlay_type)
        self.enabled = QCheckBox("Receive notifications")
        self.enabled.setToolTip(
            "Disabled overlays remain configured but do not appear during play")
        form.addRow("Status", self.enabled)

        self.position = QComboBox()
        for label, value in POSITIONS:
            self.position.addItem(label, value)
        self.position.setToolTip(
            "Initial position; dragging the overlay saves an exact position")
        form.addRow("Initial position", self.position)
        self.sort = QComboBox()
        self.sort.addItem("Newest first", "newest")
        self.sort.addItem("Oldest first", "oldest")
        self.sort.addItem("Least time remaining", "time_remaining")
        self.sort.setToolTip("How simultaneous notification rows are ordered")
        form.addRow("Order", self.sort)

        self.max_entries = QSpinBox()
        self.max_entries.setRange(1, 20)
        self.max_entries.setToolTip("Maximum rows visible in this overlay")
        form.addRow("Visible rows", self.max_entries)
        self.font_name = QComboBox()
        self.font_name.setEditable(True)
        self.font_name.addItems(("Noto Sans", "Segoe UI", "Arial", "Verdana"))
        self.font_name.setToolTip("Font family used only by this overlay")
        self.font_name.lineEdit().setToolTip(
            "Type or choose the font family used only by this overlay")
        self.font_name.lineEdit().setAccessibleName("Overlay font family")
        form.addRow("Font", self.font_name)
        self.font_size = QSpinBox()
        self.font_size.setRange(7, 32)
        self.font_size.setSuffix(" pt")
        self.font_size.setToolTip("Text size used only by this overlay")
        form.addRow("Text size", self.font_size)
        self.font_weight = QComboBox()
        for label, value in FONT_WEIGHTS:
            self.font_weight.addItem(label, value)
        self.font_weight.setToolTip(
            "Font weight used by titles, messages, and countdowns")
        form.addRow("Text weight", self.font_weight)
        self.font_color = ColorButton("#F2EAD8")
        form.addRow("Text color", self.font_color)

        self.group_titles = QCheckBox("Replace repeated titles")
        self.group_titles.setToolTip(
            "Keep the newest row when the same trigger fires again")
        form.addRow("Repeated triggers", self.group_titles)
        self.group_characters = QCheckBox("Keep each character separate")
        self.group_characters.setToolTip(
            "When grouping is enabled, do not merge different character profiles")
        form.addRow("Characters", self.group_characters)

        self.show_bars = QCheckBox("Show countdown progress bars")
        self.show_bars.setToolTip("Show a visual bar under timed notifications")
        form.addRow("Timer bars", self.show_bars)
        self.standardize_bars = QCheckBox("Use one shared time scale")
        self.standardize_bars.setToolTip(
            "Compare all bars against the longest active countdown")
        form.addRow("Bar scale", self.standardize_bars)
        self.bar_color = ColorButton("#B5782F")
        form.addRow("Bar color", self.bar_color)
        self.empty_bar_color = ColorButton("#171B20")
        form.addRow("Empty bar", self.empty_bar_color)

        self.background_color = ColorButton("#0B0D10")
        form.addRow("Background", self.background_color)
        self.background_opacity = QSpinBox()
        self.background_opacity.setRange(0, 100)
        self.background_opacity.setSuffix("%")
        self.background_opacity.setToolTip(
            "Opacity of the overlay card while a notification is active")
        form.addRow("Background opacity", self.background_opacity)
        self.faded_background_color = ColorButton("#0B0D10")
        self.faded_background_color.setToolTip(
            "Background color during the final part of a text fade")
        form.addRow("Fading background", self.faded_background_color)
        self.faded_background_opacity = QSpinBox()
        self.faded_background_opacity.setRange(0, 100)
        self.faded_background_opacity.setSuffix("%")
        self.faded_background_opacity.setToolTip(
            "Background opacity during the final part of a text fade")
        form.addRow("Fading opacity", self.faded_background_opacity)
        self.fade_seconds = QSpinBox()
        self.fade_seconds.setRange(0, 300)
        self.fade_seconds.setSuffix(" s")
        self.fade_seconds.setToolTip(
            "Default lifetime for text notifications that do not specify one")
        form.addRow("Text fade", self.fade_seconds)
        editor_scroll = QScrollArea()
        editor_scroll.setObjectName("OverlayEditorScroll")
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_scroll.setWidget(editor)
        splitter.addWidget(editor_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        arrangement = QHBoxLayout()
        arrange_selected = QPushButton("Arrange selected")
        arrange_selected.setIcon(game_icon("cursor"))
        arrange_selected.setToolTip(
            "Show this overlay on screen so it can be moved and resized")
        arrange_selected.clicked.connect(self._arrange_selected)
        arrange_all = QPushButton("Arrange all")
        arrange_all.setIcon(game_icon("frame"))
        arrange_all.setToolTip(
            "Show every overlay together for direct screen placement")
        arrange_all.clicked.connect(self._arrange_all)
        arrangement.addWidget(arrange_selected)
        arrangement.addWidget(arrange_all)
        arrangement.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setToolTip("Discard overlay changes")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("PrimaryAction")
        save.setIcon(game_icon("spawn"))
        save.setToolTip("Save the overlay registry and trigger routing")
        save.clicked.connect(self._save)
        arrangement.addWidget(cancel)
        arrangement.addWidget(save)
        root.addLayout(arrangement)

        self._populate()

    def _populate(self, selected_id=""):
        self.overlay_list.blockSignals(True)
        self.overlay_list.clear()
        for overlay_id, settings in self._draft.items():
            kind = "TIMER" if settings.get("type") == "timer" else "TEXT"
            state = "" if settings.get("enabled", True) else " · OFF"
            item = QListWidgetItem(
                game_icon("timer" if kind == "TIMER" else "poi"),
                f"{settings.get('label', overlay_id)}\n{kind}{state}")
            item.setData(Qt.ItemDataRole.UserRole, overlay_id)
            self.overlay_list.addItem(item)
        if not self._draft:
            empty = QListWidgetItem(
                game_icon("delete"),
                "NO OVERLAYS\nON-SCREEN NOTIFICATIONS OFF")
            empty.setToolTip(
                "Create a Text or Timer overlay to enable on-screen notifications")
            empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.overlay_list.addItem(empty)
        self.overlay_list.blockSignals(False)
        target = selected_id or self._current_id
        row = 0
        for index in range(self.overlay_list.count()):
            if self.overlay_list.item(index).data(
                    Qt.ItemDataRole.UserRole) == target:
                row = index
                break
        if self.overlay_list.count():
            self.overlay_list.setCurrentRow(row)
        has_selection = bool(self._draft)
        self.delete_button.setEnabled(has_selection)
        self.duplicate_button.setEnabled(has_selection)
        self.editor_page.setEnabled(has_selection)

    def _selection_changed(self, current, _previous):
        self._capture_current()
        self._current_id = (
            current.data(Qt.ItemDataRole.UserRole) if current else "")
        self._load_current()

    def _load_current(self):
        settings = self._draft.get(self._current_id)
        if not settings:
            return
        self._loading = True
        self.name.setText(settings.get("label", ""))
        self._set_combo(self.overlay_type, settings.get("type", "text"))
        self.enabled.setChecked(settings.get("enabled", True))
        self._set_combo(
            self.position, settings.get("default_position", "top_center"))
        self._set_combo(self.sort, settings.get("sort", "newest"))
        self.max_entries.setValue(int(settings.get("max_entries", 5)))
        self.font_name.setCurrentText(settings.get("font_name", "Noto Sans"))
        self.font_size.setValue(int(settings.get("font_size", 10)))
        self._set_combo(
            self.font_weight, settings.get("font_weight", "medium"))
        self.font_color.set_value(settings.get("font_color", "#F2EAD8"))
        self.group_titles.setChecked(settings.get("group_titles", False))
        self.group_characters.setChecked(
            settings.get("group_by_character", False))
        self.show_bars.setChecked(settings.get("show_timer_bar", True))
        self.standardize_bars.setChecked(
            settings.get("standardize_timer_bars", False))
        self.bar_color.set_value(settings.get("timer_bar_color", "#B5782F"))
        self.empty_bar_color.set_value(
            settings.get("empty_bar_color", "#171B20"))
        self.background_color.set_value(
            settings.get("background_color", "#0B0D10"))
        self.background_opacity.setValue(
            int(settings.get("background_opacity", 92)))
        self.faded_background_color.set_value(
            settings.get("faded_background_color", "#0B0D10"))
        self.faded_background_opacity.setValue(
            int(settings.get("faded_background_opacity", 65)))
        self.fade_seconds.setValue(int(settings.get("text_fade_seconds", 8)))
        self._loading = False
        self._type_changed()

    def _capture_current(self):
        if self._loading or self._current_id not in self._draft:
            return
        settings = self._draft[self._current_id]
        settings.update({
            "label": self.name.text().strip() or "Overlay",
            "type": str(self.overlay_type.currentData()),
            "enabled": self.enabled.isChecked(),
            "default_position": str(self.position.currentData()),
            "sort": str(self.sort.currentData()),
            "newest_first": self.sort.currentData() == "newest",
            "max_entries": self.max_entries.value(),
            "font_name": self.font_name.currentText().strip() or "Noto Sans",
            "font_size": self.font_size.value(),
            "font_weight": str(self.font_weight.currentData()),
            "font_color": self.font_color.value(),
            "group_titles": self.group_titles.isChecked(),
            "group_by_character": self.group_characters.isChecked(),
            "show_timer_bar": self.show_bars.isChecked(),
            "standardize_timer_bars": self.standardize_bars.isChecked(),
            "timer_bar_color": self.bar_color.value(),
            "empty_bar_color": self.empty_bar_color.value(),
            "background_color": self.background_color.value(),
            "background_opacity": self.background_opacity.value(),
            "faded_background_color": self.faded_background_color.value(),
            "faded_background_opacity": self.faded_background_opacity.value(),
            "text_fade_seconds": self.fade_seconds.value(),
        })

    @staticmethod
    def _set_combo(combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _type_changed(self):
        is_timer = self.overlay_type.currentData() == "timer"
        for widget in (
                self.show_bars, self.standardize_bars,
                self.bar_color, self.empty_bar_color):
            widget.setEnabled(is_timer)

    def _next_id(self, overlay_type):
        prefix = "timer_overlay" if overlay_type == "timer" else "text_overlay"
        index = 1
        while f"{prefix}_{index}" in self._draft:
            index += 1
        return f"{prefix}_{index}"

    def _add(self, overlay_type):
        self._capture_current()
        overlay_id = self._next_id(overlay_type)
        self._draft[overlay_id] = config.notification_overlay_defaults(
            overlay_id, overlay_type)
        self._draft[overlay_id]["label"] = (
            "Timer overlay" if overlay_type == "timer" else "Text overlay")
        self._populate(overlay_id)

    def _duplicate(self):
        self._capture_current()
        source = self._draft.get(self._current_id)
        if not source:
            return
        overlay_id = self._next_id(source.get("type", "text"))
        clone = deepcopy(source)
        clone["label"] = f"{source.get('label', 'Overlay')} copy"
        clone.pop("geometry", None)
        self._draft[overlay_id] = clone
        self._populate(overlay_id)

    def _delete(self):
        if self._current_id not in self._draft:
            return
        label = self._draft[self._current_id].get("label", self._current_id)
        detail = (
            " This is the last overlay, so all on-screen notifications will "
            "be disabled until you create another one."
            if len(self._draft) == 1 else
            " Triggers routed here will be moved to another overlay.")
        answer = QMessageBox.question(
            self, "Delete overlay",
            f"Delete “{label}”?{detail}",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._draft[self._current_id]
        self._current_id = ""
        self._populate()

    def _apply(self):
        self._capture_current()
        old_ids = set(config.data["general"]["notification_overlays"])
        normalized = config.normalize_notification_overlays(
            self._draft, seed_defaults=False)
        reroute_overlay_references(
            old_ids - set(normalized), normalized)
        config.data["general"]["notification_overlays"] = normalized
        config.save()
        self.manager.reload()

    def _arrange_selected(self):
        selected = self._current_id
        self._apply()
        self.accept()
        QTimer.singleShot(0, lambda: self.manager.edit(selected))

    def _arrange_all(self):
        self._apply()
        self.accept()
        QTimer.singleShot(0, self.manager.edit_all)

    def _save(self):
        self._apply()
        self.accept()
