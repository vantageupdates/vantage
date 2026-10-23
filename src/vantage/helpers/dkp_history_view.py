"""Read-only, filterable provenance for a selected character's DKP."""

from datetime import datetime, timedelta, timezone
import math

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHeaderView, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSplitter, QTableView, QTextEdit,
    QToolButton, QVBoxLayout, QWidget)

from vantage.helpers.raid_ledger import parse_timestamp


KINDS = {"raid": "Raid award", "adjustment": "Adjustment", "loot": "Loot"}


def amount_text(value):
    return "Not supplied" if value is None else f"{value:+,.2f}".rstrip("0").rstrip(".")


def finite_total(values):
    try:
        value = math.fsum(values)
        return value if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def source_title(row):
    return (row.get("item_name") if row.get("kind") == "loot" else "") or row["source"]


def source_details(row):
    """Keep the original source available beyond the compact table title."""
    title = source_title(row)
    raw = row.get("raw") or {}
    parts = []
    for value in (row.get("source"), row.get("description"), row.get("ledger_source"),
                  raw.get("Source"), raw.get("Raid"), raw.get("RaidName"),
                  raw.get("Notes"), raw.get("Description")):
        if isinstance(value, str) and value and value != title and not any(
                value in part for part in parts):
            parts.append(value)
    return "\n".join(parts)


