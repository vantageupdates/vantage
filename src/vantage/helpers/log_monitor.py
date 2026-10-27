"""Compact per-character EverQuest log activity monitor."""

import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout)
from vantage.helpers import config
from vantage.helpers.audio import (
    audio_preflight, profile_audio_settings, save_profile_audio_settings,
    speak_text, speech_voice_names, vantage_command_voice_label)
from vantage.helpers.scaled_dialog import UniformScaleDialog


class LogMonitorDialog(UniformScaleDialog):
    def __init__(self, app, parent=None):
        super().__init__(
            QSize(920, 360), parent, minimum_size=QSize(276, 108),
            initial_size=QSize(736, 288))
        self._app = app
        self._voices = speech_voice_names()
        self.setWindowTitle('Vantage · Log Profiles')
        layout = QVBoxLayout(self.scaled_surface)
        self.health_status = QLabel()
        self.health_status.setObjectName('SettingsSectionTitle')
        self.health_status.setTextFormat(Qt.TextFormat.PlainText)
        self.health_status.setWordWrap(True)
        self.health_status.setAccessibleName('Log monitoring health')
        layout.addWidget(self.health_status)
        self.health_detail = QLabel()
        self.health_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.health_detail.setWordWrap(True)
        self.health_detail.setAccessibleName('Log delivery and processing status')
        layout.addWidget(self.health_detail)
        note = QLabel(
            'ACTIVE means this log changed within 90 seconds · QUIET and STALE '
            'do not prove the game is closed.')
        note.setObjectName('CombatDataNotice')
        note.setWordWrap(True)
        note.setToolTip(
            'Vantage reads log-file timestamps only and never inspects game memory')
        layout.addWidget(note)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels((
            'Character', 'Server', 'State', 'Last event',
            'Voice', 'Speed', 'Volume', 'Test', 'Log file'))
        header_tips = (
            'Character parsed from the eqlog file name',
            'EverQuest server parsed from the eqlog file name',
            'ACTIVE, QUIET, or STALE based on recent file activity',
            'Most recent write time observed for this log',
            'Windows text-to-speech voice used for this character',
            'Independent speech speed for this character from -10 to +10',
            'Independent trigger sound and speech volume for this character',
            'Speak a short sample using this character profile',
            'Exact linked EverQuest log file')
        for column, tooltip in enumerate(header_tips):
            self.table.horizontalHeaderItem(column).setToolTip(tooltip)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setToolTip(
            'Every discovered eqlog character/server file with its independent activity state')
        self.table.setAccessibleName('EverQuest log profile activity')
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            7, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(7, 52)
        self.table.horizontalHeader().setSectionResizeMode(
            8, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.test_status = QLabel()
        self.test_status.setObjectName('TriggerTestStatus')
        self.test_status.setWordWrap(True)
        self.test_status.hide()
        layout.addWidget(self.test_status)
        self.copy_diagnostics = QPushButton('Copy diagnostics')
        self.copy_diagnostics.setToolTip(
            'Copy log monitoring, delivery and feature error details. '
            'Conversation text and credentials are not included.')
        self.copy_diagnostics.clicked.connect(self._copy_diagnostics)
        layout.addWidget(self.copy_diagnostics)
        close = QPushButton('Close')
        close.setToolTip('Close this monitor; log parsing continues in the tray')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(
            lambda: self.refresh() if self.isVisible() else None)
        self._refresh_timer.start()
        self.refresh()

    def refresh(self):
        reader = getattr(self._app, '_log_reader', None)
        self._refresh_health(reader)
        profiles = reader.profiles() if reader else []
        profile_ids = tuple(
            (profile['character'].casefold(), profile['server'].casefold())
            for profile in profiles)
        if profile_ids == getattr(self, '_profile_ids', None):
            for row, profile in enumerate(profiles):
                values = (
                    profile['character'], profile['server'], profile['status'],
                    profile['last_write'])
                for column, value in enumerate(values):
                    item = self.table.item(row, column)
                    if item:
                        item.setText(str(value))
                        item.setToolTip(
                            f"{profile['status']} · {profile['size']:,} bytes · "
                            f"{profile['file']}")
                file_item = self.table.item(row, 8)
                if file_item:
                    file_item.setText(str(profile['file']))
                    file_item.setToolTip(str(profile['file']))
            return
        self._profile_ids = profile_ids
        self.table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            values = (
                profile['character'], profile['server'], profile['status'],
                profile['last_write'])
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(
                    f"{profile['status']} · {profile['size']:,} bytes · "
                    f"{profile['file']}")
                self.table.setItem(row, column, item)
            settings = profile_audio_settings(
                profile['character'], profile['server'])
            voice = QComboBox()
            voice.addItem(vantage_command_voice_label(), '')
            for name in self._voices:
                voice.addItem(name, name)
            selected = voice.findData(settings['voice_name'])
            if selected < 0 and settings['voice_name']:
                voice.addItem(
                    f"Unavailable · {settings['voice_name']}",
                    settings['voice_name'])
                selected = voice.count() - 1
            voice.setCurrentIndex(max(0, selected))
            voice.setAccessibleName(
                f"Speech voice for {profile['character']} on {profile['server']}")
            voice.setToolTip(
                'Choose the installed Windows voice used by text-to-speech '
                'triggers for this character')
            speed = QSpinBox()
            speed.setRange(-10, 10)
            speed.setValue(settings['voice_speed'])
            speed.setPrefix('+' if speed.value() > 0 else '')
            speed.setAccessibleName(
                f"Speech speed for {profile['character']} on {profile['server']}")
            speed.setToolTip(
                'Character voice speed: -10 is slowest, '
                '0 is normal, and +10 is fastest')
            speed.valueChanged.connect(
                lambda value, widget=speed: widget.setPrefix(
                    '+' if value > 0 else ''))
            volume = QSpinBox()
            volume.setRange(0, 100)
            volume.setSuffix(' %')
            volume.setValue(settings['volume'])
            volume.setAccessibleName(
                f"Trigger volume for {profile['character']} on {profile['server']}")
            volume.setToolTip(
                'Character-level trigger volume multiplied by the master '
                'trigger volume; 0 silences this profile only')
            self.table.setCellWidget(row, 4, voice)
            self.table.setCellWidget(row, 5, speed)
            self.table.setCellWidget(row, 6, volume)
            test = QPushButton('Play')
            test.setAccessibleName(
                f"Test speech for {profile['character']} on {profile['server']}")
            test.setToolTip(
                'Save these profile controls and speak a short sample now')
            self.table.setCellWidget(row, 7, test)
            file_item = QTableWidgetItem(str(profile['file']))
            file_item.setToolTip(str(profile['file']))
            self.table.setItem(row, 8, file_item)
            save = lambda _value=None, character=profile['character'], \
                    server=profile['server'], voice=voice, speed=speed, \
                    volume=volume: save_profile_audio_settings(
                        character, server, voice.currentData(), speed.value(),
                        volume.value())
            voice.currentIndexChanged.connect(save)
            speed.editingFinished.connect(save)
            volume.editingFinished.connect(save)
            test.clicked.connect(
                lambda _checked=False, save=save,
                character=profile['character'], server=profile['server']:
                (save(), self._test_profile(character, server)))

    def _refresh_health(self, reader):
        read_health = getattr(reader, 'health_snapshot', None)
        read_dispatch = getattr(self._app, 'log_dispatch_health', None)
        reader_state = read_health() if callable(read_health) else {}
        dispatch = read_dispatch() if callable(read_dispatch) else {}
        reader_errors = reader_state.get('active_errors') or []
        feature_errors = dispatch.get('active_errors') or []
        stopped = reader is None or reader_state.get('stopped', False)
        pending = int(reader_state.get('pending_bytes') or 0)
        last_event = float(reader_state.get('last_delivered_at') or 0)
        age = max(0, int(time.time() - last_event)) if last_event else None
        if stopped:
            status = 'Monitoring stopped · Connect Logs to resume'
        elif reader_errors:
            status = 'Log file unavailable · Vantage is retrying automatically'
        elif feature_errors:
            status = 'A feature reported an error · other features keep receiving logs'
        elif pending:
            status = 'Reading pending log events'
        elif age is None:
            status = 'Monitoring · waiting for the next EverQuest event'
        elif age > 90:
            status = 'Monitoring · EverQuest has not written a new event recently'
        else:
            status = 'Monitoring · log events are reaching Vantage'
        delivered = int(reader_state.get('events_delivered') or 0)
        completed = int(dispatch.get('events_completed') or 0)
        last_text = f'{age}s ago' if age is not None else 'none this session'
        detail = (
            f'Lines read: {delivered:,} · Events processed: {completed:,} · '
            f'Last line: {last_text}')
        if pending:
            detail += f' · Waiting: {pending:,} bytes'
        if feature_errors:
            names = ', '.join(str(item.get('component') or 'Unknown')
                              for item in feature_errors[:4])
            detail += f'\nNeeds attention: {names}'
        self.health_status.setText(status)
        self.health_status.setAccessibleDescription(status)
        self.health_detail.setText(detail)
        self.health_detail.setAccessibleDescription(detail)
        self.health_detail.setToolTip(detail)
        self._diagnostic_text = '\n'.join((
            'Vantage log monitoring', status, detail,
            f"Linked folder: {reader_state.get('folder') or 'Unavailable'}",
            f"Watched files: {reader_state.get('watched_files', 0)} / "
            f"{reader_state.get('known_files', 0)}",
            f"Automatic repairs: {reader_state.get('repair_count', 0)}",
            f"Events with errors: {dispatch.get('events_with_errors', 0)}",
            *[f"Feature: {item.get('component', 'Unknown')} · "
              f"{item.get('error_type', 'Error')} · "
              f"count {item.get('count', 0)}" for item in feature_errors],
            *[f"Log file: {item.get('file', '')} · "
              f"{item.get('error', 'Unavailable')}" for item in reader_errors],
        ))

    def _copy_diagnostics(self):
        self._refresh_health(getattr(self._app, '_log_reader', None))
        QApplication.clipboard().setText(self._diagnostic_text)
        self.copy_diagnostics.setText('Diagnostics copied')

    def _test_profile(self, character, server):
        """Explicit previews bypass hidden-window gating, not mute or volume."""
        text = f'Vantage voice test for {character}'
        volume = config.data['spells']['fade_sound_volume']
        check = audio_preflight(
            'voice', text=text, volume=volume, character=character,
            server=server, channel='spells', allow_hidden=True)
        if not check.ready:
            message = f'{character} voice test: {check.reason}'
        else:
            played = speak_text(
                text, volume, source=f'Test · {character} · speech',
                character=character, server=server, channel='spells',
                allow_hidden=True)
            message = (f'{character} voice test: voice queued' if played else
                       f'{character} voice test: Windows voice unavailable')
        self.test_status.setText(message)
        self.test_status.setAccessibleName(message)
        self.test_status.setAccessibleDescription('Latest character voice test result')
        self.test_status.show()
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.test_status, message))
        except (AttributeError, RuntimeError, TypeError):
            pass
        return message
