import csv
import functools
import re

from PySide6.QtCore import Qt, QObject, QSize, Signal, QStringListModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFormLayout, QFrame,
                             QHeaderView, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QInputDialog,
                             QSpinBox, QStackedWidget, QPushButton,
                             QSplitter, QTableWidget, QTableWidgetItem,
                             QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem,
                             QTreeWidgetItemIterator, QVBoxLayout,
                             QWidget, QComboBox, QLineEdit,
                             QMessageBox, QColorDialog, QApplication, QFileDialog,
                             QCompleter)

from vantage.helpers import config, text_time_to_seconds
from vantage.helpers.audio import (
    DEFAULT_SOUND, add_custom_sound_to_combo, play_alert,
    set_sound_combo_value, speak_text)
from vantage.helpers.icons import game_icon
from vantage.helpers.friends_manager import FriendsManagerDialog
from vantage.helpers.gina_import import GinaImportError, import_gina_package
from vantage.helpers.portable import store_portable_file
from vantage.helpers.quickbar_items import QUICKBAR_ITEMS
from vantage.helpers.responsive import (
    ResponsiveActionBar, ensure_tab_tooltips, polish_form, scrollable)
from vantage.helpers.respawn_catalog import RESPAWN_CATALOG
from vantage.helpers.scaled_dialog import UniformScaleDialog
from vantage.helpers.trigger_groups import (
    group_ancestors, group_state, group_style, normalize_group_path,
    normalize_trigger_color, normalize_trigger_groups, set_group_enabled,
    set_group_style)
from vantage.parsers.spells import CustomTrigger

class SettingsSignals(QObject):
    config_updated = Signal()
    spell_triggers_updated = Signal()

    def __init__(self):
        super().__init__()

WHATS_THIS_CASTING_WINDOW = """The Casting Window is a range of time in which the spell you are casting will land.
Vantage limits parsing successful casts for the spell to only within that window. This disables Vantage from using other players'
successful casts as yours.  It will also enable the ability to parse Group, Bard, and AOE spells.  The size of the buffer
window is equal to (2 x casting_window_buffer) + 1 msec.
""".replace('\n', ' ')

WHATS_THIS_CASTING_BUFFER = """The Casting Window Buffer will widen the Casting Window to accept successful casts.
If you are laggy or group spells are not parsing all successful targets, you may need to widen this.  On the other hand,
if you are getting too much interference from other's successful casts, you may want to lessen the buffer.
""".replace('\n', ' ')

WHATS_THIS_PVP_DURATION = """Within spells_us.txt, there are secondary timers that, from my limited testing, seem to be
the duration of debuffs when you cast on yourself.  Are these timers that coincide with PVP?  I don't know, I don't play
on Red.  Using the 'PvP Duration' will use the secondary timers for non beneficiary spells and will use the primary
durations for all good buffs.
""".replace('\n', ' ')

WHATS_THIS_ITEM_TRIGGERS = """Tracks P99 item clicks by correlating your item's glow line with the spell landing. Instant
item-only self effects are recognized from spells_us when no casting line exists. The timer shows the effect name and its
tooltip identifies the item source when the log provides it.
""".replace('\n', ' ')

WHATS_THIS_SHARING = """Your location can be shared with others via a central location server. If you enable this, you
agree to send and receive location data via a third-party server. The only data other players can see is your character
name and the zone+loc you send. Nothing personally identifiable will be visible beyond this.
""".replace('\n', ' ')

WHATS_THIS_CLICKTHROUGH = """When set, the window will not capture mouse clicks, so your click will go through to
whatever is below it. Practically, this means you can still interact with EverQuest *through* the Vantage
window.""".replace('\n', ' ')


class InheritedColorPicker(QWidget):
    """Compact color picker with an explicit inheritance state."""

    def __init__(self, inherit_label, parent=None):
        super().__init__(parent)
        self._value = ''
        self._inherit_label = inherit_label
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.choose = QPushButton()
        self.choose.setToolTip('Choose a custom text color for this scope')
        self.choose.setAccessibleName('Choose text color')
        self.choose.clicked.connect(self._choose)
        layout.addWidget(self.choose, 1)
        self.clear = QPushButton('Inherit')
        self.clear.setToolTip(inherit_label)
        self.clear.setAccessibleName('Inherit text color')
        self.clear.clicked.connect(lambda: self.set_value(''))
        layout.addWidget(self.clear)
        self.set_value('')

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = normalize_trigger_color(value)
        if self._value:
            color = QColor(self._value)
            foreground = '#111318' if color.lightness() > 145 else '#F4EBD8'
            self.choose.setText(self._value)
            self.choose.setStyleSheet(
                f'background-color: {self._value}; color: {foreground};')
            self.clear.setEnabled(True)
        else:
            self.choose.setText('Inherited')
            self.choose.setStyleSheet('')
            self.clear.setEnabled(False)

    def _choose(self):
        initial = QColor(self._value or '#F2EAD8')
        color = QColorDialog.getColor(initial, self, 'Trigger text color')
        if color.isValid():
            self.set_value(color.name())


