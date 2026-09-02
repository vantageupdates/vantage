import csv
import math
import pathlib
import re
from collections import Counter

from PySide6.QtGui import QColor, QPen, QPainterPath
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsItemGroup

from vantage.helpers import config, resource_path
from vantage.helpers.portable import data_dir
from vantage.helpers.respawn_catalog import respawn_for_short_name
from vantage.parsers.maps.mapclasses import MapPoint, MapGeometry, MapLine, PointOfInterest

MAP_KEY_FILE = resource_path('data/maps/map_keys.ini')
MAP_KEY_FILE_WHO = resource_path('data/maps/map_keys_who.ini')
MAP_SPAWNTIMES_FILE = resource_path('data/maps/map_timers.csv')
MAP_FILES_LOCATION = resource_path('data/maps/map_files')
MAP_FILES_PATHLIB = pathlib.Path(MAP_FILES_LOCATION)
MAP_RECORDINGS_PATHLIB = data_dir('recordings')
ICON_MAP = {'corpse': resource_path('data/maps/spawn.png')}


def bundled_map_paths(map_file_name):
    """Return only the zone geometry/labelling files for one exact short name."""
    base_name = str(map_file_name).casefold()
    pattern = '**/{zone}*.txt'.format(zone=map_file_name)
    paths = [
        map_path for map_path in MAP_FILES_PATHLIB.glob(pattern)
        if (map_path.stem.casefold() == base_name or
            re.fullmatch(
                rf"{re.escape(base_name)}_\d+",
                map_path.stem.casefold()))
    ]
    return [map_path for map_path in paths
            if not map_path.stem.casefold().endswith('_2')]


