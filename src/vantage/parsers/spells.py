import datetime
import copy
import functools
import json
import math
import string
import re
import sqlite3
import time
from collections import deque

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox,
                             QFileDialog, QFrame, QHBoxLayout, QInputDialog,
                             QLabel, QMenu, QProgressBar, QScrollArea,
                             QSpinBox, QSizePolicy, QToolButton, QVBoxLayout,
                             QPushButton, QWidget)

from vantage.helpers.parser import ParserWindow
from vantage.helpers import config, format_time, resource_path, text_time_to_seconds
from vantage.helpers.audio import (
    play_alert, sound_choices, sound_display_name, speak_text)
from vantage.helpers.bard_counts import BardAeCounter
from vantage.helpers.boats import (
    BOAT_ROUTES, route_for_announcement, schedules_from_activities)
from vantage.helpers.icons import game_icon, game_pixmap
from vantage.helpers.log_events import extract_killed_mob
from vantage.helpers.portable import data_dir, store_portable_file
from vantage.helpers.respawn_catalog import named_spawn_for
from vantage.helpers.spell_icons import (
    spell_icon_pixmap, spell_icon_coordinates)
from vantage.helpers.trigger_groups import (
    effective_trigger_style, group_enabled, normalize_trigger_color)


TOKEN_RX = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)\}")
GROUP_REF_RX = re.compile(r"\$(?:\{(\d+)\}|(\d+))")
DISCIPLINE_COOLDOWN_RX = re.compile(
    r"^You can use the ability (?P<name>[\w` ]+) again in "
    r"(?P<minutes>\d+) (?:minute\(s\)|minutes?) "
    r"(?P<seconds>\d+) seconds?\.$", re.IGNORECASE)
MEND_COOLDOWN_LINES = {
    "You mend your wounds and heal some damage.",
    "You have failed to mend your wounds.",
}
ITEM_GLOW_RX = re.compile(
    r"^Your (?P<item>[A-Z][^.]*?) "
    r"(?:begin(?:s)? to glow(?:[^.]*)?|glows?(?:[^.]*))\.$")
ITEM_CLICK_WINDOW_SECONDS = 15.0
CHARM_TARGET_WINDOW_SECONDS = 45.0
# Log lines have one-second timestamps and the file reader polls independently
# from Qt's timers. Keep a small late-arrival margin so a valid landing line
# cannot lose its cast merely because the UI event loop ran first.
SPELL_LANDING_GRACE_MS = 3000
# EQ can report the replaced copy's worn-off line just after the refreshed
# landing line. Only an actual recast receives this short guard; first casts
# and later fades remain authoritative.
RECAST_WORN_OFF_GRACE_SECONDS = 3.0
CHARMED_PET_ACTIVITY_RX = re.compile(
    r"^(?P<pet>[\w`' -]+) tells you, 'Attacking .+? Master\.'$",
    re.IGNORECASE)
CHARM_BREAK_LINES = {
    'your charm spell has worn off.',
    'you are no longer charmed.',
}
SPELL_WORN_OFF_RX = re.compile(
    r'^Your (?P<spell>.+?) spell has worn off\.$', re.IGNORECASE)
SPELL_RESIST_RX = re.compile(
    r'^Your target resisted the (?P<spell>.+?) spell\.$', re.IGNORECASE)
COMMON_ITEM_CLICK_SPELLS = {
    "journeyman's boots": "JourneymanBoots",
    "elder spiritist's gauntlets": "Snare",
    "elder spiritist's vambraces": "Drones of Doom",
    "spear of fate": "Curse of the Spirits",
    "fungi covered great staff": "Fungal Regrowth",
}


@functools.lru_cache(maxsize=1)
def _p99_click_spell_names():
    """Return the shipped Project 1999 Wiki clicky item/effect index."""
    try:
        with open(resource_path(
                'data/spells/p99_clickies.json'), encoding='utf-8') as source:
            payload = json.load(source)
    except (OSError, ValueError, TypeError):
        return {}
    items = payload.get('items', {}) if isinstance(payload, dict) else {}
    return {
        str(item).strip().casefold(): str(effect).strip()
        for item, effect in items.items()
        if str(item).strip() and str(effect).strip()
    }


