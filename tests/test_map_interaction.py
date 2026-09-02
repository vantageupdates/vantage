import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsView

from vantage.helpers import config
from vantage.parsers.maps.mapcanvas import MapCanvas
from vantage.parsers.maps.mapclasses import MapPoint, SpawnPoint
from vantage.parsers.maps.mapdata import MapData
from vantage.parsers.maps.window import detect_log_zone


def _app():
    return QApplication.instance() or QApplication([])


def test_zone_detection_accepts_zoning_who_and_status_lines():
    assert detect_log_zone("You have entered East Commonlands.") == (
        "east commonlands", "zoning")
    assert detect_log_zone("There are 12 players in Eastern Wastes.") == (
        "eastern wastelands", "who")
    assert detect_log_zone("There is 1 player in Kael Drakkal.") == (
        "kael drakkel", "who")
    assert detect_log_zone("Players in The Wakening Land:") == (
        "the wakening lands", "who")
    assert detect_log_zone("Current Zone: ecommons") == (
        "east commonlands", "status")


def test_zone_detection_rejects_generic_or_unknown_text():
    assert detect_log_zone("There are 250 players in EverQuest.") == (None, None)
    assert detect_log_zone("Bob tells you, 'meet me in East Commonlands'") == (
        None, None)
    assert MapData.resolve_zone_name("not a real p99 zone") is None


def test_map_uses_direct_pointer_drag_and_explains_controls():
    _app()
    config.data.setdefault("maps", {})["scale"] = 0.07
    canvas = MapCanvas()

    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    assert "Drag" in canvas.toolTip()
    assert "wheel" in canvas.toolTip()


def test_map_timers_are_draggable_restartable_and_expire_cleanly():
    _app()
    removed = []
    timer = SpawnPoint(
        location=MapPoint(x=1, y=2, z=0), length=60,
        name='camp timer', on_remove=removed.append)

    assert timer.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    assert timer.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
    assert 'drag' in timer.toolTip()
    timer.setPos(15, 25)
    assert (timer.location.x, timer.location.y) == (15, 25)
    timer.start()
    timer.stop()
    generation = timer._generation
    timer._remove_if_expired(generation)
    assert removed == [timer]
