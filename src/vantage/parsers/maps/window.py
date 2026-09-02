"""Map parser for Vantage."""
import re
import string

from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QPushButton, QApplication

from vantage.helpers.parser import ParserWindow
from vantage.helpers import config, to_real_xy
from vantage.helpers.icons import game_icon
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
        self.content.addWidget(self._map, 1)
        # buttons
        button_layout = ResponsiveActionBar(20, spacing=1)
        # Five compact actions always share one logical row.  The parent
        # window scales that row uniformly at every physical size.
        button_layout.setFixedWidth(104)
        show_poi = QPushButton()
        show_poi.setIcon(game_icon('poi'))
        show_poi.setCheckable(True)
        show_poi.setChecked(config.data['maps']['show_poi'])
        show_poi.setToolTip('Show points of interest')
        show_poi.clicked.connect(self._toggle_show_poi)
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
            current = self._map._data.zone.lower() if self._map._data else ""
            if detected_zone != current:
                self._load_zone(detected_zone)
            elif source == "zoning":
                QApplication.instance()._signals["maps"].new_zone.emit(
                    detected_zone)
            return

        if text[:16] == 'Your Location is':
            QApplication.instance()._signals["maps"].location.emit(timestamp.isoformat(), text[17:])
            x, y, z = [float(value) for value in text[17:].strip().split(',')]
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
        self._title.setText(f"Map · {visible_name}")
        self._title.setToolTip(f"Zone detected from the log: {visible_name}")
        self.setWindowTitle(f"Vantage · Map · {visible_name}")
        QApplication.instance()._signals["maps"].new_zone.emit(canonical)
        return True

    def clear_player_location(self):
        """Remove the stale self marker after a confirmed camp/logout."""
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
