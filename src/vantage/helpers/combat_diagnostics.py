"""Compact, opt-in combat parser diagnostics.

The dialog follows the category split exposed by the original parser's Log
Details window while keeping raw evidence local, bounded, and disabled unless
the player explicitly enables it.
"""

from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QDialog, QFileDialog, QHBoxLayout,
    QFrame, QGraphicsItem, QGraphicsScene, QGraphicsView, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QToolButton, QVBoxLayout, QWidget)

from vantage.helpers import config


CATEGORIES = (
    "All", "Melee", "Defense", "Direct Damage", "DoT", "Healing",
    "Spells", "Unmatched")

HEADERS = {
    "All": (
        "Time", "Category", "Actor", "Target", "Amount", "Action",
        "Outcome", "Detail", "Source line"),
    "Melee": (
        "Time", "Attacker", "Opponent", "Hit", "Attack", "Outcome",
        "Detail", "Source line"),
    "Defense": (
        "Time", "Defender", "Opponent", "Outcome", "Defense", "Detail",
        "Source line"),
    "Direct Damage": (
        "Time", "Attacker", "Opponent", "Hit", "Spell", "Outcome",
        "Detail", "Source line"),
    "DoT": (
        "Time", "Attacker", "Opponent", "Hit", "Spell", "Outcome",
        "Detail", "Source line"),
    "Healing": (
        "Time", "Healer", "Healee", "Actual heal", "Spell / source",
        "Outcome", "Detail", "Source line"),
    "Spells": (
        "Time", "Caster", "Spell / action", "Outcome", "Target", "Detail",
        "Source line"),
    "Unmatched": ("Time", "Result", "Detail", "Source line"),
}

HEADER_TOOLTIPS = {
    "Time": "Timestamp supplied by the selected EverQuest log",
    "Category": "Parser branch that accepted this line",
    "Actor": "Actor parsed from the source line",
    "Attacker": "Attacker parsed from the source line",
    "Defender": "Character or NPC performing the defensive action",
    "Caster": "Caster visible in the source line",
    "Healer": "Healer visible in the source line",
    "Target": "Target parsed from the source line",
    "Opponent": "Opponent parsed from the source line",
    "Healee": "Target receiving the visible heal",
    "Amount": "Numeric amount parsed from the line",
    "Hit": "Damage value parsed from the line",
    "Actual heal": "Healing amount visible in the P99 log",
    "Action": "Normalized attack, spell, or parser action",
    "Attack": "Normalized melee attack type",
    "Defense": "Dodge, parry, block, riposte, or miss result",
    "Spell": "Spell name when it can be observed or safely correlated",
    "Spell / source": "Observed heal source; P99 may not expose a spell name",
    "Spell / action": "Spell or action name visible to the parser",
    "Outcome": "Hit, cast, resist, fizzle, interrupt, reflect, block, or avoid",
    "Result": "Why this combat-looking line needs review",
    "Detail": "Additional context used by the parser",
    "Source line": "Original local log text retained only in this bounded buffer",
}