class HistoryModel(QAbstractTableModel):
    HEADERS = ("Date / time", "Source", "DKP change", "Type", "Pool")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.sort_column = 0
        self.sort_order = Qt.SortOrder.DescendingOrder

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row
        if index.column() == 1 and role in (
                Qt.ItemDataRole.ToolTipRole, Qt.ItemDataRole.AccessibleDescriptionRole):
            return "\n".join(filter(None, (source_title(row), source_details(row))))
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.AccessibleTextRole):
            stamp = parse_timestamp(row["timestamp"])
            date = stamp.astimezone().strftime("%Y-%m-%d %H:%M") if stamp else "Date not supplied"
            return (date, source_title(row), amount_text(row["amount"]),
                    KINDS[row["kind"]], row["pool"])[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 2:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 2:
            value = row["amount"]
            return QColor("#B7F1E4" if value is not None and value >= 0 else
                          "#FFD0C8" if value is not None else "#AFC0C6")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role in (
                Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self.HEADERS[section]
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self._sort()
        self.endResetModel()

    def _sort(self):
        def key(row):
            stamp = parse_timestamp(row["timestamp"])
            values = (stamp.timestamp() if stamp else None, source_title(row).casefold(),
                      row["amount"], KINDS[row["kind"]], row["pool"].casefold())
            value = values[self.sort_column]
            return (value is not None, value if value is not None else 0)
        self.rows.sort(key=key, reverse=self.sort_order == Qt.SortOrder.DescendingOrder)

    def sort(self, column, order):
        self.beginResetModel()
        self.sort_column, self.sort_order = column, order
        self._sort()
        self.endResetModel()


class DkpHistoryView(QWidget):
    refresh_requested = Signal()
    period_changed = Signal()
    raid_requested = Signal(str)
    item_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.character = ""
        self._selected_key = None
        self._resetting = False
        self._state = "Choose a character to see where your DKP came from."
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(6)
        filters = QGridLayout()
        self.period = QComboBox()
        for text, days in (("Past 90 days", 90), ("Past 30 days", 30),
                           ("Past year", 365), ("All available (up to 10 years)", 3650)):
            self.period.addItem(text, days)
        self.period.setAccessibleName("DKP history period")
        self.period.setToolTip("Reload personal raid history for this period; other history is filtered to match")
        self.period.currentIndexChanged.connect(lambda _index: self.period_changed.emit())
        self.kind = QComboBox()
        self.kind.addItem("All movements", "")
        for key, title in KINDS.items():
            self.kind.addItem(title, key)
        self.kind.setAccessibleName("DKP movement type")
        self.pool = QComboBox()
        self.pool.addItem("All pools (separate totals)", None)
        self.pool.setAccessibleName("DKP pool")
        self.query = QLineEdit()
        self.query.setPlaceholderText("Find a raid, item or adjustment…")
        self.query.setAccessibleName("Search DKP history")
        self.query.setClearButtonEnabled(True)
        clear_query = self.query.findChild(QToolButton)
        if clear_query:
            clear_query.setAccessibleName("Clear DKP history search")
            clear_query.setToolTip("Clear DKP history search")
        self.refresh = QPushButton("Refresh history")
        self.refresh.setToolTip("Retry all history sources for this character")
        self.refresh.clicked.connect(lambda _checked=False: self.refresh_requested.emit())
        filters.addWidget(self.period, 0, 0)
        filters.addWidget(self.kind, 0, 1)
        filters.addWidget(self.pool, 0, 2)
        filters.addWidget(self.query, 1, 0, 1, 2)
        filters.addWidget(self.refresh, 1, 2)
        filters.setColumnStretch(0, 1)
        filters.setColumnStretch(1, 1)
        filters.setColumnStretch(2, 1)
        layout.addLayout(filters)
        self.summary = QLabel()
        self.summary.setObjectName("OpenDkpHistorySummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.summary)
        self.status = QLabel(self._state)
        self.status.setObjectName("OpenDkpPanelHelp")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableView()
        self.model = HistoryModel(self)
        self.table.setModel(self.model)
        self.table.setAccessibleName("DKP history and source")
        self.table.setAccessibleDescription("Select a movement to read its source below. Sort headings or resize columns.")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        for column, width in enumerate((155, 330, 105, 115, 100)):
            self.table.setColumnWidth(column, width)
        split.addWidget(self.table)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        title_row = QHBoxLayout()
        title = QLabel("Where this came from")
        title.setObjectName("OpenDkpPanelTitle")
        title_row.addWidget(title, 1)
        self.open_item = QPushButton("Open item")
        self.open_item.setToolTip("Open the selected loot item's details in Vantage")
        self.open_item.clicked.connect(self._open_item)
        self.open_item.setEnabled(False)
        title_row.addWidget(self.open_item)
        self.check_raid = QPushButton("Check raid details")
        self.check_raid.setToolTip("Read the original raid ticks to verify this award; no guild data is changed")
        self.check_raid.clicked.connect(self._request_raid)
        self.check_raid.setEnabled(False)
        title_row.addWidget(self.check_raid)
        detail_layout.addLayout(title_row)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setAccessibleName("Selected DKP movement details")
        self.detail.setToolTip(
            "Read the selected movement's source, attended ticks, amount and date; "
            "select text to copy it")
        self.detail.setMinimumHeight(100)
        self.detail.setPlaceholderText("Select a movement to see the raid ticks, adjustment reason or item purchase.")
        detail_layout.addWidget(self.detail)
        split.addWidget(detail)
        split.setSizes([180, 160])
        layout.addWidget(split, 1)
        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        self.model.modelAboutToBeReset.connect(self._remember_selection)
        self.model.modelReset.connect(self._restore_selection)
        self.kind.currentIndexChanged.connect(self.apply_filters)
        self.pool.currentIndexChanged.connect(self.apply_filters)
        self.query.textChanged.connect(self.apply_filters)

    def set_history(self, entries, character, state):
        if character != self.character:
            self.table.clearSelection()
            self.table.setCurrentIndex(QModelIndex())
            self._selected_key = None
        self.entries, self.character, self._state = list(entries), character, state
        selected = self.pool.currentData()
        self.pool.blockSignals(True)
        self.pool.clear()
        self.pool.addItem("All pools (separate totals)", None)
        pools = {row["pool_key"]: row["pool"] for row in entries}
        for key, label in sorted(pools.items(), key=lambda pair: pair[1].casefold()):
            self.pool.addItem(label, key)
        self.pool.setCurrentIndex(max(0, self.pool.findData(selected)))
        self.pool.blockSignals(False)
        self.refresh.setEnabled(bool(character))
        self.apply_filters()

    def apply_filters(self, *_args):
        query = self.query.text().strip().casefold()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.period.currentData())
        kind, pool = self.kind.currentData(), self.pool.currentData()
        rows, undated = [], 0
        for row in self.entries:
            stamp = parse_timestamp(row["timestamp"])
            if stamp is not None and stamp < cutoff:
                continue
            if kind and row["kind"] != kind or pool is not None and row["pool_key"] != pool:
                continue
            searchable = " ".join((source_title(row), source_details(row),
                                   row["timestamp"], row["pool"]))
            if query and query not in searchable.casefold():
                continue
            undated += stamp is None
            rows.append(row)
        self.model.set_rows(rows)
        groups = {}
        for row in rows:
            groups.setdefault(row["pool_key"], []).append(row)
        summaries = []
        for key, group in groups.items():
            if not key:
                summaries.append(f"Pool not supplied: {len(group)} movements — see individual amounts below")
                continue
            totals = [finite_total(row["amount"] for row in group if row["kind"] == kind and
                          row["amount"] is not None) for kind in KINDS]
            missing = sum(row["amount"] is None for row in group)
            summaries.append(f"{group[0]['pool']} · Raids {amount_text(totals[0])}  |  "
                             f"Adjustments {amount_text(totals[1])}  |  Loot {amount_text(totals[2])}"
                             + (f" · {missing} amount(s) not supplied" if missing else ""))
        self.summary.setText("\n".join(summaries) or "No movements to summarize")
        self.summary.setAccessibleName(self.summary.text())
        count = f"{len(rows):,} matching movements. " if self.character else ""
        if self.character and not rows and "loading" not in self._state:
            count += "Try another period or clear your filters. "
        note = "Shown history only — not your current balance. Pools are never combined."
        if undated:
            note += f" {undated} undated movement(s) included."
        self.status.setText(count + self._state + ("\n" + note if self.character else ""))
        self.status.setAccessibleName(self.status.text())
        self._selection_changed()

    @staticmethod
    def _row_key(row):
        if not row:
            return None
        if row.get("history_id"):
            return frozenset(("history", row["kind"], identity) for identity in
                             (row["history_id"], *row.get("history_aliases", ())))
        return frozenset((tuple(row.get(key) for key in
                               ("kind", "timestamp", "source", "pool", "raid_id")),))

    def _remember_selection(self):
        self._selected_key = self._row_key(self._selected())
        if self._selected_key:
            selected = self.table.currentIndex().row()
            for index, row in enumerate(self.model.rows):
                if index != selected:
                    self._selected_key -= self._row_key(row)
        self._resetting = True

    def _restore_selection(self):
        index = None
        if self.model.rows:
            matches = [i for i, row in enumerate(self.model.rows)
                       if self._selected_key and self._row_key(row) & self._selected_key]
            if len(matches) == 1:
                index = matches[0]
            elif self._selected_key is None:
                index = 0
        if index is not None:
            self.table.selectRow(index)
        else:
            self.table.clearSelection()
            self.table.setCurrentIndex(QModelIndex())
        self._resetting = False
        self._selection_changed()

    def _selected(self):
        return self.table.currentIndex().data(Qt.ItemDataRole.UserRole)

    def _selection_changed(self, *_args):
        if self._resetting:
            return
        row = self._selected()
        self.open_item.setEnabled(bool(row and row.get("item_name")))
        self.check_raid.setEnabled(bool(row and row["kind"] == "raid" and row["raid_id"]))
        if not row:
            self.detail.clear()
            return
        lines = [f"{source_title(row)} · {amount_text(row['amount'])} DKP",
                 f"{self.character} · {row['pool']} · " + (
                     parse_timestamp(row['timestamp']).astimezone().strftime('%Y-%m-%d %H:%M')
                     if parse_timestamp(row['timestamp']) else 'Date not supplied'),
                 source_details(row)]
        for tick in row.get("ticks", []):
            if tick.get("attended") is False:
                continue
            lines.append(f"• {tick.get('description', 'Raid tick')}: {amount_text(tick.get('amount'))} DKP")
        lines.append("Source: OpenDKP personal history" +
                     (f" · Raid {row['raid_id']}" if row['raid_id'] else "") + " · read-only")
        self.detail.setPlainText("\n".join(filter(None, lines)))

    def _request_raid(self):
        row = self._selected()
        if row and row["kind"] == "raid" and row["raid_id"]:
            self.raid_requested.emit(row["raid_id"])

    def _open_item(self):
        row = self._selected()
        if row and row.get("item_name"):
            self.item_requested.emit(row["item_name"])
