"""Map parser for Vantage."""
import json
import re
import string

from PySide6.QtCore import Signal, QObject, Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from vantage.helpers.parser import ParserWindow
from vantage.helpers import config, to_real_xy
from vantage.helpers.icons import game_icon
from vantage.helpers.respawn_catalog import named_spawn_for
from vantage.helpers.responsive import ResponsiveActionBar
from vantage.parsers.maps.mapcanvas import MapCanvas
from vantage.parsers.maps.mapclasses import MapPoint
from vantage.parsers.maps.mapdata import MapData

ZONE_PATTERNS = (
    ("zoning", re.compile(
        r"^You\s+have\s+entered\s+(?P<zone>.+?)[.!]?\s*$",
        re.IGNORECASE)),
    ("who", re.compile(
        r"^There\s+(?:is|are)\s+(?:no|\d+)\s+players?\s+in\s+"
        r"(?P<zone>.+?)[.!]?\s*$", re.IGNORECASE)),
    ("who", re.compile(
        r"^(?:Players|Characters)\s+(?:in|on)\s+(?P<zone>.+?)\s*[:.]?\s*$",
        re.IGNORECASE)),
    ("status", re.compile(
        r"^(?:You\s+are\s+(?:currently\s+)?in|Current\s+(?:zone|region)"
        r"(?:\s+is)?|Zone)\s*[:\-]?\s*(?P<zone>.+?)[.!]?\s*$",
        re.IGNORECASE)),
)

LOCATION_PATTERN = re.compile(
    r'^Your\s+Location\s+is\s+'
    r'(?P<first>[+-]?\d+(?:\.\d+)?)\s*,\s*'
    r'(?P<second>[+-]?\d+(?:\.\d+)?)\s*,\s*'
    r'(?P<third>[+-]?\d+(?:\.\d+)?)\s*$',
    re.IGNORECASE)

WHO_COUNT_PATTERN = re.compile(
    r'^There\s+(?:is|are)\s+(?P<count>no|\d+)\s+players?\s+in\s+',
    re.IGNORECASE)


def _poi_key(value):
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def _announce(widget, message):
    if not QApplication.instance() or not message:
        return
    event = QAccessibleAnnouncementEvent(widget, str(message))
    event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
    QAccessible.updateAccessibility(event)


