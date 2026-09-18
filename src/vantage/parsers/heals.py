"""Compact Complete Heal rotation monitor."""

import datetime

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QFormLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.heal_rail import HealRailWidget
from vantage.helpers.heal_chain import HealChainTracker
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.responsive import (
    ensure_table_header_tooltips, ensure_tab_tooltips)


class HealChain(ParserWindow):

    def __init__(self):
        self.name = "heals"
        super().__init__()
        self._title.setText("Heal Chain")
        self.setWindowTitle("Heal Chain")
        settings = config.data["heals"]
        self._tracker = HealChainTracker(
            settings["hotkey_format"], settings["interval"],
            settings["cast_seconds"])
        self._history_revision = -1
        self._last_turn_key = None

        self.header_countdown = QLabel("READY")
        self.header_countdown.setObjectName("HealChainHeaderCountdown")
        self.header_countdown.setProperty("State", "ready")
        self.header_countdown.setMinimumWidth(66)
        self.header_countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_countdown.setAccessibleName(
            "Current Complete Heal countdown")
        self.header_countdown.setToolTip(
            "Current cleric marker and cast time remaining; stays visible when rolled up")
        self.menu_area.addWidget(self.header_countdown)

        self.interval = QSpinBox()
        self.interval.setObjectName("HealChainInterval")
        self.interval.setRange(1, 9)
        self.interval.setSuffix("s")
        self.interval.setValue(settings["interval"])
        self.interval.setMinimumWidth(43)
        self.interval.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.interval.setAccessibleName("Complete Heal chain interval")
        self.interval.setToolTip(
            "Expected time between clerics; /gu !KI3 changes it to 3 seconds")
        self.interval.valueChanged.connect(self._interval_changed)
        self.menu_area.addWidget(self.interval)

        self.pause = QPushButton()
        self.pause.setObjectName("HealChainPause")
        self.pause.setCheckable(True)
        self.pause.setIcon(game_icon("pause"))
        self.pause.setAccessibleName("Pause Heal Chain monitoring")
        self.pause.setToolTip("Pause or resume new Heal Chain events")
        self.pause.toggled.connect(self._pause_changed)
        self.menu_area.addWidget(self.pause)

        self.clear_button = QPushButton()
        self.clear_button.setObjectName("HealChainClear")
        self.clear_button.setIcon(game_icon("delete"))
        self.clear_button.setAccessibleName("Clear Heal Chain")
        self.clear_button.setToolTip(
            "Clear the live chain and its session history")
        self.clear_button.clicked.connect(self._clear)
        self.menu_area.addWidget(self.clear_button)

        self.summary = QLabel("Listening for Complete Heal announcements")
        self.summary.setObjectName("HealChainSummary")
        self.summary.setProperty("State", "ready")
        self.summary.setAccessibleName(self.summary.text())
        self.summary.setAccessibleDescription(
            "Current monitoring state, spacing, call format, tank, and next "
            "Complete Heal marker")
        self.summary.setWordWrap(True)
        self.summary.setToolTip(
            "Shows the current tank, cleric marker, next marker, and interruption state")
        self.content.addWidget(self.summary)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("HealChainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(False)
        self.rails = HealRailWidget(self._tracker)
        self.live = self._make_table(
            ("Tank", "Order", "Cleric", "Cast", "Left", "Status"))
        self.live.setObjectName("HealChainLiveTable")
        self.live.setAccessibleName("Active Complete Heal casts")
        self.live.setAccessibleDescription(
            "Current and recently interrupted Complete Heal calls, including "
            "tank, cleric, marker, remaining time, and next marker")
        self.history = self._make_table(
            ("Time", "Tank", "Order", "Cleric", "Next", "Result"))
        self.history.setObjectName("HealChainHistoryTable")
        self.history.setAccessibleName("Complete Heal session history")
        self.history.setAccessibleDescription(
            "Completed and interrupted Complete Heal calls from this session")
        self.tabs.addTab(self.rails, "Rails")
        self.tabs.addTab(self.live, "Live")
        self.tabs.addTab(self.history, "History")
        self.settings_tab = self._build_settings_tab()
        self.tabs.addTab(self.settings_tab, "Settings")
        ensure_tab_tooltips(self.tabs, {
            "Rails": "Show each tank's active Complete Heal rotation rail",
            "Live": "Show casts that are active or recently interrupted",
            "History": "Show the bounded Complete Heal session history",
            "Settings": "Configure this Heal Chain window here",
        })
        self.content.addWidget(self.tabs, 1)
        QWidget.setTabOrder(self._button, self.interval)
        QWidget.setTabOrder(self.interval, self.pause)
        QWidget.setTabOrder(self.pause, self.clear_button)
        QWidget.setTabOrder(
            self.clear_button, self._header_overflow_button)
        QWidget.setTabOrder(
            self._header_overflow_button, self._settings_button)
        QWidget.setTabOrder(self._settings_button, self._roll_button)
        QWidget.setTabOrder(self._roll_button, self._minimize_button)
        QWidget.setTabOrder(self._minimize_button, self.tabs)
        QWidget.setTabOrder(self.notify_turn, self._button)
        self.monitor_enabled.installEventFilter(self)
        self.notify_turn.installEventFilter(self)
        self._button.installEventFilter(self)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    def _build_settings_tab(self):
        """Keep every Heal Chain option inside the Heal Chain window."""
        page = QWidget()
        page.setObjectName("HealChainSettingsPage")
        form = QFormLayout(page)
        form.setContentsMargins(10, 8, 10, 8)
        form.setSpacing(7)

        self.monitor_enabled = QCheckBox("Read Complete Heal calls")
        self.monitor_enabled.setAccessibleName("Enable Heal Chain monitor")
        self.monitor_enabled.setToolTip(
            "Parse Complete Heal calls even while this panel is hidden")
        form.addRow("Monitor", self.monitor_enabled)

        self.settings_interval = QSpinBox()
        self.settings_interval.setRange(1, 9)
        self.settings_interval.setSuffix(" s")
        self.settings_interval.setAccessibleName("Cleric spacing")
        self.settings_interval.setToolTip(
            "Expected time between clerics; the header control mirrors this")
        form.addRow("Cleric spacing", self.settings_interval)

        self.cast_seconds = QSpinBox()
        self.cast_seconds.setRange(1, 20)
        self.cast_seconds.setSuffix(" s")
        self.cast_seconds.setAccessibleName("Cast rail length")
        self.cast_seconds.setToolTip(
            "Length of the moving Complete Heal cast rail")
        form.addRow("Cast rail length", self.cast_seconds)

        self.hotkey_format = QLineEdit()
        self.hotkey_format.setPlaceholderText("### - CH - tankname")
        self.hotkey_format.setAccessibleName("Heal announcement format")
        self.hotkey_format.setToolTip(
            "Use ### for cleric order and tankname for the target")
        form.addRow("Announcement format", self.hotkey_format)

        self.own_marker = QLineEdit()
        self.own_marker.setMaxLength(3)
        self.own_marker.setPlaceholderText("Auto-detect")
        self.own_marker.setAccessibleName("Your cleric order")
        self.own_marker.setToolTip(
            "Optional marker such as AAA; blank learns it from your own call")
        form.addRow("Your cleric order", self.own_marker)

        self.notify_turn = QCheckBox("Alert when your marker is next")
        self.notify_turn.setAccessibleName("Alert when you are next")
        form.addRow("Turn alert", self.notify_turn)

        note = QLabel(
            "Changes save here immediately. Required format tokens: "
            "### = cleric order · tankname = heal target.")
        note.setObjectName("CombatDataNotice")
        note.setWordWrap(True)
        form.addRow("", note)

        self._load_embedded_settings()
        self.monitor_enabled.toggled.connect(self._save_embedded_settings)
        self.settings_interval.valueChanged.connect(
            self._settings_interval_changed)
        self.cast_seconds.valueChanged.connect(self._save_embedded_settings)
        self.hotkey_format.editingFinished.connect(
            self._save_embedded_settings)
        self.own_marker.editingFinished.connect(
            self._save_embedded_settings)
        self.notify_turn.toggled.connect(self._save_embedded_settings)
        return page

    def _load_embedded_settings(self):
        settings = config.data["heals"]
        pairs = (
            (self.monitor_enabled, settings["enabled"]),
            (self.settings_interval, settings["interval"]),
            (self.cast_seconds, settings["cast_seconds"]),
            (self.hotkey_format, settings["hotkey_format"]),
            (self.own_marker, settings.get("own_marker", "")),
            (self.notify_turn, settings.get("notify_turn", True)),
        )
        for widget, value in pairs:
            widget.blockSignals(True)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            else:
                widget.setText(str(value))
            widget.blockSignals(False)

    def _settings_interval_changed(self, value):
        self.interval.blockSignals(True)
        self.interval.setValue(value)
        self.interval.blockSignals(False)
        self._save_embedded_settings()

    def _save_embedded_settings(self, *_args):
        settings = config.data["heals"]
        settings.update({
            "enabled": self.monitor_enabled.isChecked(),
            "interval": self.settings_interval.value(),
            "cast_seconds": self.cast_seconds.value(),
            "hotkey_format": self.hotkey_format.text().strip() or
                             "### - CH - tankname",
            "own_marker": self.own_marker.text().strip().upper(),
            "notify_turn": self.notify_turn.isChecked(),
        })
        self._tracker.configure(
            settings["hotkey_format"], settings["interval"],
            settings["cast_seconds"])
        config.save()
        self.refresh()

    def _show_inline_settings(self):
        """The header gear opens the local Settings tab, not global Settings."""
        if self._collapsed:
            self._toggle_rollup()
        self.tabs.setCurrentWidget(self.settings_tab)
        self.tabs.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _parser_settings_config_update_watcher(self):
        super()._parser_settings_config_update_watcher()
        self._load_embedded_settings()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if watched is self.notify_turn and key == Qt.Key.Key_Tab \
                    and not shift:
                self._focus_embedded_control(
                    self._button, Qt.FocusReason.TabFocusReason)
                return True
            if watched is self.monitor_enabled and (
                    key == Qt.Key.Key_Backtab or
                    (key == Qt.Key.Key_Tab and shift)):
                self._focus_embedded_control(
                    self.tabs, Qt.FocusReason.BacktabFocusReason)
                return True
            if watched is self._button and (
                    key == Qt.Key.Key_Backtab or
                    (key == Qt.Key.Key_Tab and shift)):
                self._focus_embedded_control(
                    self.notify_turn, Qt.FocusReason.BacktabFocusReason)
                return True
        return super().eventFilter(watched, event)

    def _focus_embedded_control(self, control, reason):
        """Move focus across the scaled Qt proxy without losing the child."""
        if control is None or not control.isVisibleTo(self._surface):
            return False
        self._surface.setFocusProxy(control)
        self._scale_scene.setActivePanel(self._scale_proxy)
        self._scale_proxy.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._scale_scene.setFocusItem(self._scale_proxy, reason)
        self._scale_proxy.setFocus(reason)
        self._surface.setFocus(reason)
        control.setFocus(reason)
        return control.hasFocus() or self._surface.focusWidget() is control

    @staticmethod
    def _make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        ensure_table_header_tooltips(table, "the Heal Chain")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        table.setToolTip("Complete Heal chain events parsed from your linked EQ log")
        return table

    def _interval_changed(self, value):
        self._tracker.interval = value
        config.data["heals"]["interval"] = value
        if hasattr(self, "settings_interval"):
            self.settings_interval.blockSignals(True)
            self.settings_interval.setValue(value)
            self.settings_interval.blockSignals(False)
        config.save()
        self.refresh()

    def _pause_changed(self, paused):
        self.rails.set_paused(paused)
        self.pause.setIcon(game_icon("play" if paused else "pause"))
        self.pause.setAccessibleName(
            "Resume Heal Chain monitoring" if paused else
            "Pause Heal Chain monitoring")
        self.pause.setToolTip(
            "Resume reading new Complete Heal events" if paused else
            "Pause reading new Complete Heal events")
        self.refresh()

    def _set_visual_state(self, state):
        """Keep status color, text, and accessible state in sync."""
        state = str(state)
        for widget in (self.header_countdown, self.summary):
            if widget.property("State") == state:
                continue
            widget.setProperty("State", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _clear(self):
        if not self._tracker.casts:
            return
        answer = QMessageBox.question(
            self, "Clear Heal Chain", "Clear the live chain and session history?\n"
            "The original EverQuest log will not be changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self._tracker.clear()
            self.refresh()

    def parse(self, timestamp, text):
        settings = config.data["heals"]
        self._tracker.configure(
            settings["hotkey_format"], settings["interval"],
            settings["cast_seconds"])
        if self.pause.isChecked() or not settings["enabled"]:
            return
        result = self._tracker.ingest(timestamp, text)
        if not result:
            return
        event, payload = result
        if event == "interval":
            self.interval.blockSignals(True)
            self.interval.setValue(payload)
            self.interval.blockSignals(False)
            config.data["heals"]["interval"] = payload
            config.save()
        elif event == "cast":
            self._notify_turn(payload)
        self.refresh()

    def _notify_turn(self, cast):
        settings = config.data["heals"]
        own = (settings.get("own_marker") or self._tracker.local_marker).upper()
        next_marker = self._tracker.next_marker(cast.tank, cast.marker)
        turn_key = (cast.tank.casefold(), next_marker, cast.started_at)
        if (settings.get("notify_turn", True) and own and next_marker == own and
                turn_key != self._last_turn_key):
            self._last_turn_key = turn_key
            QApplication.instance().show_overlay_notification(
                "Vantage · YOUR HEAL",
                f"{own} is next on {cast.tank}", msecs=3500,
                overlay_id="alerts")

    @staticmethod
    def _item(value, right=False):
        item = QTableWidgetItem(str(value))
        if right:
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return item

    def refresh(self):
        now = datetime.datetime.now()
        self.rails.update()
        active = list(reversed(self._tracker.active(now)))
        self.live.setRowCount(len(active))
        for row, cast in enumerate(active):
            remaining = cast.remaining(now, self._tracker.cast_seconds)
            next_marker = self._tracker.next_marker(cast.tank, cast.marker)
            values = (cast.tank, cast.marker, cast.cleric)
            for column, value in enumerate(values):
                self.live.setItem(row, column, self._item(value))
            progress = QProgressBar()
            progress.setObjectName("HealChainProgress")
            progress.setRange(0, 1000)
            progress.setValue(round(
                remaining / self._tracker.cast_seconds * 1000))
            progress.setFormat("")
            progress.setAccessibleName(
                f"Cast remaining for {cast.marker} from {cast.cleric}")
            progress.setAccessibleDescription(
                f"{remaining:.1f} seconds remain on {cast.tank}")
            progress.setToolTip(
                f"{cast.marker} from {cast.cleric} · {remaining:.1f}s remaining")
            self.live.setCellWidget(row, 3, progress)
            self.live.setItem(row, 4, self._item(f"{remaining:.1f}s", True))
            self.live.setItem(row, 5, self._item(
                "INTERRUPTED" if cast.interrupted else f"Next {next_marker}"))

        if self.pause.isChecked():
            self._set_visual_state("paused")
            self.header_countdown.setText("PAUSED")
            self.header_countdown.setToolTip(
                "Heal Chain monitoring is paused; resume to read new calls")
            self.summary.setText(
                f"Monitoring paused  ·  {self._tracker.interval}s spacing  ·  "
                "press Play to resume")
        elif active:
            self._set_visual_state("active")
            latest = active[0]
            remaining = latest.remaining(now, self._tracker.cast_seconds)
            self.header_countdown.setText(
                f"{latest.marker} {remaining:.1f}s")
            self.header_countdown.setToolTip(
                f"{latest.cleric} healing {latest.tank} · "
                f"{remaining:.1f} seconds remain · next "
                f"{self._tracker.next_marker(latest.tank, latest.marker)}")
            next_marker = self._tracker.next_marker(latest.tank, latest.marker)
            self.summary.setText(
                f"Tank: {latest.tank}  ·  {latest.marker}: {latest.cleric}  ·  "
                f"Next: {next_marker}  ·  {self._tracker.interval}s spacing")
        else:
            self._set_visual_state("ready")
            self.header_countdown.setText("READY")
            self.header_countdown.setToolTip(
                "No Complete Heal cast is currently active")
            self.summary.setText(
                f"Listening for CH calls  ·  {self._tracker.interval}s spacing  ·  "
                f"{self._tracker.hotkey_format}")
        self.summary.setAccessibleName(self.summary.text())

        if self._history_revision == self._tracker.revision:
            return
        casts = list(reversed(self._tracker.casts))[:150]
        self.history.setRowCount(len(casts))
        for row, cast in enumerate(casts):
            values = (
                cast.started_at.strftime("%H:%M:%S"), cast.tank, cast.marker,
                cast.cleric, self._tracker.next_marker(cast.tank, cast.marker),
                "Interrupted" if cast.interrupted else "Called")
            for column, value in enumerate(values):
                self.history.setItem(row, column, self._item(value, column == 0))
        self._history_revision = self._tracker.revision
