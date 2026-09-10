import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

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


def test_character_context_keeps_latest_aging_camp_snapshot_until_welcome():
    tracker = CharacterContextTracker()
    context, changed = tracker.store_you_spells_if_empty(
        "Alice", "Green", [
            {"name": "Spirit of Wolf", "seconds": 372},
            {"name": "", "seconds": 9},
            {"name": "Invalid", "seconds": -1},
        ])
    assert changed is True
    assert context.saved_you_spells[0]["name"] == "Spirit of Wolf"
    assert context.saved_you_spells[0]["seconds"] == 372
    assert context.saved_you_spells[0]["deadline"] > time.time()

    _context, changed = tracker.store_you_spells_if_empty(
        "Alice", "Green", [{"name": "Shielding", "seconds": 99}])
    assert changed is True
    _context, saved, changed = tracker.take_saved_you_spells(
        "Alice", "Green")
    assert changed is True
    assert saved[0]["name"] == "Shielding"
    assert saved[0]["seconds"] == 99
    assert saved[0]["deadline"] > time.time()
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
# First layout/tooltip rendering can exceed 35ms on a loaded Windows host.
# Keep the preparing state alive long enough to inspect it; still exercise
# actual timer completion and wait past the same deadline after cancellation.
app._camp_sessions.delay_ms = 1000
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
QTest.qWait(1100)
app.processEvents()

target = spells._spell_container.get_spell_target_by_name('__you__')
after_camp_names = sorted(
    widget.spell.name for widget in target.spell_widgets())
saved = config.data['general']['character_profiles'][
    'green|alice']['saved_you_spells']
mobile_after_camp = spells.mobile_snapshot()
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
mobile_after_welcome = spells.mobile_snapshot()
welcome_status_cleared = (
    spells._camp_state == '' and spells._title.text() == 'Spells')

maps._map.add_player('__you__', now, MapPoint(x=12, y=22, z=4))
app._parse((now, CAMP_PREPARING_LINE, 'Alice', 'Green'))
app._parse((now, CAMP_ABANDONED_LINE, 'Alice', 'Green'))
QTest.qWait(1100)
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
    'mobile_after_camp': mobile_after_camp,
    'location_cleared': location_cleared,
    'after_welcome_names': after_welcome_names,
    'restored_seconds': restored_seconds,
    'saved_after_welcome': saved_after_welcome,
    'mobile_after_welcome': mobile_after_welcome,
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
    assert result["mobile_after_camp"]["character"] == "Alice"
    assert result["mobile_after_camp"]["camp_state"] == "camped"
    assert [row["name"].casefold()
            for row in result["mobile_after_camp"]["timers"]] == [
        "spirit of wolf"]
    assert result["mobile_after_camp"]["timers"][0]["remaining_seconds"] > 0
    assert result["location_cleared"] is True
    assert result["after_welcome_names"] == ["shielding", "spirit of wolf"]
    assert 0 < result["restored_seconds"] <= result["saved"][0]["seconds"]
    assert result["saved_after_welcome"] == []
    assert result["mobile_after_welcome"]["camp_state"] == ""
    assert [row["name"].casefold()
            for row in result["mobile_after_welcome"]["timers"]] == [
        "spirit of wolf"]
    assert result["welcome_status_cleared"] is True
    assert result["after_abandon_names"] == ["shielding", "spirit of wolf"]
    assert result["location_after_abandon"] is True
    assert result["minimum"] == [65, 100]
    assert result["logical_surface"][0] == 260
    # The complete 25% replica keeps its full logical surface; shortening the
    # physical window does not clip or rearrange tracked buff rows.
    assert result["logical_surface"][1] == 400