@functools.lru_cache(maxsize=512)
def item_click_spell_name(item_name):
    """Resolve an item to its exact P99 click spell from the cached index."""
    item_name = str(item_name or '').strip()
    common = COMMON_ITEM_CLICK_SPELLS.get(item_name.casefold())
    if common:
        return common
    database = data_dir('cache', create=False) / 'p99-item-metadata.sqlite'
    if database.is_file():
        try:
            with sqlite3.connect(
                    f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
                row = connection.execute(
                    "SELECT clickName FROM items WHERE name = ? COLLATE NOCASE "
                    "AND trim(coalesce(clickName, '')) <> '' LIMIT 1",
                    (item_name,)).fetchone()
            if row and str(row[0]).strip():
                return str(row[0]).strip()
        except sqlite3.Error:
            pass
    return _p99_click_spell_names().get(item_name.casefold(), '')


def _is_charm_spell(spell):
    """Return True for the classic charm family with no target landing text."""
    return bool(
        int(getattr(spell, 'duration_formula', 0) or 0) and
        not str(getattr(spell, 'effect_text_other', '') or '').strip() and
        str(getattr(spell, 'effect_text_you', '') or '').strip().casefold() ==
        'you have been charmed.')


def _charmed_pet_from_activity(text):
    """Extract the controlled NPC from a player-owned pet activity line."""
    match = CHARMED_PET_ACTIVITY_RX.match(str(text or '').strip())
    return match.group('pet').strip() if match else ''


def compile_trigger_pattern(text, character='', raw_regex=False):
    """Compile friendly tokens or an explicitly imported regular expression."""
    parts = []
    captured = set()
    cursor = 0
    for match in TOKEN_RX.finditer(text):
        literal = text[cursor:match.start()]
        parts.append(literal if raw_regex else re.escape(literal).replace(r'\*', '.*'))
        token = match.group(1)
        folded = token.casefold()
        if folded == 'c' and character and character != 'ConfigureMe':
            parts.append(re.escape(character))
        elif folded == 'counter':
            parts.append(r'\d+')
        elif folded == 'ts':
            # GINA-compatible dynamic TimeSpan: [days:]hours:minutes:seconds
            # with optional fractional seconds.  A bare value means seconds.
            if '__ts__' in captured:
                parts.append(r'(?P=ts)')
            else:
                parts.append(
                    r'(?P<ts>(?:(?:\d+):){0,3}\d+(?:\.\d+)?)')
                captured.add('__ts__')
        elif token in captured:
            parts.append(f'(?P={token})')
        else:
            parts.append(f"(?P<{token}>[A-Za-z0-9'` .-]+?)")
            captured.add(token)
        cursor = match.end()
    tail = text[cursor:]
    parts.append(tail if raw_regex else re.escape(tail).replace(r'\*', '.*'))
    pattern = ''.join(parts)
    if not raw_regex:
        pattern = '^' + pattern + '$'
    return re.compile(pattern, re.RegexFlag.IGNORECASE)


def render_trigger_text(template, match, trigger):
    values = match.groupdict() if match else {}
    character = (
        getattr(trigger, 'runtime_character', '') or
        config.data['sharing'].get('player_name', ''))
    if character and character != 'ConfigureMe':
        values.update({'c': character, 'C': character})
    values['COUNTER'] = str(trigger.counter)
    rendered = TOKEN_RX.sub(lambda token: values.get(
        token.group(1), values.get(token.group(1).casefold(), token.group(0))), template)

    def numeric_group(reference):
        try:
            return match.group(int(reference.group(1) or reference.group(2))) or ''
        except (IndexError, AttributeError):
            return ''

    return GROUP_REF_RX.sub(numeric_group, rendered) if match else rendered


def dynamic_timer_seconds(match):
    """Resolve a GINA-style ``{ts}`` capture into seconds."""
    if not match:
        return 0.0
    try:
        value = match.groupdict().get('ts') or match.groupdict().get('TS')
    except (AttributeError, IndexError):
        return 0.0
    if not value:
        return 0.0
    try:
        parts = [float(part) for part in str(value).split(':')]
    except ValueError:
        return 0.0
    if not 1 <= len(parts) <= 4:
        return 0.0
    seconds = parts[-1]
    if len(parts) >= 2:
        seconds += parts[-2] * 60
    if len(parts) >= 3:
        seconds += parts[-3] * 3600
    if len(parts) == 4:
        seconds += parts[-4] * 86400
    return max(0.0, min(seconds, 31_536_000.0))


class Spells(ParserWindow):
    """Tracks spell casting, duration, and targets by name."""

    spell_faded = Signal(str, str)

    def __init__(self):
        self.name = "spells"
        super().__init__()
        QApplication.instance()._signals['settings'].spell_triggers_updated.connect(self.load_custom_timers)
        self._setup_ui()
        self.spell_book, self.text_you, self.text_other = create_spell_book()
        self._custom_timers = []  # [(start regex, end regex, CustomTrigger)]
        self._trigger_runs = {}
        self._trigger_history = deque(maxlen=500)
        self._trigger_compile_errors = {}
        self._context_revision = None
        self._bard_counter = BardAeCounter()
        QApplication.instance()._signals['settings'].config_updated.connect(
            self._bard_config_updated)
        self.load_custom_timers()
        self._casting = None  # holds Spell when casting
        self._zoning = None  # holds time of zone or None
        self._spell_trigger = None
        self._pending_charm = None
        self._pending_item_click = None
        self._item_other_effects = sorted(
            ((effect, spell) for effect, spell in self.text_other.items()
             if effect), key=lambda pair: len(pair[0]), reverse=True)
        self._current_zone = config.data['maps'].get('last_zone', '')
        self._active_character = config.data['sharing'].get('player_name', '')
        self._boat_network = QNetworkAccessManager(self)
        self._boat_pending = False
        self._boat_server = ''
        self._boat_refresh_timer = QTimer(self)
        self._boat_refresh_timer.setInterval(5 * 60 * 1000)
        self._boat_refresh_timer.timeout.connect(self._refresh_boat_schedules)
        self._boat_refresh_timer.start()
        if self._boat_toggle.isChecked():
            QTimer.singleShot(0, self._refresh_boat_schedules)
        self._trigger_runtime_timer = QTimer(self)
        self._trigger_runtime_timer.setInterval(250)
        self._trigger_runtime_timer.timeout.connect(
            self._update_custom_trigger_timers)
        self._trigger_runtime_timer.start()
        self._bard_runtime_timer = QTimer(self)
        self._bard_runtime_timer.setInterval(250)
        self._bard_runtime_timer.timeout.connect(self._flush_bard_counts)
        self._bard_runtime_timer.start()
        self._runtime_state_save_timer = QTimer(self)
        self._runtime_state_save_timer.setSingleShot(True)
        self._runtime_state_save_timer.setInterval(200)
        self._runtime_state_save_timer.timeout.connect(
            self._persist_runtime_timer_state)
        self._spell_container.state_changed.connect(
            self._schedule_runtime_timer_state_save)
        self._refresh_character_profiles()
        self._restore_runtime_timer_state()
        QApplication.instance().aboutToQuit.connect(
            self._persist_runtime_timer_state)

    def _setup_ui(self):
        self._spell_container = SpellContainer()
        self._boat_group = BoatScheduleGroup()
        self._bard_group = BardCountGroup()
        self._spell_container.set_boat_group(self._boat_group)
        self._spell_container.set_bard_group(self._bard_group)
        self._bard_group.set_enabled(
            config.data['spells'].get('bard_count_enabled', False))
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setWidget(self._spell_container)
        self._scroll_area.setObjectName('SpellScrollArea')
        self.content.addWidget(self._scroll_area, 1)
        # Recent spell outcomes live beside the timer rows that caused them.
        # The tray is heightless while empty and grows to at most three compact
        # pills, so it does not reserve another permanent status line.
        self._event_tray = QFrame()
        self._event_tray.setObjectName('SpellEventTray')
        self._event_layout = QVBoxLayout(self._event_tray)
        self._event_layout.setContentsMargins(3, 2, 3, 2)
        self._event_layout.setSpacing(2)
        self._event_pills = deque()
        self._event_tray.hide()
        self.content.addWidget(self._event_tray, 0)
        self._custom_timer_toggle = QPushButton()
        self._custom_timer_toggle.setIcon(game_icon('timer'))
        self._custom_timer_toggle.setCheckable(True)
        self._custom_timer_toggle.setToolTip(
            'Enable or disable custom triggers and timers')
        self._custom_timer_toggle.setAccessibleName(
            'Enable or disable custom triggers')
        self._custom_timer_toggle.setChecked(config.data['spells']['use_custom_triggers'])
        self._custom_timer_toggle.clicked.connect(self._toggle_custom_timers)
        self.menu_area.addWidget(self._custom_timer_toggle)
        self._boat_toggle = QToolButton()
        self._boat_toggle.setObjectName('CompactMenuButton')
        self._boat_toggle.setIcon(game_icon('timer'))
        self._boat_toggle.setCheckable(True)
        self._boat_toggle.setChecked(
            config.data['spells'].get('show_boat_schedules', False))
        self._boat_toggle.setAccessibleName('Show P99 boat schedules')
        self._boat_toggle.setToolTip(
            'Show or hide compact P99 boat arrivals; use the arrow to refresh or inspect the PigParse source')
        self._boat_toggle.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        boat_menu = QMenu(self._boat_toggle)
        boat_menu.setToolTipsVisible(True)
        refresh = boat_menu.addAction('Refresh boat data')
        refresh.setToolTip(
            'Fetch the latest Green, Blue, Red, or Quarm observation from PigParse')
        refresh.triggered.connect(self._manual_refresh_boats)
        source = boat_menu.addAction('Open PigParse source')
        source.setToolTip(
            'Open the public PigParse page used as the remote source of truth')
        source.triggered.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://pigparse.azurewebsites.net/')))
        self._boat_toggle.setMenu(boat_menu)
        self._boat_toggle.clicked.connect(self._toggle_boat_schedules)
        self.menu_area.addWidget(self._boat_toggle)
        self._boat_group.set_enabled(self._boat_toggle.isChecked())
        self._library_button = QPushButton()
        self._library_button.setIcon(game_icon('search'))
        self._library_button.setAccessibleName('Open P99 Spell Library')
        self._library_button.setToolTip(
            'Search P99 spells by class and level, with Wiki acquisition and prices')
        self._library_button.clicked.connect(
            QApplication.instance().show_spell_library)
        self.menu_area.addWidget(self._library_button)
        # At small physical widths the full logical surface is scaled down,
        # but three adjacent spell tools still starve the title. Collapse the
        # two lower-frequency tools into one accessible menu while preserving
        # every action and tooltip.
        self._header_tools_button = QToolButton()
        self._header_tools_button.setObjectName('CompactMenuButton')
        self._header_tools_button.setIcon(game_icon('ph-stack'))
        self._header_tools_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self._header_tools_button.setAccessibleName('More spell tools')
        self._header_tools_button.setToolTip(
            'Boat schedules, source details, and the P99 Spell Library')
        spell_tools_menu = QMenu(self._header_tools_button)
        spell_tools_menu.setToolTipsVisible(True)
        self._compact_boat_action = spell_tools_menu.addAction(
            'Show P99 boat schedules')
        self._compact_boat_action.setCheckable(True)
        self._compact_boat_action.setChecked(self._boat_toggle.isChecked())
        self._compact_boat_action.setToolTip(
            'Show or hide compact P99 boat arrivals from PigParse')
        self._compact_boat_action.triggered.connect(
            self._set_compact_boat_schedules)
        compact_refresh = spell_tools_menu.addAction('Refresh boat data')
        compact_refresh.setToolTip(
            'Fetch the latest boat observation from PigParse')
        compact_refresh.triggered.connect(self._manual_refresh_boats)
        compact_source = spell_tools_menu.addAction('Open PigParse source')
        compact_source.setToolTip(
            'Open the public source used for boat observations')
        compact_source.triggered.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://pigparse.azurewebsites.net/')))
        spell_tools_menu.addSeparator()
        compact_library = spell_tools_menu.addAction('Open P99 Spell Library')
        compact_library.setToolTip(
            'Search spells by class and level, including acquisition details')
        compact_library.triggered.connect(
            QApplication.instance().show_spell_library)
        self._header_tools_button.setMenu(spell_tools_menu)
        self.menu_area.addWidget(self._header_tools_button)
        self._header_tools_button.hide()
        self._character_widget = QComboBox()
        self._character_widget.setObjectName('SpellCharacterProfile')
        self._character_widget.setMinimumContentsLength(8)
        self._character_widget.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._character_widget.setAccessibleName('Spell timer character')
        self._character_widget.setToolTip(
            'Choose which character timers are shown; each character remembers '
            'its own level')
        self._character_widget.currentIndexChanged.connect(
            self._character_profile_changed)
        self._add_character_button = QToolButton()
        self._add_character_button.setObjectName('CompactMenuButton')
        self._add_character_button.setIcon(game_icon('add'))
        self._add_character_button.setAccessibleName('Add spell timer character')
        self._add_character_button.setToolTip(
            'Add a character profile and remember a separate spell level')
        self._add_character_button.clicked.connect(self._add_character_profile)
        self._level_widget = QSpinBox()
        self._level_widget.setObjectName('SpellLevelRocker')
        self._level_widget.setRange(1, 65)
        self._level_widget.setValue(config.data['spells']['level'])
        self._level_widget.setPrefix('Lv ')
        self._level_widget.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self._level_widget.setAccelerated(True)
        self._level_widget.setAccessibleName('Character level')
        self._level_widget.setAccessibleDescription(
            'Use the integrated up and down rocker or the keyboard arrow keys '
            'to change the level used for spell durations')
        self._level_widget.setToolTip(
            'Character level · use the integrated rocker or Up/Down keys')
        self._level_widget.valueChanged.connect(self._level_change)
        # Profiles live in a slim content strip, not the title header. This
        # preserves the fixed 22 px window chrome and prevents controls from
        # overlapping when the complete panel replica is scaled down.
        self._profile_bar = QWidget()
        self._profile_bar.setObjectName('SpellProfileBar')
        profile_layout = QHBoxLayout(self._profile_bar)
        profile_layout.setContentsMargins(3, 1, 3, 1)
        profile_layout.setSpacing(2)
        self._profile_label = QLabel('Character')
        self._profile_label.setToolTip(
            'Timers can be filtered by character and each profile keeps its level')
        profile_layout.addWidget(self._profile_label, 0)
        profile_layout.addWidget(self._character_widget, 1)
        profile_layout.addWidget(self._add_character_button, 0)
        profile_layout.addWidget(self._level_widget, 0)
        self.content.insertWidget(1, self._profile_bar, 0)
        self._camp_state = ''
        self._update_profile_bar_density()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_profile_bar_density()

    def _update_profile_bar_density(self):
        """Keep every profile field readable in genuinely tiny replicas."""
        if not hasattr(self, '_profile_label'):
            return
        compact = self.width() < 250
        very_compact = self.width() < 150
        self._profile_label.setVisible(not compact)
        self._add_character_button.setVisible(not very_compact)
        self._level_widget.setPrefix('Lv ')
        self._character_widget.setMinimumWidth(44 if compact else 72)
        # Reserve the complete prefix/value plus the in-field rocker. This is
        # calculated from the active font so DPI or font scaling cannot place
        # the step controls over the number.
        level_text_width = self._level_widget.fontMetrics().horizontalAdvance(
            f'Lv {self._level_widget.maximum()}')
        # Keep the complete label clear of both embedded rocker halves even at
        # fractional overlay scale. The previous 70 px capsule let Windows'
        # native edit margins cover the leading ``L`` in ``Lv 60``.
        level_width = max(82, level_text_width + 56)
        self._level_widget.setFixedWidth(level_width)
        compact_header = self.width() < 215
        self._boat_toggle.setVisible(not compact_header)
        self._library_button.setVisible(not compact_header)
        self._header_tools_button.setVisible(compact_header)
        # Keep the actual title legible instead of allowing a dense run of
        # header actions to collapse it to a few clipped pixels.
        self._title.setMinimumWidth(34 if compact_header else 0)

    def _set_compact_boat_schedules(self, checked):
        """Mirror the narrow-header menu action to the canonical toggle."""
        self._boat_toggle.setChecked(bool(checked))
        self._toggle_boat_schedules(bool(checked))

    def _dismiss_spell_event(self, pill):
        try:
            self._event_pills.remove(pill)
        except ValueError:
            return
        self._event_layout.removeWidget(pill)
        pill.deleteLater()
        self._event_tray.setVisible(bool(self._event_pills))

    def _push_spell_event(self, kind, spell_name='', target_name=''):
        """Show one attributable, temporary outcome at the panel bottom."""
        kind = str(kind or 'EVENT').strip().upper()
        spell_name = string.capwords(str(spell_name or '').strip())
        spell_name = ' '.join(
            token.upper() if token.casefold() in {
                'ii', 'iii', 'iv', 'vi', 'vii', 'viii', 'ix'} else token
            for token in spell_name.split())
        target_name = str(target_name or '').strip()
        parts = [kind]
        if spell_name:
            parts.append(spell_name)
        if target_name and target_name.casefold() not in {
                '__you__', '__custom__', '__utility__'}:
            parts.append(target_name)
        message = ' · '.join(parts)
        pill = QLabel(message)
        pill.setObjectName('SpellEventPill')
        pill.setProperty('EventKind', kind.casefold().replace(' ', '_'))
        pill.setToolTip(
            f'Recent EQ log event: {message}. This notice clears automatically.')
        pill.setAccessibleName(message)
        pill.setAccessibleDescription(
            'Temporary spell outcome parsed from the linked EverQuest log')
        pill.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        pill.setFixedHeight(20)
        self._event_layout.insertWidget(0, pill)
        self._event_pills.appendleft(pill)
        while len(self._event_pills) > 3:
            self._dismiss_spell_event(self._event_pills[-1])
        self._event_tray.show()
        QTimer.singleShot(12_000, lambda item=pill: self._dismiss_spell_event(item))
        return pill

    def recent_spell_events(self):
        """Return visible event text for diagnostics, mobile, and tests."""
        return [pill.text() for pill in self._event_pills]

    def _line_has_custom_audio(self, text):
        """Avoid playing both a row-fade sound and a matching trigger sound."""
        active_character = (
            self._active_character or
            config.data.get('sharing', {}).get('player_name', ''))
        for rx, _end_rxs, trigger in self._custom_timers:
            match = rx.match(text)
            captured_character = (
                match.groupdict().get('c') if match else '')
            if (match and trigger.enabled and
                    (trigger.sound_path or trigger.tts_text) and
                    group_enabled(
                        config.data['spells'], trigger.category,
                        active_character) and
                    (not trigger.profile or trigger.profile.casefold() ==
                     active_character.casefold()) and
                    (not captured_character or not active_character or
                     captured_character.casefold() ==
                     active_character.casefold()) and
                    (not trigger.zone or trigger.zone.casefold() ==
                     self._current_zone.casefold())):
                return True
        return False

    @staticmethod
    def _profile_key(character='', server=''):
        return (
            f'{str(server or "").strip().casefold()}|'
            f'{str(character or "").strip().casefold()}')

    def _refresh_character_profiles(self, preferred_key=None):
        profiles = config.data.get('general', {}).get(
            'character_profiles', {})
        selected_key = str(
            preferred_key if preferred_key is not None else
            config.data['spells'].get('active_character_key', ''))
        self._character_widget.blockSignals(True)
        self._character_widget.clear()
        self._character_widget.addItem(
            'All', {'key': '', 'character': '', 'server': '',
                    'level': config.data['spells']['level']})
        for raw_key, values in sorted(
                profiles.items(), key=lambda pair: (
                    str(pair[1].get('character', '')).casefold(),
                    str(pair[1].get('server', '')).casefold())):
            if not isinstance(values, dict):
                continue
            character = str(values.get('character') or '').strip()[:64]
            server = str(values.get('server') or '').strip()[:64]
            if not character:
                continue
            try:
                level = max(1, min(65, int(
                    values.get('level') or config.data['spells']['level'])))
            except (TypeError, ValueError):
                level = max(1, min(65, int(config.data['spells']['level'])))
            key = self._profile_key(character, server)
            label = character + (f' · {server}' if server else '')
            self._character_widget.addItem(label, {
                'key': key or str(raw_key), 'character': character,
                'server': server, 'level': level})
        index = self._character_widget.findData(
            selected_key, role=Qt.ItemDataRole.UserRole)
        if index < 0:
            for candidate in range(self._character_widget.count()):
                values = self._character_widget.itemData(candidate) or {}
                if values.get('key') == selected_key:
                    index = candidate
                    break
        self._character_widget.setCurrentIndex(max(0, index))
        self._character_widget.blockSignals(False)
        self._character_profile_changed(
            self._character_widget.currentIndex(), persist=False)

    def _selected_character_profile(self):
        values = self._character_widget.currentData()
        return values if isinstance(values, dict) else {
            'key': '', 'character': '', 'server': '',
            'level': config.data['spells']['level']}

    def _character_profile_changed(self, _index, persist=True):
        profile = self._selected_character_profile()
        character = str(profile.get('character') or '')
        server = str(profile.get('server') or '')
        level = max(1, min(65, int(
            profile.get('level') or config.data['spells']['level'])))
        self._level_widget.blockSignals(True)
        self._level_widget.setValue(level)
        self._level_widget.blockSignals(False)
        self._level_widget.setAccessibleName(
            f'Level for {character}' if character else 'Default spell level')
        self._spell_container.set_profile_filter(character, server)
        if persist:
            config.data['spells']['active_character_key'] = str(
                profile.get('key') or '')
            config.data['spells']['level'] = level
            config.save()

    def _add_character_profile(self):
        name, accepted = QInputDialog.getText(
            self, 'Add spell character', 'Character name:')
        character = str(name or '').strip()[:64]
        if not accepted or not character:
            return False
        server = str(getattr(self, '_active_server', '') or '').strip()[:64]
        level = self._level_widget.value()
        app = QApplication.instance()
        updater = getattr(app, 'update_character_level', None)
        if updater:
            updater(character, server, level)
        else:
            key = self._profile_key(character, server)
            profiles = config.data['general'].setdefault(
                'character_profiles', {})
            profiles[key] = {
                'character': character, 'server': server, 'level': level,
                'player_class': '', 'group_leader': '', 'pet_name': '',
                'pet_state': '', 'pet_spell': '', 'zone': '',
                'saved_you_spells': [], 'source': 'Manual profile',
                'revision': 1}
            config.save()
        key = self._profile_key(character, server)
        self._refresh_character_profiles(key)
        config.data['spells']['active_character_key'] = key
        config.save()
        return True

    def _active_cast_level(self):
        context = getattr(self, '_character_context', None)
        if context and int(getattr(context, 'level', 0) or 0) > 0:
            return max(1, min(65, int(context.level)))
        key = self._profile_key(
            getattr(self, '_active_character', ''),
            getattr(self, '_active_server', ''))
        values = config.data.get('general', {}).get(
            'character_profiles', {}).get(key, {})
        try:
            return max(1, min(65, int(
                values.get('level') or config.data['spells']['level'])))
        except (TypeError, ValueError):
            return max(1, min(65, int(config.data['spells']['level'])))

    def _spell_for_active_profile(self, source):
        spell = copy.copy(source)
        spell.runtime_level = self._active_cast_level()
        return spell

    def _schedule_runtime_timer_state_save(self):
        self._runtime_state_save_timer.start()

    def _persist_runtime_timer_state(self):
        self.checkpoint_runtime_state()

    def checkpoint_runtime_state(self):
        """Synchronously preserve every active buff before an app handoff."""
        self._runtime_state_save_timer.stop()
        config.data['spells']['active_timer_state'] = \
            self._spell_container.snapshot_runtime_state()
        if getattr(config, '_filename', ''):
            config.save()
        return len(config.data['spells']['active_timer_state'])

    def _restore_runtime_timer_state(self):
        saved = config.data['spells'].get('active_timer_state', [])
        restored = self._spell_container.restore_runtime_state(
            saved, self.spell_book)
        # Drop expired or malformed rows immediately. Absolute deadlines mean
        # the remaining values are already current after any offline interval.
        cleaned = self._spell_container.snapshot_runtime_state()
        if cleaned != saved:
            config.data['spells']['active_timer_state'] = cleaned
            if getattr(config, '_filename', ''):
                config.save()
        return restored

    def _spell_triggered(self, trigger=None):
        """SpellTrigger spell_triggered event handler. """
        trigger = trigger or self._spell_trigger
        # A timeout already queued by Qt must never complete whichever newer
        # cast happens to be current. The emitting trigger owns its result.
        if trigger is not self._spell_trigger:
            return
        if trigger:
            for index in range(len(trigger.targets)):
                self._spell_target_detected(trigger, index)
            if (not trigger.targets and _is_charm_spell(trigger.spell)):
                # Classic EQ does not print a normal target landing line for
                # charm. A failure removes the trigger before this point; a
                # completed window may therefore wait for player-owned pet
                # activity to identify the controlled NPC.
                self._pending_charm = (trigger.timestamp, trigger.spell)
        self._remove_spell_trigger(trigger)

    def _spell_target_detected(self, trigger, target_index):
        """Paint a confirmed landing immediately, including group spells."""
        if trigger is not self._spell_trigger:
            return False
        try:
            target_index = int(target_index)
            timestamp, target_name = trigger.targets[target_index]
        except (IndexError, TypeError, ValueError):
            return False
        if target_index in trigger.delivered_target_indexes:
            return False
        spell = self._spell_for_active_profile(trigger.spell)
        self._spell_container.add_spell(
            spell, timestamp, target_name,
            getattr(self, '_active_character', ''),
            getattr(self, '_active_server', ''),
            named=self._is_named_target(target_name))
        trigger.delivered_target_indexes.add(target_index)
        return True

    def _consume_charm_activity(self, timestamp, text):
        """Create a charm timer from the first bounded pet activity proof."""
        pending = self._pending_charm
        if not pending:
            return False
        elapsed = (timestamp - pending[0]).total_seconds()
        if elapsed < 0 or elapsed > CHARM_TARGET_WINDOW_SECONDS:
            self._pending_charm = None
            return False
        target = _charmed_pet_from_activity(text)
        if not target:
            return False
        spell = self._spell_for_active_profile(pending[1])
        # Start at estimated landing, not at the later attack/guard message.
        landed = pending[0] + datetime.timedelta(
            milliseconds=max(0, int(getattr(spell, 'cast_time', 0) or 0)))
        self._spell_container.add_spell(
            spell, landed, target,
            getattr(self, '_active_character', ''),
            getattr(self, '_active_server', ''),
            named=self._is_named_target(target))
        self._pending_charm = None
        return True

    def _is_named_target(self, target):
        """Return whether the target is the zone's exact catalogued named."""
        if str(target or '').startswith('__'):
            return False
        # Local import keeps the spell list independent from map rendering.
        from vantage.parsers.maps.mapdata import MapData
        canonical = MapData.resolve_zone_name(self._current_zone)
        if not canonical:
            return False
        short_name = MapData.get_zone_dict().get(canonical)
        return bool(named_spawn_for(short_name, target))

    def parse(self, timestamp, text):
        """Parse casting triggers (casting, failure, success)."""

        self._sync_character_context()
        self._consume_charm_activity(timestamp, text)
        if config.data['spells'].get('bard_count_enabled', False):
            self._handle_bard_summaries(
                self._bard_counter.ingest(timestamp, text))

        server = self._boat_server_name()
        if (self._boat_toggle.isChecked() and server != self._boat_server and
                not self._boat_pending):
            QTimer.singleShot(0, self._refresh_boat_schedules)
        observed_boat = route_for_announcement(text)
        if observed_boat and self._boat_toggle.isChecked():
            schedules = schedules_from_activities([{
                'startPoint': observed_boat.start_point,
                'boat': observed_boat.boat_id,
                'lastSeen': timestamp,
            }], timestamp, source=(
                f'EQ log · {self._active_character}'
                if self._active_character else 'EQ log'))
            self._boat_group.update_schedules(
                schedules, server, replace=False)

        if text.startswith('You have entered '):
            self._current_zone = text[17:].rstrip('.')

        # P99 emits the authoritative cooldown duration after a discipline.
        # This mirrors the studied utility behavior and never guesses from a
        # class table when the line is absent.
        discipline = DISCIPLINE_COOLDOWN_RX.match(text)
        if discipline:
            values = discipline.groupdict()
            seconds = int(values['minutes']) * 60 + int(values['seconds'])
            self._add_builtin_utility_timer(
                values['name'].strip(), seconds, timestamp,
                source_spell=values['name'].strip())
        elif text in MEND_COOLDOWN_LINES:
            self._add_builtin_utility_timer(
                'Mend', 6 * 60, timestamp, source_spell='Chloroplast')

        # Worn-off lines carry no target id. Mark only the oldest matching
        # instance as FADED so the affected mob remains visibly identifiable
        # for a few seconds instead of disappearing without an explanation.
        faded = self._spell_container.mark_worn_off(
            text, timestamp,
            play_sound=not self._line_has_custom_audio(text))
        if faded:
            target = faded.parentWidget()
            target_name = (
                target.target_label.text()
                if target and hasattr(target, 'target_label') else '')
            event_kind = (
                'CHARM BROKE'
                if str(text or '').strip().casefold() in CHARM_BREAK_LINES
                else 'WORN OFF')
            self._push_spell_event(
                event_kind, getattr(faded.spell, 'name', 'Spell'),
                target_name)
            self.spell_faded.emit(
                str(getattr(target, 'name', '')),
                str(getattr(faded.spell, 'name', 'Spell')))
        if str(text or '').strip().casefold() in CHARM_BREAK_LINES:
            self._pending_charm = None

        # EQ gives same-named mobs no stable id. A death therefore retires one
        # deterministic matching instance rather than erasing every copy.
        slain_mob = extract_killed_mob(text)
        if slain_mob:
            self._spell_container.remove_dead_target(slain_mob)

        # custom timers
        if config.data['spells']['use_custom_triggers']:
            for rx, end_rxs, ct in self._custom_timers:
                evaluation_started = time.perf_counter_ns()
                if any(end_rx.match(text) for end_rx in end_rxs):
                    match_us = (
                        time.perf_counter_ns() - evaluation_started) / 1000.0
                    removed = False
                    for run_key in self._trigger_run_keys(ct):
                        removed = self._end_trigger_run(run_key) or removed
                    if removed:
                        self._record_trigger_match(
                            timestamp, ct, text, "Timer ended early",
                            status="Ended early", match_us=match_us)
                    continue
                match = rx.match(text)
                match_us = (
                    time.perf_counter_ns() - evaluation_started) / 1000.0
                active_character = (
                    self._active_character or
                    config.data['sharing'].get('player_name', ''))
                captured_character = (
                    match.groupdict().get('c') if match else '')
                if (match and ct.enabled and
                        group_enabled(
                            config.data['spells'], ct.category,
                            active_character) and
                        (not ct.profile or ct.profile.casefold() ==
                         active_character.casefold()) and
                        (not captured_character or not active_character or
                         captured_character.casefold() ==
                         active_character.casefold()) and
                        (not ct.zone or ct.zone.casefold() == self._current_zone.casefold())):
                    now = time.monotonic()
                    if now - ct.last_fired < 0.75:
                        continue
                    if (ct.counter_reset_seconds and ct.last_fired and
                            now - ct.last_fired > ct.counter_reset_seconds):
                        ct.counter = 0
                    ct.last_fired = now
                    ct.counter += 1
                    ct.runtime_character = active_character
                    timer_name = render_trigger_text(
                        ct.timer_name or ct.name, match, ct)
                    duration = (
                        (dynamic_timer_seconds(match)
                         if '{ts}' in ct.text.casefold() else
                         text_time_to_seconds(ct.time))
                        if ct.timer_type in ('countdown', 'repeating') else 0)
                    output = []
                    start_timer = False
                    display_name = timer_name
                    run_key = ''
                    if ct.timer_type != 'none':
                        matching_runs = self._matching_trigger_runs(
                            ct, timer_name)
                        active = bool(matching_runs)
                        start_timer = not (
                            ct.restart_behavior == 'keep' and active)
                        display_name = (
                            f"{timer_name} #{ct.counter}"
                            if ct.restart_behavior == 'new' else timer_name)
                        if start_timer:
                            if (ct.restart_behavior == 'restart' and
                                    matching_runs):
                                for existing_key, _existing in matching_runs:
                                    self._end_trigger_run(existing_key)
                            if ct.restart_behavior == 'new':
                                run_key = (
                                    f"new:{ct.name}:{time.monotonic_ns()}")
                            elif ct.restart_based_on_timer_name:
                                run_key = f"timer:{timer_name.casefold()}"
                            else:
                                run_key = ct.name
                            if duration > 0:
                                spell = Spell(
                                    name=display_name,
                                    runtime_key=run_key,
                                    duration=max(1, int(math.ceil(duration / 6))),
                                    duration_seconds=duration,
                                    duration_formula=11,
                                    spell_icon=14,
                                    runtime_level=self._active_cast_level())
                                self._spell_container.add_spell(
                                    spell, timestamp, '__custom__',
                                    active_character,
                                getattr(self, '_active_server', ''))
                            if ct.restart_behavior == 'new':
                                ct.active_names.append(run_key)
                            else:
                                ct.active_names[:] = [run_key]
                            self._start_trigger_run(
                                ct, run_key, display_name, duration, match,
                                timestamp)
                            output.append(
                                "Timer restarted" if active else
                                "Stopwatch started" if ct.timer_type == 'stopwatch'
                                else "Timer started")
                        else:
                            output.append("Existing timer kept")
                    if ct.sound_path:
                        play_alert(
                            ct.sound_path,
                            config.data['spells']['fade_sound_volume'], 1,
                            source=f"Trigger · {timer_name}",
                            character=active_character,
                            server=getattr(self, '_active_server', ''),
                            channel='spells')
                        output.append(
                            f"Sound · {sound_display_name(ct.sound_path)}")
                    if ct.tts_text:
                        speak_text(
                            render_trigger_text(ct.tts_text, match, ct),
                            config.data['spells']['fade_sound_volume'],
                            ct.interrupt_speech,
                            source=f"Trigger · {timer_name} · speech",
                            character=active_character,
                            server=getattr(self, '_active_server', ''),
                            channel='spells')
                        output.append("Text-to-speech")
                    if ct.clipboard_text:
                        QApplication.clipboard().setText(
                            render_trigger_text(ct.clipboard_text, match, ct))
                        output.append("Copied resolved text")
                    app = QApplication.instance()
                    show_overlay = (
                        ct.overlay_id != 'none' and
                        ((ct.timer_type != 'none' and start_timer and
                          not self._trigger_runs.get(
                              run_key, {}).get('defer_overlay')) or
                         (ct.timer_type == 'none' and bool(ct.alert_text))))
                    if show_overlay:
                        overlay_text = (
                            render_trigger_text(ct.alert_text, match, ct)
                            if ct.alert_text else f"{ct.category} timer")
                        app.show_overlay_notification(
                            display_name, overlay_text,
                            msecs=3500,
                            overlay_id=ct.overlay_id,
                            countdown_seconds=duration,
                            timer_key=run_key,
                            timer_mode=(
                                'stopwatch' if ct.timer_type == 'stopwatch'
                                else 'countdown'),
                            character=active_character,
                            text_color=self._trigger_text_color(
                                ct, active_character))
                        output.append(f"{ct.overlay_id.title()} overlay")
                    self._record_trigger_match(
                        timestamp, ct, text, " · ".join(output) or "Matched",
                        status="Matched", match_us=match_us)

        # Item clicks need their own correlation path. P99 commonly logs
        # ``You begin casting ...`` followed by ``Your <item> begins to glow``;
        # the item's real cast time can differ from the spell record. Instant
        # clickies may emit only the glow and landing lines. Keep a short,
        # player-owned glow anchor so these effects are tracked without opening
        # a broad window for another player's spell landing.
        item_glow = (
            ITEM_GLOW_RX.match(text)
            if config.data['spells']['use_item_triggers'] else None)
        if item_glow:
            item_name = item_glow.group('item').strip()
            self._pending_item_click = (
                timestamp, item_name, item_click_spell_name(item_name))
            if self._spell_trigger:
                self._spell_trigger.mark_item_cast(item_name, timestamp)
        elif (config.data['spells']['use_item_triggers'] and
              self._pending_item_click):
            self._consume_item_effect(timestamp, text)
        else:
            self._pending_item_click = None

        if self._spell_trigger:
            self._spell_trigger.parse(timestamp, text)

        # Initial Spell Cast and trigger setup
        if text[:17] == 'You begin casting':
            spell = self.spell_book.get(text[18:-1], None)
            if spell and spell.duration_formula != 0:
                self._spell_triggered()  # in case we cut off the cast window, force trigger
                self._remove_spell_trigger()
                if _is_charm_spell(spell):
                    self._pending_charm = None

                spell_trigger = SpellTrigger(
                    spell=spell,
                    timestamp=timestamp
                )
                spell_trigger.target_detected.connect(
                    self._spell_target_detected)
                spell_trigger.spell_triggered.connect(self._spell_triggered)
                self._spell_trigger = spell_trigger

        # Spell Interrupted. A resist names its spell, so a delayed resist from
        # an earlier cast must not cancel a newer unrelated trigger.
        else:
            resist = SPELL_RESIST_RX.match(text)
            current_name = (
                str(self._spell_trigger.spell.name).strip().casefold()
                if self._spell_trigger else '')
            resist_name = resist.group('spell').strip() if resist else ''
            matching_resist = bool(
                resist and current_name == resist_name.casefold())
        if (text[:17] != 'You begin casting' and self._spell_trigger and (
              text == 'Your spell is interrupted.' or
              text == 'Your spell fizzles!' or
              matching_resist or
              text.startswith('Your spell did not take hold.') or
              text.startswith('You try to cast a spell on'))):
            failed_spell = self._spell_trigger.spell
            interrupted_charm = _is_charm_spell(failed_spell)
            event_kind = (
                'RESIST' if matching_resist else
                'FIZZLE' if text == 'Your spell fizzles!' else
                'INTERRUPTED' if text == 'Your spell is interrupted.' else
                'DID NOT HOLD' if text.startswith(
                    'Your spell did not take hold.') else 'CAST BLOCKED')
            self._push_spell_event(event_kind, failed_spell.name)
            self._remove_spell_trigger()
            if interrupted_charm:
                self._pending_charm = None

        elif (text[:17] != 'You begin casting' and resist and
              not matching_resist):
            # Still make the P99 outcome visible, but preserve any newer cast
            # that is currently waiting for its own landing line.
            self._push_spell_event('RESIST', resist_name)

        # Elongate self buff timers by time zoning
        elif text[:23] == 'LOADING, PLEASE WAIT...':
            self._spell_triggered()
            self._remove_spell_trigger()
            self._zoning = timestamp
            spell_target = self._spell_container.get_spell_target_by_name(
                '__you__')
            if spell_target:
                for spell_widget in spell_target.spell_widgets():
                    spell_widget.pause()
        elif self._zoning and text[:16] == 'You have entered':
            self._current_zone = text[17:].rstrip('.')
            delay = (timestamp - self._zoning).total_seconds()
            # If zoning took longer than like two minutes, likely false alarm
            if delay > 120:
                self._zoning = None
            else:
                spell_target = self._spell_container.get_spell_target_by_name(
                    '__you__')
                if spell_target:
                    for spell_widget in spell_target.spell_widgets():
                        spell_widget.elongate(delay)
                        spell_widget.resume()

    def _consume_item_effect(self, timestamp, text):
        """Add a confirmed or item-only landing that has no cast trigger."""
        if self._spell_trigger:
            return False
        pending = self._pending_item_click
        item_name = ''
        if pending:
            elapsed = (timestamp - pending[0]).total_seconds()
            if elapsed < 0 or elapsed > ITEM_CLICK_WINDOW_SECONDS:
                self._pending_item_click = None
                pending = None
            else:
                item_name = pending[1]

        preferred = pending[2] if pending and len(pending) > 2 else ''
        landing = self._item_effect_landing(
            text, include_other=bool(pending), preferred_spell=preferred)
        if not landing:
            return False
        spell, target = landing
        # A self landing with no glow/cast anchor is accepted only when the
        # client marks the spell unavailable to every playable class. This is
        # how truly item-only instant effects are represented in spells_us.
        if not pending and not getattr(spell, 'item_only', False):
            return False
        self._pending_item_click = None
        detected = copy.copy(spell)
        detected.source_item = item_name or 'Item-only effect'
        detected.runtime_level = self._active_cast_level()
        self._spell_container.add_spell(
            detected, timestamp, target,
            getattr(self, '_active_character', ''),
            getattr(self, '_active_server', ''),
            named=self._is_named_target(target))
        return True

    def _item_effect_landing(
            self, text, include_other=False, preferred_spell=''):
        preferred = self.spell_book.get(str(preferred_spell or ''))
        if preferred and preferred.duration_formula != 0:
            if preferred.effect_text_you and text == preferred.effect_text_you:
                return preferred, '__you__'
            if (include_other and preferred.effect_text_other and
                    text.endswith(preferred.effect_text_other)):
                target = text[:-len(preferred.effect_text_other)].strip()
                if target:
                    return preferred, target
        spell = self.text_you.get(text)
        if (spell and spell.effect_text_you and
                spell.duration_formula != 0):
            return spell, '__you__'
        if include_other:
            for effect, candidate in self._item_other_effects:
                if (candidate.duration_formula != 0 and
                        text.endswith(effect)):
                    target = text[:-len(effect)].strip()
                    if target:
                        return candidate, target
        return None

    def _add_builtin_utility_timer(
            self, name, seconds, timestamp, source_spell=''):
        seconds = max(1, int(seconds))
        source = self.spell_book.get(source_spell)
        if source is None and source_spell == 'Chloroplast':
            source = self.spell_book.get('Regeneration')
        spell = Spell(
            name=str(name).strip() or 'Ability cooldown',
            runtime_key=f"utility:{str(name).strip().casefold()}",
            duration=max(1, int(math.ceil(seconds / 6))),
            duration_seconds=seconds,
            duration_formula=11,
            spell_icon=(source.spell_icon if source else 14),
            type=1,
            runtime_level=self._active_cast_level())
        self._spell_container.add_spell(
            spell, timestamp, '__utility__',
            getattr(self, '_active_character', ''),
            getattr(self, '_active_server', ''))

    def _bard_config_updated(self):
        enabled = config.data['spells'].get('bard_count_enabled', False)
        self._bard_group.set_enabled(enabled)
        if not enabled:
            self._bard_counter.reset()

    def _flush_bard_counts(self):
        if not config.data['spells'].get('bard_count_enabled', False):
            return
        self._handle_bard_summaries(self._bard_counter.flush())

    def _handle_bard_summaries(self, summaries):
        for summary in summaries:
            self._bard_group.add_summary(summary)
            if config.data['spells'].get('bard_count_overlay', True):
                QApplication.instance().show_overlay_notification(
                    'Bard AE Count', summary.text, msecs=5000,
                    overlay_id='alerts',
                    character=getattr(self, '_active_character', ''),
                    text_color='#D2B873')
            if config.data['spells'].get('bard_count_audio', False):
                speak_text(
                    summary.text,
                    config.data['spells']['fade_sound_volume'], True,
                    source='Bard AE Count',
                    character=getattr(self, '_active_character', ''),
                    server=getattr(self, '_active_server', ''),
                    channel='spells')

    def _trigger_run_keys(self, trigger):
        """Return every live internal run owned by one trigger definition."""
        return [
            key for key, run in self._trigger_runs.items()
            if run.get('trigger') is trigger]

    def _matching_trigger_runs(self, trigger, display_name):
        """Apply GINA's optional cross-trigger TimerName restart scope."""
        if trigger.restart_based_on_timer_name:
            folded = str(display_name or '').casefold()
            return [
                (key, run) for key, run in self._trigger_runs.items()
                if str(run.get('name') or '').casefold() == folded]
        run = self._trigger_runs.get(trigger.name)
        return [(trigger.name, run)] if run else []

    def _end_trigger_run(self, run_key):
        """Remove one internal run plus its visible buff and overlay rows."""
        run = self._trigger_runs.pop(run_key, None)
        if not run:
            return False
        trigger = run.get('trigger')
        display_name = str(run.get('name') or run_key)
        self._spell_container.end_custom_timer(
            display_name, runtime_key=run_key)
        dismiss = getattr(
            QApplication.instance(), 'dismiss_overlay_timer', None)
        if callable(dismiss):
            dismiss(run_key)
        if trigger and run_key in trigger.active_names:
            trigger.active_names.remove(run_key)
        return True

    def _start_trigger_run(
            self, trigger, run_key, name, duration, match, timestamp):
        now = time.monotonic()
        visible_seconds = min(
            duration, trigger.timer_visible_seconds) \
            if duration and trigger.timer_visible_seconds else 0
        self._trigger_runs[run_key] = {
            'key': run_key,
            'trigger': trigger,
            'name': name,
            'duration': duration,
            'started': now,
            'deadline': now + duration if duration else None,
            'ending_fired': False,
            'visible': not bool(visible_seconds and visible_seconds < duration),
            'defer_overlay': bool(visible_seconds and visible_seconds < duration),
            'visible_seconds': visible_seconds,
            'overlay_text': (
                render_trigger_text(trigger.alert_text, match, trigger)
                if trigger.alert_text else f'{trigger.category} timer'),
            'ending_text': render_trigger_text(
                trigger.timer_ending_alert, match, trigger),
            'ended_text': render_trigger_text(
                trigger.timer_ended_alert, match, trigger),
            'ending_tts': render_trigger_text(
                trigger.timer_ending_tts, match, trigger),
            'ended_tts': render_trigger_text(
                trigger.timer_ended_tts, match, trigger),
            'timestamp': timestamp,
            'character': getattr(trigger, 'runtime_character', ''),
            'server': getattr(self, '_active_server', ''),
        }

    @staticmethod
    def _trigger_text_color(trigger, character=''):
        style = effective_trigger_style(
            config.data['spells'], trigger.category,
            {'font_color': trigger.text_color}, character)
        return style.get('font_color', '')

    def _show_trigger_run_overlay(self, run, remaining=None):
        trigger = run['trigger']
        if trigger.overlay_id == 'none':
            return
        duration = run['duration'] if remaining is None else max(
            1, int(math.ceil(remaining)))
        QApplication.instance().show_overlay_notification(
            run['name'], run['overlay_text'], msecs=3500,
            overlay_id=trigger.overlay_id,
            countdown_seconds=duration,
            timer_key=run['key'],
            timer_mode=(
                'stopwatch' if trigger.timer_type == 'stopwatch'
                else 'countdown'),
            character=run.get('character', ''),
            text_color=self._trigger_text_color(
                trigger, run.get('character', '')))

    def _fire_trigger_stage(self, run, stage):
        trigger = run['trigger']
        if stage == 'ending':
            text = run['ending_text']
            sound = trigger.timer_ending_sound
            speech = run['ending_tts']
            interrupt = trigger.timer_ending_interrupt
            label = 'Timer ending'
        else:
            text = run['ended_text']
            sound = trigger.timer_ended_sound
            speech = run['ended_tts']
            interrupt = trigger.timer_ended_interrupt
            label = 'Timer ended'
        outputs = []
        if sound:
            play_alert(
                sound, config.data['spells']['fade_sound_volume'], 1,
                source=f"Trigger · {run['name']} · {label}",
                character=run.get('character', ''),
                server=run.get('server', ''), channel='spells')
            outputs.append(f"Sound · {sound_display_name(sound)}")
        if speech:
            speak_text(
                speech, config.data['spells']['fade_sound_volume'], interrupt,
                source=f"Trigger · {run['name']} · {label} speech",
                character=run.get('character', ''),
                server=run.get('server', ''), channel='spells')
            outputs.append('Text-to-speech')
        if text and trigger.overlay_id != 'none':
            QApplication.instance().show_overlay_notification(
                f"{run['name']} · {label}", text, msecs=4500,
                overlay_id=trigger.overlay_id,
                character=run.get('character', ''),
                text_color=self._trigger_text_color(
                    trigger, run.get('character', '')))
            outputs.append('Overlay')
        if outputs:
            self._record_trigger_match(
                datetime.datetime.now(), trigger, label,
                f"{label} · " + ' · '.join(outputs), status=label,
                profile=run.get('character', ''))

    def _update_custom_trigger_timers(self):
        now = time.monotonic()
        for run_key, run in list(self._trigger_runs.items()):
            trigger = run['trigger']
            if trigger.timer_type == 'stopwatch':
                continue
            deadline = run.get('deadline')
            if deadline is None:
                continue
            remaining = deadline - now
            if (run.get('defer_overlay') and not run.get('visible') and
                    remaining <= run.get('visible_seconds', 0)):
                run['visible'] = True
                self._show_trigger_run_overlay(run, remaining)
            if (trigger.timer_ending_seconds and not run['ending_fired'] and
                    0 < remaining <= trigger.timer_ending_seconds):
                run['ending_fired'] = True
                self._fire_trigger_stage(run, 'ending')
            if remaining > 0:
                continue

            self._fire_trigger_stage(run, 'ended')
            dismiss = getattr(
                QApplication.instance(), 'dismiss_overlay_timer', None)
            if callable(dismiss):
                dismiss(run_key)
            if trigger.timer_type == 'repeating':
                run['started'] = now
                run['deadline'] = now + run['duration']
                run['ending_fired'] = False
                run['visible'] = not run.get('defer_overlay', False)
                spell = Spell(
                    name=run['name'],
                    runtime_key=run_key,
                    duration=max(1, int(math.ceil(run['duration'] / 6))),
                    duration_seconds=run['duration'],
                    duration_formula=11,
                    spell_icon=14)
                self._spell_container.add_spell(
                    spell, datetime.datetime.now(), '__custom__',
                    run.get('character', ''), run.get('server', ''))
                if run['visible']:
                    self._show_trigger_run_overlay(run)
            else:
                self._trigger_runs.pop(run_key, None)
                if run_key in trigger.active_names:
                    trigger.active_names.remove(run_key)

    def _remove_spell_trigger(self, trigger=None):
        trigger = trigger or self._spell_trigger
        if trigger is None:
            return
        trigger.stop()
        trigger.deleteLater()
        if trigger is self._spell_trigger:
            self._spell_trigger = None

    @staticmethod
    def _spell_widget_matches_profile(widget, character='', server=''):
        character = str(character or '').strip().casefold()
        server = str(server or '').strip().casefold()
        widget_character = str(
            getattr(widget, 'runtime_character', '') or '').strip().casefold()
        widget_server = str(
            getattr(widget, 'runtime_server', '') or '').strip().casefold()
        if character and widget_character and character != widget_character:
            return False
        if server and widget_server and server != widget_server:
            return False
        return True

    def snapshot_you_spells(self, character='', server='', now=None):
        """Capture exact remaining self-buff seconds for camp restoration."""
        target = self._spell_container.get_spell_target_by_name('__you__')
        if not target:
            return []
        now = now or datetime.datetime.now()
        saved = []
        for widget in target.spell_widgets():
            if not self._spell_widget_matches_profile(
                    widget, character, server):
                continue
            seconds = int(math.ceil(
                (widget.end_time - now).total_seconds()))
            if seconds > 0:
                saved.append({
                    'name': widget.spell.name,
                    'seconds': min(seconds, 7 * 24 * 60 * 60),
                })
        return saved[:128]

    def clear_you_spells(self, character='', server=''):
        """Remove only the active profile's self buffs after a completed camp."""
        target = self._spell_container.get_spell_target_by_name('__you__')
        if not target:
            return 0
        removed = 0
        for widget in list(target.spell_widgets()):
            if self._spell_widget_matches_profile(widget, character, server):
                widget._remove()
                removed += 1
        self._spell_container._sync_empty_state()
        return removed

    def restore_you_spells(
            self, saved, character='', server='', timestamp=None):
        """Restore a one-shot camp snapshot when EQ logs Welcome to EverQuest."""
        lookup = {
            name.casefold(): spell for name, spell in self.spell_book.items()}
        restored = 0
        timestamp = timestamp or datetime.datetime.now()
        for item in list(saved or [])[:128]:
            if not isinstance(item, dict):
                continue
            source = lookup.get(str(item.get('name') or '').casefold())
            try:
                remaining = int(item.get('seconds', 0))
            except (TypeError, ValueError):
                remaining = 0
            if not source or remaining <= 0:
                continue
            spell = Spell(**source.__dict__)
            spell.saved_remaining_seconds = min(
                remaining, 7 * 24 * 60 * 60)
            self._spell_container.add_spell(
                spell, timestamp, '__you__', character, server)
            restored += 1
        return restored

    def set_camp_status(self, state, character=''):
        """Show compact, silent feedback for the log-authoritative camp state."""
        state = str(state or '').strip().casefold()
        self._camp_state = state
        self._spell_container.set_camp_state(state)
        target = self._spell_container.get_spell_target_by_name('__you__')
        if state == 'preparing':
            title = 'Spells · CAMP 6s'
            target_title = 'You · CAMP 6s'
            tooltip = (
                'Camp preparation detected in the EQ log. If it is not '
                'abandoned, Vantage preserves your self buffs after six seconds.')
        elif state == 'camped':
            title = 'Spells · CAMPED'
            target_title = 'You · CAMPED'
            tooltip = (
                'Camp completed from the EQ log. Self buffs are stored for this '
                'character and restore after Welcome to EverQuest!')
        else:
            title = 'Spells'
            target_title = 'You'
            tooltip = 'Drag this bar to move the window'
        self._title.setText(title)
        self._title.setToolTip(tooltip)
        self._title.setAccessibleDescription(tooltip)
        if target:
            target.target_label.setText(target_title)
            target.target_label.setToolTip(tooltip)
            target.target_label.setAccessibleName(target_title)
            target.target_label.setAccessibleDescription(tooltip)

    def camp_status_widget(self):
        """Return the visible authored-tooltip owner for UI verification."""
        target = self._spell_container.get_spell_target_by_name('__you__')
        if target and self._camp_state == 'preparing':
            return target.target_label
        return self._title

    def _sync_character_context(self):
        context = getattr(self, '_character_context', None)
        if not context:
            return
        identity = (
            context.server.casefold(), context.character.casefold(),
            context.revision)
        if identity == self._context_revision:
            return
        self._context_revision = identity
        key = self._profile_key(context.character, context.server)
        profile_index = next((
            index for index in range(self._character_widget.count())
            if (self._character_widget.itemData(index) or {}).get('key') == key
        ), -1)
        if context.character and profile_index < 0:
            label = context.character + (
                f' · {context.server}' if context.server else '')
            self._character_widget.addItem(label, {
                'key': key, 'character': context.character,
                'server': context.server,
                'level': max(1, int(context.level or
                                    config.data['spells']['level']))})
            profile_index = self._character_widget.count() - 1
        elif context.level and profile_index >= 0:
            profile = dict(self._character_widget.itemData(profile_index) or {})
            profile['level'] = max(1, min(65, int(context.level)))
            self._character_widget.setItemData(profile_index, profile)
        selected = self._selected_character_profile()
        selected_matches = bool(
            context.character and (
                not selected.get('key') or selected.get('key') == key))
        if context.level and selected_matches:
            self._level_widget.blockSignals(True)
            self._level_widget.setValue(context.level)
            self._level_widget.blockSignals(False)
            config.data['spells']['level'] = context.level
        details = [
            'Level used to calculate the correct buff duration',
            f'Profile: {context.character or "unknown"}' + (
                f' · {context.server}' if context.server else '')]
        if context.player_class:
            details.append(
                f'Class: {context.player_class} · inferred only from a spell '
                'exclusive to one P99 class or an exact class action')
        if context.level:
            details.append(
                f'Level {context.level} · learned from an exact level-up line '
                'or the minimum level of an exclusive spell')
        self._level_widget.setToolTip('\n'.join(details))

    def _level_change(self, _):
        level = self._level_widget.value()
        config.data['spells']['level'] = level
        profile = self._selected_character_profile()
        character = str(profile.get('character') or '')
        server = str(profile.get('server') or '')
        profile['level'] = level
        self._character_widget.setItemData(
            self._character_widget.currentIndex(), profile)
        app = QApplication.instance()
        updater = getattr(app, 'update_character_level', None)
        if updater and character:
            updater(character, server, level)
        else:
            config.save()

    def load_custom_timers(self):
        self._custom_timers = []
        previous_errors = dict(self._trigger_compile_errors)
        compile_errors = {}
        for item in config.data['spells']['custom_timers']:
            ct = CustomTrigger(*item)
            try:
                rx = compile_trigger_pattern(
                    ct.text, '', ct.regex)
                end_rxs = [
                    compile_trigger_pattern(
                        str(pattern.get('text') or ''), '',
                        bool(pattern.get('regex', False)))
                    for pattern in ct.end_patterns
                    if str(pattern.get('text') or '').strip()]
            except re.error as error:
                message = str(error)
                compile_errors[ct.name] = message
                if previous_errors.get(ct.name) != message:
                    self._record_trigger_match(
                        datetime.datetime.now(), ct, ct.text,
                        f"Invalid pattern · {message}", status="Error")
                continue
            self._custom_timers.append((rx, end_rxs, ct))
        self._trigger_compile_errors = compile_errors

    def _record_trigger_match(
            self, timestamp, trigger, line, output, status="Matched",
            match_us=0.0, profile=""):
        profile = str(
            profile or getattr(trigger, 'runtime_character', '') or
            trigger.profile or getattr(self, '_active_character', '') or
            config.data.get('sharing', {}).get('player_name', ''))
        self._trigger_history.appendleft({
            'time': timestamp.strftime('%H:%M:%S') if hasattr(
                timestamp, 'strftime') else str(timestamp),
            'trigger': trigger.name,
            'category': trigger.category,
            'line': str(line),
            'output': str(output),
            'source': trigger.source,
            'status': str(status or 'Matched'),
            'profile': profile if profile != 'ConfigureMe' else '',
            'zone': getattr(self, '_current_zone', ''),
            'match_us': round(max(0.0, float(match_us or 0.0)), 2),
        })

    def test_trigger_line(self, line, trigger_name=""):
        """Dry-run one log line through the exact compiled trigger patterns."""
        line = str(line or '').strip()
        if not line:
            return 0
        original_line = line
        if line.startswith('[') and '] ' in line:
            line = line.split('] ', 1)[1]
        wanted = str(trigger_name or '').casefold()
        matches = 0
        timestamp = datetime.datetime.now()
        for rx, end_rxs, trigger in self._custom_timers:
            if wanted and trigger.name.casefold() != wanted:
                continue
            started = time.perf_counter_ns()
            end_match = next(
                (match for pattern in end_rxs
                 if (match := pattern.match(line))), None)
            match = rx.match(line)
            match_us = (time.perf_counter_ns() - started) / 1000.0
            if end_match:
                self._record_trigger_match(
                    timestamp, trigger, original_line,
                    'Would end an active timer early', status='Test end',
                    match_us=match_us)
                matches += 1
                continue
            if not match:
                continue
            trigger.runtime_character = (
                self._active_character or
                config.data.get('sharing', {}).get('player_name', ''))
            rendered_name = render_trigger_text(trigger.name, match, trigger)
            outputs = []
            if trigger.timer_type != 'none':
                duration = (
                    dynamic_timer_seconds(match)
                    if '{ts}' in trigger.text.casefold() else
                    text_time_to_seconds(trigger.time))
                outputs.append(
                    f"{trigger.timer_type} · {duration:g}s"
                    if duration else trigger.timer_type)
            if trigger.alert_text:
                outputs.append(
                    f"overlay: {render_trigger_text(trigger.alert_text, match, trigger)}")
            if trigger.tts_text:
                outputs.append(
                    f"speech: {render_trigger_text(trigger.tts_text, match, trigger)}")
            if trigger.sound_path:
                outputs.append(f"sound: {sound_display_name(trigger.sound_path)}")
            if trigger.clipboard_text:
                outputs.append(
                    f"clipboard: {render_trigger_text(trigger.clipboard_text, match, trigger)}")
            self._record_trigger_match(
                timestamp, trigger, original_line,
                f"{rendered_name} · " + (
                    ' · '.join(outputs) if outputs else 'no output actions'),
                status='Test', match_us=match_us)
            matches += 1
        return matches

    def trigger_history(self):
        return list(self._trigger_history)

    def clear_trigger_history(self):
        self._trigger_history.clear()

    def _toggle_custom_timers(self, _):
        config.data['spells']['use_custom_triggers'] = \
            self._custom_timer_toggle.isChecked()
        config.save()

    def _boat_server_name(self):
        value = str(getattr(self, '_active_server', '') or '').casefold()
        for token, label in (
                ('green', 'Green'), ('blue', 'Blue'), ('red', 'Red'),
                ('quarm', 'Quarm')):
            if token in value:
                return label
        return 'Green'

    def _toggle_boat_schedules(self, checked):
        if hasattr(self, '_compact_boat_action'):
            self._compact_boat_action.setChecked(bool(checked))
        config.data['spells']['show_boat_schedules'] = bool(checked)
        config.save()
        self._boat_group.set_enabled(bool(checked))
        self._spell_container._sync_empty_state()
        if checked:
            self._refresh_boat_schedules()

    def _manual_refresh_boats(self):
        if not self._boat_toggle.isChecked():
            self._boat_toggle.setChecked(True)
            self._toggle_boat_schedules(True)
            return
        self._refresh_boat_schedules()

    def _refresh_boat_schedules(self):
        if not self._boat_toggle.isChecked() or self._boat_pending:
            return
        server = self._boat_server_name()
        self._boat_pending = True
        self._boat_server = server
        self._boat_group.set_status(
            f'BOAT SCHEDULES · syncing PigParse · {server}')
        request = QNetworkRequest(QUrl(
            'https://pigparse.azurewebsites.net/api/boat/'
            f'serverActivity/{server}'))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader, 'Vantage/1.44.25')
        reply = self._boat_network.get(request)
        reply.finished.connect(
            lambda reply=reply, server=server:
            self._boat_reply_finished(reply, server))

    def _boat_reply_finished(self, reply, server):
        self._boat_pending = False
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._boat_group.set_status(
                    f'BOAT SCHEDULES · PigParse unavailable · {server}')
                return
            payload = json.loads(bytes(reply.readAll()).decode(
                'utf-8', errors='replace'))
            schedules = schedules_from_activities(
                payload, source=f'PigParse API · {server}')
            if not schedules:
                self._boat_group.set_status(
                    f'BOAT SCHEDULES · no observations · {server}')
                return
            self._boat_group.update_schedules(schedules, server)
        except (TypeError, ValueError, json.JSONDecodeError):
            self._boat_group.set_status(
                f'BOAT SCHEDULES · invalid PigParse response · {server}')
        finally:
            reply.deleteLater()


