"""Explicit, minimal public boat-arrival reporting; no log auto-upload."""
import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.boats import BOAT_ROUTES
from vantage.helpers.scaled_dialog import UniformScaleDialog


class BoatArrivalDialog(UniformScaleDialog):
    def __init__(self, client, parent=None, *, active_server='',
                 viewed_server='Green', reporter='', route_key=None,
                 active_server_provider=None):
        super().__init__(QSize(480, 450), parent)
        self.setWindowTitle('Sync a boat arrival')
        self.setAccessibleName('Share a P99 boat arrival')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.client = client
        self._active_server_provider = active_server_provider
        self._context_server = active_server
        self._submitted_server = ''
        self._submitted_reporter = ''
        self._unsupported_server = bool(
            active_server and active_server not in ('Green', 'Blue'))
        outer = QVBoxLayout(self.scaled_surface)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)
        self.body_scroll = QScrollArea()
        self.body_scroll.setObjectName('BoatArrivalScroll')
        self.body_scroll.viewport().setObjectName('BoatArrivalViewport')
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_scroll.setAccessibleName('Boat arrival details and confirmation')
        body = QWidget()
        body.setObjectName('BoatArrivalBody')
        layout = QVBoxLayout(body)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.body_scroll.setWidget(body)
        outer.addWidget(self.body_scroll, 1)
        title = QLabel('Boat arrived? Share the time.')
        title.setObjectName('SectionTitle')
        layout.addWidget(title)
        instructions = QLabel(
            'Press Sync only when the boat reaches the selected arrival point. '
            'Do not report a future NPC announcement or an unrelated shuttle. '
            'Reports update estimates for this server, not exact guarantees.')
        instructions.setWordWrap(True)
        instructions.setAccessibleName('Boat arrival reporting instructions')
        layout.addWidget(instructions)
        form = QFormLayout()
        form.setSpacing(10)
        self.server = QComboBox()
        self.server.addItems(['Green', 'Blue'])
        self.server.setCurrentText(
            active_server if active_server in ('Green', 'Blue') else viewed_server)
        self.server.setEnabled(active_server not in ('Green', 'Blue'))
        self.server.setAccessibleName('Server receiving the boat report')
        self.server.setToolTip(
            'Reports use the active character server, independently of the '
            'server you are viewing. If unknown, choose the actual server.')
        form.addRow('Server', self.server)
        self.dock = QComboBox()
        for route in BOAT_ROUTES:
            self.dock.addItem(
                route.pretty_name,
                (route.boat_id, route.start_point))
        if route_key:
            index = next((i for i in range(self.dock.count())
                          if self.dock.itemData(i) == route_key), -1)
            if index >= 0:
                self.dock.setCurrentIndex(index)
        self.dock.setAccessibleName('Boat and arrival point')
        self.dock.setToolTip('Choose the exact arrival point you can see now')
        form.addRow('Arrival point', self.dock)
        self.reporter = QLineEdit(str(reporter or '')[:48])
        self.reporter.setMaxLength(48)
        self.reporter.setPlaceholderText('Character name or nickname')
        self.reporter.setAccessibleName('Public boat reporter name')
        self.reporter.setToolTip(
            'This name is public and self-reported, not verified character ownership')
        form.addRow('Reported by', self.reporter)
        layout.addLayout(form)
        privacy = QLabel(
            'Only the boat, arrival point, server, time and this public name '
            'are shared. No logs, buffs, account or character settings are uploaded.')
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        self.confirm = QCheckBox('Publish this arrival and my public name.')
        self.confirm.setToolTip('Confirm that the boat has just arrived at the selected point')
        self.confirm.setAccessibleName('Confirm the visible boat arrival and public report')
        layout.addWidget(self.confirm)
        self.status = QLabel(
            'Only Green and Blue reports are supported.' if self._unsupported_server else
            ('Reporting for your active character; the viewed server may differ.'
             if active_server in ('Green', 'Blue') else
             'Choose the actual server you are playing on before reporting.'))
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setAccessibleName('Boat arrival report status')
        layout.addWidget(self.status)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.submit = QPushButton('Boat arrived · Sync')
        self.submit.setObjectName('PrimaryAction')
        self.submit.setAccessibleName('Publish the confirmed boat arrival')
        self.submit.setToolTip('Publish this arrival now; offline reports are not queued')
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        self.close_button.setToolTip('Close this report window')
        buttons.addWidget(self.submit, 1)
        buttons.addWidget(self.close_button)
        outer.addLayout(buttons)
        self.confirm.toggled.connect(self._validate)
        self.reporter.textChanged.connect(self._validate)
        self.submit.clicked.connect(self._send)
        client.busy_changed.connect(self._validate)
        client.report_finished.connect(self._completed)
        for first, second in zip(
                (self.server, self.dock, self.reporter, self.confirm, self.submit),
                (self.dock, self.reporter, self.confirm, self.submit, self.close_button)):
            QWidget.setTabOrder(first, second)
        self._validate()

    def _validate(self, *_):
        name = self.reporter.text().strip()
        valid = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9 '_-]{0,47}", name))
        self.submit.setEnabled(
            valid and self.confirm.isChecked() and not self._unsupported_server
            and not self.client.is_reporting)
        self.submit.setText(
            'Sharing arrival…' if self.client.is_reporting else 'Boat arrived · Sync')

    def _send(self):
        if not self.submit.isEnabled():
            return
        if self._active_server_provider is not None:
            active_server = self._active_server_provider()
            if active_server != self._context_server:
                self._context_server = active_server
                self._unsupported_server = bool(
                    active_server and active_server not in ('Green', 'Blue'))
                if active_server in ('Green', 'Blue'):
                    self.server.setCurrentText(active_server)
                self.server.setEnabled(active_server not in ('Green', 'Blue'))
                self.confirm.setChecked(False)
                self.status.setText(
                    'Only Green and Blue reports are supported.'
                    if self._unsupported_server else
                    'Active server changed. Check the server and arrival point, then confirm again.')
                self._validate()
                return
        boat, start_point = self.dock.currentData()
        self._submitted_server = self.server.currentText()
        self._submitted_reporter = self.reporter.text().strip()
        self.status.setText('Sharing this arrival…')
        started = self.client.report_arrival(
            self._submitted_server, boat, start_point, self._submitted_reporter)
        if not started:
            self.status.setText('Could not start the report. Check your connection and try again.')
            self.confirm.setChecked(False)
        self._validate()

    def _completed(self, server, accepted, message):
        if server != self._submitted_server:
            return
        self.status.setText(message)
        self.confirm.setChecked(False)
        if accepted:
            config.data['spells']['boat_reporter'] = self._submitted_reporter
            config.save()
        self._validate()
        QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self.status, message))
