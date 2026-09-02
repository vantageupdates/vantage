import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest

from vantage.helpers.camp_session import (
    CAMP_ABANDONED_LINE,
    CAMP_COMPLETION_DELAY_MS,
    CAMP_PREPARING_LINE,
    CampSessionController,
)
from vantage.helpers.character_context import CharacterContextTracker


ROOT = Path(__file__).resolve().parents[1]


def test_camp_controller_matches_exact_lines_cancels_and_separates_profiles():
    qt_app = QCoreApplication.instance() or QCoreApplication([])
    controller = CampSessionController(delay_ms=25)
    completed = []
    states = []
    controller.camp_completed.connect(
        lambda timestamp, character, server:
        completed.append((timestamp, character, server)))
    controller.state_changed.connect(
        lambda state, character, server:
        states.append((state, character, server)))

    assert controller.ingest(
        CAMP_PREPARING_LINE.lower(), 1, "Alice", "Green") == ""
    assert controller.pending_count == 0

    assert controller.ingest(
        CAMP_PREPARING_LINE, 2, "Alice", "Green") == "preparing"
    assert controller.ingest(
        CAMP_PREPARING_LINE, 3, "Bob", "Green") == "preparing"
    assert controller.pending_count == 2
    assert controller.ingest(
        CAMP_ABANDONED_LINE, 4, "Alice", "Green") == "abandoned"
    assert controller.pending_count == 1
    QTest.qWait(60)

    assert completed == [(3, "Bob", "Green")]
    assert states == [
        ("preparing", "Alice", "Green"),
        ("preparing", "Bob", "Green"),
        ("abandoned", "Alice", "Green"),
        ("camped", "Bob", "Green"),
    ]
    assert CAMP_COMPLETION_DELAY_MS == 6000
    assert qt_app is not None


def test_character_context_keeps_one_bounded_camp_snapshot_until_welcome():
    tracker = CharacterContextTracker()
    context, changed = tracker.store_you_spells_if_empty(
        "Alice", "Green", [
            {"name": "Spirit of Wolf", "seconds": 372},
            {"name": "", "seconds": 9},
            {"name": "Invalid", "seconds": -1},
        ])
    assert changed is True
    assert context.saved_you_spells == [
        {"name": "Spirit of Wolf", "seconds": 372}]

    _context, changed = tracker.store_you_spells_if_empty(
        "Alice", "Green", [{"name": "Shielding", "seconds": 99}])
    assert changed is False
    _context, saved, changed = tracker.take_saved_you_spells(
        "Alice", "Green")
    assert changed is True
    assert saved == [{"name": "Spirit of Wolf", "seconds": 372}]
    assert tracker.snapshot()["green|alice"]["saved_you_spells"] == []


