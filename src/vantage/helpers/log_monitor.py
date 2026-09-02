"""Compact per-character EverQuest log activity monitor."""

from PySide6.QtCore import QSize, QTimer
from PySide6.QtWidgets import (
    QComboBox, QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout)
from vantage.helpers import config
from vantage.helpers.audio import (
    profile_audio_settings, save_profile_audio_settings, speak_text,
    speech_voice_names)
from vantage.helpers.scaled_dialog import UniformScaleDialog


class LogMonitorDialog(UniformScaleDialog):
    def __init__(self, app, parent=None):
        super().__init__(
            QSize(920, 260), parent, minimum_size=QSize(276, 78),
            initial_size=QSize(736, 208))
        self._app = app
        self._voices = speech_voice_names()
        self.setWindowTitle('Vantage · Log Profiles')
        layout = QVBoxLayout(self.scaled_surface)
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
        close = QPushButton('Close')
        close.setToolTip('Close this monitor; log parsing continues in the tray')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    def refresh(self):
        reader = getattr(self._app, '_log_reader', None)
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
            voice.addItem('System default', '')
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
                (save(), speak_text(
                    f'Vantage voice test for {character}',
                    config.data['spells']['fade_sound_volume'], True,
                    source=f'Test · {character} · speech',
                    character=character, server=server)))