class BoatScheduleWidget(QFrame):
    """One lightweight repeating arrival row backed by a dated observation."""

    def __init__(self, schedule):
        super().__init__()
        self.setObjectName('BoatScheduleWidget')
        self._schedule = None
        self._arrival_at = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 3, 1)
        layout.setSpacing(3)
        icon = QLabel()
        icon.setPixmap(game_pixmap('timer', 16, self))
        icon.setFixedSize(18, 18)
        icon.setAccessibleName('Boat arrival timer icon')
        icon.setToolTip('Repeating P99 boat arrival schedule')
        layout.addWidget(icon)

        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(1)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(3)
        self.name_label = QLabel()
        self.name_label.setObjectName('BoatScheduleName')
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.name_label, 1)
        self.time_label = QLabel()
        self.time_label.setObjectName('BoatScheduleTime')
        self.time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        heading.addWidget(self.time_label)
        details.addLayout(heading)

        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(3)
        self.source_label = QLabel()
        self.source_label.setObjectName('BoatScheduleSource')
        source_row.addWidget(self.source_label)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setToolTip(
            'Time remaining relative to one modeled boat cycle')
        source_row.addWidget(self.progress, 1)
        details.addLayout(source_row)
        layout.addLayout(details, 1)
        self.set_schedule(schedule)

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc)

    @staticmethod
    def _age_text(seconds):
        seconds = max(0, int(seconds))
        if seconds < 60:
            return '<1m'
        if seconds < 3600:
            return f'{seconds // 60}m'
        if seconds < 86400:
            return f'{seconds // 3600}h'
        return f'{seconds // 86400}d'

    def set_schedule(self, schedule):
        self._schedule = schedule
        self._arrival_at = (
            self._now() + datetime.timedelta(
                seconds=schedule.remaining_seconds))
        route = schedule.route
        self.name_label.setText(route.pretty_name)
        self.progress.setRange(0, max(1, int(route.trip_seconds)))
        self.progress.setStyleSheet(
            'QProgressBar { border: none; background: #171A1F; padding: 0; }'
            f'QProgressBar::chunk {{ background: {route.color}; }}')
        self.update_now(self._now())

    def update_now(self, now):
        route = self._schedule.route
        remaining = (self._arrival_at - now).total_seconds()
        while remaining <= 0:
            self._arrival_at += datetime.timedelta(
                seconds=route.trip_seconds)
            remaining = (self._arrival_at - now).total_seconds()
        age = max(0, (now - self._schedule.last_seen).total_seconds())
        stale = age > route.trip_seconds * 3
        source_kind = (
            'LOG' if self._schedule.source.casefold().startswith('eq log')
            else 'PIG')
        self.source_label.setText(
            f'{source_kind} · {"STALE " if stale else ""}'
            f'{self._age_text(age)}')
        self.time_label.setText(format_time(
            datetime.timedelta(seconds=max(0, int(remaining)))))
        self.progress.setValue(max(0, int(remaining)))
        freshness = (
            'The observation is older than three modeled trips; the countdown '
            'is an extrapolation and may have drifted.' if stale else
            'The observation is within three modeled trips.')
        tooltip = (
            f'{route.boat_name} · {route.start_point} to {route.end_point}\n'
            f'Source: {self._schedule.source}\n'
            f'Last observed: {self._schedule.last_seen.astimezone():%Y-%m-%d %H:%M:%S}\n'
            f'{freshness}')
        self.setToolTip(tooltip)
        self.name_label.setToolTip(tooltip)
        self.source_label.setToolTip(tooltip)
        self.time_label.setToolTip(tooltip)


