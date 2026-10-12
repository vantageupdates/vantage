"""Direct Quick Bar access to the existing shared boat schedule controller."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget)

from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow


class BoatSchedules(ParserWindow):
    """Own the boat surface, without another client or another arrival clock."""

    name = "boats"
    _allow_clickthrough = False

    def __init__(self, spells):
        super().__init__()
        self._spells = spells
        self.setWindowTitle("Boat Schedules")
        self._title.setText("Boat Schedules")
        self.setAccessibleName("Boat Schedules")

        # Transfer the original rows rather than cloning their snapshots. A
        # second view built from remaining_seconds would restart its ETA on
        # every refresh and could disagree with local log observations.
        self.group = spells._boat_group
        container = spells._spell_container
        container._layout.removeWidget(self.group)
        container._boat_group = None
        container._sync_empty_state()
        spells._boat_window = self
        self.group.header.hide()  # The shared window header is the title now.

        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(7, 5, 7, 7)
        layout.setSpacing(5)
        controls = QHBoxLayout()
        self.monitoring_toggle = QCheckBox("Live schedules")
        self.monitoring_toggle.setAccessibleName("Enable live boat schedules")
        self.monitoring_toggle.setToolTip(
            "Refresh boat estimates every minute, including while this window is hidden")
        self.monitoring_toggle.setChecked(spells._boat_toggle.isChecked())
        self.monitoring_toggle.toggled.connect(self._set_monitoring)
        spells._boat_toggle.toggled.connect(self._reflect_monitoring)
        controls.addWidget(self.monitoring_toggle)
        controls.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(game_icon("refresh"))
        self.refresh_button.setAccessibleName("Refresh boat schedules")
        self.refresh_button.setToolTip("Check for new arrivals for the selected server")
        self.refresh_button.clicked.connect(spells._manual_refresh_boats)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

        self.instructions = QLabel(
            "Choose Green or Blue. At the dock, use Sync arrival to share "
            "a boat you actually see arrive.")
        self.instructions.setObjectName("BoatScheduleStatus")
        self.instructions.setTextFormat(Qt.TextFormat.PlainText)
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("BoatScheduleScroll")
        self.scroll_area.viewport().setObjectName("BoatScheduleViewport")
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setAccessibleName("Boat arrival estimates")
        body = QWidget()
        body.setObjectName("BoatScheduleBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.group)
        body_layout.addStretch(1)
        self.scroll_area.setWidget(body)
        layout.addWidget(self.scroll_area, 1)
        self.paused_notice = QLabel(
            "Live schedules are off. Turn them on or press Refresh to resume.")
        self.paused_notice.setObjectName("BoatScheduleStatus")
        self.paused_notice.setWordWrap(True)
        layout.addWidget(self.paused_notice)
        self.paused_notice.setVisible(not self.monitoring_toggle.isChecked())
        self.content.addWidget(panel, 1)
        QWidget.setTabOrder(self.monitoring_toggle, self.refresh_button)
        QWidget.setTabOrder(self.refresh_button, self.group.server_selector)
        QWidget.setTabOrder(self.group.server_selector, self.group.sync_button)

    def _reflect_monitoring(self, checked):
        with QSignalBlocker(self.monitoring_toggle):
            self.monitoring_toggle.setChecked(bool(checked))
        self.paused_notice.setVisible(not checked)

    def _set_monitoring(self, checked):
        self._spells._boat_toggle.setChecked(bool(checked))
        self._spells._toggle_boat_schedules(bool(checked))

    def showEvent(self, event):
        super().showEvent(event)
        self.group._tick()

    def toggle(self):
        # Opening this tool is enough to start it: users do not have to find
        # the old Buffs switch first. Re-showing a window while changing its
        # frame or Always on Top is not an intentional open and must respect
        # Live schedules Off. Hiding/rolling it never disables updates.
        if not self.isVisible() and not self._spells._boat_toggle.isChecked():
            self._set_monitoring(True)
        super().toggle()

    def parse(self, timestamp, text):
        # Spells consumes boat observations once, using the active character
        # and server. This view participates in the common parser dispatcher
        # but must not process the same line or create another controller.
        pass