class CombatDiagnosticsDialog(QDialog):
    """Modeless, progressively disclosed view of raw parser decisions."""

    def __init__(self, tracker, parent=None):
        super().__init__(parent)
        self.tracker = tracker
        self.setWindowTitle("Parser Diagnostics")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(300, 154)
        self.resize(760, 390)
        self._signature = None

        self._surface = QWidget()
        self._surface.setObjectName("CombatDiagnosticsSurface")
        self._surface.setFixedSize(760, 390)
        root = QVBoxLayout(self._surface)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(5)

        notice = QLabel(
            "ADVANCED · local session evidence only · raw chat is never collected here")
        notice.setObjectName("CombatDataNotice")
        notice.setWordWrap(True)
        notice.setToolTip(
            "Diagnostics store at most 5,000 combat parser decisions in memory; "
            "they are not uploaded and are cleared when Vantage exits")
        root.addWidget(notice)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)

        self.capture = QPushButton("Capture")
        self.capture.setCheckable(True)
        self.capture.setChecked(bool(tracker.diagnostics_enabled))
        self.capture.setAccessibleName("Capture parser diagnostics")
        self.capture.setToolTip(
            "Start or stop retaining new combat parser decisions; no past lines are read")
        self.capture.toggled.connect(self._capture_toggled)
        toolbar.addWidget(self.capture)

        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Filter actor, spell, outcome, or source…")
        self.search.setAccessibleName("Filter parser diagnostics")
        self.search.setToolTip(
            "Filter the current diagnostic category without changing stored records")
        self.search.textChanged.connect(self._filter_changed)
        toolbar.addWidget(self.search, 1)

        self.copy_button = QPushButton("Copy")
        self.copy_button.setAccessibleName("Copy diagnostic rows")
        self.copy_button.setToolTip(
            "Copy selected rows, or every filtered row when nothing is selected")
        self.copy_button.clicked.connect(self._copy_rows)
        toolbar.addWidget(self.copy_button)

        self.save_button = QPushButton("CSV…")
        self.save_button.setAccessibleName("Save diagnostic rows as CSV")
        self.save_button.setToolTip(
            "Save the current filtered diagnostic category as a UTF-8 CSV file")
        self.save_button.clicked.connect(self._save_csv)
        toolbar.addWidget(self.save_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("DangerAction")
        self.clear_button.setAccessibleName("Clear diagnostic buffer")
        self.clear_button.setToolTip(
            "Delete only the in-memory diagnostic buffer; parsed fights are unchanged")
        self.clear_button.clicked.connect(self._clear)
        toolbar.addWidget(self.clear_button)
        root.addLayout(toolbar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setAccessibleName("Parser diagnostic categories")
        self.tabs.setToolTip(
            "Switch between melee, defense, direct damage, DoT, healing, spell, "
            "and unmatched parser evidence")
        self.tables = {}
        for category in CATEGORIES:
            table = self._make_table(category)
            self.tables[category] = table
            host = QWidget()
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(table)
            index = self.tabs.addTab(host, category)
            self.tabs.setTabToolTip(
                index, f"Show {category.casefold()} parser evidence")
        self.tabs.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabs, 1)
        QTimer.singleShot(0, self._polish_tab_scrollers)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setAccessibleName("Diagnostic capture status")
        self.status.setToolTip(
            "Shows capture state, visible rows, and the fixed 5,000-record limit")
        footer.addWidget(self.status, 1)
        close_button = QPushButton("Close")
        close_button.setAccessibleName("Close parser diagnostics")
        close_button.setToolTip(
            "Close this window; capture keeps its selected on or off state")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self._scene = QGraphicsScene(self)
        self._scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self._proxy = self._scene.addWidget(self._surface)
        self._proxy.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self._view = QGraphicsView(self._scene, self)
        self._view.setObjectName("CombatDiagnosticsScaleView")
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._view.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing)
        self._view.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._view.setToolTip(
            "Parser diagnostic surface; resize the window to scale every control together")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._view)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self.refresh)
        self.refresh(force=True)
        QTimer.singleShot(0, self._update_scale)

    def _polish_tab_scrollers(self):
        for index, button in enumerate(
                self.tabs.tabBar().findChildren(QToolButton)):
            label = ("Previous diagnostic category" if index == 0 else
                     "Next diagnostic category")
            button.setAccessibleName(label)
            button.setToolTip(label)

    def _make_table(self, category):
        headers = HEADERS[category]
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAccessibleName(f"{category} parser diagnostic table")
        table.setToolTip(
            f"Parsed {category.casefold()} decisions and their original local source lines")
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsMovable(True)
        for index, label in enumerate(headers):
            item = table.horizontalHeaderItem(index)
            item.setToolTip(HEADER_TOOLTIPS[label])
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        return table

    @staticmethod
    def _time(record):
        return record.timestamp.strftime("%H:%M:%S")

    def _values(self, record, category):
        amount = f"{record.amount:,}" if record.amount else "—"
        if category == "All":
            return (
                self._time(record), record.category, record.actor, record.target,
                amount, record.action, record.outcome, record.detail, record.source)
        if category in {"Melee", "Direct Damage", "DoT", "Healing"}:
            return (
                self._time(record), record.actor, record.target, amount,
                record.action, record.outcome, record.detail, record.source)
        if category == "Defense":
            return (
                self._time(record), record.actor, record.target, record.outcome,
                record.action, record.detail, record.source)
        if category == "Spells":
            return (
                self._time(record), record.actor, record.action, record.outcome,
                record.target, record.detail, record.source)
        return (self._time(record), record.outcome, record.detail, record.source)

    def _category(self):
        return CATEGORIES[max(0, self.tabs.currentIndex())]

    def _filtered_records(self, category=None):
        category = category or self._category()
        query = self.search.text().strip().casefold()
        records = (
            list(self.tracker.diagnostics) if category == "All" else
            [record for record in self.tracker.diagnostics
             if record.category == category])
        if not query:
            return records
        return [
            record for record in records
            if query in "\n".join((
                record.category, record.actor, record.target, str(record.amount),
                record.action, record.outcome, record.detail,
                record.source)).casefold()]

    def _filter_changed(self):
        self._signature = None
        self.refresh(force=True)

    def _tab_changed(self):
        self._signature = None
        self.refresh(force=True)

    def _capture_toggled(self, enabled):
        self.tracker.set_diagnostics_enabled(enabled)
        config.data["combat"]["parser_diagnostics_enabled"] = bool(enabled)
        config.save()
        self._signature = None
        self.refresh(force=True)

    def _clear(self):
        self.tracker.clear_diagnostics()
        self._signature = None
        self.refresh(force=True)

    def refresh(self, force=False):
        signature = (
            self.tracker.diagnostics_revision, self._category(),
            self.search.text().casefold(), self.tracker.diagnostics_enabled)
        if not force and signature == self._signature:
            return
        self._signature = signature

        counts = {category: 0 for category in CATEGORIES}
        counts["All"] = len(self.tracker.diagnostics)
        for record in self.tracker.diagnostics:
            counts[record.category] = counts.get(record.category, 0) + 1
        for index, category in enumerate(CATEGORIES):
            self.tabs.setTabText(index, f"{category} ({counts.get(category, 0):,})")

        category = self._category()
        records = self._filtered_records(category)
        table = self.tables[category]
        table.setUpdatesEnabled(False)
        table.setRowCount(len(records))
        for row, record in enumerate(records):
            for column, value in enumerate(self._values(record, category)):
                item = QTableWidgetItem(str(value or "—"))
                item.setToolTip(str(value or HEADER_TOOLTIPS.get(
                    HEADERS[category][column], "Parsed diagnostic value")))
                if HEADERS[category][column] in {"Amount", "Hit", "Actual heal"}:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, column, item)
        table.setUpdatesEnabled(True)
        table.viewport().update()

        state = "ON" if self.tracker.diagnostics_enabled else "OFF"
        self.status.setText(
            f"Capture {state} · showing {len(records):,} of "
            f"{counts.get(category, 0):,} · memory limit 5,000")
        self.clear_button.setEnabled(bool(self.tracker.diagnostics))
        self.copy_button.setEnabled(bool(records))
        self.save_button.setEnabled(bool(records))

    def _table_text(self, selected_only=False):
        category = self._category()
        table = self.tables[category]
        selected = sorted({index.row() for index in table.selectedIndexes()})
        rows = selected if selected_only and selected else range(table.rowCount())
        header = [table.horizontalHeaderItem(column).text()
                  for column in range(table.columnCount())]
        values = [header]
        for row in rows:
            values.append([
                table.item(row, column).text() if table.item(row, column) else ""
                for column in range(table.columnCount())])
        return values

    def _copy_rows(self):
        rows = self._table_text(selected_only=True)
        QApplication.clipboard().setText(
            "\n".join("\t".join(values) for values in rows))

    def _save_csv(self):
        suggested = f"Vantage-Parser-Diagnostics-{self._category().replace(' ', '-')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Parser Diagnostics", suggested, "CSV files (*.csv)")
        if not path:
            return
        target = Path(path)
        if target.suffix.casefold() != ".csv":
            target = target.with_suffix(".csv")
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(self._table_text())

    def showEvent(self, event):
        super().showEvent(event)
        self._update_scale()
        self._signature = None
        self.refresh(force=True)
        self._refresh_timer.start()
        self.search.setFocus(Qt.FocusReason.OtherFocusReason)

    def hideEvent(self, event):
        self._refresh_timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scale()

    def _update_scale(self):
        if not self._view or not self._proxy:
            return
        self._scene.setSceneRect(QRectF(0, 0, 760, 390))
        viewport = self._view.viewport().size()
        scale = max(0.01, min(viewport.width() / 760, viewport.height() / 390))
        self._view.resetTransform()
        self._view.scale(scale, scale)