class GinaImportPreviewDialog(UniformScaleDialog):
    """Review and selectively commit data-only imported triggers."""

    def __init__(self, triggers, parent=None):
        super().__init__(
            QSize(820, 470), parent, minimum_size=QSize(246, 141),
            initial_size=QSize(656, 376))
        self.setWindowTitle('Vantage · Review Trigger Import')
        self._batch = triggers
        self._rows = []
        root = QVBoxLayout(self.scaled_surface)
        intro = QLabel(
            'Imported triggers start disabled. Packaged WAV sounds are held in '
            'memory and copied only for selected triggers; external executable '
            'content and outside audio paths are never loaded.')
        intro.setObjectName('TriggerTokenLegend')
        intro.setWordWrap(True)
        intro.setToolTip(
            'Cancel leaves no imported audio behind. External file paths are '
            'replaced with safe gallery sounds.')
        root.addWidget(intro)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ('Import', 'Name', 'Search text', 'Timer', 'Actions'))
        header_tips = (
            'Include or exclude this trigger from the import',
            'Imported trigger name', 'Log text or regular expression to match',
            'Imported countdown or stopwatch duration',
            'Safe actions retained from the imported trigger')
        for column, tooltip in enumerate(header_tips):
            self.table.horizontalHeaderItem(column).setToolTip(tooltip)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setToolTip(
            'Review every trigger and uncheck anything you do not want to import')
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        for trigger in triggers:
            row = self.table.rowCount()
            self.table.insertRow(row)
            include = QCheckBox()
            include.setChecked(True)
            include.setAccessibleName(f'Import {trigger.name}')
            include.setToolTip(f'Include or exclude {trigger.name}')
            check_host = QWidget()
            check_layout = QHBoxLayout(check_host)
            check_layout.setContentsMargins(5, 0, 5, 0)
            check_layout.addWidget(include, 0, Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(row, 0, check_host)
            timer = trigger.time if trigger.timer_type != 'none' else '—'
            actions = []
            if trigger.alert_text:
                actions.append('Text')
            if trigger.tts_text:
                actions.append('TTS')
            if trigger.sound_path:
                actions.append(
                    'Pack WAV' if (
                        hasattr(triggers, 'has_embedded_audio') and
                        triggers.has_embedded_audio(trigger))
                    else 'Gallery sound')
            if trigger.end_patterns:
                actions.append('Ender')
            if trigger.text_color:
                actions.append(trigger.text_color)
            for column, value in enumerate((
                    trigger.name, trigger.text, timer,
                    ' · '.join(actions) or 'Match only'), 1):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
            self._rows.append((include, trigger))
        root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        select_all = QPushButton('All')
        select_all.setToolTip('Select every imported trigger')
        select_all.clicked.connect(
            lambda: self._set_all(True))
        select_none = QPushButton('None')
        select_none.setToolTip('Clear every imported trigger selection')
        select_none.clicked.connect(
            lambda: self._set_all(False))
        cancel = QPushButton('Cancel')
        cancel.setToolTip('Close without importing anything')
        cancel.clicked.connect(self.reject)
        commit = QPushButton('Import selected')
        commit.setObjectName('PrimaryAction')
        commit.setToolTip('Add the checked triggers as disabled editable copies')
        commit.clicked.connect(self.accept)
        actions.addWidget(select_all)
        actions.addWidget(select_none)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(commit)
        root.addLayout(actions)

    def _set_all(self, checked):
        for checkbox, _trigger in self._rows:
            checkbox.setChecked(checked)

    def selected_triggers(self):
        return [trigger for checkbox, trigger in self._rows
                if checkbox.isChecked()]


class SettingsWindow(UniformScaleDialog):

    def __init__(self):
        super().__init__(
            QSize(720, 520), minimum_size=QSize(216, 156),
            initial_size=QSize(612, 442))
        self.setWindowTitle('Vantage · Settings')

        layout = QVBoxLayout()

        self._section_combo = QComboBox()
        self._section_combo.setAccessibleName('Settings section')
        self._section_combo.setToolTip(
            'Choose a settings section when the compact section selector is visible')
        self._section_combo.setVisible(False)
        self._section_combo.currentIndexChanged.connect(
            lambda index: self._list_widget.setCurrentRow(index))
        layout.addWidget(self._section_combo)

        top_layout = QHBoxLayout()
        self._list_widget = QListWidget()
        self._list_widget.setObjectName('SettingsList')
        self._list_widget.setAccessibleName('Settings section list')
        self._list_widget.setToolTip(
            'Choose General, Triggers, Maps, Timers, Combat, Market, Sharing, Quick Bar, or Appearance')
        self._list_widget.setIconSize(QSize(15, 15))
        self._list_widget.setSpacing(1)
        self._list_widget.setUniformItemSizes(True)
        self._list_widget.setMovement(QListWidget.Movement.Static)
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_widget.currentItemChanged.connect(self._switch_stack)
        self._widget_stack = QStackedWidget()
        self._widget_stack.setObjectName('SettingsStack')
        top_layout.addWidget(self._list_widget, 0)
        top_layout.addWidget(self._widget_stack, 1)
        self._color_dialogs = dict()

        settings = self._create_settings()
        if settings:
            section_icons = {
                'General': 'settings', 'Buffs & Triggers': 'spells', 'Maps': 'map',
                'Smart Timers': 'timer', 'Combat': 'combat',
                'Heal Chain': 'heal',
                'Market': 'market',
                'Sharing': 'spawn', 'Appearance': 'compact',
                'Quick Bar': 'compact',
            }
            for setting_name, stacked_widget in settings:
                item = QListWidgetItem(game_icon(
                    section_icons.get(setting_name, 'settings')), setting_name)
                item.setToolTip(f'Open the {setting_name} settings section')
                self._list_widget.addItem(item)
                self._section_combo.addItem(
                    game_icon(section_icons.get(setting_name, 'settings')),
                    setting_name)
                combo_index = self._section_combo.count() - 1
                self._section_combo.setItemData(
                    combo_index, f'Open the {setting_name} settings section',
                    Qt.ItemDataRole.ToolTipRole)
                page_layout = stacked_widget.layout()
                if isinstance(page_layout, QFormLayout):
                    polish_form(page_layout)
                self._widget_stack.addWidget(scrollable(
                    stacked_widget, 'SettingsPageScroll'))

            self._list_widget.setCurrentRow(0)
        self._list_widget.setMaximumWidth(
            self._list_widget.minimumSizeHint().width())

        self._list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        buttons = QWidget()
        buttons.setObjectName('SettingsButtons')
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        save_button = QPushButton('Save')
        save_button.setObjectName('PrimaryAction')
        save_button.setIcon(game_icon('spawn'))
        save_button.setAutoDefault(False)
        save_button.setAccessibleName('Save Vantage settings')
        save_button.setToolTip('Save every changed setting and close this window')
        save_button.clicked.connect(self._save)
        buttons_layout.addWidget(save_button)
        cancel_button = QPushButton('Cancel')
        cancel_button.setAutoDefault(False)
        cancel_button.setAccessibleName('Cancel Vantage settings')
        cancel_button.setToolTip('Discard unsaved changes and close this window')
        cancel_button.clicked.connect(self._cancelled)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.insertStretch(0)
        buttons.setLayout(buttons_layout)
        layout.addLayout(top_layout, 1)
        layout.addWidget(buttons, 0)

        self.scaled_surface.setLayout(layout)

        self._set_values()

    def _save(self):
        for stacked_widget in self._widget_stack.findChildren(QFrame):
            for widget in stacked_widget.children():
                wt = type(widget)
                if wt == QCheckBox:
                    key1, key2 = widget.objectName().split(':')
                    config.data[key1][key2] = widget.isChecked()
                elif wt == QSpinBox:
                    key1, key2 = widget.objectName().split(':')
                    config.data[key1][key2] = widget.value()
                elif wt == QLineEdit:
                    key1, key2 = widget.objectName().split(':')
                    config.data[key1][key2] = widget.text()
                elif wt == QComboBox and ':' in widget.objectName():
                    key1, key2 = widget.objectName().split(':')
                    config.data[key1][key2] = widget.currentData()
        for widget in self._color_dialogs.values():
            wt = type(widget)
            if wt == QColorDialog:
                key1, key2 = widget.objectName().split(':')
                hexcolor = hex(widget.currentColor().rgb()).replace('0xff', '#')
                config.data[key1][key2] = hexcolor
        config.save()
        QApplication.instance()._signals["settings"].config_updated.emit()
        self.accept()

    def _cancelled(self):
        self._set_values()
        self.reject()

    def closeEvent(self, _):
        self._set_values()
        self.reject()

    def _switch_stack(self):
        if self._list_widget.selectedIndexes():
            index = self._list_widget.currentRow()
            self._widget_stack.setCurrentIndex(index)
            self._section_combo.blockSignals(True)
            self._section_combo.setCurrentIndex(index)
            self._section_combo.blockSignals(False)

    def select_section(self, section_name):
        """Select a named page before the settings dialog is shown."""
        matches = self._list_widget.findItems(
            str(section_name), Qt.MatchFlag.MatchExactly)
        if matches:
            self._list_widget.setCurrentItem(matches[0])

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def _set_values(self):
        for stacked_widget in self._widget_stack.findChildren(QFrame):
            for widget in stacked_widget.children():
                wt = type(widget)
                if wt == QCheckBox:
                    key1, key2 = widget.objectName().split(':')
                    widget.setChecked(config.data[key1][key2])
                    if key1 == 'sharing' and key2 == 'player_name_override' \
                            and not config.data[key1][key2]:
                        self.sharing_player_name.setDisabled(True)
                elif wt == QSpinBox:
                    key1, key2 = widget.objectName().split(':')
                    widget.setValue(config.data[key1][key2])
                elif wt == QLineEdit:
                    key1, key2 = widget.objectName().split(':')
                    widget.setText(config.data[key1][key2])
                elif wt == QComboBox and ':' in widget.objectName():
                    key1, key2 = widget.objectName().split(':')
                    value = config.data[key1][key2]
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        set_sound_combo_value(widget, value)
                elif wt == QPushButton and widget.objectName():
                    # Using QPushButton as a poor-man's rectangle
                    key1, key2 = widget.objectName().split(':')
                    hexcolor = config.data[key1][key2]
                    widget.setStyleSheet(
                        "background-color: {0}; "
                        "border: 4px solid {0};".format(hexcolor))
        for widget in self._color_dialogs.values():
            wt = type(widget)
            if wt == QColorDialog:
                key1, key2 = widget.objectName().split(':')
                hexcolor = config.data[key1][key2]
                intcolor = int(hexcolor.replace('#', '0xff'), 16)
                widget.setCurrentColor(QColor(intcolor))

    def _create_settings(self):
        stacked_widgets = []

        # General Settings
        general_settings = QFrame()
        gsl = QFormLayout()
        gsl.addRow(SettingsHeader('GENERAL'))
        gsl.addRow(SettingsHeader('WINDOWS'))
        gsl_window_flush = QCheckBox()
        gsl_window_flush.setObjectName('general:window_flush')
        gsl.addRow('Align windows vertically', gsl_window_flush)
        startup_state = QLabel('Quick Bar only')
        startup_state.setAccessibleName(
            'Startup windows: Quick Bar only')
        startup_state.setToolTip(
            'The Quick Bar opens automatically; every other tool stays '
            'hidden until you select it')
        gsl.addRow('When Vantage starts', startup_state)
        reduce_motion = QCheckBox()
        reduce_motion.setObjectName('general:reduce_motion')
        reduce_motion.setToolTip(
            'Avoids flashing alerts while preserving color, text, and sound')
        gsl.addRow('Reduce motion and flashes', reduce_motion)
        update_check = QCheckBox()
        update_check.setObjectName('general:update_check')
        update_check.setToolTip(
            'Once per day, check the official vantageupdates/vantage GitHub '
            'Release; downloads and installation always require your click')
        gsl.addRow('Check for updates daily', update_check)

        gsl.addRow(SettingsHeader('LOG ARCHIVE'))
        log_archive_enabled = QCheckBox()
        log_archive_enabled.setObjectName('general:log_archive_enabled')
        log_archive_enabled.setToolTip(
            'Every hour, move oversized eqlog files into the archive folder '
            'inside the linked EverQuest Logs folder; disabled by default')
        gsl.addRow('Archive oversized EQ logs', log_archive_enabled)
        log_archive_size = QSpinBox()
        log_archive_size.setRange(1, 2048)
        log_archive_size.setSuffix(' MB')
        log_archive_size.setValue(100)
        log_archive_size.setObjectName('general:log_archive_size_mb')
        log_archive_size.setToolTip(
            'Archive an eqlog file after it reaches this size; the original '
            'content is moved, never deleted')
        gsl.addRow('Archive threshold', log_archive_size)
        archive_note = QLabel(
            'Opt-in · checked hourly · recoverable in EverQuest\\Logs\\archive')
        archive_note.setObjectName('CombatDataNotice')
        archive_note.setWordWrap(True)
        archive_note.setToolTip(
            'Only eqlog_*_*.txt files are considered; other text files are left alone')
        gsl.addRow('Storage', archive_note)

        gsl.addRow(SettingsHeader('EVERQUEST FILES'))
        manage_friends = QPushButton('Manage Friends')
        manage_friends.setIcon(game_icon('edit'))
        manage_friends.setAccessibleName('Manage EverQuest Friends files')
        manage_friends.setToolTip(
            'Merge, edit, and safely synchronize the [Friends] section across '
            'the selected server character INI files')
        manage_friends.clicked.connect(
            lambda: FriendsManagerDialog(self).exec())
        gsl.addRow('Character friends', manage_friends)

        gsl.addRow(SettingsHeader('OVERLAYS'))
        arrange_notifications = QPushButton('Arrange')
        arrange_notifications.setIcon(game_icon('cursor'))
        arrange_notifications.setAccessibleName(
            'Arrange notification overlays')
        arrange_notifications.setToolTip(
            'Show every overlay so each can be moved, resized, and locked')
        arrange_notifications.clicked.connect(
            QApplication.instance().arrange_notification_overlays)
        preview_notification = QPushButton('Preview')
        preview_notification.setIcon(game_icon('poi'))
        preview_notification.setToolTip(
            'Show a test alert in the saved Alerts overlay')
        preview_notification.clicked.connect(lambda: (
            QApplication.instance().show_overlay_notification(
                'Vantage · preview',
                'Alerts will appear here without blocking the game.',
                3500)))
        manage_notifications = QPushButton('Manage')
        manage_notifications.setIcon(game_icon('settings'))
        manage_notifications.setAccessibleName('Manage notification overlays')
        manage_notifications.setToolTip(
            'Create, rename, duplicate, style, route, or delete overlays')
        manage_notifications.clicked.connect(
            lambda: QApplication.instance().manage_notification_overlays(self))
        notification_row = QHBoxLayout()
        notification_row.setContentsMargins(0, 0, 0, 0)
        notification_row.setSpacing(3)
        notification_row.addWidget(arrange_notifications, 1)
        notification_row.addWidget(manage_notifications)
        notification_row.addWidget(preview_notification)
        gsl.addRow('Notification overlays', notification_row)
        general_settings.setLayout(gsl)

        stacked_widgets.append(('General', general_settings))

        # Spell Settings
        spells_settings = QFrame()
        ssl = QFormLayout()
        ssl.addRow(SettingsHeader('DETECTION'))
        ssl_casting_window = QCheckBox()
        ssl_casting_window.setWhatsThis(WHATS_THIS_CASTING_WINDOW)
        ssl_casting_window.setObjectName('spells:use_casting_window')
        ssl.addRow('Use casting window', ssl_casting_window)
        ssl_casting_window_buffer = QSpinBox()
        ssl_casting_window_buffer.setWhatsThis(WHATS_THIS_CASTING_BUFFER)
        ssl_casting_window_buffer.setRange(1, 4000)
        ssl_casting_window_buffer.setSingleStep(100)
        ssl_casting_window_buffer.setObjectName('spells:casting_window_buffer')

        ssl.addRow(
            'Casting margin (ms 1–4000)',
            ssl_casting_window_buffer
            )
        ssl_open_custom = QPushButton("Open Library")
        ssl_open_custom.setIcon(game_icon('timer'))
        ssl_open_custom.clicked.connect(self._get_custom_timers)
        ssl.addRow('Triggers and timers', ssl_open_custom)

        ssl.addRow(SettingsHeader('FADING ALERTS'))
        fade_enabled = QCheckBox()
        fade_enabled.setObjectName('spells:fade_sound_enabled')
        ssl.addRow('Enable fading sound', fade_enabled)
        spell_background_audio = QCheckBox()
        spell_background_audio.setObjectName('spells:sounds_when_hidden')
        spell_background_audio.setToolTip(
            'Allow buff, resist, and trigger sounds while the Buffs & Triggers '
            'window is hidden; off by default so every sound has a visible source')
        ssl.addRow('Sound while window hidden', spell_background_audio)
        fade_warning = QSpinBox()
        fade_warning.setRange(0, 600)
        fade_warning.setSuffix(' s')
        fade_warning.setObjectName('spells:fade_warning_seconds')
        fade_warning.setToolTip(
            'The bar turns yellow at this remaining time; the final 20 '
            'seconds always use the faster red critical warning')
        ssl.addRow('Warn before fading', fade_warning)
        fade_volume = QSpinBox()
        fade_volume.setRange(0, 100)
        fade_volume.setSuffix('%')
        fade_volume.setObjectName('spells:fade_sound_volume')
        fade_volume.setToolTip(
            'Master volume for buff warnings and trigger actions; each log '
            'profile can lower it independently in Log Profiles')
        ssl.addRow('Master trigger volume', fade_volume)
        fade_sound_row = QHBoxLayout()
        self.fade_sound_path = QComboBox()
        self.fade_sound_path.setObjectName('spells:fade_sound_path')
        self.fade_sound_path.setAccessibleName('Buff sound gallery')
        set_sound_combo_value(self.fade_sound_path, DEFAULT_SOUND)
        fade_sound_row.addWidget(self.fade_sound_path, 1)
        fade_browse = QPushButton('WAV…')
        fade_browse.setIcon(game_icon('copy'))
        fade_browse.clicked.connect(self._choose_fade_sound)
        fade_sound_row.addWidget(fade_browse)
        fade_test = QPushButton('Test')
        fade_test.setIcon(game_icon('play'))
        fade_test.clicked.connect(lambda: play_alert(
            self.fade_sound_path.currentData(), fade_volume.value(), 2,
            source="Test · buff sound"))
        fade_sound_row.addWidget(fade_test)
        ssl.addRow('Sound gallery', fade_sound_row)
        gallery_note = QLabel(
            '6 original CC0 sounds included · custom WAV files are also supported')
        gallery_note.setWordWrap(True)
        ssl.addRow('', gallery_note)

        ssl.addRow(SettingsHeader('ADVANCED'))
        ssl_secondary_duration = QCheckBox()
        ssl_secondary_duration.setWhatsThis(WHATS_THIS_PVP_DURATION)
        ssl_secondary_duration.setObjectName('spells:use_secondary_all')
        ssl.addRow('Use PvP durations', ssl_secondary_duration)
        ssl_item_trigger_mode = QCheckBox()
        ssl_item_trigger_mode.setWhatsThis(WHATS_THIS_ITEM_TRIGGERS)
        ssl_item_trigger_mode.setObjectName('spells:use_item_triggers')
        ssl_item_trigger_mode.setToolTip(WHATS_THIS_ITEM_TRIGGERS)
        ssl.addRow('Track item click effects', ssl_item_trigger_mode)
        bard_count = QCheckBox()
        bard_count.setObjectName('spells:bard_count_enabled')
        bard_count.setToolTip(
            'Group exact P99 Bard AE landing and resist lines into 1.5-second '
            'bursts; a single anonymous “winces” line is discarded')
        ssl.addRow('Bard AE hit counts', bard_count)
        bard_overlay = QCheckBox()
        bard_overlay.setObjectName('spells:bard_count_overlay')
        bard_overlay.setToolTip(
            'Show each completed Bard AE count in the movable Alerts overlay; '
            'the compact Buffs history remains available when this is off')
        ssl.addRow('Bard count overlay', bard_overlay)
        bard_audio = QCheckBox()
        bard_audio.setObjectName('spells:bard_count_audio')
        bard_audio.setToolTip(
            'Speak the completed hit/resist count using the master trigger '
            'volume; disabled by default so no sound is unexplained')
        ssl.addRow('Speak Bard count', bard_audio)
        bard_count.toggled.connect(bard_overlay.setEnabled)
        bard_count.toggled.connect(bard_audio.setEnabled)
        bard_overlay.setEnabled(bard_count.isChecked())
        bard_audio.setEnabled(bard_count.isChecked())
        spells_settings.setLayout(ssl)

        stacked_widgets.append(('Buffs & Triggers', spells_settings))

        # Map Settings
        map_settings = QFrame()
        msl = QFormLayout()
        msl.addRow(SettingsHeader('GENERAL'))
        msl_line_width = QSpinBox()
        msl_line_width.setObjectName('maps:line_width')
        msl_line_width.setRange(1, 10)
        msl_line_width.setSingleStep(1)
        msl.addRow('Map line width', msl_line_width)

        msl_grid_line_width = QSpinBox()
        msl_grid_line_width.setObjectName('maps:grid_line_width')
        msl_grid_line_width.setRange(1, 10)
        msl_grid_line_width.setSingleStep(1)
        msl.addRow('Grid line width', msl_grid_line_width)

        msl.addRow(SettingsHeader('Z LEVELS'))

        msl_current_z_alpha = QSpinBox()
        msl_current_z_alpha.setRange(1, 100)
        msl_current_z_alpha.setSingleStep(1)
        msl_current_z_alpha.setSuffix('%')
        msl_current_z_alpha.setObjectName('maps:current_z_alpha')
        msl.addRow('Current level opacity', msl_current_z_alpha)

        msl_closest_z_alpha = QSpinBox()
        msl_closest_z_alpha.setRange(1, 100)
        msl_closest_z_alpha.setSingleStep(1)
        msl_closest_z_alpha.setSuffix('%')
        msl_closest_z_alpha.setObjectName('maps:closest_z_alpha')
        msl.addRow('Nearby level opacity', msl_closest_z_alpha)

        msl_other_z_alpha = QSpinBox()
        msl_other_z_alpha.setRange(1, 100)
        msl_other_z_alpha.setSingleStep(1)
        msl_other_z_alpha.setSuffix('%')
        msl_other_z_alpha.setObjectName('maps:other_z_alpha')
        msl.addRow('Other level opacity', msl_other_z_alpha)

        map_settings.setLayout(msl)
        stacked_widgets.append(('Maps', map_settings))

        # Smart timer and lightweight market settings.
        timer_settings = QFrame()
        tsl = QFormLayout()
        tsl.addRow(SettingsHeader('SMART SPAWN TIMERS'))
        timer_volume = QSpinBox()
        timer_volume.setRange(0, 100)
        timer_volume.setSuffix('%')
        timer_volume.setObjectName('timers:volume')
        timer_volume.setToolTip(
            'Default volume for new timers; change an individual timer from '
            'its Edit dialog')
        tsl.addRow('Default timer volume', timer_volume)
        timer_background_audio = QCheckBox()
        timer_background_audio.setObjectName('timers:sounds_when_hidden')
        timer_background_audio.setToolTip(
            'Keep critical timer alarms audible while Smart Timers is hidden; '
            'turn this off for strict visible-window-only audio')
        tsl.addRow('Timer sounds while hidden', timer_background_audio)
        timer_compact = QCheckBox()
        timer_compact.setObjectName('timers:compact')
        timer_compact.setToolTip(
            'Hide secondary source, cycle, and kill-time text from '
            'each timer row while keeping every timer action available')
        tsl.addRow('Compact rows', timer_compact)
        timer_auto_log = QCheckBox()
        timer_auto_log.setObjectName('timers:auto_from_log')
        timer_auto_log.setToolTip(
            'Creates or restarts a timer for each “has slain” line in the active '
            'zone. EverQuest does not identify whether a mob is named or normal, '
            'so this mode listens for both to avoid missing a named mob.')
        tsl.addRow('Automatic timers on mob death', timer_auto_log)
        encounter_events = QCheckBox()
        encounter_events.setObjectName('timers:encounter_events_enabled')
        encounter_events.setToolTip(
            'Recognize exact local-log FTE, server-quake, and Ring War start '
            'events; Ring War creates the original 3-wave schedule locally')
        tsl.addRow('Raid encounter events', encounter_events)
        encounter_sound = QCheckBox()
        encounter_sound.setObjectName('timers:encounter_sound_enabled')
        encounter_sound.setToolTip(
            'Play an attributable Vantage alert for FTE, quake, Ring War, and '
            'each due Ring War milestone; overlays still work when this is off')
        tsl.addRow('Encounter alert sound', encounter_sound)
        tsl.addRow(SettingsHeader('SAFETY ALERTS'))
        afk_attacked = QCheckBox()
        afk_attacked.setObjectName('timers:afk_attacked_enabled')
        afk_attacked.setToolTip(
            'Warn only when an incoming hit or miss targets You while the real '
            'EverQuest or WinEQ game surface is not focused; repeats are '
            'limited to once every five seconds')
        tsl.addRow('Attacked while tabbed out', afk_attacked)
        death_loop = QCheckBox()
        death_loop.setObjectName('timers:death_loop_enabled')
        death_loop.setToolTip(
            'Warn after repeated player deaths with no outgoing attack, cast, '
            'or message; Vantage never closes or sends input to EverQuest')
        tsl.addRow('Death-loop warning', death_loop)
        death_count = QSpinBox()
        death_count.setRange(2, 20)
        death_count.setObjectName('timers:death_loop_deaths')
        death_count.setToolTip(
            'Number of unattended deaths required before the death-loop alert')
        tsl.addRow('Deaths required', death_count)
        death_window = QSpinBox()
        death_window.setRange(30, 600)
        death_window.setSuffix(' s')
        death_window.setObjectName('timers:death_loop_seconds')
        death_window.setToolTip(
            'Sliding time window used to count unattended deaths')
        tsl.addRow('Death-loop window', death_window)
        safety_sound = QCheckBox()
        safety_sound.setObjectName('timers:safety_sound_enabled')
        safety_sound.setToolTip(
            'Play a clearly attributed danger alert for AFK attack and '
            'death-loop warnings; overlays remain active when sound is off')
        tsl.addRow('Safety alert sound', safety_sound)
        catalog_known = sum(
            entry.seconds is not None for entry in RESPAWN_CATALOG.values())
        timer_catalog = QLabel(
            f'{len(RESPAWN_CATALOG)} zones included · '
            f'{catalog_known} with published timing\n'
            'Source shown on each timer: P99 community catalog')
        timer_catalog.setWordWrap(True)
        timer_catalog.setToolTip(
            'Zones without a published time are marked instead of inventing a respawn.')
        tsl.addRow('Automatic catalog', timer_catalog)
        timer_settings.setLayout(tsl)
        stacked_widgets.append(('Smart Timers', timer_settings))

        combat_settings = QFrame()
        csl = QFormLayout()
        csl.addRow(SettingsHeader('COMBAT PARSER'))
        combat_timeout = QSpinBox()
        combat_timeout.setRange(3, 120)
        combat_timeout.setSuffix(' s')
        combat_timeout.setObjectName('combat:encounter_timeout')
        combat_timeout.setToolTip(
            'Finish a fight after this many seconds without visible damage')
        csl.addRow('No-damage timeout', combat_timeout)
        combat_history = QSpinBox()
        combat_history.setRange(25, 1000)
        combat_history.setSingleStep(25)
        combat_history.setObjectName('combat:history_limit')
        combat_history.setToolTip(
            'Maximum recent threat targets retained in working memory; saved fights are not limited')
        csl.addRow('Threat target memory', combat_history)
        combat_storage = QLabel(
            'Unlimited local SQLite history · every parsed fight remains '
            'until you delete selected fights or clear all history.')
        combat_storage.setWordWrap(True)
        combat_storage.setObjectName('CombatDataNotice')
        combat_storage.setToolTip(
            'Open Combat › Fights to inspect, combine, rename, undo, or delete saved encounters')
        csl.addRow('Saved fights', combat_storage)
        combat_views = QLabel(
            'Overview · Player DPS · Tanking · Spells · Healing · Fights\n'
            'Parsing continues while the Combat window is hidden.')
        combat_views.setWordWrap(True)
        csl.addRow('Workspace', combat_views)
        combat_visibility = QLabel(
            'Healing is complete only for events visible in your own P99 log. '
            'Vantage never fabricates heals between other raid members.')
        combat_visibility.setWordWrap(True)
        combat_visibility.setObjectName('TriggerTokenLegend')
        csl.addRow('Log visibility', combat_visibility)
        combat_settings.setLayout(csl)
        stacked_widgets.append(('Combat', combat_settings))

        heal_settings = QFrame()
        hsl = QFormLayout()
        hsl.addRow(SettingsHeader('COMPLETE HEAL CHAIN'))
        heal_enabled = QCheckBox()
        heal_enabled.setObjectName('heals:enabled')
        heal_enabled.setToolTip(
            'Parse Complete Heal calls even while the Heal Chain panel is hidden')
        hsl.addRow('Enable chain monitor', heal_enabled)
        heal_interval = QSpinBox()
        heal_interval.setRange(1, 9)
        heal_interval.setSuffix(' s')
        heal_interval.setObjectName('heals:interval')
        heal_interval.setToolTip(
            'Expected spacing; an in-game !KI1 through !KI9 call updates it')
        hsl.addRow('Cleric spacing', heal_interval)
        cast_seconds = QSpinBox()
        cast_seconds.setRange(1, 20)
        cast_seconds.setSuffix(' s')
        cast_seconds.setObjectName('heals:cast_seconds')
        cast_seconds.setToolTip('Length of the moving Complete Heal cast rail')
        hsl.addRow('Cast rail length', cast_seconds)
        hotkey_format = QLineEdit()
        hotkey_format.setObjectName('heals:hotkey_format')
        hotkey_format.setPlaceholderText('### - CH - tankname')
        hotkey_format.setToolTip(
            'Use ### where the cleric order appears and tankname where the tank appears')
        hsl.addRow('Announcement format', hotkey_format)
        format_legend = QLabel(
            'Required tokens:  ### = cleric order · tankname = heal target\n'
            'Examples: “AAA - CH - Vulak” or “ST CCC CH -- Dain”')
        format_legend.setWordWrap(True)
        format_legend.setObjectName('TriggerTokenLegend')
        hsl.addRow('Format legend', format_legend)
        own_marker = QLineEdit()
        own_marker.setObjectName('heals:own_marker')
        own_marker.setPlaceholderText('Auto-detect from your own call')
        own_marker.setMaxLength(3)
        own_marker.setToolTip(
            'Optional marker such as AAA; leave empty to learn it from a “You” call')
        hsl.addRow('Your cleric order', own_marker)
        notify_turn = QCheckBox()
        notify_turn.setObjectName('heals:notify_turn')
        notify_turn.setToolTip('Show a Vantage overlay when your marker is next')
        hsl.addRow('Alert when you are next', notify_turn)
        privacy = QLabel(
            'Local only · reads the linked EQ log · no raid data is sent to an external server.')
        privacy.setWordWrap(True)
        privacy.setObjectName('CombatDataNotice')
        hsl.addRow('Data handling', privacy)
        heal_settings.setLayout(hsl)
        stacked_widgets.append(('Heal Chain', heal_settings))

        market_settings = QFrame()
        mrsl = QFormLayout()
        mrsl.addRow(SettingsHeader('pigparse green'))
        market_refresh = QSpinBox()
        market_refresh.setRange(10, 120)
        market_refresh.setSuffix(' min')
        market_refresh.setObjectName('market:refresh_minutes')
        market_refresh.setToolTip(
            'PigParse publishes rebuilt Green data on a 10-minute cycle')
        mrsl.addRow('Refresh interval', market_refresh)
        consider_lookup = QCheckBox()
        consider_lookup.setObjectName('market:auto_consider_lookup')
        consider_lookup.setToolTip(
            'When an exact EverQuest /consider faction line appears, open a '
            'compact internal P99 Wiki NPC card; repeated considers reuse the '
            'current card instead of creating duplicates')
        mrsl.addRow('NPC card on /consider', consider_lookup)
        market_source = QLabel(
            'Primary source: PigParse API · Green\n'
            'Secondary reference: Project 1999 Wiki')
        market_source.setWordWrap(True)
        mrsl.addRow('Sources', market_source)
        market_settings.setLayout(mrsl)
        stacked_widgets.append(('Market', market_settings))

        # Sharing Settings
        sharing_settings = QFrame()
        shsl = QFormLayout()
        shsl.addRow(SettingsHeader('GENERAL'))

        enable_sharing = QCheckBox()
        enable_sharing.setWhatsThis(WHATS_THIS_SHARING)
        enable_sharing.setObjectName('sharing:enabled')
        shsl.addRow('Enable location sharing', enable_sharing)

        self.sharing_player_name = QLineEdit()
        self.sharing_player_name.setObjectName('sharing:player_name')
        shsl.addRow(
            'Display name',
            self.sharing_player_name
        )

        sharing_player_name_override = QCheckBox()
        sharing_player_name_override.setObjectName(
            'sharing:player_name_override')
        shsl.addRow(
            'Use custom name',
            sharing_player_name_override
        )
        sharing_player_name_override.clicked.connect(
            functools.partial(self._dynamic_field_toggle,
                              sharing_player_name_override,
                              self.sharing_player_name, True))

        sharing_hostname = QLineEdit()
        sharing_hostname.setObjectName('sharing:url')
        shsl.addRow(
            'Sharing server',
            sharing_hostname
        )

        self.sharing_group_key = QLineEdit()
        self.sharing_group_key.setObjectName('sharing:group_key')
        shsl.addRow(
            'Group key',
            self.sharing_group_key
        )
        sharing_reconnect_delay = QSpinBox()
        sharing_reconnect_delay.setRange(1, 300)
        sharing_reconnect_delay.setSingleStep(1)
        sharing_reconnect_delay.setSuffix(' s')
        sharing_reconnect_delay.setObjectName('sharing:reconnect_delay')
        shsl.addRow('Reconnect delay', sharing_reconnect_delay)
        sharing_settings.setLayout(shsl)
        stacked_widgets.append(('Sharing', sharing_settings))

        # Quick Bar Settings
        quickbar_settings = QFrame()
        qbsl = QFormLayout()
        qbsl.addRow(SettingsHeader('QUICK BAR'))
        orientation = QComboBox()
        orientation.setObjectName('quickbar:orientation')
        orientation.setAccessibleName('Quick Bar orientation')
        orientation.setToolTip(
            'Place the command buttons in one horizontal row or vertical column')
        orientation.addItem('Horizontal · top or bottom edge', 'horizontal')
        orientation.addItem('Vertical · left or right edge', 'vertical')
        qbsl.addRow('Orientation', orientation)
        quickbar_header = QCheckBox()
        quickbar_header.setObjectName('quickbar:show_header')
        quickbar_header.setToolTip(
            'Turn off the title row and leave only the command buttons')
        qbsl.addRow('Show header', quickbar_header)
        quickbar_tick = QCheckBox()
        quickbar_tick.setObjectName('quickbar:show_server_tick')
        quickbar_tick.setToolTip(
            'Show the live six-second Server Tick countdown and progress')
        qbsl.addRow('Live Server Tick', quickbar_tick)
        quickbar_opacity = QSpinBox()
        quickbar_opacity.setRange(25, 100)
        quickbar_opacity.setSingleStep(5)
        quickbar_opacity.setSuffix('%')
        quickbar_opacity.setObjectName('quickbar:opacity')
        quickbar_opacity.setToolTip(
            'The whole Quick Bar remains readable over EverQuest')
        qbsl.addRow('Window opacity', quickbar_opacity)
        quickbar_top = QCheckBox()
        quickbar_top.setObjectName('quickbar:always_on_top')
        quickbar_top.setToolTip(
            'Keep the Quick Bar above EverQuest and other normal windows')
        qbsl.addRow('Always on top', quickbar_top)

        group_titles = {
            'windows': 'WINDOW BUTTONS',
            'tools': 'TOOLS',
            'logs': 'LOGS',
            'audio': 'AUDIO',
            'system': 'SYSTEM',
        }
        current_group = None
        for key, label, _icon_name, group in QUICKBAR_ITEMS:
            if group != current_group:
                qbsl.addRow(SettingsHeader(group_titles[group]))
                current_group = group
            visible = QCheckBox()
            visible.setObjectName(f'quickbar:show_{key}')
            visible.setToolTip(
                f'Show or hide the {label} button on the Quick Bar')
            qbsl.addRow(label, visible)
        quickbar_settings.setLayout(qbsl)
        stacked_widgets.append(('Quick Bar', quickbar_settings))

        # Appearance Settings
        appearance_settings = QFrame()
        appear_sl = QFormLayout()
        window_labels = {
            'maps': 'MAPS', 'spells': 'BUFFS', 'timers': 'TIMERS',
            'combat': 'COMBAT', 'heals': 'HEAL CHAIN', 'market': 'MARKET',
        }
        for window in (
                "maps", "spells", "timers", "combat", "heals", "market"):
            appear_sl.addRow(SettingsHeader(window_labels[window]))
            opacity = QSpinBox()
            opacity.setRange(25, 100)
            opacity.setSingleStep(5)
            opacity.setSuffix('%')
            opacity.setObjectName('%s:opacity' % window)
            appear_sl.addRow('Window opacity', opacity)
            if window != 'market':
                enable_clickthrough = QCheckBox()
                enable_clickthrough.setWhatsThis(WHATS_THIS_SHARING)
                enable_clickthrough.setObjectName('%s:clickthrough' % window)
                enable_clickthrough.setWhatsThis(WHATS_THIS_CLICKTHROUGH)
                appear_sl.addRow('Allow click-through', enable_clickthrough)
            else:
                interactive_market = QLabel(
                    'Always interactive for search and filters')
                interactive_market.setToolTip(
                    'Market does not use click-through because it contains text fields')
                appear_sl.addRow('Mouse and keyboard input', interactive_market)

            auto_hide_menu = QCheckBox()
            auto_hide_menu.setObjectName('%s:auto_hide_menu' % window)
            appear_sl.addRow('Auto-hide toolbar', auto_hide_menu)

            always_on_top = QCheckBox()
            always_on_top.setObjectName('%s:always_on_top' % window)
            appear_sl.addRow('Always on top', always_on_top)

        appearance_settings.setLayout(appear_sl)
        stacked_widgets.append(('Appearance', appearance_settings))

        return stacked_widgets

    def show_color_picker(self, window, preview):
        dialog = self._color_dialogs[window]
        if dialog.exec():
            current_color = dialog.currentColor()
            hexcolor = hex(current_color.rgb()).replace('0xff', '#')
            preview.setStyleSheet("background-color: {0}; "
                                  "border: 4px solid {0};".format(hexcolor))
        else:
            hexcolor = config.data[window]['color']
            intcolor = int(hexcolor.replace('#', '0x'), 16)
            dialog.setCurrentColor(QColor(intcolor))

    def _get_custom_timers(self):
        dialog = CustomTriggerSettings()
        dialog.exec()

    def _choose_fade_sound(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose Fading Sound', '', 'WAV Audio (*.wav)')
        if path:
            add_custom_sound_to_combo(
                self.fade_sound_path, store_portable_file(path))

    def _dynamic_field_toggle(self, toggle_field, dynamic_field, invert=False):
        if toggle_field.isChecked():
            dynamic_field.setDisabled(not invert)
        else:
            dynamic_field.setDisabled(bool(invert))


class SettingsHeader(QLabel):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setObjectName('SettingsLabel')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class TokenLineEdit(QLineEdit):
    """Line edit that completes trigger tokens at the cursor."""

    TOKENS = (
        '{c}', '{target}', '{mob}', '{spell}', '{damage}', '{ts}',
        '{COUNTER}')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token_start = -1
        self._completer = QCompleter(self)
        self._completer.setModel(QStringListModel(list(self.TOKENS), self._completer))
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setWidget(self)
        self._completer.activated[str].connect(self._insert_token)
        self.textEdited.connect(self._suggest_token)

    def _suggest_token(self, _):
        position = self.cursorPosition()
        before = self.text()[:position]
        start = before.rfind('{')
        if start < 0 or '}' in before[start:]:
            self._completer.popup().hide()
            return
        self._token_start = start
        self._completer.setCompletionPrefix(before[start:])
        if self._completer.completionCount():
            self._completer.complete(self.cursorRect())

    def _insert_token(self, token):
        if self._token_start < 0:
            return
        position = self.cursorPosition()
        value = self.text()
        self.setText(value[:self._token_start] + token + value[position:])
        self.setCursorPosition(self._token_start + len(token))


class TriggerMatchLogDialog(UniformScaleDialog):
    """Searchable session profiler and side-effect-free trigger test console."""

    HEADERS = (
        'Time', 'Status', 'Trigger', 'Category', 'Profile', 'Zone', 'µs',
        'Matched log line', 'Resolved output', 'Source')

    def __init__(self, parent=None):
        super().__init__(
            QSize(980, 540), parent, minimum_size=QSize(294, 162),
            initial_size=QSize(784, 432))
        self.setWindowTitle('Vantage · Trigger Match Log')
        layout = QVBoxLayout(self.scaled_surface)

        help_text = QLabel(
            'Newest first · records the exact line, resolved output, active '
            'profile, zone, source, and pattern evaluation time. History is '
            'bounded to 500 session events.')
        help_text.setObjectName('TriggerTokenLegend')
        help_text.setWordWrap(True)
        help_text.setToolTip(
            'Only parsed trigger metadata is retained; Vantage does not copy '
            'the full EverQuest log into this history')
        layout.addWidget(help_text)

        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText('Search trigger, line, output, source…')
        self.search.setAccessibleName('Search trigger match history')
        self.search.setToolTip(
            'Filter visible history across every displayed field; Ctrl+A and '
            'normal text-edit shortcuts work here')
        search_clear = self.search.findChild(QToolButton)
        if search_clear:
            search_clear.setAccessibleName('Clear trigger history search')
            search_clear.setToolTip('Clear the trigger history search text')
        self.search.textChanged.connect(self._apply_filters)
        filters.addWidget(self.search, 1)
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName('Trigger match status filter')
        self.status_filter.setToolTip(
            'Show matches, dry-run tests, timer stages, or pattern errors')
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.status_filter)
        self.profile_filter = QComboBox()
        self.profile_filter.setAccessibleName('Trigger profile filter')
        self.profile_filter.setToolTip(
            'Show every profile or one character log profile')
        self.profile_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.profile_filter)
        self.category_filter = QComboBox()
        self.category_filter.setAccessibleName('Trigger category filter')
        self.category_filter.setToolTip(
            'Show every trigger category or one exact category')
        self.category_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.category_filter)
        layout.addLayout(filters)

        test_row = QHBoxLayout()
        test_row.setSpacing(4)
        self.test_trigger = QComboBox()
        self.test_trigger.setAccessibleName('Trigger to dry run')
        self.test_trigger.setToolTip(
            'Test all compiled triggers or limit the dry run to one trigger')
        self.test_trigger.addItem('All triggers', '')
        for item in config.data.get('spells', {}).get('custom_timers', []):
            if item and str(item[0]).strip():
                self.test_trigger.addItem(str(item[0]), str(item[0]))
        selected_trigger = str(getattr(parent, '_current_trigger', '') or '')
        selected_index = self.test_trigger.findData(selected_trigger)
        if selected_index >= 0:
            self.test_trigger.setCurrentIndex(selected_index)
        test_row.addWidget(self.test_trigger)
        self.test_line = QLineEdit()
        self.test_line.setPlaceholderText('Paste one EQ log message to dry run')
        self.test_line.setAccessibleName('Dry-run EverQuest log message')
        self.test_line.setToolTip(
            'Evaluate the exact compiled patterns without playing audio, '
            'starting timers, copying text, or showing overlays')
        self.test_line.returnPressed.connect(self._dry_run)
        test_row.addWidget(self.test_line, 1)
        run_test = QPushButton('Test Line')
        run_test.setIcon(game_icon('play'))
        run_test.setToolTip(
            'Dry run this line and add every match to the session history')
        run_test.clicked.connect(self._dry_run)
        test_row.addWidget(run_test)
        layout.addLayout(test_row)

        self.summary = QLabel('0 events')
        self.summary.setObjectName('CombatDataNotice')
        self.summary.setAccessibleName('Visible trigger history summary')
        self.summary.setToolTip(
            'Visible events, total session events, and pattern evaluation timing')
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setAccessibleName('Trigger match and test history')
        self.table.setToolTip(
            'Select rows to copy; click a header to sort after history is loaded')
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (7, 8):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            9, QHeaderView.ResizeMode.ResizeToContents)
        header_tips = (
            'Time recorded in this Vantage session',
            'Matched, Test, Test end, timer stage, or Error',
            'Trigger name after token resolution where applicable',
            'Trigger group/category', 'Character profile used for this event',
            'EverQuest zone visible to Vantage',
            'Pattern evaluation time in microseconds',
            'Exact EQ message evaluated',
            'Resolved actions or dry-run result', 'Trigger provenance')
        for column, tooltip in enumerate(header_tips):
            self.table.horizontalHeaderItem(column).setToolTip(tooltip)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        refresh = QToolButton()
        refresh.setObjectName('ToolbarAction')
        refresh.setText('Refresh')
        refresh.setIcon(game_icon('refresh'))
        refresh.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        refresh.setAccessibleName('Refresh trigger history')
        refresh.setToolTip('Reload the bounded in-memory trigger history')
        refresh.clicked.connect(self.refresh)
        copy = QToolButton()
        copy.setObjectName('ToolbarAction')
        copy.setText('Copy')
        copy.setIcon(game_icon('copy'))
        copy.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        copy.setAccessibleName('Copy selected trigger history rows')
        copy.setToolTip(
            'Copy selected rows as tab-separated text; copies every visible row '
            'when nothing is selected')
        copy.clicked.connect(self._copy_rows)
        export = QToolButton()
        export.setObjectName('ToolbarAction')
        export.setText('Export CSV')
        export.setIcon(game_icon('export'))
        export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        export.setAccessibleName('Export visible trigger history')
        export.setToolTip('Export only the currently filtered rows to a CSV file')
        export.clicked.connect(self._export_csv)
        clear = QPushButton('Clear Session History')
        clear.setIcon(game_icon('delete'))
        clear.setObjectName('DangerAction')
        clear.setToolTip(
            'Clear only this bounded Vantage session history; the EQ log is untouched')
        clear.clicked.connect(self._clear)
        close = QPushButton('Close')
        close.setToolTip('Close the Trigger Match Log')
        close.clicked.connect(self.accept)
        actions.addWidget(refresh)
        actions.addWidget(copy)
        actions.addWidget(export)
        actions.addWidget(clear)
        actions.addStretch(1)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._history = []
        self._visible_history = []
        self.refresh()

    def _spells(self):
        app = QApplication.instance()
        return getattr(app, '_parsers_dict', {}).get('spells')

    def refresh(self):
        parser = self._spells()
        self._history = parser.trigger_history() if parser else []
        self._rebuild_filter(
            self.status_filter, 'All statuses',
            sorted({str(entry.get('status') or 'Matched')
                    for entry in self._history}, key=str.casefold))
        self._rebuild_filter(
            self.profile_filter, 'All profiles',
            sorted({str(entry.get('profile') or 'Unspecified')
                    for entry in self._history}, key=str.casefold))
        self._rebuild_filter(
            self.category_filter, 'All categories',
            sorted({str(entry.get('category') or 'Default')
                    for entry in self._history}, key=str.casefold))
        self._apply_filters()

    @staticmethod
    def _rebuild_filter(combo, all_label, values):
        previous = str(combo.currentData() or '')
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, '')
        for value in values:
            combo.addItem(value, value)
        index = combo.findData(previous)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _apply_filters(self, *_):
        query = self.search.text().strip().casefold()
        status = str(self.status_filter.currentData() or '').casefold()
        profile = str(self.profile_filter.currentData() or '').casefold()
        category = str(self.category_filter.currentData() or '').casefold()
        visible = []
        for entry in self._history:
            entry_status = str(entry.get('status') or 'Matched')
            entry_profile = str(entry.get('profile') or 'Unspecified')
            entry_category = str(entry.get('category') or 'Default')
            if status and entry_status.casefold() != status:
                continue
            if profile and entry_profile.casefold() != profile:
                continue
            if category and entry_category.casefold() != category:
                continue
            haystack = ' '.join(str(entry.get(key) or '') for key in (
                'time', 'status', 'trigger', 'category', 'profile', 'zone',
                'line', 'output', 'source')).casefold()
            if query and query not in haystack:
                continue
            visible.append(entry)
        self._visible_history = visible
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(visible))
        for row, entry in enumerate(visible):
            match_us = float(entry.get('match_us') or 0.0)
            values = (
                entry.get('time', ''), entry.get('status', 'Matched'),
                entry.get('trigger', ''), entry.get('category', ''),
                entry.get('profile') or 'Unspecified', entry.get('zone') or '—',
                f'{match_us:,.2f}' if match_us else '—',
                entry.get('line', ''), entry.get('output', ''),
                entry.get('source', ''))
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.setSortingEnabled(True)
        timings = [
            float(entry.get('match_us') or 0.0) for entry in visible
            if float(entry.get('match_us') or 0.0) > 0]
        timing = (
            f' · avg {sum(timings) / len(timings):,.2f} µs · '
            f'max {max(timings):,.2f} µs' if timings else '')
        self.summary.setText(
            f'{len(visible)} of {len(self._history)} events{timing}')

    def _dry_run(self):
        parser = self._spells()
        if not parser:
            self.summary.setText('Trigger parser is not available')
            return
        line = self.test_line.text().strip()
        if not line:
            self.summary.setText('Paste one EQ log message before testing')
            self.test_line.setFocus()
            return
        count = parser.test_trigger_line(
            line, str(self.test_trigger.currentData() or ''))
        self.refresh()
        self.summary.setText(
            f'{count} dry-run match' + ('es' if count != 1 else '') +
            f' · {len(self._visible_history)} visible events')

    def _table_rows(self, prefer_selection=True):
        selected = sorted({item.row() for item in self.table.selectedItems()})
        rows = (
            selected if prefer_selection and selected else
            list(range(self.table.rowCount())))
        return [[
            self.table.item(row, column).text()
            if self.table.item(row, column) else ''
            for column in range(self.table.columnCount())]
            for row in rows]

    def _copy_rows(self):
        rows = self._table_rows()
        if not rows:
            self.summary.setText('No visible trigger events to copy')
            return
        lines = ['\t'.join(self.HEADERS)]
        lines.extend('\t'.join(row) for row in rows)
        QApplication.clipboard().setText('\n'.join(lines))
        self.summary.setText(f'Copied {len(rows)} trigger event rows')

    def _export_csv(self):
        if not self._visible_history:
            self.summary.setText('No visible trigger events to export')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Trigger Match Log', 'Vantage-Trigger-Match-Log.csv',
            'CSV table (*.csv);;All Files (*)')
        if not path:
            return
        if not path.casefold().endswith('.csv'):
            path += '.csv'
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as output:
                writer = csv.writer(output)
                writer.writerow(self.HEADERS)
                writer.writerows(self._table_rows(prefer_selection=False))
        except OSError as error:
            QMessageBox.warning(self, 'Export Failed', str(error))
            return
        self.summary.setText(
            f'Exported {self.table.rowCount()} visible trigger events')

    def _clear(self):
        parser = self._spells()
        if not parser:
            return
        answer = QMessageBox.question(
            self, 'Clear Trigger Match Log',
            'Clear the in-memory trigger history for this session?',
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            parser.clear_trigger_history()
            self.refresh()


TRIGGER_ITEM_KIND = Qt.ItemDataRole.UserRole
TRIGGER_ITEM_ID = Qt.ItemDataRole.UserRole + 1


class TriggerLibraryTree(QTreeWidget):
    """Compact hierarchical library with a reliable post-drop signal."""

    structure_changed = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        if event.isAccepted():
            self.structure_changed.emit()


class CustomTriggerSettings(UniformScaleDialog):

    def __init__(self):
        super().__init__(
            QSize(680, 650), minimum_size=QSize(204, 195),
            initial_size=QSize(544, 520))

        self._custom_triggers = {}
        self._current_trigger = ''
        self._tree_loading = False

        self.setWindowTitle("Vantage · Triggers and Timers")
        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self):

        layout = QVBoxLayout()

        self._triggers = TriggerLibraryTree()
        self._triggers.setObjectName('TriggerLibraryTree')
        self._triggers.setAccessibleName('Trigger group and trigger library')
        self._triggers.setToolTip(
            'Groups and triggers · drag a row to reorder it or move it into another group')
        self._triggers.setHeaderLabels(('Trigger library', 'Scope'))
        self._triggers.headerItem().setToolTip(
            0, 'Nested trigger groups and individual trigger names')
        self._triggers.headerItem().setToolTip(
            1, 'All characters or the exact character profile override')
        self._triggers.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._triggers.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._triggers.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._triggers.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self._triggers.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._triggers.setDropIndicatorShown(True)
        self._triggers.setMinimumHeight(92)
        self._triggers.setMaximumHeight(190)
        self._triggers.itemSelectionChanged.connect(self._activated)
        self._triggers.itemChanged.connect(self._tree_item_changed)
        self._triggers.structure_changed.connect(self._persist_tree_structure)
        layout.addWidget(self._triggers)

        action_bar = ResponsiveActionBar(86)
        self._add_trigger_button = QPushButton()
        self._add_trigger_button.setText('Add')
        self._add_trigger_button.setIcon(game_icon('add'))
        self._add_trigger_button.setToolTip(
            'Create a trigger inside the selected group')
        self._add_trigger_button.clicked.connect(self._add_trigger)
        action_bar.addWidget(self._add_trigger_button)

        self._add_group_button = QPushButton('Group')
        self._add_group_button.setIcon(game_icon('layers'))
        self._add_group_button.setToolTip(
            'Create a group; use / in the name for nested groups')
        self._add_group_button.clicked.connect(self._add_group)
        action_bar.addWidget(self._add_group_button)

        self._clone_trigger_button = QPushButton('Clone')
        self._clone_trigger_button.setIcon(game_icon('copy'))
        self._clone_trigger_button.setToolTip(
            'Duplicate the selected trigger as an editable copy')
        self._clone_trigger_button.clicked.connect(self._clone_trigger)
        action_bar.addWidget(self._clone_trigger_button)

        self._remove_trigger_button = QPushButton()
        self._remove_trigger_button.setText('Delete')
        self._remove_trigger_button.setIcon(game_icon('delete'))
        self._remove_trigger_button.setObjectName('DangerAction')
        self._remove_trigger_button.setToolTip(
            'Delete the selected trigger; deleting a group moves its triggers to its parent')
        self._remove_trigger_button.clicked.connect(self._remove_trigger)
        action_bar.addWidget(self._remove_trigger_button)

        self._save_trigger_button = QPushButton()
        self._save_trigger_button.setText('Save')
        self._save_trigger_button.setIcon(game_icon('spawn'))
        self._save_trigger_button.setObjectName('PrimaryAction')
        self._save_trigger_button.setToolTip(
            'Save every edited trigger, group and character override')
        self._save_trigger_button.clicked.connect(self._save_trigger)
        action_bar.addWidget(self._save_trigger_button)

        self._import_gina_button = QPushButton('Import Trigger Pack…')
        self._import_gina_button.setToolTip(
            'Import editable copies from .gtp, ShareData.xml, XML, or .gtt; '
            'review every trigger before committing')
        self._import_gina_button.setIcon(game_icon('refresh'))
        self._import_gina_button.clicked.connect(self._import_gina)
        action_bar.addWidget(self._import_gina_button)

        history_button = QPushButton('Match Log')
        history_button.setIcon(game_icon('combat'))
        history_button.setToolTip(
            'Show exactly which triggers matched and which sound or overlay they produced')
        history_button.clicked.connect(self._show_match_log)
        action_bar.addWidget(history_button)

        layout.addWidget(action_bar)

        trigger_layout = polish_form(QFormLayout())
        trigger_layout.setSpacing(10)

        trigger_layout.addRow(SettingsHeader('TRIGGER'))

        self._trigger_name = TokenLineEdit()
        self._trigger_name.setMaxLength(120)
        self._trigger_name.setToolTip(
            'Editable name used in the library and match history')
        trigger_layout.addRow('Name', self._trigger_name)

        self._trigger_text = TokenLineEdit()
        self._trigger_text.setToolTip(
            'Exact EQ log text to match; type { to see supported tokens')
        trigger_layout.addRow('Log text', self._trigger_text)

        token_legend = QLabel(
            "TOKENS · type { to autocomplete\n"
            "* any text · {c} your character · {target}/{mob}/{spell}/{damage} "
            "capture text · {ts} dynamic D:H:M:S timer · {COUNTER} activation count")
        token_legend.setObjectName('TriggerTokenLegend')
        token_legend.setWordWrap(True)
        token_legend.setMaximumHeight(88)
        token_legend.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        token_legend.setToolTip(
            'Type an opening brace in token-aware fields to choose a valid token')
        trigger_layout.addWidget(token_legend)

        self._trigger_time = QLineEdit()
        self._trigger_time.setText("hh:mm:ss")
        self._trigger_time.setToolTip(
            'Timer duration; 3 means 3 minutes, and 3:50 or 1:03:50 are also accepted')

        self._trigger_enabled = QCheckBox('Enabled')
        self._trigger_enabled.setChecked(True)
        self._trigger_enabled.setToolTip(
            'Enable this trigger without changing the rest of its category')
        trigger_layout.addRow('Status', self._trigger_enabled)

        self._trigger_regex = QCheckBox('Regular expression')
        self._trigger_regex.setToolTip(
            'For advanced or imported patterns only; normal triggers do not need it')
        trigger_layout.addRow('Pattern mode', self._trigger_regex)

        self._trigger_source = QLabel('Vantage')
        self._trigger_source.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        trigger_layout.addRow('Source', self._trigger_source)

        self._trigger_category = QComboBox()
        self._trigger_category.setEditable(True)
        self._trigger_category.setAccessibleName('Trigger category')
        self._trigger_category.setToolTip(
            'Group related triggers and enable or disable the whole category')
        self._trigger_category.lineEdit().setToolTip(
            'Choose or type the category used to organize this trigger')
        self._trigger_category.currentTextChanged.connect(
            self._category_changed)
        trigger_layout.addRow('Category', self._trigger_category)

        self._category_enabled = QCheckBox('Enabled for this category')
        self._category_enabled.setToolTip(
            'Turn this group on or off for the selected character scope')
        self._category_enabled.setChecked(True)
        trigger_layout.addRow('Category status', self._category_enabled)

        self._category_scope = QComboBox()
        self._category_scope.setEditable(True)
        self._category_scope.addItem('All characters', '')
        active_profile = str(config.data.get(
            'sharing', {}).get('player_name', '')).strip()
        if active_profile and active_profile != 'ConfigureMe':
            self._category_scope.addItem(active_profile, active_profile)
        self._category_scope.setToolTip(
            'Choose All characters or type one exact character name for a group override')
        self._category_scope.lineEdit().setToolTip(
            'Type one exact character name, or use All characters for the global group style')
        self._category_scope.lineEdit().setAccessibleName(
            'Trigger group character scope')
        self._category_scope.currentTextChanged.connect(self._category_changed)
        trigger_layout.addRow('Group applies to', self._category_scope)

        self._category_color = InheritedColorPicker(
            'Remove this group override and inherit its parent or overlay color')
        self._category_color.setToolTip(
            'A group color is inherited by child groups and triggers unless overridden')
        trigger_layout.addRow('Group text color', self._category_color)

        self._trigger_profile = QLineEdit()
        self._trigger_profile.setPlaceholderText('Blank = every character')
        self._trigger_profile.setToolTip(
            'Optional exact character profile for this trigger')
        trigger_layout.addRow('Character profile', self._trigger_profile)

        self._trigger_zone = QLineEdit()
        self._trigger_zone.setPlaceholderText('Blank = all zones')
        self._trigger_zone.setToolTip(
            'Optional exact zone restriction; blank allows every zone')
        trigger_layout.addRow('Zone', self._trigger_zone)

        self._trigger_comments = QLineEdit()
        self._trigger_comments.setPlaceholderText(
            'Optional notes about purpose, source, or setup')
        self._trigger_comments.setToolTip(
            'Local notes that do not affect matching or trigger actions')
        trigger_layout.addRow('Comments', self._trigger_comments)

        self._trigger_alert = TokenLineEdit()
        self._trigger_alert.setPlaceholderText('Optional overlay alert')
        self._trigger_alert.setToolTip(
            'Text shown on the selected overlay when this trigger matches')
        self._trigger_color = InheritedColorPicker(
            'Remove this trigger override and inherit its group or overlay color')
        self._trigger_color.setToolTip(
            'Final text-color override for this trigger only')

        self._trigger_overlay = QComboBox()
        self._refresh_overlay_routes()
        self._trigger_overlay.setToolTip(
            'Route this trigger to any user-defined, independently positioned overlay')

        self._trigger_restart = QComboBox()
        self._trigger_restart.addItem('Restart existing timer', 'restart')
        self._trigger_restart.addItem('Keep existing timer', 'keep')
        self._trigger_restart.addItem('Start another instance', 'new')
        self._trigger_restart.setToolTip(
            'Choose what happens when the same timer matches again')

        self._trigger_end_text = TokenLineEdit()
        self._trigger_end_text.setPlaceholderText(
            'Optional log text that ends this timer early')
        self._trigger_enders = QTableWidget(0, 2)
        self._trigger_enders.setHorizontalHeaderLabels(('Log text', 'Regex'))
        self._trigger_enders.horizontalHeaderItem(0).setToolTip(
            'Independent log pattern that immediately ends the running timer')
        self._trigger_enders.horizontalHeaderItem(1).setToolTip(
            'Whether only this early-ending pattern uses regular expressions')
        self._trigger_enders.verticalHeader().setVisible(False)
        self._trigger_enders.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._trigger_enders.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._trigger_enders.setMinimumHeight(112)
        self._trigger_enders.setToolTip(
            'Any matching row immediately ends this timer; each row can use plain text or regex')
        ender_host = QWidget()
        ender_layout = QVBoxLayout(ender_host)
        ender_layout.setContentsMargins(0, 0, 0, 0)
        ender_layout.setSpacing(3)
        ender_layout.addWidget(self._trigger_enders)
        ender_actions = QHBoxLayout()
        add_ender = QPushButton('Add ender')
        add_ender.setIcon(game_icon('add'))
        add_ender.setToolTip('Add another independent early-ending log pattern')
        add_ender.clicked.connect(lambda: self._add_end_pattern())
        remove_ender = QPushButton('Delete selected')
        remove_ender.setIcon(game_icon('delete'))
        remove_ender.setObjectName('DangerAction')
        remove_ender.setToolTip('Delete the selected early-ending pattern')
        remove_ender.clicked.connect(self._remove_end_pattern)
        ender_actions.addWidget(add_ender)
        ender_actions.addWidget(remove_ender)
        ender_layout.addLayout(ender_actions)

        trigger_sound_panel = QWidget()
        trigger_sound_row = QVBoxLayout(trigger_sound_panel)
        trigger_sound_row.setContentsMargins(0, 0, 0, 0)
        self._trigger_sound = QComboBox()
        self._trigger_sound.setAccessibleName('Trigger sound gallery')
        set_sound_combo_value(self._trigger_sound, DEFAULT_SOUND)
        trigger_sound_row.addWidget(self._trigger_sound)
        trigger_sound_actions = ResponsiveActionBar(96)
        trigger_sound_browse = QPushButton('Choose WAV…')
        trigger_sound_browse.setIcon(game_icon('copy'))
        trigger_sound_browse.setToolTip(
            'Copy a custom WAV into the portable Vantage sound gallery')
        trigger_sound_browse.clicked.connect(self._choose_trigger_sound)
        trigger_sound_actions.addWidget(trigger_sound_browse)
        trigger_sound_test = QPushButton('Test')
        trigger_sound_test.setIcon(game_icon('play'))
        trigger_sound_test.setToolTip(
            'Play the selected trigger sound at the configured trigger volume')
        trigger_sound_test.clicked.connect(
            lambda: play_alert(
                self._trigger_sound.currentData(),
                config.data['spells']['fade_sound_volume'], 1,
                source="Test · trigger sound")
            if self._trigger_sound.currentData() else None)
        trigger_sound_actions.addWidget(trigger_sound_test)
        trigger_sound_row.addWidget(trigger_sound_actions)
        self._trigger_timer_type = QComboBox()
        self._trigger_timer_type.addItem('No timer', 'none')
        self._trigger_timer_type.addItem('Timer · count down', 'countdown')
        self._trigger_timer_type.addItem('Stopwatch · count up', 'stopwatch')
        self._trigger_timer_type.addItem('Repeating timer', 'repeating')
        self._trigger_timer_type.setToolTip(
            'Choose the same four timer modes supported by full trigger tools')
        self._trigger_timer_type.currentIndexChanged.connect(
            self._timer_type_changed)
        self._trigger_timer_name = TokenLineEdit()
        self._trigger_timer_name.setPlaceholderText(
            'Blank = use trigger name')
        self._trigger_timer_name.setToolTip(
            'Visible timer label; supports the same captured tokens as display text')
        self._trigger_restart_name = QCheckBox(
            'Match running timers by displayed timer name')
        self._trigger_restart_name.setToolTip(
            'Allow another trigger with the same resolved timer name to restart '
            'or keep that timer; off keeps each trigger independent')
        self._trigger_visible_seconds = QSpinBox()
        self._trigger_visible_seconds.setRange(0, 86400)
        self._trigger_visible_seconds.setSuffix(' s')
        self._trigger_visible_seconds.setToolTip(
            '0 shows the whole countdown; otherwise show only its final seconds')
        self._trigger_counter_reset = QSpinBox()
        self._trigger_counter_reset.setRange(0, 86400)
        self._trigger_counter_reset.setSuffix(' s')
        self._trigger_counter_reset.setToolTip(
            'Reset {COUNTER} after this many seconds without another match')

        self._trigger_clipboard = TokenLineEdit()
        self._trigger_clipboard.setPlaceholderText(
            'Optional resolved text copied on a match')
        self._trigger_clipboard.setToolTip(
            'Leave blank to avoid changing the Windows clipboard')

        self._trigger_tts = TokenLineEdit()
        self._trigger_tts.setPlaceholderText(
            'Optional text spoken through the Windows voice')
        self._trigger_interrupt_speech = QCheckBox('Interrupt current speech')
        self._trigger_interrupt_speech.setToolTip(
            'Stop the current Vantage voice before speaking this action')

        self._trigger_ending_seconds = QSpinBox()
        self._trigger_ending_seconds.setRange(0, 86400)
        self._trigger_ending_seconds.setSuffix(' s before end')
        self._trigger_ending_seconds.setToolTip(
            'Fire the Timer Ending actions at this remaining time; 0 disables them')
        self._trigger_ending_alert = TokenLineEdit()
        self._trigger_ending_alert.setPlaceholderText(
            'Optional text when the timer is ending')
        self._trigger_ending_sound = QComboBox()
        set_sound_combo_value(self._trigger_ending_sound, '')
        self._trigger_ending_tts = TokenLineEdit()
        self._trigger_ending_tts.setPlaceholderText(
            'Optional speech when the timer is ending')
        self._trigger_ending_interrupt = QCheckBox('Interrupt current speech')

        self._trigger_ended_alert = TokenLineEdit()
        self._trigger_ended_alert.setPlaceholderText(
            'Optional text when the timer reaches zero')
        self._trigger_ended_sound = QComboBox()
        set_sound_combo_value(self._trigger_ended_sound, '')
        self._trigger_ended_tts = TokenLineEdit()
        self._trigger_ended_tts.setPlaceholderText(
            'Optional speech when the timer reaches zero')
        self._trigger_ended_interrupt = QCheckBox('Interrupt current speech')

        def speech_panel(editor, interrupt, source):
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            panel_layout.setSpacing(3)
            editor.setToolTip(
                'Resolved tokens are spoken by the built-in Windows voice')
            panel_layout.addWidget(editor)
            row = QHBoxLayout()
            interrupt.setToolTip(
                'Stop current Vantage speech before speaking this action')
            test = QPushButton('Test voice')
            test.setIcon(game_icon('play'))
            test.setToolTip('Speak this text now using the Windows voice')
            test.clicked.connect(lambda: speak_text(
                editor.text(), config.data['spells']['fade_sound_volume'],
                interrupt.isChecked(), source=source))
            row.addWidget(interrupt)
            row.addWidget(test)
            panel_layout.addLayout(row)
            return panel

        basic_speech_panel = speech_panel(
            self._trigger_tts, self._trigger_interrupt_speech,
            'Test · trigger speech')
        ending_speech_panel = speech_panel(
            self._trigger_ending_tts, self._trigger_ending_interrupt,
            'Test · timer ending speech')
        ended_speech_panel = speech_panel(
            self._trigger_ended_tts, self._trigger_ended_interrupt,
            'Test · timer ended speech')

        def stage_sound_panel(combo, source):
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            panel_layout.setSpacing(3)
            combo.setToolTip(
                'Choose No sound, a built-in sound, or a portable custom WAV')
            panel_layout.addWidget(combo)
            actions = ResponsiveActionBar(96)
            choose = QPushButton('Choose WAV…')
            choose.setIcon(game_icon('copy'))
            choose.setToolTip('Copy a custom WAV into Vantage portable data')
            choose.clicked.connect(lambda: self._choose_stage_sound(combo))
            actions.addWidget(choose)
            test = QPushButton('Test')
            test.setIcon(game_icon('play'))
            test.setToolTip('Play this stage sound at the configured volume')
            test.clicked.connect(lambda: play_alert(
                combo.currentData(),
                config.data['spells']['fade_sound_volume'], 1,
                source=source) if combo.currentData() else None)
            actions.addWidget(test)
            panel_layout.addWidget(actions)
            return panel

        ending_sound_panel = stage_sound_panel(
            self._trigger_ending_sound, 'Test · timer ending sound')
        ended_sound_panel = stage_sound_panel(
            self._trigger_ended_sound, 'Test · timer ended sound')

        action_tabs = QTabWidget()
        self._action_tabs = action_tabs
        action_tabs.setObjectName('TriggerActionTabs')
        action_tabs.setToolTip(
            'Basic, Timer, Timer Ending, and Timer Ended behaviors are independent')

        basic_page = QWidget()
        basic_layout = polish_form(QFormLayout(basic_page))
        basic_layout.addRow('Display text', self._trigger_alert)
        basic_layout.addRow('Text color', self._trigger_color)
        basic_layout.addRow('Overlay route', self._trigger_overlay)
        basic_layout.addRow('Sound', trigger_sound_panel)
        basic_layout.addRow('Text-to-speech', basic_speech_panel)
        basic_layout.addRow('Copy to clipboard', self._trigger_clipboard)
        action_tabs.addTab(basic_page, 'Basic')

        timer_page = QWidget()
        timer_layout = polish_form(QFormLayout(timer_page))
        timer_layout.addRow('Timer type', self._trigger_timer_type)
        timer_layout.addRow('Timer name', self._trigger_timer_name)
        timer_layout.addRow('Duration', self._trigger_time)
        timer_layout.addRow('Visible duration', self._trigger_visible_seconds)
        timer_layout.addRow('When running', self._trigger_restart)
        timer_layout.addRow('Restart scope', self._trigger_restart_name)
        timer_layout.addRow('Early enders', ender_host)
        timer_layout.addRow('Counter reset', self._trigger_counter_reset)
        action_tabs.addTab(timer_page, 'Timer')

        ending_page = QWidget()
        ending_layout = polish_form(QFormLayout(ending_page))
        ending_layout.addRow('Threshold', self._trigger_ending_seconds)
        ending_layout.addRow('Display text', self._trigger_ending_alert)
        ending_layout.addRow('Sound', ending_sound_panel)
        ending_layout.addRow('Text-to-speech', ending_speech_panel)
        action_tabs.addTab(ending_page, 'Timer Ending')

        ended_page = QWidget()
        ended_layout = polish_form(QFormLayout(ended_page))
        ended_layout.addRow('Display text', self._trigger_ended_alert)
        ended_layout.addRow('Sound', ended_sound_panel)
        ended_layout.addRow('Text-to-speech', ended_speech_panel)
        action_tabs.addTab(ended_page, 'Timer Ended')
        ensure_tab_tooltips(action_tabs, {
            'Basic': 'Configure the actions fired when this trigger matches',
            'Timer': 'Configure timer type, duration, restart, and early ending',
            'Timer Ending': 'Configure actions fired before the timer expires',
            'Timer Ended': 'Configure actions fired when the timer expires',
        })
        trigger_host = QWidget()
        trigger_host.setLayout(trigger_layout)
        editor_split = QSplitter(Qt.Orientation.Horizontal)
        editor_split.setObjectName('TriggerEditorSplit')
        editor_split.setChildrenCollapsible(False)
        core_scroll = scrollable(trigger_host, 'TriggerEditScroll')
        core_scroll.setMinimumWidth(290)
        action_tabs.setMinimumWidth(290)
        editor_split.addWidget(core_scroll)
        editor_split.addWidget(action_tabs)
        editor_split.setStretchFactor(0, 1)
        editor_split.setStretchFactor(1, 1)
        layout.addWidget(editor_split, 1)

        button_layout = QHBoxLayout()
        button_layout.addWidget(QWidget(), 1)  # spacer
        self._exit_button = QPushButton("Close")
        self._exit_button.setToolTip(
            'Save the trigger library and close this editor')
        self._exit_button.clicked.connect(self._close)
        button_layout.addWidget(self._exit_button)
        layout.addItem(button_layout)

        self.scaled_surface.setLayout(layout)

    def _timer_type_changed(self, *_):
        timer_type = self._trigger_timer_type.currentData()
        counts_down = timer_type in ('countdown', 'repeating')
        has_timer = timer_type != 'none'
        self._trigger_time.setEnabled(counts_down)
        self._trigger_timer_name.setEnabled(has_timer)
        self._trigger_restart_name.setEnabled(has_timer)
        self._trigger_visible_seconds.setEnabled(counts_down)
        self._trigger_restart.setEnabled(has_timer)
        self._trigger_enders.setEnabled(has_timer)
        self._trigger_counter_reset.setEnabled(has_timer)
        if hasattr(self, '_action_tabs'):
            self._action_tabs.setTabEnabled(2, counts_down)
            self._action_tabs.setTabEnabled(3, counts_down)

    def _add_end_pattern(self, text='', regex=False):
        row = self._trigger_enders.rowCount()
        self._trigger_enders.insertRow(row)
        pattern = TokenLineEdit()
        pattern.setText(str(text or ''))
        pattern.setPlaceholderText('Log text that ends this timer')
        pattern.setToolTip(
            'This timer ends immediately when the linked log line matches')
        regex_toggle = QCheckBox()
        regex_toggle.setChecked(bool(regex))
        regex_toggle.setAccessibleName(
            f'Use regular expression for early ender {row + 1}')
        regex_toggle.setToolTip(
            'Use regex only for this early-ending pattern')
        self._trigger_enders.setCellWidget(row, 0, pattern)
        self._trigger_enders.setCellWidget(row, 1, regex_toggle)
        self._trigger_enders.setCurrentCell(row, 0)

    def _remove_end_pattern(self):
        row = self._trigger_enders.currentRow()
        if row >= 0:
            self._trigger_enders.removeRow(row)

    def _load_end_patterns(self, trigger):
        self._trigger_enders.setRowCount(0)
        patterns = trigger.end_patterns or ([{
            'text': trigger.end_text, 'regex': trigger.regex}]
            if trigger.end_text else [])
        for pattern in patterns:
            self._add_end_pattern(
                pattern.get('text', ''), pattern.get('regex', False))

    def _end_patterns(self):
        patterns = []
        for row in range(self._trigger_enders.rowCount()):
            editor = self._trigger_enders.cellWidget(row, 0)
            regex_toggle = self._trigger_enders.cellWidget(row, 1)
            text = editor.text().strip() if editor else ''
            if text:
                patterns.append({
                    'text': text,
                    'regex': bool(regex_toggle and regex_toggle.isChecked())})
        return patterns

    def _load_from_config(self, selected_name=None, selected_group=None):
        selected_name = selected_name or self._current_trigger
        self._tree_loading = True
        self._triggers.clear()
        self._custom_triggers.clear()
        spells = config.data['spells']
        groups = normalize_trigger_groups(spells)
        for item in spells['custom_timers']:
            ct = CustomTrigger(*item)
            self._custom_triggers[ct.name] = ct

        self._trigger_category.blockSignals(True)
        self._trigger_category.clear()
        self._trigger_category.addItems(sorted(groups))
        self._trigger_category.blockSignals(False)

        group_items = {}
        ordered_groups = sorted(
            groups.items(),
            key=lambda pair: (
                pair[0].count('/'), pair[1].get('order', 0),
                pair[0].casefold()))
        for path, definition in ordered_groups:
            parent_path = path.rsplit('/', 1)[0] if '/' in path else ''
            item = QTreeWidgetItem((path.rsplit('/', 1)[-1], 'All'))
            item.setData(0, TRIGGER_ITEM_KIND, 'group')
            item.setData(0, TRIGGER_ITEM_ID, path)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsUserCheckable |
                Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled |
                Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(
                0, Qt.CheckState.Checked if definition.get('enabled', True)
                else Qt.CheckState.Unchecked)
            item.setToolTip(
                0, f'{path} · drag to nest or reorder · rename inline')
            item.setToolTip(
                1, 'The checkbox is the global state; character overrides are edited below')
            parent = group_items.get(parent_path)
            if parent:
                parent.addChild(item)
            else:
                self._triggers.addTopLevelItem(item)
            group_items[path] = item

        order = spells.get('trigger_order', [])
        if not isinstance(order, list):
            order = []
        order_index = {str(name): index for index, name in enumerate(order)}
        triggers = sorted(
            self._custom_triggers.values(),
            key=lambda trigger: (
                order_index.get(trigger.name, len(order_index)),
                trigger.name.casefold()))
        selected_item = None
        first_trigger = None
        for trigger in triggers:
            parent = group_items.get(normalize_group_path(trigger.category))
            if parent is None:
                parent = group_items.get('Default')
            item = QTreeWidgetItem((
                trigger.name, trigger.profile or 'All'))
            item.setData(0, TRIGGER_ITEM_KIND, 'trigger')
            item.setData(0, TRIGGER_ITEM_ID, trigger.name)
            item.setFlags(
                (item.flags() | Qt.ItemFlag.ItemIsUserCheckable |
                 Qt.ItemFlag.ItemIsDragEnabled) &
                ~Qt.ItemFlag.ItemIsDropEnabled &
                ~Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(
                0, Qt.CheckState.Checked if trigger.enabled
                else Qt.CheckState.Unchecked)
            item.setToolTip(
                0, f'{trigger.name} · drag to move or reorder · check to enable')
            item.setToolTip(
                1, trigger.profile or 'Runs for every character')
            if parent:
                parent.addChild(item)
            else:
                self._triggers.addTopLevelItem(item)
            first_trigger = first_trigger or item
            if trigger.name == selected_name:
                selected_item = item

        self._triggers.expandAll()
        if selected_group and selected_group in group_items:
            selected_item = group_items[selected_group]
        self._tree_loading = False
        if selected_item or first_trigger:
            self._triggers.setCurrentItem(selected_item or first_trigger)
            self._activated()
        else:
            self._current_trigger = None
            self._clear()
            self._save_trigger_button.setEnabled(False)

    def _save_to_config(self):
        spells = config.data['spells']
        order = [
            name for name in self._tree_trigger_order()
            if name in self._custom_triggers]
        order.extend(
            name for name in self._custom_triggers if name not in order)
        order_index = {name: index for index, name in enumerate(order)}
        spells['trigger_order'] = order
        spells['custom_timers'] = [
            trigger.to_list() for trigger in sorted(
                self._custom_triggers.values(), key=lambda trigger: (
                    order_index.get(trigger.name, len(order_index)),
                    trigger.name.casefold()))
            if trigger.name]
        groups = normalize_trigger_groups(spells)
        spells['trigger_categories'] = {
            path: definition.get('enabled', True)
            for path, definition in groups.items()
        }
        config.save()
        QApplication.instance()._signals['settings'].spell_triggers_updated.emit()

    def _tree_trigger_order(self):
        order = []
        iterator = QTreeWidgetItemIterator(self._triggers)
        while iterator.value():
            item = iterator.value()
            if item.data(0, TRIGGER_ITEM_KIND) == 'trigger':
                order.append(str(item.data(0, TRIGGER_ITEM_ID)))
            iterator += 1
        return order or list(self._custom_triggers)

    def _selected_tree_item(self):
        return self._triggers.currentItem()

    def _selected_trigger_name(self):
        item = self._selected_tree_item()
        if item and item.data(0, TRIGGER_ITEM_KIND) == 'trigger':
            return str(item.data(0, TRIGGER_ITEM_ID) or '')
        return ''

    def _selected_group_path(self):
        item = self._selected_tree_item()
        if not item:
            return 'Default'
        if item.data(0, TRIGGER_ITEM_KIND) == 'trigger':
            item = item.parent()
        if item and item.data(0, TRIGGER_ITEM_KIND) == 'group':
            return normalize_group_path(item.data(0, TRIGGER_ITEM_ID))
        return 'Default'

    def _tree_item_changed(self, *_):
        if not self._tree_loading:
            self._persist_tree_structure()

    def _persist_tree_structure(self):
        """Commit drag/drop, rename and enable changes into runtime config."""
        if self._tree_loading:
            return
        selected_name = self._selected_trigger_name()
        selected_group = (
            self._selected_group_path() if not selected_name else None)
        old_groups = normalize_trigger_groups(config.data['spells'])
        new_groups = {}
        trigger_order = []
        group_order = 0

        self._tree_loading = True

        def visit(item, parent_path=''):
            nonlocal group_order
            kind = item.data(0, TRIGGER_ITEM_KIND)
            if kind == 'group':
                leaf = normalize_group_path(item.text(0))
                path = normalize_group_path(
                    f'{parent_path}/{leaf}' if parent_path else leaf)
                old_path = normalize_group_path(
                    item.data(0, TRIGGER_ITEM_ID))
                definition = dict(old_groups.get(old_path, {
                    'enabled': True, 'profiles': {}}))
                definition['enabled'] = (
                    item.checkState(0) == Qt.CheckState.Checked)
                definition['profiles'] = dict(
                    definition.get('profiles', {}))
                definition['order'] = group_order
                group_order += 1
                new_groups[path] = definition
                item.setData(0, TRIGGER_ITEM_ID, path)
                for index in range(item.childCount()):
                    visit(item.child(index), path)
                return
            if kind == 'trigger':
                name = str(item.data(0, TRIGGER_ITEM_ID) or '')
                trigger = self._custom_triggers.get(name)
                if trigger:
                    trigger.category = parent_path or 'Default'
                    trigger.enabled = (
                        item.checkState(0) == Qt.CheckState.Checked)
                    trigger_order.append(name)

        for index in range(self._triggers.topLevelItemCount()):
            visit(self._triggers.topLevelItem(index))
        self._tree_loading = False

        if not new_groups:
            new_groups = {
                'Default': {'enabled': True, 'profiles': {}, 'order': 0}}
        spells = config.data['spells']
        spells['trigger_groups'] = new_groups
        spells['trigger_categories'] = {
            path: definition['enabled']
            for path, definition in new_groups.items()}
        spells['trigger_order'] = trigger_order
        self._save_to_config()
        self._load_from_config(selected_name, selected_group)

    def _add_group(self):
        parent = self._selected_group_path()
        name, accepted = QInputDialog.getText(
            self, 'New Trigger Group',
            'Group name (use / for nested groups):')
        if not accepted or not name.strip():
            return
        path = normalize_group_path(
            f'{parent}/{name}' if parent and parent != 'Default'
            else name)
        groups = normalize_trigger_groups(config.data['spells'])
        if path in groups:
            self._load_from_config(selected_group=path)
            return
        for ancestor in group_ancestors(path):
            groups.setdefault(ancestor, {
                'enabled': True, 'profiles': {}, 'order': len(groups)})
        config.data['spells']['trigger_groups'] = groups
        self._save_to_config()
        self._load_from_config(selected_group=path)

    def _clone_trigger(self):
        name = self._selected_trigger_name()
        source = self._custom_triggers.get(name)
        if not source:
            return
        base = f'{source.name} · Copy'
        clone_name = base
        suffix = 2
        while clone_name in self._custom_triggers:
            clone_name = f'{base} {suffix}'
            suffix += 1
        clone = CustomTrigger(*source.to_list())
        clone.name = clone_name
        clone.enabled = False
        clone.comments = (
            f'{clone.comments} · Cloned from {source.name}'.strip(' ·'))
        self._custom_triggers[clone_name] = clone
        self._save_to_config()
        self._load_from_config(selected_name=clone_name)

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _refresh_overlay_routes(self):
        selected = self._trigger_overlay.currentData() \
            if self._trigger_overlay.count() else None
        self._trigger_overlay.clear()
        for overlay_id, settings in config.data.get(
                'general', {}).get('notification_overlays', {}).items():
            kind = 'Timer' if settings.get('type') == 'timer' else 'Text'
            state = '' if settings.get('enabled', True) else ' · disabled'
            self._trigger_overlay.addItem(
                f"{settings.get('label', overlay_id)} · {kind}{state}",
                overlay_id)
        self._trigger_overlay.addItem('No visual overlay', 'none')
        if selected is not None:
            self._set_combo_data(self._trigger_overlay, selected)

    def _display_trigger(self, trigger):
        self._trigger_name.setText(trigger.name)
        self._trigger_text.setText(trigger.text)
        self._trigger_time.setText(trigger.time)
        self._trigger_enabled.setChecked(trigger.enabled)
        self._trigger_regex.setChecked(trigger.regex)
        self._trigger_source.setText(trigger.source)
        self._trigger_category.setCurrentText(trigger.category)
        self._category_enabled.setChecked(
            config.data['spells']['trigger_categories'].get(
                trigger.category, True))
        self._trigger_profile.setText(trigger.profile)
        self._trigger_zone.setText(trigger.zone)
        self._trigger_comments.setText(trigger.comments)
        self._trigger_alert.setText(trigger.alert_text)
        self._trigger_color.set_value(trigger.text_color)
        self._set_combo_data(self._trigger_overlay, trigger.overlay_id)
        self._set_combo_data(
            self._trigger_restart, trigger.restart_behavior)
        self._trigger_timer_name.setText(trigger.timer_name)
        self._trigger_restart_name.setChecked(
            trigger.restart_based_on_timer_name)
        self._trigger_end_text.setText(trigger.end_text)
        self._load_end_patterns(trigger)
        set_sound_combo_value(self._trigger_sound, trigger.sound_path)
        self._set_combo_data(self._trigger_timer_type, trigger.timer_type)
        self._trigger_visible_seconds.setValue(trigger.timer_visible_seconds)
        self._trigger_counter_reset.setValue(trigger.counter_reset_seconds)
        self._trigger_clipboard.setText(trigger.clipboard_text)
        self._trigger_tts.setText(trigger.tts_text)
        self._trigger_interrupt_speech.setChecked(trigger.interrupt_speech)
        self._trigger_ending_seconds.setValue(trigger.timer_ending_seconds)
        self._trigger_ending_alert.setText(trigger.timer_ending_alert)
        set_sound_combo_value(
            self._trigger_ending_sound, trigger.timer_ending_sound)
        self._trigger_ending_tts.setText(trigger.timer_ending_tts)
        self._trigger_ending_interrupt.setChecked(
            trigger.timer_ending_interrupt)
        self._trigger_ended_alert.setText(trigger.timer_ended_alert)
        set_sound_combo_value(
            self._trigger_ended_sound, trigger.timer_ended_sound)
        self._trigger_ended_tts.setText(trigger.timer_ended_tts)
        self._trigger_ended_interrupt.setChecked(
            trigger.timer_ended_interrupt)

    def _add_trigger(self):
        category = self._selected_group_path()
        self._current_trigger = ''
        self._clear()
        self._trigger_category.setCurrentText(category)
        self._save_trigger_button.setEnabled(True)
        self._trigger_name.setPlaceholderText('<new>')
        self._trigger_name.selectAll()
        self._trigger_name.setFocus()
        self._trigger_text.setPlaceholderText('match*me')
        self._trigger_time.setPlaceholderText('hh:mm:ss')

    def _remove_trigger(self):
        name = self._selected_trigger_name()
        if name:
            self._custom_triggers.pop(name, None)
            self._save_to_config()
            self._load_from_config()
            return
        path = self._selected_group_path()
        if path == 'Default':
            QMessageBox.information(
                self, 'Default Group',
                'The Default group is always available and cannot be deleted.')
            return
        parent = path.rsplit('/', 1)[0] if '/' in path else 'Default'
        for trigger in self._custom_triggers.values():
            if (trigger.category == path or
                    trigger.category.startswith(path + '/')):
                trigger.category = parent
        groups = normalize_trigger_groups(config.data['spells'])
        config.data['spells']['trigger_groups'] = {
            group: definition for group, definition in groups.items()
            if group != path and not group.startswith(path + '/')}
        self._save_to_config()
        self._load_from_config(selected_group=parent)

    def _save_trigger(self):
        if self._current_trigger is None:
            category = self._selected_group_path()
            profile = self._category_scope_profile()
            set_group_enabled(
                config.data['spells'], category,
                self._category_enabled.isChecked(), profile)
            set_group_style(
                config.data['spells'], category,
                {'font_color': self._category_color.value()}, profile)
            self._save_to_config()
            self._load_from_config(selected_group=category)
            return
        if self._trigger_name.text():
            # validate text and time
            timer_type = self._trigger_timer_type.currentData()
            time_value = self._trigger_time.text().strip()
            valid_time = bool(re.fullmatch(
                r'\d{1,5}:[0-5]\d:[0-5]\d', time_value))
            if timer_type in ('none', 'stopwatch') and not time_value:
                valid_time = True
            if timer_type in ('countdown', 'repeating'):
                dynamic_time = '{ts}' in self._trigger_text.text().casefold()
                valid_time = dynamic_time or (
                    valid_time and text_time_to_seconds(time_value) > 0)
            if self._trigger_text.text() and valid_time:
                if self._trigger_name.text() in self._custom_triggers and \
                        not self._trigger_name.text() == self._current_trigger:
                    m = QMessageBox()
                    m.setText("A custom trigger with this name already exists.")
                    m.exec()
                    return
                elif not self._trigger_name.text() == self._current_trigger and \
                        self._current_trigger not in ('', None):
                    # update name and info
                    ct = self._custom_triggers.pop(self._current_trigger)
                    ct.name = self._trigger_name.text()
                    ct.text = self._trigger_text.text()
                    ct.time = self._trigger_time.text()
                    self._apply_extra_fields(ct)
                    self._custom_triggers[ct.name] = ct
                elif self._current_trigger == '':
                    # new trigger
                    ct = CustomTrigger(
                        self._trigger_name.text(),
                        self._trigger_text.text(),
                        self._trigger_time.text(),
                        self._trigger_zone.text().strip(),
                        str(self._trigger_sound.currentData() or DEFAULT_SOUND),
                        self._trigger_alert.text().strip(),
                        self._trigger_enabled.isChecked(),
                        self._trigger_regex.isChecked(),
                        'Vantage',
                        self._trigger_category.currentText().strip() or 'Default',
                        str(self._trigger_overlay.currentData()),
                        str(self._trigger_restart.currentData()),
                        self._trigger_end_text.text().strip(),
                        self._trigger_profile.text().strip(),
                    )
                    self._apply_extra_fields(ct)
                    self._custom_triggers[ct.name] = ct
                else:
                    # update
                    ct = self._custom_triggers[self._current_trigger]
                    ct.text = self._trigger_text.text()
                    ct.time = self._trigger_time.text()
                    self._apply_extra_fields(ct)
                    self._custom_triggers[self._current_trigger] = ct

                # save and reload
                saved_name = ct.name
                self._save_to_config()
                self._load_from_config(selected_name=saved_name)

            else:
                m = QMessageBox()
                m.setText(
                    "Log text is required. Countdown and repeating timers "
                    "also need a duration greater than 00:00:00 or a {ts} "
                    "dynamic duration token in the search text.")
                m.exec()

    def _activated(self, *_):
        if self._tree_loading:
            return
        name = self._selected_trigger_name()
        if name and name in self._custom_triggers:
            self._current_trigger = name
            self._display_trigger(self._custom_triggers[name])
            self._save_trigger_button.setEnabled(True)
            return
        self._current_trigger = None
        path = self._selected_group_path()
        self._clear()
        self._trigger_category.setCurrentText(path)
        self._category_changed()
        self._save_trigger_button.setEnabled(True)

    def _clear(self):
        self._trigger_name.clear()
        self._trigger_text.clear()
        self._trigger_time.clear()
        self._trigger_enabled.setChecked(True)
        self._trigger_regex.setChecked(False)
        self._trigger_source.setText('Vantage')
        self._trigger_category.setCurrentText('Default')
        self._category_enabled.setChecked(True)
        self._category_color.set_value('')
        self._trigger_profile.clear()
        self._trigger_zone.clear()
        self._trigger_comments.clear()
        self._trigger_alert.clear()
        self._trigger_color.set_value('')
        preferred = next((
            overlay_id for overlay_id, settings in
            config.data.get('general', {}).get(
                'notification_overlays', {}).items()
            if settings.get('type', 'text') == 'text'
            and settings.get('enabled', True)), 'none')
        self._set_combo_data(self._trigger_overlay, preferred)
        self._set_combo_data(self._trigger_restart, 'restart')
        self._trigger_timer_name.clear()
        self._trigger_restart_name.setChecked(False)
        self._trigger_end_text.clear()
        self._trigger_enders.setRowCount(0)
        set_sound_combo_value(self._trigger_sound, DEFAULT_SOUND)
        self._set_combo_data(self._trigger_timer_type, 'none')
        self._trigger_visible_seconds.setValue(0)
        self._trigger_counter_reset.setValue(0)
        self._trigger_clipboard.clear()
        self._trigger_tts.clear()
        self._trigger_interrupt_speech.setChecked(False)
        self._trigger_ending_seconds.setValue(0)
        self._trigger_ending_alert.clear()
        set_sound_combo_value(self._trigger_ending_sound, '')
        self._trigger_ending_tts.clear()
        self._trigger_ending_interrupt.setChecked(False)
        self._trigger_ended_alert.clear()
        set_sound_combo_value(self._trigger_ended_sound, '')
        self._trigger_ended_tts.clear()
        self._trigger_ended_interrupt.setChecked(False)

    def _apply_extra_fields(self, trigger):
        trigger.enabled = self._trigger_enabled.isChecked()
        trigger.regex = self._trigger_regex.isChecked()
        trigger.zone = self._trigger_zone.text().strip()
        trigger.alert_text = self._trigger_alert.text().strip()
        trigger.text_color = self._trigger_color.value()
        trigger.sound_path = str(self._trigger_sound.currentData() or DEFAULT_SOUND)
        trigger.category = (
            self._trigger_category.currentText().strip() or 'Default')
        trigger.profile = self._trigger_profile.text().strip()
        trigger.overlay_id = str(self._trigger_overlay.currentData())
        trigger.restart_behavior = str(self._trigger_restart.currentData())
        trigger.timer_name = self._trigger_timer_name.text().strip()
        trigger.restart_based_on_timer_name = (
            self._trigger_restart_name.isChecked())
        trigger.end_patterns = self._end_patterns()
        trigger.end_text = (
            trigger.end_patterns[0]['text'] if trigger.end_patterns else '')
        trigger.comments = self._trigger_comments.text().strip()
        trigger.timer_type = str(self._trigger_timer_type.currentData())
        trigger.timer_visible_seconds = self._trigger_visible_seconds.value()
        trigger.counter_reset_seconds = self._trigger_counter_reset.value()
        trigger.clipboard_text = self._trigger_clipboard.text().strip()
        trigger.tts_text = self._trigger_tts.text().strip()
        trigger.interrupt_speech = self._trigger_interrupt_speech.isChecked()
        trigger.timer_ending_seconds = self._trigger_ending_seconds.value()
        trigger.timer_ending_alert = self._trigger_ending_alert.text().strip()
        trigger.timer_ending_sound = str(
            self._trigger_ending_sound.currentData() or '')
        trigger.timer_ending_tts = self._trigger_ending_tts.text().strip()
        trigger.timer_ending_interrupt = (
            self._trigger_ending_interrupt.isChecked())
        trigger.timer_ended_alert = self._trigger_ended_alert.text().strip()
        trigger.timer_ended_sound = str(
            self._trigger_ended_sound.currentData() or '')
        trigger.timer_ended_tts = self._trigger_ended_tts.text().strip()
        trigger.timer_ended_interrupt = (
            self._trigger_ended_interrupt.isChecked())
        set_group_enabled(
            config.data['spells'], trigger.category,
            self._category_enabled.isChecked(),
            self._category_scope_profile())
        set_group_style(
            config.data['spells'], trigger.category,
            {'font_color': self._category_color.value()},
            self._category_scope_profile())

    def _category_scope_profile(self):
        index = self._category_scope.currentIndex()
        data = self._category_scope.itemData(index) if index >= 0 else None
        if data is not None:
            return str(data).strip()
        text = self._category_scope.currentText().strip()
        return '' if text.casefold() == 'all characters' else text

    def _category_changed(self, *_):
        category = self._trigger_category.currentText().strip() or 'Default'
        profile = self._category_scope_profile()
        self._category_enabled.setChecked(
            group_state(
                config.data['spells'], category, profile))
        self._category_color.set_value(
            group_style(
                config.data['spells'], category, profile).get(
                    'font_color', ''))

    def _show_match_log(self):
        TriggerMatchLogDialog(self).exec()

    def _import_gina(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Import Trigger Pack', '',
            'Trigger packs (*.gtp *.xml *.gtt);;All Files (*)')
        if not path:
            return
        try:
            batch = import_gina_package(path)
        except GinaImportError as error:
            QMessageBox.warning(self, 'Import Failed', str(error))
            return
        preview = GinaImportPreviewDialog(batch, self)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return
        imported = preview.selected_triggers()
        if not imported:
            return
        if hasattr(batch, 'materialize_selected'):
            imported = batch.materialize_selected(imported)
        added = 0
        for trigger in imported:
            base = trigger.name
            name = base
            suffix = 2
            while name in self._custom_triggers:
                name = f'{base[:108]} · {suffix}'
                suffix += 1
            trigger.name = name
            self._custom_triggers[name] = trigger
            added += 1
        self._save_to_config()
        self._load_from_config()
        QMessageBox.information(
            self, 'Import Complete',
            f'{added} triggers were imported and disabled. Enable only the ones you want.')

    def _choose_trigger_sound(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose Trigger Sound', '', 'WAV Audio (*.wav)')
        if path:
            add_custom_sound_to_combo(
                self._trigger_sound, store_portable_file(path))

    def _choose_stage_sound(self, combo):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose Trigger Stage Sound', '', 'WAV Audio (*.wav)')
        if path:
            add_custom_sound_to_combo(combo, store_portable_file(path))

    def _close(self, _):
        self._save_to_config()
        self.accept()

    def closeEvent(self, _):
        self._save_to_config()
        self.accept()
