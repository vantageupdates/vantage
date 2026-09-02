# testing
import traceback

import os

import pathvalidate
from PySide6.QtCore import Qt, QPoint, Signal, QTimer
from PySide6.QtGui import QPainter, QTransform, QColor, QPen, QAction
from PySide6.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView,
                             QInputDialog, QMenu, QLineEdit,
                             QGraphicsPathItem)

from vantage.helpers import config, resource_path, to_range, text_time_to_seconds
from vantage.parsers.maps.mapclasses import (MapPoint, WayPoint, Player, SpawnPoint, MouseLocation,
                         PointOfInterest, UserWaypoint)
from vantage.parsers.maps.mapdata import MapData, MAP_RECORDINGS_PATHLIB, ICON_MAP


class MapCanvas(QGraphicsView):
    """Map Widget for Everquest Map Files."""

    manual_pan = Signal()

    def __init__(self):

        self._data = None
        # UI Init
        super().__init__()
        self.setObjectName('MapCanvas')
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContentsMargins(0, 0, 0, 0)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(
            'Drag with the left button to pan · wheel to zoom · '
            'Ctrl+wheel to change the Z layer')
        self._scene = QGraphicsScene()
        self.setScene(self._scene)
        self._scale = config.data['maps']['scale']
        self._mouse_location = MouseLocation()
        self._path_recording = False
        self._path_recording_name = ""
        self._path_file = None
        self._path_last_loc = None
        self._pan_press_pos = QPoint()
        self._pan_announced = False
        self._manual_view = False

    def load_map(self, map_name, keep_loc=False):
        old_player_data = None
        try:
            try:
                old_player_data = self._data.players['__you__']
            except:
                pass  # no old location for player
            map_data = MapData(str(map_name))

        except:
            traceback.print_exc()
            return False

        else:
            self._data = map_data
            self._manual_view = False
            self._scene.clear()
            self._z_index = 0
            self._draw()
            rect = self._scene.sceneRect()
            rect.adjust(-self._data.geometry.width * 2, -self._data.geometry.height * 2,
                        self._data.geometry.width * 2, self._data.geometry.height * 2)
            self.setSceneRect(rect)
            self.update()
            self.update_()

            QTimer.singleShot(0, self.fit_overview)
            self._mouse_location = MouseLocation()
            self._scene.addItem(self._mouse_location)
            config.data['maps']['last_zone'] = self._data.zone
            config.save()
            if keep_loc and old_player_data:
                self.add_player(
                    '__you__', old_player_data.timestamp,
                    old_player_data.location)
            return True

    def _draw(self):
        for z in self._data.keys():
            self._scene.addItem(self._data[z]['paths'])
            for p in self._data[z]['poi']:
                self._scene.addItem(p.text)

        self._scene.addItem(self._data.grid)

    def update_(self, ratio=None):
        if not ratio:
            ratio = self._scale

        current_alpha = config.data['maps']['current_z_alpha'] / 100
        other_alpha = config.data['maps']['other_z_alpha'] / 100
        closest_alpha = config.data['maps']['closest_z_alpha'] / 100

        # scene
        self.setTransform(QTransform())  # reset transform object
        self._scale = to_range(ratio, 0.0006, 5.0)
        config.data['maps']['scale'] = self._scale
        self.scale(self._scale, self._scale)

        # lines and points of interest
        current_z_level = self._data.geometry.z_groups[self._z_index]
        closest_z_levels = set()
        for x in [i for i in [self._z_index - 1, self._z_index + 1] if i > -1]:
            try:
                closest_z_levels.add(self._data.geometry.z_groups[x])
            except:
                pass

        for z in self._data.keys():
            alpha = current_alpha
            if config.data['maps']['use_z_layers']:
                if z == current_z_level:
                    alpha = current_alpha
                elif z in closest_z_levels:
                    alpha = closest_alpha
                else:
                    alpha = other_alpha
            # lines
            bolded = 0.5 if config.data['maps']['use_z_layers'] else 0.0
            for path in self._data[z]['paths'].childItems():
                if z == current_z_level or not config.data['maps']['use_z_layers']:
                    pen = path.pen()
                    pen.setWidth(int(max(
                        config.data['maps']['line_width'] + bolded,
                        (config.data['maps']['line_width'] +
                         bolded) / self._scale
                    )))
                    path.setPen(pen)
                else:
                    pen = path.pen()
                    pen.setWidth(int(max(
                        config.data['maps']['line_width'] - 0.8,
                        (config.data['maps']['line_width'] - 0.8) / self._scale
                    )))
                    path.setPen(pen)

            self._data[z]['paths'].setOpacity(alpha)

            # points of interest
            for p in self._data[z]['poi']:
                p.update_(min(5, self.to_scale()))
                # Full-zone overviews become unreadable when every classic
                # map label is painted at once. Reveal labels as the user
                # zooms in; never prefix them with decorative glyphs.
                labels_visible = (
                    config.data['maps']['show_poi'] and
                    self._manual_view and
                    self._scale >= 0.18)
                if not labels_visible:
                    p.text.setOpacity(0)
                elif config.data['maps']['use_z_layers']:
                    if z == current_z_level:
                        p.text.setOpacity(current_alpha)
                    else:
                        p.text.setOpacity(other_alpha)
                else:
                    p.text.setOpacity(current_alpha)

        # players
        for player in self._data.players.values():
            player.update_(self.to_scale())
            if config.data['maps']['use_z_layers']:
                if player.z_level == current_z_level:
                    player.setOpacity(current_alpha)
                else:
                    player.setOpacity(other_alpha)
            else:
                player.setOpacity(current_alpha)

        # waypoint
        if self._data.way_point:
            self._data.way_point.update_(self.to_scale())
            if config.data['maps']['use_z_layers']:
                self._data.way_point.pixmap.setOpacity(
                    current_alpha if (self._data.way_point.location.z ==
                                      current_z_level) else other_alpha
                )
                player = self._data.players.get('__you__', None)
                if player and current_z_level in \
                        [self._data.way_point.location.z, player.z_level]:
                    self._data.way_point.line.setOpacity(current_alpha)
                else:
                    self._data.way_point.line.setOpacity(other_alpha)

            else:
                self._data.way_point.pixmap.setOpacity(current_alpha)

        # user waypoints
        for waypoint in self._data.waypoints.values():
            waypoint.update_(self.to_scale())
            if config.data['maps']['use_z_layers']:
                if waypoint.z_level == current_z_level:
                    waypoint.setOpacity(current_alpha)
                else:
                    waypoint.setOpacity(other_alpha)
            else:
                waypoint.setOpacity(current_alpha)

        # spawns
        for spawn in self._data.spawns:
            spawn.setScale(self.to_scale())
            spawn.realign(self.to_scale())
            if config.data['maps']['use_z_layers']:
                spawn.setOpacity(
                    current_alpha if (spawn.location.z ==
                                      current_z_level) else other_alpha
                )
            else:
                spawn.setOpacity(current_alpha)

        # grid lines
        if config.data['maps']['show_grid']:
            pen = self._data.grid.pen()
            pen.setWidth(int(max(
                config.data['maps']['grid_line_width'],
                self.to_scale(config.data['maps']['grid_line_width'])
            )))
            self._data.grid.setPen(pen)
            self._data.grid.setVisible(True)
        else:
            self._data.grid.setVisible(False)

    def to_scale(self, float_value=1.0):
        return float_value / self._scale

    def center(self):
        player = None
        if self._data:
            player = self._data.players.get('__you__', None)
        if config.data['maps']['auto_follow'] and player:
            self.centerOn(
                player.location.x,
                player.location.y
            )

    def fit_overview(self):
        """Fit the current zone cleanly inside the native map viewport."""
        if not self._data or self.viewport().width() < 40 \
                or self.viewport().height() < 40:
            return
        geometry = self._data.geometry
        available_width = max(1, self.viewport().width() - 24)
        available_height = max(1, self.viewport().height() - 24)
        ratio = min(
            available_width / max(1, geometry.width),
            available_height / max(1, geometry.height))
        self._manual_view = False
        self.update_(ratio)
        self.centerOn(geometry.center_x, geometry.center_y)

    def remove_player(self, name):
        player = self._data.players.pop(name)
        if player:
            self._scene.removeItem(player)

    def add_player(self, name, timestamp, location):
        if name not in self._data.players:
            self._data.players[name] = Player(
                name=name,
                location=location,
                timestamp=timestamp)
            self._scene.addItem(self._data.players[name])
        else:
            self._data.players[name].previous_location = self._data.players[name].location
            self._data.players[name].location = location
            self._data.players[name].timestamp = timestamp
        self._data.players[name].z_level = self._data.get_closest_z_group(
            self._data.players[name].location.z
        )

        if name == '__you__' and config.data['maps']['use_z_layers']:
            self._z_index = self._data.geometry.z_groups.index(
                self._data.get_closest_z_group(
                    self._data.players['__you__'].location.z
                ))

        self.update_()

        if self._data.way_point and name == '__you__':
            self._data.way_point.update_(
                self.to_scale(),
                location=location
            )

        if name == '__you__' and config.data['maps']['auto_follow']:
            self.center()

    def remove_waypoint(self, name):
        waypoint = self._data.waypoints.pop(name)
        if waypoint:
            self._scene.removeItem(waypoint)

    def add_waypoint(self, name, location, icon):
        if name not in self._data.waypoints:
            self._data.waypoints[name] = UserWaypoint(
                name=name.rsplit(":", 1)[0],
                icon=ICON_MAP.get(icon, resource_path('data/maps/waypoint.png')),
                location=location
            )
            self._scene.addItem(self._data.waypoints[name])

        self._data.waypoints[name].z_level = self._data.get_closest_z_group(
            self._data.waypoints[name].location.z
        )

        self.update_()

    def enterEvent(self, event):
        if config.data['maps']['show_mouse_location']:
            self._mouse_location.setVisible(True)
        QGraphicsView.enterEvent(self, event)

    def leaveEvent(self, event):
        self._mouse_location.setVisible(False)
        QGraphicsView.leaveEvent(self, event)

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton
                and not self._pan_announced
                and (event.pos() - self._pan_press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._pan_announced = True
            self._manual_view = True
            self.manual_pan.emit()
        self._mouse_location.set_value(
            self.mapToScene(event.pos()),
            self._scale,
            self
            )
        QGraphicsView.mouseMoveEvent(self, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_press_pos = event.pos()
            self._pan_announced = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        QGraphicsView.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        QGraphicsView.mouseReleaseEvent(self, event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event):
        # Scale based on scroll wheel direction
        self._manual_view = True
        movement = event.angleDelta().y()
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if movement > 0:
                self.update_(self._scale + self._scale * 0.1)
            else:
                self.update_(self._scale - self._scale * 0.1)
        else:
            if self._data:
                if movement > 0:
                    self._z_index = max(self._z_index - 1, 0)
                else:
                    self._z_index = min(
                        self._z_index + 1, len(self._data.geometry.z_groups) - 1)
                self.update_()

        # Update Mouse Location
        mouse_pos = int(event.position().x()), int(event.position().y())
        self._mouse_location.set_value(
            self.mapToScene(*mouse_pos),
            self._scale,
            self
        )

    def resizeEvent(self, event):
        QGraphicsView.resizeEvent(self, event)
        if self._data:
            player = self._data.players.get('__you__')
            if config.data['maps']['auto_follow'] and player:
                self.center()
            elif not self._manual_view:
                QTimer.singleShot(0, self.fit_overview)

    def contextMenuEvent(self, event):
        # create menu
        pos = self.mapToScene(event.pos())
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        # remove from memory after usage
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # remove from memory
        spawn_point_menu = menu.addMenu('Map Timer')
        spawn_point_menu.setToolTipsVisible(True)
        spawn_point_create = spawn_point_menu.addAction('Create at cursor')
        spawn_point_create.setToolTip(
            'Create a draggable countdown at this exact map location')
        spawn_point_delete = spawn_point_menu.addAction('Delete at cursor')
        spawn_point_delete.setToolTip(
            'Delete the map timer directly under the cursor')
        spawn_point_delete_all = spawn_point_menu.addAction('Delete all')
        spawn_point_delete_all.setToolTip(
            'Delete every temporary timer on this map')
        way_point_menu = menu.addMenu('Way Point')
        way_point_create = way_point_menu.addAction('Create on Cursor')
        way_point_delete = way_point_menu.addAction('Clear')
        pathing_menu = menu.addMenu('Custom Pathing')
        pathing_start_recording = QAction('Start Recording')
        pathing_rename_recording = QAction('Rename Path')
        pathing_stop_recording = QAction('Stop Recording')
        if not self._path_recording:
            pathing_menu.addAction(pathing_start_recording)
        else:
            current = pathing_menu.addAction(self._path_recording_name)
            current.setEnabled(False)
            pathing_menu.addSeparator()
            pathing_menu.addAction(pathing_rename_recording)
            pathing_menu.addAction(pathing_stop_recording)
        load_map = menu.addAction('Load Map')
        fit_map = menu.addAction('Fit Entire Map (Home)')

        # execute
        action = menu.exec(self.mapToGlobal(event.pos()))

        # parse response

        if action == spawn_point_create:
            dialog = QInputDialog(self)
            dialog.setWindowTitle('Create Spawn Point')
            dialog.setLabelText('Respawn Time (hh:mm:ss):')
            dialog.setTextValue(self._data.get_default_spawn_timer())

            if dialog.exec():
                spawn_time = text_time_to_seconds(dialog.textValue())
                spawn = SpawnPoint(
                    location=MapPoint(
                        x=pos.x(),
                        y=pos.y(),
                        z=self._data.geometry.z_groups[self._z_index]
                    ),
                    length=spawn_time,
                    on_remove=self._remove_spawn,
                    name='spawn timer',
                )

                self._scene.addItem(spawn)
                self._data.spawns.append(spawn)
                spawn.start()
            dialog.deleteLater()

        if action == spawn_point_delete:
            selected = self._scene.itemAt(
                pos.x(), pos.y(), QTransform())
            if selected:
                group = (
                    selected if isinstance(selected, SpawnPoint)
                    else selected.parentItem())
                if isinstance(group, SpawnPoint):
                    self._remove_spawn(group)

        if action == spawn_point_delete_all:
            for spawn in list(self._data.spawns):
                self._remove_spawn(spawn)

        if action == way_point_create:
            if self._data.way_point:
                self._scene.removeItem(self._data.way_point.pixmap)
                self._scene.removeItem(self._data.way_point.line)
                self._data.way_point = None

            self._data.way_point = WayPoint(
                location=MapPoint(
                    x=pos.x(),
                    y=pos.y(),
                    z=self._data.geometry.z_groups[self._z_index]
                )
            )

            self._scene.addItem(self._data.way_point.pixmap)
            self._scene.addItem(self._data.way_point.line)

        if action == way_point_delete:
            if self._data.way_point:
                self._scene.removeItem(self._data.way_point.pixmap)
                self._scene.removeItem(self._data.way_point.line)
            self._data.way_point = None

        if action == pathing_start_recording:
            self.start_path_recording()

        if action == pathing_rename_recording:
            self.rename_path_recording()

        if action == pathing_stop_recording:
            self.stop_path_recording()

        if action == load_map:
            dialog = QInputDialog(self)
            dialog.setWindowTitle('Load Map')
            dialog.setLabelText('Select map to load:')
            dialog.setComboBoxItems(
                sorted([map.title() for map in MapData.get_zone_dict()]))
            if dialog.exec():
                self.load_map(dialog.textValue().lower())
            dialog.deleteLater()

        if action == fit_map:
            self.fit_overview()

    def _remove_spawn(self, spawn):
        if not self._data:
            return
        if spawn in self._data.spawns:
            self._data.spawns.remove(spawn)
        if spawn.scene() is self._scene:
            self._scene.removeItem(spawn)

        self.update_()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Home:
            self.fit_overview()
            event.accept()
            return
        QGraphicsView.keyPressEvent(self, event)

    def _get_path_filename(self, custom_name=None, relative=False):
        custom_name = custom_name or self._path_recording_name
        clean_name = pathvalidate.sanitize_filename(custom_name)
        clean_name = clean_name.replace(' ', '_')
        if relative:
            return clean_name
        zone_key = MapData.get_zone_dict().get(self._data.zone.strip().lower())
        filename = "{zone}_{recording}.txt".format(
            zone=zone_key,
            recording=clean_name)

        # Make sure the directory exists
        record_dir = MAP_RECORDINGS_PATHLIB
        if not os.path.exists(record_dir):
            try:
                print("Creating custom map directory.")
                os.makedirs(record_dir)
            except Exception as e:
                print("Failed to make custom map directory: %s" % e)
        return record_dir.joinpath(filename)

    def start_path_recording(self, name=None):
        print("Start recording!")
        if self._path_recording:
            return

        if name:
            path_name = name
            ok_pressed = True
        else:
            path_name, ok_pressed = QInputDialog.getText(
                self,  # parent
                "Start Recording Path",  # title
                "Name of path to record:",  # label
                echo=QLineEdit.EchoMode.Normal,
                text="")
        if ok_pressed:
            self._path_recording_name = path_name
            try:
                self._path_file = open(self._get_path_filename(), 'a')
                self._path_recording = True
                self._path_last_loc = None
            except Exception as e:
                print("Failed to open pathfile: %s" % e)

    def rename_path_recording(self, new_name=None):
        print("Rename recording!")
        if not self._path_recording:
            return

        if new_name:
            path_name = new_name
            ok_pressed = True
        else:
            path_name, ok_pressed = QInputDialog.getText(
                self,  # parent
                "Rename Path",  # title
                "New path name:",  # label
                echo=QLineEdit.EchoMode.Normal,
                text=self._path_recording_name)

        if ok_pressed:
            old_path_name = self._path_recording_name
            new_path_name = path_name
            try:
                self._path_file.close()
                self._path_file = None
            except Exception as e:
                print("Failed to close path recording file: %s" % e)
                return
            try:
                os.rename(self._get_path_filename(custom_name=old_path_name),
                          self._get_path_filename(custom_name=new_path_name))
                self._path_recording_name = new_path_name
            except Exception as e:
                print("Failed to rename path recording file: %s" % e)
                self._path_recording = False
                return
            try:
                self._path_file = open(self._get_path_filename(), 'a')
            except Exception as e:
                print("Failed to open renamed path recording file: %s" % e)
                self._path_recording = False
                return

    def stop_path_recording(self):
        print("Stop recording!")
        if not self._path_recording:
            return

        if self._path_last_loc is not None:
            print("Recording final path point.")
            self.record_path_point(
                self._path_last_loc, "%s (end)" % self._path_recording_name)

        try:
            self._path_file.close()
        except Exception as e:
            print("Failed to stop recording: %s" % e)
            return
        self._path_file = None
        self._path_recording = False
        self._path_last_loc = None

    def record_path_loc(self, loc):
        if not self._path_recording:
            return

        print("Recording loc: %s" % str(loc))
        if self._path_last_loc is None:
            print("Recording first path point.")
            self.record_path_point(
                loc, "%s (start)" % self._path_recording_name)
        else:
            line = (
                "L {x1}, {y1}, {z1}, {x2}, {y2}, {z2}, {r}, {g}, {b}\n".format(
                    x1=self._path_last_loc[0],
                    y1=self._path_last_loc[1],
                    z1=self._path_last_loc[2],
                    x2=loc[0], y2=loc[1], z2=loc[2],
                    r=255, g=0, b=0
                ))
            try:
                self._path_file.write(line)
                self._path_file.flush()
            except Exception as e:
                print("Failed to write loc to pathfile: %s" % e)

            # Also add line to the active map
            z_group = self._data.get_closest_z_group(loc[2])
            color = MapData.color_transform(QColor(255, 0, 0))
            map_line = QGraphicsPathItem()
            map_line.setPen(
                QPen(color, config.data['maps']['line_width']))
            map_path = map_line.path()
            map_path.moveTo(self._path_last_loc[0], self._path_last_loc[1])
            map_path.lineTo(loc[0], loc[1])
            map_line.setPath(map_path)
            self._data[z_group]['paths'].addToGroup(map_line)
            self.update_()

        # Update past loc to current loc
        self._path_last_loc = loc

    def record_path_point(self, loc, desc):
        if not self._path_recording:
            return
        point = "P {x}, {y}, {z}, {r}, {g}, {b}, {size}, {desc}\n".format(
            x=loc[0], y=loc[1], z=loc[2],
            r=255, g=0, b=0,
            size=3, desc=desc
        )
        try:
            self._path_file.write(point)
            self._path_file.flush()
        except Exception as e:
            print("Failed to write point to pathfile: %s" % e)

        # Also add point to the active map
        z_group = self._data.get_closest_z_group(loc[2])
        color = MapData.color_transform(QColor(255, 0, 0))
        map_poi = MapPoint(
            x=loc[0], y=loc[1], z=loc[2],
            color=color, size=3, text=desc)
        self._data[z_group]['poi'].append(
            PointOfInterest(location=map_poi))
        self._draw()
        self.update_()