class BoatScheduleGroup(QFrame):
    """Compact source-labelled boat rows embedded in the buff window."""

    def __init__(self):
        super().__init__()
        self.setObjectName('BoatScheduleGroup')
        self._rows = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.header = QLabel('Boat Schedules')
        self.header.setObjectName('SpellTargetLabel')
        self.header.setProperty('TargetType', 0)
        self.header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header.setToolTip(
            'P99 boat arrivals calculated from dated PigParse or local EQ log observations')
        self._layout.addWidget(self.header)
        self.status = QLabel('BOAT SCHEDULES · waiting for PigParse')
        self.status.setObjectName('BoatScheduleStatus')
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setToolTip(
            'PigParse supplies the observation; Vantage labels stale extrapolations')
        self._layout.addWidget(self.status)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self.setVisible(False)

    def set_enabled(self, enabled):
        self.setVisible(bool(enabled))
        if enabled:
            self._clock.start()
            self._tick()
        else:
            self._clock.stop()

    def set_status(self, text):
        self.status.setText(str(text))

    def rows(self):
        return list(self._rows.values())

    def update_schedules(self, schedules, server='Green', replace=True):
        incoming = {
            (schedule.route.boat_id, schedule.route.start_point): schedule
            for schedule in schedules}
        if replace:
            for key in list(self._rows):
                if key not in incoming:
                    row = self._rows.pop(key)
                    row.setParent(None)
                    row.deleteLater()
        for key, schedule in incoming.items():
            if key in self._rows:
                self._rows[key].set_schedule(schedule)
            else:
                self._rows[key] = BoatScheduleWidget(schedule)
        route_order = {
            (route.boat_id, route.start_point): index
            for index, route in enumerate(BOAT_ROUTES)}
        ordered = sorted(
            self._rows.items(), key=lambda item: route_order[item[0]])
        for index, (_key, row) in enumerate(ordered, 2):
            self._layout.insertWidget(index, row)
        now = datetime.datetime.now(datetime.timezone.utc)
        stale = sum(
            1 for row in self._rows.values()
            if (now - row._schedule.last_seen).total_seconds() >
            row._schedule.route.trip_seconds * 3)
        self.status.setText(
            f'BOATS · {len(self._rows)} arrivals · {server} · '
            f'{stale} stale source' if stale else
            f'BOATS · {len(self._rows)} arrivals · {server} · source current')
        self._tick()
        owner = self.parentWidget()
        if owner and hasattr(owner, '_sync_empty_state'):
            owner._sync_empty_state()

    def _tick(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for row in self._rows.values():
            row.update_now(now)


class BardCountGroup(QFrame):

    def __init__(self):
        super().__init__()
        self.setObjectName('BardCountGroup')
        self._rows = deque(maxlen=4)
        self._enabled = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self.header = QLabel('Bard AE Counts')
        self.header.setObjectName('SpellTargetLabel')
        self.header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header.setToolTip(
            'Last four exact 1.5-second Bard AE hit/resist bursts in this session')
        self._layout.addWidget(self.header)
        self.setVisible(False)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        self.setVisible(self._enabled and bool(self._rows))
        self._sync_owner()

    def add_summary(self, summary):
        label = QLabel(
            f"{summary.timestamp:%H:%M:%S} · {summary.text}"
            if hasattr(summary.timestamp, 'strftime') else summary.text)
        label.setObjectName('BardCountRow')
        label.setToolTip(
            f"{summary.text}\nSource: {summary.source}\n"
            'Song name is omitted when any event in the burst is ambiguous.')
        label.setAccessibleName(f"Bard AE count: {summary.text}")
        if len(self._rows) == self._rows.maxlen:
            oldest = self._rows.popleft()
            self._layout.removeWidget(oldest)
            oldest.deleteLater()
        self._rows.append(label)
        self._layout.addWidget(label)
        self.setVisible(self._enabled)
        self._sync_owner()

    def rows(self):
        return list(self._rows)

    def _sync_owner(self):
        owner = self.parentWidget()
        if owner and hasattr(owner, '_sync_empty_state'):
            owner._sync_empty_state()


class SpellContainer(QFrame):

    state_changed = Signal()

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout()
        self.setLayout(self._layout)
        self.setObjectName('SpellContainer')
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addStretch(1)
        self._activity_sequence = 0
        self._target_sequence = 0
        self._filter_character = ''
        self._filter_server = ''
        self._empty_state = QLabel(
            "NO ACTIVE BUFFS\nWaiting for casts from the log…", self)
        self._empty_state.setObjectName("SpellEmptyState")
        self._empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_state.setWordWrap(True)
        self._empty_state.setAccessibleName(
            "No active buffs; waiting for log events")
        self._empty_state.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._sync_empty_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        margin = 10
        self._empty_state.setGeometry(
            margin, margin,
            max(0, self.width() - margin * 2),
            max(0, self.height() - margin * 2))

    def _sync_empty_state(self):
        boats_visible = bool(
            getattr(self, '_boat_group', None) and
            not self._boat_group.isHidden())
        bard_visible = bool(
            getattr(self, '_bard_group', None) and
            not self._bard_group.isHidden())
        empty = (
            not any(not target.isHidden()
                    for target in self.findChildren(SpellTarget)) and
            not boats_visible and not bard_visible)
        self._empty_state.setVisible(empty)
        if empty:
            self._empty_state.raise_()

    def set_camp_state(self, state):
        state = str(state or '').strip().casefold()
        if state == 'preparing':
            text = 'PREPARING CAMP · 6s\nWaiting for EverQuest confirmation…'
            accessible = 'Preparing camp; waiting six seconds for confirmation'
            tooltip = (
                'The exact EQ camp line started a six-second confirmation. '
                'Abandoning camp cancels it.')
        elif state == 'camped':
            text = 'CAMPED\nSelf buffs saved for login…'
            accessible = 'Camp completed; self buffs saved for login'
            tooltip = (
                'Self buffs were preserved and restore after the log reports '
                'Welcome to EverQuest!')
        else:
            text = 'NO ACTIVE BUFFS\nWaiting for casts from the log…'
            accessible = 'No active buffs; waiting for log events'
            tooltip = ''
        self._empty_state.setText(text)
        self._empty_state.setAccessibleName(accessible)
        self._empty_state.setToolTip(tooltip)
        self._sync_empty_state()

    def set_boat_group(self, group):
        self._boat_group = group
        self._layout.insertWidget(0, group)
        self._sync_empty_state()

    def set_bard_group(self, group):
        self._bard_group = group
        self._layout.insertWidget(1, group)
        self._sync_empty_state()

    def set_profile_filter(self, character='', server=''):
        self._filter_character = str(character or '').strip().casefold()
        self._filter_server = str(server or '').strip().casefold()
        self._apply_profile_filter()

    def _apply_profile_filter(self):
        for target in self.findChildren(SpellTarget):
            visible = False
            for widget in target.spell_widgets():
                widget_character = str(
                    getattr(widget, 'runtime_character', '') or '').strip().casefold()
                widget_server = str(
                    getattr(widget, 'runtime_server', '') or '').strip().casefold()
                matches = (
                    not self._filter_character or not widget_character or
                    (widget_character == self._filter_character and
                     (not self._filter_server or not widget_server or
                      widget_server == self._filter_server)))
                widget.setVisible(matches)
                visible = visible or matches
            target.setVisible(visible)
        self._sync_empty_state()

    @staticmethod
    def _spell_runtime_payload(spell):
        fields = (
            'id', 'name', 'runtime_key', 'duration_seconds', 'duration',
            'duration_formula', 'pvp_duration', 'pvp_duration_formula', 'type',
            'spell_icon', 'skill', 'resist_type', 'effect_text_you',
            'effect_text_other', 'effect_text_worn_off', 'source_item',
            'item_only', 'runtime_level')
        payload = {}
        for field_name in fields:
            value = getattr(spell, field_name, None)
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[field_name] = value
        return payload

    def snapshot_runtime_state(self, now_epoch=None, now_datetime=None):
        """Serialize active rows with absolute deadlines for offline aging."""
        now_epoch = time.time() if now_epoch is None else float(now_epoch)
        now_datetime = now_datetime or datetime.datetime.now()
        saved = []
        for target in sorted(
                self.findChildren(SpellTarget),
                key=lambda item: item.created_order):
            for widget in target.spell_widgets():
                if widget._removed or widget._faded:
                    continue
                remaining = (widget.end_time - now_datetime).total_seconds()
                if remaining <= 0:
                    continue
                saved.append({
                    'deadline': now_epoch + remaining,
                    'target': target.name,
                    'target_created_order': target.created_order,
                    'target_activity_order': target.last_activity_order,
                    'target_named': target.is_named,
                    'target_marker': target.instance_marker,
                    'target_alias': target.alias,
                    'character': widget.runtime_character,
                    'server': widget.runtime_server,
                    'warning_played': widget._warning_played,
                    'spell': self._spell_runtime_payload(widget.spell),
                })
                if len(saved) >= 512:
                    return saved
        return saved

    def restore_runtime_state(
            self, saved, spell_book, now_epoch=None, now_datetime=None):
        """Restore unexpired rows and subtract all time elapsed while offline."""
        if not isinstance(saved, list):
            return 0
        now_epoch = time.time() if now_epoch is None else float(now_epoch)
        now_datetime = now_datetime or datetime.datetime.now()
        lookup = {
            str(name).casefold(): spell for name, spell in spell_book.items()}
        targets = {}
        restored = 0
        for item in saved[:512]:
            if not isinstance(item, dict) or not isinstance(item.get('spell'), dict):
                continue
            try:
                deadline = float(item.get('deadline', 0))
                remaining = int(math.ceil(deadline - now_epoch))
            except (TypeError, ValueError, OverflowError):
                continue
            if remaining <= 0:
                continue
            payload = dict(item['spell'])
            name = str(payload.get('name') or '').strip()
            if not name:
                continue
            source = lookup.get(name.casefold())
            spell = copy.copy(source) if source else Spell()
            for key, value in payload.items():
                if key in {
                        'id', 'name', 'runtime_key', 'duration_seconds',
                        'duration', 'duration_formula', 'pvp_duration',
                        'pvp_duration_formula', 'type', 'spell_icon', 'skill',
                        'resist_type', 'effect_text_you', 'effect_text_other',
                        'effect_text_worn_off', 'source_item', 'item_only',
                        'runtime_level'}:
                    setattr(spell, key, value)
            spell.saved_remaining_seconds = min(
                remaining, 365 * 24 * 60 * 60)
            spell.saved_warning_played = bool(item.get('warning_played', False))
            target_name = str(item.get('target') or '__you__')[:128]
            try:
                created_order = max(1, int(
                    item.get('target_created_order', restored + 1)))
            except (TypeError, ValueError):
                created_order = restored + 1
            target_key = (target_name.casefold(), created_order)
            target = targets.get(target_key)
            if target is None:
                target = SpellTarget(
                    target=target_name, created_order=created_order,
                    named=bool(item.get('target_named', False)),
                    marker=str(item.get('target_marker') or '')[:8],
                    alias=str(item.get('target_alias') or '')[:32])
                try:
                    target.last_activity_order = max(
                        0, int(item.get('target_activity_order', 0)))
                except (TypeError, ValueError):
                    target.last_activity_order = 0
                self._layout.addWidget(target, 0)
                targets[target_key] = target
                self._target_sequence = max(
                    self._target_sequence, target.created_order)
                self._activity_sequence = max(
                    self._activity_sequence, target.last_activity_order)
            target.add_spell(
                spell, now_datetime,
                str(item.get('character') or '')[:80],
                str(item.get('server') or '')[:80])
            restored += 1
        for target_name in {target.name for target in targets.values()}:
            self._renumber_target_instances(target_name)
        self._reorder_targets()
        self._apply_profile_filter()
        return restored

    def add_spell(
            self, spell, timestamp, target='__you__', character='', server='',
            named=False):
        instances = self.get_spell_targets_by_name(target)
        named = bool(named)
        # Named NPCs are unique within their P99 spawn context. Older builds
        # may already have inferred duplicates, so collapse them before recast.
        if named and len(instances) > 1:
            for duplicate in instances[1:]:
                duplicate._remove()
            instances = instances[:1]
        if named and instances:
            instances[0].is_named = True
        spell_target = self._choose_target_instance(
            instances, spell, timestamp, target, named)
        if not spell_target:
            self._target_sequence += 1
            spell_target = SpellTarget(
                target=target, created_order=self._target_sequence,
                named=named,
                marker=(
                    '' if named or str(target).startswith('__') else
                    self._allocate_target_marker(target)))
            self._layout.addWidget(spell_target, 0)

        spell_target.add_spell(spell, timestamp, character, server)
        self._activity_sequence += 1
        spell_target.last_activity_order = self._activity_sequence
        self._renumber_target_instances(target)
        self._reorder_targets()
        self._apply_profile_filter()
        self._sync_empty_state()
        self.state_changed.emit()

    @staticmethod
    def _choose_target_instance(instances, spell, timestamp, target,
                                named=False):
        """Infer duplicate mobs while preserving normal self/recast behavior.

        EverQuest logs only the visible target name. For detrimental effects,
        another landing while the latest identical timer is still in its first
        quarter is treated as another same-named mob. Once that latest instance
        has progressed further, the oldest timer is the safer recast target.
        """
        if not instances:
            return None
        if (named or str(target).startswith('__') or
                not _spell_targets_enemy(spell)):
            return instances[0]
        spell_key = str(getattr(spell, 'runtime_key', spell.name))
        matching = []
        for instance in instances:
            widget = instance.spell_widget(spell_key)
            if widget is not None:
                matching.append((instance, widget))
        if not matching:
            return max(instances, key=lambda item: item.last_activity_order)
        latest = max(
            matching, key=lambda pair: pair[0].last_activity_order)
        if latest[0].spell_remaining_ratio(latest[1], timestamp) >= 0.75:
            return None
        return min(matching, key=lambda pair: pair[1].end_time)[0]

    def _reorder_targets(self):
        """Keep newly affected enemies at the top of the mob section."""
        targets = sorted(
            self.findChildren(SpellTarget), key=_spell_target_sort_key)
        for index, widget in enumerate(targets):
            self._layout.insertWidget(index, widget, 0)

    def spell_targets(self):
        """Returns a list of all SpellTargets."""
        return self.findChildren(SpellTarget)

    def get_spell_targets_by_name(self, name):
        folded = str(name or '').strip().casefold()
        return sorted([
            target for target in self.spell_targets()
            if target.name.strip().casefold() == folded
        ], key=lambda target: target.created_order)

    def get_spell_target_by_name(self, name):
        spell_targets = self.get_spell_targets_by_name(name)
        if spell_targets:
            return spell_targets[0]
        return None

    def remove_dead_target(self, name):
        """Remove one oldest enemy instance named by an EQ death line."""
        candidates = [
            target for target in self.get_spell_targets_by_name(name)
            if int(target.target_label.property('TargetType') or 0) == 2]
        if not candidates:
            return False
        victim = min(candidates, key=lambda target: (
            target.earliest_expiry(), target.created_order))
        victim._remove()
        self._renumber_target_instances(name)
        self._sync_empty_state()
        return True

    def mark_worn_off(self, text, timestamp=None, play_sound=True):
        """Mark one best matching row FADED without erasing its mob context."""
        worn_text = str(text or '').strip().casefold()
        if not worn_text:
            return None
        matches = []
        charm_break = worn_text in CHARM_BREAK_LINES
        named_worn_off = SPELL_WORN_OFF_RX.match(str(text or '').strip())
        reported_spell = (
            named_worn_off.group('spell').strip().casefold()
            if named_worn_off else '')
        for target in self.spell_targets():
            for widget in target.spell_widgets():
                worn_off = str(
                    widget.spell.effect_text_worn_off or '').strip().casefold()
                exact_match = worn_off and worn_text == worn_off
                spell_name_match = (
                    reported_spell and
                    str(widget.spell.name).strip().casefold() == reported_spell)
                if ((exact_match or spell_name_match or
                     (charm_break and _is_charm_spell(widget.spell))) and
                        not widget._faded and
                        not widget.ignores_replaced_worn_off(timestamp)):
                    matches.append(widget)
        if not matches:
            return None
        victim = min(matches, key=lambda widget: widget.end_time)
        victim.mark_faded(timestamp, play_sound=play_sound)
        return victim

    def _renumber_target_instances(self, name):
        instances = self.get_spell_targets_by_name(name)
        total = len(instances)
        for target in instances:
            if (not target.is_named and not target.name.startswith('__') and
                    not target.instance_marker):
                target.instance_marker = self._allocate_target_marker(
                    target.name, exclude=target)
        for number, target in enumerate(instances, 1):
            target.set_instance_number(
                number, 1 if target.is_named else total)

    def _allocate_target_marker(self, name, exclude=None):
        used = {
            target.instance_marker for target in
            self.get_spell_targets_by_name(name)
            if target is not exclude and target.instance_marker}
        index = 0
        while True:
            marker = (
                chr(ord('A') + index) if index < 26 else f'A{index + 1}')
            if marker not in used:
                return marker
            index += 1

    def _spell_widget_removed(self, target):
        if target and not target._removed:
            self._renumber_target_instances(target.name)
        self._apply_profile_filter()
        self.state_changed.emit()

    def _create_duplicate_target(self, source):
        """Create a stable manual instance for logs that expose no mob ID."""
        self._target_sequence += 1
        target = SpellTarget(
            target=source.name, created_order=self._target_sequence,
            named=False, marker=self._allocate_target_marker(source.name))
        self._layout.addWidget(target, 0)
        return target

    def move_spell_widget(self, widget, destination=None):
        """Move a live effect without restarting its countdown."""
        source = widget.parentWidget()
        if not isinstance(source, SpellTarget) or source.is_named:
            return None
        if destination is None:
            destination = self._create_duplicate_target(source)
        if (destination is source or
                destination.name.casefold() != source.name.casefold()):
            return destination
        spell_key = str(getattr(
            widget.spell, 'runtime_key', widget.spell.name))
        existing = destination.spell_widget(spell_key)
        if existing and existing is not widget:
            return destination
        destination._layout.insertWidget(
            max(1, destination._layout.count() - 1), widget)
        destination._initialized = True
        destination.last_activity_order = max(
            destination.last_activity_order, source.last_activity_order)
        destination._sort_spell_widgets()
        destination.set_instance_number(destination.instance_number)
        if not source._removed:
            source.set_instance_number(source.instance_number)
        self._renumber_target_instances(source.name)
        self._reorder_targets()
        self._apply_profile_filter()
        self.state_changed.emit()
        return destination

    def _target_removed(self, target):
        name = target.name
        QTimer.singleShot(0, lambda: self._finish_target_removed(name))

    def _finish_target_removed(self, name):
        self._renumber_target_instances(name)
        self._apply_profile_filter()
        self.state_changed.emit()

    def has_custom_timer(self, name):
        target = self.get_spell_target_by_name('__custom__')
        return bool(target and any(
            widget.spell.name.casefold() == str(name).casefold()
            for widget in target.spell_widgets()))

    def end_custom_timer(self, name, runtime_key=''):
        target = self.get_spell_target_by_name('__custom__')
        if not target:
            return False
        removed = False
        for widget in list(target.spell_widgets()):
            widget_key = str(getattr(
                widget.spell, 'runtime_key', widget.spell.name))
            matches = (
                widget_key == str(runtime_key)
                if runtime_key else
                widget.spell.name.casefold() == str(name).casefold())
            if matches:
                widget._remove()
                removed = True
        return removed


class SpellTarget(QFrame):

    def __init__(self, target='__you__', created_order=0, named=False,
                 marker='', alias=''):
        super().__init__()
        self.name = target
        if target == '__you__':
            self.title = 'you'
        elif target == '__custom__':
            self.title = 'custom'
        elif target == '__utility__':
            self.title = 'cooldowns'
        else:
            self.title = target
        self._initialized = False  # don't delete until after first spell
        self.last_activity_order = 0
        self.created_order = int(created_order)
        self.instance_number = 1
        self.instance_total = 1
        self.is_named = bool(named)
        self.instance_marker = str(marker or '')[:8]
        self.alias = str(alias or '').strip()[:32]
        self._removed = False
        self.setObjectName('SpellContainer')

        self._setup_ui()

    def _setup_ui(self):
        self._layout = QVBoxLayout()
        self.setLayout(self._layout)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.target_label = QToolButton()
        self.target_label.setText(self.title.title())
        self.target_label.setObjectName('SpellTargetLabel')
        self.target_label.setAutoRaise(True)
        self.target_label.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.target_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.target_label.setMinimumHeight(20)
        self.target_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.target_label.installEventFilter(self)
        self.target_label.clicked.connect(
            lambda: self._target_menu(self.target_label.rect().center()))
        self.target_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.target_label.customContextMenuRequested.connect(self._target_menu)
        self._layout.addWidget(self.target_label, 0)
        self._layout.addStretch()

    def _remove(self, event=None):
        if self._removed:
            return
        self._removed = True
        owner = self.parentWidget()
        focus_target = None
        if owner:
            siblings = [
                target for target in owner.spell_targets()
                if target is not self and not target._removed]
            if siblings:
                focus_target = siblings[0].target_label
            else:
                window = self.window()
                focus_target = getattr(window, '_character_widget', None)
        self.setParent(None)
        self.deleteLater()
        if owner and hasattr(owner, '_target_removed'):
            owner._target_removed(self)
        elif owner and hasattr(owner, '_sync_empty_state'):
            QTimer.singleShot(0, owner._sync_empty_state)
        if focus_target is not None:
            QTimer.singleShot(0, lambda: focus_target.setFocus(
                Qt.FocusReason.OtherFocusReason))

    def spell_widgets(self):
        """Returns a list of all SpellWidgets."""
        return self.findChildren(SpellWidget)

    def spell_widget(self, spell_key):
        spell_key = str(spell_key)
        for widget in self.spell_widgets():
            if str(getattr(
                    widget.spell, 'runtime_key', widget.spell.name)) == spell_key:
                return widget
        return None

    @staticmethod
    def spell_remaining_ratio(widget, timestamp):
        try:
            remaining = (widget.end_time - timestamp).total_seconds()
        except (AttributeError, TypeError):
            return 1.0
        duration = max(1.0, float(getattr(widget, '_seconds', 1)))
        return max(0.0, min(1.0, remaining / duration))

    def earliest_expiry(self):
        expiries = [widget.end_time for widget in self.spell_widgets()]
        return min(expiries) if expiries else datetime.datetime.max

    def set_instance_number(self, number, total=1):
        self.instance_number = max(1, int(number))
        self.instance_total = max(1, int(total))
        if self.name.startswith('__'):
            return
        base = self.title.title()
        # A/B markers identify simultaneous same-named mobs. A lone mob does
        # not need a suffix, which also makes clearing a custom label visibly
        # return to the plain mob name.
        marker = self.alias or (
            self.instance_marker if self.instance_total > 1 else '')
        display = (
            f'{base} · {marker}' if marker and not self.is_named else base)
        self.target_label.setText(display)
        effects = [
            string.capwords(str(widget.spell.name))
            for widget in self.spell_widgets() if not widget._removed]
        effect_text = (
            ' Active effects: ' + ', '.join(effects) + '.' if effects else '')
        if self.is_named:
            tooltip = (
                'Named NPC · Vantage keeps one spell target instance in this zone. '
                'Click, Enter, Space, or right-click for actions; press Delete '
                'to remove its timers.' +
                effect_text)
        elif int(total) > 1:
            tooltip = (
                'Tracked hostile mobs · EverQuest logs do not expose mob IDs. '
                'Vantage separated '
                f'{total} active mobs with stable markers; right-click to name '
                'this one by location. A death line removes the oldest matching '
                'instance. Click, Enter, or Space for actions; press Delete to '
                'remove this one.' + effect_text)
        else:
            tooltip = (
                'Tracked hostile mob · click, Enter, Space, or right-click for '
                'actions such as naming it by location. Press Delete to remove '
                'this target and its spell timers.' +
                effect_text)
        self.target_label.setToolTip(tooltip)
        self.target_label.setAccessibleName(display)
        self.target_label.setAccessibleDescription(tooltip)

    def _target_menu(self, position):
        menu = QMenu(self)
        rename = menu.addAction('Name this mob…')
        rename.setToolTip(
            'Give this tracked instance a location label such as Entrance or Ramp')
        clear = menu.addAction('Clear custom mob name')
        clear.setToolTip(
            'Remove the custom location label; A/B remains only when multiple '
            'same-named mobs must be distinguished')
        clear.setEnabled(bool(self.alias))
        menu.addSeparator()
        remove = menu.addAction('Remove this mob and its spell timers')
        action = menu.exec(self.target_label.mapToGlobal(position))
        if action == rename:
            value, accepted = QInputDialog.getText(
                self, 'Name tracked mob', 'Short location or marker:',
                text=self.alias)
            if accepted:
                self.set_mob_alias(value)
        elif action == clear:
            self.set_mob_alias('')
        elif action == remove:
            self._remove()

    def set_mob_alias(self, value):
        """Set or clear a persisted location label and repaint immediately."""
        normalized = str(value or '').strip()[:32]
        if normalized == self.alias:
            return False
        self.alias = normalized
        self.set_instance_number(self.instance_number, self.instance_total)
        owner = self.parentWidget()
        if owner and hasattr(owner, 'state_changed'):
            owner.state_changed.emit()
        return True

    def eventFilter(self, watched, event):
        if (watched is self.target_label and
                event.type() == QEvent.Type.KeyPress and
                event.key() in {
                    Qt.Key.Key_Delete, Qt.Key.Key_Backspace}):
            self._remove()
            return True
        if (watched is self.target_label and
                event.type() == QEvent.Type.KeyPress and
                (event.key() == Qt.Key.Key_Menu or
                 (event.key() == Qt.Key.Key_F10 and
                  event.modifiers() & Qt.KeyboardModifier.ShiftModifier))):
            self._target_menu(self.target_label.rect().center())
            return True
        return super().eventFilter(watched, event)

    def childEvent(self, event):
        if event.type() == QEvent.Type.ChildRemoved:
            if isinstance(event.child(), SpellWidget):
                if not self.findChildren(SpellWidget):
                    self._remove()
        event.accept()

    def add_spell(self, spell, timestamp, character='', server=''):
        target_type = 0 if _spell_targets_enemy(spell) else 1
        matching = []
        spell_key = str(getattr(spell, 'runtime_key', spell.name))
        for sw in self.findChildren(SpellWidget):
            target_type *= 0 if _spell_targets_enemy(sw.spell) else 1
            widget_key = str(getattr(
                sw.spell, 'runtime_key', sw.spell.name))
            # Self buffs describe one active effect per character.  Old saved
            # rows and item-click aliases may use a different runtime key for
            # the same visible buff, so their canonical identity is the spell
            # name. Enemy timers keep the stronger runtime key because same-
            # named mobs and custom effects must remain independently movable.
            same_spell = (
                (self.name == '__you__' and
                 str(sw.spell.name).strip().casefold() ==
                 str(spell.name).strip().casefold()) or
                widget_key == spell_key)
            existing_character = str(
                sw.runtime_character or '').strip().casefold()
            incoming_character = str(character or '').strip().casefold()
            existing_server = str(sw.runtime_server or '').strip().casefold()
            incoming_server = str(server or '').strip().casefold()
            same_profile = (
                not self.name.startswith('__') or
                not incoming_character or not existing_character or
                (existing_character == incoming_character and
                 (not incoming_server or not existing_server or
                  existing_server == incoming_server)))
            if same_spell and same_profile:
                matching.append(sw)
        if matching:
            # Keep one row and remove legacy duplicates. Prefer the explicitly
            # profiled row over a pre-profile row with an empty character.
            primary = max(matching, key=lambda widget: (
                bool(str(widget.runtime_character or '').strip()),
                widget.end_time))
            primary.spell = spell
            primary.runtime_character = str(
                character or primary.runtime_character or '')
            primary.runtime_server = str(server or primary.runtime_server or '')
            primary.recast(timestamp)
            for duplicate in matching:
                if duplicate is not primary:
                    duplicate._remove()
        else:
            self._layout.addWidget(SpellWidget(
                spell, timestamp, character, server))
        if self.name in ('__you__', '__custom__', '__utility__'):
            self.target_label.setProperty('TargetType', 0)  # user
        elif not target_type:  # treat target like enemy
            self.target_label.setProperty('TargetType', 2)  # enemy
        else:
            self.target_label.setProperty('TargetType', 1)  # friendly
        self.target_label.setStyle(self.target_label.style())

        self._sort_spell_widgets()
        self.set_instance_number(self.instance_number)

    def _sort_spell_widgets(self):
        """Place the next spell to expire first, including after a recast."""
        for index, widget in enumerate(sorted(
                self.findChildren(SpellWidget), key=_spell_widget_sort_key)):
            self._layout.insertWidget(
                index + 1, widget)  # + 1 keeps the target label pinned


class SpellProgressBar(QProgressBar):
    """Compact flat progress bar with its name and countdown painted inside."""

    def __init__(self, spell_name):
        super().__init__()
        self._spell_name = string.capwords(spell_name)
        self._time_text = ''
        self.setTextVisible(False)
        self.setAccessibleName(f'{self._spell_name} spell timer')

    def set_time_text(self, text):
        self._time_text = str(text)
        self.setAccessibleDescription(
            f'{self._spell_name} has faded'
            if self._time_text == 'FADED' else
            f'{self._spell_name}, {self._time_text} remaining')
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        font = self.font()
        font.setFamily('Segoe UI')
        font.setPixelSize(max(9, min(11, self.height() - 7)))
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        time_width = metrics.horizontalAdvance(self._time_text)
        right_edge = max(4, self.width() - 4)
        name_width = max(0, right_edge - time_width - 11)
        name = metrics.elidedText(
            self._spell_name, Qt.TextElideMode.ElideRight, name_width)
        name_rect = self.rect().adjusted(4, 0, -(time_width + 8), 0)
        time_rect = self.rect().adjusted(
            max(4, self.width() - time_width - 4), 0, -4, 0)
        jitter = (
            1 if self.property('Critical') and self.property('Pulse') else 0)
        if jitter:
            name_rect.translate(jitter, 0)
            time_rect.translate(-jitter, 0)
        left_flags = (
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right_flags = (
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # One restrained one-pixel shadow keeps text legible on every school
        # color without adding glow or another UI layer.
        painter.setPen(QColor(0, 0, 0, 205))
        painter.drawText(name_rect.translated(1, 1), left_flags, name)
        painter.drawText(
            time_rect.translated(1, 1), right_flags, self._time_text)
        painter.setPen(QColor(
            '#FFFFFF' if self.property('Critical') else
            '#FFF0C2' if self.property('Warning') else '#F7F8F8'))
        painter.drawText(name_rect, left_flags, name)
        painter.drawText(time_rect, right_flags, self._time_text)
        painter.end()


class SpellWidget(QFrame):

    def __init__(self, spell, timestamp, character='', server=''):
        super().__init__()
        self.setObjectName('SpellWidget')
        self.spell = spell
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f'{self.spell.name} spell timer')
        self.runtime_character = str(character or '')
        self.runtime_server = str(server or '')
        self._active = True
        self._removed = False
        self._faded = False
        self._faded_until = 0.0
        self._ignore_worn_off_until = None
        self._warning_played = bool(getattr(
            self.spell, 'saved_warning_played', False))

        self._fade_remove_timer = QTimer(self)
        self._fade_remove_timer.setSingleShot(True)
        self._fade_remove_timer.timeout.connect(self._remove_if_still_faded)

        self._setup_ui()
        # Child construction can cause some Qt platform styles to restore a
        # QFrame's default NoFocus policy. Set this after the complete row is
        # assembled so keyboard removal and actions remain reliable.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._calculate(timestamp)
        self.setProperty('Warning', False)
        self._update()

    def _calculate(self, timestamp):
        try:
            runtime_level = max(1, min(65, int(getattr(
                self.spell, 'runtime_level',
                config.data['spells']['level']))))
        except (TypeError, ValueError):
            runtime_level = max(1, min(
                65, int(config.data['spells']['level'])))
        self._ticks = get_spell_duration(
            self.spell, runtime_level)
        explicit_seconds = getattr(self.spell, 'duration_seconds', None)
        try:
            calculated = int(explicit_seconds)
        except (TypeError, ValueError):
            calculated = 0
        if calculated <= 0:
            calculated = self._ticks * 6
        restored = int(getattr(
            self.spell, 'saved_remaining_seconds', calculated))
        self._seconds = max(calculated, restored)
        remaining = max(0, min(self._seconds, restored))
        self.end_time = timestamp + datetime.timedelta(seconds=remaining)
        self.progress.setMaximum(self._seconds)

    def _setup_ui(self):
        # Keep the row itself lean while giving nearly all of its height to
        # the useful coloured timer surface. The local progress-bar style
        # also overrides the application's generic 7 px progress-bar cap.
        self.setFixedHeight(26)
        layout = QHBoxLayout()
        layout.setContentsMargins(1, 2, 2, 2)
        self.setLayout(layout)
        icon_label = get_spell_icon(
            self.spell.spell_icon, self.spell.name)
        icon_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(icon_label, 0)
        layout.setSpacing(2)

        self.progress = SpellProgressBar(self.spell.name)
        self.progress.setProperty('Warning', False)
        self.progress.setProperty('Critical', False)
        self.progress.setProperty('Pulse', False)
        self.progress.setProperty('Faded', False)
        if self.spell.type:
            self.progress.setObjectName('SpellWidgetProgressBarGood')
        else:
            self.progress.setObjectName('SpellWidgetProgressBarBad')
        self.progress.setStyleSheet(spell_progress_stylesheet(self.spell))
        # Apply the real widget metric after QSS so border-box arithmetic in
        # Qt cannot silently grow the 22 px bar back to 24 px.
        self.progress.setFixedHeight(22)
        self.progress.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self.progress, 1)
        school = spell_school_name(self.spell)
        item_source = str(getattr(self.spell, 'source_item', '') or '')
        source_text = f'Item click · {item_source} · ' if item_source else ''
        self.progress.setToolTip(
            f'{source_text}{school} · visual progress of the spell time remaining')
        self.setToolTip(
            f'{source_text}{school} · double-click to remove; right-click, '
            'Enter, Space, Shift+F10, or Menu for mob assignment, sound, and '
            'remove actions')
        target_kind = 'beneficial or personal' if self.spell.type else 'hostile'
        self.setAccessibleDescription(
            f'{target_kind} {school} timer; double-click or press Delete to '
            'remove; press Enter, Space, Shift+F10, or Menu for actions')
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._sound_menu)

    def recast(self, timestamp):
        self._calculate(timestamp)
        self.progress.setStyleSheet(spell_progress_stylesheet(self.spell))
        self._fade_remove_timer.stop()
        self._active = True
        self._faded = False
        self._faded_until = 0.0
        try:
            self._ignore_worn_off_until = timestamp + datetime.timedelta(
                seconds=RECAST_WORN_OFF_GRACE_SECONDS)
        except TypeError:
            self._ignore_worn_off_until = None
        self._warning_played = False
        self.setProperty('Warning', False)
        self.setProperty('Critical', False)
        self.setProperty('Pulse', False)
        self.progress.setProperty('Warning', False)
        self.progress.setProperty('Critical', False)
        self.progress.setProperty('Pulse', False)
        self.progress.setProperty('Faded', False)
        self.setStyle(self.style())
        self.progress.setStyle(self.progress.style())
        school = spell_school_name(self.spell)
        item_source = str(getattr(self.spell, 'source_item', '') or '')
        source_text = f'Item click · {item_source} · ' if item_source else ''
        self.progress.setToolTip(
            f'{source_text}{school} · visual progress of the spell time remaining')
        self.setToolTip(
            f'{source_text}{school} · double-click to remove; right-click, '
            'Enter, Space, Shift+F10, or Menu for mob assignment, sound, and '
            'remove actions')
        # Clear a visible FADED label immediately. Calling _update() here
        # would create another recurring callback chain, so refresh only the
        # active display while the existing chain continues normally.
        remaining = self.end_time - datetime.datetime.now()
        self.progress.setValue(max(0, int(remaining.total_seconds())))
        self.progress.set_time_text(format_time(remaining))
        self.progress.update()
        self._request_resort()
        self._notify_state_changed()

    def ignores_replaced_worn_off(self, timestamp):
        """Ignore only the stale wear-off emitted by a just-replaced buff."""
        if self._ignore_worn_off_until is None or timestamp is None:
            return False
        try:
            return timestamp <= self._ignore_worn_off_until
        except TypeError:
            return False

    def _remove_if_still_faded(self):
        if self._faded and not self._removed:
            self._remove()

    def _update(self):
        if self._removed:
            return
        refresh_ms = 1000
        if self._faded:
            now = time.monotonic()
            if now >= self._faded_until:
                self._remove()
                return
            pulse = (
                False if config.data['general'].get('reduce_motion') else
                bool(int(now * 4) % 2))
            self.progress.setValue(self.progress.maximum())
            self.progress.set_time_text('FADED')
            self.progress.setProperty('Warning', False)
            self.progress.setProperty('Critical', False)
            self.progress.setProperty('Faded', True)
            self.progress.setProperty('Pulse', pulse)
            self.progress.setStyle(self.progress.style())
            QTimer.singleShot(250 if not config.data['general'].get(
                'reduce_motion') else 1000, self._update)
            return
        if self._active:
            remaining = self.end_time - datetime.datetime.now()
            remaining_seconds = remaining.total_seconds()
            self.progress.setValue(max(0, int(remaining_seconds)))
            self.progress.update()
            warning, critical, pulse, refresh_ms = spell_warning_state(
                remaining_seconds,
                config.data['spells']['fade_warning_seconds'],
                config.data['general'].get('reduce_motion'))
            self.progress.setProperty('Warning', warning)
            self.progress.setProperty('Critical', critical)
            self.progress.setProperty('Pulse', pulse)
            self.progress.setStyle(self.progress.style())
            if warning:
                if remaining_seconds > 0 and not self._warning_played:
                    self._warning_played = True
                    self._play_fade_alert()
            if remaining_seconds <= 0:
                self._remove()
                return
            self.progress.set_time_text(format_time(remaining))
        if not self._removed:
            QTimer.singleShot(refresh_ms if self._active else 1000, self._update)

    def pause(self):
        self._active = False
        self._notify_state_changed()

    def resume(self):
        if self._faded:
            return
        self._active = True
        self._request_resort()
        self._notify_state_changed()

    def mark_faded(self, timestamp=None, play_sound=True):
        """Keep an early worn-off effect visible as a red blinking FADED row."""
        if self._removed or self._faded:
            return
        self._faded = True
        self._active = False
        self._faded_until = time.monotonic() + 6.0
        self._fade_remove_timer.start(6000)
        if timestamp is not None:
            self.end_time = timestamp
        target = self.parentWidget()
        target_name = (
            target.target_label.text()
            if target and hasattr(target, 'target_label') else 'matched target')
        tooltip = (
            f'{self.spell.name} worn off · matched to {target_name} · '
            'the row remains for 6 seconds')
        self.progress.setToolTip(tooltip)
        self.setToolTip(tooltip)
        if play_sound and not self._warning_played:
            self._warning_played = True
            self._play_fade_alert()
        self._request_resort()
        self._notify_state_changed()
        self._update()

    def elongate(self, seconds):
        self.end_time += datetime.timedelta(seconds=seconds)
        self._request_resort()
        self._notify_state_changed()

    def _request_resort(self):
        target = self.parentWidget()
        if target and hasattr(target, '_sort_spell_widgets'):
            target._sort_spell_widgets()

    def _owner_container(self):
        target = self.parentWidget()
        owner = target.parentWidget() if isinstance(target, SpellTarget) else None
        return target, owner

    def _notify_state_changed(self):
        _target, owner = self._owner_container()
        if owner and hasattr(owner, 'state_changed'):
            owner.state_changed.emit()

    def _remove(self):
        if self._removed:
            return
        self._fade_remove_timer.stop()
        target, owner = self._owner_container()
        focus_target = None
        if target:
            siblings = [
                widget for widget in target.spell_widgets()
                if widget is not self and not widget._removed]
            if siblings:
                focus_target = siblings[0]
            elif owner:
                other_targets = [
                    candidate for candidate in owner.spell_targets()
                    if candidate is not target and not candidate._removed]
                if other_targets:
                    focus_target = other_targets[0].target_label
                else:
                    focus_target = getattr(
                        self.window(), '_character_widget', None)
        self._removed = True
        self.setParent(None)
        self.deleteLater()
        if owner and hasattr(owner, '_spell_widget_removed'):
            owner._spell_widget_removed(target)
        if focus_target is not None:
            QTimer.singleShot(0, lambda: focus_target.setFocus(
                Qt.FocusReason.OtherFocusReason))

    def _play_fade_alert(self, force=False):
        settings = config.data['spells']
        key = self.spell.name
        if not force and (
                not settings['fade_sound_enabled'] or
                key in settings['fade_sound_muted']):
            return
        path = settings['fade_sound_overrides'].get(
            key, settings['fade_sound_path'])
        play_alert(
            path, settings['fade_sound_volume'], 1,
            source=("Test" if force else "Buff fading") +
            f" · {self.spell.name}",
            character=self.runtime_character,
            server=self.runtime_server,
            channel='' if force else 'spells',
            allow_hidden=bool(force))

    def _sound_menu(self, position):
        settings = config.data['spells']
        key = self.spell.name
        menu = QMenu(self)
        target, owner = self._owner_container()
        move_actions = {}
        new_target_action = None
        if (isinstance(target, SpellTarget) and owner and
                not target.is_named and not target.name.startswith('__')):
            assign_menu = menu.addMenu('Assign effect to tracked mob')
            assign_menu.setToolTipsVisible(True)
            for candidate in owner.get_spell_targets_by_name(target.name):
                label = candidate.alias or candidate.instance_marker
                candidate_has_effect = bool(candidate.spell_widget(str(getattr(
                    self.spell, 'runtime_key', self.spell.name))))
                action = assign_menu.addAction(
                    f'{candidate.title.title()} · {label}' +
                    (' · current' if candidate is target else ''))
                action.setEnabled(
                    candidate is not target and not candidate_has_effect)
                action.setToolTip(
                    'This mob already has this effect' if candidate_has_effect else
                    'Move this effect without restarting its countdown')
                move_actions[action] = candidate
            new_target_action = assign_menu.addAction(
                f'New {target.title.title()} mob')
            new_target_action.setToolTip(
                'Create another stable mob marker and move this effect there')
            menu.addSeparator()
        gallery = menu.addMenu('Sound gallery')
        gallery_actions = {}
        for label, uri, description in sound_choices():
            gallery_actions[gallery.addAction(
                f'{label} · {description}')] = uri
        choose = menu.addAction('Choose custom WAV…')
        use_default = menu.addAction('Use default sound')
        muted = key in settings['fade_sound_muted']
        mute = menu.addAction('Unmute this buff' if muted else 'Mute this buff')
        menu.addSeparator()
        test = menu.addAction('Test fade alert')
        menu.addSeparator()
        remove = menu.addAction('Remove this spell timer')
        action = menu.exec(self.mapToGlobal(position))
        if action in move_actions:
            owner.move_spell_widget(self, move_actions[action])
        elif (new_target_action is not None and
              action is new_target_action and owner):
            owner.move_spell_widget(self)
        elif action in gallery_actions:
            settings['fade_sound_overrides'][key] = gallery_actions[action]
            if key in settings['fade_sound_muted']:
                settings['fade_sound_muted'].remove(key)
            config.save()
        elif action == choose:
            path, _ = QFileDialog.getOpenFileName(
                self, f'Fade sound · {self.spell.name}', '', 'WAV Audio (*.wav)')
            if path:
                settings['fade_sound_overrides'][key] = store_portable_file(path)
                if key in settings['fade_sound_muted']:
                    settings['fade_sound_muted'].remove(key)
                config.save()
        elif action == use_default:
            settings['fade_sound_overrides'].pop(key, None)
            config.save()
        elif action == mute:
            if muted:
                settings['fade_sound_muted'].remove(key)
            else:
                settings['fade_sound_muted'].append(key)
            config.save()
        elif action == test:
            self._play_fade_alert(force=True)
        elif action == remove:
            self._remove()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._remove()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            self._remove()
            event.accept()
            return
        if (event.key() == Qt.Key.Key_Menu or
                (event.key() == Qt.Key.Key_F10 and
                 event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self._sound_menu(self.rect().center())
            event.accept()
            return
        if event.key() in {
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self._sound_menu(self.rect().center())
            event.accept()
            return
        super().keyPressEvent(event)


def _spell_icon_coordinates(icon_index):
    """Compatibility wrapper for the shared Velious atlas helper."""
    return spell_icon_coordinates(icon_index)


def _spell_targets_enemy(spell):
    """Treat classic lull effects as mob effects despite EQ's beneficial bit."""
    return (
        not int(getattr(spell, 'type', 0)) or
        'less aggressive' in str(
            getattr(spell, 'effect_text_other', '')).casefold())


def spell_warning_state(remaining_seconds, warning_seconds=40,
                        reduce_motion=False, clock=None):
    """Return warning, critical, pulse and refresh state for a spell row."""
    remaining = float(remaining_seconds)
    warning = remaining <= max(0, int(warning_seconds))
    critical = warning and remaining <= 20
    if reduce_motion or not warning:
        pulse = False
    else:
        current = time.monotonic() if clock is None else float(clock)
        pulse = bool(int(current * (4 if critical else 1)) % 2)
    refresh_ms = 250 if critical and not reduce_motion else 1000
    return warning, critical, pulse, refresh_ms


def _spell_target_sort_key(target):
    """Pin utility sections, then order enemy mobs by latest spell activity."""
    target_type = int(target.target_label.property('TargetType') or 0)
    system_order = {
        '__you__': 0,
        '__custom__': 1,
        '__utility__': 2,
    }
    if target_type == 0:
        return target_type, system_order.get(target.name, 10), target.name.casefold()
    if target_type == 2:
        return target_type, -int(target.last_activity_order), target.name.casefold()
    return target_type, 0, target.name.casefold()


def _spell_widget_sort_key(widget):
    """Sort stable countdown rows by expiry, then spell name for equal times."""
    return widget.end_time, str(widget.spell.name).casefold()


SPELL_SCHOOLS = {
    4: 'Abjuration',
    5: 'Alteration',
    14: 'Conjuration',
    18: 'Divination',
    24: 'Evocation',
}
def spell_school_name(spell):
    """Return the EQ casting skill represented by the client spell record."""
    skill = int(getattr(spell, 'skill', 0) or 0)
    return SPELL_SCHOOLS.get(skill, 'Other casting skill')


@functools.lru_cache(maxsize=256)
def _spell_icon_accent(icon_index):
    """Extract the dominant chromatic family from the exact Velious icon art."""
    # Sample the native 40 px cell. Sampling the 20 px display copy allowed
    # dark outlines to outvote the actual artwork on detailed icons.
    image = spell_icon_pixmap(int(icon_index or 0), 40).toImage()
    hue_bins = {}
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            saturation = color.saturation()
            value = color.value()
            hue = color.hue()
            if (color.alpha() < 96 or value < 34 or
                    saturation < 38 or hue < 0):
                continue
            # Twenty-four hue families are narrow enough to keep blue, teal,
            # amber and red icons distinct while grouping their pixel-art
            # highlights and shadows. Chroma is deliberately weighted more
            # than luminance so gray borders never become the bar color.
            key = int((hue + 7.5) // 15) % 24
            weight = (0.35 + (saturation / 255.0) ** 1.65 * 2.8) * (
                0.55 + value / 255.0 * 0.45)
            total, red, green, blue = hue_bins.get(key, (0.0, 0.0, 0.0, 0.0))
            hue_bins[key] = (
                total + weight,
                red + color.red() * weight,
                green + color.green() * weight,
                blue + color.blue() * weight)
    if not hue_bins:
        # Empty/unused icon cells get the same blue fallback treatment and
        # bounds as real art; never bypass the readable palette pipeline.
        accent = QColor('#477B91')
    else:
        total, red, green, blue = max(
            hue_bins.values(), key=lambda values: values[0])
        accent = QColor(
            round(red / total), round(green / total), round(blue / total))
    hue, saturation, value, alpha = accent.getHsv()
    if hue < 0:
        hue = 198
    # Retain the icon's hue while putting every fill in the same restrained
    # value range. Give the native pixel-art chroma a deliberate but bounded
    # lift: bars should read as the icon's color at a glance while the shared
    # dark value ceiling keeps white countdown text comfortably legible.
    boosted_saturation = saturation + max(28, round(saturation * 0.26))
    return QColor.fromHsv(
        hue, max(156, min(248, boosted_saturation)),
        # The label crosses both the filled and empty portions of the bar,
        # so every art-derived fill must remain dark enough for the same
        # off-white text to stay readable across the whole countdown.
        max(102, min(122, value)), alpha)


def _spell_bar_contrast(foreground, background):
    """Return the measured sRGB contrast of a painted label and bar stop."""
    def luminance(color):
        channels = []
        for channel in (color.redF(), color.greenF(), color.blueF()):
            channels.append(
                channel / 12.92 if channel <= 0.04045 else
                ((channel + 0.055) / 1.055) ** 2.4)
        return (0.2126 * channels[0] + 0.7152 * channels[1] +
                0.0722 * channels[2])

    foreground_luminance = luminance(foreground)
    background_luminance = luminance(background)
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _readable_spell_bar_color(color, minimum_contrast=4.5):
    """Darken only value until off-white timer text meets normal-text AA."""
    foreground = QColor('#F7F8F8')
    hue, saturation, value, alpha = color.getHsv()
    while (value > 0 and
           _spell_bar_contrast(foreground, color) < minimum_contrast):
        value -= 1
        color = QColor.fromHsv(hue, saturation, value, alpha)
    return color


def spell_progress_palette(spell):
    """Build a moderately chromatic, readable palette from the spell icon."""
    body = _spell_icon_accent(int(getattr(spell, 'spell_icon', 0) or 0))
    hue, saturation, value, alpha = body.getHsv()
    highlight = _readable_spell_bar_color(QColor.fromHsv(
        hue, max(96, saturation - 8), min(170, value + 18), alpha))
    body = _readable_spell_bar_color(body)
    depth = _readable_spell_bar_color(QColor.fromHsv(
        hue, min(248, saturation + 10), max(62, value - 16), alpha))
    border = QColor.fromHsv(
        hue, max(112, min(232, saturation - 18)),
        min(162, value + 10), alpha)
    return tuple(color.name(QColor.NameFormat.HexRgb).upper() for color in (
        highlight, body, depth, border))


def spell_progress_stylesheet(spell):
    """A compact, gently dimensional bar keyed to the real icon artwork."""
    highlight, body, depth, border = spell_progress_palette(spell)
    return f"""
        QProgressBar {{
            min-height: 20px;
            max-height: 20px;
            border: 1px solid {border};
            border-radius: 5px;
            padding: 0px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #111820, stop:0.22 #0C1218, stop:1 #080C10);
        }}
        QProgressBar::chunk {{
            border-radius: 4px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {highlight}, stop:0.20 {body},
                stop:0.78 {body}, stop:1 {depth});
        }}
        QProgressBar[Warning="true"] {{
            border-color: #E7B85D;
        }}
        QProgressBar[Warning="true"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #A76D1D, stop:0.22 #855312, stop:1 #593509);
        }}
        QProgressBar[Warning="true"][Pulse="true"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #BC812D, stop:0.22 #9A6515, stop:1 #68410B);
        }}
        QProgressBar[Critical="true"] {{
            border-color: #E35B5B;
        }}
        QProgressBar[Critical="true"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #D05258, stop:0.22 #B3363C, stop:1 #772329);
        }}
        QProgressBar[Critical="true"][Pulse="true"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #E25A62, stop:0.22 #BC353C, stop:1 #812229);
        }}
        QProgressBar[Faded="true"] {{
            border-color: #B54149;
        }}
        QProgressBar[Faded="true"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #BF414A, stop:0.22 #9B2831, stop:1 #671A22);
        }}
        QProgressBar[Faded="true"][Pulse="true"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #EC626B, stop:0.22 #D13E48, stop:1 #8D232C);
        }}
    """


def get_spell_icon(icon_index, spell_name=''):
    """Return the matching zero-based square Velious spell icon."""
    scaled_icon_image = spell_icon_pixmap(icon_index, 20)
    label = QLabel()
    label.setPixmap(scaled_icon_image)
    label.setFixedSize(20, 20)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    readable_name = string.capwords(spell_name) if spell_name else 'Spell'
    label.setAccessibleName(f'Icon for {readable_name}')
    label.setToolTip(
        f'{readable_name} · Velious spell icon {int(icon_index)}')
    return label


class Spell:

    def __init__(self, **kwargs):
        self.id = 0
        self.name = ''
        self.effect_text_you = ''
        self.effect_text_other = ''
        self.effect_text_worn_off = ''
        self.aoe_range = 0
        self.max_targets = 1
        self.cast_time = 0
        self.resist_type = 0
        self.duration_formula = 0
        self.pvp_duration_formula = 0
        self.duration = 0
        self.pvp_duration = 0
        self.type = 0
        self.spell_icon = 0
        self.skill = 0
        self.target_type = 0
        self.class_levels = ()
        self.item_only = False
        self.source_item = ''
        self.__dict__.update(kwargs)


class SpellTrigger(QObject):

    spell_triggered = Signal(object)
    target_detected = Signal(object, int)

    def __init__(self, **kwargs):
        super().__init__()
        self.timestamp = None  # datetime
        self.spell = None  # Spell
        self.__dict__.update(kwargs)

        self.targets = []  # [(timestamp, target)]
        self.delivered_target_indexes = set()
        self.activated = False
        self._item_cast_timestamp = None

        # create casting trigger window
        self._times_up_timer = QTimer(self)
        self._times_up_timer.setSingleShot(True)
        self._times_up_timer.timeout.connect(self._times_up)
        if config.data['spells']['use_casting_window']:
            buffer_ms = config.data['spells']['casting_window_buffer']
            # Start cleanup from when the log line was consumed, not from its
            # wall-clock timestamp. On startup a backlog is parsed in a burst;
            # subtracting that backlog age used to expire every cast before its
            # immediately-following landing line could be read.
            expiry_delay = int(
                self.spell.cast_time + buffer_ms + SPELL_LANDING_GRACE_MS)
            self._times_up_timer.start(max(1, expiry_delay))
        else:
            self.activated = True

    def parse(self, timestamp, text):
        if self._item_cast_timestamp is not None:
            try:
                elapsed_ms = (
                    timestamp - self._item_cast_timestamp).total_seconds() * 1000
            except (AttributeError, TypeError):
                return
            in_window = 0 <= elapsed_ms <= ITEM_CLICK_WINDOW_SECONDS * 1000
        elif config.data['spells']['use_casting_window']:
            try:
                elapsed_ms = (
                    timestamp - self.timestamp).total_seconds() * 1000
            except (AttributeError, TypeError):
                return
            buffer_ms = config.data['spells']['casting_window_buffer']
            earliest = max(0, int(self.spell.cast_time) - buffer_ms)
            latest = (
                int(self.spell.cast_time) + buffer_ms +
                SPELL_LANDING_GRACE_MS)
            in_window = earliest <= elapsed_ms <= latest
        else:
            in_window = True
        if in_window:
            folded = str(text or '').casefold()
            effect_you = str(self.spell.effect_text_you or '')
            effect_other = str(self.spell.effect_text_other or '')
            if effect_you and folded.startswith(effect_you.casefold()):
                # cast self
                self.targets.append((timestamp, '__you__'))
            elif effect_other and folded.endswith(effect_other.casefold()):
                # cast other
                target = text[:-len(effect_other)].strip()
                self.targets.append((timestamp, target))
            elif _is_charm_spell(self.spell):
                target = _charmed_pet_from_activity(text)
                if target:
                    landed = self.timestamp + datetime.timedelta(
                        milliseconds=max(
                            0, int(getattr(self.spell, 'cast_time', 0) or 0)))
                    self.targets.append((landed, target))
            if self.targets:
                self.activated = True
                # Do not hold confirmed group/AOE targets until the cleanup
                # window expires. The direct Qt signal updates the row in the
                # same event that consumed the EQ log line.
                self.target_detected.emit(self, len(self.targets) - 1)
            if self.targets and self.spell.max_targets == 1:
                self.stop()  # make sure you don't get two triggers
                self.activated = True
                self.spell_triggered.emit(self)

    def mark_item_cast(self, item_name, timestamp=None):
        """Trust a player-owned item glow and widen the item's landing window."""
        if not getattr(self.spell, 'source_item', ''):
            self.spell = copy.copy(self.spell)
        self.spell.source_item = str(item_name or 'Item click')
        self._item_cast_timestamp = timestamp or self.timestamp
        self.stop()
        self.activated = True
        self._times_up_timer.start(round(ITEM_CLICK_WINDOW_SECONDS * 1000))

    def _times_up(self):
        self.spell_triggered.emit(self)

    def stop(self):
        self._times_up_timer.stop()


def create_spell_book():
    """ Returns a dictionary of Spell by k, v -> spell_name, Spell() """
    spell_book = {}
    self_candidates = {}
    other_candidates = {}
    with open(resource_path('data/spells/spells_us.txt')) as spell_file:
        for line in spell_file:
            values = line.strip().split('^')
            spell = Spell(
                id=int(values[0]),
                name=values[1].lower(),
                effect_text_you=values[6],
                effect_text_other=values[7],
                effect_text_worn_off=values[8],
                aoe_range=int(values[10]),
                max_targets=(6 if int(values[10]) > 0 else 1),
                cast_time=int(values[13]),
                resist_type=int(values[85]),
                duration_formula=int(values[16]),
                pvp_duration_formula=int(values[181]),
                duration=int(values[17]),
                pvp_duration=int(values[182]),
                type=int(values[83]),
                spell_icon=int(values[144]),
                skill=int(values[100]),
                target_type=int(values[98]),
                class_levels=tuple(
                    int(values[index]) for index in range(104, 120)),
                item_only=all(
                    int(values[index]) == 255
                    for index in range(104, 120))
            )
            spell_book[values[1]] = spell
            if spell.effect_text_you:
                self_candidates.setdefault(
                    spell.effect_text_you.casefold(), []).append(spell)
            if spell.effect_text_other:
                other_candidates.setdefault(
                    spell.effect_text_other.casefold(), []).append(spell)
    # A landing sentence is not an item identity. P99 has dozens of effects
    # such as "You feel different." shared by unrelated illusions. Keep only
    # messages that resolve to one spell name; a player-owned item-glow plus
    # the P99 clicky index handles ambiguous effects explicitly.
    text_lookup_self = {
        candidates[-1].effect_text_you: candidates[-1]
        for candidates in self_candidates.values()
        if len({spell.name.casefold() for spell in candidates}) == 1
    }
    text_lookup_other = {
        candidates[-1].effect_text_other: candidates[-1]
        for candidates in other_candidates.values()
        if len({spell.name.casefold() for spell in candidates}) == 1
    }
    return spell_book, text_lookup_self, text_lookup_other


def get_spell_duration(spell, level):
    if spell.name in config.data['spells']['use_secondary']:
        formula, duration = spell.pvp_duration_formula, spell.pvp_duration
    elif config.data['spells']['use_secondary_all'] and spell.type == 0:
        formula, duration = spell.pvp_duration_formula, spell.pvp_duration
    else:
        formula, duration = spell.duration_formula, spell.duration

    spell_ticks = 0
    if formula == 0:
        spell_ticks = 0
    if formula == 1:
        spell_ticks = int(math.ceil(level / float(2.0)))
        spell_ticks = min(spell_ticks, duration)
    if formula == 2:
        spell_ticks = int(math.ceil(level / float(5.0) * 3))
        spell_ticks = min(spell_ticks, duration)
    if formula == 3:
        spell_ticks = int(level * 30)
        spell_ticks = min(spell_ticks, duration)
    if formula == 4:
        if duration == 0:
            spell_ticks = 50
        else:
            spell_ticks = duration
    if formula == 5:
        spell_ticks = duration
        if spell_ticks == 0:
            spell_ticks = 3
    if formula == 6:
        spell_ticks = int(math.ceil(level / float(2.0)))
        spell_ticks = min(spell_ticks, duration)
    if formula == 7:
        spell_ticks = level
        spell_ticks = min(spell_ticks, duration)
    if formula == 8:
        spell_ticks = level + 10
        spell_ticks = min(spell_ticks, duration)
    if formula == 9:
        spell_ticks = int((level * 2) + 10)
        spell_ticks = min(spell_ticks, duration)
    if formula == 10:
        spell_ticks = int(level * 3 + 10)
        spell_ticks = min(spell_ticks, duration)
    if formula == 11:
        spell_ticks = duration
    if formula == 12:
        spell_ticks = duration
    if formula == 15:
        spell_ticks = duration
    if formula == 50:
        spell_ticks = 72000
    if formula == 3600:
        if duration == 0:
            spell_ticks = 3600
        else:
            spell_ticks = duration
    return spell_ticks


class CustomTrigger:

    def __init__(self, name='', text='', time='', zone='', sound_path='',
                 alert_text='', enabled=True, regex=False,
                 source='Vantage', category='Default',
                 overlay_id='auto', restart_behavior='restart',
                 end_text='', profile='', comments='', timer_type='auto',
                 timer_visible_seconds=0, timer_ending_seconds=0,
                 timer_ending_alert='', timer_ending_sound='',
                 timer_ended_alert='', timer_ended_sound='',
                 counter_reset_seconds=0, clipboard_text='',
                 end_patterns=None, tts_text='', interrupt_speech=False,
                 timer_ending_tts='', timer_ending_interrupt=False,
                 timer_ended_tts='', timer_ended_interrupt=False,
                 text_color='', timer_name='',
                 restart_based_on_timer_name=False, **_):
        self.name, self.text, self.time = name, text, time
        self.zone = zone
        self.sound_path = sound_path
        self.alert_text = alert_text
        self.enabled = bool(enabled)
        self.regex = bool(regex)
        self.source = str(source or 'Vantage')
        self.category = str(category or 'Default').strip() or 'Default'
        overlay_definitions = config.data.get('general', {}).get(
            'notification_overlays', {})
        valid_overlay_ids = set(overlay_definitions)
        if overlay_id != 'none' and overlay_id not in valid_overlay_ids:
            preferred_type = (
                'timer' if text_time_to_seconds(self.time) > 0 else 'text')
            overlay_id = next((
                candidate_id for candidate_id, settings
                in overlay_definitions.items()
                if settings.get('type', 'text') == preferred_type
                and settings.get('enabled', True)), '')
            if not overlay_id:
                overlay_id = next(iter(valid_overlay_ids), (
                    'timers' if preferred_type == 'timer' else 'alerts'))
        self.overlay_id = overlay_id
        self.restart_behavior = (
            restart_behavior if restart_behavior in ('restart', 'keep', 'new')
            else 'restart')
        self.timer_name = str(timer_name or '').strip()
        self.restart_based_on_timer_name = bool(
            restart_based_on_timer_name)
        self.end_text = str(end_text or '')
        self.profile = str(profile or '').strip()
        self.comments = str(comments or '')
        if timer_type == 'auto':
            timer_type = (
                'countdown' if text_time_to_seconds(self.time) > 0
                else 'none')
        self.timer_type = (
            timer_type if timer_type in (
                'none', 'countdown', 'stopwatch', 'repeating')
            else 'countdown')
        if (self.timer_type in ('countdown', 'repeating') and
                text_time_to_seconds(self.time) <= 0 and
                '{ts}' not in self.text.casefold()):
            self.timer_type = 'none'
        def nonnegative(value):
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        self.timer_visible_seconds = nonnegative(timer_visible_seconds)
        self.timer_ending_seconds = nonnegative(timer_ending_seconds)
        self.timer_ending_alert = str(timer_ending_alert or '')
        self.timer_ending_sound = str(timer_ending_sound or '')
        self.timer_ended_alert = str(timer_ended_alert or '')
        self.timer_ended_sound = str(timer_ended_sound or '')
        self.counter_reset_seconds = nonnegative(counter_reset_seconds)
        self.clipboard_text = str(clipboard_text or '')
        patterns = end_patterns if isinstance(end_patterns, list) else []
        self.end_patterns = [
            dict(pattern) for pattern in patterns
            if isinstance(pattern, dict) and str(pattern.get('text') or '').strip()]
        if self.end_text and not self.end_patterns:
            self.end_patterns.append({
                'text': self.end_text, 'regex': self.regex})
        self.tts_text = str(tts_text or '')
        self.interrupt_speech = bool(interrupt_speech)
        self.timer_ending_tts = str(timer_ending_tts or '')
        self.timer_ending_interrupt = bool(timer_ending_interrupt)
        self.timer_ended_tts = str(timer_ended_tts or '')
        self.timer_ended_interrupt = bool(timer_ended_interrupt)
        self.text_color = normalize_trigger_color(text_color)
        self.counter = 0
        self.last_fired = 0.0
        self.active_names = []
        self.runtime_character = ''

    def to_list(self):
        return [
            self.name, self.text, self.time, self.zone,
            self.sound_path, self.alert_text, self.enabled,
            self.regex, self.source, self.category, self.overlay_id,
            self.restart_behavior, self.end_text, self.profile,
            self.comments, self.timer_type, self.timer_visible_seconds,
            self.timer_ending_seconds, self.timer_ending_alert,
            self.timer_ending_sound, self.timer_ended_alert,
            self.timer_ended_sound, self.counter_reset_seconds,
            self.clipboard_text, self.end_patterns, self.tts_text,
            self.interrupt_speech, self.timer_ending_tts,
            self.timer_ending_interrupt, self.timer_ended_tts,
            self.timer_ended_interrupt, self.text_color, self.timer_name,
            self.restart_based_on_timer_name]

    def __str__(self):
        return '{},{},{}'.format(
            self.name, self.text, self.time
        )
