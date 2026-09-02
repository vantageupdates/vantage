import datetime
import copy
import functools
import hashlib
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
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                             QLabel, QMenu, QProgressBar, QScrollArea, QSpinBox,
                             QSizePolicy, QToolButton, QVBoxLayout, QPushButton,
                             QWidget)

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
COMMON_ITEM_CLICK_SPELLS = {
    "journeyman's boots": "JourneymanBoots",
    "elder spiritist's gauntlets": "Snare",
    "elder spiritist's vambraces": "Drones of Doom",
    "spear of fate": "Curse of the Spirits",
    "fungi covered great staff": "Fungal Regrowth",
}


@functools.lru_cache(maxsize=512)
def item_click_spell_name(item_name):
    """Resolve an item to its exact P99 click spell from the cached index."""
    item_name = str(item_name or '').strip()
    common = COMMON_ITEM_CLICK_SPELLS.get(item_name.casefold())
    if common:
        return common
    database = data_dir('cache', create=False) / 'p99-item-metadata.sqlite'
    if not database.is_file():
        return ''
    try:
        with sqlite3.connect(
                f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT clickName FROM items WHERE name = ? COLLATE NOCASE "
                "AND trim(coalesce(clickName, '')) <> '' LIMIT 1",
                (item_name,)).fetchone()
        return str(row[0]).strip() if row else ''
    except sqlite3.Error:
        return ''


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
        self._spell_triggers = []  # need a queue because of landing windows
        self._spell_trigger = None
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
        self._level_widget = QSpinBox()
        self._level_widget.setRange(1, 65)
        self._level_widget.setValue(config.data['spells']['level'])
        self._level_widget.setPrefix('lvl. ')
        self._level_widget.setAccessibleName('Character level')
        self._level_widget.setToolTip(
            'Level used to calculate the correct buff duration')
        self.menu_area.addWidget(self._level_widget, 0)
        self._level_widget.valueChanged.connect(self._level_change)
        self._camp_state = ''

    def _spell_triggered(self):
        """SpellTrigger spell_triggered event handler. """
        if self._spell_trigger:
            if self._spell_trigger.activated:
                for target in self._spell_trigger.targets:
                    self._spell_container.add_spell(
                        self._spell_trigger.spell, target[0], target[1],
                        getattr(self, '_active_character', ''),
                        getattr(self, '_active_server', ''),
                        named=self._is_named_target(target[1]))
        self._remove_spell_trigger()

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
        faded = self._spell_container.mark_worn_off(text, timestamp)
        if faded:
            target = faded.parentWidget()
            self.spell_faded.emit(
                str(getattr(target, 'name', '')),
                str(getattr(faded.spell, 'name', 'Spell')))

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
                                    spell_icon=14)
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
                            server=getattr(self, '_active_server', ''))
                        output.append(
                            f"Sound · {sound_display_name(ct.sound_path)}")
                    if ct.tts_text:
                        speak_text(
                            render_trigger_text(ct.tts_text, match, ct),
                            config.data['spells']['fade_sound_volume'],
                            ct.interrupt_speech,
                            source=f"Trigger · {timer_name} · speech",
                            character=active_character,
                            server=getattr(self, '_active_server', ''))
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
                self._spell_trigger.mark_item_cast(item_name)
        elif config.data['spells']['use_item_triggers']:
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

                spell_trigger = SpellTrigger(
                    spell=spell,
                    timestamp=timestamp
                )
                spell_trigger.spell_triggered.connect(self._spell_triggered)
                self._spell_trigger = spell_trigger

        # Spell Interrupted
        elif (self._spell_triggers and
              text[:26] == 'Your spell is interrupted.' or
              text[:20] == 'Your target resisted' or
              text[:29] == 'Your spell did not take hold.' or
              text[:26] == 'You try to cast a spell on'):
            self._remove_spell_trigger()

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
            type=1)
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
                    server=getattr(self, '_active_server', ''))

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
                server=run.get('server', ''))
            outputs.append(f"Sound · {sound_display_name(sound)}")
        if speech:
            speak_text(
                speech, config.data['spells']['fade_sound_volume'], interrupt,
                source=f"Trigger · {run['name']} · {label} speech",
                character=run.get('character', ''),
                server=run.get('server', ''))
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

    def _remove_spell_trigger(self):
        if self._spell_trigger:
            self._spell_trigger.stop()
            self._spell_trigger.deleteLater()
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
        if context.level:
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
        app = QApplication.instance()
        updater = getattr(app, 'update_character_level', None)
        if updater and getattr(self, '_active_character', ''):
            updater(
                self._active_character,
                getattr(self, '_active_server', ''), level)
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
            QNetworkRequest.KnownHeaders.UserAgentHeader, 'Vantage/1.44.11')
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

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout()
        self.setLayout(self._layout)
        self.setObjectName('SpellContainer')
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addStretch(1)
        self._activity_sequence = 0
        self._target_sequence = 0
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
            not bool(self.findChildren(SpellTarget)) and
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
                named=named)
            self._layout.addWidget(spell_target, 0)

        spell_target.add_spell(spell, timestamp, character, server)
        self._activity_sequence += 1
        spell_target.last_activity_order = self._activity_sequence
        self._renumber_target_instances(target)
        self._reorder_targets()
        self._sync_empty_state()

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

    def mark_worn_off(self, text, timestamp=None):
        """Mark one best matching row FADED without erasing its mob context."""
        worn_text = str(text or '').strip().casefold()
        if not worn_text:
            return None
        matches = []
        for target in self.spell_targets():
            for widget in target.spell_widgets():
                worn_off = str(
                    widget.spell.effect_text_worn_off or '').strip().casefold()
                if worn_off and worn_text == worn_off and not widget._faded:
                    matches.append(widget)
        if not matches:
            return None
        victim = min(matches, key=lambda widget: widget.end_time)
        victim.mark_faded(timestamp)
        return victim

    def _renumber_target_instances(self, name):
        instances = self.get_spell_targets_by_name(name)
        total = len(instances)
        for number, target in enumerate(instances, 1):
            target.set_instance_number(
                number, 1 if target.is_named else total)

    def _target_removed(self, target):
        name = target.name
        QTimer.singleShot(0, lambda: (
            self._renumber_target_instances(name),
            self._sync_empty_state()))

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

    def __init__(self, target='__you__', created_order=0, named=False):
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
        self.is_named = bool(named)
        self.setObjectName('SpellContainer')

        self._setup_ui()

    def _setup_ui(self):
        self._layout = QVBoxLayout()
        self.setLayout(self._layout)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.target_label = QLabel(self.title.title())
        self.target_label.setObjectName('SpellTargetLabel')
        self.target_label.setMinimumHeight(20)
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_label.mouseDoubleClickEvent = self._remove
        self._layout.addWidget(self.target_label, 0)
        self._layout.addStretch()

    def _remove(self, event=None):
        owner = self.parentWidget()
        self.setParent(None)
        self.deleteLater()
        if owner and hasattr(owner, '_target_removed'):
            owner._target_removed(self)
        elif owner and hasattr(owner, '_sync_empty_state'):
            QTimer.singleShot(0, owner._sync_empty_state)

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
        if self.name.startswith('__'):
            return
        base = self.title.title()
        display = (
            f'{base} #{self.instance_number}'
            if int(total) > 1 and not self.is_named else base)
        self.target_label.setText(display)
        if self.is_named:
            tooltip = (
                'Named NPC · Vantage keeps one spell target instance in this zone. '
                'Double-click to remove its timers.')
        elif int(total) > 1:
            tooltip = (
                'EverQuest logs do not expose mob IDs. Vantage separated '
                f'{total} active mobs with this name; a death line removes '
                'the oldest matching instance. Double-click to remove this one.')
        else:
            tooltip = 'Double-click to remove this target and its spell timers'
        self.target_label.setToolTip(tooltip)
        self.target_label.setAccessibleName(display)
        self.target_label.setAccessibleDescription(tooltip)

    def childEvent(self, event):
        if event.type() == QEvent.Type.ChildRemoved:
            if isinstance(event.child(), SpellWidget):
                if not self.findChildren(SpellWidget):
                    self._remove()
        event.accept()

    def add_spell(self, spell, timestamp, character='', server=''):
        target_type = 0 if _spell_targets_enemy(spell) else 1
        recast = False
        spell_key = str(getattr(spell, 'runtime_key', spell.name))
        for sw in self.findChildren(SpellWidget):
            target_type *= 0 if _spell_targets_enemy(sw.spell) else 1
            widget_key = str(getattr(
                sw.spell, 'runtime_key', sw.spell.name))
            if widget_key == spell_key:
                recast = True
                # The log may supply a different authoritative duration on a
                # later cooldown line; replace the timer model before recast.
                sw.spell = spell
                sw.runtime_character = str(character or '')
                sw.runtime_server = str(server or '')
                sw.recast(timestamp)
        if not recast:
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

    def _sort_spell_widgets(self):
        """Place the next spell to expire first, including after a recast."""
        for index, widget in enumerate(sorted(
                self.findChildren(SpellWidget), key=_spell_widget_sort_key)):
            self._layout.insertWidget(
                index + 1, widget)  # + 1 keeps the target label pinned