class MapData(dict):

    def __init__(self, zone=None):
        super().__init__()
        self.zone = zone
        self.raw = {'lines': [], 'poi': [], 'grid': []}
        self.geometry = None  # MapGeometry
        self.players = {}
        self.spawns = []
        self.waypoints = {}
        self.way_point = None
        self.grid = None

        if self.zone is not None:
            self._load()

    def _load(self):
        # Get list of all map files for current zone
        map_file_name = MapData.get_zone_dict()[self.zone.strip().lower()]
        pattern = '**/{zone}*.txt'.format(zone=map_file_name)
        # Brewall's ``*_2.txt`` companion is a reusable vector-font legend,
        # not zone geometry. Rendering it produces the wall of tiny glyphs
        # seen over the game and also distorts the map's fitting bounds.
        maps = bundled_map_paths(map_file_name) + \
            list(MAP_RECORDINGS_PATHLIB.glob(pattern))

        all_x, all_y, all_z = [], [], []

        # TODO: Remove the references to raw
        # Create Lines and Points
        for map_file in maps:
            print("Loading: %s" % map_file)
            with open(map_file, 'r') as f:
                for line in f.readlines():
                    line_type = line.lower()[0:1]
                    data = [value.strip() for value in line[1:].split(',')]
                    if line_type == 'l':  # line
                        x1, y1, z1, x2, y2, z2 = list(map(float, data[0:6]))
                        self.raw['lines'].append(MapLine(
                            x1=x1,
                            y1=y1,
                            z1=z1,
                            x2=x2,
                            y2=y2,
                            z2=z2,
                            color=self.color_transform(QColor(
                                int(data[6]),
                                int(data[7]),
                                int(data[8])
                            ))
                        ))
                        all_x.extend((x1, x2))
                        all_y.extend((y1, y2))
                        all_z.append(min(z1, z2))
                        # if abs(z1 - z2) < 2:
                        # if z1 == z2:
                        # all_z.extend((z1, z2))

                    elif line_type == 'p':  # point
                        x, y, z = map(float, data[0:3])
                        self.raw['poi'].append(MapPoint(
                            x=x,
                            y=y,
                            z=z,
                            size=int(data[6]),
                            text=str(data[7]),
                            color=self.color_transform(QColor(
                                int(data[3]),
                                int(data[4]),
                                int(data[5])
                            ))
                        ))

        # Create Grid Lines
        lowest_x, highest_x, lowest_y, highest_y, lowest_z, highest_z = min(all_x), max(all_x), min(all_y), max(
            all_y), min(all_z), max(all_z)

        left, right = int(math.floor(lowest_x / 1000) *
                          1000), int(math.ceil(highest_x / 1000) * 1000)
        top, bottom = int(math.floor(lowest_y / 1000) *
                          1000), int(math.ceil(highest_y / 1000) * 1000)

        for number in range(left, right + 1000, 1000):
            self.raw['grid'].append(MapLine(
                x1=number, x2=number, y1=top, y2=bottom, z1=0, z2=0, color=QColor(255, 255, 255, 25)))

        for number in range(top, bottom + 1000, 1000):
            self.raw['grid'].append(MapLine(
                y1=number, y2=number, x1=left, x2=right, z1=0, z2=0, color=QColor(255, 255, 255, 25)))

        self.grid = QGraphicsPathItem()
        line_path = QPainterPath()
        for line in self.raw['grid']:
            line_path.moveTo(line.x1, line.y1)
            line_path.lineTo(line.x2, line.y2)
        self.grid.setPath(line_path)
        self.grid.setPen(QPen(
            line.color,
            config.data['maps']['grid_line_width']
        ))
        self.grid.setZValue(0)

        # Get z levels
        counter = Counter(all_z)

        # bunch together zgroups based on peaks with floor being low point before rise
        z_groups = []
        last_value = None
        first_run = True
        for z in sorted(counter.items(), key=lambda x: x[0]):
            if last_value is None:
                last_value = z
                continue
            if (abs(last_value[0] - z[0]) < 20) or z[1] < 8:
                last_value = (last_value[0], last_value[1] + z[1])
            else:
                if first_run:
                    first_run = False
                    if last_value[1] < 40 or abs(last_value[0] - z[0]) < 18:
                        last_value = z
                        continue
                z_groups.append(last_value[0])
                last_value = z

        # get last iteration
        if last_value[1] > 50:
            z_groups.append(last_value[0])

        self._z_groups = z_groups

        # Create QGraphicsPathItem for lines seperately to retain colors
        temp_dict = {}
        for l in self.raw['lines']:
            lz = min(l.z1, l.z2)
            lz = self.get_closest_z_group(lz)
            if not temp_dict.get(lz, None):
                temp_dict[lz] = {'paths': {}}
            lc = l.color.getRgb()
            if not temp_dict[lz]['paths'].get(lc, None):
                path_item = QGraphicsPathItem()
                path_item.setPen(
                    QPen(l.color, config.data['maps']['line_width']))
                temp_dict[lz]['paths'][lc] = path_item
            path = temp_dict[lz]['paths'][lc].path()
            path.moveTo(l.x1, l.y1)
            path.lineTo(l.x2, l.y2)
            temp_dict[lz]['paths'][lc].setPath(path)

        # Group QGraphicsPathItems into QGraphicsItemGroups and update self
        for z in temp_dict:
            item_group = QGraphicsItemGroup()
            for (_, path) in temp_dict[z]['paths'].items():
                item_group.addToGroup(path)
            self[z] = {'paths': None, 'poi': []}
            self[z]['paths'] = item_group

        # Create Points of Interest
        for p in self.raw['poi']:
            z = self.get_closest_z_group(p.z)
            self[z]['poi'].append(
                PointOfInterest(location=p)
            )

        self.geometry = MapGeometry(
            lowest_x=lowest_x,
            highest_x=highest_x,
            lowest_y=lowest_y,
            highest_y=highest_y,
            lowest_z=lowest_z,
            highest_z=highest_z,
            center_x=int(highest_x - (highest_x - lowest_x) / 2),
            center_y=int(highest_y - (highest_y - lowest_y) / 2),
            width=int(highest_x - lowest_x),
            height=int(highest_y - lowest_y),
            z_groups=z_groups
        )

        # Load Spawn Timer Pairs from map_timers.csv
        with open(MAP_SPAWNTIMES_FILE, 'r') as file:
            reader = csv.reader(file)
            self.spawn_timer_dict = dict(reader)

    def get_closest_z_group(self, z):
        closest = min(self._z_groups, key=lambda x: abs(x - z))
        if z < closest:
            lower_index = self._z_groups.index(closest) - 1
            if lower_index > -1:
                closest = self._z_groups[lower_index]
        return closest

    @staticmethod
    def get_zone_dict():
        # Load Map Pairs from map_keys.ini
        zone_dict = {}
        with open(MAP_KEY_FILE, 'r') as file:
            for line in file.readlines():
                values = line.split('=')
                zone_dict[values[0].strip()] = values[1].strip()
        return zone_dict

    @staticmethod
    def translate_who_zone(zone_name):
        # Load the display-name aliases used by EverQuest's /who output.
        zone_dict = {}
        with open(MAP_KEY_FILE_WHO, 'r') as file:
            for line in file.readlines():
                values = line.split('=')
                zone_dict[values[0].strip()] = values[1].strip()
        return zone_dict.get(zone_name.strip().lower(), zone_name)

    @staticmethod
    def resolve_zone_name(zone_name):
        """Return the canonical map name for a human or short zone name.

        EverQuest uses slightly different names in zoning messages, /who
        summaries and map filenames.  Only names backed by a bundled map are
        returned so an unrelated chat line can never replace the active map.
        """
        candidate = str(zone_name or "").strip()
        candidate = candidate.replace("’", "'")
        candidate = re.sub(r"\s+", " ", candidate)
        candidate = candidate.rstrip(" .:;!?").strip().lower()
        if not candidate or candidate == "everquest":
            return None

        candidate = MapData.translate_who_zone(candidate).strip().lower()
        zone_dict = MapData.get_zone_dict()
        if candidate in zone_dict:
            return candidate

        # Accept internal zone short names as well as the visible names.
        for display_name, short_name in zone_dict.items():
            if candidate == short_name.lower():
                return display_name

        # Some log sources omit the leading article used by the map index.
        with_article = f"the {candidate}"
        if with_article in zone_dict:
            return with_article
        if candidate.startswith("the ") and candidate[4:] in zone_dict:
            return candidate[4:]
        return None

    def get_default_spawn_timer(self):
        short_zone = MapData.get_zone_dict().get(
            str(self.zone or '').strip().lower())
        catalog_entry = respawn_for_short_name(short_zone)
        if catalog_entry and catalog_entry.seconds is not None:
            return catalog_entry.timer_text
        return self.spawn_timer_dict.get(short_zone, '6:40')

    @staticmethod
    def color_transform(color):
        lightness = color.lightness()
        if lightness == 0:
            return QColor(255, 255, 255)
        if color.red == color.green == color.blue:
            return QColor(255, 255, 255)
        if lightness < 150:
            return color.lighter(150)
        return color
