"""Small native layout helpers for resizable Vantage surfaces."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout, QGridLayout, QLayout, QScrollArea, QSizePolicy,
    QTableWidget, QTabWidget, QToolButton, QWidget)


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
        QTimer.singleShot(0, self._reflow)
        return widget

    def widgets(self):
        return tuple(self._widgets)

    def eventFilter(self, watched, event):
        if watched in self._widgets and event.type() in (
                QEvent.Type.Show, QEvent.Type.Hide,
                QEvent.Type.LayoutRequest, QEvent.Type.EnabledChange):
            QTimer.singleShot(0, self._reflow)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

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