class SpellProgressBar(QProgressBar):
    """Compact glass progress bar with its name and countdown painted inside."""

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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Preserve the school colour at the rim while giving every timer the
        # same quiet reading surface. This keeps white text legible without a
        # glow and makes mixed-school lists feel like one coherent component.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 8, 11, 118))
        painter.drawRoundedRect(self.rect().adjusted(2, 4, -2, -4), 3, 3)
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
        self.runtime_character = str(character or '')
        self.runtime_server = str(server or '')
        self._active = True
        self._removed = False
        self._faded = False
        self._faded_until = 0.0
        self._warning_played = False

        self._setup_ui()
        self._calculate(timestamp)
        self.setProperty('Warning', False)
        self._update()

    def _calculate(self, timestamp):
        self._ticks = get_spell_duration(
            self.spell, config.data['spells']['level'])
        calculated = int(getattr(
            self.spell, 'duration_seconds', self._ticks * 6))
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
        self.setFixedHeight(28)
        layout = QHBoxLayout()
        layout.setContentsMargins(1, 2, 2, 2)
        self.setLayout(layout)
        layout.addWidget(get_spell_icon(
            self.spell.spell_icon, self.spell.name), 0)
        layout.setSpacing(2)

        self.progress = SpellProgressBar(self.spell.name)
        self.progress.setFixedHeight(24)
        self.progress.setProperty('Warning', False)
        self.progress.setProperty('Critical', False)
        self.progress.setProperty('Pulse', False)
        self.progress.setProperty('Faded', False)
        if self.spell.type:
            self.progress.setObjectName('SpellWidgetProgressBarGood')
        else:
            self.progress.setObjectName('SpellWidgetProgressBarBad')
        self.progress.setStyleSheet(spell_progress_stylesheet(self.spell))

        layout.addWidget(self.progress, 1)
        school = spell_school_name(self.spell)
        item_source = str(getattr(self.spell, 'source_item', '') or '')
        source_text = f'Item click · {item_source} · ' if item_source else ''
        self.progress.setToolTip(
            f'{source_text}{school} · visual progress of the spell time remaining')
        self.setToolTip(
            f'{source_text}{school} · double-click to remove · '
            'right-click to customize the fading sound')
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._sound_menu)

    def recast(self, timestamp):
        self._calculate(timestamp)
        self.progress.setStyleSheet(spell_progress_stylesheet(self.spell))
        self._active = True
        self._faded = False
        self._faded_until = 0.0
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
            f'{source_text}{school} · double-click to remove · '
            'right-click to customize the fading sound')
        self._request_resort()

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

    def resume(self):
        if self._faded:
            return
        self._active = True
        self._request_resort()

    def mark_faded(self, timestamp=None):
        """Keep an early worn-off effect visible as a red blinking FADED row."""
        if self._removed or self._faded:
            return
        self._faded = True
        self._active = False
        self._faded_until = time.monotonic() + 6.0
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
        if not self._warning_played:
            self._warning_played = True
            self._play_fade_alert()
        self._request_resort()
        self._update()

    def elongate(self, seconds):
        self.end_time += datetime.timedelta(seconds=seconds)
        self._request_resort()

    def _request_resort(self):
        target = self.parentWidget()
        if target and hasattr(target, '_sort_spell_widgets'):
            target._sort_spell_widgets()

    def _remove(self):
        if self._removed:
            return
        self._removed = True
        self.setParent(None)
        self.deleteLater()

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
            server=self.runtime_server)

    def _sound_menu(self, position):
        settings = config.data['spells']
        key = self.spell.name
        menu = QMenu(self)
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
        action = menu.exec(self.mapToGlobal(position))
        if action in gallery_actions:
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

    def mouseDoubleClickEvent(self, _):
        self._remove()


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
_SPELL_SCHOOL_PROGRESS_PALETTES = {
    4: ('#4D83A8', '#2A628F', '#123753', '#355E7D'),   # Abjuration
    5: ('#4C956B', '#28734E', '#123D2B', '#315F4B'),   # Alteration
    14: ('#76559A', '#5D3B84', '#2E1C48', '#574177'),  # Conjuration
    18: ('#9A7834', '#7B5B1F', '#45310F', '#665936'),  # Divination
    24: ('#A8543D', '#873725', '#4E2018', '#6F4034'),  # Evocation
}
_DETRIMENTAL_PROGRESS_PALETTES = {
    1: ('#76559A', '#5D3B84', '#2E1C48', '#503762'),  # magic
    2: ('#A85A2D', '#873D1D', '#4B2414', '#62402A'),  # fire
    3: ('#397F99', '#28667F', '#143C4C', '#345362'),  # cold
    4: ('#56823E', '#3D692C', '#263F1C', '#475B35'),  # poison
    5: ('#9A465E', '#7C3048', '#481D2B', '#613441'),  # disease
}
_DEFAULT_DETRIMENTAL_PALETTE = (
    '#A64D3E', '#85362D', '#4B211D', '#60372F')


