"""Small native layout helpers for resizable Vantage surfaces."""

from __future__ import annotations

import hashlib
import re
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QGridLayout, QHeaderView, QLayout,
    QMenu, QScrollArea, QSizePolicy, QTableView, QTableWidget, QTabWidget,
    QToolButton, QTreeView, QWidget)

from vantage.helpers import config


TABLE_HEADER_TOOLTIPS = {
    "%": "Percentage represented by this row in the current view",
    "% spell": "Share of the displayed spell damage represented by this row",
    "actor": "Character or NPC responsible for the event",
    "amount": "Numeric amount visible in the source log event",
    "attack": "Melee attack, skill, or damage source",
    "average": "Arithmetic mean for the values represented by this row",
    "avg": "Arithmetic mean for the values represented by this row",
    "cast": "Elapsed or remaining cast information",
    "caster": "Character or NPC whose cast is visible in the log",
    "cleric": "Cleric name parsed from the Complete Heal announcement",
    "damage": "Damage observed in the linked EverQuest log",
    "detail": "Additional parsed context for this row",
    "dps": "Damage per second for the displayed scope",
    "duplicates": "Additional rolls by a player in the same roll set",
    "duration": "Elapsed time covered by this row",
    "event": "Normalized type of logged event",
    "file": "EverQuest log file containing the match",
    "flux": "Recent change in the local threat estimate",
    "healer": "Character whose heal is visible in the log",
    "healing": "Healing amount visible in the linked EverQuest log",
    "heals": "Number of visible healing events",
    "hits": "Number of successful damaging hits",
    "left": "Estimated seconds left in the current cast",
    "line": "Line number inside the source log file",
    "matching log line": "Original log text that matched the search",
    "maximum": "Largest observed value for this row",
    "max": "Largest observed value for this row",
    "mh": "Threat attributed to the configured main hand",
    "min": "Smallest observed value for this row",
    "next": "Next configured Complete Heal order marker",
    "oh": "Threat attributed to the configured off hand",
    "order": "Complete Heal order marker parsed from the announcement",
    "outcome": "Parsed result such as hit, resist, interrupt, or avoidance",
    "owner": "Character linked to this pet",
    "pet": "Pet name visible in the log or manual link",
    "player": "Character represented by this row",
    "players": "Number of player attackers represented in the fight",
    "proc": "Threat attributed to configured weapon proc messages",
    "range": "Minimum and maximum values for this /random set",
    "result": "Resolved outcome for this event or fight",
    "roll": "Value printed by one /random event",
    "rolls": "Number of rolls included in this set",
    "skill": "Threat attributed to supported combat skills",
    "source": "Log-visible or configured source for this row",
    "spell": "Spell name visible or safely correlated from the log",
    "spell / action": "Spell, discipline, or action visible in the log",
    "started": "Time this event group or fight began",
    "state": "Current parser or estimator state",
    "status": "Current Complete Heal cast status",
    "target": "Character or NPC receiving the event",
    "threat": "Local threat estimate from observable actions",
    "ticks": "Number of visible damage-over-time ticks",
    "time": "Timestamp supplied by the linked EverQuest log",
    "tpm": "Estimated threat per minute",
    "winner": "Player selected by the current duplicate-roll policy",
    "winning roll": "Highest eligible roll in this set",
    "your dps": "Damage per second attributed to the active character",
    "zone": "EverQuest zone active when the event was logged",
}


def ensure_table_header_tooltips(table: QTableWidget, context="this"):
    """Give every authored table heading a semantic keyboard/hover description."""
    for column in range(table.columnCount()):
        item = table.horizontalHeaderItem(column)
        if item is None or item.toolTip().strip():
            continue
        heading = item.text().strip()
        tooltip = TABLE_HEADER_TOOLTIPS.get(heading.casefold())
        item.setToolTip(
            tooltip or f"{heading} value for each row in {context} view")
    return table


def ensure_tab_tooltips(tabs: QTabWidget, descriptions):
    """Describe every tab and its native overflow buttons without adding UI."""
    descriptions = dict(descriptions or {})
    for index in range(tabs.count()):
        label = tabs.tabText(index)
        tabs.setTabToolTip(
            index, descriptions.get(
                label, f"Open the {label} view"))

    def polish_scrollers():
        for index, button in enumerate(
                tabs.tabBar().findChildren(QToolButton)):
            label = "Previous tab" if index == 0 else "Next tab"
            button.setAccessibleName(label)
            button.setToolTip(label)

    QTimer.singleShot(0, polish_scrollers)
    return tabs