SCRIPT = r"""
import datetime
import json

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolTip

from vantage.helpers import config
from vantage.helpers.camp_session import (
    CAMP_ABANDONED_LINE, CAMP_PREPARING_LINE, WELCOME_LINE)
from vantage.parsers.maps.mapclasses import MapPoint
from vantage.parsers.spells import Spell
from vantage.helpers.application import VantageApp


def spell_named(spells, name):
    source = next(
        spell for key, spell in spells.spell_book.items()
        if key.casefold() == name.casefold())
    return Spell(**source.__dict__)


def panel_tooltip(panel, control):
    logical = control.mapTo(panel._surface, control.rect().center())
    scene = panel._scale_proxy.mapToScene(QPointF(logical))
    point = panel._scale_view.mapFromScene(scene)
    event = QHelpEvent(
        QEvent.Type.ToolTip, point,
        panel._scale_view.viewport().mapToGlobal(point))
    QToolTip.hideText()
    QApplication.sendEvent(panel._scale_view.viewport(), event)
    app.processEvents()
    return QToolTip.text()


app = VantageApp([])
app._camp_sessions.delay_ms = 35
spells = app._parsers_dict['spells']
maps = app._parsers_dict['maps']
if spells._collapsed:
    spells._set_collapsed(False)
now = datetime.datetime.now().replace(microsecond=0)
spells._spell_container.add_spell(
    spell_named(spells, 'Spirit of Wolf'), now, '__you__', 'Alice', 'Green')
spells._spell_container.add_spell(
    spell_named(spells, 'Shielding'), now, '__you__', 'Bob', 'Green')
maps._map.add_player('__you__', now, MapPoint(x=10, y=20, z=3))

app._parse((now, CAMP_PREPARING_LINE, 'Alice', 'Green'))
spells.resize(spells.minimumSize())
spells.show()
app.processEvents()
camp_status = spells.camp_status_widget()
preparing_tooltip = panel_tooltip(spells, camp_status)
preparing_expected = camp_status.toolTip()
preparing_text = camp_status.text()
QTest.qWait(60)
app.processEvents()

target = spells._spell_container.get_spell_target_by_name('__you__')
after_camp_names = sorted(
    widget.spell.name for widget in target.spell_widgets())
saved = config.data['general']['character_profiles'][
    'green|alice']['saved_you_spells']
camped_text = spells._title.text()
location_cleared = '__you__' not in maps._map._data.players

app._parse((now + datetime.timedelta(seconds=7), WELCOME_LINE,
            'Alice', 'Green'))
app.processEvents()
target = spells._spell_container.get_spell_target_by_name('__you__')
after_welcome_names = sorted(
    widget.spell.name for widget in target.spell_widgets())
restored = next(
    widget for widget in target.spell_widgets()
    if widget.runtime_character == 'Alice')
restored_seconds = round(
    (restored.end_time - datetime.datetime.now()).total_seconds())
saved_after_welcome = config.data['general']['character_profiles'][
    'green|alice']['saved_you_spells']
welcome_status_cleared = (
    spells._camp_state == '' and spells._title.text() == 'Spells')

maps._map.add_player('__you__', now, MapPoint(x=12, y=22, z=4))
app._parse((now, CAMP_PREPARING_LINE, 'Alice', 'Green'))
app._parse((now, CAMP_ABANDONED_LINE, 'Alice', 'Green'))
QTest.qWait(60)
app.processEvents()
target = spells._spell_container.get_spell_target_by_name('__you__')
after_abandon_names = sorted(
    widget.spell.name for widget in target.spell_widgets())

print(json.dumps({
    'preparing_text': preparing_text,
    'preparing_tooltip': preparing_tooltip,
    'preparing_expected': preparing_expected,
    'camped_text': camped_text,
    'after_camp_names': after_camp_names,
    'saved': saved,
    'location_cleared': location_cleared,
    'after_welcome_names': after_welcome_names,
    'restored_seconds': restored_seconds,
    'saved_after_welcome': saved_after_welcome,
    'welcome_status_cleared': welcome_status_cleared,
    'after_abandon_names': after_abandon_names,
    'location_after_abandon': '__you__' in maps._map._data.players,
    'minimum': [spells.width(), spells.height()],
    'logical_surface': [spells._surface.width(), spells._surface.height()],
}))

spells.close()
app.quit()
"""


def test_camp_cycle_preserves_restores_and_clears_only_the_active_profile(
        tmp_path):
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["VANTAGE_DATA_DIR"] = str(tmp_path / "profile")
    completed = subprocess.run(
        [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["preparing_text"] == "You · CAMP 6s"
    assert result["preparing_tooltip"] == result["preparing_expected"]
    assert result["camped_text"] == "Spells · CAMPED"
    assert result["after_camp_names"] == ["shielding"]
    assert result["saved"][0]["name"] == "spirit of wolf"
    assert result["saved"][0]["seconds"] > 0
    assert result["location_cleared"] is True
    assert result["after_welcome_names"] == ["shielding", "spirit of wolf"]
    assert 0 < result["restored_seconds"] <= result["saved"][0]["seconds"]
    assert result["saved_after_welcome"] == []
    assert result["welcome_status_cleared"] is True
    assert result["after_abandon_names"] == ["shielding", "spirit of wolf"]
    assert result["location_after_abandon"] is True
    assert result["minimum"] == [72, 111]
    assert result["logical_surface"][0] == 260
    assert 399 <= result["logical_surface"][1] <= 401