def spell_school_name(spell):
    """Return the EQ casting skill represented by the client spell record."""
    skill = int(getattr(spell, 'skill', 0) or 0)
    return SPELL_SCHOOLS.get(skill, 'Other casting skill')


def spell_progress_palette(spell):
    """Return a stable glass palette keyed to the spell's casting school."""
    skill = int(getattr(spell, 'skill', 0) or 0)
    if skill in _SPELL_SCHOOL_PROGRESS_PALETTES:
        return _SPELL_SCHOOL_PROGRESS_PALETTES[skill]
    if not int(getattr(spell, 'type', 0)):
        return _DETRIMENTAL_PROGRESS_PALETTES.get(
            int(getattr(spell, 'resist_type', 0)),
            _DEFAULT_DETRIMENTAL_PALETTE)
    identity = (
        f"{getattr(spell, 'name', '')}|{getattr(spell, 'spell_icon', 0)}"
        .encode('utf-8', errors='replace'))
    index = int.from_bytes(
        hashlib.blake2s(identity, digest_size=2).digest(), 'big')
    fallback_palettes = tuple(_SPELL_SCHOOL_PROGRESS_PALETTES.values())
    return fallback_palettes[index % len(fallback_palettes)]


def spell_progress_stylesheet(spell):
    """A compact dark-glass bar with readable school colour and soft edges."""
    highlight, body, depth, border = spell_progress_palette(spell)
    return f"""
        QProgressBar {{
            min-height: 24px;
            max-height: 24px;
            border: 1px solid {border};
            border-radius: 6px;
            padding: 0px;
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #222930, stop:0.42 #12171C, stop:1 #080A0D);
        }}
        QProgressBar::chunk {{
            border-radius: 5px;
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 {highlight}, stop:0.12 {highlight},
                stop:0.22 {body}, stop:0.70 {body}, stop:1 {depth});
        }}
        QProgressBar[Warning="true"] {{
            border-color: #E7B85D;
        }}
        QProgressBar[Warning="true"]::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFF0A0, stop:0.18 #E6B84E,
                stop:0.72 #A96818, stop:1 #53310F);
        }}
        QProgressBar[Warning="true"][Pulse="true"]::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFFBE1, stop:0.16 #FFD867,
                stop:0.66 #E49324, stop:1 #7A470F);
        }}
        QProgressBar[Critical="true"] {{
            border-color: #E35B5B;
        }}
        QProgressBar[Critical="true"]::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFB0A8, stop:0.18 #F05A52,
                stop:0.72 #B5262E, stop:1 #5B1218);
        }}
        QProgressBar[Critical="true"][Pulse="true"]::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFF3EF, stop:0.16 #FF8178,
                stop:0.66 #E02F38, stop:1 #7B111B);
        }}
        QProgressBar[Faded="true"] {{
            border-color: #B54149;
        }}
        QProgressBar[Faded="true"]::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #F07A72, stop:0.20 #C93640,
                stop:0.74 #7D1D29, stop:1 #3E0D14);
        }}
        QProgressBar[Faded="true"][Pulse="true"]::chunk {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 #FFF0EC, stop:0.18 #FF6F67,
                stop:0.68 #D51F2F, stop:1 #6D0B15);
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
        self.class_levels = ()
        self.item_only = False
        self.source_item = ''
        self.__dict__.update(kwargs)


class SpellTrigger(QObject):

    spell_triggered = Signal()

    def __init__(self, **kwargs):
        super().__init__()
        self.timestamp = None  # datetime
        self.spell = None  # Spell
        self.__dict__.update(kwargs)

        self.targets = []  # [(timestamp, target)]
        self.activated = False

        # create casting trigger window
        self._times_up_timer = QTimer()
        self._times_up_timer.setSingleShot(True)
        self._times_up_timer.timeout.connect(self._times_up)
        self._activate_timer = QTimer()
        self._activate_timer.setSingleShot(True)
        self._activate_timer.timeout.connect(self._activate)

        if config.data['spells']['use_casting_window']:
            #  just in case user set casting window buffer super low, create offset for more accuracy.
            msec_offset = (datetime.datetime.now() -
                           self.timestamp).total_seconds() * 1000
            self._times_up_timer.start(
                int(self.spell.cast_time + config.data['spells']['casting_window_buffer'] - msec_offset))
            self._activate_timer.start(
                int(self.spell.cast_time - config.data['spells']['casting_window_buffer'] - msec_offset))
        else:
            self.activated = True

    def parse(self, timestamp, text):
        if self.activated:
            if self.spell.effect_text_you and text[:len(self.spell.effect_text_you)] == self.spell.effect_text_you:
                # cast self
                self.targets.append((timestamp, '__you__'))
            elif text[len(text) - len(self.spell.effect_text_other):] == self.spell.effect_text_other and \
                    len(self.spell.effect_text_other) > 0:
                # cast other
                target = text[:len(text) -
                              len(self.spell.effect_text_other)].strip()
                self.targets.append((timestamp, target))
            if self.targets and self.spell.max_targets == 1:
                self.stop()  # make sure you don't get two triggers
                self.spell_triggered.emit()

    def mark_item_cast(self, item_name):
        """Trust a player-owned item glow and widen the item's landing window."""
        if not getattr(self.spell, 'source_item', ''):
            self.spell = copy.copy(self.spell)
        self.spell.source_item = str(item_name or 'Item click')
        self.stop()
        self.activated = True
        self._times_up_timer.start(round(ITEM_CLICK_WINDOW_SECONDS * 1000))

    def _times_up(self):
        self.spell_triggered.emit()

    def _activate(self):
        self.activated = True

    def stop(self):
        self._times_up_timer.stop()
        self._activate_timer.stop()


def create_spell_book():
    """ Returns a dictionary of Spell by k, v -> spell_name, Spell() """
    spell_book = {}
    text_lookup_self = {}
    text_lookup_other = {}
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
                class_levels=tuple(
                    int(values[index]) for index in range(104, 120)),
                item_only=all(
                    int(values[index]) == 255
                    for index in range(104, 120))
            )
            spell_book[values[1]] = spell
            text_lookup_self[spell.effect_text_you] = spell
            text_lookup_other[spell.effect_text_other] = spell
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