def _safe_column_key(value):
    value = re.sub(r"[^a-z0-9_.-]+", "-", str(value or "").casefold())
    return value.strip("-")[:96]


class TableColumnManager(QObject):
    """Make every native data column manually resizable and persistent.

    Qt's Stretch, Fixed, and ResizeToContents modes can look reasonable on a
    fresh screen while making a clipped column impossible to correct.  This
    application filter freezes each table's authored layout into Interactive
    sections on first show, then remembers the user's exact widths.
    """

    MIN_WIDTH = 28
    MAX_WIDTH = 2400
    MAX_TABLES = 256
    WIDTH_STEP = 32
    INSTRUCTIONS = (
        "Drag heading dividers to resize columns. Press Shift+F10 from a cell "
        "for keyboard column width controls.")

    def __init__(self, application=None):
        application = application or QApplication.instance()
        super().__init__(application)
        self.setObjectName("TableColumnManager")
        self._application = application
        self._views = {}
        self._defaults = {}
        self._sources = {}
        self._models = set()
        self._applying = set()
        self._open_menus = []
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save)
        if application is not None:
            application.installEventFilter(self)
            application.aboutToQuit.connect(self.flush)

    @staticmethod
    def _view_ref(view):
        return weakref.ref(view)

    def eventFilter(self, watched, event):
        view = watched if isinstance(watched, (QTableView, QTreeView)) else None
        if view is not None:
            if event.type() == QEvent.Type.Show:
                self._schedule_configure(view)
            elif event.type() == QEvent.Type.LayoutRequest:
                header = view.horizontalHeader()
                if (header is not None and header.count() and
                        (header.stretchLastSection() or any(
                            header.sectionResizeMode(column) !=
                            QHeaderView.ResizeMode.Interactive
                            for column in range(header.count())))):
                    self._schedule_configure(view)

        source_ref = self._sources.get(id(watched))
        source_view = source_ref() if source_ref is not None else view
        if (source_view is not None and
                event.type() == QEvent.Type.KeyPress and
                event.key() == Qt.Key.Key_F10 and
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._show_column_menu(source_view, watched, QPoint(-1, -1))
            event.accept()
            return True
        return False

    def _schedule_configure(self, view):
        reference = self._view_ref(view)

        def configure():
            candidate = reference()
            if candidate is None:
                return
            try:
                self._configure(candidate)
            except RuntimeError:
                return

        QTimer.singleShot(0, configure)

    def _owner_key(self, view):
        application = self._application or QApplication.instance()
        for name, parser in getattr(application, "_parsers_dict", {}).items():
            surface = getattr(parser, "_surface", None)
            try:
                if surface is not None and (
                        view is surface or surface.isAncestorOf(view)):
                    return _safe_column_key(name)
            except RuntimeError:
                continue
        window = view.window()
        return _safe_column_key(
            window.objectName() or window.windowTitle() or
            window.metaObject().className()) or "vantage"

    def _column_key(self, view):
        explicit = _safe_column_key(view.property("vantageColumnKey"))
        identity = explicit or _safe_column_key(view.objectName())
        if not identity:
            identity = _safe_column_key(view.accessibleName())
        model = view.model()
        headings = []
        if model is not None:
            for column in range(min(64, model.columnCount())):
                headings.append(str(model.headerData(
                    column, Qt.Orientation.Horizontal,
                    Qt.ItemDataRole.DisplayRole) or ""))
        digest = hashlib.sha1(
            "\x1f".join(headings).encode("utf-8")).hexdigest()[:12]
        if not identity:
            identity = view.metaObject().className().casefold()
        return f"{self._owner_key(view)}/{identity}-{digest}"

    @staticmethod
    def _widths(view):
        return [view.columnWidth(column)
                for column in range(view.model().columnCount())]

    @staticmethod
    def _storage():
        general = config.data.setdefault("general", {})
        storage = general.setdefault("table_column_widths", {})
        if not isinstance(storage, dict):
            storage = {}
            general["table_column_widths"] = storage
        return storage

    def _configure(self, view):
        if isinstance(view.window(), QFileDialog):
            return
        model = view.model()
        header = view.horizontalHeader()
        count = model.columnCount() if model is not None else 0
        if count <= 0 or header is None:
            return
        key = self._column_key(view)
        previous_key = str(
            view.property("vantageColumnKeyResolved") or "")
        if previous_key and previous_key != key:
            self._views.pop(previous_key, None)
        view.setProperty("vantageColumnKeyResolved", key)
        self._views[key] = self._view_ref(view)
        current = [max(self.MIN_WIDTH, int(view.columnWidth(column)))
                   for column in range(count)]
        if key not in self._defaults or len(self._defaults[key]) != count:
            self._defaults[key] = list(current)

        applying_key = id(header)
        self._applying.add(applying_key)
        try:
            header.setStretchLastSection(False)
            for column in range(count):
                header.setSectionResizeMode(
                    column, QHeaderView.ResizeMode.Interactive)
            saved = self._storage().get(key)
            widths = saved if isinstance(saved, list) and len(saved) == count else current
            for column, width in enumerate(widths):
                view.setColumnWidth(column, max(
                    self.MIN_WIDTH, min(self.MAX_WIDTH, int(width))))
        finally:
            self._applying.discard(applying_key)

        if not view.property("vantageColumnManagerConnected"):
            view.setProperty("vantageColumnManagerConnected", True)
            reference = self._view_ref(view)
            header.sectionResized.connect(
                lambda *_args, ref=reference: self._column_resized(ref))
            header.sectionCountChanged.connect(
                lambda *_args, ref=reference: self._reconfigure_ref(ref))
            self._install_context_source(view, view)
            self._install_context_source(view.viewport(), view)
            self._install_context_source(header, view)
        model_id = id(model)
        if model_id not in self._models:
            self._models.add(model_id)
            reference = self._view_ref(view)
            model.headerDataChanged.connect(
                lambda orientation, *_args, ref=reference:
                self._header_data_changed(ref, orientation))
            model.modelReset.connect(
                lambda ref=reference: self._reconfigure_ref(ref))
            model.destroyed.connect(
                lambda *_args, current_id=model_id:
                self._models.discard(current_id))
        self._describe(view)

    def _header_data_changed(self, reference, orientation):
        if orientation == Qt.Orientation.Horizontal:
            self._reconfigure_ref(reference)

    def _reconfigure_ref(self, reference):
        view = reference()
        if view is not None:
            self._schedule_configure(view)

    def _install_context_source(self, source, view):
        if source.property("vantageColumnMenuConnected"):
            return
        source.setProperty("vantageColumnMenuConnected", True)
        source.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        source_ref = weakref.ref(source)
        view_ref = self._view_ref(view)
        self._sources[id(source)] = view_ref
        source.customContextMenuRequested.connect(
            lambda point, sref=source_ref, vref=view_ref:
            self._show_menu_refs(vref, sref, point))
        source.destroyed.connect(
            lambda *_args, source_id=id(source): self._sources.pop(
                source_id, None))

    def _show_menu_refs(self, view_ref, source_ref, point):
        view = view_ref()
        source = source_ref()
        if view is not None and source is not None:
            self._show_column_menu(view, source, point)

    def _describe(self, view):
        description = view.accessibleDescription().strip()
        if self.INSTRUCTIONS not in description:
            view.setAccessibleDescription(
                f"{description} {self.INSTRUCTIONS}".strip())
        header = view.horizontalHeader()
        name = view.accessibleName().strip() or "this table"
        if not header.accessibleName().strip():
            header.setAccessibleName(f"Resizable columns for {name}")
        header.setAccessibleDescription(self.INSTRUCTIONS)
        header.setToolTip(
            "Drag a divider to resize · double-click to auto-fit · "
            "Shift+F10 for keyboard controls")

    def _menu_column(self, view, source, point):
        header = view.horizontalHeader()
        column = -1
        if source is header and point.x() >= 0:
            column = header.logicalIndexAt(point)
        elif source is view.viewport() and point.x() >= 0:
            column = view.columnAt(point.x())
        index = view.currentIndex()
        if column < 0 and index.isValid():
            column = index.column()
        return max(0, min(header.count() - 1, column if column >= 0 else 0))

    @staticmethod
    def _heading(view, column):
        model = view.model()
        heading = model.headerData(
            column, Qt.Orientation.Horizontal,
            Qt.ItemDataRole.DisplayRole) if model is not None else ""
        return str(heading or f"Column {column + 1}")

    def _show_column_menu(self, view, source, point):
        try:
            column = self._menu_column(view, source, point)
            heading = self._heading(view, column)
        except RuntimeError:
            return
        menu = QMenu(view)
        menu.setAccessibleName(f"{heading} column width controls")
        menu.setToolTipsVisible(True)
        wider = menu.addAction(f"Widen {heading}")
        wider.setToolTip(f"Increase the {heading} column by {self.WIDTH_STEP} pixels")
        wider.triggered.connect(
            lambda: self._change_width(view, column, self.WIDTH_STEP))
        narrower = menu.addAction(f"Narrow {heading}")
        narrower.setToolTip(f"Decrease the {heading} column by {self.WIDTH_STEP} pixels")
        narrower.triggered.connect(
            lambda: self._change_width(view, column, -self.WIDTH_STEP))
        auto_fit = menu.addAction(f"Auto-fit {heading}")
        auto_fit.setToolTip(f"Fit the {heading} column to its visible content")
        auto_fit.triggered.connect(lambda: self._auto_fit(view, column))
        menu.addSeparator()
        reset = menu.addAction("Reset this table's columns")
        reset.setToolTip("Restore the authored column widths for this table")
        reset.triggered.connect(lambda: self.reset_view(view))

        index = view.currentIndex()
        if point.x() < 0 or point.y() < 0:
            cell = view.visualRect(index) if index.isValid() else view.rect()
            global_point = view.viewport().mapToGlobal(cell.bottomLeft())
        else:
            global_point = source.mapToGlobal(point)
        self._open_menus.append(menu)

        def close_menu():
            try:
                view.setFocus(Qt.FocusReason.OtherFocusReason)
            except RuntimeError:
                pass
            if menu in self._open_menus:
                self._open_menus.remove(menu)
            menu.deleteLater()

        menu.aboutToHide.connect(close_menu)
        menu.popup(global_point)

    def _change_width(self, view, column, delta):
        width = max(self.MIN_WIDTH, min(
            self.MAX_WIDTH, view.columnWidth(column) + int(delta)))
        view.setColumnWidth(column, width)
        self._announce_width(view, column)

    def _auto_fit(self, view, column):
        view.resizeColumnToContents(column)
        width = max(self.MIN_WIDTH, min(
            self.MAX_WIDTH, view.columnWidth(column)))
        view.setColumnWidth(column, width)
        view.horizontalHeader().setSectionResizeMode(
            column, QHeaderView.ResizeMode.Interactive)
        self._announce_width(view, column)

    def _announce_width(self, view, column):
        message = (
            f"{self._heading(view, column)} column width "
            f"{view.columnWidth(column)} pixels")
        view.setAccessibleDescription(f"{self.INSTRUCTIONS} {message}.")
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(view, message))
        except RuntimeError:
            pass

    def _column_resized(self, reference):
        view = reference()
        if view is None:
            return
        try:
            header = view.horizontalHeader()
            if id(header) in self._applying:
                return
            key = self._column_key(view)
            widths = [max(self.MIN_WIDTH, min(
                self.MAX_WIDTH, int(width))) for width in self._widths(view)]
        except RuntimeError:
            return
        storage = self._storage()
        storage[key] = widths
        if len(storage) > self.MAX_TABLES:
            for stale in list(storage)[:-self.MAX_TABLES]:
                storage.pop(stale, None)
        self._save_timer.start()

    def _save(self):
        if getattr(config, "_filename", ""):
            config.save()

    def flush(self):
        """Commit a pending width change before an update or normal exit."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()

    def reset_view(self, view):
        key = self._column_key(view)
        defaults = self._defaults.get(key)
        if not defaults or len(defaults) != view.model().columnCount():
            return False
        self._storage().pop(key, None)
        header = view.horizontalHeader()
        self._applying.add(id(header))
        try:
            for column, width in enumerate(defaults):
                view.setColumnWidth(column, width)
        finally:
            self._applying.discard(id(header))
        self._save_timer.start()
        self._announce_width(view, max(0, view.currentIndex().column()))
        return True

    def capture_current_as_defaults(self, views):
        """Replace migrated custom defaults after legacy reset code runs."""
        for view in views:
            try:
                self._defaults[self._column_key(view)] = self._widths(view)
            except RuntimeError:
                continue

    def apply_saved(self):
        """Apply a reset/rollback snapshot to every currently live table."""
        storage = self._storage()
        for key, reference in list(self._views.items()):
            view = reference()
            if view is None:
                self._views.pop(key, None)
                continue
            widths = storage.get(key, self._defaults.get(key, []))
            if len(widths) != view.model().columnCount():
                continue
            header = view.horizontalHeader()
            self._applying.add(id(header))
            try:
                for column, width in enumerate(widths):
                    view.setColumnWidth(column, int(width))
            finally:
                self._applying.discard(id(header))


def polish_form(layout: QFormLayout) -> QFormLayout:
    """Make a form stack its label above the field when width is constrained."""
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.setFieldGrowthPolicy(
        QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    layout.setLabelAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    layout.setHorizontalSpacing(5)
    layout.setVerticalSpacing(4)
    return layout


def scrollable(widget: QWidget, object_name="ResponsiveScroll") -> QScrollArea:
    """Wrap a page without imposing its desktop size hint on the window."""
    area = QScrollArea()
    area.setObjectName(object_name)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.viewport().setProperty("ResponsiveViewport", True)
    widget.setProperty("ResponsivePage", True)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    area.setWidget(widget)
    return area


class ResponsiveActionBar(QWidget):
    """Reflow actions into extra rows instead of clipping them."""

    def __init__(self, min_cell_width=112, spacing=3, parent=None):
        super().__init__(parent)
        self._min_cell_width = max(20, int(min_cell_width))
        self._widgets = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)
        # Accept the width offered by the logical design surface.  Individual
        # actions keep their compact size, while the bar can still arrange
        # them horizontally before the whole surface is uniformly scaled.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def addWidget(self, widget):
        explicitly_hidden = (
            widget.testAttribute(
                Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
            and widget.isHidden())
        self._widgets.append(widget)
        widget.installEventFilter(self)
        # Start in one column so the layout never establishes a wide minimum
        # before the first real resize determines how many columns fit.
        self._grid.addWidget(widget, len(self._widgets) - 1, 0)
        if not explicitly_hidden:
            widget.show()
        QTimer.singleShot(0, self._safe_reflow)
        return widget

    def widgets(self):
        return tuple(self._widgets)

    def eventFilter(self, watched, event):
        if watched in self._widgets and event.type() in (
                QEvent.Type.Show, QEvent.Type.Hide,
                QEvent.Type.LayoutRequest, QEvent.Type.EnabledChange):
            QTimer.singleShot(0, self._safe_reflow)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _safe_reflow(self):
        """Ignore a queued reflow after its dialog or child controls closed."""
        try:
            self._reflow()
        except RuntimeError:
            # Rapid audit/user closes can delete the C++ widget before a
            # zero-delay layout callback runs. There is nothing left to lay out.
            return

    def _reflow(self):
        visible = [widget for widget in self._widgets if not widget.isHidden()]
        if not visible:
            self._columns = 0
            return
        available = max(self._min_cell_width, self.contentsRect().width())
        columns = max(1, min(len(visible), available // self._min_cell_width))
        if columns == self._columns and all(
                self._grid.indexOf(widget) >= 0 for widget in visible):
            return
        self._columns = columns
        for widget in self._widgets:
            self._grid.removeWidget(widget)
        for index, widget in enumerate(visible):
            row, column = divmod(index, columns)
            self._grid.addWidget(widget, row, column)
        for column in range(columns):
            self._grid.setColumnStretch(column, 0)
        rows = (len(visible) + columns - 1) // columns
        row_heights = []
        for row in range(rows):
            row_widgets = visible[row * columns:(row + 1) * columns]
            row_heights.append(max(
                widget.minimumSizeHint().height() for widget in row_widgets))
        margins = self._grid.contentsMargins()
        required_height = (
            margins.top() + margins.bottom() + sum(row_heights) +
            max(0, rows - 1) * self._grid.verticalSpacing())
        if self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)
            self.updateGeometry()