class MapLootDialog(QDialog):
    """Native, cached loot list for one map label."""

    def __init__(self, point, mob, zone, open_item, open_zones, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Loot · {point.label}")
        self.setMinimumSize(330, 230)
        self.setMaximumWidth(520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.item_buttons = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        title = QLabel(point.label)
        title.setObjectName("SettingsHeader")
        title.setAccessibleDescription(
            f"Map point loot details for {point.label}")
        layout.addWidget(title)
        location = QLabel(
            f"{zone} · map {point.location.x:g}, {point.location.y:g}, "
            f"Z {point.location.z:g}")
        location.setObjectName("InlineStatus")
        location.setWordWrap(True)
        layout.addWidget(location)

        drops = [str(value).strip() for value in (mob or {}).get("drops", ())
                 if str(value).strip()][:100]
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Map loot status")
        layout.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setAccessibleName(f"Known loot from {point.label}")
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        if drops:
            self.status.setText(
                f"{len(drops)} cached drop{'s' if len(drops) != 1 else ''} · "
                "choose an item for its full Vantage card")
            for item_name in drops:
                button = QPushButton(item_name)
                button.setObjectName("MapLootItemLink")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setAccessibleName(f"Open item {item_name}")
                button.setAccessibleDescription(
                    "Open the full native Vantage item card")
                button.setToolTip(
                    f"Open {item_name} stats, effects, drops, and quests")
                button.clicked.connect(
                    lambda _checked=False, name=item_name: open_item(name))
                body_layout.addWidget(button)
                self.item_buttons.append(button)
        else:
            self.status.setText(
                "No cached loot is available for this named map point yet. "
                "Load this zone in Zones to refresh its P99 data.")
            zones_button = QPushButton("Open Zones")
            zones_button.setAccessibleName(
                f"Open Zones for {point.label} loot data")
            zones_button.setToolTip(
                "Open the current zone browser to load named and loot data")
            zones_button.clicked.connect(open_zones)
            body_layout.addWidget(zones_button)
            self.item_buttons.append(zones_button)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        self._close_button.setAccessibleDescription(
            "Close map loot details and return to the map point selector")
        QTimer.singleShot(0, self._focus_first_action)

    def _focus_first_action(self):
        target = self.item_buttons[0] if self.item_buttons else self._close_button
        target.setFocus(Qt.FocusReason.TabFocusReason)



def detect_log_zone(text):
    """Extract a validated bundled-map zone from a log message."""
    line = str(text or "").strip()
    for source, pattern in ZONE_PATTERNS:
        match = pattern.match(line)
        if match:
            zone = MapData.resolve_zone_name(match.group("zone"))
            if zone:
                return zone, source
    return None, None


def detect_log_location(text):
    """Return a safe three-value coordinate tuple from an EQ /loc line."""
    match = LOCATION_PATTERN.match(str(text or '').strip())
    if not match:
        return None
    return tuple(float(match.group(name)) for name in (
        'first', 'second', 'third'))


def detect_who_player_count(text):
    """Return the total reported by /who, including zero for 'no'."""
    match = WHO_COUNT_PATTERN.match(str(text or '').strip())
    if not match:
        return None
    value = match.group('count').lower()
    return 0 if value == 'no' else int(value)

class MapsSignals(QObject):
    zoning = Signal()
    new_zone = Signal(str)
    location = Signal(str, str)
    death = Signal(str, str)
    start_recording = Signal(str)
    rename_recording = Signal(str)
    stop_recording = Signal()

class Maps(ParserWindow):
    # MapCanvas is itself a QGraphicsView. Keep it native so its paths and
    # labels render once, at the correct resolution, without nested transforms.
    _native_surface = True

    def __init__(self):
        self.name = "maps"
        super().__init__()
        # interface
        self._map = MapCanvas()
        self._map.manual_pan.connect(self._manual_pan_started)
        self._map.poi_activated.connect(self._poi_label_activated)
        self.content.addWidget(self._map, 1)
        # buttons
        button_layout = ResponsiveActionBar(20, spacing=1)
        # Six compact actions always share one logical row.  The parent
        # window scales that row uniformly at every physical size.
        button_layout.setFixedWidth(125)
        show_poi = QPushButton()
        show_poi.setIcon(game_icon('poi'))
        show_poi.setCheckable(True)
        show_poi.setChecked(config.data['maps']['show_poi'])
        show_poi.setToolTip('Show points of interest')
        show_poi.clicked.connect(self._toggle_show_poi)
        self._show_poi_button = show_poi
        button_layout.addWidget(show_poi)
        auto_follow = QPushButton()
        auto_follow.setIcon(game_icon('follow'))
        auto_follow.setCheckable(True)
        auto_follow.setChecked(config.data['maps']['auto_follow'])
        auto_follow.setToolTip('Automatically center on the player')
        auto_follow.clicked.connect(self._toggle_auto_follow)
        self._auto_follow_button = auto_follow
        button_layout.addWidget(auto_follow)
        toggle_z_layers = QPushButton()
        toggle_z_layers.setIcon(game_icon('layers'))
        toggle_z_layers.setCheckable(True)
        toggle_z_layers.setChecked(config.data['maps']['use_z_layers'])
        toggle_z_layers.setToolTip('Show Z-height layers')
        toggle_z_layers.clicked.connect(self._toggle_z_layers)
        button_layout.addWidget(toggle_z_layers)
        show_grid_lines = QPushButton()
        show_grid_lines.setIcon(game_icon('grid'))
        show_grid_lines.setCheckable(True)
        show_grid_lines.setChecked(config.data['maps']['show_grid'])
        show_grid_lines.setToolTip('Show grid')
        show_grid_lines.clicked.connect(self._toggle_show_grid)
        button_layout.addWidget(show_grid_lines)
        show_mouse_location = QPushButton()
        show_mouse_location.setIcon(game_icon('cursor'))
        show_mouse_location.setCheckable(True)
        show_mouse_location.setChecked(config.data['maps']['show_mouse_location'])
        show_mouse_location.setToolTip('Show /loc under the pointer')
        show_mouse_location.clicked.connect(self._toggle_show_mouse_location)
        button_layout.addWidget(show_mouse_location)
        show_location_hud = QPushButton()
        show_location_hud.setIcon(game_icon('location'))
        show_location_hud.setCheckable(True)
        show_location_hud.setChecked(config.data['maps']['show_location_hud'])
        show_location_hud.setToolTip(
            'Show location HUD from EverQuest /loc and /who')
        show_location_hud.setAccessibleName('Show map location HUD')
        show_location_hud.setAccessibleDescription(
            'Displays the current zone, slash who player count, and last '
            'slash loc coordinates without blocking the map')
        show_location_hud.clicked.connect(self._toggle_location_hud)
        self._location_hud_button = show_location_hud
        button_layout.addWidget(show_location_hud)

        self._poi_button = QToolButton()
        self._poi_button.setIcon(game_icon('poi'))
        self._poi_button.setText('POI')
        self._poi_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._poi_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._poi_button.setAccessibleName('Choose map point of interest')
        self._poi_button.setAccessibleDescription(
            'Lists every label in the current map. Choose one to center it; '
            'diamond entries also open cached named loot details. This is the '
            'keyboard-accessible equivalent of clicking a map label.')
        self._poi_button.setToolTip(
            'Find any map label · ◆ entries have named or loot details')
        self._poi_menu = QMenu(self._poi_button)
        self._poi_menu.setAccessibleName('Current map points of interest')
        self._poi_menu.setToolTipsVisible(True)
        self._poi_button.setMenu(self._poi_menu)
        self._poi_actions = []
        self._loot_dialog = None

        self.menu_area.addWidget(self._poi_button)
        self.menu_area.addWidget(button_layout)

        if config.data['maps']['last_zone']:
            self._load_zone(config.data['maps']['last_zone'])
        else:
            self._load_zone('west freeport')

    def parse(self, timestamp, text):
        if text[:23] == 'LOADING, PLEASE WAIT...':
            QApplication.instance()._signals["maps"].zoning.emit()
            return

        detected_zone, source = detect_log_zone(text)
        if detected_zone:
            if source == 'zoning':
                self._map.clear_location_hud_position()
            current = self._map._data.zone.lower() if self._map._data else ""
            if detected_zone != current:
                self._load_zone(detected_zone)
            elif source == "zoning":
                QApplication.instance()._signals["maps"].new_zone.emit(
                    detected_zone)
            visible_name = string.capwords(detected_zone)
            self._map.update_location_hud_zone(
                visible_name, source, detect_who_player_count(text))
            return

        location = detect_log_location(text)
        if location is not None:
            QApplication.instance()._signals["maps"].location.emit(timestamp.isoformat(), text[17:])
            self._map.update_location_hud_position(location)
            x, y, z = location
            x, y = to_real_xy(x, y)
            self._map.add_player('__you__', timestamp, MapPoint(x=x, y=y, z=z))
            self._map.record_path_loc((x, y, z))
        elif text[:16] == "start_recording_":
            QApplication.instance()._signals["maps"].start_recording.emit(text.split()[0][16:])
            recording_name = text.split()[0][16:]
            if recording_name:
                recording_name = recording_name.replace('_', ' ')
                self._map.start_path_recording(recording_name)
        elif text[:17] == "rename_recording_":
            QApplication.instance()._signals["maps"].rename_recording.emit(text.split()[0][17:])
            recording_name = text.split()[0][17:]
            if recording_name:
                recording_name = recording_name.replace('_', ' ')
                self._map.rename_path_recording(new_name=recording_name)
        elif text[:14] == "stop_recording":
            QApplication.instance()._signals["maps"].stop_recording.emit()
            self._map.stop_path_recording()
        elif text[:19] == "You have been slain":
            QApplication.instance()._signals["maps"].death.emit(timestamp.isoformat(), text)

    def _load_zone(self, zone):
        canonical = MapData.resolve_zone_name(zone)
        if not canonical or not self._map.load_map(canonical):
            return False
        visible_name = string.capwords(self._map._data.zone)
        self._map.update_location_hud_zone(visible_name)
        self._title.setText(f"Map · {visible_name}")
        self._title.setToolTip(f"Zone detected from the log: {visible_name}")
        self.setWindowTitle(f"Vantage · Map · {visible_name}")
        self._refresh_poi_menu()
        QApplication.instance()._signals["maps"].new_zone.emit(canonical)
        return True

    def _zone_mobs(self):
        """Return existing Zones state/cache; never start a parallel request."""
        if not self._map._data:
            return []
        zone_name = self._map._data.zone
        app = QApplication.instance()
        zones = getattr(app, '_parsers_dict', {}).get('zones') if app else None
        if zones is not None:
            loaded_name = str(getattr(zones, '_zone_data', {}).get('name') or '')
            if (MapData.resolve_zone_name(loaded_name) ==
                    MapData.resolve_zone_name(zone_name)):
                loaded = list(getattr(zones, '_zone_mobs', ()) or ())
                if loaded:
                    return loaded
        try:
            from vantage.parsers.market import _wiki_zone_cache_path
            payload = json.loads(
                _wiki_zone_cache_path(zone_name).read_text(encoding='utf-8'))
            return list(payload.get('mobs') or ()) if isinstance(payload, dict) else []
        except (OSError, UnicodeError, ValueError, TypeError,
                json.JSONDecodeError):
            return []

    def _poi_detail(self, point, mobs=None):
        label_key = _poi_key(point.label)
        available_mobs = self._zone_mobs() if mobs is None else mobs
        mob = next((dict(row) for row in available_mobs
                    if _poi_key(row.get('name') or row.get('target')) == label_key), None)
        if mob is not None:
            target = str(mob.get('target') or mob.get('name') or '').strip()
            if target and not mob.get('drops'):
                try:
                    from vantage.parsers.market import _wiki_entity_cache_path
                    entity = json.loads(_wiki_entity_cache_path(
                        target, 'npc').read_text(encoding='utf-8'))
                    if isinstance(entity, dict) and entity.get('kind') == 'NPC':
                        mob.update({
                            key: entity[key] for key in
                            ('drops', 'quests', 'description', 'notes')
                            if entity.get(key)})
                except (OSError, UnicodeError, ValueError, TypeError,
                        json.JSONDecodeError):
                    pass
            if mob.get('named') or mob.get('drops'):
                return mob
        short_name = MapData.get_zone_dict().get(
            str(self._map._data.zone).strip().casefold(), '')
        catalog = named_spawn_for(short_name, point.label)
        if catalog is not None:
            return {'name': catalog.npc_name, 'named': True, 'drops': []}
        return None

    def _all_pois(self):
        if not self._map._data:
            return []
        return [point for z in self._map._data.keys()
                for point in self._map._data[z]['poi']]

    def _refresh_poi_menu(self):
        self._poi_menu.clear()
        self._poi_actions = []
        points = sorted(self._all_pois(), key=lambda point: (
            point.label.casefold(), point.location.z,
            point.location.x, point.location.y))
        if not points:
            empty = self._poi_menu.addAction('No map labels available')
            empty.setEnabled(False)
            self._poi_button.setEnabled(False)
            self._poi_button.setAccessibleDescription(
                'No points of interest are available in the current map.')
            return
        self._poi_button.setEnabled(True)
        self._poi_button.setAccessibleDescription(
            f'{len(points)} current map labels. Choose one to center it; '
            'diamond entries also open cached named loot details. This native '
            'menu is the keyboard-accessible map-label control.')
        mobs = self._zone_mobs()
        for point in points:
            detail = self._poi_detail(point, mobs)
            marker = '◆ ' if detail is not None else '• '
            action = self._poi_menu.addAction(
                f'{marker}{point.label} · {point.location.x:g}, '
                f'{point.location.y:g}')
            action.setToolTip(
                (f'{point.label} has named/loot details; center and open them'
                 if detail is not None else
                 f'Center the map on {point.label}'))
            action.triggered.connect(
                lambda _checked=False, selected=point:
                self._activate_poi(selected, open_details=True))
            self._poi_actions.append(action)

    def _activate_poi(self, point, *, open_details=False):
        if not self._map.focus_poi(point):
            return False
        if not config.data['maps']['show_poi']:
            config.data['maps']['show_poi'] = True
            config.save()
            self._show_poi_button.setChecked(True)
            self._map.update_()
            self._map.centerOn(point.location.x, point.location.y)
        self._manual_pan_started()
        self._poi_button.setText('POI')
        self._poi_button.setToolTip(
            f'Centered on {point.label} · choose another map label')
        _announce(self._poi_button, f'Map centered on {point.label}')
        detail = self._poi_detail(point)
        if open_details and detail is not None:
            self._open_poi_loot(point, detail)
        return True

    def _poi_label_activated(self, point):
        return self._activate_poi(point, open_details=True)

    def _open_poi_loot(self, point, detail):
        if self._loot_dialog is not None:
            try:
                self._loot_dialog.close()
            except RuntimeError:
                pass
        # A QMenu action can temporarily own QApplication focus while it
        # triggers. Return to a stable, visible control instead of that menu.
        return_focus = self._poi_button
        dialog = MapLootDialog(
            point, detail, string.capwords(self._map._data.zone),
            self._open_map_loot_item, self._open_current_zone_browser, self)
        self._loot_dialog = dialog

        def finished(_result, current=dialog, target=return_focus):
            if self._loot_dialog is current:
                self._loot_dialog = None
            QTimer.singleShot(
                0, lambda control=target: self._restore_poi_focus(control))

        dialog.finished.connect(finished)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def _restore_poi_focus(self, control):
        try:
            if control is None or not control.isVisibleTo(self._surface):
                control = self._poi_button
            self.raise_()
            self.activateWindow()
            self._surface.setFocusProxy(control)
            self._scale_scene.setActivePanel(self._scale_proxy)
            self._scale_scene.setFocusItem(
                self._scale_proxy, Qt.FocusReason.TabFocusReason)
            self._scale_proxy.setFocus(Qt.FocusReason.TabFocusReason)
            self._surface.setFocus(Qt.FocusReason.TabFocusReason)
            control.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        except RuntimeError:
            return False

    @staticmethod
    def _open_map_loot_item(name):
        app = QApplication.instance()
        market = getattr(app, '_parsers_dict', {}).get('market') if app else None
        return bool(market and market._show_wiki_item_name(name))

    def _open_current_zone_browser(self):
        app = QApplication.instance()
        zones = getattr(app, '_parsers_dict', {}).get('zones') if app else None
        if zones is None:
            return False
        zones._select_zone(self._map._data.zone)
        zones.show()
        zones.raise_()
        zones.activateWindow()
        zones.zone_selector.setFocus(Qt.FocusReason.TabFocusReason)
        return True

    def clear_player_location(self):
        """Remove the stale self marker after a confirmed camp/logout."""
        self._map.clear_location_hud_position()
        if not self._map._data or '__you__' not in self._map._data.players:
            return False
        self._map.remove_player('__you__')
        self._map.update_()
        return True

    # events
    def _toggle_show_poi(self, _):
        config.data['maps']['show_poi'] = not config.data['maps']['show_poi']
        config.save()
        self._map.update_()

    def _toggle_auto_follow(self, checked):
        config.data['maps']['auto_follow'] = bool(checked)
        config.save()
        self._auto_follow_button.setToolTip(
            'Automatically center on the player'
            if checked else
            'Tracking paused; enable it to recenter on the player')
        self._map.center()

    def _manual_pan_started(self):
        """Keep a manually dragged map where the user leaves it."""
        if config.data['maps']['auto_follow']:
            config.data['maps']['auto_follow'] = False
            config.save()
        self._auto_follow_button.setChecked(False)
        self._auto_follow_button.setToolTip(
            'Tracking paused after moving the map; enable it to recenter')

    def _toggle_z_layers(self, _):
        config.data['maps']['use_z_layers'] = not config.data['maps']['use_z_layers']
        config.save()
        self._map.update_()

    def _toggle_show_grid(self, _):
        config.data['maps']['show_grid'] = not config.data['maps']['show_grid']
        config.save()
        self._map.update_()

    def _toggle_show_mouse_location(self, _=False):
        config.data['maps']['show_mouse_location'] = not config.data['maps']['show_mouse_location']
        config.save()

    def _toggle_location_hud(self, checked):
        config.data['maps']['show_location_hud'] = bool(checked)
        config.save()
        self._map.set_location_hud_visible(checked)
