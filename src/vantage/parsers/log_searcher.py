"""Standalone cached search across every linked Project 1999 log."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.log_search_cache import LogSearchCache
from vantage.helpers.parser import ParserWindow
from vantage.helpers.portable import data_dir


class _LogSearchSignals(QObject):
    index_progress = Signal(int, int, str)
    index_done = Signal(object, str)
    search_done = Signal(object, bool, str)


class LogSearcher(ParserWindow):
    """Fast, local history search with an incremental live-log listener."""

    name = "log_searcher"
    _allow_clickthrough = False

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Log Searcher")
        self._title.setText("Log Searcher")
        self._signals = _LogSearchSignals(self)
        self._signals.index_progress.connect(self._index_progress)
        self._signals.index_done.connect(self._index_complete)
        self._signals.search_done.connect(self._search_complete)
        self._cache = None
        self._cache_directory = ""
        self._indexing = False
        self._searching = False
        self._index_pending = False
        self._initial_focus_set = False
        self._index_focus = None
        self._search_focus = None
        self._index_fallback_focus = None
        self._search_fallback_focus = None
        self._listener_timer = QTimer(self)
        self._listener_timer.setSingleShot(True)
        self._listener_timer.setInterval(700)
        self._listener_timer.timeout.connect(self.refresh_index)
        self._build_ui()
        QTimer.singleShot(0, self.refresh_index)

    def _build_ui(self):
        body = QFrame()
        body.setObjectName("LogSearcherBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        intro = QLabel(
            "Search conversations, deaths, loot and other events across every "
            "character log. Vantage keeps an incremental local cache and never "
            "changes the original EQ files.")
        intro.setWordWrap(True)
        intro.setObjectName("VantageUIIntro")
        layout.addWidget(intro)

        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(5)
        query_label = QLabel("Find")
        self.query = QLineEdit()
        self.query.setPlaceholderText(
            "Name, phrase, item, mob or part of a conversation…")
        self.query.setClearButtonEnabled(True)
        self.query.setAccessibleName("Search all cached EverQuest logs")
        self.query.setToolTip(
            "Search message text; leave blank to browse the selected event type")
        query_label.setBuddy(self.query)
        for button in self.query.findChildren(QToolButton):
            button.setAccessibleName("Clear log search text")
            button.setToolTip("Clear the log search text")
        self.query.returnPressed.connect(self.search)
        controls.addWidget(query_label, 0, 0)
        controls.addWidget(self.query, 0, 1, 1, 5)

        character_label = QLabel("Character")
        self.character = QComboBox()
        self.character.setAccessibleName("Log owner character")
        self.character.setToolTip(
            "Restrict results to the log owned by one character and server")
        self.character.addItem("All characters", "")
        character_label.setBuddy(self.character)
        controls.addWidget(character_label, 1, 0)
        controls.addWidget(self.character, 1, 1)

        event_label = QLabel("Event")
        self.category = QComboBox()
        self.category.setAccessibleName("Log event type")
        self.category.setToolTip(
            "Show only conversations, deaths, loot, zones, combat or system events")
        for label, value in (
                ("Everything", ""), ("Conversations", "conversation"),
                ("Deaths", "death"), ("Loot", "loot"),
                ("Zone changes", "zone"), ("Combat", "combat"),
                ("System and other", "system")):
            self.category.addItem(label, value)
        event_label.setBuddy(self.category)
        controls.addWidget(event_label, 1, 2)
        controls.addWidget(self.category, 1, 3)

        range_label = QLabel("When")
        self.date_range = QComboBox()
        self.date_range.setAccessibleName("Log search date range")
        self.date_range.setToolTip("Restrict results to a recent time period")
        for label, hours in (
                ("All time", 0), ("Today", 24), ("7 days", 168),
                ("30 days", 720), ("90 days", 2160)):
            self.date_range.addItem(label, hours)
        range_label.setBuddy(self.date_range)
        controls.addWidget(range_label, 1, 4)
        controls.addWidget(self.date_range, 1, 5)

        self.search_button = QPushButton("Search logs")
        self.search_button.setIcon(game_icon("search"))
        self.search_button.setAccessibleName("Search the cached EverQuest logs")
        self.search_button.setToolTip("Search using the selected filters")
        self.search_button.clicked.connect(self.search)
        controls.addWidget(self.search_button, 2, 1)
        self.refresh_button = QPushButton("Refresh cache")
        self.refresh_button.setIcon(game_icon("refresh"))
        self.refresh_button.setAccessibleName(
            "Refresh the local cache from every EverQuest log")
        self.refresh_button.setToolTip(
            "Read only new complete lines; unchanged logs are not scanned again")
        self.refresh_button.clicked.connect(
            lambda: self.refresh_index(user_initiated=True))
        controls.addWidget(self.refresh_button, 2, 2)
        self.copy_button = QPushButton("Copy selected")
        self.copy_button.setIcon(game_icon("copy"))
        self.copy_button.setAccessibleName("Copy selected log search rows")
        self.copy_button.setToolTip(
            "Copy the complete text of every selected result")
        self.copy_button.clicked.connect(self.copy_selected)
        controls.addWidget(self.copy_button, 2, 3)
        controls.setColumnStretch(1, 1)
        controls.setColumnStretch(3, 1)
        controls.setColumnStretch(5, 1)
        layout.addLayout(controls)

        self.source = QLabel("No EverQuest Logs folder linked")
        self.source.setObjectName("CombatDataNotice")
        self.source.setWordWrap(True)
        self.source.setAccessibleName("Log Searcher source folder")
        layout.addWidget(self.source)
        self.status = QLabel("Waiting for the local log cache")
        self.status.setObjectName("VantageUIStatus")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Log Searcher status")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("LogSearcherResults")
        self.table.setHorizontalHeaderLabels(
            ("Time", "Character", "Server", "Type", "Message", "Log file"))
        header_tooltips = (
            "Time recorded by the EverQuest log",
            "Character whose log contains this event",
            "Server parsed from the EverQuest log file name",
            "Detected event category",
            "Complete matching EverQuest log message",
            "Source EverQuest log file",
        )
        for column, tooltip in enumerate(header_tooltips):
            self.table.horizontalHeaderItem(column).setToolTip(tooltip)
        self.table.setAccessibleName("EverQuest log search results")
        self.table.setAccessibleDescription(
            "Adjustable columns showing event time, log owner, type, message and source file")
        self.table.setToolTip(
            "Select rows to copy; drag any column divider to adjust its width")
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        for index, width in enumerate((138, 110, 90, 105, 470, 190)):
            self.table.setColumnWidth(index, width)
        layout.addWidget(self.table, 1)
        self.content.addWidget(body, 1)

    def _logs_directory(self):
        selected = str(config.data.get("general", {}).get("eq_log_dir") or "")
        if selected and Path(selected).is_dir():
            return str(Path(selected).resolve())
        eq_root = str(config.data.get("vantage_ui", {}).get("eq_dir") or "")
        candidate = Path(eq_root) / "Logs"
        return str(candidate.resolve()) if candidate.is_dir() else ""

    def _cache_for(self, directory):
        normalized = str(Path(directory).resolve()).casefold()
        if self._cache is None or normalized != self._cache_directory.casefold():
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
            self._cache = LogSearchCache(
                data_dir("log-search", f"logs-{digest}.sqlite3"))
            self._cache_directory = str(Path(directory).resolve())
        return self._cache

    def parse(self, _timestamp, _text):
        """The existing EQ log listener schedules one incremental cache pass."""
        if self._logs_directory():
            self._listener_timer.start()

    def refresh_index(self, *, user_initiated=False):
        directory = self._logs_directory()
        if not directory:
            self.source.setText("No EverQuest Logs folder linked")
            self._set_status(
                "Select the EverQuest Logs folder from the Quick Bar first.")
            return False
        self.source.setText(f"Source · {directory}")
        self.source.setAccessibleDescription(
            f"Reading every eqlog file below {directory}, including its archive folder")
        if self._indexing:
            self._index_pending = True
            return False
        self._indexing = True
        self._index_focus = (
            self._surface.focusWidget() if user_initiated else None)
        self.refresh_button.setEnabled(False)
        self._index_fallback_focus = (
            self._surface.focusWidget() if user_initiated else None)
        self._set_status(
            "Updating the local log cache…", announce=user_initiated)
        cache = self._cache_for(directory)

        def worker():
            try:
                summary = cache.index_directory(
                    directory,
                    lambda current, total, source: self._signals.index_progress.emit(
                        current, total, source))
            except (OSError, ValueError) as error:
                self._signals.index_done.emit(None, str(error))
            else:
                self._signals.index_done.emit(summary, "")

        threading.Thread(
            target=worker, name="Vantage-Log-Indexer", daemon=True).start()
        return True

    def _index_progress(self, current, total, source):
        if self.isVisible():
            self._set_status(
                f"Caching log {current:,}/{max(1, total):,} · {source}",
                announce=False)

    def _populate_characters(self, profiles):
        current = str(self.character.currentData() or "")
        self.character.blockSignals(True)
        self.character.clear()
        self.character.addItem("All characters", "")
        for character, server in profiles:
            key = f"{character}\0{server}"
            self.character.addItem(f"{character} · {server}", key)
        index = self.character.findData(current)
        self.character.setCurrentIndex(max(0, index))
        self.character.blockSignals(False)

    def _index_complete(self, summary, error):
        self._indexing = False
        self.refresh_button.setEnabled(True)
        if error:
            self._set_status(f"Log cache could not update · {error}")
        elif summary is not None:
            self._populate_characters(summary.characters)
            self._set_status(
                f"Cached {summary.indexed_lines:,} lines from {summary.files:,} "
                f"logs · {summary.added_lines:,} new · listener active")
        if self._index_pending:
            self._index_pending = False
            self._listener_timer.start()
        if self._index_focus is not None:
            self._restore_operation_focus(
                self._index_focus, self._index_fallback_focus)
            self._index_focus = None
            self._index_fallback_focus = None

    def search(self, _checked=False):
        directory = self._logs_directory()
        if not directory:
            self._set_status("Select the EverQuest Logs folder first.")
            return False
        if self._searching:
            return False
        cache = self._cache_for(directory)
        owner = str(self.character.currentData() or "")
        character, separator, server = owner.partition("\0")
        if not separator:
            character = server = ""
        hours = int(self.date_range.currentData() or 0)
        since = (datetime.now() - timedelta(hours=hours)).timestamp() \
            if hours else 0.0
        query = self.query.text().strip()
        category = str(self.category.currentData() or "")
        self._searching = True
        self._search_focus = self._surface.focusWidget()
        self.search_button.setEnabled(False)
        self._search_fallback_focus = self._surface.focusWidget()
        description = query or self.category.currentText().casefold()
        self._set_status(f"Searching cached logs for {description}…")

        def worker():
            try:
                results, truncated = cache.search(
                    query, character=character, server=server,
                    category=category, since_epoch=since, limit=2000)
            except (OSError, ValueError) as error:
                self._signals.search_done.emit((), False, str(error))
            else:
                self._signals.search_done.emit(results, truncated, "")

        threading.Thread(
            target=worker, name="Vantage-Log-Search", daemon=True).start()
        return True

    @staticmethod
    def _display_time(value):
        if not value:
            return "Unknown"
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value

    def _search_complete(self, results, truncated, error):
        self._searching = False
        self.search_button.setEnabled(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))
        for row, result in enumerate(results):
            values = (
                self._display_time(result.timestamp), result.character,
                result.server, result.category.replace("_", " ").title(),
                result.message, result.source)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        if error:
            self._set_status(f"Log search failed · {error}")
        else:
            suffix = " · first 2,000 shown" if truncated else ""
            self._set_status(f"{len(results):,} matching log lines{suffix}")
            if results:
                self.table.selectRow(0)
        if self._search_focus is not None:
            self._restore_operation_focus(
                self._search_focus, self._search_fallback_focus)
            self._search_focus = None
            self._search_fallback_focus = None

    def copy_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            self._set_status("Select one or more log rows to copy.")
            return False
        copied = ["\t".join(
            self.table.horizontalHeaderItem(column).text()
            for column in range(self.table.columnCount()))]
        for row in rows:
            copied.append("\t".join(
                self.table.item(row, column).text()
                if self.table.item(row, column) else ""
                for column in range(self.table.columnCount())))
        QApplication.clipboard().setText("\n".join(copied))
        self._set_status(
            f"Copied {len(rows)} log row{'s' if len(rows) != 1 else ''}.")
        return True

    def showEvent(self, event):
        super().showEvent(event)
        if self._initial_focus_set:
            return
        self._initial_focus_set = True
        QTimer.singleShot(
            0, lambda: self.query.setFocus(
                Qt.FocusReason.OtherFocusReason) if self.isVisible() else None)

    def _restore_operation_focus(self, target, fallback):
        """Restore focus through the scaled proxy unless the user moved it."""
        current = self._surface.focusWidget()
        if current not in (None, target, fallback):
            return False
        if not target.isEnabled() or not target.isVisibleTo(self._surface):
            return False
        self._surface.setFocusProxy(target)
        self._scale_view.setFocus(Qt.FocusReason.OtherFocusReason)
        self._scale_scene.setActivePanel(self._scale_proxy)
        self._scale_scene.setFocusItem(
            self._scale_proxy, Qt.FocusReason.OtherFocusReason)
        self._scale_proxy.setFocus(Qt.FocusReason.OtherFocusReason)
        self._surface.setFocus(Qt.FocusReason.OtherFocusReason)
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _set_status(self, text, *, announce=True):
        text = str(text)
        changed = self.status.text() != text
        self.status.setText(text)
        self.status.setAccessibleDescription(text)
        if not announce or not changed or not self.isVisible():
            return
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.status, text))
        except (AttributeError, RuntimeError, TypeError):
            pass
